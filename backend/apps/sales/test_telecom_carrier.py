"""門號商品只能選自己那家電信的方案(owner 2026-10-19:「TCC ,CHM,FET 這三個品號不管是誰，選的資費只能是
設定好的該電信所屬資費，不能打台哥大跳出遠傳讓你選」)。管理員也一樣;伺服器擋,不是只有畫面。"""
from decimal import Decimal

from django.test import TestCase

from apps.backup.tests.factory import Company
from apps.catalog.models import Product
from apps.parties.models import Carrier, TelecomPlan

from .models import SalesOrderItem

SALES = "/api/v1/sales-orders/"
PRODUCTS = "/api/v1/products/"


class _Shop(TestCase):
    def setUp(self):
        self.c = Company("a", "甲通訊行", "甲")
        t = self.c.tenant
        self.twm = Carrier.objects.create(tenant=t, code="TWM", name="台灣大哥大")
        self.fet = Carrier.objects.create(tenant=t, code="FET", name="遠傳電信")
        self.twm_plan = TelecomPlan.objects.create(
            tenant=t, carrier=self.twm, name="台哥大 1399 續約", monthly_fee=1399, contract_months=30,
            kind="renewal", commission=Decimal("6000"))
        self.fet_plan = TelecomPlan.objects.create(
            tenant=t, carrier=self.fet, name="遠傳 1399 續約", monthly_fee=1399, contract_months=30,
            kind="renewal", commission=Decimal("7000"))
        self.tcc = Product.objects.create(
            tenant=t, category=self.c.cat_case, name="台哥大續約", is_virtual=True, requires_serial=False,
            allows_telecom_line=True, allows_commission=True, telecom_carrier=self.twm)

    def sell(self, product, plan, client=None):
        return (client or self.c.clerk).post(SALES, {
            "customer": self.c.customer.id, "warehouse": self.c.wh.id, "tax_method": "untaxed",
            "doc_date": "2026-10-19", "payments": [],
            "items": [{"product": product.id, "qty": 1, "unit_price": "0", "msisdn": "0912345678",
                       "telecom_plan": plan.id}],
        }, format="json")


class SellTests(_Shop):
    def test_its_own_carrier_goes_through(self):
        r = self.sell(self.tcc, self.twm_plan)
        self.assertEqual(r.status_code, 201, r.content.decode())
        self.assertEqual(SalesOrderItem.objects.get(so_id=r.json()["id"]).commission, Decimal("6000"))

    def test_another_carriers_plan_is_refused_for_everyone(self):
        for who in (self.c.clerk, self.c.admin):
            r = self.sell(self.tcc, self.fet_plan, who)
            self.assertEqual(r.status_code, 400)
            self.assertIn("只能選 台灣大哥大 的方案", r.content.decode())
        self.assertFalse(SalesOrderItem.objects.exists())

    def test_a_phone_number_product_without_a_carrier_cannot_be_sold(self):
        Product.objects.filter(pk=self.tcc.pk).update(telecom_carrier=None)   # 以前建的門號商品
        r = self.sell(self.tcc, self.twm_plan)
        self.assertEqual(r.status_code, 400)
        self.assertIn("還沒設定電信商", r.content.decode())


class ProductFormTests(_Shop):
    def make(self, **body):
        base = {"category": self.c.cat_case.id, "name": "遠傳新辦攜碼", "is_virtual": True,
                "requires_serial": False, "allows_telecom_line": True}
        return self.c.admin.post(PRODUCTS, {**base, **body}, format="json")

    def test_a_phone_number_product_needs_a_carrier(self):
        r = self.make()
        self.assertEqual(r.status_code, 400)
        self.assertIn("門號商品要選電信商", r.content.decode())
        r = self.make(telecom_carrier=self.fet.id)
        self.assertEqual(r.status_code, 201, r.content.decode())
        self.assertEqual((r.json()["telecom_carrier"], r.json()["telecom_carrier_name"]), (self.fet.id, "遠傳電信"))

    def test_another_companys_carrier_is_not_accepted(self):
        b = Company("b", "乙通訊行", "乙")
        theirs = Carrier.objects.create(tenant=b.tenant, code="FET", name="遠傳電信")
        r = self.make(telecom_carrier=theirs.id)
        self.assertEqual(r.status_code, 400)
        self.assertFalse(Product.objects.filter(tenant=self.c.tenant, name="遠傳新辦攜碼").exists())

    def test_turning_off_phone_numbers_drops_the_carrier(self):
        r = self.c.admin.patch(f"{PRODUCTS}{self.tcc.id}/", {"allows_telecom_line": False}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.tcc.refresh_from_db()
        self.assertIsNone(self.tcc.telecom_carrier_id)

    def test_editing_something_else_on_an_old_product_is_not_blocked(self):
        Product.objects.filter(pk=self.tcc.pk).update(telecom_carrier=None)
        r = self.c.admin.patch(f"{PRODUCTS}{self.tcc.id}/", {"list_price": "100"}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())

    def test_plans_can_be_listed_for_one_carrier(self):
        rows = self.c.clerk.get("/api/v1/telecom-plans/", {"carrier": self.twm.id}).json()
        rows = rows["results"] if isinstance(rows, dict) else rows
        self.assertEqual([p["name"] for p in rows], ["台哥大 1399 續約"])
