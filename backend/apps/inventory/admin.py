from django.contrib import admin

from .models import ProductSerial, StockMovement, Warehouse


@admin.register(Warehouse)
class WarehouseAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "is_active")
    list_filter = ("is_active",)
    search_fields = ("code", "name")


@admin.register(ProductSerial)
class ProductSerialAdmin(admin.ModelAdmin):
    list_display = ("serial_no", "product", "warehouse", "status", "purchase_unit_cost", "received_at")
    list_filter = ("status", "warehouse")
    search_fields = ("serial_no", "product__sku", "product__name")
    raw_id_fields = ("product",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ("created_at", "movement_type", "serial", "from_warehouse", "to_warehouse")
    list_filter = ("movement_type",)
    search_fields = ("serial__serial_no", "ref_doc_type")
    raw_id_fields = ("serial",)
    readonly_fields = ("created_at", "updated_at")
