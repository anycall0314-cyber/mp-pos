"""排程指令:重算所有 tenant 的動態安全庫存與銷售趨勢。

建議每晚 02:00 跑一次,在 Mac mini 上 cron 設定範例:
    0 2 * * * cd /path/to/backend && /path/to/.venv/bin/python manage.py compute_dynamic_stock

也可以加 `--tenant CODE` 只跑單一 tenant(debug 用)。
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.catalog.services_dynamic_stock import recompute_for_tenant
from apps.tenants.models import Tenant


class Command(BaseCommand):
    help = "重算動態安全庫存(EWMA + 14/90 雙窗趨勢 + attach_rate)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--tenant",
            type=str,
            default=None,
            help="只跑指定 tenant code,空白 = 所有 active tenant",
        )

    def handle(self, *args, **options):
        tenant_code = options.get("tenant")
        started = timezone.now()

        if tenant_code:
            tenants = Tenant.objects.filter(code=tenant_code, is_active=True)
            if not tenants.exists():
                self.stderr.write(
                    self.style.ERROR(f"找不到 active tenant: {tenant_code}")
                )
                return
        else:
            tenants = Tenant.objects.filter(is_active=True)

        total = {"hosts": 0, "accessories": 0, "tenants": 0}
        for tenant in tenants:
            self.stdout.write(f"[{tenant.code}] 重算中…")
            result = recompute_for_tenant(tenant)
            total["hosts"] += result["hosts"]
            total["accessories"] += result["accessories"]
            total["tenants"] += 1
            self.stdout.write(
                f"  → 主機 {result['hosts']} 筆 / 配件 {result['accessories']} 筆"
            )

        elapsed = (timezone.now() - started).total_seconds()
        self.stdout.write(
            self.style.SUCCESS(
                f"完成:{total['tenants']} 個 tenant、"
                f"主機 {total['hosts']} 筆、配件 {total['accessories']} 筆,"
                f"耗時 {elapsed:.1f}s"
            )
        )
