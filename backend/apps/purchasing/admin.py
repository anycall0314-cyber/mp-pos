import json
import re

from django import forms
from django.contrib import admin

from .models import PurchaseOrder, PurchaseOrderItem


SERIAL_SPLIT_RE = re.compile(r"[\s,;]+")


class PurchaseOrderItemForm(forms.ModelForm):
    """把 serial_numbers JSONField 改成單行輸入,接逗號 / 換行 / 分號分隔。"""

    serial_numbers = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"size": 36, "placeholder": "IMEI1, IMEI2, ..."}),
        label="序號列表",
        help_text="多筆以逗號 / 換行 / 分號分隔;也接受 JSON 陣列",
    )

    class Meta:
        model = PurchaseOrderItem
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        instance = kwargs.get("instance")
        if instance and isinstance(instance.serial_numbers, list):
            self.initial["serial_numbers"] = ", ".join(
                str(s) for s in instance.serial_numbers
            )

    def clean_serial_numbers(self):
        raw = (self.cleaned_data.get("serial_numbers") or "").strip()
        if not raw:
            return []
        if raw.startswith("["):
            try:
                value = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise forms.ValidationError(f"JSON 格式錯誤:{exc}") from exc
            if not isinstance(value, list):
                raise forms.ValidationError("須為陣列")
            return [str(x).strip() for x in value if str(x).strip()]
        parts = SERIAL_SPLIT_RE.split(raw)
        return [p.strip() for p in parts if p.strip()]


class PurchaseOrderItemInline(admin.TabularInline):
    model = PurchaseOrderItem
    form = PurchaseOrderItemForm
    extra = 1
    autocomplete_fields = ("product",)
    fields = (
        "line_no",
        "product",
        "qty",
        "unit_price",
        "amount",
        "serial_numbers",
        "unit_landed_cost",
    )
    readonly_fields = ("amount", "unit_landed_cost")


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):
    list_display = (
        "no",
        "doc_date",
        "supplier",
        "warehouse",
        "tax_method",
        "subtotal",
        "tax_amount",
        "total_cost",
        "created_at",
    )
    list_filter = ("warehouse", "doc_date", "tax_method")
    search_fields = ("no", "supplier__code", "supplier__name", "note")
    readonly_fields = ("no", "subtotal", "tax_amount", "total_cost")
    autocomplete_fields = ("supplier", "warehouse")
    date_hierarchy = "doc_date"
    inlines = [PurchaseOrderItemInline]
    ordering = ("-doc_date", "-id")

    class Media:
        css = {"all": ("admin/inline_compact.css",)}
