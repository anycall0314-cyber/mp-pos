"""進貨單建單即生效的業務副作用。

由 ViewSet.perform_create 於儲存後同一個 transaction 內呼叫。
1. 驗證明細的 serial_numbers 數量 == qty(虛擬商品例外),且無重複、不與系統內既有序號衝突
2. 依課稅別計算單據 subtotal / tax_amount / total_cost
   - 應稅內含:unit_price 已含稅 → net = unit_price / 1.05
   - 應稅外加:unit_price 未稅 → 稅額外加
   - 免稅 / 零稅:無稅
3. 每筆明細記錄 unit_landed_cost(未稅落地成本)
4. 為實體商品建 ProductSerial(in_stock) + 寫 StockMovement
5. 更新 Product.weighted_avg_cost 使用「未稅成本」
   new_avg = (current_stock × current_avg + batch_net_total) / (current_stock + batch_qty)
"""
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.inventory.models import ProductSerial, StockBalance, StockMovement

from .models import PurchaseOrder, PurchaseOrderItem

CENTS = Decimal("0.01")
TAX_RATE = Decimal("0.05")


class PurchaseOrderError(Exception):
    """進貨業務錯誤;由 view 轉成 400 回應。"""


VALID_GRADES = set(ProductSerial.ConditionGrade.values)


def _normalize_serial_entry(raw):
    """把進貨序號項目正規化:接受純字串或 dict 形式。

    傳入:
        "IMEI123"  → {"sn": "IMEI123"}
        {"sn": "IMEI123", "grade": "A", "cost": "10000", ...}  → 原樣回傳(加 strip)
    """
    if isinstance(raw, dict):
        out = dict(raw)
        out["sn"] = str(out.get("sn", "")).strip()
        return out
    return {"sn": str(raw).strip()}


def _serial_cost(entry: dict, fallback_unit_price: Decimal) -> Decimal:
    """中古機每隻序號的進貨成本:有填用自己的,沒填用上方表格的單價當預設。"""
    raw = entry.get("cost")
    if raw in (None, "", 0, "0"):
        return Decimal(str(fallback_unit_price))
    try:
        return Decimal(str(raw))
    except Exception:
        return Decimal(str(fallback_unit_price))


def _validate_items(po: PurchaseOrder, items):
    if not items:
        raise PurchaseOrderError("無明細,無法過帳")

    all_serials = []
    for it in items:
        sn = it.serial_numbers
        if not isinstance(sn, list):
            raise PurchaseOrderError(f"第 {it.line_no} 行序號格式錯誤,應為陣列")
        if not it.product.requires_serial:
            if sn:
                raise PurchaseOrderError(
                    f"第 {it.line_no} 行商品「{it.product.name}」不追蹤序號,序號欄請留空"
                )
            continue
        normalized = [_normalize_serial_entry(s) for s in sn]
        if len(normalized) != it.qty:
            raise PurchaseOrderError(
                f"第 {it.line_no} 行序號數量({len(normalized)})不符進貨數量({it.qty})"
            )
        if any((not e["sn"]) for e in normalized):
            raise PurchaseOrderError(f"第 {it.line_no} 行有空白序號")
        only_sn = [e["sn"] for e in normalized]
        if len(set(only_sn)) != len(only_sn):
            raise PurchaseOrderError(f"第 {it.line_no} 行序號有重複")
        if it.product.is_secondhand:
            for e in normalized:
                grade = (e.get("grade") or "").strip()
                if grade and grade not in VALID_GRADES:
                    raise PurchaseOrderError(
                        f"第 {it.line_no} 行序號 {e['sn']} 成色等級「{grade}」無效"
                    )
        it.serial_numbers = normalized  # 寫回正規化結果,提交時使用
        all_serials.extend(only_sn)

    if len(set(all_serials)) != len(all_serials):
        raise PurchaseOrderError("整單序號內出現重複")

    existing = list(
        ProductSerial.objects.for_tenant(po.tenant)
        .filter(serial_no__in=all_serials)
        .values_list("serial_no", flat=True)
    )
    if existing:
        raise PurchaseOrderError(f"序號已存在於系統:{', '.join(existing[:5])}")


def _net_unit_price(unit_price: Decimal, tax_method: str) -> Decimal:
    """依課稅別把單價換算為未稅落地成本。"""
    if tax_method == PurchaseOrder.TaxMethod.TAXABLE_INCLUDED:
        return (unit_price / (Decimal("1") + TAX_RATE)).quantize(CENTS)
    # 應稅外加 / 免稅 / 零稅:單價即未稅
    return unit_price.quantize(CENTS)


