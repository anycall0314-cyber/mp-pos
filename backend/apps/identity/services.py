"""商品識別引擎(規則版,不需 AI)。

一條進貨文字 → 對到我的哪個標準商品,並算出「規則型」信心分數(整數 0-100)。
比對階梯(可靠的先比,一命中就停;對齊 docs/product-roadmap.md §7.2):

    ① 條碼(GTIN)精準            → 100,自動
    ② 廠商料號精準              → 99,自動
    ③ 已核准別名 / SKU / 品名精準 → 97,自動(這是「教過一次就自動」的路)
    ④ 品牌 / 容量 / 顏色 + 名稱模糊 → 產候選 + 分數(名稱相似最高封頂 96,不讓它單獨自動)
    ⑤ AI 語意                   → 這版不做

紀律:
- 信心分數由「規則」算(有沒有條碼、名稱涵蓋率、屬性衝突),不是 AI 自評。
- **屬性衝突(容量不同)→ 禁止自動對應**,就算名字很像也擋下(絕不 128G 誤對 256G)。
- 門檻(自動 / 待選)讀 settings,不寫死。
"""
import json
import re
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Case, IntegerField, Q, Value, When

from apps.assistant.parsers import _KV_RE, _PRICE_RE, _QTY_RE, _SERIAL_RE
from apps.catalog.models import Category, Product
from apps.purchasing.serializers import PurchaseOrderSerializer
from apps.purchasing.services import commit_purchase_order

from .models import IntakeBatch, IntakeDocument, IntakeItem, ProductAlias
from .normalize import normalize, normalize_capacity


class IdentityError(Exception):
    """商品識別 / 待確認區流程錯誤;view 轉成 400。"""

# 從純文字裡抓容量 token(128g / 256GB / 1tb),用於衝突檢查。
_CAP_TOKEN_RE = re.compile(r"\d+\s*(?:gb|g|tb|t)\b", re.I)
_TOKEN_SPLIT_RE = re.compile(r"[\s,/、]+")


def _auto_score():
    return getattr(settings, "IDENTITY_AUTO_MATCH_SCORE", 98)


def _review_score():
    return getattr(settings, "IDENTITY_REVIEW_SCORE", 85)


def _detect_capacity(text: str) -> str:
    """從文字抓出容量(正規化);抓不到回空字串。"""
    m = _CAP_TOKEN_RE.search(text or "")
    return normalize_capacity(m.group(0)) if m else ""


def _brief(product, score, reason, conflict=False):
    return {
        "product_id": product.id,
        "sku": product.sku,
        "name": product.name,
        "capacity": product.capacity,
        "color": product.color,
        "score": int(score),
        "reason": reason,
        "conflict": conflict,
    }


def _alias_lookup(tenant, supplier, key, kinds):
    """在別名庫找 normalized_value==key 的一筆(限指定 kinds)。
    supplier 相符或別名為通用(supplier 為空)都算命中。
    """
    if not key:
        return None
    qs = ProductAlias.objects.for_tenant(tenant).filter(
        is_active=True, kind__in=kinds, normalized_value=key
    ).select_related("product").filter(Q(supplier__isnull=True) | Q(supplier=supplier))
    # 有指定廠商的別名(0)優先於通用別名(1)
    return qs.annotate(
        _generic=Case(When(supplier__isnull=True, then=Value(1)),
                      default=Value(0), output_field=IntegerField())
    ).order_by("_generic").first()


def _tokenize(raw_text):
    """拆詞,並把「容量詞」抽掉(容量改當結構化訊號比,不當名稱必須字)。
    回傳 (比對用詞, 容量詞)。
    """
    toks = [t for t in _TOKEN_SPLIT_RE.split((raw_text or "").strip()) if t]
    match_toks = [t for t in toks if not _CAP_TOKEN_RE.fullmatch(t)]
    return match_toks, _detect_capacity(raw_text)


