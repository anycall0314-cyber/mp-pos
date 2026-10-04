from django.contrib import admin

from .models import ProductSerial, StockMovement, Warehouse


@admin.register(Warehouse)
class WarehouseAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "address", "phone", "is_active")
    list_filter = ("is_active",)
    search_fields = ("code", "name", "address", "phone")


@admin.register(ProductSerial)
class ProductSerialAdmin(admin.ModelAdmin):
    list_display = ("serial_no", "product", "warehouse", "status", "purchase_unit_cost", "received_at")
    list_filter = ("status", "warehouse")
    search_fields = ("serial_no", "product__sku", "product__name")
    raw_id_fields = ("product",)
    # 狀態與序號不能在後台直接改:改序號不會動到登記的碼(別台就能再用同一個碼),
    # 把作廢改回在庫的那一台也不會重新登記。要改碼走 set_codes(),狀態由單據決定。
    readonly_fields = ("created_at", "updated_at", "status", "serial_no")

    # 後台不能新增 / 刪除設備:新增不會登記碼(要走進貨 / 收購的 create_serial()),
    # 刪除會把它的單據紀錄一起弄壞。這裡只留查看與改門市、機況這類欄位。
    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ("created_at", "movement_type", "serial", "from_warehouse", "to_warehouse")
    list_filter = ("movement_type",)
    search_fields = ("serial__serial_no", "ref_doc_type")
    raw_id_fields = ("serial",)
    readonly_fields = ("created_at", "updated_at")
