"""登入 / 取當前使用者 / 登出 endpoints。

設計:
- /auth/login/  POST username + password → 回 token + user 基本資料
- /auth/me/     GET 帶 Authorization: Token xxx → 回當前 user + profile + tenant + warehouse
- /auth/logout/ POST 銷毀當前 token

token 走 DRF authtoken。一帳號一 token,登出即作廢。
"""
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from rest_framework import serializers, status
from rest_framework.authtoken.models import Token
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response


def _serialize_user(user: User) -> dict:
    profile = getattr(user, "profile", None)
    sales_person = getattr(user, "sales_person", None)
    data = {
        "id": user.id,
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "is_superuser": user.is_superuser,
        "profile": None,
        "sales_person": None,
    }
    if profile:
        data["profile"] = {
            "role": profile.role,
            "role_label": profile.get_role_display(),
            "tenant_id": profile.tenant_id,
            "tenant_name": profile.tenant.name if profile.tenant_id else None,
            "default_warehouse_id": profile.default_warehouse_id,
            "default_warehouse_name": (
                profile.default_warehouse.name
                if profile.default_warehouse_id
                else None
            ),
            "is_warehouse_locked": profile.is_warehouse_locked,
        }
    if sales_person:
        data["sales_person"] = {
            "id": sales_person.id,
            "code": sales_person.code,
            "name": sales_person.name,
        }
    return data


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)


@api_view(["POST"])
@authentication_classes([])  # 不要求 token,登入端點本來就是拿 token 的入口
@permission_classes([AllowAny])
def login(request):
    ser = LoginSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    user = authenticate(
        request,
        username=ser.validated_data["username"],
        password=ser.validated_data["password"],
    )
    if user is None:
        return Response(
            {"detail": "帳號或密碼錯誤"},
            status=status.HTTP_401_UNAUTHORIZED,
        )
    if not user.is_active:
        return Response(
            {"detail": "此帳號已停用"},
            status=status.HTTP_403_FORBIDDEN,
        )
    token, _created = Token.objects.get_or_create(user=user)
    return Response({"token": token.key, "user": _serialize_user(user)})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def me(request):
    return Response(_serialize_user(request.user))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def logout(request):
    Token.objects.filter(user=request.user).delete()
    return Response({"detail": "已登出"})
