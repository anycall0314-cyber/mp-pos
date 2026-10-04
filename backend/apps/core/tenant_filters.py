"""篩選條件(?customer=、?warehouse= …)也只認「這家公司」的資料。

django-filter 替每個外鍵篩選自動產生的下拉來源是整張表:別家公司的編號會被當成
「有效的選項」(回 200 空清單),不存在的編號才回 400 —— 等於可以拿來試探別家有哪些編號。
這裡把每個外鍵篩選的來源限縮到 request.tenant,別家的編號跟不存在的編號一樣回 400。
"""
from django_filters import ModelChoiceFilter, ModelMultipleChoiceFilter
from django_filters.rest_framework import DjangoFilterBackend


def _has_tenant(model):
    return any(f.name == "tenant" for f in model._meta.get_fields())


class TenantDjangoFilterBackend(DjangoFilterBackend):
    def get_filterset(self, request, queryset, view):
        filterset = super().get_filterset(request, queryset, view)
        tenant = getattr(request, "tenant", None)
        if filterset is None or tenant is None:
            return filterset
        for f in filterset.filters.values():
            if not isinstance(f, (ModelChoiceFilter, ModelMultipleChoiceFilter)):
                continue
            source = f.queryset
            if source is None or callable(source):
                continue
            if _has_tenant(source.model):
                f.queryset = source.filter(tenant=tenant)
        return filterset
