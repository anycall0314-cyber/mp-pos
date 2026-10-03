"""新增商品前的防重複關卡。

所有「建新品」的入口(單筆 / 批次 / 型號展開 / 匯入 / 待確認區建新品 / 直接打 API)
都要過 `guard_new_product()`。只做在畫面上的話,換個入口或直接打 API 就繞過去了。

兩種結果:

- **硬擋**(`identifier`):條碼、或品名整句就是另一個商品「已確認的叫法」。
  這是可靠識別,不能用「不同款」繞過;真的有疑義要先去處理那個識別碼。
- **要說明**(`similar`):特徵看起來是同一款(名稱換順序、同義詞、少寫 / 多寫一項)。
  名稱相似不等於同一個實物,所以不強制合併 —— 但要寫下「哪裡不同」才能繼續,
  不能只按一個沒有理由的忽略鈕。寫下的理由會留存(`ProductDistinctDecision`)。
"""
import hashlib

from django.db import connection

from .models import ProductDistinctDecision
from .product_match import (
    IDENTIFIER,
    SAME_ITEM_LEVELS,
    Candidate,
    MatchContext,
    MatchResult,
    identifier_hits,
)

REASON_MIN_LEN = 2


class DuplicateProduct(Exception):
    """新品被防重複關卡擋下。`kind`:identifier(硬擋)/ similar(要說明差異)。"""

    IDENTIFIER = "identifier"
    SIMILAR = "similar"

    def __init__(self, kind, candidates, message):
        super().__init__(message)
        self.kind = kind
        self.candidates = candidates
        self.message = message

    def as_dict(self):
        """給 API 回 409 用。候選只放認得出商品的最少欄位,不帶成本 / 庫存。"""
        return {
            "detail": self.message,
            "code": "duplicate_product",
            "kind": self.kind,
            "candidates": self.candidates,
            # 批次入口:哪一筆對到哪些既有商品
            "items": getattr(self, "items", []),
        }


def _lock_barcode(tenant, barcode):
    """同一個條碼的建檔序列化(交易結束自動釋放)。

    商品條碼欄位沒有唯一約束,兩個人同時用同一個條碼建檔時,兩邊都會查到
    「沒人用過」。這把鎖讓第二個人等第一個人寫完再查。非 PostgreSQL 跳過。
    """
    if connection.vendor != "postgresql" or not barcode:
        return
    payload = f"product-barcode:{tenant.id}:{barcode}"
    n = int.from_bytes(hashlib.sha256(payload.encode()).digest()[:8], "big", signed=True)
    with connection.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", [n])


def _describe(tenant, found, planned=None):
    from apps.catalog.models import Product

    rows = {
        p.id: p for p in Product.objects.for_tenant(tenant)
        .filter(id__in=found.product_ids).select_related("category")
    }
    # 預覽時同一批裡還沒真的建出來的那幾筆(負數 id)
    virtual = [
        {
            "id": None, "sku": "", "name": planned[c.product_id], "category_name": "",
            "is_active": True, "level": c.level,
            "reasons": ["同一批裡的另一筆"], "differences": c.differences,
        }
        for c in found.candidates if planned and c.product_id in planned
    ]
    return virtual + [
        {
            "id": c.product_id,
            "sku": rows[c.product_id].sku,
            "name": rows[c.product_id].name,
            "category_name": rows[c.product_id].category.name,
            "is_active": rows[c.product_id].is_active,
            "level": c.level,
            "reasons": c.reasons,
            "differences": c.differences,
        }
        for c in found.candidates if c.product_id in rows
    ]


def has_real_reason(reason) -> bool:
    """差異理由要有內容:至少兩個字(文字或數字),只打標點或空白不算。"""
    return sum(1 for ch in (reason or "") if ch.isalnum()) >= REASON_MIN_LEN


def check_new_product(tenant, *, name, spec="", color="", capacity="", barcode="",
                      is_secondhand=False, context=None, exclude_id=None,
                      planned=None):
    """查一個準備新增的商品會不會跟既有的重複。回 None 或 DuplicateProduct(不丟)。

    要在交易內呼叫(條碼鎖是交易層級的)。批次入口請傳同一份 `context`
    (`MatchContext`),並在每建好一筆後 `context.add(product)`。
    """
    from apps.catalog.models import Product

    barcode = (barcode or "").strip()
    _lock_barcode(tenant, barcode)

    # ⓪ 一字不差的同名:資料庫本來就不允許,直接指出是哪一筆(不能用理由繞過)。
    #    以前是表單驗證回一句「已存在」,看不到是哪個商品、也沒有「就是這個」可按。
    same = (
        Product.objects.for_tenant(tenant).filter(name=(name or "").strip())
        .exclude(pk=exclude_id).values_list("id", flat=True)
    ) if (name or "").strip() else []
    if same:
        exact = MatchResult(MatchResult.EXISTING, [
            Candidate(pid, IDENTIFIER, 100, ["品名相同"], [], False, True) for pid in same
        ])
        return DuplicateProduct(
            DuplicateProduct.IDENTIFIER, _describe(tenant, exact), "已經有同名的商品",
        )

    # ① 可靠識別:條碼、整句品名是別人已確認的叫法(不分新品 / 中古都算)
    hits = identifier_hits(tenant, (name or "").strip(), barcode=barcode)
    hits.pop(exclude_id, None)   # 改既有商品時,自己不算
    if hits:
        exact = MatchResult(MatchResult.EXISTING, [
            Candidate(pid, IDENTIFIER, 100, sorted(set(reasons)), [], False, True)
            for pid, reasons in hits.items()
        ])
        rows = _describe(tenant, exact)
        who = "、".join(f"「{r['name']}」" for r in rows)
        return DuplicateProduct(
            DuplicateProduct.IDENTIFIER, rows,
            f"這個條碼 / 叫法已經屬於{who},不能再建一個",
        )

    # ② 特徵看起來是同一款(兩個方向都看)
    text = " ".join(x for x in (name, spec, color, capacity) if x)
    context = context or MatchContext(tenant)
    similar = MatchResult(MatchResult.CANDIDATES, [
        c for c in context.scan(
            text, is_secondhand=is_secondhand, limit=5,
            with_related=False, symmetric=True, exclude_id=exclude_id,
        ) if c.level in SAME_ITEM_LEVELS
    ])
    if similar.candidates:
        rows = _describe(tenant, similar, planned)
        return DuplicateProduct(
            DuplicateProduct.SIMILAR, rows,
            "找到可能相同的商品:" + "、".join(r["name"] for r in rows),
        )
    return None