def _calc_doc_tax(items, tax_method: str):
    """依課稅別把明細加總拆成 (subtotal_net, tax, total_gross)。
    使用 item.amount(已含贈品折算 + 中古機逐隻成本加總邏輯)。
    """
    gross_sum = sum((Decimal(it.amount) for it in items), Decimal("0"))
    if tax_method == PurchaseOrder.TaxMethod.TAXABLE_INCLUDED:
        total = gross_sum.quantize(CENTS)
        subtotal = (gross_sum / (Decimal("1") + TAX_RATE)).quantize(CENTS)
        tax = (total - subtotal).quantize(CENTS)
        return subtotal, tax, total
    if tax_method == PurchaseOrder.TaxMethod.TAXABLE_EXCLUDED:
        subtotal = gross_sum.quantize(CENTS)
        tax = (gross_sum * TAX_RATE).quantize(CENTS)
        total = (subtotal + tax).quantize(CENTS)
        return subtotal, tax, total
    # tax_free / zero_tax
    subtotal = gross_sum.quantize(CENTS)
    return subtotal, Decimal("0.00"), subtotal


def commit_purchase_order(po: PurchaseOrder) -> PurchaseOrder:
    """進貨單儲存即觸發,寫所有業務副作用。"""
    items = list(po.items.select_related("product").all())
    _validate_items(po, items)

    with transaction.atomic():
        # 1. 每筆明細:
        #    - billed_qty 未填 → 預設等於 qty
        #    - 一般商品:amount = billed_qty × unit_price(贈品不計價),
        #      unit_landed_cost = (未稅 billed_amount) / qty
        #    - 中古機(is_secondhand):每隻序號可帶自己的 cost,
        #      amount = sum(每隻 cost,空值 fallback 為 unit_price),
        #      unit_landed_cost = 未稅 amount / qty(僅供加權平均報表參考)
        for it in items:
            if not it.billed_qty:
                it.billed_qty = it.qty
            billed_dec = Decimal(it.billed_qty)
            qty_dec = Decimal(it.qty)

            if it.product.is_secondhand and it.product.requires_serial:
                # 中古機:billed_qty 強制等於 qty(中古不分贈品)
                it.billed_qty = it.qty
                billed_dec = qty_dec
                entries = [_normalize_serial_entry(e) for e in it.serial_numbers]
                gross_sum = sum(
                    (_serial_cost(e, it.unit_price) for e in entries),
                    Decimal("0"),
                )
                it.amount = gross_sum.quantize(CENTS)
                if po.tax_method == PurchaseOrder.TaxMethod.TAXABLE_INCLUDED:
                    net_sum = (gross_sum / (Decimal("1") + TAX_RATE)).quantize(CENTS)
                else:
                    net_sum = gross_sum.quantize(CENTS)
                it.unit_landed_cost = (
                    (net_sum / qty_dec).quantize(CENTS)
                    if qty_dec > 0
                    else Decimal("0")
                )
            else:
                it.amount = (billed_dec * it.unit_price).quantize(CENTS)
                net_unit = _net_unit_price(it.unit_price, po.tax_method)
                net_billed_total = net_unit * billed_dec
                it.unit_landed_cost = (
                    (net_billed_total / qty_dec).quantize(CENTS)
                    if qty_dec > 0
                    else Decimal("0")
                )
            # 繞過 PurchaseOrderItem.save() 的 amount 自動重算
            # (中古機 amount 來自各序號 cost 加總,不是 billed_qty × unit_price)
            PurchaseOrderItem.objects.filter(pk=it.pk).update(
                billed_qty=it.billed_qty,
                amount=it.amount,
                unit_landed_cost=it.unit_landed_cost,
            )

        # 2. 為實體商品建序號 + 寫異動 + 更新加權平均(使用未稅成本)
        # - requires_serial=True:建 ProductSerial 並寫 StockMovement
        # - requires_serial=False 且 is_virtual=False(配件):更新 StockBalance
        #   per (product, warehouse) + 重算 Product.weighted_avg_cost(全域)
        # - is_virtual=True:不動庫存,只計入單頭金額(手續費 / 折抵 / 補成本等)
        now = timezone.now()
        for it in items:
            product = it.product
            if not product.requires_serial:
                if not product.is_virtual:
                    _update_balance_on_purchase(po, it, product)
                continue
            current_stock = (
                ProductSerial.objects.for_tenant(po.tenant)
                .filter(product=product, status=ProductSerial.Status.IN_STOCK)
                .count()
            )
            # unit_landed_cost 已含贈品稀釋;乘 qty 得本批未稅總成本
            batch_total_net = it.unit_landed_cost * Decimal(it.qty)
            new_total_qty = current_stock + it.qty
            if new_total_qty > 0:
                old_value = Decimal(current_stock) * product.weighted_avg_cost
                product.weighted_avg_cost = (
                    (old_value + batch_total_net) / Decimal(new_total_qty)
                ).quantize(CENTS)
            product.save(update_fields=["weighted_avg_cost"])

            for entry in it.serial_numbers:
                entry = _normalize_serial_entry(entry)
                extra = {}
                serial_cost_net = it.unit_landed_cost  # 預設用線平均(非中古機)
                if product.is_secondhand:
                    grade = (entry.get("grade") or "").strip()
                    if grade:
                        extra["condition_grade"] = grade
                    if entry.get("price") not in (None, "", 0, "0"):
                        try:
                            extra["custom_unit_price"] = Decimal(
                                str(entry["price"])
                            )
                        except Exception:
                            pass
                    if entry.get("battery") not in (None, ""):
                        try:
                            bh = int(entry["battery"])
                            if 0 <= bh <= 100:
                                extra["battery_health"] = bh
                        except Exception:
                            pass
                    note_value = (entry.get("note") or "").strip()
                    if note_value:
                        extra["condition_note"] = note_value
                    # 中古機:每隻獨立成本(沒填用線單價 fallback),轉成未稅
                    gross = _serial_cost(entry, it.unit_price)
                    if po.tax_method == PurchaseOrder.TaxMethod.TAXABLE_INCLUDED:
                        serial_cost_net = (
                            gross / (Decimal("1") + TAX_RATE)
                        ).quantize(CENTS)
                    else:
                        serial_cost_net = gross.quantize(CENTS)
                serial = ProductSerial.objects.create(
                    tenant=po.tenant,
                    product=product,
                    serial_no=entry["sn"],
                    warehouse=po.warehouse,
                    status=ProductSerial.Status.IN_STOCK,
                    purchase_unit_cost=serial_cost_net,
                    purchase_order_item=it,
                    received_at=now,
                    **extra,
                )
                StockMovement.objects.create(
                    tenant=po.tenant,
                    serial=serial,
                    movement_type=StockMovement.MovementType.PURCHASE_IN,
                    to_warehouse=po.warehouse,
                    ref_doc_type="purchase_order",
                    ref_doc_id=po.id,
                    note=f"進貨單 {po.no} 第 {it.line_no} 行",
                )

        # 3. 更新單頭金額
        subtotal, tax_amount, total = _calc_doc_tax(items, po.tax_method)
        po.subtotal = subtotal
        po.tax_amount = tax_amount
        po.total_cost = total
        po.save(update_fields=["subtotal", "tax_amount", "total_cost"])

    return po