def _candidate_search(tenant, match_toks, raw_text, limit=8):
    """名稱模糊:逐詞 AND icontains(沿用既有 resolver 精神,DB 可攜)。"""
    base = Product.objects.for_tenant(tenant).filter(is_active=True)
    if match_toks:
        cond = Q()
        for tk in match_toks:
            cond &= Q(name__icontains=tk)
        matches = list(base.filter(cond)[:limit])
        if matches:
            return matches
    # 退回:整串 icontains
    return list(base.filter(name__icontains=(raw_text or "").strip())[:limit])


def _name_score(match_toks, product):
    """名稱涵蓋率分數(0-92)。名稱相似永遠低於自動門檻,不讓它單獨自動對應。"""
    if not match_toks:
        return 0
    name_norm = normalize(product.name)
    hit = sum(1 for tk in match_toks if normalize(tk) and normalize(tk) in name_norm)
    return int((hit / len(match_toks)) * 92)


def match_line(tenant, supplier, raw_text, raw_barcode="", raw_vendor_sku=""):
    """對一行進貨做識別。回傳 dict(matched_product / status / confidence / candidates)。"""
    S = IntakeItem.MatchStatus

    # ① 條碼精準(Product.barcode 或 別名 kind=barcode)
    bkey = normalize(raw_barcode)
    if bkey:
        by_field = Product.objects.for_tenant(tenant).filter(
            is_active=True, barcode=raw_barcode.strip()
        ).first()
        alias = _alias_lookup(tenant, supplier, bkey, [ProductAlias.Kind.BARCODE])
        hit = by_field or (alias.product if alias else None)
        if hit:
            return {"matched_product": hit, "status": S.AUTO_MATCHED,
                    "confidence": 100, "candidates": [_brief(hit, 100, "條碼相符")]}

    # ② 廠商料號精準
    vkey = normalize(raw_vendor_sku)
    if vkey:
        alias = _alias_lookup(tenant, supplier, vkey, [ProductAlias.Kind.VENDOR_SKU])
        if alias:
            return {"matched_product": alias.product, "status": S.AUTO_MATCHED,
                    "confidence": 99, "candidates": [_brief(alias.product, 99, "廠商料號相符")]}

    # ③ 已核准別名 / SKU / 品名精準
    tkey = normalize(raw_text)
    alias = _alias_lookup(
        tenant, supplier, tkey,
        [ProductAlias.Kind.VENDOR_NAME, ProductAlias.Kind.LEGACY_NAME, ProductAlias.Kind.OEM_MODEL],
    )
    if alias:
        return {"matched_product": alias.product, "status": S.AUTO_MATCHED,
                "confidence": 97, "candidates": [_brief(alias.product, 97, "已學過的別名相符")]}
    exact = Product.objects.for_tenant(tenant).filter(is_active=True).filter(
        sku__iexact=raw_text.strip()
    ).first()
    if exact:
        return {"matched_product": exact, "status": S.AUTO_MATCHED,
                "confidence": 98, "candidates": [_brief(exact, 98, "品號相符")]}

    # ④ 屬性 + 名稱模糊 → 產候選;容量當結構化訊號:相符加分、不符標衝突
    match_toks, q_cap = _tokenize(raw_text)
    matches = _candidate_search(tenant, match_toks, raw_text)
    if not matches:
        return {"matched_product": None, "status": S.UNKNOWN, "confidence": 0, "candidates": []}

    scored = []
    for p in matches:
        score = _name_score(match_toks, p)
        conflict = False
        reason = "名稱相似"
        if q_cap and p.capacity:
            if normalize_capacity(p.capacity) == q_cap:
                score = min(96, score + 4)
                reason = "名稱相似 + 容量相符"
            else:
                conflict = True
                reason = f"名稱像,但容量對不上(單據 {q_cap} / 商品 {p.capacity})"
        scored.append(_brief(p, score, reason, conflict))
    scored.sort(key=lambda c: (c["conflict"], -c["score"]))
    candidates = scored[:6]

    non_conflict = [c for c in candidates if not c["conflict"]]
    best = non_conflict[0] if non_conflict else None

    # 名稱模糊永遠不夠格「自動」(封頂 96 < 自動門檻),一律進待確認。
    if best is None:
        # 有相似候選但全部容量衝突 → 明確標「屬性衝突」提醒人看
        status = S.CONFLICT if candidates else S.UNKNOWN
        return {"matched_product": None, "status": status, "confidence": 0, "candidates": candidates}
    if best["score"] >= _review_score():
        status = S.NEEDS_REVIEW
    else:
        status = S.UNKNOWN
    return {"matched_product": None, "status": status,
            "confidence": best["score"], "candidates": candidates}


