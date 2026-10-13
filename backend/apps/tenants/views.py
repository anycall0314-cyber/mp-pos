from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Q
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core import staff_cost
from apps.core.warehouse_scoping import locked_warehouse_id

from . import abilities
from .models import InvoiceTrack, InvoiceType, PaymentMethod
from .serializers import (
    InvoiceTrackJumpSerializer,
    InvoiceTrackSerializer,
    InvoiceTypeSerializer,
    PaymentMethodSerializer,
)
from .services import (
    InvoiceTrackError,
    jump_invoice_track,
    lock_track_setup,
    no_track_reason,
    peek_next_track,
    track_in_use,
    upcoming_period_gap,
)


class InvoiceTypeViewSet(viewsets.ModelViewSet):
    """發票類型主檔。

    code 不可改;只允許切換 is_active / is_default / 改名稱 / 排序。
    is_default 一次只有一個生效:存的時候若把某筆設為 default,自動清除其他的。
    """

    serializer_class = InvoiceTypeSerializer
    search_fields = ["code", "name"]
    ordering = ["sort_order", "code"]
    filterset_fields = ["is_active"]
    http_method_names = ["get", "patch", "put", "head", "options"]

    def get_queryset(self):
        return InvoiceType.objects.for_tenant(self.request.tenant)

    @transaction.atomic
    def perform_update(self, serializer):
        instance = serializer.save()
        if instance.is_default:
            InvoiceType.objects.for_tenant(instance.tenant).exclude(
                pk=instance.pk
            ).update(is_default=False)


