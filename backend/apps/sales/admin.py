from django.contrib import admin

from .models import SalesOrder, SalesOrderItem


class SalesOrderItemInline(admin.TabularInline):
    model = SalesOrderItem
    extra = 1
    autocomplete_fields = ("product", "sim_card")
    fields = (
        "line_no",
        "product",
        "qty",
        "unit_price",
        "amount",
        "cost_at_post",
        "sim_card",
        "msisdn",
        "telecom_plan",
        "commission",
        "activation_date",
        "note",
    )
    readonly_fields = ("amount", "cost_at_post")


@admin.register(SalesOrder)
class SalesOrderAdmin(admin.ModelAdmin):
    list_display = (
        "no",
        "doc_date",
        "customer",
        "warehouse",
        "subtotal",
        "tax_amount",
        "total",
        "created_at",
    )
    list_filter = ("warehouse", "tax_method", "sales_type", "doc_date")
    search_fields = (
        "no",
        "customer__code",
        "customer__name",
        "invoice_no",
        "note",
    )
    readonly_fields = ("no", "subtotal", "tax_amount", "total")
    autocomplete_fields = ("customer", "warehouse")
    date_hierarchy = "doc_date"
    inlines = [SalesOrderItemInline]
    ordering = ("-doc_date", "-id")
