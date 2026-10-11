"""預設来源只在新交易帶入；每張單自行保存，不反寫會員。"""
from rest_framework import serializers

from .models import Customer, Member


def sales_default(tenant):
    return Customer.objects.for_tenant(tenant).filter(is_sales_default=True, is_active=True).first()


def member_source(member, tenant):
    if member is None or member.default_source_mode == Member.SourceMode.SALES_DEFAULT:
        return sales_default(tenant)
    if member.default_source_mode == Member.SourceMode.DIRECT:
        return None
    source = member.default_customer
    if source is None or source.tenant_id != tenant.pk or not source.is_active:
        raise serializers.ValidationError({"customer": "會員預設來源已停用或不屬於本公司，請選本次來源"})
    return source


def transaction_source(data, tenant):
    source = data.get("customer") if "customer" in data else member_source(data.get("member"), tenant)
    if source is not None and (source.tenant_id != tenant.pk or not source.is_active):
        raise serializers.ValidationError({"customer": "來源已停用或不屬於本公司"})
    return source
