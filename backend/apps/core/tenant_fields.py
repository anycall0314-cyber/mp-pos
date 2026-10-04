"""序列化器的關聯欄位只認「這家公司」的資料。

DRF 的 ModelSerializer 對外鍵預設接受整張表的任何編號;多家公司共用資料庫時,
猜到別家的編號就能把別家的門市 / 商品 / 序號 / 單據掛進自己的單。這個 mixin 在
get_fields() 時把每一個指向「有 tenant 欄位的表」的關聯欄位,限縮到 request.tenant。
巢狀的明細序列化器也要掛(它們從最外層拿到同一個 request)。
沒有 request 的內部使用(例如測試或指令直接呼叫)不限縮;service 層另外再核對一次。
"""
from rest_framework import serializers


def _limit(field, tenant):
    target = field.child_relation if isinstance(field, serializers.ManyRelatedField) else field
    if not isinstance(target, serializers.RelatedField) or target.read_only:
        return
    qs = target.queryset
    if qs is None:
        return
    model = qs.model
    if any(f.name == "tenant" for f in model._meta.get_fields()):
        target.queryset = qs.filter(tenant=tenant)


class TenantScopedRelatedFieldsMixin:
    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get("request") if hasattr(self, "context") else None
        tenant = getattr(request, "tenant", None)
        if tenant is None:
            return fields
        for field in fields.values():
            _limit(field, tenant)
        return fields
