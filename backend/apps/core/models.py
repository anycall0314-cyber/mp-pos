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