class InvoiceTrackViewSet(abilities.WritesNeed, viewsets.ModelViewSet):
    """發票字軌主檔。

    - 新增 / 修改 / 刪除 / 跳號要有「發票字軌」那一項(`abilities.INVOICE_TRACKS`);看字軌、預覽下一張不用(開單要用)。
    - 鎖在門市的帳號只看得到自己門市的與全公司共用的;只能新增、修改、刪除自己門市的。
      共用的(分門市之前建的舊字軌)它只能跳號(它的發票機卡紙時要對得回來),其他要管理員。
    """

    serializer_class = InvoiceTrackSerializer
    needs_ability = abilities.INVOICE_TRACKS
    search_fields = ["prefix", "period_label", "note"]
    ordering = ["-id"]
    filterset_fields = ["invoice_type", "is_active", "warehouse"]

    def get_queryset(self):
        qs = InvoiceTrack.objects.for_tenant(self.request.tenant).select_related(
            "invoice_type", "warehouse"
        )
        store = locked_warehouse_id(self.request.user)
        if store is not None:
            qs = qs.filter(Q(warehouse_id=store) | Q(warehouse__isnull=True))
        return qs

    def get_object(self):
        """要改、要刪的那一條:**鎖住之後重新讀**(呼叫的地方已經在交易裡)。
        不鎖的話,檢查與存檔用的是進來時讀到的那一份 —— 中間剛好有人結帳取了號(或跳了號),存檔會把「下一張」蓋回舊的,之後開出重複的號碼。"""
        track = super().get_object()
        if self.action in ("update", "partial_update", "destroy"):
            track = self.get_queryset().select_for_update(of=("self",)).get(pk=track.pk)
        return track

    def create(self, request, *args, **kwargs):
        with transaction.atomic():
            lock_track_setup(request.tenant)          # 同一家公司一次一個人動字軌的設定(重疊檢查才看得到對方)
            return super().create(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        with transaction.atomic():
            lock_track_setup(request.tenant)          # 先拿公司這一把,get_object 才鎖字軌那一列
            return super().update(request, *args, **kwargs)

    def _own_store_only(self, warehouse_id):
        store = locked_warehouse_id(self.request.user)
        if store is not None and warehouse_id != store:
            raise PermissionDenied("這個帳號只能設定自己門市的字軌")

    def perform_create(self, serializer):
        self._own_store_only(getattr(serializer.validated_data.get("warehouse"), "id", None))
        serializer.save(tenant=self.request.tenant)

    def perform_update(self, serializer):
        self._own_store_only(serializer.instance.warehouse_id)
        if "warehouse" in serializer.validated_data:
            self._own_store_only(getattr(serializer.validated_data["warehouse"], "id", None))
        serializer.save()

    def destroy(self, request, *args, **kwargs):
        with transaction.atomic():
            track = self.get_object()                 # 鎖住:檢查「用過沒有」到刪掉之間不會有人剛好取號
            self._own_store_only(track.warehouse_id)
            if track_in_use(track):
                return Response(
                    {"detail": "這條字軌已經開過發票或跳過號,不能刪;不用了請改成停用"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            track.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=["get"])
    def peek(self, request):
        """預覽下一張要開的發票號碼(不真正取號),以及它是哪一條字軌的(開單頁的「跳號」要用)。

        GET /api/v1/invoice-tracks/peek/?invoice_type_code=ev_tri&warehouse=3
        鎖在門市的帳號一律看自己門市;沒有帶門市 → 只看全公司共用的字軌。
        """
        code = request.query_params.get("invoice_type_code", "")
        store = locked_warehouse_id(request.user)
        if store is None:
            raw = request.query_params.get("warehouse") or ""
            store = int(raw) if raw.isascii() and raw.isdigit() else None
        track = peek_next_track(request.tenant, code, store)
        if track is None:
            # detail = 取不到號的原因(「115年11-12月 的字軌還沒設定」/「…用完了」):開單頁照著講
            return Response(
                {"next_invoice_no": None, "track": None, "upcoming": "",
                 "detail": no_track_reason(request.tenant, code, store) or "無可用字軌"},
                status=status.HTTP_200_OK,
            )
        return Response({
            "next_invoice_no": track.format_number(track.next_number),
            "track": InvoiceTrackSerializer(track, context=self.get_serializer_context()).data,
            # 快換期了、下一期的字軌還沒設定 → 下一期的名稱(開單頁先提醒);不用提醒是空字串
            "upcoming": upcoming_period_gap(request.tenant, code, store),
        })

    @action(detail=True, methods=["post"])
    def jump(self, request, pk=None):
        """跳號:把「下一張」改成發票機裡那捲紙的下一張。

        POST /api/v1/invoice-tracks/{id}/jump/  {"next_number": 12345690, "reason": "卡紙"}
        """
        track = self.get_object()          # 看不到的字軌(別家公司、別間門市)在這裡就是 404
        raw = request.data.get("next_number")
        if isinstance(raw, str) and raw.isascii() and raw.isdigit():
            raw = int(raw)
        reason = request.data.get("reason") or ""
        if not isinstance(reason, str):
            reason = ""
        try:
            track, _ = jump_invoice_track(
                request.tenant, track.pk, raw, user=request.user, reason=reason
            )
        except InvoiceTrackError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        track = self.get_queryset().get(pk=track.pk)
        return Response(self.get_serializer(track).data)

    @action(detail=True, methods=["get"])
    def jumps(self, request, pk=None):
        """這條字軌的跳號紀錄(新的在前)。"""
        track = self.get_object()
        rows = track.jumps.select_related("track", "created_by__profile").order_by("-id")
        return Response(InvoiceTrackJumpSerializer(rows, many=True).data)


class PaymentMethodViewSet(viewsets.ModelViewSet):
    """付款方式主檔。

    code 不可改;is_default 一次只有一個生效。
    刪除允許(使用者自行新增的支付通路可移除)。
    """

    serializer_class = PaymentMethodSerializer
    search_fields = ["code", "name", "note"]
    ordering = ["sort_order", "code"]
    filterset_fields = ["is_active", "kind"]

    def get_queryset(self):
        return PaymentMethod.objects.for_tenant(self.request.tenant)

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)

    @transaction.atomic
    def perform_update(self, serializer):
        instance = serializer.save()
        if instance.is_default:
            PaymentMethod.objects.for_tenant(instance.tenant).exclude(
                pk=instance.pk
            ).update(is_default=False)


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def tenant_settings(request):
    """GET 回租戶層級設定;PATCH 更新(限 tenant_admin / platform_admin)。"""
    tenant = request.tenant
    profile = getattr(request.user, "profile", None)
    role = profile.role if profile else None
    is_manager = role in ("platform_admin", "tenant_admin")
    # 業務員成本全公司的那一條(績效的基準):只有管理員拿得到、改得動
    staff_rule = {
        "staff_cost_mode": tenant.staff_cost_mode,
        "staff_cost_value": str(tenant.staff_cost_value),
    }
    if request.method == "GET":
        return Response(
            {
                "id": tenant.id,
                "name": tenant.name,
                "code": tenant.code,
                "repair_warranty_days": tenant.repair_warranty_days,
                "contract_remind_months": tenant.contract_remind_months,
                **(staff_rule if is_manager else {}),
            }
        )
    if not is_manager:
        return Response({"detail": "權限不足"}, status=status.HTTP_403_FORBIDDEN)
    days = request.data.get("repair_warranty_days")
    if days is not None:
        try:
            days = int(days)
        except (ValueError, TypeError):
            return Response(
                {"detail": "保固天數需為整數"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if days < 1 or days > 3650:
            return Response(
                {"detail": "保固天數需在 1 ~ 3650 之間"},
                status=status.HTTP_400_BAD_REQUEST,
            )
    months = request.data.get("contract_remind_months")
    if months is not None:
        try:
            months = int(months)
        except (ValueError, TypeError):
            return Response(
                {"detail": "提醒的月數需為整數"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if months < 1 or months > 24:
            return Response(
                {"detail": "提醒的月數需在 1 ~ 24 之間"},
                status=status.HTTP_400_BAD_REQUEST,
            )
    mode = request.data.get("staff_cost_mode")
    value = request.data.get("staff_cost_value")
    if mode is not None or value is not None:
        changing_mode = mode is not None
        mode = tenant.staff_cost_mode if mode is None else mode
        try:
            if value is not None:
                value = Decimal(str(value))
                if not value.is_finite():
                    raise InvalidOperation
                value = staff_cost.cents(value)          # 先收到分(四捨五入),再看放不放得下
            elif not changing_mode:
                value = tenant.staff_cost_value
            # 換算法而沒有送數字:value 留著 None,下面會講「請填數字」(不沿用原本的)
        except (InvalidOperation, ValueError, TypeError):
            return Response({"detail": "業務員成本的數字不對"}, status=status.HTTP_400_BAD_REQUEST)
        problem = staff_cost.check(mode, value, staff_cost.COMPANY_MODES)
        if problem is None and value is not None and value >= Decimal("1000000000000"):
            problem = "數字太大"
        if problem:
            return Response({"detail": f"業務員成本{problem}"}, status=status.HTTP_400_BAD_REQUEST)
        value = Decimal("0") if not mode else value            # 尚未設定:數值不留
    # 全部檢查過才存:其中一個不對就整筆不動(不會回了錯誤、另一個欄位卻已經改掉)
    changed = []
    if days is not None:
        tenant.repair_warranty_days = days
        changed.append("repair_warranty_days")
    if months is not None:
        tenant.contract_remind_months = months
        changed.append("contract_remind_months")
    if mode is not None:
        tenant.staff_cost_mode, tenant.staff_cost_value = mode, value
        changed += ["staff_cost_mode", "staff_cost_value"]
    if changed:
        tenant.save(update_fields=changed)
    return Response(
        {
            "id": tenant.id,
            "repair_warranty_days": tenant.repair_warranty_days,
            "contract_remind_months": tenant.contract_remind_months,
            "staff_cost_mode": tenant.staff_cost_mode,
            "staff_cost_value": str(tenant.staff_cost_value),
        }
    )
