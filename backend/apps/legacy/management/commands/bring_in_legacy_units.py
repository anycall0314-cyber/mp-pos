"""舊系統「IMEI 明細表」放進來當盤點入庫的參考清單(不是庫存;沒刷到的不會入)。

    # 試算(不寫任何東西)
    python manage.py bring_in_legacy_units --tenant 公司代碼 --report IMEI明細表.xls \
        [--cost 存量金額表.xls] [--price 商品價格查詢表.xls]
    # 真的做(整份換掉)
    python manage.py bring_in_legacy_units ... --confirm

**對正式站跑之前要 owner 再說一次可以**(舊系統的資料放上正式站;2026-10-10 的規則)。規則在 `apps/legacy/units.py`。
"""
from django.core.management.base import BaseCommand, CommandError

from apps.legacy import products, units
from apps.tenants.models import Tenant


class Command(BaseCommand):
    help = "舊系統的機器清單(IMEI 明細表)放進來當盤點入庫的參考(預設試算,--confirm 才寫入)"

    def add_arguments(self, parser):
        parser.add_argument("--tenant", required=True, help="公司代碼")
        parser.add_argument("--report", required=True, help="歐睿匯出的 IMEI 明細表")
        parser.add_argument("--cost", help="存量金額表(每個舊品號的成本;選填)")
        parser.add_argument("--price", help="商品價格查詢表 ST015(每個舊品號的零售價;選填)")
        parser.add_argument("--confirm", action="store_true", help="真的寫入(沒有就只試算)")

    def handle(self, *args, **opts):
        tenant = Tenant.objects.filter(code=opts["tenant"]).first()
        if tenant is None:
            raise CommandError(f"找不到公司:{opts['tenant']}")
        try:
            rows = products.read_ored_rows(_read(opts["report"]))
            costs = products.old_costs(products.read_ored_rows(_read(opts["cost"]))) if opts["cost"] else {}
            prices = (units.prices_from(products.stock_items(products.read_ored_rows(_read(opts["price"]))))
                      if opts["price"] else {})
            r = units.load_units(tenant, rows, costs, prices, write=opts["confirm"])
        except (OSError, products.ReportError) as e:
            raise CommandError(str(e)) from None
        w = self.stdout.write
        w(f"公司 {tenant.code}「{tenant.name}」|{'寫入(整份換掉)' if opts['confirm'] else '試算(沒有寫入任何東西)'}")
        w(f"報表庫存中 {r.rows} 列;放進清單 {r.units} 台(沒有 IMEI 的 {r.no_code};同一台登記好幾筆的 {r.duplicate_keys})")
        w(f"有成本 {r.with_cost};有售價 {r.with_price}")
        w("、".join(f"{k} {v}" for k, v in sorted(r.by_prefix.items(), key=lambda kv: -kv[1])[:15]))


def _read(path):
    with open(path, "rb") as f:
        return f.read()
