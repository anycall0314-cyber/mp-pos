"""員工帳號(系統設定 → 員工帳號)。只有公司管理員 / 平台管理員能看、能改。

這裡管:店員帳號哪幾項可以做(清單與判斷在 abilities.py);幫店員重設密碼、停用 / 啟用店員帳號
(owner 2026-10-19:老闆要收得回離職的人的帳號)。管理員帳號、新增帳號、門市照舊在平台管理。
"""
from django.db import transaction
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import abilities
from .auth_views import password_problem, set_password_and_sign_out
from .models import UserProfile
from .permissions import is_tenant_admin


def _row(profile) -> dict:
    user = profile.user
    sales_person = getattr(user, "sales_person", None)
    store = profile.default_warehouse
    return {
        "id": user.id,
        "username": user.username,
        "name": (sales_person.name if sales_person else "") or f"{user.last_name}{user.first_name}",
        "role": profile.role,
        "role_label": profile.get_role_display(),
        "warehouse": f"{store.code} {store.name}" if store else "",
        "is_active": user.is_active,
        # 管理員永遠全開、不能在這裡關
        "editable": profile.role == UserProfile.Role.TENANT_USER,
        "abilities": abilities.for_user(user),
    }


def _company_accounts(tenant):
    return (
        UserProfile.objects.filter(tenant=tenant)
        .select_related("user", "user__sales_person", "default_warehouse")
        .order_by("role", "user__username")
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def staff_accounts(request):
    if not is_tenant_admin(request.user):
        return Response({"detail": "只有管理員可以看員工帳號的權限"}, status=status.HTTP_403_FORBIDDEN)
    return Response({
        "abilities": abilities.catalog(),
        "accounts": [_row(p) for p in _company_accounts(request.tenant)],
    })


@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def staff_account(request, pk: int):
    if not is_tenant_admin(request.user):
        return Response({"detail": "只有管理員可以改員工帳號的權限"}, status=status.HTTP_403_FORBIDDEN)
    wanted = request.data.get("abilities") if isinstance(request.data, dict) else None
    if not isinstance(wanted, dict) or not wanted:
        return Response({"detail": "沒有要改的項目"}, status=status.HTTP_400_BAD_REQUEST)
    unknown = [k for k in wanted if not isinstance(k, str) or k not in abilities.KEYS]
    if unknown:
        return Response({"detail": "沒有這個權限項目"}, status=status.HTTP_400_BAD_REQUEST)
    if any(not isinstance(v, bool) for v in wanted.values()):
        return Response({"detail": "每一項只能是可以 / 不可以"}, status=status.HTTP_400_BAD_REQUEST)
    with transaction.atomic():
        # 連點兩項會有兩個請求同時進來:鎖住這個帳號再改,後到的看得到先到的結果(不然會互相蓋掉)
        profile = (
            UserProfile.objects.select_for_update()
            .filter(tenant=request.tenant, user_id=pk).first()
        )
        if profile is None:
            return Response({"detail": "找不到這個帳號"}, status=status.HTTP_404_NOT_FOUND)
        if profile.role != UserProfile.Role.TENANT_USER:
            return Response({"detail": "管理員帳號永遠全開,不能在這裡關"}, status=status.HTTP_400_BAD_REQUEST)
        profile.denied_abilities = abilities.change(profile, wanted)
        # 這一次要開的項目,開了也還是不能用(它要的另外幾項關著)→ 不存、講要先開哪幾項(不然那一格會自己彈回去,人不知道為什麼)
        off = abilities.switched_off(profile)
        for key, allowed in wanted.items():
            because = abilities.blocked_by(off, key) if allowed else []
            if because:
                names = "、".join(abilities.LABELS[k] for k in because)
                return Response(
                    {"detail": f"「{abilities.LABELS[key]}」要先開:{names}"},
                    status=status.HTTP_400_BAD_REQUEST)
        profile.save(update_fields=["denied_abilities", "updated_at"])
    profile = _company_accounts(request.tenant).get(pk=profile.pk)
    return Response(_row(profile))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def staff_account_access(request, pk: int):
    """幫自己公司的店員重設密碼(`{"password": ...}`),或停用 / 啟用那個帳號(`{"is_active": false/true}`)。

    重設或停用都會讓那個店員每一台都要重新登入。停用連業務員一起停(開單選不到他),啟用一起開;
    以前的單據、獎金都還在(不刪帳號,單據指著他)。管理員帳號這裡不能動。
    """
    from rest_framework.authtoken.models import Token

    if not is_tenant_admin(request.user):
        return Response({"detail": "只有管理員可以管員工帳號"}, status=status.HTTP_403_FORBIDDEN)
    data = request.data if isinstance(request.data, dict) else {}
    wants_password, wants_active = "password" in data, "is_active" in data
    if wants_password == wants_active:
        return Response({"detail": "沒有要改的項目"}, status=status.HTTP_400_BAD_REQUEST)
    if wants_password:
        problem = password_problem(data["password"])
        if problem:
            return Response({"detail": problem}, status=status.HTTP_400_BAD_REQUEST)
    elif not isinstance(data["is_active"], bool):
        return Response({"detail": "只能是停用 / 啟用"}, status=status.HTTP_400_BAD_REQUEST)
    with transaction.atomic():
        profile = (
            UserProfile.objects.select_for_update()
            .select_related("user").filter(tenant=request.tenant, user_id=pk).first()
        )
        if profile is None:
            return Response({"detail": "找不到這個帳號"}, status=status.HTTP_404_NOT_FOUND)
        if profile.role != UserProfile.Role.TENANT_USER:
            return Response({"detail": "管理員帳號請找平台"}, status=status.HTTP_400_BAD_REQUEST)
        user = profile.user
        if wants_password:
            set_password_and_sign_out(user, data["password"])
        else:
            user.is_active = data["is_active"]
            user.save(update_fields=["is_active"])
            if not user.is_active:
                Token.objects.filter(user=user).delete()
            sales_person = getattr(user, "sales_person", None)
            if sales_person is not None and sales_person.is_active != user.is_active:
                sales_person.is_active = user.is_active
                sales_person.save(update_fields=["is_active", "updated_at"])
    profile = _company_accounts(request.tenant).get(pk=profile.pk)
    return Response(_row(profile))
