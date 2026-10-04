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
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.catalog.models import Category, Product
from apps.core.tenant_fields import same_company as _same_company
from apps.inventory.locking import lock_stock_rows, locked_balance as _locked_balance
from apps.inventory.identifiers import IdentifierError, create_serial, main_code, split_codes, taken
from apps.inventory.models import ProductSerial, StockBalance, StockMovement
from apps.parties.models import Customer, SimCard, TelecomPlan
from apps.tenants.services import InvoiceTrackError, assign_invoice_no

from .models import (
    SalesOrder,
    SalesOrderItem,
    SalesOrderItemSerial,
    SalesOrderPayment,
    SalesReturn,
    SalesReturnItemSerial,
)

CENTS = Decimal("0.01")
TAX_RATE = Decimal("0.05")


class SalesOrderError(Exception):
    """銷貨業務錯誤;由 view 轉成 400 回應。"""


def _lock_rows(tenant, warehouse, serial_ids=(), sim_ids=(), products=(), create=False):
    """這張單會動到的序號、SIM 卡、這家門市的庫存餘額,先照固定順序鎖住再檢查。
    規則與原因見 apps/inventory/locking.py(銷貨、進貨、調撥、維修共用)。"""
    lock_stock_rows(
        tenant, serial_ids=serial_ids, sim_ids=sim_ids,
        balances=[(p, warehouse) for p in products], create=create,
    )


def _stock_products(items):
    """明細裡走「庫存餘額」的商品(配件 / 零件:不逐支記、也不是虛擬商品)。"""
    return [it.product for it in items if not it.product.requires_serial and not it.product.is_virtual]