# ─────────────────── 從文字建待確認批次 ───────────────────
def _parse_lines(raw_text):
    """把貼上的多行文字拆成明細行。沿用指令助理的量 / 價 / 序號 regex。
    標頭行(#進貨 供應商=... 這種 key=value 行)略過,供應商 / 倉由外層另外帶。
    回傳 [{raw_text, qty, unit_price, serials}]。
    """
    lines = [ln.strip() for ln in (raw_text or "").splitlines() if ln.strip()]
    items = []
    for ln in lines:
        if ln.startswith("#") or _KV_RE.search(ln):
            continue
        qty_m, price_m, serial_m = _QTY_RE.search(ln), _PRICE_RE.search(ln), _SERIAL_RE.search(ln)
        serials = []
        if serial_m:
            serials = [s for s in re.split(r"[,\s、]+", serial_m.group(1).strip()) if s]
        name = ln
        for m in (qty_m, price_m, serial_m):
            if m and m.start() < len(name):
                name = name[: m.start()]
        name = name.strip(" -•\t")
        if not name:
            continue
        qty = int(qty_m.group(1)) if qty_m else 1
        try:
            unit_price = Decimal(price_m.group(1)) if price_m else Decimal("0")
        except InvalidOperation:
            unit_price = Decimal("0")
        items.append({"raw_text": name, "qty": qty, "unit_price": unit_price, "serials": serials})
    return items


def _add_item(tenant, batch, line_no, *, raw_text, qty=1, unit_price=Decimal("0"),
              serials=None, barcode="", vendor_sku="", ocr_confidence=None):
    """跑識別 + 落一筆 IntakeItem。貼文字 / 拍照兩條路共用。"""
    res = match_line(tenant, batch.supplier, raw_text, raw_barcode=barcode, raw_vendor_sku=vendor_sku)
    return IntakeItem.objects.create(
        tenant=tenant, batch=batch, line_no=line_no, raw_text=raw_text,
        raw_barcode=barcode, raw_vendor_sku=vendor_sku,
        raw_qty=qty, raw_unit_price=unit_price, raw_serials=serials or [],
        matched_product=res["matched_product"], match_status=res["status"],
        match_confidence=res["confidence"], candidates=res["candidates"],
        ocr_confidence=ocr_confidence or {},
    )


def run_intake_from_text(tenant, raw_text, source=IntakeBatch.Source.MANUAL_TEXT,
                         supplier=None, warehouse=None, vendor_doc_no="", user=None):
    """建立一個待確認批次:拆行 → 逐行識別 → 落 IntakeItem。不寫正式庫存。"""
    batch = IntakeBatch.objects.create(
        tenant=tenant, source=source, supplier=supplier, warehouse=warehouse,
        vendor_doc_no=vendor_doc_no, raw_text=raw_text or "", created_by=user,
    )
    for idx, row in enumerate(_parse_lines(raw_text), start=1):
        _add_item(tenant, batch, idx, raw_text=row["raw_text"], qty=row["qty"],
                  unit_price=row["unit_price"], serials=row["serials"])
    _refresh_batch_status(batch)
    return batch


def _to_int_qty(v):
    try:
        return max(1, int(float(str(v).strip() or 1)))
    except (ValueError, TypeError):
        return 1


