"""商品匯入(表格檔或貼上的表格)。

2026-10-23 起(全站檢視 D7 / D8;「批次貼上」併進來):
- 一開始先選類別(`category`,每一列沒填類別的用它),還有「按數量 / 逐件記序號」(`requires_serial`,
  **一定要選、沒有預設** —— 紅隊:進過貨就改不回來,不能讓人照預設按確認)。
- 欄位(標題可中文或英文):必填 品名;選填 規格、建議售價、條碼、類別(名稱或代碼,只收已經有的)、品號(空的由系統照類別產生)、安全庫存。
- **主機類別(手機 / 平板 / 穿戴)、中古機類別不能用這裡建**:手機照平台型號庫,走「新增手機型號」。
- 類別不再自動建立(打錯字會多出一個類別,也沒有主機 / 配件的設定)。
- 已存在的品號 / 品名、可能重複的跳過(列出原因)。
- 所有新商品 lifecycle_status='pending'(待補齊),不影響庫存警示推論
"""
from __future__ import annotations

import csv
import io
from decimal import Decimal, InvalidOperation
from io import BytesIO
from typing import Any

from django.db import transaction
from openpyxl import load_workbook

from apps.core.money import round_money
from apps.identity.dedup import check_new_product
from apps.identity.product_match import MatchContext

from .models import Category, Product

# 標題列關鍵字 → 內部欄位
_FIELD_MAP: dict[str, str] = {
    # name
    "品名": "name",
    "商品名稱": "name",
    "名稱": "name",
    "name": "name",
    # category
    "類別": "category",
    "類別名稱": "category",
    "類別代碼": "category",
    "category": "category",
    # spec
    "規格": "spec",
    "spec": "spec",
    # sku
    "品號": "sku",
    "sku": "sku",
    # safety_stock
    "安全庫存": "safety_stock",
    "safety_stock": "safety_stock",
    "safety": "safety_stock",
    # list_price
    "建議售價": "list_price",
    "建議零售價": "list_price",
    "售價": "list_price",
    "list_price": "list_price",
    # barcode
    "條碼": "barcode",
    "barcode": "barcode",
}


def _norm_header(h: Any) -> str:
    return str(h or "").strip().lower()


def _normalize_row(raw: dict) -> dict:
    """標題對應到內部欄位 key,忽略不認識的 column。"""
    out: dict = {}
    for header, val in raw.items():
        target = _FIELD_MAP.get(_norm_header(header)) or _FIELD_MAP.get(str(header or "").strip())
        if target:
            out[target] = val
    return out


def _read_xlsx(file_obj) -> list[dict]:
    wb = load_workbook(
        filename=BytesIO(file_obj.read()), read_only=True, data_only=True
    )
    ws = wb.active
    rows_iter = ws.iter_rows(values_only=True)
    header = next(rows_iter, None)
    if not header:
        return []
    header = [str(h or "").strip() for h in header]
    out = []
    for row in rows_iter:
        if row is None:
            continue
        d = {}
        for i, val in enumerate(row):
            if i < len(header) and header[i]:
                d[header[i]] = val
        # 整列空白跳過
        if not any((v is not None and str(v).strip()) for v in d.values()):
            continue
        out.append(d)
    return out


def _read_csv(file_obj) -> list[dict]:
    content = file_obj.read()
    if isinstance(content, bytes):
        # 去 BOM + decode
        if content.startswith(b"\xef\xbb\xbf"):
            content = content[3:]
        text = content.decode("utf-8-sig", errors="replace")
    else:
        text = content
    reader = csv.DictReader(io.StringIO(text))
    return [dict(r) for r in reader]


def _number(val) -> Decimal:
    """表格裡的數字:空的 = 0;千分位、$、元、空白去掉(Excel 複製出來常有「1,290」)。
    看不懂、負的丟 ValueError —— 不能默默變成 0(Codex 複審 P1:以前「1,290」會存成售價 0)。"""
    if val is None:
        return Decimal("0")
    text = str(val).strip()
    for junk in (",", "，", "$", "NT", "元", " "):
        text = text.replace(junk, "")
    if text == "":
        return Decimal("0")
    try:
        num = Decimal(text)
    except InvalidOperation:
        raise ValueError(str(val).strip())
    if not num.is_finite() or num < 0:
        raise ValueError(str(val).strip())
    return num


DEVICE_CATEGORY = "手機、平板、穿戴請用「手機型號」建"
MAX_ROWS = 2000


def blocks_import(cat: Category) -> bool:
    """主機類別、中古機類別不收:那種商品一台一個序號、照平台型號庫建。"""
    return cat.holds_devices or cat.is_secondhand_default


def read_rows(file_obj, filename: str) -> list[dict]:
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if ext in ("xlsx", "xls"):
        return _read_xlsx(file_obj)
    if ext == "csv":
        return _read_csv(file_obj)
    raise ValueError(f"不支援的檔案格式 .{ext}(請使用 .xlsx 或 .csv)")


