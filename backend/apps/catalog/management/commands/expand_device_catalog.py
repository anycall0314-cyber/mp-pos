"""把平台型號庫展開成一家公司的品號(M1-C)。規則在 `apps/catalog/device_expand.py`。

    python manage.py expand_device_catalog --tenant JB --links 對照.json             # 試算(不寫)
    python manage.py expand_device_catalog --tenant JB --links 對照.json --confirm   # 寫進去(一支一個交易,可以重跑)

`--links`:`{"links": {公司機型名稱: 型號庫編號}, "holds": [先不展開的型號庫編號]}`(對照怎麼來的見 docs/development/M1_標準機型清單/)。
`--no-new-for-old`:草稿補進來的舊機(2018 以前)只建中古機、不建全新。
"""
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.catalog import device_expand
from apps.tenants.models import Tenant


class Command(BaseCommand):
    help = "平台型號庫 → 一家公司的品號(全新、中古機;2026 年以後上市的手機加已拆封;耳機、手環只建全新、按數量)"

    def add_arguments(self, parser):
        parser.add_argument("--tenant", required=True, help="公司代碼(例:JB)")
        parser.add_argument("--links", help="公司機型 ↔ 型號庫的對照與先不展開的(JSON)")
        parser.add_argument("--categories", default=",".join(device_expand.ALL_CATEGORIES))
        parser.add_argument("--no-new-for-old", action="store_true")
        parser.add_argument("--confirm", action="store_true", help="真的寫進去(沒有這個只試算)")

    def handle(self, *args, **opts):
        tenant = Tenant.objects.filter(code=opts["tenant"]).first()
        if tenant is None:
            raise CommandError(f"沒有這家公司:{opts['tenant']}")
        spec = json.loads(Path(opts["links"]).read_text(encoding="utf-8")) if opts["links"] else {}
        links, holds = spec.get("links") or {}, spec.get("holds") or []
        confirm = opts["confirm"]
        problems = device_expand.apply_links(tenant, links, confirm=confirm)
        if problems:
            raise CommandError("對照有問題,整批不做:\n" + "\n".join(problems[:20]))
        try:
            report = device_expand.expand(tenant, categories=tuple(opts["categories"].split(",")), links=links, holds=holds,
                                          new_for_old=not opts["no_new_for_old"], confirm=confirm)
        except device_expand.ExpandError as exc:
            raise CommandError(str(exc)) from None
        total = sum(report.created.values())
        self.stdout.write(
            f"{tenant.code}:{'寫好了' if confirm else '試算(沒有寫入)'} —— 型號 {report.devices} 支(先不展開 {report.held};"
            f"新機型 {report.new_models}、名稱一樣直接對上 {report.linked};對照寫上 {len(links)}),"
            f"品號 {total} 個 {report.created}")
        if report.shared:
            self.stdout.write(f"型號庫設了配件共用:{report.shared} 個配件加上了新機")
        if report.extra_variants:
            self.stdout.write(f"已有品號的機型、型號庫多的容量 / 顏色(沒建)共 {len(report.extra_variants)} 個機型,例:")
            for name, extra in report.extra_variants[:10]:
                self.stdout.write(f"  {name}:{'、'.join(extra[:8])}")
        if report.problems:
            self.stdout.write(f"沒做的 {len(report.problems)} 支:")
            for p in report.problems[:30]:
                self.stdout.write(f"  {p}")
