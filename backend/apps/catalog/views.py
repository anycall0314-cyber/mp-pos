from django.db.models import Count, OuterRef, Q, Subquery
from rest_framework import viewsets

from apps.inventory.models import ProductSerial
from apps.purchasing.models import PurchaseOrderItem

from .models import Category, Product
from .serializers import CategorySerializer, ProductSerializer


class CategoryViewSet(viewsets.ModelViewSet):
    serializer_class = CategorySerializer
    search_fields = ["code", "name"]
    ordering_fields = ["sort_order", "code", "name", "created_at"]
    ordering = ["sort_order", "code"]
    filterset_fields = ["is_active"]

    def get_queryset(self):
        return Category.objects.for_tenant(self.request.tenant)

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)


class ProductViewSet(viewsets.ModelViewSet):
    serializer_class = ProductSerializer
    search_fields = ["sku", "name", "spec", "barcode", "category__name", "category__code"]
    ordering_fields = ["sku", "name", "created_at", "list_price"]
    ordering = ["sku"]
    filterset_fields = ["is_active", "category", "requires_serial"]

    def get_queryset(self):
        tenant = self.request.tenant
        # 上一次進貨(不含作廢)的單價
        last_price_sq = (
            PurchaseOrderItem.objects.filter(
                product=OuterRef("pk"),
                po__is_void=False,
            )
            .order_by("-po__doc_date", "-id")
            .values("unit_price")[:1]
        )
        return (
            Product.objects.for_tenant(tenant)
            .select_related("category")
            .annotate(
                stock_qty=Count(
                    "serials",
                    filter=Q(serials__status=ProductSerial.Status.IN_STOCK),
                ),
                last_purchase_price=Subquery(last_price_sq),
            )
        )

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)
