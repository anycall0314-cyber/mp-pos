"""登入驗證 + 公司維護鎖。

還原進行中(或中斷後還沒確認)的公司,所有操作都要擋下,不然還原到一半有人
開單,那張單不是被蓋掉就是混進還原後的資料裡。擋在「驗證登入」這一步,是因為
每一支 API 都一定會經過這裡;放在個別 view 的權限類別裡,總會漏掉哪一支。
"""
from django.http import HttpResponse
from django.urls import NoReverseMatch, reverse
from rest_framework import status
from rest_framework.authentication import TokenAuthentication
from rest_framework.exceptions import APIException, PermissionDenied
from rest_framework.permissions import SAFE_METHODS, BasePermission

from .models import TenantMaintenance

# 維護中仍然要能用的:登入 / 看自己是誰,以及備份還原自己的畫面
_EXEMPT_PREFIXES = ("/api/v1/auth/", "/api/v1/backup/")
# 平台後台:改哪一家公司看的是網址上的編號或送出的內容,由 BlocksCompanyUnderMaintenance
# 照實際要改的那一筆判斷
_PLATFORM_PREFIX = "/api/v1/platform/"


class CompanyUnderMaintenance(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "公司資料還原中,暫時無法操作,請稍後再試"
    default_code = "company_maintenance"


def _locked(tenant_ids) -> bool:
    ids = {int(t) for t in tenant_ids if t is not None and str(t).isdigit()}
    return bool(ids) and TenantMaintenance.objects.filter(
        tenant_id__in=ids, active=True
    ).exists()


class BlocksCompanyUnderMaintenance(BasePermission):
    """平台後台專用:要改的對象屬於維護中的公司,就擋下。

    平台管理員沒有自己的公司,平台後台的網址也不帶 ?tenant=(改哪一家是看網址上
    的編號或送出的內容),登入驗證那一層看不出來他要動誰 —— 所以在這裡照「實際要
    改的那一筆」判斷。只擋會改資料的動作,查看不擋。
    """

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        data = request.data if hasattr(request.data, "get") else {}
        targets = [data.get("tenant")]          # 新增 / 把人或門市指到維護中的公司
        store = data.get("default_warehouse")   # 把帳號綁到維護中公司的門市
        if store is not None and str(store).isdigit():
            from apps.inventory.models import Warehouse

            targets.append(
                Warehouse.objects.filter(pk=int(store)).values_list("tenant_id", flat=True).first()
            )
        if _locked(targets):
            raise CompanyUnderMaintenance()
        return True

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        if obj._meta.label == "tenants.Tenant":
            owner = obj.pk
        elif hasattr(obj, "tenant_id"):
            owner = obj.tenant_id
        else:                                    # 帳號:看它的 profile 屬於哪家公司
            owner = getattr(getattr(obj, "profile", None), "tenant_id", None)
        if _locked([owner]):
            raise CompanyUnderMaintenance()
        return True


class MaintenanceAwareTokenAuthentication(TokenAuthentication):
    def authenticate(self, request):
        result = super().authenticate(request)
        if result is None:
            return None
        user, _token = result
        if request.path.startswith(_EXEMPT_PREFIXES):
            return result
        from apps.tenants.middleware import effective_tenant_id, may_switch_company

        profile = getattr(user, "profile", None)
        has_company = bool(profile is not None and profile.tenant_id)
        if not has_company and request.path.startswith(_PLATFORM_PREFIX):
            return result
        # 沒綁公司、又不是平台管理員的帳號,不能用任何公司的資料
        # (否則會落到預設公司,或靠 ?tenant= 切到任何一家)
        if not has_company and not may_switch_company(user):
            raise PermissionDenied("這個帳號沒有綁定公司")
        # 看的是「這個請求實際會落在哪一家公司」,跟 TenantMiddleware 同一套規則:
        # 沒有自己公司的帳號不帶 ?tenant=(或帶了不存在的編號)會落到預設公司,
        # 預設公司在維護中就要擋。
        if _locked([effective_tenant_id(request, user)]):
            raise CompanyUnderMaintenance()
        return result


class AdminMaintenanceGuard:
    """Django 管理後台(/admin/)的維護鎖。

    管理後台用的是 session 登入,不經過上面的 token 驗證,也看不出一次修改會動到
    哪一家公司(一個畫面可以改任何公司的資料)。所以做法保守:**只要有任何一家
    公司在還原,管理後台就暫時不能修改**,只能看。登入 / 登出不擋。
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self._prefix = None

    def _admin_prefix(self):
        if self._prefix is None:
            try:
                self._prefix = reverse("admin:index")
            except NoReverseMatch:
                self._prefix = ""
        return self._prefix

    def __call__(self, request):
        prefix = self._admin_prefix()
        if (
            prefix and request.path.startswith(prefix)
            and request.method not in SAFE_METHODS
            and not request.path.startswith((prefix + "login", prefix + "logout"))
            and TenantMaintenance.objects.filter(active=True).exists()
        ):
            return HttpResponse(
                "有公司正在還原資料,管理後台暫時不能修改。請稍後再試。",
                status=503, content_type="text/plain; charset=utf-8",
            )
        return self.get_response(request)
