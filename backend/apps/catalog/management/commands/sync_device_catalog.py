"""平台型號庫(M1)匯入 / 收回。規則在 `apps/catalog/device_catalog.py`。

    python manage.py sync_device_catalog                    # 試算:會新增 / 修改 / 不動幾支(不寫)
    python manage.py sync_device_catalog --confirm          # 寫進型號庫(重跑同一份 = 什麼都不動)
    python manage.py sync_device_catalog --undo 3 --confirm # 收回第 3 次匯入

資料檔預設 `apps/catalog/data/device_catalog.json`(`--file` 換別的)。型號庫是平台一份,不屬於任何公司。
"""
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.catalog import device_catalog
from apps.catalog.models import DeviceCatalogRun

DEFAULT = Path(__file__).resolve().parents[2] / "data" / "device_catalog.json"


class Command(BaseCommand):
    help = "平台型號庫:匯入(可重跑)/ 收回一次匯入"

    def add_arguments(self, parser):
        parser.add_argument("--file", default=str(DEFAULT))
        parser.add_argument("--confirm", action="store_true", help="真的寫進去(沒有這個只試算)")
        parser.add_argument("--undo", type=int, help="收回這一次匯入(編號)")

    def handle(self, *args, **opts):
        try:
            if opts["undo"]:
                run = DeviceCatalogRun.objects.filter(pk=opts["undo"]).first()
                if run is None:
                    raise CommandError(f"沒有這一次匯入:{opts['undo']}")
                if not opts["confirm"]:
                    self.stdout.write(f"試算:會收回第 {run.pk} 次({run.source}){run.counts};加 --confirm 才做")
                    return
                got = device_catalog.undo(run.pk)
                self.stdout.write(f"收回第 {run.pk} 次:刪掉 {got['deleted']} 支、倒回 {got['restored']} 支")
                return
            path = Path(opts["file"])
            payload = json.loads(path.read_text(encoding="utf-8"))
            p = device_catalog.plan(payload)
            self.stdout.write(f"{path.name}(版本 {payload.get('version', '?')}):新增 {len(p['created'])}、修改 {len(p['updated'])}、不動 {p['unchanged']}")
            if not opts["confirm"]:
                self.stdout.write("試算,沒有寫入;加 --confirm 才寫")
                return
            run = device_catalog.sync(payload, source=f"{path.name}@{payload.get('version', '?')}")
            self.stdout.write("沒有要改的" if run is None else f"寫好了:第 {run.pk} 次匯入 {run.counts}")
        except device_catalog.CatalogError as exc:
            raise CommandError(str(exc)) from None
