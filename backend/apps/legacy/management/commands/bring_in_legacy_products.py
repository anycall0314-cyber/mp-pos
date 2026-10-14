"""舊 POS 有庫存的品項整批建成品號(品名、舊品號當條碼、售價、成本;不帶數量)。

    # 試算(不寫任何東西)
    python manage.py bring_in_legacy_products --tenant 公司代碼 --report 商品價格查詢表.xls --mapping 類別對照表.xlsx \
        [--cost 存量金額表.xls]
    # 真的做
    python manage.py bring_in_legacy_products ... --confirm
    # 收回整批建的(用過的品號不刪)
    python manage.py bring_in_legacy_products --tenant 公司代碼 --undo [--confirm]

報表用「商品價格查詢表 ST015」(有庫存量、全公司、轉Excel;有零售價),庫存明細表也認(沒有售價,建出來售價是 0)。
成本用「存量金額表」(每個品號一件的成本;沒給、或表上沒有的品號,成本是 0)。
**對正式站跑之前要 owner 再說一次可以**(舊系統的品名、條碼放上正式站;2026-10-10 的規則)。規則在 `apps/legacy/products.py`。
"""
from django.core.management.base import BaseCommand, CommandError

from apps.legacy import products
from apps.tenants.models import Tenant


class Command(BaseCommand):
    help = "舊 POS 有庫存的品項整批建成品號(預設試算,--confirm 才寫入)"

    def add_arguments(self, parser):
        parser.add_argument("--tenant", required=True, help="公司代碼")
        parser.add_argument("--report", help="歐睿匯出的報表(商品價格查詢表 ST015 或庫存明細表)")
        parser.add_argument("--mapping", help="類別對照表 xlsx(舊品名第一段 → 類別)")
        parser.add_argument("--cost", help="歐睿匯出的存量金額表(每個品號的成本;選填)")
        parser.add_argument("--undo", action="store_true", help="收回整批建的(用過的品號不刪)")
        parser.add_argument("--confirm", action="store_true", help="真的寫入(沒有就只試算)")

    def handle(self, *args, **opts):
        tenant = Tenant.objects.filter(code=opts["tenant"]).first()
        if tenant is None:
            raise CommandError(f"找不到公司:{opts['tenant']}")
        write = opts["confirm"]
        mode = "寫入" if write else "試算(沒有寫入任何東西)"
        self.stdout.write(f"公司 {tenant.code}「{tenant.name}」|{mode}")
        if opts["undo"]:
            r = products.take_back_products(tenant, write=write)
            self.stdout.write(f"收回:刪掉品號 {r['removed']} 個;只解除對照 {r['unlinked']} 個;用過、不動 {r['kept']} 個")
            return
        if not opts["report"] or not opts["mapping"]:
            raise CommandError("要給 --report 和 --mapping")
        try:
            with open(opts["report"], "rb") as f:
                items = products.stock_items(products.read_ored_rows(f.read()))
            with open(opts["mapping"], "rb") as f:
                mapping = products.load_category_mapping(f.read())
            if opts["cost"]:
                with open(opts["cost"], "rb") as f:
                    products.with_costs(items, products.old_costs(products.read_ored_rows(f.read())))
        except (OSError, products.ReportError) as e:
            raise CommandError(str(e)) from None
        r = products.bring_in_products(tenant, items, mapping, write=write)
        w = self.stdout.write
        w(f"報表 {len(items)} 個舊品號;沒有庫存 {r.zero_stock}")
        w(f"新建品號 {r.created}(售價 0 的 {r.no_price};沒有成本的 {r.no_cost};另記原廠條碼 {r.aliases})")
        w(f"對到原本就有的(條碼相同){r.linked};之前就對照好的 {r.already}")
        w(f"手機 / 中古機(盤點時刷序號){r.serial}")
        w(f"對照表填排除 {sum(r.excluded.values())}:" + _top(r.excluded))
        w(f"對照表沒有 {sum(r.unmapped.values())}:" + _top(r.unmapped))
        w(f"同名但條碼不同、沒建 {len(r.same_name)}" + "".join(f"\n  {c} {n}" for c, n in r.same_name[:20]))
        if r.new_categories:
            w("新建類別:" + "、".join(r.new_categories))


def _top(counts: dict, n=15) -> str:
    items = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return "、".join(f"{k} {v}" for k, v in items[:n]) + (" …" if len(items) > n else "")
