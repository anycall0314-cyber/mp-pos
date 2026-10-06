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

from apps.core.money import round_money
from apps.core.tenant_fields import same_company
from apps.identity.normalize import normalize_serial
from apps.inventory.identifiers import (
    IdentifierError,
    create_serial,
    looks_like_imei,
    main_code,
    release_codes,
    split_codes,
    taken,
    twin_ids,
)
from apps.inventory.locking import lock_document, lock_stock_rows, locked_balance
from apps.inventory.models import ProductSerial, StockBalance, StockMovement

from .models import PurchaseOrder, PurchaseOrderItem

CENTS = Decimal("0.01")
TAX_RATE = Decimal("0.05")


class PurchaseOrderError(Exception):
    """進貨業務錯誤;由 view 轉成 400 回應。"""


VALID_GRADES = set(ProductSerial.ConditionGrade.values)


def _normalize_serial_entry(raw):
    """進貨的一台設備 → {"imei": …, "sn": …, 其他欄位照舊}。兩格可以都填,也可以只填一格。

    三種寫法:
        "356…"                              沒講是哪一種:像 IMEI(15 碼、檢查碼正確)放 IMEI,否則放 SN
        {"sn": "X", "grade": "A", …}        舊格式(沒有 imei 這個鍵):sn 就是「那個序號」,同上
        {"imei": "356…", "sn": "F2L…", …}   有 imei 這個鍵:照寫的放,不改判
    """
    if isinstance(raw, dict):
        out = dict(raw)
        explicit = "imei" in out
        imei = str(out.get("imei") or "").strip()
        sn = str(out.get("sn") or "").strip()
    else:
        out, explicit, imei, sn = {}, False, "", str(raw if raw is not None else "").strip()
    if not explicit and looks_like_imei(sn):
        imei, sn = sn, ""
    out["imei"], out["sn"] = imei, sn
    return out


def _entry_code(entry):
    """這一台的主碼(訊息與主序號用):有 IMEI 用 IMEI,沒有才用 SN。"""
    return main_code(entry["imei"], entry["sn"])


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
    if not same_company(po.tenant_id, po.supplier, po.warehouse, po.category, po.payment_method):
        raise PurchaseOrderError("供應商 / 門市 / 進貨類別 / 付款方式不屬於這家公司")
    for it in items:
        if not same_company(po.tenant_id, it, it.product):
            raise PurchaseOrderError(f"第 {it.line_no} 行的商品不屬於這家公司")

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
        codes = []
        for e in normalized:
            try:
                split_codes(e["imei"], e["sn"])
            except IdentifierError as exc:
                raise PurchaseOrderError(f"第 {it.line_no} 行:{exc}")
            codes += [c for c in (e["imei"], e["sn"]) if c]
        # IMEI 與 SN 一起比:同一個碼不能出現兩次(不管是哪一格)
        keys = [normalize_serial(c) for c in codes]
        if len(set(keys)) != len(keys):
            raise PurchaseOrderError(f"第 {it.line_no} 行序號有重複")
        for e in normalized:
            raw_grade = e.get("grade")
            if raw_grade in (None, ""):
                continue
            if not isinstance(raw_grade, str):
                raise PurchaseOrderError(
                    f"第 {it.line_no} 行序號 {_entry_code(e)} 成色等級格式錯誤,應為文字"
                )
            grade = raw_grade.strip()
            if grade and grade not in VALID_GRADES:
                raise PurchaseOrderError(
                    f"第 {it.line_no} 行序號 {_entry_code(e)} 成色等級「{grade}」無效"
                )
        it.serial_numbers = normalized  # 寫回正規化結果,提交時使用
        all_serials.extend(codes)

    all_keys = [normalize_serial(c) for c in all_serials]
    if len(set(all_keys)) != len(all_keys):
        raise PurchaseOrderError("整單序號內出現重複")

    # 已經被這家公司別台設備用掉的碼(IMEI、SN 都算)
    existing = taken(po.tenant, all_serials)
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
    # 單頭的三個數字一律整數元、四捨五入(跟廠商發票上的算法一樣;規則見 apps/core/money.py)
    gross_sum = sum((Decimal(it.amount) for it in items), Decimal("0"))
    if tax_method == PurchaseOrder.TaxMethod.TAXABLE_INCLUDED:
        total = round_money(gross_sum)
        subtotal = round_money(gross_sum / (Decimal("1") + TAX_RATE))
        tax = total - subtotal
        return subtotal, tax, total
    if tax_method == PurchaseOrder.TaxMethod.TAXABLE_EXCLUDED:
        subtotal = round_money(gross_sum)
        tax = round_money(gross_sum * TAX_RATE)
        total = subtotal + tax
        return subtotal, tax, total
    # tax_free / zero_tax
    subtotal = round_money(gross_sum)
    return subtotal, Decimal("0.00"), subtotal


