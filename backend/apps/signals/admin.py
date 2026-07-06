from django.contrib import admin

from .models import DemandAlert, MarketSignal, SubjectAlias


@admin.register(SubjectAlias)
class SubjectAliasAdmin(admin.ModelAdmin):
    list_display = ("alias", "subject_key", "kind", "product")
    list_filter = ("kind",)
    search_fields = ("alias", "subject_key")


@admin.register(MarketSignal)
class MarketSignalAdmin(admin.ModelAdmin):
    list_display = ("period_date", "source", "subject_key", "value")
    list_filter = ("source",)
    search_fields = ("subject_key",)


@admin.register(DemandAlert)
class DemandAlertAdmin(admin.ModelAdmin):
    list_display = ("window_end", "direction", "authorized", "subject_key", "product",
                    "heat_growth", "internal_growth", "status")
    list_filter = ("direction", "authorized", "status", "kind")
    search_fields = ("subject_key",)
