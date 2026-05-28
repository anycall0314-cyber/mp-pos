"""維修單業務邏輯。"""
from decimal import Decimal

from django.db import transaction

from apps.catalog.models import Product
from apps.inventory.models import StockBalance, StockMovement

from .models import RepairOrder, RepairOrderPart


def compute_in_house_quote(repair_order: RepairOrder) -> Decimal:
    """自修建議報價 = 領用零件成本合計 + 工資。"""
    parts_cost = sum(
        (p.qty * (p.part_product.weighted_avg_cost or Decimal("0")))
        for p in repair_order.parts.select_related("part_product").all()
    )
    return Decimal(parts_cost) + (repair_order.labor_fee or Decimal("0"))


def _parts_cost(repair_order: RepairOrder) -> Decimal:
    """合計這張單已領用零件的成本(用各 line 的 unit_cost,未填則用 product 加權平均)。"""
    total = Decimal("0")
    for p in repair_order.parts.select_related("part_product").all():
        unit = p.unit_cost or (p.part_product.weighted_avg_cost or Decimal("0"))
        total += Decimal(unit) * p.qty
    return total


def compute_personal_margin(repair_order: RepairOrder) -> dict:
    """個人毛利分解 — 拆給 sales_person(收件)與 technician(技師)。

    公式表:
    - 自修(technician 空或 = sales_person):全歸 sales_person
        sales_person 毛利 = 客戶實付 − 零件成本
    - 自修(technician ≠ sales_person):
        sales_person 毛利 = 客戶實付 − 工資 − 零件成本
        technician     毛利 = 工資
    - 委外給外廠(technician 空):
        sales_person 毛利 = 客戶實付 − 委外實際費用
    - 內部轉單(technician 不空 且 mode=external):
        sales_person 毛利 = 客戶實付 − internal_settle_amount
        technician     毛利 = internal_settle_amount − 零件成本

    回傳 dict:{ sales_person_id: Decimal, technician_id: Decimal,
                sales_person_amount, technician_amount,
                kind: "in_house_solo" | "in_house_split" |
                      "external_vendor" | "internal_transfer" }
    """
    paid = repair_order.customer_paid_amount or Decimal("0")
    parts_cost = _parts_cost(repair_order)
    labor = repair_order.labor_fee or Decimal("0")
    settle = repair_order.internal_settle_amount or Decimal("0")
    ext_actual = repair_order.external_quote_actual or Decimal("0")

    sp_id = repair_order.sales_person_id
    tech_id = repair_order.technician_id
    same_person = (not tech_id) or tech_id == sp_id

    if repair_order.mode == RepairOrder.Mode.IN_HOUSE:
        if same_person:
            return {
                "kind": "in_house_solo",
                "sales_person_id": sp_id,
                "sales_person_amount": paid - parts_cost,
                "technician_id": None,
                "technician_amount": Decimal("0"),
            }
        return {
            "kind": "in_house_split",
            "sales_person_id": sp_id,
            "sales_person_amount": paid - labor - parts_cost,
            "technician_id": tech_id,
            "technician_amount": labor,
        }

    # mode == external
    if tech_id and tech_id != sp_id:
        # 內部轉單
        return {
            "kind": "internal_transfer",
            "sales_person_id": sp_id,
            "sales_person_amount": paid - settle,
            "technician_id": tech_id,
            "technician_amount": settle - parts_cost,
        }
    # 委外給外廠
    return {
        "kind": "external_vendor",
        "sales_person_id": sp_id,
        "sales_person_amount": paid - ext_actual,
        "technician_id": None,
        "technician_amount": Decimal("0"),
    }


def compute_margin(repair_order: RepairOrder) -> Decimal:
    """完工毛利。
    自修:客戶實付 - 零件成本合計 - 工資
    委外:客戶實付 - 委外實際費用
    """
    paid = repair_order.customer_paid_amount or Decimal("0")
    if repair_order.mode == RepairOrder.Mode.EXTERNAL:
        return paid - (repair_order.external_quote_actual or Decimal("0"))
    parts_cost = sum(
        (p.qty * (p.unit_cost or Decimal("0")))
        for p in repair_order.parts.all()
    )
    labor = repair_order.labor_fee or Decimal("0")
    return paid - Decimal(parts_cost) - labor


