from django.contrib import admin

from .models import Category, Product


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "sort_order", "next_sku_seq", "is_active")
    list_editable = ("sort_order", "is_active")
    list_filter = ("is_active",)
    search_fields = ("code", "name")
    readonly_fields = ("next_sku_seq",)
    ordering = ("sort_order", "code")


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        "sku",
        "name",
        "category",
        "is_virtual",
        "list_price",
        "requires_serial",
        "counts_cash",
        "counts_margin",
        "is_active",
    )
    list_filter = (
        "is_active",
        "is_virtual",
        "category",
        "requires_serial",
        "allows_telecom_line",
        "allows_commission",
        "counts_cash",
        "counts_margin",
    )
    search_fields = ("sku", "name", "barcode")
    readonly_fields = ("sku", "weighted_avg_cost")
    ordering = ("sku",)
    autocomplete_fields = ("category",)
    fieldsets = (
        ("基本", {"fields": ("sku", "name", "spec", "barcode", "category")}),
        ("價格與成本", {"fields": ("list_price", "weighted_avg_cost")}),
        (
            "屬性",
            {
                "fields": (
                    "requires_serial",
                    "allows_telecom_line",
                    "allows_commission",
                    "is_active",
                ),
            },
        ),
        (
            "會計處理",
            {
                "fields": (
                    "is_virtual",
                    "counts_cash",
                    "counts_margin",
                ),
            },
        ),
    )
