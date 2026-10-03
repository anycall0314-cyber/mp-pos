"""商品識別引擎(規則版,不需 AI)。

一條進貨文字 → 對到我的哪個標準商品,並算出「規則型」信心分數(整數 0-100)。
比對階梯(可靠的先比,一命中就停;對齊 docs/product-roadmap.md §7.2):

    ① 條碼(GTIN)精準            → 100,自動
    ② 廠商料號精準              → 99,自動
    ③ 已核准別名 / SKU / 品名精準 → 97,自動(這是「教過一次就自動」的路)
    ④ 機型 / 顏色 / 款式特徵相符   → 產候選 + 分數(最高封頂 96,不讓它單獨自動)
       這一級與進貨搜尋、新增前防重複共用 `product_match.find_candidates`
    ⑤ AI 語意                   → 這版不做

紀律:
- 信心分數由「規則」算(有沒有條碼、名稱涵蓋率、屬性衝突),不是 AI 自評。
- **屬性衝突(容量不同)→ 禁止自動對應**,就算名字很像也擋下(絕不 128G 誤對 256G)。
- 門檻(自動 / 待選)讀 settings,不寫死。
"""
import hashlib
import json
import re
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import IntegrityError, connection, transaction
from django.db.models import Case, IntegerField, Q, Value, When
from django.utils import timezone

from apps.assistant.parsers import _KV_RE, _PRICE_RE, _QTY_RE, _SERIAL_RE
from apps.catalog.models import Category, Product
from apps.inventory.models import ProductSerial, ProductSerialIdentifier
from apps.purchasing.serializers import PurchaseOrderSerializer
from apps.purchasing.services import commit_purchase_order

from .models import (
    IntakeBatch,
    IntakeDocument,
    IntakeItem,
    IntakeReceivedUnit,
    IntakeUnitIdentifier,
    ProductAlias,
)
from .dedup import guard_new_product, record_distinct_decision
from .normalize import (
    ALIAS_VALUE_MAX,
    alias_key,
    normalize_capacity,
    normalize_serial,
)
from .product_match import (
    COVERS,
    EXACT,
    MatchResult,
    build_terms,
    find_candidates,
    is_broad_phrase,
)


class IdentityError(Exception):
    """商品識別 / 待確認區流程錯誤;view 轉成 400。"""

# 從純文字裡抓容量 token(128g / 256GB / 1tb),用於衝突檢查。
_CAP_TOKEN_RE = re.compile(r"\d+\s*(?:gb|g|tb|t)\b", re.I)


def _auto_score():
    return getattr(settings, "IDENTITY_AUTO_MATCH_SCORE", 98)


def _review_score():
    return getattr(settings, "IDENTITY_REVIEW_SCORE", 85)


def _detect_capacity(text: str) -> str:
    """從文字抓出容量(正規化);抓不到回空字串。"""
    m = _CAP_TOKEN_RE.search(text or "")
    return normalize_capacity(m.group(0)) if m else ""


# 地區版本關鍵字 → 標準碼(顏色因同義詞太雜,留到 P1 的 CanonicalTermAlias 再做衝突)
_REGION_TOKENS = {
    "台版": "TW", "臺版": "TW", "台灣版": "TW", "國際版": "INTL",
    "港版": "HK", "美版": "US", "陸版": "CN", "中國版": "CN", "日版": "JP",
}


def _detect_region(text: str) -> str:
    t = text or ""
    for k, v in _REGION_TOKENS.items():
        if k in t:
            return v
    return ""


def _norm_region(val: str) -> str:
    val = (val or "").strip()
    if not val:
        return ""
    for k, v in _REGION_TOKENS.items():
        if k in val:
            return v
    return val.lower()


