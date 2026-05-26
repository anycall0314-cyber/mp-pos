"""自訂 DRF permission。"""
from rest_framework import permissions


class IsPlatformAdmin(permissions.BasePermission):
    """只有 platform_admin 角色才能呼叫。"""

    message = "需要平台管理員權限"

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        profile = getattr(request.user, "profile", None)
        return bool(profile and profile.role == "platform_admin")


class IsTenantAdminOrAbove(permissions.BasePermission):
    """tenant_admin 或 platform_admin 才能呼叫(管理該 tenant 內的設定)。"""

    message = "需要經銷商管理員或平台管理員權限"

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        profile = getattr(request.user, "profile", None)
        if not profile:
            return False
        return profile.role in ("platform_admin", "tenant_admin")
