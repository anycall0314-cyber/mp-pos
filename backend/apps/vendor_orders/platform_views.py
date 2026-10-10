"""平台管理員維護的名單:叫貨類別、叫貨廠商。**不屬於任何公司;只有平台管理員能看、能改。**

招到一家廠商 = 在這裡加一筆(名稱、類別、怎麼接、對方的網址)。只能停用、不能刪:各公司的叫貨單與入庫紀錄還靠代碼指著它。
**「對方的網址」決定各家門市的金鑰會被送到哪裡** —— 一定要 https、不能帶帳密與參數;改它等於把這家所有門市的金鑰改送到新的地方,
只有平台管理員能動。
"""
import re
from urllib.parse import urlsplit

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.tenants.permissions import IsPlatformAdmin

from .models import Vendor, VendorCategory, VendorSecret

PLATFORM_ONLY = [IsAuthenticated, IsPlatformAdmin]
CODE = re.compile(r"^[a-z0-9][a-z0-9-]{1,19}$")
PREFIX = re.compile(r"^[A-Za-z0-9_-]{0,20}$")
MAX_ORDER = 9999
LABELS = {"name": "名稱", "is_active": "啟用"}


class Wrong(Exception):
    """送來的內容不對(訊息給人看)。"""


def _bad(message):
    return Response({"detail": str(message)}, status=status.HTTP_400_BAD_REQUEST)


def _text(data, name, limit) -> str:
    value = data.get(name)
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
        raise Wrong(f"{LABELS[name]}要填、而且不能超過 {limit} 個字")
    return value.strip()


def _flag(data, name) -> bool:
    if not isinstance(data.get(name), bool):
        raise Wrong(f"{LABELS[name]}只能是開或關")
    return data[name]


def _order(data) -> int:
    value = data.get("sort_order")
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= MAX_ORDER:
        raise Wrong(f"排序要是 0 到 {MAX_ORDER} 的整數")
    return value


def clean_base(raw) -> str:
    """對方的網址:https://主機[:埠]/路徑。不收 http(金鑰會用明碼在網路上跑)、帳密、參數。"""
    if not isinstance(raw, str) or not raw.strip() or len(raw.strip()) > 200:
        raise Wrong("對方的網址要填、而且不能超過 200 個字")
    url = raw.strip().rstrip("/")
    try:
        parts = urlsplit(url)
        host = parts.hostname
        parts.port          # 埠不是數字時這裡會丟錯
    except ValueError:
        raise Wrong("對方的網址看不懂") from None
    if (parts.scheme != "https" or not host or parts.username or parts.password or parts.query or parts.fragment
            or any(c.isspace() for c in url)):
        raise Wrong("對方的網址要是 https:// 開頭的完整網址,不能帶帳號密碼或參數")
    return url


# ── 類別 ────────────────────────────────────────────────────────────────────
def _category_data(c: VendorCategory) -> dict:
    return {"id": c.id, "name": c.name, "sort_order": c.sort_order, "is_active": c.is_active,
            "vendors": c.vendors.count()}


def _category_values(data, current=None) -> dict:
    out = {}
    if current is None or "name" in data:
        out["name"] = _text(data, "name", 20)
        clash = VendorCategory.objects.filter(name=out["name"])
        if current is not None:
            clash = clash.exclude(pk=current.pk)
        if clash.exists():
            raise Wrong(f"已經有「{out['name']}」這個類別")
    if "sort_order" in data:
        out["sort_order"] = _order(data)
    if "is_active" in data:
        out["is_active"] = _flag(data, "is_active")
    return out


@api_view(["GET", "POST"])
@permission_classes(PLATFORM_ONLY)
def categories(request):
    if request.method == "POST":
        data = request.data if isinstance(request.data, dict) else {}
        try:
            row = VendorCategory.objects.create(**_category_values(data))
        except Wrong as exc:
            return _bad(exc)
        return Response(_category_data(row), status=status.HTTP_201_CREATED)
    return Response({"results": [_category_data(c) for c in VendorCategory.objects.all()]})


