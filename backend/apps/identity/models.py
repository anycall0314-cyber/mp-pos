"""商品識別:跨廠商品名別名庫 + 進貨待確認區。

對齊 docs/product-roadmap.md 第 1 階段:
- ProductAlias:把「廠商 A / 廠商 B / 我舊 POS」的品名、料號、條碼,對到我的一個標準商品。
- IntakeBatch / IntakeItem:一張進貨(貼字 / 指令 / 拍照 / 匯入)先落在待確認區,
  認得的自動對應、認不出的擱著等人確認,**在人確認前絕不寫正式庫存**。

鐵律:名稱不同不代表不同商品;認不出不代表新品;寧可暫存也不錯誤異動。
"""
from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.models import TenantOwnedModel

from .normalize import normalize


class ProductAlias(TenantOwnedModel):
    """一條別名:某個外部講法 → 我的一個標準商品(catalog.Product)。"""

    class Kind(models.TextChoices):
        BARCODE = "barcode", "條碼(GTIN/EAN/UPC)"
        VENDOR_SKU = "vendor_sku", "廠商料號"
        VENDOR_NAME = "vendor_name", "廠商品名"
        OEM_MODEL = "oem_model", "原廠型號"
        LEGACY_NAME = "legacy_name", "舊品名 / 簡稱"

    class Source(models.TextChoices):
        MANUAL = "manual", "人工建立"
        LEARNED = "learned", "待確認區學來的"
        IMPORTED = "imported", "匯入"

    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.CASCADE,
        related_name="aliases",
        verbose_name="對應商品",
    )
    supplier = models.ForeignKey(
        "parties.Supplier",
        on_delete=models.CASCADE,
        related_name="product_aliases",
        null=True,
        blank=True,
        verbose_name="廠商",
        help_text="留空 = 通用別名(我的舊品名 / 中文簡稱,不分廠商)",
    )
    kind = models.CharField("類型", max_length=16, choices=Kind.choices)
    value = models.CharField("原始字", max_length=200)
    normalized_value = models.CharField(
        "比對鍵", max_length=200, db_index=True, blank=True,
        help_text="value 正規化後的字,系統自動算,別名比對用",
    )
    verified = models.BooleanField(
        "已確認", default=True,
        help_text="人工確認過的別名(從待確認區學來的都算);自動猜的可設 False",
    )
    source = models.CharField(
        "來源", max_length=12, choices=Source.choices, default=Source.MANUAL
    )
    note = models.CharField("備註", max_length=200, blank=True)
    is_active = models.BooleanField("啟用", default=True)

    class Meta:
        constraints = [
            # 同一租戶,同一條碼(GTIN)只能指向一個商品——不分廠商。
            models.UniqueConstraint(
                fields=["tenant", "normalized_value"],
                condition=Q(kind="barcode", is_active=True),
                name="uniq_alias_barcode",
            ),
            # 同一廠商、同一料號 / 品名,不重複。
            models.UniqueConstraint(
                fields=["tenant", "supplier", "kind", "normalized_value"],
                condition=Q(is_active=True),
                name="uniq_alias_vendor_ref",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "kind", "normalized_value"]),
            models.Index(fields=["tenant", "product"]),
        ]
        ordering = ["product", "kind", "value"]
        verbose_name = "商品別名"
        verbose_name_plural = "商品別名"

    def save(self, *args, **kwargs):
        self.normalized_value = normalize(self.value)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        who = self.supplier.name if self.supplier_id else "通用"
        return f"[{who}] {self.value} → {self.product_id}"


class IntakeBatch(TenantOwnedModel):
    """一次進貨的待確認批次(一張出貨單 / 一次貼字 / 一次拍照)。"""

    class Source(models.TextChoices):
        MANUAL_TEXT = "manual_text", "手動貼單文字"
        ASSISTANT = "assistant", "指令助理"
        OCR = "ocr", "拍照 / PDF 辨識"
        IMPORT = "import", "檔案匯入"

    class Status(models.TextChoices):
        OPEN = "open", "待確認"
        RESOLVED = "resolved", "已對應完(可過帳)"
        COMMITTED = "committed", "已過帳"
        CANCELLED = "cancelled", "已取消"

    source = models.CharField(
        "來源", max_length=16, choices=Source.choices, default=Source.MANUAL_TEXT
    )
    supplier = models.ForeignKey(
        "parties.Supplier", on_delete=models.PROTECT,
        related_name="intake_batches", null=True, blank=True, verbose_name="廠商",
    )
    warehouse = models.ForeignKey(
        "inventory.Warehouse", on_delete=models.PROTECT,
        related_name="intake_batches", null=True, blank=True, verbose_name="入庫倉",
    )
    vendor_doc_no = models.CharField(
        "廠商出貨單號", max_length=60, blank=True,
        help_text="同廠商同單號不重複匯入(防重複入庫)",
    )
    raw_text = models.TextField("原始內容", blank=True, help_text="貼上的文字 / OCR 全文")
    status = models.CharField(
        "狀態", max_length=12, choices=Status.choices, default=Status.OPEN
    )
    note = models.CharField("備註", max_length=200, blank=True)
    committed_purchase_order_id = models.BigIntegerField(
        "過帳後進貨單 ID", null=True, blank=True
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="+", null=True, blank=True, verbose_name="操作者",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "supplier", "vendor_doc_no"],
                condition=~Q(vendor_doc_no="") & ~Q(status="cancelled"),
                name="uniq_intake_vendor_doc",
            ),
        ]
        indexes = [models.Index(fields=["tenant", "status"])]
        ordering = ["-id"]
        verbose_name = "進貨待確認批次"
        verbose_name_plural = "進貨待確認批次"

    def __str__(self) -> str:
        return f"[{self.get_status_display()}] {self.get_source_display()} #{self.pk}"


