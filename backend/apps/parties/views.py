from django.db import transaction
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Carrier, Customer, SalesPerson, SimCard, Supplier, TelecomPlan
from .serializers import (
    CarrierSerializer,
    CustomerSerializer,
    SalesPersonSerializer,
    SimCardSerializer,
    SupplierSerializer,
    TelecomPlanSerializer,
)


class SupplierViewSet(viewsets.ModelViewSet):
    serializer_class = SupplierSerializer
    search_fields = ["code", "name", "contact", "phone", "tax_id"]
    ordering_fields = ["sort_order", "code", "name", "created_at"]
    ordering = ["sort_order", "code"]
    filterset_fields = ["is_active"]

    def get_queryset(self):
        return Supplier.objects.for_tenant(self.request.tenant)

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)


class CustomerViewSet(viewsets.ModelViewSet):
    serializer_class = CustomerSerializer
    search_fields = ["code", "phone", "name", "tax_id"]
    ordering_fields = ["code", "phone", "name", "created_at"]
    ordering = ["code"]
    filterset_fields = ["is_active", "kind", "is_member"]

    def get_queryset(self):
        return Customer.objects.for_tenant(self.request.tenant)

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)

    @action(detail=False, methods=["get"], url_path="lookup")
    def lookup(self, request):
        """以電話精準查會員;查無回 404 由前端詢問是否新增。

        phone 在 Customer 上已非唯一(同行多人共用公司電話會發生),
        多筆時優先回傳 is_member=True 的那筆,其次最舊建立的。
        """
        phone = request.query_params.get("phone", "").strip()
        if not phone:
            return Response(
                {"detail": "phone 為必填參數"}, status=status.HTTP_400_BAD_REQUEST
            )
        obj = (
            self.get_queryset()
            .filter(phone=phone)
            .order_by("-is_member", "created_at")
            .first()
        )
        if obj is None:
            return Response(
                {"detail": "未登錄"}, status=status.HTTP_404_NOT_FOUND
            )
        return Response(self.get_serializer(obj).data)


class SalesPersonViewSet(viewsets.ModelViewSet):
    serializer_class = SalesPersonSerializer
    search_fields = ["code", "name", "phone"]
    ordering_fields = ["code", "name", "created_at"]
    ordering = ["code"]
    filterset_fields = ["is_active"]

    def get_queryset(self):
        return SalesPerson.objects.for_tenant(self.request.tenant)

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)


class CarrierViewSet(viewsets.ModelViewSet):
    serializer_class = CarrierSerializer
    search_fields = ["code", "name"]
    ordering_fields = ["code", "name"]
    ordering = ["code"]
    filterset_fields = ["is_active"]

    def get_queryset(self):
        return Carrier.objects.for_tenant(self.request.tenant)

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)


class SimCardViewSet(viewsets.ModelViewSet):
    serializer_class = SimCardSerializer
    search_fields = ["card_no", "vendor__code", "vendor__name", "note"]
    ordering_fields = ["card_no", "vendor__code", "status", "created_at"]
    ordering = ["vendor__code", "card_no"]
    filterset_fields = ["vendor", "status", "deposit_refunded"]

    def get_queryset(self):
        return SimCard.objects.for_tenant(self.request.tenant).select_related(
            "vendor"
        )

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)


# 接受的類型別名(value 為 TelecomPlan.Kind 內部值)
TELECOM_KIND_ALIASES = {
    "new": "new",
    "新辦": "new",
    "renewal": "renewal",
    "續約": "renewal",
    "portin": "portin",
    "攜碼": "portin",
}


class TelecomPlanViewSet(viewsets.ModelViewSet):
    serializer_class = TelecomPlanSerializer
    search_fields = ["name", "code", "carrier__code", "carrier__name", "note"]
    ordering_fields = ["code", "monthly_fee", "contract_months", "commission"]
    ordering = ["carrier__code", "monthly_fee", "contract_months"]
    filterset_fields = ["carrier", "kind", "is_active"]

    def get_queryset(self):
        return TelecomPlan.objects.for_tenant(self.request.tenant).select_related(
            "carrier"
        )

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)

    @action(detail=False, methods=["post"], url_path="bulk")
    def bulk_create(self, request):
        """批次新增電信方案。

        payload:
        {
          "common": { "carrier": int, "kind": "new", "is_active": true },
          "items": [
            { "name": "中華 1399 30月", "monthly_fee": "1399",
              "contract_months": "30", "commission": "12000",
              "kind": "新辦", "carrier_name": "中華電信" }
          ]
        }
        每筆可選 carrier_name(後端依名稱解析覆寫 common.carrier);
        kind 接受 new/新辦、renewal/續約、portin/攜碼。
        任一筆失敗 → 整批 rollback。
        """
        common = request.data.get("common", {}) or {}
        items = request.data.get("items", []) or []
        if not items:
            return Response(
                {"detail": "至少 1 筆"}, status=status.HTTP_400_BAD_REQUEST
            )

        tenant = request.tenant
        carrier_by_name = {
            c.name: c.id for c in Carrier.objects.for_tenant(tenant).all()
        }

        created = []
        errors = []
        try:
            with transaction.atomic():
                for idx, row in enumerate(items, start=1):
                    payload = {**common, **row}
                    if not payload.get("name"):
                        errors.append({"line": idx, "errors": "專案名稱為必填"})
                        continue
                    # 解析 carrier_name → carrier id
                    cname = payload.pop("carrier_name", None)
                    if cname:
                        cid = carrier_by_name.get(cname)
                        if cid is None:
                            errors.append(
                                {"line": idx, "errors": f"電信商「{cname}」不存在"}
                            )
                            continue
                        payload["carrier"] = cid
                    # 解析 kind 別名
                    if payload.get("kind"):
                        k = TELECOM_KIND_ALIASES.get(str(payload["kind"]).strip())
                        if k is None:
                            errors.append(
                                {
                                    "line": idx,
                                    "errors": f"類型「{payload['kind']}」無效(可填 新辦/續約/攜碼)",
                                }
                            )
                            continue
                        payload["kind"] = k
                    serializer = TelecomPlanSerializer(
                        data=payload, context={"request": request}
                    )
                    if serializer.is_valid():
                        instance = serializer.save(tenant=tenant)
                        created.append(TelecomPlanSerializer(instance).data)
                    else:
                        errors.append({"line": idx, "errors": serializer.errors})
                if errors:
                    raise ValueError("validation_failed")
        except ValueError:
            return Response(
                {"detail": "部分品項失敗,已全部復原", "errors": errors},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            {"created": created, "count": len(created)},
            status=status.HTTP_201_CREATED,
        )