def _update_balance_on_purchase(po, it, product):
    """配件進貨:把該倉的 StockBalance 加上去並重算加權平均。
    同時重算 Product.weighted_avg_cost(跨倉聚合,供報表)。
    """
    balance, _ = StockBalance.objects.get_or_create(
        tenant=po.tenant,
        product=product,
        warehouse=po.warehouse,
    )
    batch_net_total = it.unit_landed_cost * Decimal(it.qty)
    new_qty = balance.qty + it.qty
    if new_qty > 0:
        old_value = Decimal(balance.qty) * balance.weighted_avg_cost
        balance.weighted_avg_cost = (
            (old_value + batch_net_total) / Decimal(new_qty)
        ).quantize(CENTS)
    balance.qty = new_qty
    balance.save(update_fields=["qty", "weighted_avg_cost"])
    StockMovement.objects.create(
        tenant=po.tenant,
        product=product,
        qty=it.qty,
        movement_type=StockMovement.MovementType.PURCHASE_IN,
        to_warehouse=po.warehouse,
        ref_doc_type="purchase_order",
        ref_doc_id=po.id,
        note=f"進貨單 {po.no} 第 {it.line_no} 行 {product.sku} ×{it.qty}",
    )
    _recompute_product_avg_cost(po.tenant, product)