@transaction.atomic
def import_products_from_file(
    tenant, file_obj=None, filename: str = "", dry_run: bool = True, *,
    rows: list[dict] | None = None, first_row: int = 2, category: Category, requires_serial: bool,
    allows_commission: bool = False,
) -> dict:
    """主入口:檔案(`file_obj`)或貼上的表格(`rows`,每一列 {標題: 值})。dry_run=True 不寫入資料庫(用於預覽)。
    `category` / `requires_serial` 由呼叫端先驗好(view 擋掉沒選、主機類別)。"""
    raw_rows = list(rows) if rows is not None else read_rows(file_obj, filename)
    if len(raw_rows) > MAX_ROWS:
        raise ValueError(f"一次最多 {MAX_ROWS:,} 列,請分批")

    # 預載既有 cache
    cats = list(Category.objects.for_tenant(tenant))
    cat_by_code = {c.code.strip().lower(): c for c in cats}
    cat_by_name = {c.name.strip(): c for c in cats}
    existing_skus = set(
        Product.objects.for_tenant(tenant).values_list("sku", flat=True)
    )
    existing_names = set(
        Product.objects.for_tenant(tenant).values_list("name", flat=True)
    )

    success_rows: list[dict] = []
    skip_rows: list[dict] = []
    match_context = MatchContext(tenant)

    sid = transaction.savepoint()

    for idx, raw in enumerate(raw_rows, start=first_row):  # 檔案的第 1 行是標題
        norm = _normalize_row(raw)
        name = (str(norm.get("name") or "")).strip()
        sku = (str(norm.get("sku") or "")).strip()
        category_raw = (str(norm.get("category") or "")).strip()

        def skip(reason):
            skip_rows.append({"row_no": idx, "sku": sku, "name": name, "reason": reason})

        if not name:
            skip("沒有品名")
            continue
        # 類別:沒填用一開始選的;有填先試代碼(精確)、再試名稱;找不到不建
        cat = category
        if category_raw:
            cat = cat_by_code.get(category_raw.lower()) or cat_by_name.get(category_raw)
            if cat is None:
                skip(f"類別「{category_raw}」不存在")
                continue
        if blocks_import(cat):
            skip(DEVICE_CATEGORY)
            continue

        try:
            list_price = round_money(_number(norm.get("list_price")))
        except ValueError as bad:
            skip(f"建議售價「{bad}」看不懂")
            continue
        try:
            safety = int(round_money(_number(norm.get("safety_stock"))))
        except ValueError as bad:
            skip(f"安全庫存「{bad}」看不懂")
            continue

        if sku and sku in existing_skus:
            skip_rows.append(
                {
                    "row_no": idx,
                    "sku": sku,
                    "name": name,
                    "reason": f"品號 {sku} 已存在",
                }
            )
            continue
        if name in existing_names:
            skip_rows.append(
                {
                    "row_no": idx,
                    "sku": sku,
                    "name": name,
                    "reason": f"品名「{name}」已存在",
                }
            )
            continue

        # 防重複:匯入不替人按「不同款」。可能重複的列先不建,列出來讓人
        # 到商品頁單筆新增、看過候選再決定。
        dup = check_new_product(
            tenant, name=name, barcode=(str(norm.get("barcode") or "")).strip(),
            context=match_context,
        )
        if dup is not None:
            skip_rows.append(
                {
                    "row_no": idx,
                    "sku": sku,
                    "name": name,
                    "reason": dup.message + "(要建請到商品頁單筆新增並說明差異)",
                }
            )
            continue

        barcode = (str(norm.get("barcode") or "")).strip()

        p = Product(
            tenant=tenant,
            sku=sku,                      # 空的由 Product.save 照類別產生
            name=name,
            spec=(str(norm.get("spec") or "")).strip(),
            category=cat,
            list_price=list_price,
            safety_stock=safety,
            barcode=barcode,
            requires_serial=requires_serial,
            allows_commission=allows_commission,
            lifecycle_status=Product.LifecycleStatus.PENDING,
            is_active=True,
        )
        p.save()
        match_context.add(p)

        existing_skus.add(p.sku)
        existing_names.add(name)
        success_rows.append(
            {
                "row_no": idx,
                "sku": p.sku if sku else "",          # 系統產生的不寫(預覽跟真的匯入可能不是同一號)
                "name": name,
                "category": cat.name,
                "list_price": int(list_price),
            }
        )

    if dry_run:
        transaction.savepoint_rollback(sid)
    else:
        transaction.savepoint_commit(sid)

    return {
        "dry_run": dry_run,
        "total_rows": len(raw_rows),
        "success_count": len(success_rows),
        "skip_count": len(skip_rows),
        "success_rows": success_rows[:200],
        "skip_rows": skip_rows[:200],
    }
