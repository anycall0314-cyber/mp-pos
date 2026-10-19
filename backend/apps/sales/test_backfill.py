"""手機回補:銷貨單多打一行回補品號,這一行客人不用付、只算毛利(owner 2026-10-19:「計毛利目前用在手機回補」;
選「多打一行」、「也算進獎金」、「只進毛利」)。

商品勾掉「計入現金」= 那一行不算進單的總額 / 稅 / 付款 / 營業日報現金,不算銷售額;算進毛利與業務員毛利。
"""
from decimal import Decimal as D

from django.test import TestCase
from django.utils import timezone

from apps.backup.tests.factory import Company
from apps.catalog.models import Product
from apps.ledger.checks import check_sales_orders, check_sales_returns

from .models import SalesOrder, SalesOrderItem

SALES = "/api/v1/sales-orders/"
QUERY = "/api/v1/analytics/query/"


class BackfillTests(TestCase):
    def setUp(self):
        self.c = Company("a", "甲通訊行", "甲")
        self.c.purchase(case_qty=5)                                  # 皮套成本 100
        self.backfill = Product.objects.create(
            tenant=self.c.tenant, category=self.c.cat_case, name="手機回補", is_virtual=True,
            requires_serial=False, counts_cash=False, counts_margin=True)

    def sell(self, paid, backfill="1000", tax_method="untaxed", expect=201):
        r = self.c.clerk.post(SALES, {
            "customer": self.c.customer.id, "warehouse": self.c.wh.id, "tax_method": tax_method,
            "sales_person": self.c.sales_person.id,
            "items": [{"product": self.c.case.id, "qty": 1, "unit_price": "390"},
                      {"product": self.backfill.id, "qty": 1, "unit_price": backfill}],
            "payments": [{"method": "cash", "amount": str(paid)}],
        }, format="json")
        self.assertEqual(r.status_code, expect, r.content.decode())
        return r.json()

    def ask(self, *measures):
        today = timezone.localdate().isoformat()
        r = self.c.admin.post(QUERY, {"measures": list(measures), "dimensions": [],
                                      "period": {"from": today, "to": today}}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        return {k: D(str(v)) for k, v in r.json()["totals"].items()}

    def test_the_customer_only_pays_for_the_goods(self):
        so = self.sell(390)
        o = SalesOrder.objects.get(pk=so["id"])
        self.assertEqual((o.subtotal, o.tax_amount, o.total), (D("390"), D("0"), D("390")))
        line = SalesOrderItem.objects.get(so=o, product=self.backfill)
        self.assertEqual((line.counts_cash, line.amount, line.untaxed_amount, line.tax_amount),
                         (False, D("1000"), D("1000"), D("0")))
        self.assertIn("不一致", str(self.sell(1390, expect=400)))     # 回補不能叫客人付

    def test_tax_is_only_on_what_the_customer_pays(self):
        o = SalesOrder.objects.get(pk=self.sell(410, tax_method="taxable_excluded")["id"])   # 390 外加 5%
        self.assertEqual((o.subtotal, o.tax_amount, o.total), (D("390"), D("20"), D("410")))
        line = SalesOrderItem.objects.get(so=o, product=self.backfill)
        self.assertEqual((line.untaxed_amount, line.tax_amount), (D("1000"), D("0")))

    def test_not_sales_but_counted_in_both_margins(self):
        self.sell(390)
        got = self.ask("sales_untaxed", "sales_cost", "backfill", "sales_profit", "staff_profit", "gross_profit")
        self.assertEqual(got["sales_untaxed"], D("390"))            # 銷售額不含回補
        self.assertEqual(got["backfill"], D("1000"))
        self.assertEqual(got["sales_profit"], D("390") - D("100") + D("1000"))
        self.assertEqual(got["staff_profit"], D("1290"))            # 業務員毛利也含回補(沒設業務員成本 = 實際成本)
        self.assertEqual(got["gross_profit"], D("1290"))

    def test_the_cash_report_and_the_nightly_checks_agree(self):
        self.sell(390)
        r = self.c.admin.get("/api/v1/reports/business-daily/",
                             {"warehouse": self.c.wh.id, "date": timezone.localdate().isoformat()})
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.assertEqual(D(str(r.json()["sales"]["total"])), D("390"))
        self.assertTrue(all(c["ok"] for c in check_sales_orders(self.c.tenant)))

    def test_a_whole_return_takes_the_backfill_back(self):
        so = self.sell(390)
        r = self.c.admin.post("/api/v1/sales-returns/", {"original_so": so["id"], "payment_method": "cash"},
                              format="json")
        self.assertEqual(r.status_code, 201, r.content.decode())
        self.assertEqual(D(str(r.json()["total"])), D("390"))        # 退給客人的只有他付的
        got = self.ask("backfill", "return_backfill", "gross_profit", "staff_gross_profit")
        self.assertEqual((got["return_backfill"], got["gross_profit"], got["staff_gross_profit"]),
                         (D("1000"), D("0"), D("0")))
        self.assertTrue(all(c["ok"] for c in check_sales_returns(self.c.tenant)))

    def test_only_a_virtual_product_can_skip_payment(self):
        Product.objects.filter(pk=self.c.case.pk).update(counts_cash=False)
        r = self.c.clerk.post(SALES, {
            "customer": self.c.customer.id, "warehouse": self.c.wh.id, "tax_method": "untaxed",
            "items": [{"product": self.c.case.id, "qty": 1, "unit_price": "390"}], "payments": [],
        }, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("只能是虛擬商品", r.content.decode())
