from datetime import date

from django.conf import settings
from django.db import models, transaction

from apps.core.models import TenantOwnedModel


class TransferOrder(TenantOwnedModel):
    """調撥單(單頭)。儲存即生效;單步從來源倉直接到目的倉。"""

    no = models.CharField(
        "單號",
        max_length=30,
        editable=False,
        blank=True,
        help_text="系統自動產生:TR-{6位流水}",
    )
    from_warehouse = models.ForeignKey(
        "inventory.Warehouse",
        on_delete=models.PROTECT,
        related_name="transfer_outs",
        verbose_name="來源倉",
    )
    to_warehouse = models.ForeignKey(
        "inventory.Warehouse",
        on_delete=models.PROTECT,
        related_name="transfer_ins",
        verbose_name="目的倉",
    )
    doc_date = models.DateField("單據日期", default=date.today)
    note = models.CharField("備註", max_length=200, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
        null=True,
        blank=True,
        verbose_name="作業者",
    )
    is_void = models.BooleanField("作廢", default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "no"], name="uniq_to_tenant_no"),
        ]
        ordering = ["-doc_date", "-id"]
        verbose_name = "調撥單"
        verbose_name_plural = "調撥單"

    def __str__(self) -> str:
        return self.no

    def save(self, *args, **kwargs):
        if not self.no:
            with transaction.atomic():
                last = (
                    TransferOrder.objects.filter(tenant=self.tenant)
                    .order_by("-id")
                    .first()
                )
                if last and last.no:
                    try:
                        last_seq = int(last.no.split("-")[-1])
                    except (ValueError, IndexError):
                        last_seq = 0
                else:
                    last_seq = 0
                self.no = f"TR-{last_seq + 1:06d}"
        super().save(*args, **kwargs)


class TransferOrderItem(TenantOwnedModel):
    """調撥明細。一行 = 一個商品。序號商品掛 serials M2M,配件只填 qty。"""

    to = models.ForeignKey(
        TransferOrder,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name="調撥單",
    )
    line_no = models.PositiveIntegerField("行號", default=1)
    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.PROTECT,
        related_name="transfer_items",
        verbose_name="商品",
    )
    qty = models.PositiveIntegerField("數量", default=1)
    note = models.CharField("備註", max_length=200, blank=True)

    class Meta:
        ordering = ["to", "line_no"]
        verbose_name = "調撥明細"
        verbose_name_plural = "調撥明細"

    def __str__(self) -> str:
        return f"{self.to_id}::{self.line_no}"


class TransferOrderItemSerial(TenantOwnedModel):
    """調撥明細的序號(序號商品才有)。"""

    item = models.ForeignKey(
        TransferOrderItem,
        on_delete=models.CASCADE,
        related_name="serials",
        verbose_name="調撥明細",
    )
    serial = models.ForeignKey(
        "inventory.ProductSerial",
        on_delete=models.PROTECT,
        related_name="transfer_item_serials",
        verbose_name="序號",
    )
    line_pos = models.PositiveIntegerField("位序", default=0)

    class Meta:
        ordering = ["item", "line_pos", "id"]
        verbose_name = "調撥明細序號"
        verbose_name_plural = "調撥明細序號"

    def __str__(self) -> str:
        return f"{self.item_id}::{self.serial_id}"
