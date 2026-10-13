"""發票機(WP-103)測試頁要印的東西:行號測試、樣張。排版與位元組在 `wp103.py`;畫面把 `data` 原樣送進 COM 埠。

只回排好的字與位元組,不碰任何單據、不取發票號碼(測試印在真的發票紙上會用掉那一張:印完用跳號把系統對回紙上的號碼)。
"""
import base64

from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from . import wp103

KINDS = ("ruler", "sample")


@api_view(["GET"])
def invoice_printer_test(request):
    """?kind=ruler(行號測試)| sample(樣張)&top=上面先空幾行(只有樣張用)"""
    kind = (request.query_params.get("kind") or "ruler").strip()
    if kind not in KINDS:
        return Response({"detail": "只有行號測試與樣張兩種"}, status=status.HTTP_400_BAD_REQUEST)
    raw = (request.query_params.get("top") or "0").strip()
    low, high = wp103.TOP_RANGE
    top = min(max(int(raw), low), high) if raw.isascii() and raw.isdigit() else low
    try:
        if kind == "ruler":
            lines = wp103.ruler_lines()
        else:
            lines = wp103.invoice_lines(wp103.sample_invoice(timezone.localtime()), top)
        data = wp103.page_bytes(lines)
    except wp103.LayoutError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response({
        "kind": kind, "top": top, "lines": lines, "page_lines": wp103.PAGE_LINES, "top_max": high,
        "data": base64.b64encode(data).decode("ascii"),
    })
