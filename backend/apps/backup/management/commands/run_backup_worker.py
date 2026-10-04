"""備份 / 還原的背景 worker。

    python manage.py run_backup_worker            # 常駐,每隔幾秒看一次有沒有工作
    python manage.py run_backup_worker --once     # 做完目前排隊的就結束(排程或手動用)

工作狀態都在資料庫,這支可以隨時停掉重啟:做到一半的工作租約到期後會被重新接手。

順便每分鐘看一次要不要做「每日庫存快照 + 對帳」(apps/ledger/daily.py,過了收店時間才做)。
"""
import time

from django.core.management.base import BaseCommand

from apps.backup import jobs


class Command(BaseCommand):
    help = "執行排隊中的公司備份與還原工作"

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="做完目前排隊的就結束")
        parser.add_argument("--interval", type=float, default=5.0, help="沒工作時隔幾秒再看")

    def handle(self, *args, **opts):
        from apps.backup import restore
        from apps.ledger import daily

        next_daily = 0.0
        while True:
            if time.monotonic() >= next_daily:
                next_daily = time.monotonic() + 60
                try:
                    daily.run_due(log=self.stdout.write)
                except Exception as exc:  # 每日對帳出錯不能讓備份 / 還原停擺
                    self.stdout.write(f"每日對帳失敗 {type(exc).__name__}: {exc}")
            worked = False
            job = jobs.claim_next()
            if job is not None:
                worked = True
                job = jobs.run_backup(job)
                self.stdout.write(f"備份 #{job.pk}:{job.get_status_display()} {job.error[:80]}")
            rjob = restore.claim_next()
            if rjob is not None:
                worked = True
                rjob = restore.run_restore(rjob)
                self.stdout.write(f"還原 #{rjob.pk}:{rjob.get_status_display()} {rjob.error[:80]}")
            jobs.expire_old()
            if worked:
                continue
            if opts["once"]:
                return
            time.sleep(opts["interval"])
