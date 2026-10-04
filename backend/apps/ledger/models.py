"""帳本健檢:每日庫存快照 + 每日自動對帳(資料底層規劃 2.5)。

庫存金額、庫齡、週轉天數都需要「過去某一天的庫存」,事後無法從異動準確倒推成本,
所以每天收店後記一份。對帳結果存表,管理員在「設定 → 每日對帳」看。
"""
from django.db import models

from apps.core.models import TenantOwnedModel


class StockSnapshot(TenantOwnedModel):
    """某天收店時、某門市、某商品、某種狀態的庫存。只記有數量的。"""

    class State(models.TextChoices):
        IN_STOCK = "in_stock", "在庫"
        RETURNED = "returned", "退回待處理"
        RMA = "rma", "維修中"
        IN_TRANSIT = "in_transit", "調撥中"

    business_date = models.DateField("營業日")
    warehouse = models.ForeignKey(
        "inventory.Warehouse", on_delete=models.PROTECT, related_name="+",
        null=True, blank=True, verbose_name="門市",
        help_text="調撥中記在目的門市;找不到調撥單的留空",
    )
    product = models.ForeignKey(
        "catalog.Product", on_delete=models.PROTECT, related_name="+", verbose_name="商品"
    )
    state = models.CharField("狀態", max_length=20, choices=State.choices)
    qty = models.PositiveIntegerField("數量")
    cost_value = models.DecimalField(
        "成本金額(未稅)", max_digits=16, decimal_places=2,
        help_text="序號 = 各台進貨成本加總;配件 = 數量 × 該門市加權平均;調撥中配件 = 派發時成本",
    )
    taken_at = models.DateTimeField("記錄時間")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "business_date", "warehouse", "product", "state"],
                nulls_distinct=False, name="uniq_stock_snapshot_day",
            ),
        ]
        indexes = [models.Index(fields=["tenant", "business_date"], name="stock_snapshot_day")]
        ordering = ["-business_date", "warehouse_id", "product_id"]
        verbose_name = "每日庫存快照"
        verbose_name_plural = "每日庫存快照"


class StockSnapshotDay(TenantOwnedModel):
    """某天拍過了(沒有庫存的公司也會有這一列,才分得出「拍到零」和「沒拍」)。"""

    business_date = models.DateField("營業日")
    taken_at = models.DateTimeField("記錄時間")
    row_count = models.PositiveIntegerField("列數")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "business_date"], name="uniq_stock_snapshot_day_marker"
            ),
        ]
        ordering = ["-business_date"]
        verbose_name = "每日庫存快照紀錄"
        verbose_name_plural = "每日庫存快照紀錄"


class LedgerCheckRun(TenantOwnedModel):
    """一次對帳。results 是每一項檢查的結果清單(見 checks.py)。"""

    business_date = models.DateField("營業日")
    started_at = models.DateTimeField("開始")
    finished_at = models.DateTimeField("結束", null=True, blank=True)
    ok = models.BooleanField("全部一致", default=False)
    problem_count = models.PositiveIntegerField("不一致項目數", default=0)
    results = models.JSONField("結果", default=list)

    class Meta:
        indexes = [models.Index(fields=["tenant", "business_date"], name="ledger_check_day")]
        ordering = ["-id"]
        verbose_name = "每日對帳"
        verbose_name_plural = "每日對帳"
