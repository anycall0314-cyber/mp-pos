"""一家公司現有商品的一次整理(M1-E 第二段)。規則在 `apps/catalog/shop_tidy.py`。

    python manage.py tidy_shop_catalog --tenant JB --answers 答案.json                 # 試算(不寫)
    python manage.py tidy_shop_catalog --tenant JB --answers 答案.json --confirm       # 寫進去(可以重跑)
    python manage.py tidy_shop_catalog --tenant TEST --answers 答案.json --kinds-from JB --report 結果.csv

`--answers`:`{"makers": [算廠牌的片段], "wear": {舊品名: "earbuds" | "watch" | "other"}}`(Jev 判的、有把握的;沒把握的不放,列給 owner)。
`--kinds-from`:類別的種類(主機 / 配件 / 一般)照另一家同名的類別。
"""
import csv
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.catalog import shop_tidy
from apps.tenants.models import Tenant


class Command(BaseCommand):
    help = "整理一家公司現有的商品:充電/線材改名傳輸線、耳機手環手錶搬到穿戴、從品名補配件廠牌與適用機型"

    def add_arguments(self, parser):
        parser.add_argument("--tenant", required=True, help="公司代碼(例:JB)")
        parser.add_argument("--answers", required=True, help="Jev 判好的廠牌片段與要搬到穿戴的舊品名(JSON)")
        parser.add_argument("--kinds-from", help="類別的種類照這一家同名的類別(公司代碼)")
        parser.add_argument("--report", help="每一個改到的商品寫進這個 CSV")
        parser.add_argument("--confirm", action="store_true", help="真的寫進去(沒有這個只試算)")

    def handle(self, *args, **opts):
        tenant = Tenant.objects.filter(code=opts["tenant"]).first()
        if tenant is None:
            raise CommandError(f"沒有這家公司:{opts['tenant']}")
        source = None
        if opts["kinds_from"]:
            source = Tenant.objects.filter(code=opts["kinds_from"]).first()
            if source is None:
                raise CommandError(f"沒有這家公司:{opts['kinds_from']}")
        answers = json.loads(Path(opts["answers"]).read_text(encoding="utf-8"))
        r = shop_tidy.tidy(tenant, answers, kinds_from=source, confirm=opts["confirm"])
        out = self.stdout.write
        out(f"{tenant.code}:{'寫好了' if opts['confirm'] else '試算(沒有寫入)'}")
        out(f"  類別種類 {len(r.kinds)} 個:{'、'.join(r.kinds) or '無'}")
        out(f"  改名:{'、'.join(r.renamed) or '無'}")
        out(f"  搬到穿戴:{dict(r.moved) or '無'}")
        out(f"  廠牌:{sum(r.makers.values())} 個商品、{len(r.makers)} 個廠牌 {r.makers.most_common(15)}")
        out(f"  適用機型:{r.fit_products} 個配件、{r.fit_links} 筆;配件類別裡對不到機型的 {r.no_fit} 個")
        if opts["report"]:
            with open(opts["report"], "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow(["類別", "品名", "做了什麼", "內容"])
                w.writerows(r.rows)
            out(f"  明細:{opts['report']}({len(r.rows)} 列)")
