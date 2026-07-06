"""每週把 Google Trends 匯出的 CSV 灌進 MarketSignal。

Google Trends 官方 API 至今仍是限量 alpha,初期用 CSV 最實在。
接受「整理過的長格式」CSV,欄位(中英擇一即可):
    date / 日期 , keyword / 關鍵字 , value / 熱度
關鍵字會透過 SubjectAlias 對應到 subject_key;對不到的會列出來提醒你補別名。

用法:
    python manage.py import_trends_csv --tenant demo --file trends.csv
    python manage.py import_trends_csv --tenant demo --file repair.csv --kind repair_part --source repair_search
"""
import csv
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError

from apps.signals.models import MarketSignal, SubjectAlias, SubjectKind
from apps.signals.services import record_signal
from apps.tenants.models import Tenant

_DATE_KEYS = ("date", "日期", "week", "週")
_KW_KEYS = ("keyword", "關鍵字", "query", "term")
_VAL_KEYS = ("value", "熱度", "interest", "值")


def _pick(row, keys):
    for k in keys:
        for actual in row:
            if actual and actual.strip().lower() == k.lower():
                return row[actual]
    return None


def _parse_date(s):
    s = (s or "").strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise CommandError(f"無法解析日期:{s!r}(請用 YYYY-MM-DD)")


class Command(BaseCommand):
    help = "匯入 Google Trends CSV 到 MarketSignal"

    def add_arguments(self, parser):
        parser.add_argument("--tenant", required=True, help="租戶 code")
        parser.add_argument("--file", required=True, help="CSV 路徑")
        parser.add_argument("--kind", default=SubjectKind.PRODUCT_SALES,
                            choices=[c[0] for c in SubjectKind.choices])
        parser.add_argument("--source", default=MarketSignal.Source.GOOGLE_TRENDS,
                            choices=[c[0] for c in MarketSignal.Source.choices])

    def handle(self, *args, **opts):
        try:
            tenant = Tenant.objects.get(code=opts["tenant"])
        except Tenant.DoesNotExist:
            raise CommandError(f"找不到租戶:{opts['tenant']}")

        aliases = {
            a.alias.strip().lower(): a.subject_key
            for a in SubjectAlias.objects.for_tenant(tenant).filter(kind=opts["kind"])
        }

        imported, unmapped = 0, set()
        with open(opts["file"], newline="", encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                kw = (_pick(row, _KW_KEYS) or "").strip()
                d = _pick(row, _DATE_KEYS)
                v = _pick(row, _VAL_KEYS)
                if not kw or d is None or v in (None, ""):
                    continue
                subject_key = aliases.get(kw.lower())
                if not subject_key:
                    unmapped.add(kw)
                    continue
                record_signal(tenant, opts["source"], subject_key, _parse_date(d), v)
                imported += 1

        self.stdout.write(self.style.SUCCESS(f"匯入 {imported} 筆訊號"))
        if unmapped:
            self.stdout.write(self.style.WARNING(
                "以下關鍵字沒有別名對應,請到 SubjectAlias 補:" + "、".join(sorted(unmapped))
            ))
