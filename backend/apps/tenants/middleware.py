from django.conf import settings
from django.utils.functional import SimpleLazyObject


def _get_default_tenant():
    from apps.tenants.models import Tenant

    tenant, _ = Tenant.objects.get_or_create(
        id=settings.DEFAULT_TENANT_ID,
        defaults={"name": "Default", "code": "default"},
    )
    return tenant


def _resolve_tenant_from_request(request):
    """登入後從 user.profile.tenant 取;否則 fallback 到 DEFAULT_TENANT_ID。

    過渡期(Phase 1 後端 + 前端尚未都上線):前端還沒帶 token 時,viewset 走
    AllowAny 但仍需要 request.tenant,所以 fallback 到 default。等到 Phase 1
    全部完成、permission 切回 IsAuthenticated 之後,沒登入就不會走到這。

    platform_admin 沒有自己的 tenant,要打 tenant-scoped API 時用 query param
    `?tenant=X` 或 header `X-Tenant-ID: X` 切換要看的 tenant。
    """
    from apps.tenants.models import Tenant

    user = getattr(request, "user", None)
    if user and user.is_authenticated:
        profile = getattr(user, "profile", None)
        if profile and profile.tenant_id:
            return profile.tenant
        tenant_id = request.GET.get("tenant") or request.headers.get(
            "X-Tenant-ID"
        )
        if tenant_id and str(tenant_id).isdigit():
            try:
                return Tenant.objects.get(pk=int(tenant_id))
            except Tenant.DoesNotExist:
                pass
    return _get_default_tenant()


def effective_tenant_id(request, user):
    """這個請求實際會落在哪一家公司(只回 id、不建資料)。

    規則必須跟上面的 `_resolve_tenant_from_request` 一模一樣:公司維護鎖用它判斷
    「這個請求會不會動到維護中的公司」。兩邊不一致的話,沒有自己公司的帳號
    (平台管理員)不帶 ?tenant= 時會落到預設公司,鎖卻看不到。改一邊要改另一邊
    (apps/backup 的測試會比對兩者)。
    """
    from apps.tenants.models import Tenant

    profile = getattr(user, "profile", None)
    if profile and profile.tenant_id:
        return profile.tenant_id
    raw = request.GET.get("tenant") or request.headers.get("X-Tenant-ID")
    if raw and str(raw).isdigit() and Tenant.objects.filter(pk=int(raw)).exists():
        return int(raw)
    return settings.DEFAULT_TENANT_ID


class TenantMiddleware:
    """從登入帳號的 UserProfile 解析 tenant;未登入回 DEFAULT_TENANT_ID。

    註:DRF auth 在 viewset dispatch 才會跑,middleware 階段 request.user 還是
    AnonymousUser。所以我們用 SimpleLazyObject 延後解析,等真正存取
    request.tenant 時才執行(那時 DRF 已經把 request.user 換成真實 user)。
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.tenant = SimpleLazyObject(
            lambda: _resolve_tenant_from_request(request)
        )
        return self.get_response(request)