def _recompute_product_avg_cost(tenant, product):
    """跨倉聚合 Product.weighted_avg_cost。
    序號商品:用所有 in_stock 序號成本平均
    配件:用所有 StockBalance(qty>0)的加權平均
    """
    if product.requires_serial:
        _recompute_weighted_avg_cost(tenant, product)
        return
    balances = StockBalance.objects.filter(
        tenant=tenant, product=product, qty__gt=0
    )
    total_qty = 0
    total_value = Decimal("0")
    for b in balances:
        total_qty += b.qty
        total_value += Decimal(b.qty) * b.weighted_avg_cost
    product.weighted_avg_cost = (
        (total_value / Decimal(total_qty)).quantize(CENTS)
        if total_qty > 0
        else Decimal("0")
    )
    product.save(update_fields=["weighted_avg_cost"])


def _recompute_weighted_avg_cost(tenant, product):
    """以該商品目前 in_stock 序號的 purchase_unit_cost 重算加權平均。"""
    serials = ProductSerial.objects.for_tenant(tenant).filter(
        product=product, status=ProductSerial.Status.IN_STOCK
    )
    n = serials.count()
    if n == 0:
        product.weighted_avg_cost = Decimal("0")
    else:
        total = sum(
            (s.purchase_unit_cost for s in serials), Decimal("0")
        )
        product.weighted_avg_cost = (total / Decimal(n)).quantize(CENTS)
    product.save(update_fields=["weighted_avg_cost"])


def void_purchase_order(po: PurchaseOrder) -> PurchaseOrder:
    """整單作廢:
    - 序號商品:該單建的序號全須仍 in_stock 才能作廢
    - 配件:該倉 StockBalance 數量需 >= 本單進量(賣掉/調走的不能還回去)
    """
    if po.is_void:
        raise PurchaseOrderError("此單已作廢")

    items = list(po.items.select_related("product").all())
    serials_qs = ProductSerial.objects.for_tenant(po.tenant).filter(
        purchase_order_item__in=items
    )
    not_in_stock = serials_qs.exclude(status=ProductSerial.Status.IN_STOCK)
    if not_in_stock.exists():
        sample = list(not_in_stock.values_list("serial_no", flat=True)[:3])
        raise PurchaseOrderError(
            f"序號已動用,無法作廢:{', '.join(sample)}"
        )

    # 預先驗證配件庫存夠不夠扣
    for it in items:
        product = it.product
        if product.requires_serial or product.is_virtual:
            continue
        balance = StockBalance.objects.filter(
            tenant=po.tenant, product=product, warehouse=po.warehouse
        ).first()
        if not balance or balance.qty < it.qty:
            current = balance.qty if balance else 0
            raise PurchaseOrderError(
                f"商品 {product.sku} 在 {po.warehouse.code} 現有 {current},"
                f"無法回退本單的 {it.qty} 件(部分已售出/調撥)"
            )

    with transaction.atomic():
        affected_product_ids = set()
        for s in serials_qs:
            affected_product_ids.add(s.product_id)
            s.status = ProductSerial.Status.VOID
            s.warehouse = None
            s.save(update_fields=["status", "warehouse"])
            StockMovement.objects.create(
                tenant=po.tenant,
                serial=s,
                movement_type=StockMovement.MovementType.VOID,
                from_warehouse=po.warehouse,
                ref_doc_type="purchase_order",
                ref_doc_id=po.id,
                note=f"進貨單 {po.no} 作廢",
            )

        # 配件:從本倉 balance 扣掉本單進貨量
        for it in items:
            product = it.product
            if product.requires_serial or product.is_virtual:
                continue
            affected_product_ids.add(product.id)
            balance = StockBalance.objects.get(
                tenant=po.tenant, product=product, warehouse=po.warehouse
            )
            balance.qty -= it.qty
            if balance.qty == 0:
                balance.weighted_avg_cost = Decimal("0")
            balance.save(update_fields=["qty", "weighted_avg_cost"])
            StockMovement.objects.create(
                tenant=po.tenant,
                product=product,
                qty=it.qty,
                movement_type=StockMovement.MovementType.VOID,
                from_warehouse=po.warehouse,
                ref_doc_type="purchase_order",
                ref_doc_id=po.id,
                note=f"進貨單 {po.no} 作廢 {product.sku} ×{it.qty}",
            )

        # 重算加權平均(受影響商品)
        from apps.catalog.models import Product

        for pid in affected_product_ids:
            product = Product.objects.get(pk=pid)
            _recompute_product_avg_cost(po.tenant, product)

        po.is_void = True
        po.save(update_fields=["is_void"])

    return po
