"""銷貨儲存即生效 service。

1. 驗證每筆明細的 serials(多支):屬於該 product、status=in_stock、warehouse=銷貨倉
2. 整單序號不重複
3. 算 subtotal / tax_amount / total(依 tax_method)
4. 寫每筆 item.amount + cost_at_post
   - cost_at_post = sum 各 serial 的 purchase_unit_cost(實體);虛擬 = 0
5. 序號狀態 → sold,sold_at=now
6. 寫 StockMovement(SALE_OUT)
7. SIM 卡 → issued
"""
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.inventory.models import ProductSerial, StockMovement
from apps.parties.models import SimCard, TelecomPlan
from apps.tenants.services import InvoiceTrackError, assign_invoice_no

from .models import SalesOrder

CENTS = Decimal("0.01")
TAX_RATE = Decimal("0.05")


class SalesOrderError(Exception):
    """銷貨業務錯誤;由 view 轉成 400 回應。"""


def _validate_items(so: SalesOrder, items):
    if not items:
        raise SalesOrderError("無明細,無法過帳")

    all_serial_ids = []
    for it in items:
        product = it.product
        item_serials = list(it.serials.select_related("serial").all())
        serial_ids = [s.serial_id for s in item_serials]

        if product.is_virtual:
            if item_serials:
                raise SalesOrderError(
                    f"第 {it.line_no} 行虛擬商品 {product.sku} 不可指定序號"
                )
        elif product.requires_serial:
            if len(item_serials) != it.qty:
                raise SalesOrderError(
                    f"第 {it.line_no} 行需 {it.qty} 個序號,目前有 {len(item_serials)} 個"
                )
            for sos in item_serials:
                serial = sos.serial
                if serial.product_id != it.product_id:
                    raise SalesOrderError(
                        f"第 {it.line_no} 行序號 {serial.serial_no} 不屬於商品 {product.sku}"
                    )
                if serial.status != ProductSerial.Status.IN_STOCK:
                    raise SalesOrderError(
                        f"第 {it.line_no} 行序號 {serial.serial_no} 目前狀態為「{serial.get_status_display()}」,不可銷貨"
                    )
                if serial.warehouse_id != so.warehouse_id:
                    raise SalesOrderError(
                        f"第 {it.line_no} 行序號 {serial.serial_no} 不在銷貨倉內"
                    )
            if len(set(serial_ids)) != len(serial_ids):
                raise SalesOrderError(
                    f"第 {it.line_no} 行內序號重複"
                )
            all_serial_ids.extend(serial_ids)
        else:
            raise SalesOrderError(
                f"第 {it.line_no} 行商品 {product.sku} 不追序號的實體商品 MVP 未支援"
            )

        # 屬性限制
        has_telecom = bool(
            it.sim_card_id or it.msisdn or it.telecom_plan_id or it.activation_date
        )
        if has_telecom and not product.allows_telecom_line:
            raise SalesOrderError(
                f"第 {it.line_no} 行商品 {product.sku} 不可填寫電信欄位"
                f"(SIM 卡 / 門號 / 方案 / 上線日)"
            )
        if it.commission and it.commission > 0 and not product.allows_commission:
            raise SalesOrderError(
                f"第 {it.line_no} 行商品 {product.sku} 不可填寫佣金"
            )

        plan = it.telecom_plan
        if plan:
            requires_card = plan.kind in (
                TelecomPlan.Kind.NEW,
                TelecomPlan.Kind.PORTIN,
            )
            if requires_card and not it.sim_card_id:
                raise SalesOrderError(
                    f"第 {it.line_no} 行方案 {plan.code} ({plan.get_kind_display()})"
                    f"須指定 SIM 卡"
                )
            if not requires_card and it.sim_card_id:
                raise SalesOrderError(
                    f"第 {it.line_no} 行方案 {plan.code} ({plan.get_kind_display()})"
                    f"不需指定 SIM 卡"
                )
        elif it.sim_card_id:
            raise SalesOrderError(f"第 {it.line_no} 行有指定 SIM 卡但未選方案")

        if it.sim_card_id:
            card = it.sim_card
            if plan and card.vendor_id != plan.carrier_id:
                raise SalesOrderError(
                    f"第 {it.line_no} 行卡片 {card.card_no} 不屬於方案"
                    f" {plan.code} 的廠商"
                )
            if card.status != SimCard.Status.IN_STOCK:
                raise SalesOrderError(
                    f"第 {it.line_no} 行卡片 {card.card_no} 狀態為"
                    f"「{card.get_status_display()}」,不可出卡"
                )

    if len(set(all_serial_ids)) != len(all_serial_ids):
        raise SalesOrderError("整單序號重複")

    sim_ids = [it.sim_card_id for it in items if it.sim_card_id]
    if len(set(sim_ids)) != len(sim_ids):
        raise SalesOrderError("整單卡片重複")


