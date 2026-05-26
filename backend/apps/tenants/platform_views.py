"""平台管理員(platform_admin)專用 endpoints。

提供三組 CRUD:
- /platform/tenants/      經銷商主檔(Tenant)
- /platform/users/        所有經銷商底下的使用者(User + UserProfile + 可選 SalesPerson)
- /platform/warehouses/   所有經銷商底下的門市(Warehouse)

所有 endpoint 都鎖 IsPlatformAdmin。
"""
from django.contrib.auth.models import User
from django.db import transaction
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.inventory.models import Warehouse
from apps.parties.models import SalesPerson

from .models import Tenant, UserProfile
from .permissions import IsPlatformAdmin


# ────────────────────────────────────────────────────────────
# Tenant
# ────────────────────────────────────────────────────────────


class PlatformTenantSerializer(serializers.ModelSerializer):
    user_count = serializers.SerializerMethodField()
    warehouse_count = serializers.SerializerMethodField()

    class Meta:
        model = Tenant
        fields = [
            "id",
            "code",
            "name",
            "is_active",
            "user_count",
            "warehouse_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "user_count",
            "warehouse_count",
            "created_at",
            "updated_at",
        ]

    def get_user_count(self, obj):
        return obj.user_profiles.count()

    def get_warehouse_count(self, obj):
        return Warehouse.objects.filter(tenant=obj).count()


class PlatformTenantViewSet(viewsets.ModelViewSet):
    """經銷商主檔。新建後該經銷商初始沒有任何使用者 / 門市,接著用
    /platform/users/ 跟 /platform/warehouses/ 補。
    """

    permission_classes = [IsAuthenticated, IsPlatformAdmin]
    serializer_class = PlatformTenantSerializer
    queryset = Tenant.objects.all().order_by("id")
    search_fields = ["code", "name"]
    filterset_fields = ["is_active"]


# ────────────────────────────────────────────────────────────
# User(含 UserProfile + 可選 SalesPerson)
# ────────────────────────────────────────────────────────────


