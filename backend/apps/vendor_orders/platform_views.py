"""平台管理員維護的名單:叫貨類別、叫貨廠商。**不屬於任何公司;只有平台管理員能看、能改。**

招到一家廠商 = 在這裡加一筆(名稱、類別、怎麼接、對方的網址)。只能停用、不能刪:各公司的叫貨單與入庫紀錄還靠代碼指著它。
**半自動的廠商**(對方沒有可以接的系統):不用填網址;商品與參考價由平台在這裡建一份**價目表**(一項一項加,或從 Excel 整批貼上),所有店家看到同一份。
**「對方的網址」決定各家門市的金鑰會被送到哪裡** —— 一定要 https、不能帶帳密與參數;改它等於把這家所有門市的金鑰改送到新的地方,
只有平台管理員能動。
"""
import re
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

from django.db import transaction

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.tenants.permissions import IsPlatformAdmin

from .models import Vendor, VendorCategory, VendorItem, VendorLink, VendorSecret

PLATFORM_ONLY = [IsAuthenticated, IsPlatformAdmin]
CODE = re.compile(r"^[a-z0-9][a-z0-9-]{1,19}$")
PREFIX = re.compile(r"^[A-Za-z0-9_-]{0,20}$")
MAX_ORDER = 9999
LABELS = {"name": "名稱", "is_active": "啟用"}
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_PRICE = Decimal("9999999.99")
MAX_PACK = 100000
IMPORT_ROWS = 1000
AUTO_SKU = re.compile(r"^N(\d{4,})$")


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
    """每家廠商有幾家門市開通了(全自動 = 貼了金鑰;半自動 = 按了開通):改網址、停用之前看一眼影響多大。"""
    out: dict[str, int] = {}
    manual = set(Vendor.objects.filter(protocol=Vendor.Protocol.MANUAL).values_list("code", flat=True))
    for code in VendorSecret.objects.exclude(link__provider__in=manual).values_list("link__provider", flat=True):
        out[code] = out.get(code, 0) + 1
    for code in VendorLink.objects.filter(provider__in=manual, opened=True).values_list("provider", flat=True):
        out[code] = out.get(code, 0) + 1
    return out