class IntakeItem(TenantOwnedModel):
    """待確認區的一行:原始文字 + 拆出的量價序號 + 識別結果 + 候選。"""

    class MatchStatus(models.TextChoices):
        AUTO_MATCHED = "auto_matched", "自動對應"
        NEEDS_REVIEW = "needs_review", "待選候選"
        UNKNOWN = "unknown", "未知商品"
        CONFLICT = "conflict", "屬性衝突"
        RESOLVED = "resolved", "已人工對應"
        NEW_PRODUCT = "new_product", "已建新品對應"
        REJECTED = "rejected", "已駁回"

    batch = models.ForeignKey(
        IntakeBatch, on_delete=models.CASCADE, related_name="items", verbose_name="批次"
    )
    line_no = models.PositiveIntegerField("行號")
    raw_text = models.CharField("原始文字", max_length=300)
    raw_barcode = models.CharField("原始條碼", max_length=80, blank=True)
    raw_vendor_sku = models.CharField("原始廠商料號", max_length=80, blank=True)
    raw_qty = models.PositiveIntegerField("數量", default=1)
    raw_unit_price = models.DecimalField(
        "進價", max_digits=14, decimal_places=2, default=0
    )
    raw_serials = models.JSONField("序號清單", default=list, blank=True)

    matched_product = models.ForeignKey(
        "catalog.Product", on_delete=models.PROTECT,
        related_name="intake_items", null=True, blank=True, verbose_name="對應商品",
    )
    match_status = models.CharField(
        "識別狀態", max_length=16, choices=MatchStatus.choices,
        default=MatchStatus.UNKNOWN,
    )
    match_confidence = models.PositiveIntegerField(
        "信心分數", default=0, help_text="0-100 整數;規則算出,非 AI 自評"
    )
    candidates = models.JSONField(
        "候選清單", default=list, blank=True,
        help_text="[{product_id, sku, name, score, reason}] 給人選",
    )
    ocr_confidence = models.JSONField(
        "OCR 辨識信心", default=dict, blank=True,
        help_text="拍照來源:每欄的辨識信心(0-1);與 match_confidence 是兩回事",
    )
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="+", null=True, blank=True, verbose_name="處理者",
    )
    note = models.CharField("備註", max_length=200, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["batch", "line_no"], name="uniq_intake_item_line"
            ),
        ]
        indexes = [models.Index(fields=["tenant", "match_status"])]
        ordering = ["batch", "line_no"]
        verbose_name = "進貨待確認明細"
        verbose_name_plural = "進貨待確認明細"

    def __str__(self) -> str:
        return f"{self.batch_id}#{self.line_no} {self.raw_text[:20]}"


class IntakeDocument(TenantOwnedModel):
    """進貨單原圖(拍照 / PDF)。原圖與 OCR 結果分開留底,供稽核與重新辨識。"""

    class OcrStatus(models.TextChoices):
        PENDING = "pending", "待辨識"
        DONE = "done", "已辨識"
        FAILED = "failed", "辨識失敗"

    batch = models.ForeignKey(
        IntakeBatch, on_delete=models.CASCADE, related_name="documents",
        null=True, blank=True, verbose_name="待確認批次",
    )
    image = models.FileField("原圖 / 檔案", upload_to="intake_docs/%Y/%m/")
    original_filename = models.CharField("原始檔名", max_length=200, blank=True)
    ocr_status = models.CharField(
        "辨識狀態", max_length=12, choices=OcrStatus.choices, default=OcrStatus.PENDING
    )
    ocr_raw = models.JSONField("辨識原始結果", default=dict, blank=True)
    ocr_message = models.CharField("辨識訊息", max_length=300, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="+", null=True, blank=True, verbose_name="上傳者",
    )

    class Meta:
        indexes = [models.Index(fields=["tenant", "ocr_status"])]
        ordering = ["-id"]
        verbose_name = "進貨單原圖"
        verbose_name_plural = "進貨單原圖"

    def __str__(self) -> str:
        return f"[{self.get_ocr_status_display()}] {self.original_filename or self.image.name}"