class PlatformUserSerializer(serializers.ModelSerializer):
    # write
    password = serializers.CharField(
        write_only=True, required=False, allow_blank=False
    )
    tenant = serializers.PrimaryKeyRelatedField(
        queryset=Tenant.objects.all(), required=False, allow_null=True
    )
    role = serializers.ChoiceField(
        choices=UserProfile.Role.choices, required=False
    )
    default_warehouse = serializers.PrimaryKeyRelatedField(
        queryset=Warehouse.objects.all(),
        required=False,
        allow_null=True,
    )
    is_warehouse_locked = serializers.BooleanField(required=False)
    # 是否同步建一筆 SalesPerson 並綁定到此 User
    create_sales_person = serializers.BooleanField(
        write_only=True, required=False, default=False
    )
    sales_person_code = serializers.CharField(
        write_only=True, required=False, allow_blank=True
    )
    # read
    role_display = serializers.CharField(
        source="profile.get_role_display", read_only=True, default=""
    )
    tenant_id_display = serializers.IntegerField(
        source="profile.tenant_id", read_only=True
    )
    tenant_name = serializers.CharField(
        source="profile.tenant.name", read_only=True, default=""
    )
    default_warehouse_id_display = serializers.IntegerField(
        source="profile.default_warehouse_id", read_only=True
    )
    default_warehouse_name = serializers.CharField(
        source="profile.default_warehouse.name", read_only=True, default=""
    )
    is_warehouse_locked_display = serializers.BooleanField(
        source="profile.is_warehouse_locked", read_only=True, default=True
    )
    sales_person_id = serializers.IntegerField(
        source="sales_person.id", read_only=True, default=None
    )
    sales_person_name = serializers.CharField(
        source="sales_person.name", read_only=True, default=""
    )

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "first_name",
            "last_name",
            "email",
            "is_active",
            "is_superuser",
            "password",
            # profile write
            "tenant",
            "role",
            "default_warehouse",
            "is_warehouse_locked",
            # sales person create
            "create_sales_person",
            "sales_person_code",
            # read
            "role_display",
            "tenant_id_display",
            "tenant_name",
            "default_warehouse_id_display",
            "default_warehouse_name",
            "is_warehouse_locked_display",
            "sales_person_id",
            "sales_person_name",
        ]
        read_only_fields = [
            "id",
            "is_superuser",
            "role_display",
            "tenant_id_display",
            "tenant_name",
            "default_warehouse_id_display",
            "default_warehouse_name",
            "is_warehouse_locked_display",
            "sales_person_id",
            "sales_person_name",
        ]

    def validate(self, attrs):
        role = attrs.get("role")
        tenant = attrs.get("tenant")
        if role and role != UserProfile.Role.PLATFORM_ADMIN and tenant is None:
            # 更新時可能 role 沒帶,從 instance 取
            inst = self.instance
            if not inst or not inst.profile.tenant_id:
                raise serializers.ValidationError(
                    {"tenant": "此角色必須指定 tenant"}
                )
        return attrs

    @transaction.atomic
    def create(self, validated):
        password = validated.pop("password", None)
        tenant = validated.pop("tenant", None)
        role = validated.pop("role", UserProfile.Role.TENANT_USER)
        default_warehouse = validated.pop("default_warehouse", None)
        is_warehouse_locked = validated.pop(
            "is_warehouse_locked",
            role == UserProfile.Role.TENANT_USER,  # 預設只店員鎖倉
        )
        create_sp = validated.pop("create_sales_person", False)
        sp_code = validated.pop("sales_person_code", "")
        if not password:
            raise serializers.ValidationError(
                {"password": "建立帳號必須提供密碼"}
            )

        user = User.objects.create_user(
            username=validated["username"],
            email=validated.get("email", ""),
            password=password,
            first_name=validated.get("first_name", ""),
            last_name=validated.get("last_name", ""),
            is_active=validated.get("is_active", True),
        )
        UserProfile.objects.create(
            user=user,
            tenant=tenant if role != UserProfile.Role.PLATFORM_ADMIN else None,
            role=role,
            default_warehouse=default_warehouse,
            is_warehouse_locked=is_warehouse_locked,
        )
        if create_sp and tenant:
            sp_code = (sp_code or user.username).strip()[:20]
            SalesPerson.objects.create(
                tenant=tenant,
                code=sp_code,
                name=(user.first_name or user.username)[:120],
                user=user,
            )
        return user

    @transaction.atomic
    def update(self, instance, validated):
        password = validated.pop("password", None)
        tenant = validated.pop("tenant", "__missing__")
        role = validated.pop("role", "__missing__")
        default_warehouse = validated.pop("default_warehouse", "__missing__")
        is_warehouse_locked = validated.pop(
            "is_warehouse_locked", "__missing__"
        )
        validated.pop("create_sales_person", None)
        validated.pop("sales_person_code", None)

        for k, v in validated.items():
            setattr(instance, k, v)
        if password:
            instance.set_password(password)
        instance.save()

        profile = instance.profile
        if role != "__missing__":
            profile.role = role
            if role == UserProfile.Role.PLATFORM_ADMIN:
                profile.tenant = None
        if tenant != "__missing__":
            profile.tenant = tenant
        if default_warehouse != "__missing__":
            profile.default_warehouse = default_warehouse
        if is_warehouse_locked != "__missing__":
            profile.is_warehouse_locked = is_warehouse_locked
        profile.save()
        return instance


class PlatformUserViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, IsPlatformAdmin]
    serializer_class = PlatformUserSerializer
    search_fields = ["username", "first_name", "last_name", "email"]
    filterset_fields = {
        "profile__tenant": ["exact"],
        "profile__role": ["exact"],
        "is_active": ["exact"],
    }

    def get_queryset(self):
        return (
            User.objects.select_related(
                "profile", "profile__tenant", "profile__default_warehouse"
            )
            .order_by("id")
        )

    @action(detail=True, methods=["post"], url_path="reset-password")
    def reset_password(self, request, pk=None):
        """平台管理員幫使用者重設密碼。
        body: { "password": "新密碼" }
        """
        user = self.get_object()
        new = request.data.get("password", "")
        if not new or len(new) < 4:
            return Response(
                {"detail": "新密碼至少 4 碼"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        user.set_password(new)
        user.save(update_fields=["password"])
        return Response({"detail": "已重設"})


# ────────────────────────────────────────────────────────────
# Warehouse(可跨 tenant)
# ────────────────────────────────────────────────────────────


class PlatformWarehouseSerializer(serializers.ModelSerializer):
    tenant_name = serializers.CharField(
        source="tenant.name", read_only=True, default=""
    )

    class Meta:
        model = Warehouse
        fields = [
            "id",
            "tenant",
            "tenant_name",
            "code",
            "name",
            "address",
            "phone",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "tenant_name", "created_at", "updated_at"]


class PlatformWarehouseViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, IsPlatformAdmin]
    serializer_class = PlatformWarehouseSerializer
    search_fields = ["code", "name", "address", "phone"]
    filterset_fields = ["tenant", "is_active"]

    def get_queryset(self):
        return Warehouse.objects.select_related("tenant").order_by(
            "tenant_id", "code"
        )
