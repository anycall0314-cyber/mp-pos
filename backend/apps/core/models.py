from django.conf import settings
from django.db import models


class TenantQuerySet(models.QuerySet):
    def for_tenant(self, tenant):
        return self.filter(tenant=tenant)


class TenantManager(models.Manager.from_queryset(TenantQuerySet)):
    pass


class TimestampedModel(models.Model):
    created_at = models.DateTimeField("建立時間", auto_now_add=True)
    updated_at = models.DateTimeField("更新時間", auto_now=True)

    class Meta:
        abstract = True


class TenantOwnedModel(TimestampedModel):
    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.PROTECT,
        related_name="+",
        db_index=True,
        verbose_name="租戶",
    )

    objects = TenantManager()

    class Meta:
        abstract = True
        indexes = [models.Index(fields=["tenant"])]


class IdempotencyKey(TenantOwnedModel):
    """建單請求的「同一份只成立一次」紀錄(用法見 apps/core/idempotency.py)。

    畫面送出一張單時自己帶一把鑰匙(`Idempotency-Key`)。連線中斷、不知道有沒有送成功時,畫面拿同一把鑰匙再送一次:
    已經成立的話伺服器回那一張,不會開第二張。記的是單號不是資料庫編號:還原備份之後編號會換,單號不會。
    只留幾天(之後不會有人拿同一把鑰匙重送),不進公司備份。
    """

    scope = models.CharField("單據種類", max_length=40)
    key = models.CharField("鑰匙", max_length=64)
    doc_no = models.CharField("成立的單號", max_length=40, blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        verbose_name="送出的人",
    )

    class Meta:
        verbose_name = "建單鑰匙"
        verbose_name_plural = "建單鑰匙"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "scope", "key"], name="uniq_idempotency_key"
            ),
        ]
        indexes = [models.Index(fields=["created_at"])]

    def __str__(self) -> str:
        return f"{self.scope}:{self.key} → {self.doc_no or '(處理中)'}"

