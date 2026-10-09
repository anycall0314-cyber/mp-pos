"""報表語意層:同一個問題只會有一種數字。

每一個期望值都是照單據手算的(不是把引擎的算法再寫一遍):

    進貨  2026-08-01  湳雅店  手機 2 支 × 20000、皮套 10 個 × 100      → 41000
    調撥              皮套 4 個 湳雅店 → 民生店
    銷貨1 2026-09-10  湳雅店  手機 25000(成本 20000)+ 皮套 2 × 390(成本 200),免稅,有業務員
    銷貨2 2026-08-15  民生店  皮套 1 × 390 含稅(未稅 371、稅 19:整數元、四捨五入;成本 100),沒有業務員
    銷貨3 2026-09-10  湳雅店  皮套 1 × 390(成本 100),免稅,有業務員
    銷退  2026-09-12  整張退掉銷貨3
"""
import shutil
import tempfile
from datetime import date, datetime, timezone as dt_timezone
from decimal import Decimal
from pathlib import Path
from unittest import mock

from django.apps import apps as django_apps
from django.test import TestCase

from apps.backup.tests.factory import Company
from apps.backup.tests.test_backup_restore import _Base as BackupBase
from apps.catalog.models import Category
from apps.inventory.models import Warehouse
from apps.ledger.models import StockSnapshot, StockSnapshotDay
from apps.purchasing.models import PurchaseOrder
from apps.sales.models import SalesOrder, SalesOrderPayment, SalesReturn
from apps.tenants.models import PaymentMethod

from . import engine, saved
from .catalog import BASES, DIMENSIONS, FACTS, MEASURES, base_keys, supported_dims
from .models import SavedReport

AUG_SEP = {"from": "2026-08-01", "to": "2026-09-30"}
SEP = {"from": "2026-09-01", "to": "2026-09-30"}


def build_shop(code="a", name="甲通訊行", tag="甲"):
    c = Company(code, name, tag)
    c.wh2 = c.warehouses[1]
    c.purchase(phone_serials=[f"{tag}-1", f"{tag}-2"], case_qty=10)
    c.transfer(4)
    c.s1 = c.sell(serial_no=f"{tag}-1", case_qty=2)
    c.s2 = c._post("/api/v1/sales-orders/", {
        "customer": c.customer.id, "warehouse": c.wh2.id, "tax_method": "taxable_included",
        "items": [{"product": c.case.id, "qty": 1, "unit_price": "390"}],
        "payments": [{"method": "cash", "amount": "390"}],
    })
    c.s3 = c.sell(case_qty=1)
    c.sr = c._post("/api/v1/sales-returns/", {"original_so": c.s3["id"], "payment_method": "cash"})
    SalesOrder.objects.filter(pk__in=[c.s1["id"], c.s3["id"]]).update(doc_date=date(2026, 9, 10))
    SalesOrder.objects.filter(pk=c.s2["id"]).update(doc_date=date(2026, 8, 15))
    SalesReturn.objects.filter(pk=c.sr["id"]).update(doc_date=date(2026, 9, 12))
    PurchaseOrder.objects.filter(tenant=c.tenant).update(doc_date=date(2026, 8, 1))
    return c


class _Shop(TestCase):
    def setUp(self):
        self.c = build_shop()
        self.t = self.c.tenant
        self.wh1, self.wh2 = self.c.wh, self.c.wh2

    def run_query(self, measures, dimensions=(), period=AUG_SEP, **extra):
        return engine.run(self.t, {
            "measures": list(measures), "dimensions": list(dimensions), "period": period, **extra,
        })

    def by_label(self, result, measure=None):
        """{角度名稱(多個用 | 接): 值}"""
        out = {}
        for row in result["rows"]:
            key = " | ".join(d["label"] for d in row["dims"])
            out[key] = row["values"][measure] if measure else row["values"]
        return out

    def assertRejected(self, spec, text):
        with self.assertRaises(engine.QueryError) as ctx:
            engine.run(self.t, spec)
        self.assertIn(text, str(ctx.exception))


