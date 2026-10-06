"""商品照片(圖片備註)。

三張表:
- `ProductPhoto`:已經掛在商品上的照片。公司資料,進備份(檔案一起打包)。
- `PhotoDraft`:一次「新增 / 編輯商品」的照片作業。照片先放這裡,商品存檔那一刻才掛上去;
  取消就整份丟掉。手機拍照的配對也綁在這一份作業上(不是綁商品、更不是綁登入的人)。
- `PhotoUpload`:作業裡的一張暫存照片。

後兩張是暫存,不進備份,過期由 `cleanup_photo_drafts` 清掉。
"""
import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.models import TenantOwnedModel


def _photo_path(instance, filename):
    # 檔名一律由伺服器產生(不用上傳時的檔名:裡面可能有個資,也可能撞名)
    return f"product_photos/{instance.tenant_id}/{filename}"


class ProductPhoto(TenantOwnedModel):
    """商品的一張照片:大圖給人核對細節,縮圖給清單用。"""

    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.CASCADE,
        related_name="photos",
        verbose_name="商品",
    )
    image = models.FileField("大圖", upload_to=_photo_path)
    thumb = models.FileField("縮圖", upload_to=_photo_path)
    width = models.PositiveIntegerField("寬", default=0)
    height = models.PositiveIntegerField("高", default=0)
    caption = models.CharField("說明", max_length=40, blank=True)
    sort = models.PositiveIntegerField("順序", default=0)
    is_primary = models.BooleanField("主圖", default=False)

    class Meta:
        ordering = ["-is_primary", "sort", "id"]
        verbose_name = "商品照片"
        verbose_name_plural = "商品照片"
        constraints = [
            # 一個商品最多一張主圖
            models.UniqueConstraint(
                fields=["product"], condition=Q(is_primary=True),
                name="uniq_product_primary_photo",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.product_id} #{self.pk}"


class PhotoDraft(TenantOwnedModel):
    """一次新增 / 編輯商品的照片作業。"""

    class State(models.TextChoices):
        OPEN = "open", "進行中"
        COMMITTED = "committed", "已隨商品儲存"
        CANCELLED = "cancelled", "已取消"

    uid = models.UUIDField("作業識別", default=uuid.uuid4, unique=True, editable=False)
    # 編輯既有商品時是那個商品;新增商品時是空的,存檔成功才填上(同一份作業重送不會再建第二個品號)
    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="商品",
    )
    # 給手機看的:這些照片會放到哪一筆(品名還沒填也要認得出是哪一次作業)
    label = models.CharField("品名", max_length=160, blank=True)
    spec = models.CharField("規格", max_length=160, blank=True)
    state = models.CharField(
        "狀態", max_length=12, choices=State.choices, default=State.OPEN
    )
    # 電腦正在存商品:不收新的照片(已經登記的那幾張可以傳完)
    frozen = models.BooleanField("電腦正在儲存", default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="建立者",
    )
    closed_at = models.DateTimeField("結束時間", null=True, blank=True)

    # ── 手機配對 ──
    # QR Code 裡的憑證只存雜湊;這把憑證只能用來對這一份作業傳照片
    pair_hash = models.CharField("配對憑證雜湊", max_length=64, blank=True, db_index=True)
    pair_expires_at = models.DateTimeField("QR Code 有效到", null=True, blank=True)
    # 配對成功的那一支手機(手機自己產生的識別,只存雜湊):第二支手機接不走
    device_hash = models.CharField("手機識別雜湊", max_length=64, blank=True)
    paired_at = models.DateTimeField("手機連上時間", null=True, blank=True)
    device_active_at = models.DateTimeField("手機最後動作時間", null=True, blank=True)

    class Meta:
        ordering = ["-id"]
        verbose_name = "商品照片作業"
        verbose_name_plural = "商品照片作業"

    def __str__(self) -> str:
        return f"{self.uid} {self.state}"


class PhotoUpload(TenantOwnedModel):
    """作業裡的一張暫存照片。uid 由上傳的那一端產生:同一張重試不會變成兩張。"""

    class Status(models.TextChoices):
        UPLOADING = "uploading", "上傳中"
        READY = "ready", "可用"
        FAILED = "failed", "失敗"
        CANCELLED = "cancelled", "已取消"

    class Source(models.TextChoices):
        DESKTOP = "desktop", "電腦"
        PHONE = "phone", "手機"

    draft = models.ForeignKey(
        PhotoDraft, on_delete=models.CASCADE, related_name="uploads", verbose_name="作業"
    )
    uid = models.CharField("上傳識別", max_length=64)
    source = models.CharField(
        "來源", max_length=8, choices=Source.choices, default=Source.DESKTOP
    )
    status = models.CharField(
        "狀態", max_length=10, choices=Status.choices, default=Status.UPLOADING
    )
    image = models.FileField("大圖", upload_to=_photo_path, blank=True)
    thumb = models.FileField("縮圖", upload_to=_photo_path, blank=True)
    width = models.PositiveIntegerField("寬", default=0)
    height = models.PositiveIntegerField("高", default=0)
    error = models.CharField("失敗原因", max_length=200, blank=True)
    # 已經變成正式的商品照片(檔案交給 ProductPhoto 了,清暫存時不能刪)
    consumed = models.BooleanField("已掛到商品", default=False)

    class Meta:
        ordering = ["id"]
        verbose_name = "暫存照片"
        verbose_name_plural = "暫存照片"
        constraints = [
            models.UniqueConstraint(fields=["draft", "uid"], name="uniq_photo_upload_uid"),
        ]

    def __str__(self) -> str:
        return f"{self.draft_id} {self.uid} {self.status}"
