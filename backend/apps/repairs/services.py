"""維修單業務邏輯。"""
from decimal import Decimal

from django.db import transaction

from apps.catalog.models import Product
from apps.core.money import round_money
from apps.core.tenant_fields import same_company
from apps.inventory.locking import lock_document, lock_stock_rows, locked_balance
from apps.inventory.models import StockBalance, StockMovement

from .models import RepairOrder, RepairOrderPart


def compute_in_house_quote(repair_order: RepairOrder) -> Decimal:
    """自修建議報價 = 領用零件成本合計 + 工資。"""
    parts_cost = sum(
        (p.qty * (p.part_product.weighted_avg_cost or Decimal("0")))
        for p in repair_order.parts.select_related("part_product").all()
    )
    # 零件成本是平均值、會有零頭;報價是金額,收成整數元
    return round_money(Decimal(parts_cost) + (repair_order.labor_fee or Decimal("0")))


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

    - 整個動作在一個交易內;先鎖這張維修單再看狀態(兩個人同時按完成只會扣一次料),
      再鎖要扣的庫存餘額(規則見 apps/inventory/locking.py)。
    - 缺料也能完工(帳上數量可能落後現場)。帳要對得起來:領用照實記全部數量,
      帳上不夠的差額另外記一筆「盤點調整」入庫(等於承認現場其實有這些料)。
      這樣庫存數量 = 異動加總,耗用報表的數字也是實際用掉的。
    """
    from django.utils import timezone

    with transaction.atomic():
        if lock_document(repair_order) is None:
            raise ValueError("找不到這張維修單")
        if repair_order.is_void:
            raise ValueError("此維修單已作廢,不能完工")
        if repair_order.status == RepairOrder.Status.COMPLETED:
            return  # 已完工的不重扣

        tenant = repair_order.tenant
        wh = repair_order.warehouse
        lines = list(repair_order.parts.select_related("part_product").order_by("id"))
        parts = [line.part_product for line in lines]
        if not same_company(tenant.pk, wh, repair_order.customer, repair_order.sales_person,
                            repair_order.technician, repair_order.repair_item,
                            repair_order.external_vendor, *lines, *parts):
            raise ValueError("維修單掛到的門市 / 客戶 / 人員 / 項目 / 廠商 / 零件不屬於這家公司")

        # 自修:依 RepairOrderPart 扣零件倉庫存
        if repair_order.mode == RepairOrder.Mode.IN_HOUSE:
            # 零件(商品)也鎖:成本快照要讀鎖到之後的加權平均(同一瞬間可能有進貨在改它)
            shared = {}
            for line in lines:
                line.part_product = shared.setdefault(line.part_product_id, line.part_product)
            lock_stock_rows(
                tenant, products=shared.values(),
                balances=[(part, wh) for part in shared.values()], create=True,
            )
            for line in lines:
                part = line.part_product
                # snapshot 當下成本(若未填過)
                if not line.unit_cost:
                    line.unit_cost = part.weighted_avg_cost or Decimal("0")
                    line.save(update_fields=["unit_cost"])
                balance = locked_balance(tenant, part, wh, create=True)
                short = line.qty - balance.qty
                if short > 0:
                    StockMovement.objects.create(
                        tenant=tenant,
                        product=part,
                        qty=short,
                        movement_type=StockMovement.MovementType.ADJUST,
                        to_warehouse=wh,
                        ref_doc_type="repair_order_shortage",
                        ref_doc_id=repair_order.id,
                        note=f"{repair_order.no} 維修領用時帳上不足,補差 {short}",
                    )
                    balance.qty += short
                balance.qty -= line.qty
                balance.save(update_fields=["qty"])
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
            repair_order.suggested_quote = compute_in_house_quote(repair_order)

        repair_order.status = RepairOrder.Status.COMPLETED
        repair_order.completed_at = timezone.now()
        repair_order.save(
            update_fields=["status", "completed_at", "suggested_quote"]
        )


def _outstanding_usage(repair_order: RepairOrder) -> dict:
    """這張維修單「領出去、還沒歸還」的零件:{(商品 id, 門市 id): 數量}。

    直接看異動紀錄(領用 − 先前重開時歸還的),不看單上現在寫的門市 / 零件 ——
    單上的資料之後可能被改過,歸還要還到當初實際領料的地方、還當初實際領的數量。
    """
    out = {}
    moves = StockMovement.objects.filter(tenant=repair_order.tenant, ref_doc_id=repair_order.id)
    for pid, wid, qty in moves.filter(
        ref_doc_type="repair_order", movement_type=StockMovement.MovementType.REPAIR_USAGE,
    ).values_list("product_id", "from_warehouse_id", "qty"):
        out[(pid, wid)] = out.get((pid, wid), 0) + qty
    for pid, wid, qty in moves.filter(
        ref_doc_type="repair_order_reopen", movement_type=StockMovement.MovementType.ADJUST,
    ).values_list("product_id", "to_warehouse_id", "qty"):
        out[(pid, wid)] = out.get((pid, wid), 0) - qty
    return {key: qty for key, qty in out.items() if qty > 0 and None not in key}


def reopen_repair_order(repair_order: RepairOrder) -> None:
    """重開已完成的維修單:歸還零件庫存 + 清完工時間 + 狀態退回待取件。

    僅在 status=completed 時有效;呼叫端負責權限檢查。
    歸還的是「當初實際領出去、還沒還」的零件(看異動紀錄,見 _outstanding_usage),
    還到當初領料的門市;委外單沒有領料,純改狀態。
    先鎖這張維修單再看狀態(兩個人同時按重開只會歸還一次),再鎖庫存餘額。
    """
    from apps.inventory.models import Warehouse

    with transaction.atomic():
        if lock_document(repair_order) is None:
            raise ValueError("找不到這張維修單")
        if repair_order.status != RepairOrder.Status.COMPLETED:
            return

        tenant = repair_order.tenant
        owed = _outstanding_usage(repair_order)
        products = {p.pk: p for p in Product.objects.filter(
            tenant=tenant, pk__in={pid for pid, _ in owed})}
        stores = {w.pk: w for w in Warehouse.objects.filter(
            tenant=tenant, pk__in={wid for _, wid in owed})}
        lock_stock_rows(
            tenant, balances=[(products[pid], stores[wid]) for pid, wid in owed], create=True
        )
        for (pid, wid), qty in sorted(owed.items()):
            part, wh = products[pid], stores[wid]
            balance = locked_balance(tenant, part, wh, create=True)
            balance.qty = balance.qty + qty
            balance.save(update_fields=["qty"])
            StockMovement.objects.create(
                tenant=tenant,
                product=part,
                qty=qty,
                movement_type=StockMovement.MovementType.ADJUST,
                to_warehouse=wh,
                ref_doc_type="repair_order_reopen",
                ref_doc_id=repair_order.id,
                note=f"{repair_order.no} 重開維修單,歸還零件",
            )

        repair_order.status = RepairOrder.Status.READY_PICKUP
        repair_order.completed_at = None
        repair_order.save(update_fields=["status", "completed_at"])


def set_repair_status(repair_order: RepairOrder, new_status: str) -> None:
    """切換進度(待處理 / 報價 / 維修中 / 送修 / 待取件)。完工走 complete、已完工要改回來走 reopen。
    鎖住單據之後才看狀態:不能把剛完工(已扣料)的單改回別的狀態,否則下次完工會再扣一次。"""
    with transaction.atomic():
        if lock_document(repair_order) is None:
            raise ValueError("找不到這張維修單")
        if repair_order.is_void:
            raise ValueError("此維修單已作廢")
        if repair_order.status == RepairOrder.Status.COMPLETED:
            raise ValueError("已完工的維修單要先重開才能改狀態")
        repair_order.status = new_status
        repair_order.save(update_fields=["status"])


def void_repair_order(repair_order: RepairOrder) -> None:
    """作廢。已完工(已扣料)的單要先重開把零件歸還,才能作廢。"""
    with transaction.atomic():
        if lock_document(repair_order) is None:
            raise ValueError("找不到這張維修單")
        if repair_order.is_void:
            raise ValueError("此維修單已作廢")
        if repair_order.status == RepairOrder.Status.COMPLETED:
            raise ValueError("已完工的維修單要先重開(歸還零件)才能作廢")
        repair_order.is_void = True
        repair_order.save(update_fields=["is_void"])


def ensure_editable(repair_order: RepairOrder) -> None:
    """修改維修單之前(交易內):鎖住並重讀;已完工 / 已作廢的不能改。
    已完工的單改了門市或零件,之後的庫存就對不回去。"""
    if lock_document(repair_order) is None:
        raise ValueError("找不到這張維修單")
    if repair_order.is_void:
        raise ValueError("此維修單已作廢,不能修改")
    if repair_order.status == RepairOrder.Status.COMPLETED:
        raise ValueError("已完工的維修單要先重開才能修改")


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
