from django.db import models

from apps.core.models import TenantOwnedModel


class SubjectKind(models.TextChoices):
    """需求標的類型:同一組表同時服務商品與維修。"""
    PRODUCT_SALES = "product_sales", "商品銷售需求"
    REPAIR_PART = "repair_part", "維修料件需求"


class SubjectAlias(TenantOwnedModel):
    """別名庫:把「17 Pro / i17P / iPhone 17 Pro」對到同一個 subject_key。

    kind=product_sales 時 subject_key 是機型 key(例 apple-iphone-15-pro);
    kind=repair_part 時是「機型+症狀」(例 apple-iphone-12__battery)。
    product 選填:商品需求可直接連到 Product,方便回寫 dynamic 修正。
    """

    alias = models.CharField("別名 / 關鍵字", max_length=120)
    subject_key = models.CharField("標的 key", max_length=120)
    kind = models.CharField(
        "標的類型", max_length=20, choices=SubjectKind.choices,
        default=SubjectKind.PRODUCT_SALES,
    )
    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.CASCADE,
        related_name="signal_aliases",
        null=True,
        blank=True,
        verbose_name="對應商品",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "kind", "alias"], name="uniq_subject_alias"
            ),
        ]
        indexes = [models.Index(fields=["tenant", "subject_key"])]
        ordering = ["subject_key", "alias"]
        verbose_name = "標的別名"
        verbose_name_plural = "標的別名"

    def __str__(self) -> str:
        return f"{self.alias} → {self.subject_key}"


class MarketSignal(TenantOwnedModel):
    """一個訊號時間點(外部熱度或內部領先訊號)。每週 / 每日一筆。"""

    class Source(models.TextChoices):
        GOOGLE_TRENDS = "google_trends", "Google 搜尋趨勢"
        GOOGLE_ADS = "google_ads", "Google 關鍵字量"
        YOUTUBE = "youtube", "YouTube 討論"
        SUPPLIER_SHORTAGE = "supplier_shortage", "供應商缺貨"
        PROMO = "promo", "促銷活動"
        REPAIR_SEARCH = "repair_search", "維修搜尋"
        INTERNAL_INQUIRY = "internal_inquiry", "自家詢問"
        PREORDER = "preorder", "預購 / 訂金"

    # 外部訊號(只准示警,不准直接授權叫貨)
    EXTERNAL_SOURCES = {
        Source.GOOGLE_TRENDS, Source.GOOGLE_ADS, Source.YOUTUBE,
        Source.SUPPLIER_SHORTAGE, Source.PROMO, Source.REPAIR_SEARCH,
    }

    source = models.CharField("來源", max_length=20, choices=Source.choices)
    subject_key = models.CharField("標的 key", max_length=120)
    period_date = models.DateField("期間(日 / 週起日)")
    value = models.DecimalField("數值", max_digits=14, decimal_places=3, default=0)
    meta = models.JSONField("附帶資料", default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "source", "subject_key", "period_date"],
                name="uniq_market_signal_point",
            ),
        ]
        indexes = [models.Index(fields=["tenant", "subject_key", "period_date"])]
        ordering = ["-period_date"]
        verbose_name = "市場訊號"
        verbose_name_plural = "市場訊號"

    def __str__(self) -> str:
        return f"{self.source} {self.subject_key} {self.period_date}:{self.value}"


class DemandAlert(TenantOwnedModel):
    """需求上升 / 下降 / 備料預警。只示警,不自動叫貨。

    authorized:外部熱度是否被內部領先訊號驗證授權(授權閘)。
    上升警示未授權 = 熱度升但自家詢問 / 銷售沒跟上 → 只觀望,不建議加量。
    """

    class Direction(models.TextChoices):
        UP = "up", "需求上升"
        DOWN = "down", "需求下降"
        WATCH = "watch", "觀望(熱度升、內部未跟上)"

    class Status(models.TextChoices):
        OPEN = "open", "待處理"
        ACK = "ack", "已讀"
        DISMISSED = "dismissed", "已忽略"

    kind = models.CharField(
        "標的類型", max_length=20, choices=SubjectKind.choices,
        default=SubjectKind.PRODUCT_SALES,
    )
    subject_key = models.CharField("標的 key", max_length=120)
    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.CASCADE,
        related_name="demand_alerts",
        null=True,
        blank=True,
        verbose_name="商品",
    )
    direction = models.CharField("方向", max_length=10, choices=Direction.choices)
    heat_growth = models.DecimalField(
        "外部熱度成長", max_digits=8, decimal_places=4, default=0,
        help_text="近 7 天 vs 前 7 天;0.28 = +28%",
    )
    internal_growth = models.DecimalField(
        "內部領先成長", max_digits=8, decimal_places=4, default=0,
        help_text="商品用 trend_ratio-1;維修用工單成長",
    )
    authorized = models.BooleanField(
        "已授權", default=False, help_text="外部熱度是否被內部訊號驗證(可否建議加量)"
    )
    score = models.DecimalField("綜合分數", max_digits=8, decimal_places=4, default=0)
    window_end = models.DateField("計算基準日")
    note = models.CharField("說明", max_length=300, blank=True)
    status = models.CharField(
        "狀態", max_length=12, choices=Status.choices, default=Status.OPEN
    )

    class Meta:
        indexes = [
            models.Index(fields=["tenant", "status", "direction"]),
            models.Index(fields=["tenant", "kind", "subject_key"]),
        ]
        ordering = ["-window_end", "-id"]
        verbose_name = "需求警示"
        verbose_name_plural = "需求警示"

    def __str__(self) -> str:
        return f"[{self.get_direction_display()}] {self.subject_key} @ {self.window_end}"