def _calc_tax(subtotal_raw: Decimal, tax_method: str):
    if tax_method == SalesOrder.TaxMethod.TAXABLE_INCLUDED:
        total = subtotal_raw.quantize(CENTS)
        subtotal = (subtotal_raw / (Decimal("1") + TAX_RATE)).quantize(CENTS)
        tax = (total - subtotal).quantize(CENTS)
        return subtotal, tax, total
    if tax_method == SalesOrder.TaxMethod.TAXABLE_EXCLUDED:
        subtotal = subtotal_raw.quantize(CENTS)
        tax = (subtotal_raw * TAX_RATE).quantize(CENTS)
        total = (subtotal + tax).quantize(CENTS)
        return subtotal, tax, total
    subtotal = subtotal_raw.quantize(CENTS)
    return subtotal, Decimal("0.00"), subtotal


def _validate_payments(so: SalesOrder, total: Decimal):
    """付款總額需等於含稅總額;若 total = 0(全免費贈送)允許無付款。"""
    payments = list(so.payments.all())
    paid = sum((p.amount for p in payments), Decimal("0")).quantize(CENTS)
    target = total.quantize(CENTS)
    if target == 0:
        if paid != 0:
            raise SalesOrderError(
                f"總額為 0,付款金額應為 0(目前 {paid})"
            )
        return
    if not payments:
        raise SalesOrderError("結帳尚未指定付款方式")
    if paid != target:
        raise SalesOrderError(
            f"付款金額 {paid} 與含稅總額 {target} 不一致"
        )


def commit_sales_order(so: SalesOrder) -> SalesOrder:
    """銷貨單儲存即觸發。"""
    items = list(
        so.items.select_related("product")
        .prefetch_related("serials__serial")
        .all()
    )
    _validate_items(so, items)

    with transaction.atomic():
        now = timezone.now()
        subtotal_raw = Decimal("0")

        for it in items:
            product = it.product
            if not it.amount:
                it.amount = (Decimal(it.qty) * it.unit_price).quantize(CENTS)
            else:
                it.amount = it.amount.quantize(CENTS)

            # cost_at_post:虛擬 = 0;實體 = sum 各 serial 的 purchase_unit_cost
            if product.is_virtual:
                it.cost_at_post = Decimal("0")
            else:
                item_serials = list(it.serials.select_related("serial").all())
                it.cost_at_post = sum(
                    (sos.serial.purchase_unit_cost for sos in item_serials),
                    Decimal("0"),
                ).quantize(CENTS)
            it.save(update_fields=["amount", "cost_at_post"])
            subtotal_raw += it.amount

            # 序號狀態 → sold + 寫 StockMovement
            for sos in it.serials.select_related("serial").all():
                serial = sos.serial
                serial.status = ProductSerial.Status.SOLD
                serial.sold_at = now
                serial.warehouse = None
                serial.save(update_fields=["status", "sold_at", "warehouse"])

                StockMovement.objects.create(
                    tenant=so.tenant,
                    serial=serial,
                    movement_type=StockMovement.MovementType.SALE_OUT,
                    from_warehouse=so.warehouse,
                    ref_doc_type="sales_order",
                    ref_doc_id=so.id,
                    note=f"銷貨單 {so.no} 第 {it.line_no} 行",
                )

            if it.sim_card_id:
                card = it.sim_card
                card.status = SimCard.Status.ISSUED
                card.issued_at = now
                card.save(update_fields=["status", "issued_at"])

        subtotal, tax_amount, total = _calc_tax(subtotal_raw, so.tax_method)
        so.subtotal = subtotal
        so.tax_amount = tax_amount
        so.total = total

        # 驗證付款金額 sum == 含稅總額
        _validate_payments(so, total)

        # 發票自動取號:有指定發票類型 + 還沒帶號碼 → 從字軌取下一張
        update_fields = ["subtotal", "tax_amount", "total"]
        if so.invoice_form and so.invoice_form != "none" and not so.invoice_no:
            try:
                so.invoice_no = assign_invoice_no(so.tenant, so.invoice_form)
                update_fields.append("invoice_no")
                if not so.invoice_date:
                    so.invoice_date = timezone.now().date()
                    update_fields.append("invoice_date")
            except InvoiceTrackError as exc:
                raise SalesOrderError(str(exc))

        so.save(update_fields=update_fields)

    return so


def void_sales_order(so: SalesOrder) -> SalesOrder:
    """整單作廢:序號全部退回 in_stock、SIM 卡退回 in_stock。"""
    if so.is_void:
        raise SalesOrderError("此單已作廢")

    items = list(
        so.items.select_related("product", "sim_card")
        .prefetch_related("serials__serial")
        .all()
    )

    with transaction.atomic():
        for it in items:
            for sos in it.serials.select_related("serial").all():
                serial = sos.serial
                serial.status = ProductSerial.Status.IN_STOCK
                serial.warehouse = so.warehouse
                serial.sold_at = None
                serial.save(update_fields=["status", "warehouse", "sold_at"])
                StockMovement.objects.create(
                    tenant=so.tenant,
                    serial=serial,
                    movement_type=StockMovement.MovementType.RETURN_IN,
                    to_warehouse=so.warehouse,
                    ref_doc_type="sales_order",
                    ref_doc_id=so.id,
                    note=f"銷貨單 {so.no} 作廢",
                )
            if it.sim_card_id:
                card = it.sim_card
                card.status = SimCard.Status.IN_STOCK
                card.issued_at = None
                card.save(update_fields=["status", "issued_at"])

        so.is_void = True
        so.save(update_fields=["is_void"])

    return so
