from django.conf import settings
from django.db import models

from apps.core.models import TenantOwnedModel


class CommandLog(TenantOwnedModel):
    """一次 AI 指令的完整生命週期紀錄。

    設計原則:POS 是帳本與規則引擎,AI 是操作介面。
    這張表存的是「提案」——原始輸入、解析出的結構化動作、以及待人確認的
    payload。**在使用者按下確認前,不會對帳本(進貨單/庫存/序號)寫任何東西**。
    確認後才呼叫既有 service(commit_purchase_order 等)真正過帳,
    並把結果單據回填 result_doc_type / result_doc_id,全程保留 audit。
    """

    class Source(models.TextChoices):
        NL_TEXT = "nl_text", "自然語言"
        PURCHASE_DOC = "purchase_doc", "進貨單(文字/OCR)"
        VOICE = "voice", "語音轉文字"

    class Status(models.TextChoices):
        PARSED = "parsed", "已解析"
        NEEDS_CLARIFICATION = "needs_clarification", "待釐清"
        AWAITING_CONFIRM = "awaiting_confirm", "待確認"
        COMMITTED = "committed", "已過帳"
        REJECTED = "rejected", "已取消"
        FAILED = "failed", "失敗"

    source = models.CharField(
        "來源", max_length=20, choices=Source.choices, default=Source.NL_TEXT
    )
    raw_input = models.TextField("原始輸入", help_text="使用者餵進來的自然語言或進貨單內容")

    intent_action = models.CharField(
        "動作", max_length=40, blank=True, help_text="解析出的固定動作代碼,如 create_purchase_order"
    )
    parsed_intent = models.JSONField(
        "解析結果", default=dict, blank=True, help_text="parser 產出的結構化 Intent(未解析成真實主檔前)"
    )
    proposal = models.JSONField(
        "提案", default=dict, blank=True,
        help_text="解析成真實主檔後、可直接執行的 payload + 給人看的顯示內容",
    )
    clarification = models.JSONField(
        "待釐清項目", default=list, blank=True,
        help_text="解析不確定時的追問清單(找不到/對到多筆商品或供應商)",
    )

    status = models.CharField(
        "狀態", max_length=24, choices=Status.choices, default=Status.PARSED
    )
    message = models.CharField("訊息", max_length=400, blank=True, help_text="錯誤或提示訊息")

    result_doc_type = models.CharField(
        "結果單據類型", max_length=40, blank=True, help_text="purchase_order / sales_order ..."
    )
    result_doc_id = models.BigIntegerField("結果單據 ID", null=True, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
        null=True,
        blank=True,
        verbose_name="操作者",
    )
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
        null=True,
        blank=True,
        verbose_name="確認者",
    )

    class Meta:
        ordering = ["-id"]
        indexes = [
            models.Index(fields=["tenant", "status"]),
            models.Index(fields=["result_doc_type", "result_doc_id"]),
        ]
        verbose_name = "AI 指令紀錄"
        verbose_name_plural = "AI 指令紀錄"

    def __str__(self) -> str:
        return f"[{self.get_status_display()}] {self.intent_action or self.source}"
