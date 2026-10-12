"""全站清單的分頁。

以前用的是 DRF 原本的那一支:一頁固定 50 筆,網址帶 `page_size=…` 它不理、也不報錯 —— 畫面要 200 筆拿到 50 筆,
第 51 筆看不到也搜不到,頁面上的合計只加了那 50 筆(2026-10-13 L1 清單不再默默少列)。

- 一頁預設 50 筆;`?page_size=` 可以要更多,最多 500。
- **要比 50 少的照舊給 50**:刷條碼、搜尋下拉(`frontend/src/api/search.ts`)一直帶著 10、20,實際拿到的是 50;
  有幾處是看「拿回來的裡面是不是只有一台符合」來決定要不要自動帶序號,拿到的變少判斷就變鬆。這一支只補「要多卻沒給」,不動「要少」。
- 同分的列最後補上編號當先後:畫面現在會一頁一頁把整份拿完,同一天 / 同一個名稱的列如果每一次查的先後不一樣,
  就會有一列出現兩次、另一列不見。

合約到期(`sales/contract_views.py`)、舊系統(`legacy/views.py`)、報表(`inventory/report_views.py`)各有自己的分頁,不走這一支。
"""
from rest_framework.pagination import PageNumberPagination

MAX_PAGE_SIZE = 500


def stable(queryset):
    """排序的最後補上編號;已經照編號排的、不是一般清單的(只取幾欄、切過、合併的查詢)原樣回去。"""
    query = getattr(queryset, "query", None)
    if query is None:
        return queryset
    if (
        getattr(queryset, "_fields", None) is not None
        or query.is_sliced or query.combinator or query.distinct_fields or query.extra_order_by
    ):
        return queryset
    meta = query.get_meta()
    order = list(query.order_by)
    if not order and query.default_ordering:
        order = list(meta.ordering or [])
    for term in order:
        if isinstance(term, str) and term.lstrip("-+") in ("pk", meta.pk.name, "?"):
            return queryset
    return queryset.order_by(*order, "pk")


class Paging(PageNumberPagination):
    page_size_query_param = "page_size"
    max_page_size = MAX_PAGE_SIZE

    def get_page_size(self, request):
        return max(super().get_page_size(request) or 0, self.page_size or 0) or None

    def paginate_queryset(self, queryset, request, view=None):
        return super().paginate_queryset(stable(queryset), request, view=view)
