"""為現有所有 tenant 補種預設發票類型 + 付款方式。

用途:Phase 2 平台後台建的經銷商最初忘了 seed,跑這個一次補齊。
get_or_create 保證對已有資料的 tenant 是 no-op。

用法:
    .venv/bin/python manage.py seed_existing_tenants
"""
from django.core.management.base import BaseCommand

from apps.tenants.models import Tenant
from apps.tenants.services import seed_tenant_defaults


class Command(BaseCommand):
    help = "為所有現有 tenant 補種預設發票類型 + 付款方式"

    def handle(self, *args, **opts):
        tenants = list(Tenant.objects.all().order_by("id"))
        for t in tenants:
            seed_tenant_defaults(t)
            self.stdout.write(
                self.style.SUCCESS(f"  ✓ {t.code} {t.name}")
            )
        self.stdout.write(
            self.style.SUCCESS(f"\n完成,處理 {len(tenants)} 個 tenant")
        )
