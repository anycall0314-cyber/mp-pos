"""維修單上當場進一個零件(owner 2026-10-29:整理自家庫存用的料可能只進一次,要「快速進貨加領料」)。

一次做完兩件事,同一個交易:
1. 這個零件:選既有的零件倉商品,或用名字建一個新的(過商品防重複關卡,類別放公司的維修料類別);
2. 開一張只有這一行的進貨單,照一般進貨單的規則入庫、算加權平均成本(commit_purchase_order)。

放進維修單的零件清單是畫面的事;維修單存檔時照舊抄那個零件當下的平均成本、完工時照舊扣門市庫存
(repairs/services.py),所以這裡進的門市要是維修單的收件門市。
"""
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import serializers

from apps.catalog.models import Category, Product
from apps.tenants import abilities

from .models import PurchaseOrder
from .serializers import PurchaseOrderSerializer
from .services import commit_purchase_order

NOTE = "維修單當場進貨"


class QuickPartSerializer(serializers.Serializer):
    """廠商、門市、付款方式的編號交給進貨單那一套去認(只認得自己公司的)。"""

    product = serializers.IntegerField(required=False, allow_null=True)
    name = serializers.CharField(required=False, allow_blank=True, max_length=200)
    supplier = serializers.IntegerField()
    warehouse = serializers.IntegerField()
    qty = serializers.IntegerField(min_value=1, max_value=999)
    unit_price = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0"))
    payment_method = serializers.IntegerField(required=False, allow_null=True)

    def validate(self, attrs):
        attrs["name"] = (attrs.get("name") or "").strip()
        if not attrs.get("product") and not attrs["name"]:
            raise serializers.ValidationError({"name": "請填零件名稱"})
        if attrs.get("product") and attrs["name"]:
            raise serializers.ValidationError({"name": "選了既有的零件就不用再填名稱"})
        attrs["unit_price"] = attrs["unit_price"].quantize(Decimal("1"), rounding=ROUND_HALF_UP)   # 全站金額整數
        return attrs


def parts_category(tenant) -> Category:
    """新零件放哪個類別:公司現在放最多零件的那一個 → 舊系統的「維修料」(RP)→ 都沒有就建一個「維修料」。"""
    cat = (
        Category.objects.for_tenant(tenant).filter(is_active=True, holds_devices=False)
        .annotate(n=Count("products", filter=Q(products__warehouse_type=Product.WarehouseType.PARTS)))
        .filter(n__gt=0).order_by("-n", "id").first()
    )
    if cat is None:
        cat = Category.objects.for_tenant(tenant).filter(code__iexact="RP").first()
    if cat is None:
        cat = Category.objects.create(tenant=tenant, code="RP", name="維修料")
    return cat


def _part(request, data) -> Product:
    from apps.catalog.serializers import ProductSerializer

    tenant = request.tenant
    if data.get("product"):
        part = Product.objects.for_tenant(tenant).filter(pk=data["product"]).first()
        if (part is None or not part.is_active or part.warehouse_type != Product.WarehouseType.PARTS
                or part.requires_serial or part.is_virtual):
            raise serializers.ValidationError({"product": "只能選零件倉的零件"})
        return part
    # 建新的零件 = 建商品:要有「商品建檔」(跟商品頁同一道)
    abilities.require(request.user, abilities.EDIT_PRODUCTS)
    ser = ProductSerializer(
        data={"name": data["name"], "category": parts_category(tenant).pk, "warehouse_type": "parts",
              "requires_serial": False},
        context={"request": request},
    )
    ser.is_valid(raise_exception=True)
    return ser.save(tenant=tenant)       # 防重複擋下會丟 DuplicateProduct,呼叫端回 409


def buy(view, request, data) -> PurchaseOrder:
    """呼叫端包交易。回進好的那一張進貨單。"""
    from apps.tenants.models import InvoiceType

    tenant = request.tenant
    part = _part(request, data)
    invoice = (
        InvoiceType.objects.for_tenant(tenant).filter(is_active=True)
        .order_by("-is_default", "sort_order", "id").values_list("code", flat=True).first()
    ) or ""
    qty = data["qty"]
    po_ser = PurchaseOrderSerializer(
        data={
            "supplier": data["supplier"],
            "warehouse": data["warehouse"],
            "doc_date": timezone.localdate(),
            "tax_method": PurchaseOrder.TaxMethod.TAXABLE_INCLUDED,
            "invoice_form": invoice,
            "payment_method": data.get("payment_method"),
            "note": NOTE,
            "items": [{
                "line_no": 1, "product": part.pk, "qty": qty, "billed_qty": qty,
                "unit_price": str(data["unit_price"]), "serial_numbers": [],
            }],
        },
        context={"request": request},
    )
    po_ser.is_valid(raise_exception=True)
    view.check_create_warehouse(po_ser)
    user = request.user if request.user.is_authenticated else None
    po = po_ser.save(tenant=tenant, created_by=user)
    commit_purchase_order(po)
    return po


def result(po: PurchaseOrder, request) -> dict:
    """回給畫面:進貨單號 + 那個零件(跟搜尋商品同一個樣子,成本照誰在看給)。"""
    from apps.catalog.serializers import ProductSerializer

    item = po.items.select_related("product").order_by("line_no", "id").first()
    part = Product.objects.get(pk=item.product_id)       # 進貨之後的平均成本
    return {
        "purchase_order": {"id": po.id, "no": po.no},
        "qty": item.qty,
        "product": ProductSerializer(part, context={"request": request}).data,
    }
