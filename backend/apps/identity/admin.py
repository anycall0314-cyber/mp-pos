"""Django admin 只當 dev fallback(對齊決策:唯一前端是 React app)。"""
from django.contrib import admin

from .models import IntakeBatch, IntakeDocument, IntakeItem, ProductAlias


@admin.register(ProductAlias)
class ProductAliasAdmin(admin.ModelAdmin):
    list_display = ("value", "kind", "supplier", "product", "verified", "is_active")
    list_filter = ("kind", "verified", "is_active")
    search_fields = ("value", "normalized_value")
    raw_id_fields = ("product", "supplier")


class IntakeItemInline(admin.TabularInline):
    model = IntakeItem
    extra = 0
    raw_id_fields = ("matched_product",)


@admin.register(IntakeBatch)
class IntakeBatchAdmin(admin.ModelAdmin):
    list_display = ("id", "source", "supplier", "status", "vendor_doc_no", "created_at")
    list_filter = ("source", "status")
    inlines = [IntakeItemInline]


@admin.register(IntakeItem)
class IntakeItemAdmin(admin.ModelAdmin):
    list_display = ("batch", "line_no", "raw_text", "match_status", "match_confidence")
    list_filter = ("match_status",)
    search_fields = ("raw_text",)
    raw_id_fields = ("batch", "matched_product")


@admin.register(IntakeDocument)
class IntakeDocumentAdmin(admin.ModelAdmin):
    list_display = ("id", "original_filename", "ocr_status", "batch", "created_at")
    list_filter = ("ocr_status",)
    raw_id_fields = ("batch",)
