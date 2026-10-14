"""中古機大量進貨的 Excel:下載範本、讀檔(只讀;規則在 `secondhand_sheet.py`)。要員工帳號的「進貨入庫」。"""
import base64

from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.catalog.models import Product
from apps.catalog.serializers import ProductSerializer
from apps.parties.models import Supplier
from apps.tenants import abilities

from . import secondhand_sheet

FILENAME = "中古機進貨範本.xlsx"


@api_view(["GET", "POST"])
@parser_classes([MultiPartParser, JSONParser])
def secondhand_purchase_sheet(request):
    """GET:這家公司的範本(base64,附現有的中古機品名清單)。POST {file, supplier?}:讀出每一台、對到哪個品號、
    每一格與碼的問題(`check_rows`),不寫任何東西。"""
    abilities.require(request.user, abilities.PURCHASE)
    if request.method == "GET":
        raw = secondhand_sheet.build_template(request.tenant)
        return Response({"filename": FILENAME, "file": base64.b64encode(raw).decode("ascii")})
    upload = request.FILES.get("file")
    if upload is None:
        return Response({"detail": "要附上 Excel 檔"}, status=400)
    if upload.size > secondhand_sheet.MAX_BYTES:
        return Response({"detail": "檔案太大(最多 5 MB)"}, status=400)
    supplier = None
    raw_supplier = request.data.get("supplier")
    if raw_supplier not in (None, ""):
        supplier = Supplier.objects.filter(tenant=request.tenant, pk=_int(raw_supplier)).first()
        if supplier is None:
            return Response({"detail": "找不到這個廠商"}, status=400)
    try:
        rows = secondhand_sheet.read_sheet(upload.read())
    except secondhand_sheet.SheetError as exc:
        return Response({"detail": str(exc)}, status=400)
    out = secondhand_sheet.check_rows(request.tenant, rows, supplier)
    # 對到的品號一次帶完整的商品資料(畫面要拿它開進貨明細,跟搜尋商品回來的一樣)
    ids = {r["product"] for r in out["rows"] if r["product"]}
    products = Product.objects.filter(tenant=request.tenant, pk__in=ids)
    out["products"] = ProductSerializer(products, many=True, context={"request": request}).data
    return Response(out)


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1
