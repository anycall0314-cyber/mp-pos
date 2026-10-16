"""型號庫自動更新(讀手機王、加新機、展開到有勾「新機自動建品號」的公司)。規則在 `apps/catalog/device_watch.py`。

    python manage.py watch_device_catalog              # 今天還沒做就做(測試站的排程每天跑這個)
    python manage.py watch_device_catalog --again      # 今天做過也再做一次
    python manage.py watch_device_catalog --dry-run    # 只讀、只算,什麼都不寫
"""
from django.core.management.base import BaseCommand

from apps.catalog import device_watch


class Command(BaseCommand):
    help = "型號庫自動更新:讀手機王的清單,新機加進型號庫並展開到有勾的公司"

    def add_arguments(self, parser):
        parser.add_argument("--again", action="store_true", help="今天做過也再做一次")
        parser.add_argument("--dry-run", action="store_true", help="只算,什麼都不寫")

    def handle(self, *args, **opts):
        if opts["dry_run"]:
            report = device_watch.check(write=False, log=self.stdout.write)
            self.stdout.write(f"{'成功' if report.ok else '沒有成功'} {report.counts}")
            for n in report.notes:
                self.stdout.write(f"  {n}")
            return
        run = device_watch.run_today(again=opts["again"], log=self.stdout.write)
        if run is None:
            self.stdout.write("今天已經做過了(或另一個程序正在做);要再做一次加 --again")
            return
        self.stdout.write(f"{'成功' if run.ok else '沒有成功'} {run.counts}")
        for n in run.notes:
            self.stdout.write(f"  {n}")
