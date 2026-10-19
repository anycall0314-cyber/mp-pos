"""登入 / 取當前使用者 / 登出 endpoints。

設計:
- /auth/login/  POST username + password → 回 token + user 基本資料
- /auth/me/     GET 帶 Authorization: Token xxx → 回當前 user + profile + tenant + warehouse
- /auth/logout/ POST 銷毀當前 token
- /account/password/ POST 自己改密碼(要打對目前的密碼)→ 換一把新 token 回去
  (不放在 /auth/ 底下:/auth/ 不受公司維護鎖管,還原到一半不該改帳號)

token 走 DRF authtoken。一帳號一 token,登出即作廢。
"""
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.db import transaction
from rest_framework import serializers, status
from rest_framework.authtoken.models import Token
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from . import abilities


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
        # 這個帳號每一項能不能做(管理員全開)。畫面照它收按鈕;真正擋的是伺服器
        "abilities": abilities.for_user(user),
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


# 平台重設、老闆重設、自己改都用同一條(平台管理一開始就是 4 碼)
MIN_PASSWORD_LENGTH = 4


def password_problem(new) -> str:
    """新密碼哪裡不行;可以就回空字串。"""
    if not isinstance(new, str) or len(new) < MIN_PASSWORD_LENGTH:
        return f"新密碼至少 {MIN_PASSWORD_LENGTH} 碼"
    # 登入那一格會把前後的空白去掉(LoginSerializer 的 CharField),存了就登不進去
    if new != new.strip():
        return "密碼前後不能有空白"
    return ""


def set_password_and_sign_out(user: User, new: str) -> None:
    """換密碼並作廢這個帳號手上的 token(每一台都要重新登入;離職的人原本開著的畫面也一起失效)。"""
    with transaction.atomic():
        user.set_password(new)
        user.save(update_fields=["password"])
        Token.objects.filter(user=user).delete()


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def change_password(request):
    """自己改自己的密碼(owner 2026-10-19:「登入後沒有修改密碼的選項」)。

    目前的密碼打錯回 400(不是 401:401 會讓畫面直接登出)。改好之後別台都要重新登入,
    這一台拿回傳的新 token 繼續用。
    """
    data = request.data if isinstance(request.data, dict) else {}
    current, new = data.get("current_password"), data.get("new_password")
    if not isinstance(current, str) or not request.user.check_password(current):
        return Response({"detail": "目前的密碼不對"}, status=status.HTTP_400_BAD_REQUEST)
    problem = password_problem(new)
    if problem:
        return Response({"detail": problem}, status=status.HTTP_400_BAD_REQUEST)
    if new == current:
        return Response({"detail": "新密碼跟目前的一樣"}, status=status.HTTP_400_BAD_REQUEST)
    with transaction.atomic():
        set_password_and_sign_out(request.user, new)
        token = Token.objects.create(user=request.user)
    return Response({"token": token.key})
