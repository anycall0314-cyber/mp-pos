"""每日庫存快照 + 對帳(平常由備份背景程式在收店後自動做)。

    python manage.py run_daily_ledger                 # 過了收店時間才做,今天做過的不重做
    python manage.py run_daily_ledger --now           # 不管時間,今天還沒做的公司現在做
    python manage.py run_daily_ledger --tenant JB     # 只做這家(一樣要過了收店時間,或加 --now)
    python manage.py run_daily_ledger --tenant JB --again   # 這家公司現在重拍、重對一次
"""
from django.core.management.base import BaseCommand, CommandError

from apps.ledger import daily
from apps.ledger.checks import run_checks
from apps.ledger.snapshot import CompanyBusy, take_snapshot


class Command(BaseCommand):
    help = "每日庫存快照 + 對帳"

    def add_arguments(self, parser):
        parser.add_argument("--now", action="store_true", help="不管時間,現在做")
        parser.add_argument("--tenant", help="只做這家公司(代碼)")
        parser.add_argument("--again", action="store_true", help="今天做過也重拍、重對(要配 --tenant)")

    def handle(self, *args, **opts):
        from apps.tenants.models import Tenant

        if opts["again"] and not opts["tenant"]:
            raise CommandError("--again 要指定 --tenant")
        if not opts["tenant"]:
            self._due(daily.run_due(force=opts["now"], log=self.stdout.write))
            return
        tenant = Tenant.objects.filter(code=opts["tenant"]).first()
        if tenant is None:
            raise CommandError(f"找不到公司代碼「{opts['tenant']}」")
        if not opts["again"]:
            self._due(daily.run_due(force=opts["now"], log=self.stdout.write, tenants=[tenant]))
            return
        try:
            self.stdout.write(f"庫存快照 {take_snapshot(tenant)} 列")
            run = run_checks(tenant)
        except CompanyBusy as exc:
            raise CommandError(str(exc))
        for r in run.results:
            mark = "一致" if r["ok"] and r["level"] == "error" else ("提醒" if r["level"] == "info" else "不一致")
            self.stdout.write(f"[{mark}] {r['label']}" + (f":{r['count']}" if r["count"] else "")
                              + (f"  {r['detail']}" if r["detail"] else ""))
            for s in r["samples"]:
                self.stdout.write(f"    {s}")

    def _due(self, failed):
        if failed is None:
            self.stdout.write(f"還沒到收店時間({daily.daily_time():%H:%M});要現在做請加 --now")
        elif failed:
            raise CommandError("沒做成的公司:" + "、".join(failed))