def _to_price(v):
    try:
        return Decimal(str(v).strip() or "0")
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


def run_intake_from_lines(tenant, lines, source=IntakeBatch.Source.OCR,
                          supplier=None, warehouse=None, vendor_doc_no="",
                          raw_text="", user=None):
    """拍照 / 匯入來源:已是結構化明細 → 逐行識別 → 落 IntakeItem。

    lines 每筆:{raw_name, supplier_sku, barcode, qty, unit_cost, field_confidence}。
    barcode / 料號會餵進識別階梯(條碼、廠商料號精準比),命中率比純品名高。
    """
    batch = IntakeBatch.objects.create(
        tenant=tenant, source=source, supplier=supplier, warehouse=warehouse,
        vendor_doc_no=vendor_doc_no, raw_text=raw_text or "", created_by=user,
    )
    line_no = 0
    for ln in lines or []:
        name = (ln.get("raw_name") or "").strip()
        barcode = (ln.get("barcode") or "").strip()
        vendor_sku = (ln.get("supplier_sku") or "").strip()
        if not name and not barcode and not vendor_sku:
            continue  # 整行空的跳過
        line_no += 1
        _add_item(
            tenant, batch, line_no, raw_text=name, qty=_to_int_qty(ln.get("qty")),
            unit_price=_to_price(ln.get("unit_cost")), barcode=barcode, vendor_sku=vendor_sku,
            ocr_confidence=ln.get("field_confidence") or {},
        )
    _refresh_batch_status(batch)
    return batch


def run_intake_from_image(tenant, uploaded_file, supplier=None, warehouse=None, user=None):
    """拍照入口:存原圖 → 讀圖成明細 → 建待確認批次。原圖與 OCR 結果分開留底(稽核)。

    讀圖模型未設定 → 丟 OcrNotConfigured;讀圖失敗 → 標記 document 失敗並丟 OcrError。
    """
    from .ocr import OcrError, get_ocr_provider

    provider = get_ocr_provider()  # 未設定 → OcrNotConfigured
    data = uploaded_file.read()
    media_type = getattr(uploaded_file, "content_type", "") or "image/jpeg"
    filename = getattr(uploaded_file, "name", "intake.jpg")

    doc = IntakeDocument(tenant=tenant, original_filename=filename, created_by=user)
    doc.image.save(filename, ContentFile(data), save=True)

    try:
        result = provider.read(data, media_type=media_type)
    except OcrError as exc:
        doc.ocr_status = IntakeDocument.OcrStatus.FAILED
        doc.ocr_message = str(exc)[:300]
        doc.save(update_fields=["ocr_status", "ocr_message", "updated_at"])
        raise

    batch = run_intake_from_lines(
        tenant, result.get("lines", []), supplier=supplier, warehouse=warehouse,
        vendor_doc_no=(result.get("doc_no") or ""),
        raw_text=json.dumps(result, ensure_ascii=False), user=user,
    )
    doc.batch = batch
    doc.ocr_status = IntakeDocument.OcrStatus.DONE
    doc.ocr_raw = result
    doc.save(update_fields=["batch", "ocr_status", "ocr_raw", "updated_at"])
    return batch


# ─────────────────── 待確認區逐筆處理 ───────────────────
_PENDING = [
    IntakeItem.MatchStatus.NEEDS_REVIEW,
    IntakeItem.MatchStatus.UNKNOWN,
    IntakeItem.MatchStatus.CONFLICT,
]
_COMMITTABLE = [
    IntakeItem.MatchStatus.AUTO_MATCHED,
    IntakeItem.MatchStatus.RESOLVED,
    IntakeItem.MatchStatus.NEW_PRODUCT,
]


