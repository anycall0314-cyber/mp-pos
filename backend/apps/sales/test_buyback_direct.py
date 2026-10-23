"""個人收購的來源是直客,不再自動建一筆「個人」來源(全站檢視 E1;owner 2026-10-23「好」)。"""
from datetime import date

from django.test import TestCase

from apps.backup.tests.factory import Company
from apps.catalog.models import Product
from apps.parties.models import Customer, Member
from apps.sales.models import SalesOrder
from apps.sales.services import acquire_secondhand_from_member


class BuybackDirectSourceTests(TestCase):
    def setUp(self):
        self.c = Company("a", "甲通訊行", "甲")
        self.used = Product.objects.create(
            tenant=self.c.tenant, category=self.c.cat_phone, name="甲 中古 iPhone 13",
            is_secondhand=True, list_price=12000,
        )
        self.member = Member.objects.create(tenant=self.c.tenant, name="王小明", phone="0911222333")

    def buy(self, imei):
        _, so = acquire_secondhand_from_member(
            tenant=self.c.tenant, member=self.member, warehouse=self.c.wh, secondhand_product=self.used,
            imei=imei, condition_grade="A", custom_unit_price=None, acquisition_price="1000",
            payment_method_code="cash",
        )
        return SalesOrder.objects.get(pk=so.pk)

    def test_the_buyback_is_direct_and_no_individual_source_is_made(self):
        before = Customer.objects.filter(tenant=self.c.tenant).count()
        so = self.buy("356938035643809")
        self.assertEqual((so.customer_id, so.source_name, so.member_id), (None, "直客", self.member.id))
        self.buy("356938035643817")                       # 同一個人再賣一台,一樣不建
        self.assertEqual(Customer.objects.filter(tenant=self.c.tenant).count(), before)
        self.assertFalse(Customer.objects.filter(tenant=self.c.tenant, kind="individual", phone="0911222333").exists())

    def test_buybacks_stay_out_of_the_sales_figures_of_the_direct_source(self):
        # 紅隊:收購記在直客底下,不能把「直客」的銷售額變少 —— 銷售類指標只算計入毛利的明細,收購另外一欄
        self.c.purchase(case_qty=1)
        self.c.sell(case_qty=1)
        self.buy("356938035643809")
        r = self.c.admin.post("/api/v1/analytics/query/", {
            "measures": ["sales_gross", "non_margin_amount"], "dimensions": ["customer"],
            "period": {"from": str(date.today()), "to": str(date.today())},
        }, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        data = r.json()
        self.assertEqual(int(float(data["totals"]["sales_gross"])), 390)            # 收購不算進銷售額
        self.assertEqual(int(float(data["totals"]["non_margin_amount"])), -1000)     # 收購另外一欄

    def test_the_daily_report_names_the_seller_of_a_buyback(self):
        # 來源都是直客了,營業日報「收購現金支出」那一列要看得到是誰賣的
        self.buy("356938035643809")
        r = self.c.admin.get(f"/api/v1/reports/business-daily/?warehouse={self.c.wh.id}&date={date.today().isoformat()}")
        self.assertEqual(r.status_code, 200, r.content.decode())
        row = r.json()["buybacks"]["rows"][0]
        self.assertEqual((row["member_name"], row["customer_name"]), ("王小明", "直客"))