def guard_new_product(tenant, *, name, spec="", color="", capacity="", barcode="",
                      is_secondhand=False, distinct_reason="", exclude_id=None):
    """建新品前呼叫。擋下就丟 DuplicateProduct;放行回「已說明不同」的相似商品清單
    (建好商品後交給 `record_distinct_decision` 留存)。
    """
    dup = check_new_product(
        tenant, name=name, spec=spec, color=color, capacity=capacity,
        barcode=barcode, is_secondhand=is_secondhand, exclude_id=exclude_id,
    )
    if dup is None:
        return []
    if dup.kind == DuplicateProduct.IDENTIFIER or not has_real_reason(distinct_reason):
        raise dup
    return dup.candidates


def record_distinct_decision(tenant, product, similar, reason, user=None):
    """把「這是不同款,因為……」留下來。`similar` 是 guard_new_product 的回傳值。"""
    if not similar:
        return None
    user = user if getattr(user, "is_authenticated", False) else None
    return ProductDistinctDecision.objects.create(
        tenant=tenant,
        product=product,
        similar_products=[
            {"id": r["id"], "sku": r["sku"], "name": r["name"]} for r in similar
        ],
        reason=(reason or "").strip()[:200],
        decided_by=user,
    )


class BatchGuard:
    """一次建很多筆的入口(型號展開 / 零件批次)用:逐筆查、最後一起回報。

    一筆一筆丟例外的話,使用者要來回好幾次才看得完整批有哪些可能重複。
    `dry_run`(預覽)時只收集不擋,讓預覽畫面先把可能重複的列出來。
    """

    def __init__(self, tenant, reasons=None, dry_run=False, user=None):
        self.tenant = tenant
        # {品名: 這一筆哪裡不同}。每一筆各自說明,不接受整批共用一句
        self.reasons = reasons if isinstance(reasons, dict) else {}
        self.dry_run = dry_run
        self.user = user
        self.found: list[dict] = []
        self._context = MatchContext(tenant)
        self._hard = False
        self._blocked = False
        self._acknowledged: dict[str, list] = {}
        # 預覽時還沒真的建出來的那幾筆:{假 id(負數): 品名}
        self._planned: dict[int, str] = {}

    def allow(self, name, **fields) -> bool:
        """這一筆可不可以建。False = 呼叫端跳過這一筆(整批最後會被 finish() 擋下)。"""
        dup = check_new_product(
            self.tenant, name=name, context=self._context, planned=self._planned,
            **fields,
        )
        if self.dry_run:
            # 預覽不會真的建商品,但後面的列要看得到這一筆,不然同一批裡的重複
            # (顏色同時填了「藍」跟「藍色」)要到正式建立才會被擋,而那時畫面上
            # 已經沒有地方可以填理由。
            fake_id = -(len(self._planned) + 1)
            self._planned[fake_id] = name
            self._context.add_planned(fake_id, name, fields.get("is_secondhand", False))
        if dup is None:
            return True
        self.found.append({"name": name, **dup.as_dict()})
        if self.dry_run:
            return True
        if dup.kind == DuplicateProduct.IDENTIFIER:
            self._hard = self._blocked = True
            return False
        if not has_real_reason(self.reasons.get(name)):
            self._blocked = True
            return False
        self._acknowledged[name] = dup.candidates
        return True

    def created(self, product):
        self._context.add(product)
        similar = self._acknowledged.pop(product.name, None)
        if similar:
            record_distinct_decision(
                self.tenant, product, similar, self.reasons.get(product.name, ""),
                self.user,
            )

    def finish(self):
        """整批跑完後呼叫。有被擋的就丟 DuplicateProduct(交易會整批回滾)。"""
        if not self._blocked:
            return
        seen, merged = set(), []
        for f in self.found:
            for c in f["candidates"]:
                if c["id"] not in seen:
                    seen.add(c["id"])
                    merged.append(c)
        names = "、".join(f["name"] for f in self.found[:5])
        more = f" 等 {len(self.found)} 筆" if len(self.found) > 5 else ""
        err = DuplicateProduct(
            DuplicateProduct.IDENTIFIER if self._hard else DuplicateProduct.SIMILAR,
            merged, f"這些可能已經建過了:{names}{more}",
        )
        err.items = self.found
        raise err
