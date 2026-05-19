from django.contrib import admin

from .models import Carrier, Customer, SalesPerson, SimCard, Supplier, TelecomPlan


@admin.register(SalesPerson)
class SalesPersonAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "phone", "is_active")
    list_filter = ("is_active",)
    search_fields = ("code", "name", "phone")
    ordering = ("code",)


@admin.register(Carrier)
class CarrierAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "is_active")
    list_filter = ("is_active",)
    search_fields = ("code", "name")


@admin.register(SimCard)
class SimCardAdmin(admin.ModelAdmin):
    list_display = (
        "card_no",
        "vendor",
        "deposit",
        "deposit_refunded",
        "status",
        "issued_at",
        "activated_at",
    )
    list_filter = ("vendor", "status", "deposit_refunded")
    search_fields = ("card_no", "vendor__code", "vendor__name", "note")
    autocomplete_fields = ("vendor",)
    readonly_fields = ("issued_at", "activated_at", "returned_at")


@admin.register(TelecomPlan)
class TelecomPlanAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "name",
        "carrier",
        "monthly_fee",
        "contract_months",
        "kind",
        "commission",
        "is_active",
    )
    list_filter = ("carrier", "kind", "is_active")
    search_fields = ("code", "name", "carrier__code", "carrier__name", "note")
    readonly_fields = ("code",)
    autocomplete_fields = ("carrier",)
    ordering = ("carrier__code", "monthly_fee", "contract_months")


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "contact", "phone", "is_active")
    list_filter = ("is_active",)
    search_fields = ("code", "name", "contact", "phone", "tax_id")
    ordering = ("code",)


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("phone", "name", "kind", "is_member", "tax_id", "is_active")
    list_filter = ("kind", "is_member", "is_active")
    search_fields = ("phone", "name", "tax_id")
    ordering = ("phone",)
