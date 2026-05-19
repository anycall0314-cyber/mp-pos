"""Trigram-aware SearchFilter:icontains 嚴格符 OR pg_trgm 相似度 fallback。

DRF SearchFilter 預設只做 icontains。為了支援打錯字也找得到(例 "iphne" → iPhone),
這支 filter 額外用 pg_trgm TrigramSimilarity 對所有 search_fields 算相似度,
取 max 之後 OR-in 進結果集,並依相似度遞減排序。

- PG + pg_trgm 啟用時:走相似度路徑
- 其他 DB:fallback 到純 icontains(行為與 DRF SearchFilter 一致)

開啟相似度閾值與字數門檻可從 settings.TRGM_SEARCH_THRESHOLD / TRGM_SEARCH_MIN_LEN 改。
"""
from django.conf import settings
from django.contrib.postgres.search import TrigramWordSimilarity
from django.db.models import F, FloatField, Q, Value
from django.db.models.functions import Greatest
from rest_framework.filters import SearchFilter

DEFAULT_THRESHOLD = getattr(settings, "TRGM_SEARCH_THRESHOLD", 0.35)
DEFAULT_FUZZY_MIN_LEN = getattr(settings, "TRGM_SEARCH_MIN_LEN", 3)


def _is_postgres():
    return settings.DATABASES["default"]["ENGINE"].endswith("postgresql")


class TrigramSearchFilter(SearchFilter):
    """SearchFilter + pg_trgm fallback。

    流程:
    1. 先做 icontains(SearchFilter 原行為)
    2. 若 icontains 命中 0 筆 且 query 長度 ≥ 3 且 DB 是 PG → 改用 trigram 相似度
    3. 相似度 ≥ threshold 才收,並依相似度遞減排序
    這樣可避免「phone 在 'PH-000004' 上出現低相似度誤命中」的情況。
    """

    def filter_queryset(self, request, queryset, view):
        search_terms = self.get_search_terms(request)
        search_fields = self.get_search_fields(view, request)
        if not search_terms or not search_fields:
            return queryset

        primary = super().filter_queryset(request, queryset, view)
        if not _is_postgres():
            return primary

        joined = " ".join(search_terms).strip()
        if len(joined) < DEFAULT_FUZZY_MIN_LEN:
            return primary

        # 先 evaluate count(走 icontains 路徑);命中就回
        # 雖然多一次查詢,但 typo fallback 路徑不該是常態,代價可接受
        if primary.exists():
            return primary

        plain_fields = []
        for f in search_fields:
            if f and f[0] in {"^", "=", "$", "@"}:
                plain_fields.append(f[1:])
            else:
                plain_fields.append(f)

        # word_similarity 比 similarity 對「短關鍵字 vs 長欄位」更穩;
        # 例:'ipone' 對 'iPhone 15 Pro 256GB 黑',word_sim ≈ 0.44 而非 0.17
        sim_exprs = [TrigramWordSimilarity(joined, f) for f in plain_fields]
        max_sim = sim_exprs[0] if len(sim_exprs) == 1 else Greatest(*sim_exprs)

        return (
            queryset.annotate(_search_sim=max_sim)
            .filter(_search_sim__gte=DEFAULT_THRESHOLD)
            .order_by(F("_search_sim").desc(nulls_last=True))
        )


__all__ = ["TrigramSearchFilter"]