def _vendor_data(v: Vendor, opened=None) -> dict:
    return {
        "id": v.id, "code": v.code, "name": v.name, "categories": [c.id for c in v.categories.all()],
        "protocol": v.protocol, "protocol_label": v.get_protocol_display(),
        "api_base": v.api_base, "key_prefix": v.key_prefix, "is_active": v.is_active, "sort_order": v.sort_order,
        "order_email": v.order_email, "contact": v.contact,
        "stores": (opened or {}).get(v.code, 0),
        # 半自動的廠商:價目表上有幾項(啟用中的)
        "items": v.items.filter(is_active=True).count() if v.protocol == Vendor.Protocol.MANUAL else 0,
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
    if "protocol" in data:
        if data["protocol"] not in Vendor.Protocol.values:
            raise Wrong("怎麼接只能選清單上的")
        out["protocol"] = data["protocol"]
    protocol = out.get("protocol", current.protocol if current is not None else Vendor.Protocol.STANDARD)
    if protocol == Vendor.Protocol.MANUAL:
        # 半自動:對方沒有系統,網址不用填(有填就照樣要是 https 的完整網址)
        if "api_base" in data:
            out["api_base"] = clean_base(data["api_base"]) if isinstance(data["api_base"], str) and data["api_base"].strip() else ""
    elif current is None or "api_base" in data or (current is not None and not current.api_base):
        out["api_base"] = clean_base(data.get("api_base"))
    if "order_email" in data:
        email = data["order_email"]
        if not isinstance(email, str) or len(email.strip()) > 200 or (email.strip() and not EMAIL.match(email.strip())):
            raise Wrong("接單信箱的格式不對(沒有就留空)")
        out["order_email"] = email.strip()
    if "contact" in data:
        contact = data["contact"]
        if not isinstance(contact, str) or len(contact.strip()) > 120:
            raise Wrong("聯絡方式最多 120 個字")
        out["contact"] = contact.strip()
    if "key_prefix" in data:
        prefix = data["key_prefix"]
        if not isinstance(prefix, str) or not PREFIX.match(prefix):
            raise Wrong("金鑰的開頭只能是英文、數字、底線、減號,最多 20 個字")
        out["key_prefix"] = prefix
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


# ── 半自動廠商的價目表 ──────────────────────────────────────────────────────
def _item_data(i: VendorItem) -> dict:
    return {"id": i.id, "sku": i.sku, "name": i.name, "spec": i.spec, "kind": i.kind, "unit": i.unit,
            "pack_qty": i.pack_qty, "ref_price": None if i.ref_price is None else str(i.ref_price),
            "is_active": i.is_active, "sort_order": i.sort_order}


def _manual_vendor(pk):
    row = Vendor.objects.filter(pk=pk).first()
    if row is None:
        return None, Response({"detail": "找不到這家廠商"}, status=status.HTTP_404_NOT_FOUND)
    if row.protocol != Vendor.Protocol.MANUAL:
        return None, _bad(f"「{row.name}」是全自動的廠商,商品清單是現問它的系統,不用建價目表")
    return row, None


def _short(value, label, limit, *, required=False) -> str:
    if value is None and not required:
        return ""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        value = str(value)
    if not isinstance(value, str) or len(value.strip()) > limit or (required and not value.strip()):
        raise Wrong(f"{label}{'要填、而且' if required else ''}不能超過 {limit} 個字")
    return value.strip()


def _pack(value) -> int:
    """一包幾個:1 到上限的整數。貼上來的是字(「10」)也收。"""
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_PACK:
        raise Wrong(f"一包幾個要是 1 到 {MAX_PACK} 的整數")
    return value


def _ref_price(value):
    """參考單價:空的 = 沒有;不然 0 到上限、最多兩位小數。貼上來的字可以帶 $ 與千分位逗號。"""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise Wrong("參考單價要是數字(沒有就留空)")
    text = str(value).strip().replace(",", "").replace("$", "").replace("＄", "")
    try:
        price = Decimal(text)
    except InvalidOperation:
        raise Wrong("參考單價要是數字(沒有就留空)") from None
    if not price.is_finite() or price < 0 or price > MAX_PRICE or price != price.quantize(Decimal("0.01")):
        raise Wrong("參考單價要是 0 以上、最多兩位小數")
    return price.quantize(Decimal("0.01"))


def _sku(value) -> str:
    sku = _short(value, "料號", 80)
    if any(c.isspace() for c in sku) or "|" in sku or "#" in sku:
        raise Wrong("料號不能有空白、| 或 #")
    return sku


def _next_sku(vendor, taken) -> str:
    """系統給的料號:N0001、N0002…(這家廠商自己的流水;`taken` = 這一次已經用掉的)。"""
    used = [int(m.group(1)) for sku in [*VendorItem.objects.filter(vendor=vendor).values_list("sku", flat=True), *taken]
            if (m := AUTO_SKU.match(sku))]
    return f"N{max(used, default=0) + 1:04d}"


def _item_values(data, current=None) -> dict:
    out = {}
    if current is None or "name" in data:
        out["name"] = _short(data.get("name"), "品名", 200, required=True)
    for field, label, limit in (("spec", "規格", 120), ("kind", "種類", 40), ("unit", "單位", 10)):
        if field in data:
            out[field] = _short(data[field], label, limit)
    if "pack_qty" in data:
        out["pack_qty"] = _pack(data["pack_qty"])
    if "ref_price" in data:
        out["ref_price"] = _ref_price(data["ref_price"])
    if "is_active" in data:
        out["is_active"] = _flag(data, "is_active")
    if "sort_order" in data:
        out["sort_order"] = _order(data)
    return out


@api_view(["GET", "POST"])
@permission_classes(PLATFORM_ONLY)
def vendor_items(request, pk: int):
    """一家半自動廠商的價目表。POST = 加一項(料號沒填就由系統給)。"""
    vendor, problem = _manual_vendor(pk)
    if problem is not None:
        return problem
    if request.method == "GET":
        return Response({"vendor": vendor.code, "results": [_item_data(i) for i in vendor.items.all()]})
    data = request.data if isinstance(request.data, dict) else {}
    try:
        values = _item_values(data)
        sku = _sku(data.get("sku"))
        with transaction.atomic():
            Vendor.objects.select_for_update().get(pk=vendor.pk)        # 兩個人同時加:料號不會撞
            if sku and VendorItem.objects.filter(vendor=vendor, sku=sku).exists():
                raise Wrong(f"料號「{sku}」這家廠商已經有了")
            item = VendorItem.objects.create(vendor=vendor, sku=sku or _next_sku(vendor, []), **values)
    except Wrong as exc:
        return _bad(exc)
    return Response(_item_data(item), status=status.HTTP_201_CREATED)


@api_view(["PATCH"])
@permission_classes(PLATFORM_ONLY)
def vendor_item(request, pk: int):
    """改價目表上的一項。**料號不能改**(各家門市的叫貨單與對照靠它認);不賣了就停用。"""
    item = VendorItem.objects.filter(pk=pk).first()
    if item is None:
        return Response({"detail": "找不到這一項"}, status=status.HTTP_404_NOT_FOUND)
    data = request.data if isinstance(request.data, dict) else {}
    if "sku" in data and data["sku"] != item.sku:
        return _bad("料號建了不能改(各家門市的叫貨單與對照靠它認);不賣了就停用,另外加一項")
    try:
        values = _item_values(data, item)
    except Wrong as exc:
        return _bad(exc)
    for name, value in values.items():
        setattr(item, name, value)
    item.save()
    return Response(_item_data(item))


IMPORT_FIELDS = ("name", "spec", "kind", "unit", "pack_qty", "ref_price")


def _import_plan(vendor, rows) -> list[dict]:
    """整批貼上的每一列要怎麼處理(只算、不存):new 新增 / update 更新 / same 沒有要改的 / error 有問題。
    有料號照料號對;沒有就照「品名 + 規格」對(對到一筆 = 更新它;對不到 = 新增,料號由系統給)。
    **已經有的那一項,貼上來空著的格子 = 不改**(少貼一欄不會把整欄清掉);要清空請個別修改。"""
    existing = list(vendor.items.all())
    by_sku = {i.sku: i for i in existing}
    by_name: dict[tuple, list] = {}
    for i in existing:
        by_name.setdefault((i.name, i.spec), []).append(i)
    seen_sku, seen_name, taken, out = set(), set(), [], []
    for n, raw in enumerate(rows, start=1):
        row = {"line": n, "action": "error", "problem": "", "sku": "", "id": None}
        try:
            if not isinstance(raw, dict):
                raise Wrong("這一列看不懂")
            name = _short(raw.get("name"), "品名", 200, required=True)
            spec = _short(raw.get("spec"), "規格", 120)
            sku = _sku(raw.get("sku"))
            # 規格跟其他格子一樣:空著 = 不改(照料號更新價錢時,沒貼規格那一欄不能把原本的規格清掉 —— 複審 2026-10-11)
            given = {"name": name, **({"spec": spec} if spec else {})}
            for field, label, limit in (("kind", "種類", 40), ("unit", "單位", 10)):
                if _short(raw.get(field), label, limit):
                    given[field] = _short(raw.get(field), label, limit)
            if raw.get("pack_qty") not in (None, ""):
                given["pack_qty"] = _pack(raw["pack_qty"])
            if _ref_price(raw.get("ref_price")) is not None:
                given["ref_price"] = _ref_price(raw["ref_price"])
            if sku:
                if sku in seen_sku:
                    raise Wrong(f"料號「{sku}」在這一批裡重複了")
                seen_sku.add(sku)
                target = by_sku.get(sku)
            else:
                if (name, spec) in seen_name:
                    raise Wrong("這一批裡有另一列品名與規格一樣(沒有料號分不出是不是同一項)")
                seen_name.add((name, spec))
                same = by_name.get((name, spec), [])
                if len(same) > 1:
                    raise Wrong("價目表上有不只一項叫這個名字,請填料號指定是哪一項")
                target = same[0] if same else None
            if target is None:
                row.update(action="new", sku=sku or "", values={"pack_qty": 1, **given})
            else:
                changed = {k: v for k, v in given.items() if getattr(target, k) != v}
                row.update(action="update" if changed else "same", sku=target.sku, id=target.id, values=changed)
            row.update(name=name, spec=spec)
        except Wrong as exc:
            row.update(problem=str(exc), name=raw.get("name") if isinstance(raw, dict) and isinstance(raw.get("name"), str) else "",
                       spec="")
        out.append(row)
    # 系統給的料號最後才排(照這一批的順序);這一批裡人自己填的料號也算用掉了(有人填 N0001、另一列讓系統給,不能拿到同一個)
    taken.extend(seen_sku)
    for row in out:
        if row["action"] == "new" and not row["sku"]:
            row["sku"] = _next_sku(vendor, taken)
            taken.append(row["sku"])
    return out


def _import_reply(plan, applied: bool) -> dict:
    counts = {k: sum(1 for r in plan if r["action"] == k) for k in ("new", "update", "same", "error")}
    shown = [{"line": r["line"], "action": r["action"], "problem": r["problem"], "sku": r["sku"], "name": r.get("name", ""),
              "spec": r.get("spec", ""),
              "changes": {k: (None if v is None else str(v)) for k, v in r.get("values", {}).items()}} for r in plan]
    return {"rows": shown, "counts": counts, "applied": applied}


@api_view(["POST"])
@permission_classes(PLATFORM_ONLY)
def vendor_items_import(request, pk: int):
    """從 Excel 整批貼上。`apply` 沒給 / false = 只預覽;true = 存(有任何一列有問題就整批不存)。"""
    vendor, problem = _manual_vendor(pk)
    if problem is not None:
        return problem
    data = request.data if isinstance(request.data, dict) else {}
    rows = data.get("rows")
    if not isinstance(rows, list) or not rows:
        return _bad("沒有要貼上的內容")
    if len(rows) > IMPORT_ROWS:
        return _bad(f"一次最多貼 {IMPORT_ROWS} 列")
    if data.get("apply") is not True:
        return Response(_import_reply(_import_plan(vendor, rows), False))
    with transaction.atomic():
        Vendor.objects.select_for_update().get(pk=vendor.pk)            # 鎖住之後才算:跟別人同時加的不會撞料號
        plan = _import_plan(vendor, rows)
        if any(r["action"] == "error" for r in plan):
            return Response({**_import_reply(plan, False), "detail": "有幾列有問題,整批都沒有存"},
                            status=status.HTTP_400_BAD_REQUEST)
        base = (vendor.items.order_by("-sort_order").values_list("sort_order", flat=True).first() or 0)
        for r in plan:
            if r["action"] == "new":
                base += 1
                VendorItem.objects.create(vendor=vendor, sku=r["sku"], sort_order=min(base, MAX_ORDER), **r["values"])
            elif r["action"] == "update":
                VendorItem.objects.filter(pk=r["id"]).update(**r["values"])
    return Response(_import_reply(plan, True))