def _learn_alias(item, product):
    """把這行原始文字學成一條別名(廠商層),下次同一家同樣講法自動對應。"""
    text = (item.raw_text or "").strip()
    if not text:
        return
    ProductAlias.objects.get_or_create(
        tenant=item.tenant,
        supplier=item.batch.supplier,
        kind=ProductAlias.Kind.VENDOR_NAME,
        normalized_value=normalize(text),
        defaults={
            "product": product, "value": text,
            "source": ProductAlias.Source.LEARNED, "verified": True,
        },
    )


def _refresh_batch_status(batch):
    if batch.status in (IntakeBatch.Status.COMMITTED, IntakeBatch.Status.CANCELLED):
        return
    pending = batch.items.filter(match_status__in=_PENDING).exists()
    batch.status = IntakeBatch.Status.OPEN if pending else IntakeBatch.Status.RESOLVED
    batch.save(update_fields=["status", "updated_at"])


def resolve_item_match(item, product, learn_alias=True, user=None):
    """把一行對應到既有商品(選候選 / 手動指定)。"""
    item.matched_product = product
    item.match_status = IntakeItem.MatchStatus.RESOLVED
    item.resolved_by = user
    item.save(update_fields=["matched_product", "match_status", "resolved_by", "updated_at"])
    if learn_alias:
        _learn_alias(item, product)
    _refresh_batch_status(item.batch)
    return item


def resolve_item_new_product(item, data, user=None):
    """從一行建立新商品並對應。"""
    try:
        cat = Category.objects.for_tenant(item.tenant).get(id=data["category"])
    except Category.DoesNotExist:
        raise IdentityError("找不到指定的類別")
    name = (data.get("name") or item.raw_text).strip()
    product = Product.objects.create(
        tenant=item.tenant, category=cat, name=name,
        capacity=data.get("capacity", ""), color=data.get("color", ""),
        region_version=data.get("region_version", ""),
        requires_serial=data.get("requires_serial", True),
    )
    item.matched_product = product
    item.match_status = IntakeItem.MatchStatus.NEW_PRODUCT
    item.resolved_by = user
    item.save(update_fields=["matched_product", "match_status", "resolved_by", "updated_at"])
    if data.get("learn_alias", True):
        _learn_alias(item, product)
    _refresh_batch_status(item.batch)
    return product


def reject_item(item, user=None):
    item.match_status = IntakeItem.MatchStatus.REJECTED
    item.resolved_by = user
    item.save(update_fields=["match_status", "resolved_by", "updated_at"])
    _refresh_batch_status(item.batch)
    return item


def commit_batch(batch, user=None):
    """全部對應完 → 組進貨單 → 走既有 commit_purchase_order 過帳(帳本唯一入口)。"""
    if batch.status == IntakeBatch.Status.COMMITTED:
        raise IdentityError("這批已經過帳了")
    if not batch.supplier_id or not batch.warehouse_id:
        raise IdentityError("請先指定廠商與入庫倉再過帳")
    if batch.items.filter(match_status__in=_PENDING).exists():
        raise IdentityError("還有未確認的明細,請先逐筆處理完")

    rows = batch.items.filter(
        match_status__in=_COMMITTABLE, matched_product__isnull=False
    ).order_by("line_no")
    payload_items = [{
        "product": it.matched_product_id,
        "qty": it.raw_qty,
        "unit_price": str(it.raw_unit_price),
        "serial_numbers": list(it.raw_serials or []),
    } for it in rows]
    if not payload_items:
        raise IdentityError("沒有可過帳的明細(都被駁回了?)")

    payload = {
        "supplier": batch.supplier_id,
        "warehouse": batch.warehouse_id,
        "tax_method": "taxable_included",
        "items": payload_items,
    }
    ser = PurchaseOrderSerializer(data=payload)
    ser.is_valid(raise_exception=True)
    with transaction.atomic():
        ser.save(tenant=batch.tenant, created_by=user)
        commit_purchase_order(ser.instance)
        batch.committed_purchase_order_id = ser.instance.id
        batch.status = IntakeBatch.Status.COMMITTED
        batch.save(update_fields=["committed_purchase_order_id", "status", "updated_at"])
    return ser.instance