@api_view(["PATCH"])
@permission_classes(PLATFORM_ONLY)
def category(request, pk: int):
    row = VendorCategory.objects.filter(pk=pk).first()
    if row is None:
        return Response({"detail": "找不到這個類別"}, status=status.HTTP_404_NOT_FOUND)
    data = request.data if isinstance(request.data, dict) else {}
    try:
        values = _category_values(data, row)
    except Wrong as exc:
        return _bad(exc)
    for name, value in values.items():
        setattr(row, name, value)
    row.save()
    return Response(_category_data(row))


# ── 廠商 ────────────────────────────────────────────────────────────────────
def _opened() -> dict:
    """每家廠商有幾家門市開通了(貼了金鑰):改網址、停用之前看一眼影響多大。"""
    out: dict[str, int] = {}
    for code in VendorSecret.objects.values_list("link__provider", flat=True):
        out[code] = out.get(code, 0) + 1
    return out


def _vendor_data(v: Vendor, opened=None) -> dict:
    return {
        "id": v.id, "code": v.code, "name": v.name, "categories": [c.id for c in v.categories.all()],
        "protocol": v.protocol, "protocol_label": v.get_protocol_display(),
        "api_base": v.api_base, "key_prefix": v.key_prefix, "is_active": v.is_active, "sort_order": v.sort_order,
        "stores": (opened or {}).get(v.code, 0),
    }


def _vendor_values(data, current=None):
    """回 (要存的欄位, 選到的類別或 None = 沒有要改類別)。"""
    out = {}
    if current is None:
        code = data.get("code")
        if not isinstance(code, str) or not CODE.match(code):
            raise Wrong("代碼要是 2 到 20 個小寫英文、數字或減號(開頭不能是減號);建了不能改")
        if Vendor.objects.filter(code=code).exists():
            raise Wrong(f"代碼「{code}」已經有了")
        out["code"] = code
    elif "code" in data and data["code"] != current.code:
        raise Wrong("代碼建了不能改(各家門市的叫貨單靠它認)")
    if current is None or "name" in data:
        out["name"] = _text(data, "name", 40)
    if current is None or "api_base" in data:
        out["api_base"] = clean_base(data.get("api_base"))
    if "key_prefix" in data:
        prefix = data["key_prefix"]
        if not isinstance(prefix, str) or not PREFIX.match(prefix):
            raise Wrong("金鑰的開頭只能是英文、數字、底線、減號,最多 20 個字")
        out["key_prefix"] = prefix
    if "protocol" in data:
        if data["protocol"] not in Vendor.Protocol.values:
            raise Wrong("怎麼接只能選清單上的")
        out["protocol"] = data["protocol"]
    if "sort_order" in data:
        out["sort_order"] = _order(data)
    if "is_active" in data:
        out["is_active"] = _flag(data, "is_active")
    picked = None
    if "categories" in data:
        ids = data["categories"]
        if not isinstance(ids, list) or any(isinstance(i, bool) or not isinstance(i, int) for i in ids):
            raise Wrong("類別不對")
        picked = list(VendorCategory.objects.filter(pk__in=ids))
        if len(picked) != len(set(ids)):
            raise Wrong("有一個類別找不到")
    return out, picked


@api_view(["GET", "POST"])
@permission_classes(PLATFORM_ONLY)
def vendor_list(request):
    if request.method == "POST":
        data = request.data if isinstance(request.data, dict) else {}
        try:
            values, picked = _vendor_values(data)
        except Wrong as exc:
            return _bad(exc)
        row = Vendor.objects.create(**values)
        if picked is not None:
            row.categories.set(picked)
        return Response(_vendor_data(row), status=status.HTTP_201_CREATED)
    opened = _opened()
    return Response({
        "results": [_vendor_data(v, opened) for v in Vendor.objects.prefetch_related("categories")],
        "protocols": [{"value": value, "label": label} for value, label in Vendor.Protocol.choices],
    })


@api_view(["PATCH"])
@permission_classes(PLATFORM_ONLY)
def vendor(request, pk: int):
    row = Vendor.objects.filter(pk=pk).first()
    if row is None:
        return Response({"detail": "找不到這家廠商"}, status=status.HTTP_404_NOT_FOUND)
    data = request.data if isinstance(request.data, dict) else {}
    try:
        values, picked = _vendor_values(data, row)
    except Wrong as exc:
        return _bad(exc)
    for name, value in values.items():
        setattr(row, name, value)
    row.save()
    if picked is not None:
        row.categories.set(picked)
    return Response(_vendor_data(row, _opened()))