def _validate_items(so: SalesOrder, items):
    if not items:
        raise SalesOrderError("無明細,無法過帳")
    if not _same_company(so.tenant_id, so.warehouse, so.customer, so.member, so.sales_person):
        raise SalesOrderError("門市 / 客戶 / 會員 / 業務員不屬於這家公司")
    if not _same_company(so.tenant_id, *so.payments.all()):
        raise SalesOrderError("付款明細不屬於這家公司")
    for it in items:
        links = list(it.serials.select_related("serial"))
        serials = [sos.serial for sos in links]
        if not _same_company(so.tenant_id, it, it.product, it.sim_card, it.telecom_plan,
                             *links, *serials):
            raise SalesOrderError(f"第 {it.line_no} 行的商品 / 序號 / 卡片 / 方案不屬於這家公司")

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
            # 配件:檢查該倉庫存是否足夠
            if item_serials:
                raise SalesOrderError(
                    f"第 {it.line_no} 行配件 {product.sku} 不可指定序號"
                )
            balance = StockBalance.objects.filter(
                tenant=so.tenant,
                product=product,
                warehouse=so.warehouse,
            ).first()
            current = balance.qty if balance else 0
            if current < it.qty:
                raise SalesOrderError(
                    f"第 {it.line_no} 行 {product.sku} 在 {so.warehouse.code} "
                    f"現有 {current},不足銷售 {it.qty}"
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


def split_tax_by_line(amounts, tax_method: str, subtotal: Decimal, tax: Decimal):
    """把單頭的未稅小計 / 稅額分到每一行。

    每行先照稅別各自算;四捨五入的零頭補在金額絕對值最大的那一行(同大取第一行),
    讓整單加總正好等於單頭。單頭不是「明細加總照稅別算出來的那個數」時,代表單頭跟
    明細本來就對不上,回傳 None,不硬塞(否則含稅行的 未稅 + 稅額 會不等於金額)。
    """
    if _calc_tax(sum(amounts, Decimal("0")), tax_method)[:2] != (subtotal, tax):
        return None
    lines = []
    for a in amounts:
        if tax_method == SalesOrder.TaxMethod.TAXABLE_INCLUDED:
            u = (a / (Decimal("1") + TAX_RATE)).quantize(CENTS)
            t = a - u
        elif tax_method == SalesOrder.TaxMethod.TAXABLE_EXCLUDED:
            u = a
            t = (a * TAX_RATE).quantize(CENTS)
        else:
            u, t = a, Decimal("0.00")
        lines.append([u, t])
    if not lines:
        return []
    du = subtotal - sum(u for u, _ in lines)
    dt = tax - sum(t for _, t in lines)
    if abs(du) > CENTS * len(lines) or abs(dt) > CENTS * len(lines):
        return None
    k = max(range(len(lines)), key=lambda i: (abs(amounts[i]), -i))
    lines[k][0] += du
    lines[k][1] += dt
    return [(u, t) for u, t in lines]


def _store_line_tax(items, tax_method, subtotal, tax, model):
    split = split_tax_by_line([it.amount for it in items], tax_method, subtotal, tax)
    if split is None:
        raise SalesOrderError("未稅 / 稅額分到每一行時對不起來")
    for it, (u, t) in zip(items, split):
        it.untaxed_amount, it.tax_amount = u, t
    model.objects.bulk_update(items, ["untaxed_amount", "tax_amount"])


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
    # 行號一樣時用建立順序決定先後(零頭補在哪一行要固定,回填也是這個順序)
    items = list(
        so.items.select_related("product")
        .prefetch_related("serials__serial")
        .order_by("line_no", "id")
    )

    with transaction.atomic():
        # 先鎖再檢查:序號是不是還在庫、卡是不是還沒發出去,都要看鎖到之後的狀態
        _lock_rows(
            so.tenant, so.warehouse,
            serial_ids=SalesOrderItemSerial.objects.filter(item__so=so).values_list("serial_id", flat=True),
            sim_ids=[it.sim_card_id for it in items if it.sim_card_id],
            products=_stock_products(items),
        )
        _validate_items(so, items)
        now = timezone.now()
        subtotal_raw = Decimal("0")

        for it in items:
            product = it.product
            if not it.amount:
                it.amount = (Decimal(it.qty) * it.unit_price).quantize(CENTS)
            else:
                it.amount = it.amount.quantize(CENTS)

            # cost_at_post:
            # - 虛擬:0
            # - 序號實體:sum 各 serial 的 purchase_unit_cost
            # - 配件(無序號實體):本倉 balance.weighted_avg_cost × qty
            if product.is_virtual:
                it.cost_at_post = Decimal("0")
            elif product.requires_serial:
                item_serials = list(it.serials.select_related("serial").all())
                it.cost_at_post = sum(
                    (sos.serial.purchase_unit_cost for sos in item_serials),
                    Decimal("0"),
                ).quantize(CENTS)
            else:
                bal = StockBalance.objects.filter(
                    tenant=so.tenant,
                    product=product,
                    warehouse=so.warehouse,
                ).first()
                unit_cost = bal.weighted_avg_cost if bal else Decimal("0")
                it.cost_at_post = (Decimal(it.qty) * unit_cost).quantize(CENTS)
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

            # 配件 / 零件:扣本倉 balance(銷貨不重算 weighted_avg)
            # 零件倉商品異動類型用 parts_transfer(對外調貨),其餘用 sale_out
            if (
                not product.requires_serial
                and not product.is_virtual
            ):
                is_parts = (
                    getattr(product, "warehouse_type", "product") == "parts"
                )
                # 零件對外銷售:售價防呆,不可低於最低售價
                if is_parts and product.min_sale_price and product.min_sale_price > 0:
                    if it.unit_price < product.min_sale_price:
                        from rest_framework.exceptions import ValidationError
                        raise ValidationError(
                            {
                                "detail": (
                                    f"零件「{product.name}」單價 "
                                    f"{int(it.unit_price)} 不可低於最低售價 "
                                    f"{int(product.min_sale_price)}"
                                )
                            }
                        )
                bal = _locked_balance(so.tenant, product, so.warehouse)
                if bal is None or bal.qty < it.qty:
                    # 檢查庫存夠不夠是在鎖之前做的;鎖到之後數量可能已經被另一張單賣掉
                    raise SalesOrderError(
                        f"第 {it.line_no} 行 {product.sku} 在 {so.warehouse.code} "
                        f"現有 {bal.qty if bal else 0},不足銷售 {it.qty}"
                    )
                bal.qty -= it.qty
                bal.save(update_fields=["qty"])
                mtype = (
                    StockMovement.MovementType.PARTS_TRANSFER
                    if is_parts
                    else StockMovement.MovementType.SALE_OUT
                )
                StockMovement.objects.create(
                    tenant=so.tenant,
                    product=product,
                    qty=it.qty,
                    movement_type=mtype,
                    from_warehouse=so.warehouse,
                    ref_doc_type="sales_order",
                    ref_doc_id=so.id,
                    note=(
                        f"銷貨單 {so.no} 第 {it.line_no} 行 "
                        f"{product.sku} ×{it.qty}"
                        + (" (零件調貨)" if is_parts else "")
                    ),
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
        _store_line_tax(items, so.tax_method, subtotal, tax_amount, SalesOrderItem)

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


SECONDHAND_INTAKE_NAME = "收購二手"
SECONDHAND_INTAKE_CATEGORY_CODE = "SYS"


class SecondhandIntakeError(Exception):
    """個人收購入庫業務錯誤;由 view 轉成 400。"""


def _get_or_create_secondhand_intake_product(tenant) -> Product:
    """取得或自動建立「收購二手」虛擬商品(per tenant)。"""
    existing = (
        Product.objects.for_tenant(tenant).filter(name=SECONDHAND_INTAKE_NAME).first()
    )
    if existing:
        return existing
    cat = (
        Category.objects.for_tenant(tenant)
        .filter(code=SECONDHAND_INTAKE_CATEGORY_CODE)
        .first()
    )
    if not cat:
        cat = Category.objects.create(
            tenant=tenant,
            code=SECONDHAND_INTAKE_CATEGORY_CODE,
            name="系統項目",
            is_active=True,
            sort_order=9999,
        )
    return Product.objects.create(
        tenant=tenant,
        category=cat,
        name=SECONDHAND_INTAKE_NAME,
        list_price=0,
        requires_serial=False,
        allows_telecom_line=False,
        allows_commission=False,
        is_virtual=True,
        is_secondhand=False,
        counts_cash=True,
        counts_margin=False,
        is_active=True,
    )


def _get_or_create_customer_for_member(tenant, member) -> Customer:
    """個人收購對應一筆 Customer(銷貨單的歸屬必填)。

    優先以 phone 比對既有個人客戶;phone 為空時退而求其次以 name 比對。
    都沒有就照會員資料新建一筆 individual Customer。
    """
    qs = Customer.objects.for_tenant(tenant).filter(kind=Customer.Kind.INDIVIDUAL)
    if member.phone:
        existing = qs.filter(phone=member.phone).order_by("created_at").first()
        if existing is not None:
            return existing
    else:
        existing = qs.filter(phone="", name=member.name).order_by("created_at").first()
        if existing is not None:
            return existing
    return Customer.objects.create(
        tenant=tenant,
        name=member.name,
        phone=member.phone,
        kind=Customer.Kind.INDIVIDUAL,
        address=member.address,
    )


def acquire_secondhand_from_member(
    *,
    tenant,
    member,
    warehouse,
    secondhand_product: Product,
    serial_no: str = "",
    condition_grade: str,
    custom_unit_price,
    acquisition_price,
    payment_method_code: str,
    battery_health=None,
    condition_note: str = "",
    doc_date=None,
    note: str = "",
    imei: str = "",
    sn: str = "",
):
    """個人會員收購中古機:一個 transaction 內同時建立序號 + 收購二手銷貨單。

    記帳方向:銷貨單 total 為負數(現金流出),與一般銷貨(正數現金流入)在報表自然相加。
    銷貨單 customer 自動帶該會員對應的個人 Customer(查無則新建),member 欄位記會員本身。

    這一台的碼:imei / sn 可以都給、也可以只給一個;serial_no 是「沒講是哪一種」的單一個碼(舊寫法)。
    """
    if not _same_company(tenant.id, member, warehouse, secondhand_product):
        raise SecondhandIntakeError("會員 / 門市 / 商品不屬於這家公司")
    if not secondhand_product.is_secondhand:
        raise SecondhandIntakeError(
            f"商品 {secondhand_product.sku} 不是中古機(is_secondhand=False)"
        )
    try:
        imei, sn = split_codes(imei, sn, serial_no)
    except IdentifierError as exc:
        raise SecondhandIntakeError(str(exc))
    serial_no = main_code(imei, sn)
    clash = taken(tenant, [imei, sn])
    if clash:
        raise SecondhandIntakeError(f"序號 {', '.join(clash)} 已存在")
    if condition_grade not in ProductSerial.ConditionGrade.values:
        raise SecondhandIntakeError(f"成色等級 {condition_grade} 無效")
    price = Decimal(str(acquisition_price)).quantize(CENTS)
    if price <= 0:
        raise SecondhandIntakeError("收購金額需大於 0")

    virtual_product = _get_or_create_secondhand_intake_product(tenant)

    with transaction.atomic():
        customer = _get_or_create_customer_for_member(tenant, member)

        try:
            serial = create_serial(
                tenant=tenant,
                product=secondhand_product,
                imei=imei,
                sn=sn,
                warehouse=warehouse,
                status=ProductSerial.Status.IN_STOCK,
                purchase_unit_cost=price,
                condition_grade=condition_grade,
                custom_unit_price=custom_unit_price,
                battery_health=battery_health,
                condition_note=condition_note,
                acquired_from_member=member,
                received_at=timezone.now(),
            )
        except IdentifierError as exc:
            raise SecondhandIntakeError(str(exc))

        so = SalesOrder.objects.create(
            tenant=tenant,
            customer=customer,
            member=member,
            warehouse=warehouse,
            doc_date=doc_date or date.today(),
            sales_type=SalesOrder.SalesType.SALE,
            tax_method=SalesOrder.TaxMethod.UNTAXED,
            note=(
                f"中古收購 {serial_no}"
                + (f" - {note}" if note else "")
            ),
        )
        SalesOrderItem.objects.create(
            tenant=tenant,
            so=so,
            line_no=1,
            product=virtual_product,
            qty=1,
            unit_price=-price,
            amount=-price,
        )
        SalesOrderPayment.objects.create(
            tenant=tenant,
            so=so,
            line_no=1,
            method=payment_method_code,
            amount=-price,
        )

        try:
            commit_sales_order(so)
        except SalesOrderError as exc:
            raise SecondhandIntakeError(str(exc))

        serial.acquired_via_sales_order = so
        serial.save(update_fields=["acquired_via_sales_order"])

        StockMovement.objects.create(
            tenant=tenant,
            serial=serial,
            movement_type=StockMovement.MovementType.TRADE_IN,
            to_warehouse=warehouse,
            ref_doc_type="sales_order",
            ref_doc_id=so.id,
            note=f"個人收購入庫 from {member.phone} {member.name}",
        )

    return serial, so


def void_sales_order(so: SalesOrder) -> SalesOrder:
    """整單作廢:序號全部退回 in_stock、SIM 卡退回 in_stock。

    已經有有效銷退的單不能作廢(庫存已經由銷退加回去了,再作廢會加第二次);要先作廢銷退。
    跟建立銷退共用同一把鎖(原銷貨單那一列),兩邊同時來也只會有一邊成功。
    """
    with transaction.atomic():
        if SalesOrder.objects.select_for_update().filter(pk=so.pk).first() is None:
            raise SalesOrderError("找不到這張銷貨單")
        so.refresh_from_db()
        if so.is_void:
            raise SalesOrderError("此單已作廢")
        returned_by = (
            SalesReturn.objects.filter(original_so=so, is_void=False)
            .values_list("no", flat=True).first()
        )
        if returned_by:
            raise SalesOrderError(f"這張銷貨單已由 {returned_by} 銷退,請先作廢銷退單")

        items = list(
            so.items.select_related("product", "sim_card")
            .prefetch_related("serials__serial")
            .all()
        )
        _lock_rows(
            so.tenant, so.warehouse,
            serial_ids=SalesOrderItemSerial.objects.filter(item__so=so).values_list("serial_id", flat=True),
            sim_ids=[it.sim_card_id for it in items if it.sim_card_id],
            products=_stock_products(items), create=True,
        )
        for it in items:
            product = it.product
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
            # 配件:回補本倉 balance(數量回補,不動 weighted_avg)
            if (
                not product.requires_serial
                and not product.is_virtual
            ):
                bal = _locked_balance(so.tenant, product, so.warehouse, create=True)
                bal.qty += it.qty
                bal.save(update_fields=["qty"])
                StockMovement.objects.create(
                    tenant=so.tenant,
                    product=product,
                    qty=it.qty,
                    movement_type=StockMovement.MovementType.RETURN_IN,
                    to_warehouse=so.warehouse,
                    ref_doc_type="sales_order",
                    ref_doc_id=so.id,
                    note=f"銷貨單 {so.no} 作廢 {product.sku} ×{it.qty}",
                )
            if it.sim_card_id:
                card = it.sim_card
                card.status = SimCard.Status.IN_STOCK
                card.issued_at = None
                card.save(update_fields=["status", "issued_at"])

        so.is_void = True
        so.save(update_fields=["is_void"])

    return so


class SalesReturnError(Exception):
    """銷退業務錯誤;由 view 轉成 400。"""


def _validate_sales_return(sr: SalesReturn):
    """驗證銷退單可以送出。銷退只能整張退:
    1. 原銷貨單 / 門市 / 客戶 / 會員都是這家公司的;原單沒作廢、不是收購單
    2. 這張原單沒有其他有效的銷退(呼叫端已先鎖住原單,兩張同時送出也只會成一張)
    3. 退款方式必須是原單付款方式之一
    4. 原單每一行都在、整行數量、單價相同;序號商品原單的每一台都在,不多不少
    """
    so = sr.original_so
    if not _same_company(sr.tenant_id, so, sr.warehouse, sr.customer, sr.member):
        raise SalesReturnError("原銷貨單 / 門市 / 客戶 / 會員不屬於這家公司")
    if so.is_void:
        raise SalesReturnError(f"原銷貨單 {so.no} 已作廢,不能銷退")
    if so.total < 0:
        raise SalesReturnError(f"{so.no} 是收購單,不能銷退")
    if SalesReturn.objects.filter(original_so=so, is_void=False).exclude(pk=sr.pk).exists():
        raise SalesReturnError(f"銷貨單 {so.no} 已經退過")

    if sr.warehouse_id != so.warehouse_id:
        raise SalesReturnError("退回門市要跟原銷貨單的門市一樣")
    if (sr.customer_id, sr.member_id) != (so.customer_id, so.member_id):
        raise SalesReturnError("客戶 / 會員要跟原銷貨單一樣")

    # 退款方式必須是原單付款方式之一(總額 0 的單沒有付款,不用退款方式)
    original_methods = set(so.payments.values_list("method", flat=True))
    if so.total == 0 and not original_methods:
        if sr.payment_method:
            raise SalesReturnError("原銷貨單總額為 0,不需要退款方式")
    elif sr.payment_method not in original_methods:
        raise SalesReturnError(
            f"退款方式 {sr.payment_method} 不在原單付款方式 {sorted(original_methods)} 內"
        )

    originals = {
        oi.id: oi for oi in so.items.select_related("product").prefetch_related("serials__serial")
    }
    items = list(
        sr.items.select_related("original_item__product", "product")
        .prefetch_related("serials__serial")
    )
    touched = []
    for oi in originals.values():
        links = list(oi.serials.all())
        touched += [oi, oi.product, *links, *[link.serial for link in links]]
    for it in items:
        links = list(it.serials.all())
        touched += [it, it.product, it.original_item, it.original_item.product,
                    *links, *[link.serial for link in links]]
    if not _same_company(sr.tenant_id, *touched):
        raise SalesReturnError("銷退明細 / 原銷貨明細 / 商品 / 序號不屬於這家公司")
    returned = {}
    for it in items:
        if it.original_item_id not in originals or it.product_id != it.original_item.product_id:
            raise SalesReturnError(f"第 {it.line_no} 行不是原銷貨單 {so.no} 的明細")
        if it.original_item_id in returned:
            raise SalesReturnError(f"第 {it.line_no} 行跟前面退的是同一行原銷貨明細")
        returned[it.original_item_id] = it
    left = len(originals) - len(returned)
    if left:
        raise SalesReturnError(f"銷退只能整張退:原銷貨單還有 {left} 行沒有退")

    for it in items:
        oi = originals[it.original_item_id]
        if it.qty != oi.qty:
            raise SalesReturnError(f"第 {it.line_no} 行要整行退(原 {oi.qty},退 {it.qty})")
        if it.unit_price != oi.unit_price:
            raise SalesReturnError(
                f"第 {it.line_no} 行單價 {it.unit_price} 與原單 {oi.unit_price} 不一致"
            )
        want = sorted(link.serial_id for link in oi.serials.all())
        got = sorted(link.serial_id for link in it.serials.all())
        if want != got:
            raise SalesReturnError(f"第 {it.line_no} 行要退原銷貨單的每一台(序號不符)")


def commit_sales_return(sr: SalesReturn) -> SalesReturn:
    """銷退單儲存即觸發。

    - 序號:status → returned,warehouse = 銷退倉,sold_at 清空 → 後續可手動轉回 in_stock
    - 配件:本倉 StockBalance.qty += qty
    - 寫 StockMovement(RETURN_IN)
    - 只能整張退:每行的金額 / 未稅 / 稅額 / 成本、單頭的 subtotal / tax / total 全部照抄原單,
      所以銷退跟原銷貨單完全對沖
    - void_original_invoice=True 時把 SO.invoice_voided 標 True(冪等)
    """
    with transaction.atomic():
        # 先鎖原銷貨單:同一張單的兩張銷退同時送出時,一張做完另一張才檢查「還能退多少」
        so = SalesOrder.objects.select_for_update().filter(
            pk=sr.original_so_id, tenant_id=sr.tenant_id
        ).first()
        if so is None:
            raise SalesReturnError("原銷貨單不屬於這家公司")
        sr.original_so = so          # 之後一律用鎖到之後重讀的這一份(不用鎖之前讀的)
        _validate_sales_return(sr)
        items = list(
            sr.items.select_related("product", "original_item")
            .prefetch_related("serials__serial")
            .order_by("line_no", "id")
        )
        _lock_rows(
            sr.tenant, sr.warehouse,
            serial_ids=SalesReturnItemSerial.objects.filter(item__sr=sr).values_list("serial_id", flat=True),
            products=_stock_products(items), create=True,
        )
        for it in items:
            product = it.product
            # 整張退 = 原單完全對沖:金額、未稅、稅額、成本每一行都照抄原行,不重算
            oi = it.original_item
            it.amount, it.untaxed_amount, it.tax_amount = oi.amount, oi.untaxed_amount, oi.tax_amount
            it.cost_at_post = oi.cost_at_post
            it.save(update_fields=["amount", "untaxed_amount", "tax_amount", "cost_at_post"])

            # 序號狀態 → returned,warehouse 回到銷退倉
            for sos in it.serials.select_related("serial").all():
                serial = sos.serial
                serial.status = ProductSerial.Status.RETURNED
                serial.warehouse = sr.warehouse
                serial.sold_at = None
                serial.save(
                    update_fields=["status", "warehouse", "sold_at"]
                )
                StockMovement.objects.create(
                    tenant=sr.tenant,
                    serial=serial,
                    movement_type=StockMovement.MovementType.RETURN_IN,
                    to_warehouse=sr.warehouse,
                    ref_doc_type="sales_return",
                    ref_doc_id=sr.id,
                    note=f"銷退單 {sr.no} 第 {it.line_no} 行",
                )

            # 配件:本倉 balance 加回
            if not product.requires_serial and not product.is_virtual:
                bal = _locked_balance(sr.tenant, product, sr.warehouse, create=True)
                bal.qty += it.qty
                bal.save(update_fields=["qty"])
                StockMovement.objects.create(
                    tenant=sr.tenant,
                    product=product,
                    qty=it.qty,
                    movement_type=StockMovement.MovementType.RETURN_IN,
                    to_warehouse=sr.warehouse,
                    ref_doc_type="sales_return",
                    ref_doc_id=sr.id,
                    note=f"銷退單 {sr.no} 第 {it.line_no} 行 {product.sku} ×{it.qty}",
                )

        # 單頭也照抄原單(舊單就算單頭跟明細有零頭差,退的數字仍跟原單一模一樣)
        sr.subtotal, sr.tax_amount, sr.total = so.subtotal, so.tax_amount, so.total
        sr.save(update_fields=["subtotal", "tax_amount", "total"])

        if sr.void_original_invoice and not so.invoice_voided:
            so.invoice_voided = True
            so.save(update_fields=["invoice_voided"])

    return sr


def void_sales_return(sr: SalesReturn) -> SalesReturn:
    """銷退單作廢:把退回的庫存再扣回去(=回到「銷售出去」的狀態)。

    - 序號:returned → sold,warehouse=None,sold_at 不重設(歷史已失,僅恢復狀態)
    - 配件:該倉 balance.qty -= qty(若不足會擋下,避免負庫存)
    - 不還原 SO.invoice_voided(由使用者決定是否要再去發票系統處理)

    全部在交易內、上鎖之後才檢查:先鎖原銷貨單(跟建立銷退 / 作廢銷貨同一把鎖),再鎖這張
    銷退、相關序號與庫存餘額。兩個人同時按作廢也只會扣一次。
    """
    with transaction.atomic():
        SalesOrder.objects.select_for_update().filter(pk=sr.original_so_id).first()
        if SalesReturn.objects.select_for_update().filter(pk=sr.pk).first() is None:
            raise SalesReturnError("找不到這張銷退單")
        sr.refresh_from_db()
        if sr.is_void:
            raise SalesReturnError("此銷退單已作廢")

        items = list(sr.items.select_related("product").order_by("line_no", "id"))
        links = list(SalesReturnItemSerial.objects.filter(item__sr=sr).order_by("id"))
        _lock_rows(sr.tenant, sr.warehouse, serial_ids=[l.serial_id for l in links],
                   products=_stock_products(items))
        serials = {
            x.pk: x for x in ProductSerial.objects.filter(pk__in=[l.serial_id for l in links])
        }
        # 退回來的機器之後如果已經被處理(轉回在庫、再賣掉、調走),就不能再把它打回「已售」
        for serial in serials.values():
            if serial.status != ProductSerial.Status.RETURNED or serial.warehouse_id != sr.warehouse_id:
                raise SalesReturnError(
                    f"作廢失敗:序號 {serial.serial_no} 目前是「{serial.get_status_display()}」,"
                    "已經不是這張銷退退回來的狀態"
                )

        for it in items:
            product = it.product
            for link in links:
                if link.item_id != it.id:
                    continue
                serial = serials[link.serial_id]
                serial.status = ProductSerial.Status.SOLD
                serial.warehouse = None
                serial.save(update_fields=["status", "warehouse"])
                StockMovement.objects.create(
                    tenant=sr.tenant,
                    serial=serial,
                    movement_type=StockMovement.MovementType.VOID,
                    from_warehouse=sr.warehouse,
                    ref_doc_type="sales_return",
                    ref_doc_id=sr.id,
                    note=f"銷退單 {sr.no} 作廢,序號回 sold",
                )

            if not product.requires_serial and not product.is_virtual:
                bal = (
                    StockBalance.objects.select_for_update()
                    .filter(tenant=sr.tenant, product=product, warehouse=sr.warehouse)
                    .first()
                )
                if bal is None:
                    raise SalesReturnError(
                        f"作廢失敗:{product.sku} 在倉 {sr.warehouse} 無餘額紀錄"
                    )
                if bal.qty < it.qty:
                    raise SalesReturnError(
                        f"作廢失敗:{product.sku} 在倉 {sr.warehouse} 庫存"
                        f"{bal.qty} 不足以扣回 {it.qty}"
                    )
                bal.qty -= it.qty
                bal.save(update_fields=["qty"])
                StockMovement.objects.create(
                    tenant=sr.tenant,
                    product=product,
                    qty=it.qty,
                    movement_type=StockMovement.MovementType.VOID,
                    from_warehouse=sr.warehouse,
                    ref_doc_type="sales_return",
                    ref_doc_id=sr.id,
                    note=f"銷退單 {sr.no} 作廢 {product.sku} ×{it.qty}",
                )

        sr.is_void = True
        sr.save(update_fields=["is_void"])

    return sr