@transaction.atomic
def complete_repair_order(repair_order: RepairOrder) -> None:
    """維修單轉「完成」狀態:扣零件倉庫存 + 寫 StockMovement。

    商品倉的序號商品不在此扣;只扣零件倉的批量庫存(StockBalance)。
    """
    if repair_order.status == RepairOrder.Status.COMPLETED:
        return  # 已完工的不重扣

    tenant = repair_order.tenant
    wh = repair_order.warehouse

    # 自修:依 RepairOrderPart 扣零件倉庫存
    if repair_order.mode == RepairOrder.Mode.IN_HOUSE:
        for line in repair_order.parts.select_related("part_product").all():
            part = line.part_product
            # snapshot 當下成本(若未填過)
            if not line.unit_cost:
                line.unit_cost = part.weighted_avg_cost or Decimal("0")
                line.save(update_fields=["unit_cost"])
            # 扣 StockBalance
            balance, _ = StockBalance.objects.get_or_create(
                tenant=tenant,
                product=part,
                warehouse=wh,
                defaults={"qty": 0},
            )
            balance.qty = max(balance.qty - line.qty, 0)
            balance.save(update_fields=["qty"])
            # 寫異動
            StockMovement.objects.create(
                tenant=tenant,
                product=part,
                qty=line.qty,
                movement_type=StockMovement.MovementType.REPAIR_USAGE,
                from_warehouse=wh,
                ref_doc_type="repair_order",
                ref_doc_id=repair_order.id,
                note=f"{repair_order.no} 維修領用",
            )

    # 自修毛利重算 suggested_quote(完工時 snapshot 當下成本)
    if repair_order.mode == RepairOrder.Mode.IN_HOUSE:
        repair_order.suggested_quote = compute_in_house_quote(repair_order)

    repair_order.status = RepairOrder.Status.COMPLETED
    from django.utils import timezone

    repair_order.completed_at = timezone.now()
    repair_order.save(
        update_fields=["status", "completed_at", "suggested_quote"]
    )


@transaction.atomic
def reopen_repair_order(repair_order: RepairOrder) -> None:
    """重開已完成的維修單:歸還零件庫存 + 清完工時間 + 狀態退回待取件。

    僅在 status=completed 時有效;呼叫端負責權限檢查。
    回退邏輯與 complete_repair_order 對稱:
    - 自修:每筆 RepairOrderPart 把 qty 加回 StockBalance,寫 ADJUST 異動
    - 委外:無庫存異動,純改狀態
    """
    if repair_order.status != RepairOrder.Status.COMPLETED:
        return

    tenant = repair_order.tenant
    wh = repair_order.warehouse

    if repair_order.mode == RepairOrder.Mode.IN_HOUSE:
        for line in repair_order.parts.select_related("part_product").all():
            part = line.part_product
            balance, _ = StockBalance.objects.get_or_create(
                tenant=tenant,
                product=part,
                warehouse=wh,
                defaults={"qty": 0},
            )
            balance.qty = balance.qty + line.qty
            balance.save(update_fields=["qty"])
            StockMovement.objects.create(
                tenant=tenant,
                product=part,
                qty=line.qty,
                movement_type=StockMovement.MovementType.ADJUST,
                to_warehouse=wh,
                ref_doc_type="repair_order_reopen",
                ref_doc_id=repair_order.id,
                note=f"{repair_order.no} 重開維修單,歸還零件",
            )

    repair_order.status = RepairOrder.Status.READY_PICKUP
    repair_order.completed_at = None
    repair_order.save(update_fields=["status", "completed_at"])


def parts_with_insufficient_stock(
    repair_order: RepairOrder,
) -> list[dict]:
    """檢查維修單目前領用零件是否有缺料,回傳缺料清單供前端警示。"""
    out: list[dict] = []
    tenant = repair_order.tenant
    wh = repair_order.warehouse
    for line in repair_order.parts.select_related("part_product").all():
        part = line.part_product
        bal = (
            StockBalance.objects.filter(
                tenant=tenant, product=part, warehouse=wh
            )
            .values_list("qty", flat=True)
            .first()
            or 0
        )
        if bal < line.qty:
            out.append(
                {
                    "part_id": part.id,
                    "part_name": part.name,
                    "needed": line.qty,
                    "available": bal,
                    "short_by": line.qty - bal,
                }
            )
    return out