def _brief(product, score, reason, conflict=False):
    return {
        "product_id": product.id,
        "sku": product.sku,
        "name": product.name,
        "capacity": product.capacity,
        "color": product.color,
        # 停售 / 封存的商品也會被列成候選(賣完一段時間再進貨是常態),
        # 前端要看得出來這筆需要「確認恢復」而不是直接當一般商品用。
        "is_active": product.is_active,
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
    # 只有「已確認(verified)」的別名才可用於自動對應(對齊計畫 P0-2)
    qs = ProductAlias.objects.for_tenant(tenant).filter(
        is_active=True, verified=True, kind__in=kinds, normalized_value=key
    ).select_related("product").filter(Q(supplier__isnull=True) | Q(supplier=supplier))
    # 有指定廠商的別名(0)優先於通用別名(1)
    return qs.annotate(
        _generic=Case(When(supplier__isnull=True, then=Value(1)),
                      default=Value(0), output_field=IntegerField())
    ).order_by("_generic").first()


def _identifier_confidence(reasons):
    """可靠識別的信心分數:條碼 100 > 廠商料號 99 > 品號 98 > 已確認的叫法 97。"""
    text = "、".join(reasons)
    if "條碼" in text:
        return 100
    if "廠商料號" in text:
        return 99
    if "品號" in text:
        return 98
    return 97


def _exact_hit(product, confidence, reason):
    """精準命中的回傳值。商品已停售時降成待確認,不直接自動對應。

    賣完被停用、過一陣子再進貨是常態,舊品號應該沿用而不是重建。但「恢復
    一個已停售商品」要人點頭,不能靠一張進貨單就悄悄把它復活。
    """
    S = IntakeItem.MatchStatus
    if not product.is_active:
        return {
            "matched_product": None,
            "status": S.NEEDS_REVIEW,
            "confidence": confidence,
            "candidates": [_brief(product, confidence, f"{reason}(此商品已停售,確認後恢復)")],
        }
    return {
        "matched_product": product,
        "status": S.AUTO_MATCHED,
        "confidence": confidence,
        "candidates": [_brief(product, confidence, reason)],
    }


def match_line(tenant, supplier, raw_text, raw_barcode="", raw_vendor_sku=""):
    """對一行進貨做識別。回傳 dict(matched_product / status / confidence / candidates)。"""
    S = IntakeItem.MatchStatus

    # ①②③ 可靠識別(條碼 / 廠商料號 / 已確認別名 / 品號)與 ④ 特徵候選都交給
    # 共用的 find_candidates。它會把**所有**命中的商品收齊:兩個商品共用同一個
    # 條碼、別名表與來源表對同一個料號各指各的,都會回衝突讓人看。這裡以前是
    # 逐階段 `.first()`,遇到那種資料會靜默挑一筆自動對應,貨就入錯了。
    found = find_candidates(
        tenant, raw_text, supplier=supplier,
        barcode=raw_barcode, vendor_sku=raw_vendor_sku, limit=8,
    )
    products = {
        p.id: p
        for p in Product.objects.for_tenant(tenant).filter(id__in=found.product_ids)
    }
    if found.status == MatchResult.EXISTING:
        c = found.candidates[0]
        return _exact_hit(
            products[c.product_id], _identifier_confidence(c.reasons),
            "、".join(c.reasons),
        )
    if found.status == MatchResult.CONFLICT:
        return {
            "matched_product": None, "status": S.CONFLICT, "confidence": 0,
            "candidates": [
                _brief(products[c.product_id], 100, "、".join(c.reasons), True)
                for c in found.candidates
            ],
        }
    if not found.candidates:
        return {"matched_product": None, "status": S.UNKNOWN, "confidence": 0, "candidates": []}

    # 容量 / 地區版本用商品的結構化欄位再把關一次:品名沒寫容量但欄位有填的,
    # 比對特徵時看不到,這裡補上(絕不 128G 誤對 256G)。
    q_cap = _detect_capacity(raw_text)
    q_region = _detect_region(raw_text)
    scored = []
    for c in found.candidates:
        p = products[c.product_id]
        conflict = c.conflict
        notes = list(c.reasons) + list(c.differences)
        if q_cap and p.capacity and normalize_capacity(p.capacity) != q_cap:
            conflict = True
            notes.append(f"容量對不上(單據 {q_cap} / 商品 {p.capacity})")
        if q_region and p.region_version and _norm_region(p.region_version) != q_region:
            conflict = True
            notes.append(f"版本對不上(單據 {q_region} / 商品 {p.region_version})")
        # 已確認的叫法但現在有別款也符合時,它會以「識別」等級排在候選第一個;
        # 分數封頂 96,不讓它看起來像可以自動對應
        scored.append(_brief(p, min(c.score, 96), "、".join(notes), conflict))
    scored.sort(key=lambda c: (c["conflict"], not c["is_active"], -c["score"]))
    candidates = scored[:6]

    non_conflict = [c for c in candidates if not c["conflict"]]
    best = non_conflict[0] if non_conflict else None

    # 特徵相符永遠不夠格「自動」(封頂 96 < 自動門檻),一律進待確認。
    if best is None:
        # 有相似候選但全部衝突 → 明確標「屬性衝突」提醒人看
        return {"matched_product": None, "status": S.CONFLICT, "confidence": 0,
                "candidates": candidates}
    status = S.NEEDS_REVIEW if best["score"] >= _review_score() else S.UNKNOWN
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
        conf = ln.get("field_confidence") or {}
        serials = list(ln.get("serial_numbers") or ln.get("document_identifiers") or [])
        item = _add_item(
            tenant, batch, line_no, raw_text=name, qty=_to_int_qty(ln.get("qty")),
            unit_price=_to_price(ln.get("unit_cost")), serials=serials,
            barcode=barcode, vendor_sku=vendor_sku, ocr_confidence=conf,
        )
        # 低 OCR 信心 → 即使字串精準也降級為待覆核(對齊計畫 P0-2)
        if item.match_status == IntakeItem.MatchStatus.AUTO_MATCHED and _low_ocr_conf(conf):
            item.match_status = IntakeItem.MatchStatus.NEEDS_REVIEW
            item.save(update_fields=["match_status", "updated_at"])
    _refresh_batch_status(batch)
    return batch


def _low_ocr_conf(conf):
    """關鍵欄位 OCR 信心低於門檻 → 視為低信心(門檻讀 settings)。"""
    thr = getattr(settings, "OCR_MIN_FIELD_CONFIDENCE", 0.7)
    for k in ("raw_name", "barcode", "qty", "unit_cost"):
        v = conf.get(k)
        if isinstance(v, (int, float)) and v < thr:
            return True
    return False


def run_intake_from_image(tenant, uploaded_file, supplier=None, warehouse=None, user=None):
    """拍照入口:存原圖 → 讀圖成明細 → 建待確認批次。原圖與 OCR 結果分開留底(稽核)。

    讀圖模型未設定 → 丟 OcrNotConfigured;讀圖失敗 → 標記 document 失敗並丟 OcrError。
    """
    from .ocr import OcrError, get_ocr_provider

    provider = get_ocr_provider()  # 未設定 → OcrNotConfigured
    data = uploaded_file.read()
    media_type = getattr(uploaded_file, "content_type", "") or "image/jpeg"
    filename = getattr(uploaded_file, "name", "intake.jpg")

    content_hash = hashlib.sha256(data).hexdigest()
    # 同一檔案若已在「已過帳」批次入庫過 → 擋下(可重傳以救回失敗 / 取消的流程)
    if IntakeDocument.objects.for_tenant(tenant).filter(
        content_hash=content_hash, batch__status=IntakeBatch.Status.COMMITTED
    ).exists():
        raise IdentityError("這張單據的檔案已經入庫過了(重複防呆)")

    doc = IntakeDocument(
        tenant=tenant, original_filename=filename,
        content_hash=content_hash, created_by=user,
    )
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


def _phrase_can_auto_match(tenant, supplier, value, product):
    """這個叫法夠不夠格當「下次直接對應」的別名。

    不夠格的兩種:
    - 太籠統:只寫機型 / 只寫類別 / 只寫顏色(`reno16`、`皮套`、`藍`)。
    - 同一句話還有別款也符合(`reno16 皮套 藍` 同時符合側翻款與掀蓋款)。

    不夠格的仍然會記下來,但只當搜尋關鍵字(verified=False):找得到候選,
    不會自動對應,也不會佔住唯一鍵讓別款記不進來。
    """
    terms = build_terms(
        Category.objects.for_tenant(tenant).values_list("name", flat=True)
    )
    if is_broad_phrase(value, terms):
        return False
    found = find_candidates(tenant, value, supplier=supplier, limit=10, with_related=False)
    mine = next((c for c in found.candidates if c.product_id == product.id), None)
    # 這句話只是商品品名的一部分(品名是「Reno16 側翻皮套 藍」,叫法是「reno16 藍」):
    # 現在只有一款符合,不代表以後也是。少講的那幾項正是用來分辨同系列別款的,
    # 所以不給自動對應資格。(用特徵本來就搜得到它,記成關鍵字不吃虧。)
    if mine is not None and mine.level == COVERS:
        return False
    for c in found.candidates:
        if c.product_id == product.id or not c.is_active:
            continue
        if c.level == EXACT or (c.level == COVERS and (mine is None or mine.level != EXACT)):
            return False
    return True


def _upsert_keyword(tenant, supplier, kind, value, key, product, user=None):
    """記成搜尋關鍵字(不取得自動對應資格)。同一句話可以掛在多個商品上。"""
    existing = (
        ProductAlias.objects.for_tenant(tenant)
        .filter(is_active=True, kind=kind, normalized_value=key,
                supplier=supplier, product=product)
        .order_by().first()
    )
    if existing is not None:
        return existing, "kept"
    alias = ProductAlias.objects.create(
        tenant=tenant, supplier=supplier, kind=kind, value=value, product=product,
        source=ProductAlias.Source.LEARNED, verified=False,
        created_by=user, updated_by=user,
    )
    return alias, "keyword"


class _Owner:
    """某個識別目前的擁有者(來源不是同類別名時用;介面跟 ProductAlias 一樣有
    `.product` / `.value`,呼叫端不用分辨是哪一種)。"""

    def __init__(self, product, value):
        self.product = product
        self.value = value


def _advisory_lock(payload: str):
    """交易層級的 advisory lock(交易結束自動釋放)。非 PostgreSQL 跳過。"""
    if connection.vendor != "postgresql":
        return
    n = int.from_bytes(
        hashlib.sha256(payload.encode("utf-8")).digest()[:8], "big", signed=True
    )
    with connection.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", [n])


def _identifier_payload(tenant, supplier, kind, key, value):
    """一個識別對應的鎖名。同一類識別用同一把鎖。"""
    if kind == ProductAlias.Kind.BARCODE:
        # 跟新增商品時鎖條碼用的是同一把(見 dedup._lock_barcode)
        return f"product-barcode:{tenant.id}:{value}"
    if kind == ProductAlias.Kind.VENDOR_SKU:
        # 跟 _lock_vendor_sku 同一把
        return f"{tenant.id}:{supplier.id if supplier is not None else 0}:{key}"
    return f"alias-name:{tenant.id}:{supplier.id if supplier else 0}:{key}"


def _lock_identifier(tenant, supplier, kind, key, value):
    """「認領一個識別」整段序列化。

    查詢端(`identifier_hits`)是跨來源一起看的:商品自己的條碼欄與條碼別名、
    別名表與來源表的料號、各種名稱類別名。寫入端如果各鎖各的,兩個人就能同時
    把同一個識別寫到不同來源、指到不同商品。同一類識別用同一把鎖。
    """
    if connection.vendor == "postgresql" and key:
        _advisory_lock(_identifier_payload(tenant, supplier, kind, key, value))


def lock_identifiers(tenant, supplier, *, name="", vendor_sku="", barcode=""):
    """一筆輸入會用到的名稱 / 料號 / 條碼鎖,**一次收齊、照固定順序取**。

    分開取的話順序會因流程而異:「建新品」先鎖條碼、後面學別名才鎖名稱;
    「對應既有商品」則是名稱 → 料號 → 條碼。兩筆同時處理同一個名稱與條碼時
    就會互等,PostgreSQL 砍掉其中一筆、使用者看到 500。同一個交易裡重複取同一把
    advisory lock 沒有副作用,所以之後各步驟自己再取一次也沒關係。
    """
    payloads = set()
    for kind, raw, scope in (
        (ProductAlias.Kind.VENDOR_NAME, name, supplier),
        (ProductAlias.Kind.VENDOR_SKU, vendor_sku, supplier),
        (ProductAlias.Kind.BARCODE, barcode, None),
    ):
        value = (str(raw) if raw is not None else "").strip()[:ALIAS_VALUE_MAX]
        key = alias_key(value)
        if key:
            payloads.add(_identifier_payload(tenant, scope, kind, key, value))
    if connection.vendor == "postgresql":
        for payload in sorted(payloads):
            _advisory_lock(payload)


def _other_source_owner(tenant, supplier, kind, key, value, exclude_alias_id=None):
    """這個識別在「別的來源」是不是已經屬於某個商品。

    同類別名彼此的衝突由 `_upsert_alias` 自己處理(可以改指);這裡看的是它
    看不到的那些:商品主檔的條碼欄、供應商來源表的料號、別種名稱類別名。
    這些都不能靠停用一條別名來改指,所以一律回衝突。
    """
    if kind == ProductAlias.Kind.BARCODE:
        owner = (
            Product.objects.for_tenant(tenant).filter(barcode=value)
            .order_by("-is_active", "sku").first()
        )
        return _Owner(owner, value) if owner is not None else None
    if kind == ProductAlias.Kind.VENDOR_SKU:
        if supplier is None:
            return None
        from apps.catalog.models import SupplierProduct

        sp = (
            SupplierProduct.objects.for_tenant(tenant)
            .filter(is_active=True, supplier=supplier, vendor_sku_key=key)
            .order_by().select_related("product").first()
        )
        return _Owner(sp.product, sp.vendor_sku) if sp is not None else None
    other = (
        ProductAlias.objects.for_tenant(tenant)
        .filter(is_active=True, verified=True, kind__in=_NAME_KINDS,
                normalized_value=key, supplier=supplier)
        .exclude(kind=kind).exclude(pk=exclude_alias_id)
        .order_by().select_related("product").first()
    )
    return other


def _upsert_alias(tenant, supplier, kind, value, product, allow_repoint=True,
                  verified=True, user=None):
    """學一條別名。同一個講法已經指到別的商品時,把舊的停用再建新的。

    `verified=False`:只記成搜尋關鍵字,見 `_upsert_keyword`。

    舊版用 `get_or_create`,學錯的對應會一直沿用 —— 人這次明明選了別的商品,
    下一批進貨還是會被帶回錯的品號,而且看不出哪裡錯。

    `allow_repoint=False` 用在「人看不到的欄位」(條碼 / 料號):那些值多半
    來自 OCR,店員是看品名決定要選哪個商品的,不該讓一個他沒看過的條碼
    去把別人正確的對應改掉。這種情況只學新的 key,已有對應就原封不動。

    回傳 (alias, action):
    created / repointed / kept / keyword / skipped / conflict。
    """
    # 先截斷再算比對鍵。反過來(用完整字串算 key、存進去卻被 save() 用
    # 截斷後的值重算)會讓查詢永遠找不到、再學一次又撞唯一鍵變成 500。
    value = (str(value) if value is not None else "").strip()[:ALIAS_VALUE_MAX]
    key = alias_key(value)
    if not key:
        return None, "skipped"

    # 條碼是 GTIN,同一個租戶內跨廠唯一(uniq_alias_barcode 不看 supplier),
    # 所以查重與存檔都不分廠商。
    alias_supplier = None if kind == ProductAlias.Kind.BARCODE else supplier

    if not verified and kind != ProductAlias.Kind.BARCODE:
        return _upsert_keyword(tenant, alias_supplier, kind, value, key, product, user)

    def _match_qs():
        # order_by() 清掉 Meta.ordering。Meta.ordering 含 "product",Django 會為了
        # 排序 JOIN catalog_product,`select_for_update()` 就連 Product 一起鎖;
        # 那把鎖跟過帳流程反向等待,實測會 deadlock。這裡只會取一列,不需要排序。
        qs = ProductAlias.objects.for_tenant(tenant).filter(
            is_active=True, kind=kind, normalized_value=key
        ).order_by()
        if kind != ProductAlias.Kind.BARCODE:
            # 只有「已確認」的那一筆才是這句話的擁有者;關鍵字可以有很多筆、
            # 各指各的商品,拿它們來判斷「已經指到別人」會誤報衝突。
            qs = qs.filter(supplier=alias_supplier, verified=True)
        return qs

    def _keep(existing):
        """命中同商品:補齊該補的欄位再回傳。

        併發重查那條路也要走這裡 —— 另一個請求可能剛寫進一條 verified=False
        或還綁著廠商的條碼別名,不補的話下次就靠它自動對應不到。
        """
        fields = []
        if not existing.verified:
            existing.verified = True
            fields.append("verified")
        # 舊資料可能把條碼別名綁在某一廠商底下,別家帶同一個條碼就查不到。
        # 既然條碼是全域唯一,命中同商品時順手改成通用。
        if kind == ProductAlias.Kind.BARCODE and existing.supplier_id is not None:
            existing.supplier = None
            fields.append("supplier")
        if fields:
            existing.updated_by = user
            existing.save(update_fields=fields + ["updated_by", "updated_at"])
        return existing, "kept"

    # 先鎖再查:同一個識別的認領要一個一個來。然後看別的來源有沒有人已經認領。
    _lock_identifier(tenant, alias_supplier, kind, key, value)
    elsewhere = _other_source_owner(tenant, alias_supplier, kind, key, value)
    if elsewhere is not None and elsewhere.product.id != product.id:
        return elsewhere, "conflict"

    hit = _match_qs().select_for_update().first()
    if hit is not None:
        if hit.product_id == product.id:
            return _keep(hit)
        if not allow_repoint:
            return hit, "conflict"
        # 指到別的商品 → 停用舊的(留下軌跡),再建一條新的。
        # 不能直接改 product:歷史上這條別名曾經代表另一個商品,
        # 改掉會讓過去的對應紀錄跟著變,追不出當時發生什麼事。
        old_note = f"改對應:{hit.product_id} → {product.id}"
        hit.is_active = False
        hit.note = (f"{hit.note} / {old_note}" if hit.note else old_note)[:200]
        hit.updated_by = user
        hit.save(update_fields=["is_active", "note", "updated_by", "updated_at"])

    def _create():
        # 這個商品先前把同一句話記成關鍵字的,直接升級那一筆,不另外多建一筆
        if kind != ProductAlias.Kind.BARCODE:
            keyword = (
                ProductAlias.objects.for_tenant(tenant)
                .filter(is_active=True, kind=kind, normalized_value=key,
                        supplier=alias_supplier, product=product, verified=False)
                .order_by().first()
            )
            if keyword is not None:
                keyword.verified = True
                keyword.updated_by = user
                keyword.save(update_fields=["verified", "updated_by", "updated_at"])
                return keyword
        return ProductAlias.objects.create(
            tenant=tenant,
            supplier=alias_supplier,
            kind=kind,
            value=value,
            product=product,
            source=ProductAlias.Source.LEARNED,
            verified=True,
            created_by=user,
            updated_by=user,
        )

    try:
        # 包一層 savepoint:兩個人同時確認同一個 key 時,`first()` 都查到空、
        # 兩邊都會 insert,其中一邊撞唯一鍵。沒有 savepoint 的話這個
        # IntegrityError 會把外層 transaction 整個弄壞,使用者看到 500。
        with transaction.atomic():
            alias = _create()
    except IntegrityError:
        existing = _match_qs().select_for_update().first()
        if existing is None:
            raise
        if existing.product_id == product.id:
            return _keep(existing)
        return existing, "conflict"
    return alias, ("repointed" if hit is not None else "created")


def _lock_vendor_sku(tenant, supplier, key):
    """把「認領這個料號」整段序列化(交易結束自動釋放)。

    別名表與來源表都可能是這個料號的擁有者,而**兩張表在那一列還不存在時
    都鎖不住任何東西** —— 兩個請求同時查到「沒人認領」,一個去寫別名、一個
    去寫來源,結果兩張表指到不同商品而且衝突清單是空的。只能用 advisory lock
    把查詢到寫入這一段包起來。

    非 PostgreSQL 不支援就跳過(dev 若切 sqlite 仍可跑,只是沒有這層保護)。
    """
    if connection.vendor != "postgresql" or not key:
        return
    payload = f"{tenant.id}:{supplier.id if supplier is not None else 0}:{key}"
    n = int.from_bytes(
        hashlib.sha256(payload.encode("utf-8")).digest()[:8], "big", signed=True
    )
    with connection.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", [n])


def _vendor_sku_owner(tenant, supplier, vendor_sku):
    """這個(廠商 + 料號)目前歸屬哪個商品 —— 別名表與來源表**一起看**。

    兩張表各自查重的話會分裂:learn_alias=False 那次只寫了來源(指 A),
    下一次 learn_alias=True 只看別名表(空的)就學成指 B,兩邊從此不一致
    而且沒有任何警示。誰先認領就是誰的,另一邊要尊重。
    """
    from apps.catalog.models import SupplierProduct

    key = alias_key(vendor_sku)
    if not key:
        return None
    # 先鎖再查。查完才鎖等於沒鎖。
    _lock_vendor_sku(tenant, supplier, key)
    alias = _alias_lookup(
        tenant, supplier, key, [ProductAlias.Kind.VENDOR_SKU]
    )
    if alias is not None:
        return alias.product
    # 來源表也要用正規化鍵查。用原字的話 ABC-01 / abc-01 / ＡＢＣ－０１
    # 會被當成三個料號,跟別名表(它用正規化鍵)對不起來 —— 就會發生
    # 「來源已認領但查不到,於是別名學成指別人」。
    sp = (
        SupplierProduct.objects.for_tenant(tenant)
        .filter(is_active=True, supplier=supplier, vendor_sku_key=key)
        .order_by()
        .select_related("product")
        .first()
    )
    return sp.product if sp is not None else None


def _record_supplier_product(item, product, user=None):
    """把「這家廠商的這個來源」記成一筆供應商商品對照。

    跟別名的分工:別名記的是「字串 → 商品」給比對用;這裡記的是來源本身
    (廠商、料號、來源品名、之後還有商品頁 / 變體 / 包裝),下次同一家再進貨
    時人看得到上次是從哪買的。

    **不會把既有的來源改指到別的商品。**跟第 2 批的別名規則一致:料號多半是
    OCR 讀的、店員是看品名選商品,不能讓一個他沒看過的料號把別人正確的來源
    改掉(那還會把商品頁、變體、包裝數一起清成預設值)。料號衝突已經由
    `alias_conflicts` 讓人看見,這裡保持沉默即可。

    沒有料號時只在「同一個商品」底下比對來源品名 —— 不能拿品名當跨商品的
    來源身分,同一家的兩款「透明殼」會互相蓋掉。
    """
    from apps.catalog.models import SupplierProduct

    supplier = item.batch.supplier
    vendor_sku = (item.effective_vendor_sku or "").strip()[:80]
    source_name = (item.effective_name or "").strip()[:300]
    if supplier is None or not (vendor_sku or source_name):
        return None

    base = SupplierProduct.objects.for_tenant(item.tenant).filter(
        is_active=True, supplier=supplier
    ).order_by()

    if vendor_sku:
        # _vendor_sku_owner 內部已取得 advisory lock,以下到寫入為止是序列化的
        owner = _vendor_sku_owner(item.tenant, supplier, vendor_sku)
        if owner is not None and owner.id != product.id:
            # 這個料號已經被別的商品認領(別名或來源任一邊)→ 不動它
            return None
        hit = base.filter(vendor_sku_key=alias_key(vendor_sku)).first()
        if hit is not None and hit.product_id != product.id:
            # 保險:拿到的列不是這個商品的就不要碰(理論上被上面擋掉了)
            return None
    else:
        # 沒有可靠的鍵,就只在這個商品自己的來源裡找同名的
        hit = base.filter(
            product=product, vendor_sku="", source_name=source_name
        ).first()

    if hit is not None:
        fields = []
        if source_name and hit.source_name != source_name:
            hit.source_name = source_name
            fields.append("source_name")
        if hit.confirmed_at is None:
            hit.confirmed_at = timezone.now()
            hit.confirmed_by = user
            fields += ["confirmed_at", "confirmed_by"]
        if fields:
            hit.save(update_fields=fields + ["updated_at"])
        return hit

    try:
        with transaction.atomic():
            return SupplierProduct.objects.create(
                tenant=item.tenant,
                product=product,
                supplier=supplier,
                vendor_sku=vendor_sku,
                source_name=source_name,
                confirmed_by=user,
                confirmed_at=timezone.now(),
            )
    except IntegrityError:
        # 併發:另一個請求先寫進同一筆。這是附加資訊,不值得為它讓整次確認失敗。
        if vendor_sku:
            return base.filter(vendor_sku_key=alias_key(vendor_sku)).first()
        return base.filter(
            product=product, vendor_sku="", source_name=source_name
        ).first()


def _learn_alias(item, product, user=None, can_repoint=False):
    """人確認後,把這行的三種講法都學起來:品名、廠商料號、條碼。

    舊版只學品名,所以供應商改了品名(料號沒變)下次就整個對不回來。
    用 effective_* 取值,人修正過的值優先於原始值 —— 人已經說了原值是錯的。

    兩條安全規則:
    - 沒指定廠商的批次不學廠商層別名。查詢端會把 supplier 為空的別名
      套用到**所有**廠商,把「還不知道是哪一家」當成「跨廠通用」,
      會讓別家的同號碼被誤對到這個商品。
    - 只有品名可以「改指」,而且只有公司管理員可以(`can_repoint`)。
      同一句話已經確認指到別的商品,一般店員再選別款不會靜默改掉它,
      而是記成衝突讓人處理。條碼與料號多半是 OCR 讀的、畫面上看不到,
      任何人都不能靠它們去把別人正確的對應改掉。
    - 太籠統、或同一句話有好幾款都符合的品名,只記成搜尋關鍵字,
      不取得下次自動對應的資格(見 `_phrase_can_auto_match`)。
    """
    supplier = item.batch.supplier
    lock_identifiers(
        item.tenant, supplier,
        name=item.effective_name if supplier is not None else "",
        vendor_sku=item.effective_vendor_sku if supplier is not None else "",
        barcode=item.effective_barcode,
    )
    results = {}
    plans = [
        (ProductAlias.Kind.BARCODE, item.effective_barcode, False),
    ]
    if supplier is not None:
        plans = [
            (ProductAlias.Kind.VENDOR_NAME, item.effective_name, can_repoint),
            (ProductAlias.Kind.VENDOR_SKU, item.effective_vendor_sku, False),
        ] + plans
    conflicts = []
    for kind, value, allow_repoint in plans:
        if kind == ProductAlias.Kind.VENDOR_SKU and value:
            # 來源表可能已經先認領了這個料號(上一次 learn_alias=False 那種)。
            # 兩張表要用同一個認領結果,否則會一邊指 A 一邊指 B 而且沒人知道。
            # _vendor_sku_owner 會先取得 advisory lock,之後的 _upsert_alias
            # 都在同一把鎖底下(同交易內重複取同一把鎖是允許的)。
            owner = _vendor_sku_owner(item.tenant, supplier, value)
            if owner is not None and owner.id != product.id:
                results[kind] = "conflict"
                conflicts.append({
                    "kind": kind,
                    "label": str(ProductAlias.Kind(kind).label),
                    "value": str(value).strip()[:200],
                    "product_sku": owner.sku,
                    "product_name": owner.name,
                })
                continue
        verified = True
        if kind == ProductAlias.Kind.VENDOR_NAME and value:
            verified = _phrase_can_auto_match(item.tenant, supplier, value, product)
        alias, action = _upsert_alias(
            item.tenant, supplier, kind, value, product,
            allow_repoint=allow_repoint, verified=verified, user=user,
        )
        results[kind] = action
        if action == "conflict" and alias is not None:
            conflicts.append({
                "kind": kind,
                "label": str(ProductAlias.Kind(kind).label),
                "value": alias.value,
                "product_sku": alias.product.sku,
                "product_name": alias.product.name,
            })
    # 不擋流程(這行已經對好了),但要留痕並讓前端看得到,
    # 否則沒人知道有個識別碼沒學進去、下一批還是會對到舊商品。
    if item.alias_conflicts != conflicts:
        item.alias_conflicts = conflicts
        item.save(update_fields=["alias_conflicts", "updated_at"])
    return results


def _refresh_batch_status(batch):
    if batch.status in (IntakeBatch.Status.COMMITTED, IntakeBatch.Status.CANCELLED):
        return
    pending = batch.items.filter(match_status__in=_PENDING).exists()
    batch.status = IntakeBatch.Status.OPEN if pending else IntakeBatch.Status.RESOLVED
    batch.save(update_fields=["status", "updated_at"])


@transaction.atomic
def resolve_item_match(item, product, learn_alias=True, user=None,
                       restore_inactive=False, can_repoint=False):
    """把一行對應到既有商品(選候選 / 手動指定)。

    學別名會「停用舊的 + 建新的」兩步,要在同一個 transaction 內完成,
    否則中途失敗會留下沒有任何 active 別名的空窗。

    `restore_inactive`:商品已停用時,呼叫端要明確說「恢復它」才會恢復,
    而且要先確認操作者有這個權限(view 負責擋)。選用本身不會偷偷把商品復活。
    """
    if not product.is_active:
        if not restore_inactive:
            raise IdentityError("這個商品已停用,請先由管理員恢復再入庫")
        product.is_active = True
        product.save(update_fields=["is_active", "updated_at"])
    item.matched_product = product
    item.match_status = IntakeItem.MatchStatus.RESOLVED
    item.resolved_by = user
    item.save(update_fields=["matched_product", "match_status", "resolved_by", "updated_at"])
    if learn_alias:
        _learn_alias(item, product, user=user, can_repoint=can_repoint)
    # 來源記錄跟「要不要學別名」是兩件事:別名是給比對用的,來源是「上次
    # 從哪買的」這個事實。關掉學習不代表不想記來源。
    _record_supplier_product(item, product, user=user)
    _refresh_batch_status(item.batch)
    return item


@transaction.atomic
def resolve_item_new_product(item, data, user=None):
    """從一行建立新商品並對應。"""
    try:
        cat = Category.objects.for_tenant(item.tenant).get(id=data["category"])
    except Category.DoesNotExist:
        raise IdentityError("找不到指定的類別")
    name = (data.get("name") or item.raw_text).strip()
    name_max = Product._meta.get_field("name").max_length
    if len(name) > name_max:
        raise IdentityError(f"品名超過 {name_max} 字上限")
    # 這一行等一下會用到的鎖先一次收齊(關卡要鎖條碼、學別名要鎖名稱與料號),
    # 順序跟「對應既有商品」那條路一致,兩邊才不會互等。
    lock_identifiers(
        item.tenant, item.batch.supplier,
        name=item.effective_name if item.batch.supplier is not None else "",
        vendor_sku=item.effective_vendor_sku if item.batch.supplier is not None else "",
        barcode=item.effective_barcode,
    )
    # 防重複關卡:待確認區「建新品」跟商品頁新增走同一道。擋下時丟
    # DuplicateProduct(view 轉 409);放行回「已說明不同」的相似商品。
    reason = data.get("distinct_reason", "")
    similar = guard_new_product(
        item.tenant, name=name, capacity=data.get("capacity", ""),
        color=data.get("color", ""), barcode=item.effective_barcode or "",
        is_secondhand=cat.is_secondhand_default, distinct_reason=reason,
    )
    # 無品牌配件容易撞名(「透明殼」「鋼化膜」滿街都是),給它一個穩定款式碼,
    # 店員不用自己想名字也分得出來。序號商品(手機)有 IMEI,不需要。
    style_code = ""
    if not data.get("requires_serial", True):
        existing = Product.objects.for_tenant(item.tenant)
        if existing.filter(name=name).exists():
            # 加了號還是可能撞(已經有人叫「透明殼 001」而下一號正好是 001),
            # 要一直取到真的沒人用的那一個,否則整個交易回滾、流水不前進,
            # 下次重試會撞同一個名字,永遠做不完。
            for _ in range(50):
                style_code = item.tenant.issue_next_style_code()
                candidate = f"{name} {style_code}"
                if len(candidate) > name_max:
                    raise IdentityError(
                        f"品名加上款式碼後超過 {name_max} 字上限,請先縮短品名"
                    )
                if not existing.filter(name=candidate).exists():
                    name = candidate
                    break
            else:
                raise IdentityError("連續 50 個款式碼都撞名,請手動指定品名")
        else:
            style_code = item.tenant.issue_next_style_code()
    product = Product.objects.create(
        tenant=item.tenant, category=cat, name=name,
        capacity=data.get("capacity", ""), color=data.get("color", ""),
        region_version=data.get("region_version", ""),
        style_code=style_code,
        requires_serial=data.get("requires_serial", True),
    )
    record_distinct_decision(item.tenant, product, similar, reason, user)
    item.matched_product = product
    item.match_status = IntakeItem.MatchStatus.NEW_PRODUCT
    item.resolved_by = user
    item.save(update_fields=["matched_product", "match_status", "resolved_by", "updated_at"])
    if data.get("learn_alias", True):
        _learn_alias(item, product, user=user)
    _record_supplier_product(item, product, user=user)
    _refresh_batch_status(item.batch)
    return product


_NAME_KINDS = (
    ProductAlias.Kind.VENDOR_NAME,
    ProductAlias.Kind.LEGACY_NAME,
    ProductAlias.Kind.OEM_MODEL,
)


@transaction.atomic
def create_alias(tenant, product, kind, value, supplier=None, verified=True,
                 note="", user=None):
    """別名管理畫面(或直接打 API)手動加一條別名。

    跟「記住這個叫法」走同一套規則:名稱類的別名,太籠統或同時符合多款的
    一律降為關鍵字;同一句話已確認指到別的商品就回衝突,不改指。
    之前這條路是直接存檔,`verified` 預設 True,等於任何人都能把「皮套」
    加成某個商品的唯一別名。
    """
    if kind in _NAME_KINDS and verified:
        verified = _phrase_can_auto_match(tenant, supplier, value, product)
    alias, action = _upsert_alias(
        tenant, supplier, kind, value, product,
        allow_repoint=False, verified=verified, user=user,
    )
    if alias is not None and action in ("created", "keyword"):
        alias.source = ProductAlias.Source.MANUAL
        alias.note = (note or "")[:200]
        alias.save(update_fields=["source", "note", "updated_at"])
    return alias, action


_ALIAS_EDITABLE = {"is_active", "verified", "note"}


@transaction.atomic
def update_alias(alias, changes, user=None):
    """別名管理畫面修改一條別名。只能改「啟用 / 已確認 / 備註」。

    內容、商品、廠商、類型不能直接改:那等於換了一條別名,原本那條代表過什麼
    就查不到了。要改指就停用這一筆、再新增一筆。

    變成「啟用中 + 已確認」的那一刻(重新啟用、或把關鍵字升級),跟新增一樣要
    過完整的規則:籠統的不能確認、已經有別的商品認領的回衝突。
    """
    extra = set(changes) - _ALIAS_EDITABLE
    if extra:
        raise IdentityError("別名的內容、商品、廠商、類型不能直接修改;要改指請停用這一筆再新增")
    # 先取識別鎖,再鎖這一列並重讀。呼叫端手上的物件是交易外讀的,可能已經舊了:
    # 兩個管理員同時改(一個停用、一個只改備註),不重讀的話後者會拿舊狀態判斷、
    # 再把整列寫回去,前者的停用就悄悄被蓋掉。內容 / 類型 / 廠商不可改,用它們
    # 算鎖名不會過期。
    key = alias.normalized_value
    scope = None if alias.kind == ProductAlias.Kind.BARCODE else alias.supplier
    _lock_identifier(alias.tenant, scope, alias.kind, key, alias.value.strip())
    fresh = ProductAlias.objects.select_for_update().order_by().get(pk=alias.pk)
    for name in ("is_active", "verified", "note"):
        setattr(alias, name, getattr(fresh, name))
    active = changes.get("is_active", alias.is_active)
    verified = changes.get("verified", alias.verified)
    becoming_owner = active and verified and not (alias.is_active and alias.verified)
    if becoming_owner:
        if alias.kind in _NAME_KINDS and not _phrase_can_auto_match(
            alias.tenant, alias.supplier, alias.value, alias.product
        ):
            raise IdentityError("這個叫法太籠統或同時符合好幾款,只能當搜尋關鍵字")
        owner = _other_source_owner(
            alias.tenant, scope, alias.kind, key, alias.value.strip(),
            exclude_alias_id=alias.pk,
        )
        if owner is None:
            same = ProductAlias.objects.for_tenant(alias.tenant).filter(
                is_active=True, verified=True, kind=alias.kind, normalized_value=key,
            ).exclude(pk=alias.pk).order_by()
            if alias.kind != ProductAlias.Kind.BARCODE:
                same = same.filter(supplier=alias.supplier)
            owner = same.select_related("product").first()
        if owner is not None and owner.product.id != alias.product_id:
            raise AliasOwnedElsewhere(owner.product)
    for name, value in changes.items():
        setattr(alias, name, value)
    alias.updated_by = user if getattr(user, "is_authenticated", False) else None
    try:
        with transaction.atomic():
            # 只寫這次要改的欄位,不把整列(可能是舊的)寫回去
            alias.save(update_fields=[*changes, "updated_by", "updated_at"])
    except IntegrityError:
        raise AliasOwnedElsewhere(None)
    return alias


class AliasOwnedElsewhere(IdentityError):
    """這個識別已經確認屬於別的商品。"""

    def __init__(self, product):
        self.product = product
        name = f"「{product.name}」" if product is not None else "別的商品"
        super().__init__(f"這個叫法已經確認指到{name}")


@transaction.atomic
def remember_phrase(tenant, product, value, supplier=None, user=None, can_repoint=False):
    """店員按「記住這個叫法」:把一句話記到一個既有商品上。

    沒指定廠商 = 店內自己的叫法(通用別名);有指定 = 那家廠商的品名。
    回傳 (alias, action, owner):action 同 `_upsert_alias`;`owner` 是衝突時
    目前擁有這句話的商品(讓畫面能講清楚「已經指到哪一個」)。
    """
    kind = ProductAlias.Kind.VENDOR_NAME if supplier is not None else ProductAlias.Kind.LEGACY_NAME
    verified = _phrase_can_auto_match(tenant, supplier, value, product)
    alias, action = _upsert_alias(
        tenant, supplier, kind, value, product,
        allow_repoint=can_repoint, verified=verified, user=user,
    )
    owner = alias.product if action == "conflict" and alias is not None else None
    return alias, action, owner


def capture_units(item, units_data, user=None):
    """逐台登記實體 unit + 識別碼(整批取代該行既有的 units)。

    units_data: [ {"identifiers": [{"kind","value","is_primary"}, ...]}, ... ]
    每台至少一個識別碼、最多一個主識別碼(沒指定就第一個當主)。
    """
    product = item.matched_product
    if not product or not product.requires_serial:
        raise IdentityError("這行不是序號商品,不需逐台登記")

    seen = set()
    parsed_units = []
    for u in units_data or []:
        raw_ids = u.get("identifiers") or []
        norm_ids, primary_count = [], 0
        for idf in raw_ids:
            val = (idf.get("value") or "").strip()
            if not val:
                continue
            nv = normalize_serial(val)
            if nv in seen:
                raise IdentityError(f"識別碼重複:{val}")
            seen.add(nv)
            is_primary = bool(idf.get("is_primary"))
            primary_count += 1 if is_primary else 0
            norm_ids.append({
                "kind": idf.get("kind") or IntakeUnitIdentifier.Kind.IMEI,
                "raw": val, "nv": nv, "is_primary": is_primary,
            })
        if not norm_ids:
            raise IdentityError("每台至少要填一個識別碼")
        if primary_count == 0:
            norm_ids[0]["is_primary"] = True
        elif primary_count > 1:
            raise IdentityError("每台只能有一個主識別碼")
        parsed_units.append(norm_ids)

    # 主序號不得與系統既有序號衝突
    primaries = [ni["nv"] for u in parsed_units for ni in u if ni["is_primary"]]
    clash = list(
        ProductSerial.objects.for_tenant(item.tenant)
        .filter(serial_no__in=primaries).values_list("serial_no", flat=True)
    )
    if clash:
        raise IdentityError(f"序號已存在系統:{', '.join(clash)}")

    with transaction.atomic():
        item.received_units.all().delete()
        for idx, norm_ids in enumerate(parsed_units, start=1):
            unit = IntakeReceivedUnit.objects.create(
                tenant=item.tenant, item=item, unit_index=idx,
                source=IntakeReceivedUnit.Source.MANUAL, captured_by=user,
            )
            IntakeUnitIdentifier.objects.bulk_create([
                IntakeUnitIdentifier(
                    tenant=item.tenant, unit=unit, kind=ni["kind"], raw_value=ni["raw"],
                    normalized_value=ni["nv"], is_primary=ni["is_primary"],
                    source=IntakeReceivedUnit.Source.MANUAL,
                )
                for ni in norm_ids
            ])
    return item


def reject_item(item, user=None):
    item.match_status = IntakeItem.MatchStatus.REJECTED
    item.resolved_by = user
    item.save(update_fields=["match_status", "resolved_by", "updated_at"])
    _refresh_batch_status(item.batch)
    return item


def correct_intake_item(item, data, user=None):
    """人工修正一行(品名/數量/單價/條碼/料號/序號),保留 raw 原值。
    改到會影響「識別」的欄位(品名/條碼/料號)才重跑比對;只改量價序號不動已對應的商品。
    """
    before_identity = (
        item.effective_name,
        item.effective_barcode,
        item.effective_vendor_sku,
    )
    if "name" in data:
        item.corrected_name = (data["name"] or "").strip()
    if data.get("qty") is not None:
        item.corrected_qty = _to_int_qty(data["qty"])
    if data.get("unit_price") is not None:
        item.corrected_unit_price = _to_price(data["unit_price"])
    if "barcode" in data:
        item.corrected_barcode = (data["barcode"] or "").strip()
    if "vendor_sku" in data:
        item.corrected_vendor_sku = (data["vendor_sku"] or "").strip()
    if "serials" in data:
        item.corrected_serials = list(data["serials"] or [])

    # 只看「欄位有沒有被送上來」會出事:前端每次儲存都會把條碼與料號一起送,
    # 值根本沒變也算「識別資料改了」→ 重跑比對 → 把人剛選好的商品覆蓋掉。
    # 要比實際的 effective 值有沒有變。
    identity_changed = any(
        (item.effective_name, item.effective_barcode, item.effective_vendor_sku)[i]
        != before_identity[i]
        for i in range(3)
    )
    # 人已經親自指定過商品就不再自動覆蓋。要換商品請重新選,
    # 不要因為順手改個數量就被系統改掉。
    human_resolved = item.match_status in (
        IntakeItem.MatchStatus.RESOLVED,
        IntakeItem.MatchStatus.NEW_PRODUCT,
    )
    if identity_changed and not human_resolved:
        res = match_line(
            item.tenant, item.batch.supplier, item.effective_name,
            raw_barcode=item.effective_barcode, raw_vendor_sku=item.effective_vendor_sku,
        )
        item.matched_product = res["matched_product"]
        item.match_status = res["status"]
        item.match_confidence = res["confidence"]
        item.candidates = res["candidates"]
    item.resolved_by = user
    item.save()
    _refresh_batch_status(item.batch)
    return item


_UNSET = object()


def set_header(batch, supplier=None, warehouse=None, tax_method=None,
               vendor_doc_no=None, document_total=_UNSET):
    """修正批次單頭(供應商 / 倉 / 稅別 / 廠商單號 / 單據總額)。None = 該欄不動。"""
    if batch.status in (IntakeBatch.Status.COMMITTED, IntakeBatch.Status.CANCELLED):
        raise IdentityError("這批已結案,不可再修改")
    fields = []
    if supplier is not None:
        batch.supplier = supplier
        fields.append("supplier")
    if warehouse is not None:
        batch.warehouse = warehouse
        fields.append("warehouse")
    if tax_method is not None:
        batch.tax_method = tax_method
        fields.append("tax_method")
    if vendor_doc_no is not None:
        batch.vendor_doc_no = vendor_doc_no
        fields.append("vendor_doc_no")
    if document_total is not _UNSET:
        batch.document_total = document_total
        fields.append("document_total")
    if fields:
        batch.save(update_fields=fields + ["updated_at"])
    return batch


def commit_batch(batch, user=None):
    """全部對應完 → 組進貨單 → 走既有 commit_purchase_order 過帳(帳本唯一入口)。

    row lock(select_for_update)防並發雙 commit:第二個請求會等到第一個結束、看到
    已過帳而擋下。稅別用 batch.tax_method、量價序號用 effective_*(修正優先)。
    """
    with transaction.atomic():
        batch = IntakeBatch.objects.select_for_update().get(pk=batch.pk)
        if batch.status == IntakeBatch.Status.COMMITTED:
            raise IdentityError("這批已經過帳了")
        if batch.status == IntakeBatch.Status.CANCELLED:
            raise IdentityError("這批已取消")
        if not batch.supplier_id or not batch.warehouse_id:
            raise IdentityError("請先指定廠商與入庫倉再過帳")
        if batch.items.filter(match_status__in=_PENDING).exists():
            raise IdentityError("還有未確認的明細,請先逐筆處理完")

        rows = batch.items.filter(
            match_status__in=_COMMITTABLE, matched_product__isnull=False
        ).select_related("matched_product").order_by("line_no")
        # 對應完成之後、過帳之前,商品可能被別人停售。鎖起來重查一次,
        # 不然會把貨入到一個停售商品上,之後在商品清單與庫存查詢都看不到。
        # 這裡刻意**不**加 select_for_update:既有進貨 / 作廢流程是
        # 「先寫 StockBalance 再更新 Product」,在這裡先鎖 Product 會跟它們
        # 反向等待而死鎖(實測 deadlock detected)。重查一次已經關掉絕大多數
        # 視窗,剩下的極窄競態不值得用一個會鎖死正式流程的鎖去換。
        product_ids = sorted({r.matched_product_id for r in rows})
        if product_ids:
            still_active = set(
                Product.objects
                .filter(id__in=product_ids, is_active=True)
                .values_list("id", flat=True)
            )
            gone = [
                f"第 {r.line_no} 行 {r.matched_product.sku}"
                for r in rows
                if r.matched_product_id not in still_active
            ]
            if gone:
                raise IdentityError(
                    "這些明細對應的商品已停售,請重新確認:" + "、".join(gone)
                )
        payload_items = []
        unit_map = {}  # 主序號(nv)→ IntakeReceivedUnit,過帳後回填識別碼
        for it in rows:
            serials = list(it.effective_serials or [])
            if it.matched_product.requires_serial:
                units = list(it.received_units.prefetch_related("identifiers"))
                if units:
                    # 逐台登記過 → 實收台數必須等於數量,主序號進帳
                    if len(units) != it.effective_qty:
                        raise IdentityError(
                            f"第 {it.line_no} 行:已登記 {len(units)} 台,數量 {it.effective_qty},請補齊逐台序號"
                        )
                    serials = []
                    for u in units:
                        pid = u.primary_identifier
                        if not pid:
                            raise IdentityError(f"第 {it.line_no} 行有一台缺主序號")
                        serials.append(pid.normalized_value)
                        unit_map[pid.normalized_value] = u
            payload_items.append({
                "product": it.matched_product_id,
                "qty": it.effective_qty,
                "unit_price": str(it.effective_unit_price),
                "serial_numbers": serials,
            })
        if not payload_items:
            raise IdentityError("沒有可過帳的明細(都被駁回了?)")

        # 單據總額平衡:有填 document_total 才核對,差超過容差就擋
        if batch.document_total is not None:
            calc = sum(
                (Decimal(str(i["unit_price"])) * i["qty"] for i in payload_items),
                Decimal("0"),
            )
            tol = Decimal(str(getattr(settings, "INTAKE_TOTAL_TOLERANCE", 1)))
            if abs(calc - batch.document_total) > tol:
                raise IdentityError(
                    f"明細合計 {calc:.0f} 與單據總額 {batch.document_total:.0f} 不符,請先核對"
                )

        payload = {
            "supplier": batch.supplier_id,
            "warehouse": batch.warehouse_id,
            "tax_method": batch.tax_method,
            "items": payload_items,
        }
        ser = PurchaseOrderSerializer(data=payload)
        ser.is_valid(raise_exception=True)
        ser.save(tenant=batch.tenant, created_by=user)
        commit_purchase_order(ser.instance)
        # 逐台識別碼回填到正式序號(主序號已是 ProductSerial.serial_no,其餘存識別碼表)
        for nv, unit in unit_map.items():
            serial = ProductSerial.objects.for_tenant(batch.tenant).filter(serial_no=nv).first()
            if not serial:
                continue
            for idf in unit.identifiers.all():
                ProductSerialIdentifier.objects.get_or_create(
                    tenant=batch.tenant, normalized_value=idf.normalized_value,
                    defaults={
                        "serial": serial, "kind": idf.kind,
                        "value": idf.raw_value, "is_primary": idf.is_primary,
                    },
                )
        batch.committed_purchase_order = ser.instance
        batch.status = IntakeBatch.Status.COMMITTED
        batch.save(update_fields=["committed_purchase_order", "status", "updated_at"])
    return ser.instance