class NumbersTests(_Shop):
    def test_every_measure_matches_the_documents(self):
        measures = [
            "sales_untaxed", "sales_gross", "sales_qty", "sales_cost", "sales_orders",
            "return_untaxed", "return_qty", "return_cost", "return_orders",
            "net_sales", "net_qty",
        ]
        self.assertEqual(self.run_query(measures)["totals"], {
            "sales_untaxed": "26541.00",      # 25000 + 780 + 371 + 390
            "sales_gross": "26560.00",        # 25780 + 390 + 390
            "sales_qty": 5,
            "sales_cost": "20400.00",         # 20000 + 200 + 100 + 100
            "sales_orders": 3,
            "return_untaxed": "390.00",
            "return_qty": 1,
            "return_cost": "100.00",
            "return_orders": 1,
            "net_sales": "26151.00",
            "net_qty": 4,
        })
        self.assertEqual(self.run_query([
            "sales_profit", "gross_profit", "margin_rate", "avg_ticket", "non_margin_amount",
            "purchase_untaxed", "purchase_qty", "received", "refunded", "net_received",
        ])["totals"], {
            "sales_profit": "6141.00",        # 26541 − 20400
            "gross_profit": "5851.00",        # 6141 − (390 − 100)
            "margin_rate": "0.2237",          # 5851 ÷ 26151
            "avg_ticket": "8853.33",          # 26560 ÷ 3
            "non_margin_amount": "0.00",
            "purchase_untaxed": "41000.00",
            "purchase_qty": 12,
            "received": "26560.00",
            "refunded": "390.00",
            "net_received": "26170.00",
        })

    def test_split_by_store(self):
        r = self.run_query(["sales_untaxed", "net_sales", "sales_orders"], ["warehouse"])
        self.assertEqual(self.by_label(r), {
            "甲湳雅店": {"sales_untaxed": "26170.00", "net_sales": "25780.00", "sales_orders": 2},
            "甲民生店": {"sales_untaxed": "371.00", "net_sales": "371.00", "sales_orders": 1},
        })
        self.assertEqual(r["columns"]["dimensions"], [{"key": "warehouse", "label": "門市"}])
        self.assertEqual(r["row_count"], 2)

    def test_split_by_month_and_by_day(self):
        r = self.run_query(["sales_untaxed", "return_untaxed"], ["date"],
                           {**AUG_SEP, "grain": "month"})
        self.assertEqual(self.by_label(r), {
            "2026-08": {"sales_untaxed": "371.00", "return_untaxed": "0.00"},
            "2026-09": {"sales_untaxed": "26170.00", "return_untaxed": "390.00"},
        })
        self.assertEqual([row["dims"][0]["label"] for row in r["rows"]], ["2026-08", "2026-09"])
        day = self.run_query(["net_sales"], ["date"], {**SEP, "grain": "day"})
        # 銷退記在退的那一天,不是原銷貨那一天
        self.assertEqual(self.by_label(day, "net_sales"),
                         {"2026-09-10": "26170.00", "2026-09-12": "-390.00"})
        self.assertEqual(self.by_label(
            self.run_query(["sales_untaxed"], ["date"], {**AUG_SEP, "grain": "quarter"}),
            "sales_untaxed"), {"2026-Q3": "26541.00"})

    def test_two_angles_at_once(self):
        r = self.run_query(["sales_qty", "sales_profit"], ["warehouse", "category"])
        self.assertEqual(self.by_label(r), {
            "甲湳雅店 | 手機": {"sales_qty": 1, "sales_profit": "5000.00"},
            "甲湳雅店 | 皮套": {"sales_qty": 3, "sales_profit": "870.00"},     # 1170 − 300
            "甲民生店 | 皮套": {"sales_qty": 1, "sales_profit": "271.00"},
        })

    def test_order_count_is_not_multiplied_by_lines(self):
        # 銷貨1 同時有手機與皮套:分品類看各算一張,合計仍然是 3 張
        r = self.run_query(["sales_orders"], ["category"])
        self.assertEqual(self.by_label(r, "sales_orders"), {"手機": 1, "皮套": 3})
        self.assertEqual(r["totals"]["sales_orders"], 3)

    def test_void_documents_are_left_out(self):
        r = self.c.admin.post(f"/api/v1/sales-orders/{self.c.s2['id']}/void/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        totals = self.run_query(["sales_untaxed", "sales_orders", "received"])["totals"]
        self.assertEqual(totals, {"sales_untaxed": "26170.00", "sales_orders": 2,
                                  "received": "26170.00"})
        r = self.c.admin.post(f"/api/v1/sales-returns/{self.c.sr['id']}/void/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self.run_query(["return_untaxed", "refunded", "net_sales"])["totals"],
                         {"return_untaxed": "0.00", "refunded": "0.00", "net_sales": "26170.00"})

    def test_buy_back_lines_are_not_revenue(self):
        # 把皮套改成「不計毛利」(收購二手那一類):不算銷售額、不算成本、不算銷量,另外一欄看
        self.c.case.counts_margin = False
        self.c.case.save(update_fields=["counts_margin"])
        self.assertEqual(self.run_query([
            "sales_untaxed", "sales_cost", "sales_qty", "sales_orders", "sales_profit",
            "non_margin_amount", "return_untaxed", "gross_profit",
        ])["totals"], {
            "sales_untaxed": "25000.00", "sales_cost": "20000.00", "sales_qty": 1,
            "sales_orders": 1, "sales_profit": "5000.00",
            "non_margin_amount": "1541.00",       # 780 + 371 + 390
            "return_untaxed": "0.00", "gross_profit": "5000.00",
        })

    def test_margin_rate_without_sales_is_empty_not_zero(self):
        r = self.run_query(["margin_rate", "avg_ticket"], period={"from": "2020-01-01", "to": "2020-01-31"})
        self.assertEqual(r["totals"], {"margin_rate": None, "avg_ticket": None})

    def test_rows_add_up_to_the_totals(self):
        for dims in (["warehouse"], ["category"], ["product"], ["date"], ["warehouse", "product"],
                     ["sales_person"], ["tax_method"], ["condition"], ["item_kind"], ["source"]):
            r = self.run_query(["sales_untaxed", "sales_cost", "return_untaxed"], dims)
            for key in ("sales_untaxed", "sales_cost", "return_untaxed"):
                self.assertEqual(
                    sum(Decimal(row["values"][key]) for row in r["rows"]),
                    Decimal(r["totals"][key]), (dims, key))

    def test_names_of_coded_angles(self):
        self.assertEqual(self.by_label(self.run_query(["received"], ["payment_method"]), "received"),
                         {"現金": "26560.00"})
        self.assertEqual(
            self.by_label(self.run_query(["sales_untaxed"], ["tax_method"]), "sales_untaxed"),
            {"未稅": "26170.00", "應稅內含": "371.00"})
        self.assertEqual(
            self.by_label(self.run_query(["sales_untaxed"], ["sales_person"]), "sales_untaxed"),
            {"甲店員": "26170.00", "(未指定)": "371.00"})
        self.assertEqual(
            self.by_label(self.run_query(["sales_qty"], ["condition", "product_kind"]), "sales_qty"),
            {"新品 | 商品": 5})


class FilterTests(_Shop):
    def test_filter_by_store_category_and_flag(self):
        self.assertEqual(self.run_query(
            ["sales_untaxed"], filters={"warehouse": [self.wh2.id]})["totals"],
            {"sales_untaxed": "371.00"})
        self.assertEqual(self.run_query(
            ["sales_untaxed"], filters={"category": [self.c.cat_phone.id]})["totals"],
            {"sales_untaxed": "25000.00"})
        self.assertEqual(self.run_query(
            ["sales_untaxed"], filters={"condition": [True]})["totals"], {"sales_untaxed": "0.00"})
        both = self.run_query(["sales_untaxed"], filters={
            "warehouse": [self.wh1.id], "category": [self.c.cat_case.id]})
        self.assertEqual(both["totals"], {"sales_untaxed": "1170.00"})
        self.assertEqual(both["applied"]["filters"], [
            {"dimension": "warehouse", "label": "門市",
             "values": [{"value": self.wh1.id, "label": "甲湳雅店"}]},
            {"dimension": "category", "label": "品類",
             "values": [{"value": self.c.cat_case.id, "label": "皮套"}]},
        ])

    def test_filter_for_blank(self):
        r = self.run_query(["sales_untaxed"], filters={"sales_person": [None]})
        self.assertEqual(r["totals"], {"sales_untaxed": "371.00"})
        r = self.run_query(["sales_untaxed"],
                           filters={"sales_person": [None, self.c.sales_person.id]})
        self.assertEqual(r["totals"], {"sales_untaxed": "26541.00"})

    def test_filter_applies_to_every_table_behind_a_measure(self):
        # 淨銷售額 = 銷貨 − 銷退,兩邊都要套到門市條件
        r = self.run_query(["net_sales"], filters={"warehouse": [self.wh1.id]})
        self.assertEqual(r["totals"], {"net_sales": "25780.00"})

    def test_filter_on_the_data_source(self):
        self.assertEqual(self.run_query(["sales_untaxed"], filters={"source": ["legacy"]})["totals"],
                         {"sales_untaxed": "0.00"})
        self.assertEqual(self.run_query(["sales_untaxed"], filters={"source": ["mp"]})["totals"],
                         {"sales_untaxed": "26541.00"})

    def test_bad_filter_values(self):
        spec = {"measures": ["sales_untaxed"], "period": AUG_SEP}
        self.assertRejected({**spec, "filters": {"warehouse": ["1"]}}, "要是編號")
        self.assertRejected({**spec, "filters": {"warehouse": [True]}}, "要是編號")
        self.assertRejected({**spec, "filters": {"warehouse": [987654321]}}, "找不到")
        self.assertRejected({**spec, "filters": {"condition": [1]}}, "是 / 否")
        self.assertRejected({**spec, "filters": {"tax_method": ["nope"]}}, "不認得")
        self.assertRejected({**spec, "filters": {"tax_method": [3]}}, "要是代碼")
        self.assertRejected({**spec, "filters": {"warehouse": []}}, "不能是空的")
        self.assertRejected({**spec, "filters": {"date": ["2026-09-10"]}}, "當條件")
        self.assertRejected({**spec, "filters": {"so__customer__phone": ["x"]}}, "當條件")
        self.assertRejected({**spec, "filters": {"warehouse": list(range(1, 300))}}, "太多")
        self.assertRejected({**spec, "filters": {"supplier": [self.c.supplier.id]}}, "不能用")

    def test_payment_method_deleted_after_use_still_works(self):
        """付款方式可以刪,單據上的代碼還在:照樣分得出來、篩得到,名稱寫明已刪除。"""
        card = PaymentMethod.objects.create(tenant=self.t, code="card", name="信用卡", kind="non_cash")
        SalesOrderPayment.objects.filter(so_id=self.c.s2["id"]).update(method="card")
        SalesReturn.objects.filter(pk=self.c.sr["id"]).update(payment_method="voucher")  # 主檔沒有
        self.assertEqual(self.by_label(self.run_query(["received"], ["payment_method"]), "received"),
                         {"現金": "26170.00", "信用卡": "390.00"})
        card.delete()
        self.assertEqual(self.by_label(self.run_query(["received"], ["payment_method"]), "received"),
                         {"現金": "26170.00", "card(已刪除)": "390.00"})
        r = self.run_query(["received"], filters={"payment_method": ["card"]})
        self.assertEqual(r["totals"], {"received": "390.00"})
        self.assertEqual(r["applied"]["filters"][0]["values"],
                         [{"value": "card", "label": "card(已刪除)"}])
        self.assertEqual(
            self.run_query(["refunded"], filters={"payment_method": ["voucher"]})["totals"],
            {"refunded": "390.00"})
        self.assertEqual(engine.options(self.t, "payment_method"), [
            {"value": "cash", "label": "現金"}, {"value": "card", "label": "card(已刪除)"},
            {"value": "voucher", "label": "voucher(已刪除)"}])
        # 主檔全部刪光:單據上用過的還是認得,沒用過的一樣不接受
        PaymentMethod.objects.filter(tenant=self.t).delete()
        self.assertEqual(
            self.run_query(["received"], filters={"payment_method": ["cash"]})["totals"],
            {"received": "26170.00"})
        self.assertRejected({"measures": ["received"], "period": AUG_SEP,
                             "filters": {"payment_method": ["nope"]}}, "不認得")
        # 單據上沒寫付款方式的(空白)不是一種代碼,不列進可選的值
        SalesOrderPayment.objects.filter(so_id=self.c.s3["id"]).update(method="")
        self.assertEqual([o["value"] for o in engine.options(self.t, "payment_method")],
                         ["card", "cash", "voucher"])

    def test_an_empty_list_of_codes_accepts_nothing(self):
        """公司沒有任何付款方式、也沒有收過款:清單是空的 = 全部不接受,不是不檢查。"""
        empty = Company("e", "空通訊行", "空")
        PaymentMethod.objects.filter(tenant=empty.tenant).delete()
        self.assertEqual(engine.options(empty.tenant, "payment_method"), [])
        with self.assertRaises(engine.QueryError) as ctx:
            engine.run(empty.tenant, {"measures": ["received"], "period": AUG_SEP,
                                      "filters": {"payment_method": ["anything"]}})
        self.assertIn("不認得", str(ctx.exception))


class OtherCompanyTests(_Shop):
    def setUp(self):
        super().setUp()
        self.b = build_shop("b", "乙通訊行", "乙")

    def test_numbers_never_include_the_other_company(self):
        r = self.run_query(["sales_untaxed", "purchase_untaxed", "received"], ["warehouse"])
        self.assertEqual(r["totals"]["sales_untaxed"], "26541.00")
        self.assertEqual(r["totals"]["purchase_untaxed"], "41000.00")
        self.assertTrue(all(row["dims"][0]["label"].startswith("甲") for row in r["rows"]))

    def test_other_companys_ids_are_unknown(self):
        for key, other in (("warehouse", self.b.wh.id), ("category", self.b.cat_phone.id),
                           ("product", self.b.phone.id), ("sales_person", self.b.sales_person.id)):
            self.assertRejected({"measures": ["sales_untaxed"], "period": AUG_SEP,
                                 "filters": {key: [other]}}, "找不到")
        self.assertRejected({"measures": ["purchase_untaxed"], "period": AUG_SEP,
                             "filters": {"supplier": [self.b.supplier.id]}}, "找不到")

    def test_choices_list_only_own_data(self):
        for key in ("warehouse", "category", "product", "sales_person", "supplier"):
            labels = [o["label"] for o in engine.options(self.t, key)]
            self.assertTrue(labels, key)
            ids = {o["value"] for o in engine.options(self.t, key)}
            model = django_apps.get_model(DIMENSIONS[key].model)
            self.assertEqual(ids, set(model.objects.filter(tenant=self.t).values_list("pk", flat=True)))
        self.assertEqual(engine.options(self.t, "payment_method"), [{"value": "cash", "label": "現金"}])
        # 別家單據上用過的付款代碼,在這家不算數
        SalesOrderPayment.objects.filter(tenant=self.b.tenant).update(method="bpay")
        SalesReturn.objects.filter(tenant=self.b.tenant).update(payment_method="bback")
        self.assertEqual(engine.options(self.t, "payment_method"), [{"value": "cash", "label": "現金"}])
        for code in ("bpay", "bback"):
            self.assertRejected({"measures": ["net_received"], "period": AUG_SEP,
                                 "filters": {"payment_method": [code]}}, "不認得")

    def test_api_answers_for_the_callers_company(self):
        spec = {"measures": ["sales_untaxed"], "dimensions": ["warehouse"], "period": AUG_SEP}
        mine = self.c.admin.post("/api/v1/analytics/query/", spec, format="json").json()
        theirs = self.b.admin.post("/api/v1/analytics/query/", spec, format="json").json()
        self.assertEqual({row["dims"][0]["label"] for row in mine["rows"]}, {"甲湳雅店", "甲民生店"})
        self.assertEqual({row["dims"][0]["label"] for row in theirs["rows"]}, {"乙湳雅店", "乙民生店"})
        # 帳號綁了公司就不能用 ?tenant= 換到別家
        r = self.c.admin.post(f"/api/v1/analytics/query/?tenant={self.b.tenant.id}", spec, format="json")
        self.assertEqual({row["dims"][0]["label"] for row in r.json()["rows"]}, {"甲湳雅店", "甲民生店"})
        r = self.c.admin.get(f"/api/v1/analytics/options/?dimension=warehouse&tenant={self.b.tenant.id}")
        self.assertEqual({o["label"] for o in r.json()["results"]}, {"甲湳雅店", "甲民生店"})


class CompareTests(_Shop):
    def test_previous_period(self):
        r = self.run_query(["net_sales", "sales_orders"], ["warehouse"], SEP, compare="previous")
        self.assertEqual(r["applied"]["compare_period"], {"from": "2026-08-02", "to": "2026-08-31"})
        rows = {row["dims"][0]["label"]: row for row in r["rows"]}
        self.assertEqual(rows["甲湳雅店"]["values"], {"net_sales": "25780.00", "sales_orders": 2})
        self.assertEqual(rows["甲湳雅店"]["previous"], {"net_sales": "0.00", "sales_orders": 0})
        # 這一期沒有、上一期有的門市也要列出來
        self.assertEqual(rows["甲民生店"]["values"], {"net_sales": "0.00", "sales_orders": 0})
        self.assertEqual(rows["甲民生店"]["previous"], {"net_sales": "371.00", "sales_orders": 1})
        self.assertEqual(r["totals"], {"net_sales": "25780.00", "sales_orders": 2})
        self.assertEqual(r["totals_previous"], {"net_sales": "371.00", "sales_orders": 1})

    def test_same_period_last_year(self):
        SalesOrder.objects.filter(pk=self.c.s2["id"]).update(doc_date=date(2025, 9, 30))
        r = self.run_query(["sales_untaxed"], period=SEP, compare="last_year")
        self.assertEqual(r["applied"]["compare_period"], {"from": "2025-09-01", "to": "2025-09-30"})
        self.assertEqual(r["totals_previous"], {"sales_untaxed": "371.00"})
        leap = engine.parse({"measures": ["sales_untaxed"], "compare": "last_year",
                             "period": {"from": "2024-02-01", "to": "2024-02-29"}})
        self.assertEqual(engine._compare_period(leap), (date(2023, 2, 1), date(2023, 2, 28)))

    def test_no_compare_by_default(self):
        r = self.run_query(["net_sales"], ["warehouse"], SEP)
        self.assertNotIn("totals_previous", r)
        self.assertNotIn("previous", r["rows"][0])
        self.assertIsNone(r["applied"]["compare"])


class StockTests(_Shop):
    def day(self, day):
        """「這一天有拍過庫存」的記號(數量是 0 的商品不會有明細,只有這個記號)。"""
        StockSnapshotDay.objects.get_or_create(
            tenant=self.t, business_date=day,
            defaults={"row_count": 0,
                      "taken_at": datetime(day.year, day.month, day.day, 15, 30, tzinfo=dt_timezone.utc)},
        )

    def snap(self, day, warehouse, qty, value, state="in_stock", product=None):
        self.day(day)
        StockSnapshot.objects.create(
            tenant=self.t, business_date=day, warehouse=warehouse, product=product or self.c.case,
            state=state, qty=qty, cost_value=value,
            taken_at=datetime(day.year, day.month, day.day, 15, 30, tzinfo=dt_timezone.utc),
        )

    def setUp(self):
        super().setUp()
        self.snap(date(2026, 8, 31), self.wh1, 6, "600")
        self.snap(date(2026, 9, 29), self.wh1, 5, "500")
        self.snap(date(2026, 9, 29), self.wh2, 3, "300")
        self.snap(date(2026, 9, 30), self.wh1, 4, "400")
        self.snap(date(2026, 9, 30), self.wh2, 3, "300")
        self.snap(date(2026, 9, 30), self.wh2, 1, "20000", state="returned", product=self.c.phone)

    def test_stock_is_the_last_day_not_a_sum_of_days(self):
        r = self.run_query(["stock_qty", "stock_value"])
        self.assertEqual(r["totals"], {"stock_qty": 8, "stock_value": "20700.00"})
        r = self.run_query(["stock_qty"], period={"from": "2026-08-01", "to": "2026-09-29"})
        self.assertEqual(r["totals"], {"stock_qty": 8})          # 9/29:5 + 3
        r = self.run_query(["stock_qty"], period={"from": "2026-08-01", "to": "2026-08-31"})
        self.assertEqual(r["totals"], {"stock_qty": 6})
        r = self.run_query(["stock_qty"], period={"from": "2026-07-01", "to": "2026-07-31"})
        self.assertEqual(r["totals"], {"stock_qty": 0})

    def test_stock_by_store_state_and_month(self):
        r = self.run_query(["stock_qty", "stock_value"], ["warehouse", "stock_state"])
        self.assertEqual(self.by_label(r), {
            "甲湳雅店 | 在庫": {"stock_qty": 4, "stock_value": "400.00"},
            "甲民生店 | 在庫": {"stock_qty": 3, "stock_value": "300.00"},
            "甲民生店 | 退回待處理": {"stock_qty": 1, "stock_value": "20000.00"},
        })
        r = self.run_query(["stock_qty"], ["date"], {**AUG_SEP, "grain": "month"})
        self.assertEqual(self.by_label(r, "stock_qty"), {"2026-08": 6, "2026-09": 8})
        self.assertEqual(r["totals"], {"stock_qty": 8})           # 合計 = 期間最後一天,不是各月相加

    def test_sold_out_is_zero_not_the_last_day_it_had_stock(self):
        """賣到 0 的東西在快照裡沒有明細。「最後一天」要看哪一天有拍過,不是看哪一天還有明細,
        否則歸零之後會一直報最後一次有貨的數量。"""
        OCT = {"from": "2026-08-01", "to": "2026-10-02"}
        self.snap(date(2026, 10, 2), self.wh1, 2, "200")          # 10/2:只剩湳雅店 2 個皮套
        # 門市歸零
        r = self.run_query(["stock_qty"], period=OCT, filters={"warehouse": [self.wh2.id]})
        self.assertEqual(r["totals"], {"stock_qty": 0})
        # 商品歸零(手機 9/30 還有 1 支退回待處理,10/2 沒有了)
        r = self.run_query(["stock_qty", "stock_value"], period=OCT,
                           filters={"product": [self.c.phone.id]})
        self.assertEqual(r["totals"], {"stock_qty": 0, "stock_value": "0.00"})
        r = self.run_query(["stock_qty"], ["warehouse"], OCT)
        self.assertEqual(self.by_label(r, "stock_qty"), {"甲湳雅店": 2})
        # 整家公司歸零:10/3 有拍、一筆明細都沒有
        self.day(date(2026, 10, 3))
        ALL = {"from": "2026-08-01", "to": "2026-10-03"}
        self.assertEqual(self.run_query(["stock_qty"], period=ALL)["totals"], {"stock_qty": 0})
        # 按月看:月底歸零的那個月要列出來寫 0,合計也是 0
        r = self.run_query(["stock_qty"], ["date"], {**ALL, "grain": "month"})
        self.assertEqual(self.by_label(r, "stock_qty"), {"2026-08": 6, "2026-09": 8, "2026-10": 0})
        self.assertEqual(r["totals"], {"stock_qty": 0})
        r = self.run_query(["stock_qty"], ["date"], {**ALL, "grain": "month"},
                           filters={"warehouse": [self.wh2.id]})
        self.assertEqual(self.by_label(r, "stock_qty"), {"2026-08": 0, "2026-09": 4, "2026-10": 0})
        # 跟上一期比:這一期歸零、上一期有貨
        r = self.run_query(["stock_qty"], period={"from": "2026-10-01", "to": "2026-10-03"},
                           compare="previous")
        self.assertEqual((r["totals"], r["totals_previous"]), ({"stock_qty": 0}, {"stock_qty": 8}))
        # 完全沒拍過的期間:0
        r = self.run_query(["stock_qty"], period={"from": "2026-07-01", "to": "2026-07-31"})
        self.assertEqual(r["totals"], {"stock_qty": 0})


class ShapeTests(_Shop):
    SPEC = {"measures": ["sales_untaxed"], "period": AUG_SEP}

    def test_sorting_and_row_limit(self):
        r = self.run_query(["sales_untaxed"], ["warehouse"])
        self.assertEqual([row["dims"][0]["label"] for row in r["rows"]], ["甲湳雅店", "甲民生店"])
        r = self.run_query(["sales_untaxed"], ["warehouse"], sort="sales_untaxed")
        self.assertEqual([row["dims"][0]["label"] for row in r["rows"]], ["甲民生店", "甲湳雅店"])
        r = self.run_query(["sales_untaxed"], ["warehouse"], sort="warehouse")
        self.assertEqual([row["dims"][0]["label"] for row in r["rows"]], ["甲民生店", "甲湳雅店"])
        r = self.run_query(["sales_untaxed"], ["date"], {**AUG_SEP, "grain": "month"}, sort="-date")
        self.assertEqual([row["dims"][0]["label"] for row in r["rows"]], ["2026-09", "2026-08"])
        # 有日期時預設照分組的順序排(先第一個分組、再第二個),不是只看日期
        r = self.run_query(["sales_untaxed"], ["warehouse", "date"], {**AUG_SEP, "grain": "month"})
        self.assertEqual([" ".join(d["label"] for d in row["dims"]) for row in r["rows"]],
                         ["甲民生店 2026-08", "甲湳雅店 2026-09"])
        r = self.run_query(["sales_qty"], ["category", "warehouse"], sort="-category")
        self.assertEqual([" ".join(d["label"] for d in row["dims"]) for row in r["rows"]],
                         ["皮套 甲民生店", "皮套 甲湳雅店", "手機 甲湳雅店"])
        r = self.run_query(["sales_untaxed"], ["warehouse"], limit=1)
        self.assertEqual((len(r["rows"]), r["row_count"], r["truncated"]), (1, 2, True))
        self.assertEqual(r["totals"], {"sales_untaxed": "26541.00"})       # 合計不受筆數上限影響

    def test_rows_without_a_value_sort_last(self):
        # 手機那張銷貨挪到期間外:手機只剩進貨,毛利率算不出來(空的)。不管由大到小或由小到大都排最後
        SalesOrder.objects.filter(pk=self.c.s1["id"]).update(doc_date=date(2020, 1, 1))
        for order in ("-margin_rate", "margin_rate"):
            r = self.run_query(["margin_rate", "purchase_qty"], ["category"], sort=order)
            self.assertEqual(
                [(row["dims"][0]["label"], row["values"]["margin_rate"] is None) for row in r["rows"]],
                [("皮套", False), ("手機", True)], order)

    def test_requests_that_make_no_sense_are_refused_in_plain_words(self):
        s = self.SPEC
        self.assertRejected([], "格式不對")
        self.assertRejected({**s, "measures": []}, "至少要選一個指標")
        self.assertRejected({**s, "measures": "sales_untaxed"}, "要是清單")
        self.assertRejected({**s, "measures": ["nope"]}, "沒有「nope」這個指標")
        self.assertRejected({**s, "measures": [{"x": 1}]}, "這個指標")
        self.assertRejected({**s, "measures": ["sales_untaxed", "sales_untaxed"]}, "重複")
        self.assertRejected({**s, "measures": list(MEASURES)[:13]}, "一次最多 12 個指標")
        self.assertRejected({**s, "dimensions": ["so__customer__phone"]}, "這個角度")
        self.assertRejected({**s, "dimensions": ["warehouse", "category", "brand", "product"]}, "最多 3 個角度")
        self.assertRejected({**s, "measures": ["received"], "dimensions": ["product"]},
                            "「收款」不能用「商品」")
        self.assertRejected({**s, "measures": ["net_received"], "dimensions": ["category"]}, "不能用")
        self.assertRejected({**s, "period": {"from": "2026-13-01", "to": "2026-09-30"}}, "YYYY-MM-DD")
        self.assertRejected({**s, "period": {"from": "2026-09-30", "to": "2026-09-01"}}, "不能早於")
        self.assertRejected({**s, "period": {"from": "1990-01-01", "to": "2026-09-01"}}, "太長")
        self.assertRejected({**s, "period": {**AUG_SEP, "grain": "hour"}}, "日期單位")
        for bad in (["month"], {"a": 1}, 5, True):
            self.assertRejected({**s, "period": {**AUG_SEP, "grain": bad}}, "日期單位")
        self.assertRejected({**s, "period": {"preset": "forever"}}, "沒有這個期間")
        self.assertRejected({**s, "period": "2026"}, "期間格式不對")
        self.assertRejected({"measures": ["sales_untaxed"]}, "YYYY-MM-DD")
        self.assertRejected({**s, "compare": "next"}, "比較只能是")
        self.assertRejected({**s, "dimensions": ["date"], "compare": "previous"}, "有日期角度時")
        self.assertRejected({**s, "sort": "sales_cost"}, "排序只能用")
        self.assertRejected({**s, "sort": ["sales_untaxed"]}, "排序只能用")
        self.assertRejected({**s, "limit": 0.5}, "筆數上限")
        self.assertRejected({**s, "limit": 0}, "筆數上限")
        self.assertRejected({**s, "limit": 99999}, "筆數上限")
        self.assertRejected({**s, "limit": True}, "筆數上限")
        for bad in (["warehouse"], [], 0, "", False):
            self.assertRejected({**s, "filters": bad}, "條件格式不對")
        self.assertEqual(engine.run(self.t, {**s, "filters": None})["applied"]["filters"], [])

    def test_relative_periods(self):
        day = date(2026, 10, 4)
        self.assertEqual(engine.preset_range("today", day), (day, day))
        self.assertEqual(engine.preset_range("yesterday", day), (date(2026, 10, 3),) * 2)
        self.assertEqual(engine.preset_range("last_7_days", day), (date(2026, 9, 28), day))
        self.assertEqual(engine.preset_range("last_30_days", day), (date(2026, 9, 5), day))
        self.assertEqual(engine.preset_range("this_month", day), (date(2026, 10, 1), day))
        self.assertEqual(engine.preset_range("last_month", day), (date(2026, 9, 1), date(2026, 9, 30)))
        self.assertEqual(engine.preset_range("this_quarter", day), (date(2026, 10, 1), day))
        self.assertEqual(engine.preset_range("this_quarter", date(2026, 9, 30)),
                         (date(2026, 7, 1), date(2026, 9, 30)))
        self.assertEqual(engine.preset_range("this_year", day), (date(2026, 1, 1), day))
        self.assertEqual(engine.preset_range("last_year", day), (date(2025, 1, 1), date(2025, 12, 31)))
        self.assertEqual(engine.preset_range("last_month", date(2026, 1, 15)),
                         (date(2025, 12, 1), date(2025, 12, 31)))
        self.assertEqual(engine.preset_range("last_month", date(2026, 3, 31)),
                         (date(2026, 2, 1), date(2026, 2, 28)))
        with mock.patch("django.utils.timezone.localdate", return_value=date(2026, 9, 20)):
            r = self.run_query(["sales_untaxed"], period={"preset": "this_month"})
        self.assertEqual(r["applied"]["period"], {"from": "2026-09-01", "to": "2026-09-20"})
        self.assertEqual(r["totals"], {"sales_untaxed": "26170.00"})

    def test_every_measure_and_angle_actually_runs(self):
        """定義裡寫的每一個組合都查得出來(欄位路徑寫錯在這裡就會爆,不是等使用者點到)。"""
        for m in MEASURES.values():
            if getattr(m, "hidden", False):
                continue
            dims = sorted(supported_dims(m.key))
            self.assertIn("date", dims)
            for d in dims:
                # 用管理員的身分跑:有的指標只有管理員看得到(公司實際拿的佣金)
                engine.run(self.t, {"measures": [m.key], "dimensions": [d], "period": AUG_SEP}, self.c.admin_user)
        for fact in FACTS.values():
            self.assertFalse(set(fact.paths) - set(DIMENSIONS), fact.key)
        for b in BASES:
            self.assertIn(b.fact, FACTS)
        for m in MEASURES.values():
            self.assertTrue(base_keys(m.key))
        for dim in DIMENSIONS.values():      # 代碼型的角度一定要有清單:條件只接受清單裡的代碼
            if dim.kind == "choice":
                self.assertTrue(callable(dim.labels), dim.key)

    def test_catalog_lists_what_can_be_combined(self):
        d = engine.describe()
        by_key = {m["key"]: m for m in d["measures"]}
        self.assertIn("warehouse", by_key["net_sales"]["dimensions"])
        self.assertNotIn("product", by_key["received"]["dimensions"])
        self.assertNotIn("supplier", by_key["net_sales"]["dimensions"])
        self.assertEqual(by_key["margin_rate"]["format"], "pct")
        # 每個指標都歸在選單的某一類
        self.assertEqual({m["group"] for m in d["measures"]} - set(d["groups"]), set())
        self.assertEqual((by_key["gross_profit"]["group"], by_key["stock_qty"]["group"],
                          by_key["net_received"]["group"]), ("毛利", "庫存", "收款"))
        self.assertEqual({p["key"] for p in d["presets"]}, set(engine.PRESETS))
        self.assertEqual(d["limits"], {"dimensions": 3, "measures": 12, "rows": 2000})


class LegacyTests(_Shop):
    """舊 POS 十年歷史跟新系統放在同一條時間軸。

        湳雅店 E11 2022-03-01  手機 5000 + 保貼 2 × 250 = 500
        民生店 E11 2022-03-02  手機 4000
        湳雅店 F11 2023-01-05  保貼 250(銷退類,淨額 −250)
    """

    def setUp(self):
        super().setUp()
        from apps.legacy import importer
        from apps.legacy.tests.archive_builder import ArchiveBuilder, doc, line

        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        b = ArchiveBuilder(tmp / "archive")
        older, newer = b.batch("2016-10-03", "2021-10-02"), b.batch("2021-10-03", "2026-10-03")
        member = b.member("001", "王小明", "0912000111")
        b.period(older, member, [])
        b.period(newer, member, [
            doc("湳雅店", "E11", "1110301001", "2022-03-01", [
                line("A1", "手機/X", "1", "5000", 5000), line("A2", "保貼", "2", "250", 500)]),
            doc("民生店", "E11", "1110302001", "2022-03-02", [line("A1", "手機/X", "1", "4000", 4000)]),
            doc("湳雅店", "F11", "1120105001", "2023-01-05", [line("A2", "保貼", "1", "250", 250)]),
        ])
        root = b.finish()
        importer.run(self.t, root, period=(date(2016, 10, 3), date(2026, 10, 3)), write=True,
                     reconciled_only=True)

    TEN_YEARS = {"from": "2016-10-03", "to": "2026-10-03"}

    def test_legacy_totals(self):
        r = self.run_query(["legacy_raw", "legacy_net", "legacy_lines"], period=self.TEN_YEARS)
        self.assertEqual(r["totals"], {"legacy_raw": "9750.00", "legacy_net": "9250.00",
                                       "legacy_lines": 4})

    def test_unmapped_until_a_person_confirms(self):
        from apps.legacy import mapping
        from apps.legacy.models import LegacyProductMap, LegacyStoreMap

        r = self.run_query(["legacy_net"], ["warehouse"], self.TEN_YEARS)
        self.assertEqual(self.by_label(r, "legacy_net"), {"未對照": "9250.00"})
        mapping.confirm_map("store", LegacyStoreMap.objects.get(tenant=self.t, store_name_raw="湳雅店"),
                            self.wh1, self.c.admin_user)
        mapping.confirm_map("product", LegacyProductMap.objects.get(tenant=self.t, product_code_raw="A1"),
                            self.c.phone, self.c.admin_user)
        r = self.run_query(["legacy_net"], ["warehouse"], self.TEN_YEARS)
        self.assertEqual(self.by_label(r, "legacy_net"), {"甲湳雅店": "5250.00", "未對照": "4000.00"})
        r = self.run_query(["legacy_net"], ["category"], self.TEN_YEARS)
        self.assertEqual(self.by_label(r, "legacy_net"), {"手機": "9000.00", "未對照": "250.00"})
        r = self.run_query(["legacy_net"], period=self.TEN_YEARS, filters={"warehouse": [self.wh1.id]})
        self.assertEqual(r["totals"], {"legacy_net": "5250.00"})
        r = self.run_query(["legacy_net"], period=self.TEN_YEARS, filters={"warehouse": [None]})
        self.assertEqual(r["totals"], {"legacy_net": "4000.00"})

    def test_old_and_new_on_one_timeline(self):
        r = self.run_query(["all_sales", "legacy_net", "net_sales"], ["date"],
                           {**self.TEN_YEARS, "grain": "year"})
        self.assertEqual(self.by_label(r), {
            "2022": {"all_sales": "9500.00", "legacy_net": "9500.00", "net_sales": "0.00"},
            "2023": {"all_sales": "-250.00", "legacy_net": "-250.00", "net_sales": "0.00"},
            "2026": {"all_sales": "26151.00", "legacy_net": "0.00", "net_sales": "26151.00"},
        })
        self.assertEqual(r["totals"]["all_sales"], "35401.00")
        r = self.run_query(["all_sales"], ["source"], self.TEN_YEARS)
        self.assertEqual(self.by_label(r, "all_sales"), {"新系統": "26151.00", "舊 POS": "9250.00"})
        r = self.run_query(["all_sales"], period=self.TEN_YEARS, filters={"source": ["legacy"]})
        self.assertEqual(r["totals"], {"all_sales": "9250.00"})

    def test_blank_rows_from_both_systems_share_one_row(self):
        r = self.run_query(["all_sales"], ["sales_person"], self.TEN_YEARS)
        self.assertEqual(self.by_label(r, "all_sales"),
                         {"甲店員": "25780.00", "(未指定) / 未對照": "9621.00"})

    def test_legacy_types(self):
        r = self.run_query(["legacy_raw"], ["legacy_doc_type"], self.TEN_YEARS)
        self.assertEqual(self.by_label(r, "legacy_raw"),
                         {"E11(加項)": "9500.00", "F11(減項)": "250.00"})
        # 單別可以當條件;不認得的單別不收
        r = self.run_query(["legacy_net"], period=self.TEN_YEARS, filters={"legacy_doc_type": ["F11"]})
        self.assertEqual(r["totals"], {"legacy_net": "-250.00"})
        self.assertRejected({"measures": ["legacy_net"], "period": self.TEN_YEARS,
                             "filters": {"legacy_doc_type": ["ZZ99"]}}, "不認得")
        self.assertIn({"value": "F11", "label": "F11(減項)"}, engine.options(self.t, "legacy_doc_type"))


class ApiTests(_Shop):
    SPEC = {"measures": ["net_sales", "gross_profit"], "dimensions": ["warehouse"], "period": AUG_SEP}

    def test_catalog_query_and_options(self):
        r = self.c.admin.get("/api/v1/analytics/catalog/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(set(r.json()),
                         {"measures", "dimensions", "groups", "grains", "presets", "limits"})
        r = self.c.admin.post("/api/v1/analytics/query/", self.SPEC, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["totals"], {"net_sales": "26151.00", "gross_profit": "5851.00"})
        r = self.c.admin.get("/api/v1/analytics/options/?dimension=warehouse")
        self.assertEqual([o["label"] for o in r.json()["results"]], ["甲民生店", "甲湳雅店"])
        r = self.c.admin.get("/api/v1/analytics/options/?dimension=warehouse&q=民生")
        self.assertEqual([o["label"] for o in r.json()["results"]], ["甲民生店"])
        r = self.c.admin.get("/api/v1/analytics/options/?dimension=condition")
        self.assertEqual(r.json()["results"], [{"value": True, "label": "中古"},
                                               {"value": False, "label": "新品"}])

    def test_bad_requests_get_a_plain_message(self):
        r = self.c.admin.post("/api/v1/analytics/query/", {"measures": ["nope"], "period": AUG_SEP},
                              format="json")
        self.assertEqual((r.status_code, r.json()), (400, {"detail": "沒有「nope」這個指標"}))
        r = self.c.admin.post("/api/v1/analytics/query/", ["x"], format="json")
        self.assertEqual(r.status_code, 400)
        # 型別亂填也是 400 的白話訊息,不是 500
        for period in ({**AUG_SEP, "grain": ["month"]}, {"preset": ["today"]}, {"from": [], "to": {}}, 7):
            r = self.c.admin.post("/api/v1/analytics/query/",
                                  {"measures": ["net_sales"], "period": period}, format="json")
            self.assertEqual(r.status_code, 400, period)
        for body in ({"measures": [["net_sales"]], "period": AUG_SEP},
                     {"measures": ["net_sales"], "dimensions": [{"a": 1}], "period": AUG_SEP},
                     {"measures": ["net_sales"], "period": AUG_SEP, "compare": ["previous"]},
                     {"measures": ["net_sales"], "period": AUG_SEP, "filters": {"warehouse": [[1]]}},
                     {"measures": ["net_sales"], "period": AUG_SEP, "filters": {"tax_method": [["x"]]}},
                     {"measures": ["net_sales"], "period": AUG_SEP, "limit": "10"}):
            r = self.c.admin.post("/api/v1/analytics/query/", body, format="json")
            self.assertEqual(r.status_code, 400, body)
        for dim in ("", "date", "so__customer", "nope"):
            r = self.c.admin.get(f"/api/v1/analytics/options/?dimension={dim}")
            self.assertEqual(r.status_code, 400, dim)

    def test_login_required(self):
        from rest_framework.test import APIClient

        anon = APIClient()
        for method, url in (("get", "catalog/"), ("post", "query/"), ("get", "options/?dimension=warehouse"),
                            ("get", "reports/"), ("post", "reports/")):
            r = getattr(anon, method)(f"/api/v1/analytics/{url}")
            self.assertEqual(r.status_code, 401, url)

    def test_store_clerk_sees_the_whole_company(self):
        # 產品決定(2026-10-04):報表暫時不依門市上鎖。要鎖時改 Base.roles 與這支測試。
        r = self.c.clerk.post("/api/v1/analytics/query/", self.SPEC, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual({row["dims"][0]["label"] for row in r.json()["rows"]}, {"甲湳雅店", "甲民生店"})

    def test_query_only_reads(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as ctx:
            self.c.admin.post("/api/v1/analytics/query/", {
                **self.SPEC, "filters": {"warehouse": [self.wh1.id]}, "compare": "previous",
            }, format="json")
        writes = [q["sql"] for q in ctx.captured_queries
                  if q["sql"].lstrip().split(" ", 1)[0].upper() in ("INSERT", "UPDATE", "DELETE")]
        self.assertEqual(writes, [])


class SavedReportTests(_Shop):
    URL = "/api/v1/analytics/reports/"
    SPEC = {"measures": ["net_sales"], "dimensions": ["warehouse"], "period": {"preset": "last_month"}}

    def setUp(self):
        super().setUp()
        self.b = build_shop("b", "乙通訊行", "乙")

    def save(self, client=None, **body):
        return (client or self.c.admin).post(self.URL, {"name": "上月各店", "spec": self.SPEC, **body},
                                             format="json")

    def names(self, client):
        return [r["name"] for r in client.get(self.URL).json()["results"]]

    def test_save_open_rename_delete(self):
        r = self.save()
        self.assertEqual(r.status_code, 201, r.content)
        body = r.json()
        self.assertEqual(body["spec"], {
            "measures": ["net_sales"], "dimensions": ["warehouse"],
            "period": {"preset": "last_month", "grain": "month"},
            "filters": {}, "compare": None, "sort": "", "limit": 500,
        })
        self.assertEqual((body["mine"], body["editable"], body["shared"], body["missing"], body["error"]),
                         (True, True, False, [], ""))
        self.assertEqual(self.names(self.c.admin), ["上月各店"])
        r = self.c.admin.patch(f"{self.URL}{body['id']}/", {"name": "上月"}, format="json")
        self.assertEqual((r.status_code, r.json()["name"]), (200, "上月"))
        r = self.c.admin.patch(f"{self.URL}{body['id']}/", {
            "spec": {**self.SPEC, "measures": ["gross_profit"]}}, format="json")
        self.assertEqual(r.json()["spec"]["measures"], ["gross_profit"])
        self.assertEqual(self.c.admin.delete(f"{self.URL}{body['id']}/").status_code, 204)
        self.assertEqual(self.names(self.c.admin), [])

    def test_only_valid_tidy_specs_are_stored(self):
        r = self.save(spec={**self.SPEC, "junk": "x" * 5000, "sql": "select 1"})
        self.assertEqual(r.status_code, 201)
        stored = SavedReport.objects.get(pk=r.json()["id"]).spec
        self.assertEqual(set(stored), {"measures", "dimensions", "period", "filters", "compare",
                                       "sort", "limit"})
        self.assertEqual(self.save(name="壞的", spec={"measures": ["nope"]}).status_code, 400)
        self.assertEqual(self.save(name="").status_code, 400)
        self.assertEqual(self.save(name="字" * 61).status_code, 400)
        self.assertEqual(self.save(name=["x"]).status_code, 400)
        self.assertEqual(self.save(name="共用", shared="yes").status_code, 400)
        dup = self.save()
        self.assertEqual((dup.status_code, dup.json()["detail"]), (400, "已經有同名的報表"))
        # 別家公司的門市當條件:存不進去
        r = self.save(name="別家", spec={**self.SPEC, "filters": {"warehouse": [self.b.wh.id]}})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(SavedReport.objects.filter(tenant=self.t).count(), 1)

    def test_private_until_an_admin_shares_it(self):
        mine = self.save().json()
        self.assertEqual(self.names(self.c.clerk), [])
        r = self.c.clerk.patch(f"{self.URL}{mine['id']}/", {"name": "偷改"}, format="json")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(self.c.clerk.delete(f"{self.URL}{mine['id']}/").status_code, 404)
        # 店員不能設成全公司共用
        self.assertEqual(self.save(self.c.clerk, name="店員的", shared=True).status_code, 400)
        own = self.save(self.c.clerk, name="店員的").json()
        self.assertEqual(self.c.clerk.patch(f"{self.URL}{own['id']}/", {"shared": True},
                                            format="json").status_code, 400)
        # 管理員共用之後:店員看得到、打得開,但不能改也不能刪
        r = self.c.admin.patch(f"{self.URL}{mine['id']}/", {"shared": True}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        seen = {r["name"]: r for r in self.c.clerk.get(self.URL).json()["results"]}
        self.assertEqual(set(seen), {"上月各店", "店員的"})
        self.assertEqual((seen["上月各店"]["mine"], seen["上月各店"]["editable"]), (False, False))
        self.assertEqual(self.c.clerk.patch(f"{self.URL}{mine['id']}/", {"name": "偷改"},
                                            format="json").status_code, 403)
        self.assertEqual(self.c.clerk.delete(f"{self.URL}{mine['id']}/").status_code, 403)
        self.assertEqual(SavedReport.objects.get(pk=mine["id"]).name, "上月各店")
        # 同名不同人可以並存
        self.assertEqual(self.save(self.c.clerk).status_code, 201)

    def test_other_company_cannot_see_or_touch(self):
        mine = self.save(shared=True).json()
        self.assertEqual(self.names(self.b.admin), [])
        self.assertEqual(self.b.admin.patch(f"{self.URL}{mine['id']}/", {"name": "x"},
                                            format="json").status_code, 404)
        self.assertEqual(self.b.admin.delete(f"{self.URL}{mine['id']}/").status_code, 404)
        self.assertTrue(SavedReport.objects.filter(pk=mine["id"], name="上月各店").exists())

    def test_filters_are_kept_by_code_not_by_row_number(self):
        spec = {**self.SPEC, "filters": {
            "warehouse": [self.wh2.id], "product": [self.c.case.id, self.c.phone.id],
            "sales_person": [None, self.c.sales_person.id], "condition": [False],
            "tax_method": ["untaxed"],
        }}
        body = self.save(spec=spec).json()
        self.assertEqual(SavedReport.objects.get(pk=body["id"]).spec["filters"], {
            "warehouse": ["w2"], "product": [self.c.case.sku, self.c.phone.sku],
            "sales_person": [None, "S1"], "condition": [False], "tax_method": ["untaxed"],
        })
        self.assertEqual(body["spec"]["filters"], spec["filters"])       # 打開時是現在的編號
        shown = {f["dimension"]: f["values"] for f in body["filters"]}    # 連名稱一起給畫面
        self.assertEqual(shown["warehouse"], [{"value": self.wh2.id, "label": "甲民生店"}])
        self.assertEqual(shown["sales_person"], [
            {"value": self.c.sales_person.id, "label": "甲店員"},
            {"value": None, "label": "未指定 / 未對照"}])
        self.assertEqual(shown["condition"], [{"value": False, "label": "新品"}])
        self.assertEqual(self.c.admin.get(self.URL).json()["results"][0]["spec"]["filters"],
                         spec["filters"])

    def test_deleted_filter_target_is_said_out_loud(self):
        spare = Warehouse.objects.create(tenant=self.t, code="w9", name="甲快閃店")
        cat = Category.objects.create(tenant=self.t, code="ZZ", name="甲暫時品類")
        body = self.save(spec={**self.SPEC, "filters": {
            "warehouse": [spare.id, self.wh1.id], "category": [cat.id]}}).json()
        spare.delete()
        cat.delete()
        opened = self.c.admin.get(self.URL).json()["results"][0]
        self.assertEqual(opened["id"], body["id"])
        self.assertEqual(opened["missing"], ["門市", "品類"])
        self.assertEqual(opened["spec"]["filters"], {"warehouse": [self.wh1.id]})
        self.assertEqual(opened["error"], "")

    def test_payment_method_deleted_later(self):
        """用過的付款方式刪掉:報表照常打開;沒用過就刪掉的:拿掉那個值並講出來。"""
        for code, name in (("card", "信用卡"), ("gift", "禮券")):
            PaymentMethod.objects.create(tenant=self.t, code=code, name=name, kind="non_cash")
        SalesOrderPayment.objects.filter(so_id=self.c.s2["id"]).update(method="card")
        body = self.save(spec={"measures": ["received"], "period": {"preset": "last_month"},
                               "filters": {"payment_method": ["card", "gift"]}}).json()
        self.assertEqual((body["error"], body["missing"]), ("", []))
        PaymentMethod.objects.filter(tenant=self.t, code__in=["card", "gift"]).delete()
        opened = self.c.admin.get(self.URL).json()["results"][0]
        self.assertEqual(opened["id"], body["id"])
        self.assertEqual((opened["error"], opened["missing"]), ("", ["付款方式"]))
        self.assertEqual(opened["spec"]["filters"], {"payment_method": ["card"]})
        self.assertEqual(opened["filters"][0]["values"], [{"value": "card", "label": "card(已刪除)"}])
        # 條件裡的代碼全部都沒有了:整個條件拿掉,一樣講出來
        only = self.save(name="只有禮券", spec={
            "measures": ["received"], "period": {"preset": "last_month"},
            "filters": {"payment_method": ["cash"]}}).json()
        row = SavedReport.objects.get(pk=only["id"])
        row.spec = {**row.spec, "filters": {"payment_method": ["gift"]}}
        row.save()
        opened = {r["name"]: r for r in self.c.admin.get(self.URL).json()["results"]}["只有禮券"]
        self.assertEqual((opened["error"], opened["missing"], opened["spec"]["filters"]),
                         ("", ["付款方式"], {}))

    def test_spec_that_no_longer_fits_the_definitions(self):
        body = self.save().json()
        SavedReport.objects.filter(pk=body["id"]).update(
            spec={**SavedReport.objects.get(pk=body["id"]).spec, "measures": ["gone_measure"]})
        opened = self.c.admin.get(self.URL).json()["results"][0]
        self.assertEqual(opened["error"], "沒有「gone_measure」這個指標")
        # 條件用到的角度後來被拿掉:講出來,其他照常
        good = self.save(name="角度沒了").json()
        row = SavedReport.objects.get(pk=good["id"])
        row.spec = {**row.spec, "filters": {"old_angle": ["x"]}}
        row.save()
        opened = {r["name"]: r for r in self.c.admin.get(self.URL).json()["results"]}["角度沒了"]
        self.assertEqual((opened["missing"], opened["error"], opened["spec"]["filters"]),
                         (["old_angle(已停用的條件)"], "", {}))

    def test_shared_report_follows_the_current_role_not_who_made_it(self):
        from apps.tenants.models import UserProfile

        body = self.save(shared=True).json()
        UserProfile.objects.filter(user=self.c.admin_user).update(role="tenant_user")
        former = Company.client(type(self.c.admin_user).objects.get(pk=self.c.admin_user.pk))
        seen = former.get(self.URL).json()["results"][0]
        self.assertEqual((seen["mine"], seen["editable"]), (True, False))
        self.assertEqual(former.patch(f"{self.URL}{body['id']}/", {"name": "改名"},
                                      format="json").status_code, 403)
        self.assertEqual(former.delete(f"{self.URL}{body['id']}/").status_code, 403)
        self.assertTrue(SavedReport.objects.filter(pk=body["id"], name="上月各店").exists())

    def test_one_broken_report_does_not_take_down_the_list(self):
        good = self.save(name="好的").json()
        today = {"measures": ["net_sales"], "period": {"preset": "today"}}
        # filters 有寫但不是物件(連空清單、0、空字串、False、空值)都算壞,不可以當成「沒有條件」
        broken = [{**today, "filters": f} for f in (
            {"warehouse": 1}, {"warehouse": "w1"}, {"warehouse": [5]}, ["warehouse"],
            {"condition": "yes"}, {"warehouse": []}, {"tax_method": [3]}, {"tax_method": [None]},
            {"old_angle": []}, {"old_angle": 0},      # 角度已經停用,值的形狀不對一樣算壞
            [], 0, "", False, None,
        )] + ["不是查詢單", [1, 2]]
        for n, spec in enumerate(broken):
            SavedReport.objects.create(tenant=self.t, owner=self.c.admin_user, name=f"壞{n}", spec=spec)
        r = self.c.admin.get(self.URL)
        self.assertEqual(r.status_code, 200, r.content)
        seen = {x["name"]: x for x in r.json()["results"]}
        self.assertEqual(len(seen), len(broken) + 1)
        self.assertEqual(seen["好的"]["error"], "")
        for n in range(len(broken)):
            self.assertEqual(seen[f"壞{n}"]["error"], saved.BROKEN, broken[n])
            self.assertEqual(seen[f"壞{n}"]["filters"], [])
        # 沒有 filters 這一欄的不算壞(就是沒有條件)
        SavedReport.objects.create(tenant=self.t, owner=self.c.admin_user, name="沒有條件", spec=today)
        plain = {x["name"]: x for x in self.c.admin.get(self.URL).json()["results"]}["沒有條件"]
        self.assertEqual((plain["error"], plain["missing"], plain["spec"]["filters"]), ("", [], {}))
        # 壞的還是刪得掉
        self.assertEqual(self.c.admin.delete(f"{self.URL}{seen['壞0']['id']}/").status_code, 204)
        self.assertEqual(good["error"], "")

    def test_admin_can_clean_up_reports_whose_owner_is_gone(self):
        body = self.save(self.c.clerk, name="離職店員的").json()
        SavedReport.objects.filter(pk=body["id"]).update(owner=None)
        self.assertEqual(self.names(self.c.clerk), [])
        self.assertEqual(self.names(self.c.admin), ["離職店員的"])
        self.assertEqual(self.names(self.b.admin), [])
        self.assertEqual(self.c.admin.delete(f"{self.URL}{body['id']}/").status_code, 204)

    def test_cap_per_person(self):
        with mock.patch.object(saved, "MAX_PER_USER", 2):
            self.assertEqual(self.save(name="1").status_code, 201)
            self.assertEqual(self.save(name="2").status_code, 201)
            r = self.save(name="3")
            self.assertEqual(r.status_code, 400)
            self.assertIn("存太多了", r.json()["detail"])
            self.assertEqual(self.save(self.c.clerk, name="3").status_code, 201)


class SavedReportBackupTests(BackupBase):
    """還原之後每一列都換了新編號;存起來的報表條件要跟著指到同一家店、同一個人。"""

    def test_saved_report_survives_restore(self):
        a = self.a
        wh1 = a.wh
        r = a.clerk.post("/api/v1/analytics/reports/", {"name": "湳雅店皮套", "spec": {
            "measures": ["sales_untaxed"], "period": {"from": "2020-01-01", "to": "2030-01-01"},
            "filters": {"warehouse": [wh1.id], "product": [a.case.id]},
        }}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        before = a.admin.post("/api/v1/analytics/query/", r.json()["spec"], format="json").json()
        self.assertEqual(before["totals"], {"sales_untaxed": "780.00"})
        job = self.backup(a)
        SavedReport.objects.filter(tenant=a.tenant).delete()
        done = self.rollback(a, self.path(job))
        self.assertEqual(done.status, "done", done.error)
        a.reload()
        self.assertNotEqual(a.wh.id, wh1.id)
        opened = a.clerk.get("/api/v1/analytics/reports/").json()["results"]
        self.assertEqual(len(opened), 1)
        self.assertEqual((opened[0]["mine"], opened[0]["missing"], opened[0]["error"]), (True, [], ""))
        self.assertEqual(opened[0]["spec"]["filters"],
                         {"warehouse": [a.wh.id], "product": [a.case.id]})
        after = a.admin.post("/api/v1/analytics/query/", opened[0]["spec"], format="json").json()
        self.assertEqual(after["totals"], before["totals"])
        self.assertEqual(a.admin.get("/api/v1/analytics/reports/").json()["results"], [])