def commit_purchase_order(po: PurchaseOrder) -> PurchaseOrder:
    """進貨單儲存即觸發,寫所有業務副作用。"""
    items = list(po.items.select_related("product", "product__condition").all())
    # 同一個商品出現在好幾行時共用同一個物件(加權平均成本一行一行往下算,不能各算各的)
    shared = {}
    for it in items:
        it.product = shared.setdefault(it.product_id, it.product)

    with transaction.atomic():
        # 先鎖再檢查、再改(規則見 apps/inventory/locking.py):這張單要改成本的商品、要加數量的庫存餘額
        lock_document(po)
        lock_stock_rows(
            po.tenant,
            products=[it.product for it in items if not it.product.is_virtual],
            balances=[(it.product, po.warehouse) for it in items
                      if not it.product.requires_serial and not it.product.is_virtual],
            create=True,
        )
        _validate_items(po, items)
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
                it.amount = round_money(gross_sum)
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
                it.amount = round_money(billed_dec * it.unit_price)
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

            # 「要不要逐台記機況」與「是不是中古機」是兩件事:
            #   - 逐台機況 / 電池 / 個別售價 / 備註 → 看 tracks_unit_condition
            #     (已拆封不是中古機,但一樣要逐台記,否則檢測資料會被丟掉)
            #   - 每隻獨立成本 → 仍只看 is_secondhand(成本政策不跟著放寬)
            tracks_unit = product.tracks_unit_condition
            for entry in it.serial_numbers:
                entry = _normalize_serial_entry(entry)
                extra = {}
                serial_cost_net = it.unit_landed_cost  # 預設用線平均(非中古機)
                if tracks_unit:
                    # grade 的型別已在 _validate_items 擋過;note 是自由欄位,
                    # 這裡用 str() 防 JSON 塞進非字串造成 AttributeError。
                    grade = str(entry.get("grade") or "").strip()
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
                    note_value = str(entry.get("note") or "").strip()
                    if note_value:
                        extra["condition_note"] = note_value
                if product.is_secondhand:
                    # 中古機:每隻獨立成本(沒填用線單價 fallback),轉成未稅
                    gross = _serial_cost(entry, it.unit_price)
                    if po.tax_method == PurchaseOrder.TaxMethod.TAXABLE_INCLUDED:
                        serial_cost_net = (
                            gross / (Decimal("1") + TAX_RATE)
                        ).quantize(CENTS)
                    else:
                        serial_cost_net = gross.quantize(CENTS)
                try:
                    serial = create_serial(
                        tenant=po.tenant,
                        product=product,
                        imei=entry["imei"],
                        sn=entry["sn"],
                        warehouse=po.warehouse,
                        status=ProductSerial.Status.IN_STOCK,
                        purchase_unit_cost=serial_cost_net,
                        purchase_order_item=it,
                        received_at=now,
                        **extra,
                    )
                except IdentifierError as exc:
                    raise PurchaseOrderError(f"第 {it.line_no} 行:{exc}")
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
    balance = locked_balance(po.tenant, product, po.warehouse, create=True)
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

    全部在交易內、上鎖之後才檢查(兩個人同時按作廢只會做一次;檢查完到扣庫存之間
    不會被別張單插進來)。
    """
    from apps.catalog.models import Product

    with transaction.atomic():
        if lock_document(po) is None:
            raise PurchaseOrderError("找不到這張進貨單")
        if po.is_void:
            raise PurchaseOrderError("此單已作廢")

        items = list(po.items.select_related("product", "product__condition").all())
        stock_items = [
            it for it in items if not it.product.requires_serial and not it.product.is_virtual
        ]
        serial_ids = list(
            ProductSerial.objects.for_tenant(po.tenant)
            .filter(purchase_order_item__in=items).values_list("pk", flat=True)
        )
        lock_stock_rows(
            po.tenant,
            products=[it.product for it in items if not it.product.is_virtual],
            # 作廢時這幾台的碼會釋放;可能要接手那些碼的設備(同碼的舊資料)一起鎖,
            # 跟這張單的設備照同一個順序鎖,兩張作廢單才不會互相等到死結
            serial_ids=[*serial_ids, *twin_ids(serial_ids)],
            balances=[(it.product, po.warehouse) for it in stock_items],
        )

        serials = list(ProductSerial.objects.filter(pk__in=serial_ids).order_by("pk"))
        # 要還在這張單進貨的門市、而且在庫:已經賣掉、調走(就算在別家門市是在庫)都算動用過
        moved = [
            x.serial_no for x in serials
            if x.status != ProductSerial.Status.IN_STOCK or x.warehouse_id != po.warehouse_id
        ]
        if moved:
            raise PurchaseOrderError(
                f"序號已動用,無法作廢:{', '.join(moved[:3])}"
            )

        # 配件庫存夠不夠扣(同一個商品在這張單出現好幾行時要加總)
        need = {}
        for it in stock_items:
            need[it.product_id] = need.get(it.product_id, 0) + it.qty
        balances = {}
        for it in stock_items:
            if it.product_id in balances:
                continue
            balance = locked_balance(po.tenant, it.product, po.warehouse)
            current = balance.qty if balance else 0
            if current < need[it.product_id]:
                raise PurchaseOrderError(
                    f"商品 {it.product.sku} 在 {po.warehouse.code} 現有 {current},"
                    f"無法回退本單的 {need[it.product_id]} 件(部分已售出/調撥)"
                )
            balances[it.product_id] = balance

        affected_product_ids = set()
        for x in serials:
            affected_product_ids.add(x.product_id)
            x.status = ProductSerial.Status.VOID
            x.warehouse = None
            x.save(update_fields=["status", "warehouse"])
            StockMovement.objects.create(
                tenant=po.tenant,
                serial=x,
                movement_type=StockMovement.MovementType.VOID,
                from_warehouse=po.warehouse,
                ref_doc_type="purchase_order",
                ref_doc_id=po.id,
                note=f"進貨單 {po.no} 作廢",
            )
        # 作廢的設備不佔碼:打錯整張作廢之後,同一批貨要能用同樣的 IMEI / SN 重新入庫
        release_codes(serial_ids)

        # 配件:從本倉 balance 扣掉本單進貨量
        for it in stock_items:
            product = it.product
            affected_product_ids.add(product.id)
            balance = balances[product.id]
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
        for pid in sorted(affected_product_ids):
            _recompute_product_avg_cost(po.tenant, Product.objects.get(pk=pid))

        po.is_void = True
        po.save(update_fields=["is_void"])

    return po


def transferable_from_purchase(po: PurchaseOrder):
    """這張進貨單進來的東西,現在還有哪些留在進貨門市、可以整張調撥出去。只讀,不改任何資料。

    - 序號商品:這張單進來的每一台,還在進貨門市而且在庫的才能調;已經賣掉 / 調走 / 退回 / 作廢的列在 gone。
    - 配件:數量 = 這張單進的數量,但不超過進貨門市現在的庫存(配件不分批,賣掉的分不出是哪一張單進的)。
    - 同一個商品在單上有好幾行時併成一行(調撥單一個商品一行)。虛擬商品不能調撥,不列。

    這裡只是「帶出建議的內容」;真正能不能調,存調撥單時由調撥那一邊鎖住庫存再檢查。
    """
    from apps.inventory.identifiers import codes_of

    lines = {}
    for it in po.items.select_related("product").order_by("line_no", "id"):
        product = it.product
        if product.is_virtual:
            continue
        line = lines.setdefault(product.id, {
            "product": product.id, "product_sku": product.sku, "product_name": product.name,
            "requires_serial": product.requires_serial,
            "purchased": 0, "qty": 0, "serials": [], "gone": [],
        })
        line["purchased"] += it.qty

    serials = (
        ProductSerial.objects.for_tenant(po.tenant)
        .filter(purchase_order_item__po=po, product_id__in=list(lines))
        .select_related("warehouse").prefetch_related("identifiers").order_by("pk")
    )
    for serial in serials:
        line = lines[serial.product_id]
        here = (serial.status == ProductSerial.Status.IN_STOCK
                and serial.warehouse_id == po.warehouse_id)
        if here:
            line["serials"].append({"id": serial.id, "serial_no": serial.serial_no, **codes_of(serial)})
        else:
            line["gone"].append({
                "serial_no": serial.serial_no,
                "status_label": serial.get_status_display(),
                "warehouse_name": serial.warehouse.name if serial.warehouse_id else "",
            })

    balances = dict(
        StockBalance.objects.for_tenant(po.tenant)
        .filter(warehouse_id=po.warehouse_id, product_id__in=list(lines))
        .values_list("product_id", "qty")
    )
    for product_id, line in lines.items():
        if line["requires_serial"]:
            line["qty"] = len(line["serials"])
        else:
            line["qty"] = max(0, min(line["purchased"], balances.get(product_id, 0)))
    return list(lines.values())
