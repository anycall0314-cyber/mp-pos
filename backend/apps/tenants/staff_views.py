"""員工帳號的權限勾選(系統設定 → 員工帳號)。只有公司管理員 / 平台管理員能看、能改。

帳號的新增、停用、密碼、門市照舊在平台管理;這裡只管「這個店員帳號哪幾項可以做」。
清單與判斷在 abilities.py。
"""
from django.db import transaction
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import abilities
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
        profile.save(update_fields=["denied_abilities", "updated_at"])
    profile = _company_accounts(request.tenant).get(pk=profile.pk)
    return Response(_row(profile))
