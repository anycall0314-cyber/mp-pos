from django.conf import settings
from django.utils.functional import SimpleLazyObject


def _get_default_tenant():
    from apps.tenants.models import Tenant

    tenant, _ = Tenant.objects.get_or_create(
        id=settings.DEFAULT_TENANT_ID,
        defaults={"name": "Default", "code": "default"},
    )
    return tenant


class TenantMiddleware:
    """
    MVP 階段把 request.tenant 寫死成 DEFAULT_TENANT_ID。
    轉 SaaS 時改成從 JWT / subdomain 解析即可，業務碼不動。
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.tenant = SimpleLazyObject(_get_default_tenant)
        return self.get_response(request)
