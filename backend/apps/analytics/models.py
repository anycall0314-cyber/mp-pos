from django.conf import settings
from django.db import models

from apps.core.models import TenantOwnedModel


class SavedReport(TenantOwnedModel):
    """存起來的查詢單(「我的報表」)。shared = 全公司都看得到(管理員才能設)。

    owner 可以是空的:還原備份時對不回來的帳號會留空(跟單據的經手帳號同一套規則),
    那種報表只有管理員看得到、可以刪。
    """

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+", verbose_name="建立者",
    )
    name = models.CharField("名稱", max_length=60)
    spec = models.JSONField("查詢單")
    shared = models.BooleanField("全公司共用", default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "owner", "name"], name="uniq_saved_report_name"),
        ]
        ordering = ["name", "id"]
        verbose_name = "存起來的報表"
        verbose_name_plural = "存起來的報表"
