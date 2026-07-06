"""把自然語言的商品/供應商/倉庫名稱,對應到真實主檔。

刻意寫成 DB 可攜(SQLite 開發 / PostgreSQL 正式都能跑):以 icontains + 逐詞 AND
為主。正式環境若要打錯字也命中,可再疊上 apps.core.filters 的 pg_trgm 相似度,
但那是加分,不是這層的必要條件。

回傳統一用 ResolveResult:
  status = "resolved"  → obj 是唯一命中
  status = "ambiguous" → candidates 是多筆候選(需要向使用者追問)
  status = "not_found" → 都沒中(可提示建檔)
"""
import re
from dataclasses import dataclass, field
from typing import Optional

from django.db.models import Q

from apps.catalog.models import Product
from apps.inventory.models import Warehouse
from apps.parties.models import Supplier

_TOKEN_RE = re.compile(r"[\s,/、]+")


@dataclass
class ResolveResult:
    status: str  # resolved / ambiguous / not_found
    obj: Optional[object] = None
    candidates: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status == "resolved"


def _tokens(text: str):
    return [t for t in _TOKEN_RE.split(text.strip()) if t]


def resolve_product(tenant, query: str, limit: int = 6) -> ResolveResult:
    q = (query or "").strip()
    if not q:
        return ResolveResult("not_found")
    base = Product.objects.for_tenant(tenant).filter(is_active=True)

    # 1) 精準:SKU / 條碼 / 完整品名
    for exact in (base.filter(sku__iexact=q).first(),
                  base.filter(barcode=q).first() if q else None,
                  base.filter(name__iexact=q).first()):
        if exact:
            return ResolveResult("resolved", obj=exact)

    # 2) 逐詞 AND icontains(「iPhone 15 Pro 256」四個詞都要在品名裡)
    toks = _tokens(q)
    cond = Q()
    for tk in toks:
        cond &= Q(name__icontains=tk)
    matches = list(base.filter(cond)[:limit]) if toks else []

    # 3) 退回:整串 icontains
    if not matches:
        matches = list(base.filter(name__icontains=q)[:limit])

    if len(matches) == 1:
        return ResolveResult("resolved", obj=matches[0])
    if len(matches) > 1:
        matches.sort(key=lambda p: len(p.name))  # 名稱最短者最貼近
        return ResolveResult("ambiguous", candidates=matches)
    return ResolveResult("not_found")


def resolve_supplier(tenant, query: str, limit: int = 6) -> ResolveResult:
    q = (query or "").strip()
    if not q:
        return ResolveResult("not_found")
    base = Supplier.objects.for_tenant(tenant).filter(is_active=True)
    exact = base.filter(code__iexact=q).first() or base.filter(name__iexact=q).first()
    if exact:
        return ResolveResult("resolved", obj=exact)
    matches = list(base.filter(name__icontains=q)[:limit])
    if len(matches) == 1:
        return ResolveResult("resolved", obj=matches[0])
    if len(matches) > 1:
        return ResolveResult("ambiguous", candidates=matches)
    return ResolveResult("not_found")


def resolve_warehouse(tenant, query: str, default_if_single: bool = True) -> ResolveResult:
    base = Warehouse.objects.for_tenant(tenant).filter(is_active=True)
    q = (query or "").strip()
    if not q:
        # 沒指定倉:只有一個倉就自動帶,否則請使用者指定
        only = list(base[:2])
        if default_if_single and len(only) == 1:
            return ResolveResult("resolved", obj=only[0])
        return ResolveResult("ambiguous", candidates=list(base[:6]))
    exact = base.filter(code__iexact=q).first() or base.filter(name__iexact=q).first()
    if exact:
        return ResolveResult("resolved", obj=exact)
    matches = list(base.filter(name__icontains=q)[:6])
    if len(matches) == 1:
        return ResolveResult("resolved", obj=matches[0])
    if len(matches) > 1:
        return ResolveResult("ambiguous", candidates=matches)
    if default_if_single:
        only = list(base[:2])
        if len(only) == 1:
            return ResolveResult("resolved", obj=only[0])
    return ResolveResult("not_found")
