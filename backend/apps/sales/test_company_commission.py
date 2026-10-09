"""門號的兩個佣金:業務員佣金(門市看的)與公司佣金(公司實際拿的,只有管理員看得到)。

owner 2026-10-09:每個方案各填兩個數字;現有的數字「已經是給門市看的」,所以照舊當業務員佣金,公司佣金先空著。
"""
from decimal import Decimal

from django.test import TestCase

from apps.backup.tests.factory import Company
from apps.catalog.models import Product
from apps.parties.models import Carrier, SimCard, TelecomPlan

from .models import SalesOrderItem

PLANS = "/api/v1/telecom-plans/"
SALES = "/api/v1/sales-orders/"
QUERY = "/api/v1/analytics/query/"


class _Shop(TestCase):
    def setUp(self):
        self.c = Company("a", "甲通訊行", "甲")
        self.t = self.c.tenant
        self.carrier = Carrier.objects.create(tenant=self.t, code="CHT", name="中華電信")
        self.plan = TelecomPlan.objects.create(
            tenant=self.t, carrier=self.carrier, name="1399 30月", monthly_fee=1399, contract_months=30,
            kind="renewal", commission=Decimal("6000"), company_commission=Decimal("10000.50"),
        )
        self.old = TelecomPlan.objects.create(           # 還沒設定公司佣金的方案(2026-10-09 之前的都是這樣)
            tenant=self.t, carrier=self.carrier, name="599 24月", monthly_fee=599, contract_months=24,
            kind="renewal", commission=Decimal("3000"),
        )
        Product.objects.filter(pk=self.c.case.pk).update(allows_telecom_line=True, allows_commission=True)
        self.c.purchase(case_qty=9)

    def sell(self, plan, client=None, **line):
        r = (client or self.c.clerk).post(SALES, {
            "customer": self.c.customer.id, "warehouse": self.c.wh.id, "tax_method": "untaxed",
            "doc_date": "2026-10-09", "payments": [],
            "items": [{"product": self.c.case.id, "qty": 1, "unit_price": "0", "msisdn": "0912345678",
                       "telecom_plan": plan.id, **line}],
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content.decode())
        return r.json()

    def rows(self, r):
        return r.json()["results"] if isinstance(r.json(), dict) else r.json()


class PlanTests(_Shop):
    def test_a_clerk_never_receives_the_company_commission(self):
        for r in (self.c.clerk.get(PLANS), self.c.clerk.get(PLANS, {"search": "1399"})):
            self.assertEqual(r.status_code, 200)
            for row in self.rows(r):
                self.assertNotIn("company_commission", row)
                self.assertIn("commission", row)
        one = self.c.clerk.get(f"{PLANS}{self.plan.id}/").json()
        self.assertNotIn("company_commission", one)
        self.assertEqual(Decimal(one["commission"]), Decimal("6000"))
        self.assertNotIn("10000", self.c.clerk.get(PLANS).content.decode())

    def test_a_manager_sees_both_and_empty_means_not_set(self):
        got = {row["name"]: row for row in self.rows(self.c.admin.get(PLANS))}
        self.assertEqual(Decimal(got["1399 30月"]["company_commission"]), Decimal("10000.50"))
        self.assertEqual(Decimal(got["1399 30月"]["commission"]), Decimal("6000"))
        self.assertIsNone(got["599 24月"]["company_commission"])

    def test_a_manager_sets_clears_and_cannot_go_negative(self):
        one = f"{PLANS}{self.old.id}/"
        r = self.c.admin.patch(one, {"company_commission": "5200"}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.old.refresh_from_db()
        self.assertEqual((self.old.company_commission, self.old.commission), (Decimal("5200"), Decimal("3000")))
        r = self.c.admin.patch(one, {"company_commission": "0"}, format="json")       # 明講 0 是 0
        self.old.refresh_from_db()
        self.assertEqual(self.old.company_commission, Decimal("0"))
        r = self.c.admin.patch(one, {"company_commission": None}, format="json")      # 清掉 = 回到未設定
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.old.refresh_from_db()
        self.assertIsNone(self.old.company_commission)
        r = self.c.admin.patch(one, {"company_commission": "-1"}, format="json")
        self.assertEqual(r.status_code, 400, r.content.decode())
        self.old.refresh_from_db()
        self.assertEqual((self.old.company_commission, self.old.commission), (None, Decimal("3000")))

    def test_the_staff_commission_is_validated_exactly_as_before(self):
        """業務員佣金原本沒有另外的限制(複審指出:這次不該順手加)。只改備註、連同原本的值一起送回來,照舊存得進去。"""
        TelecomPlan.objects.filter(pk=self.old.pk).update(commission=Decimal("-100"))
        r = self.c.admin.patch(f"{PLANS}{self.old.id}/", {"commission": "-100", "note": "更新備註"}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.old.refresh_from_db()
        self.assertEqual((self.old.commission, self.old.note), (Decimal("-100"), "更新備註"))

    def test_creating_a_plan_with_or_without_it(self):
        body = {"carrier": self.carrier.id, "name": "999 24月", "monthly_fee": 999, "contract_months": 24,
                "kind": "new", "commission": "4000"}
        r = self.c.admin.post(PLANS, body, format="json")
        self.assertEqual(r.status_code, 201, r.content.decode())
        self.assertIsNone(TelecomPlan.objects.get(name="999 24月").company_commission)
        r = self.c.admin.post(PLANS, {**body, "name": "1199 24月", "company_commission": "9000"}, format="json")
        self.assertEqual(r.status_code, 201, r.content.decode())
        self.assertEqual(TelecomPlan.objects.get(name="1199 24月").company_commission, Decimal("9000"))
        r = self.c.admin.post(f"{PLANS}bulk/", {
            "common": {"carrier": self.carrier.id, "kind": "new"},
            "items": [{"name": "批次 A", "monthly_fee": "599", "contract_months": "24",
                       "commission": "3000", "company_commission": "4500"}],
        }, format="json")
        self.assertIn(r.status_code, (200, 201), r.content.decode())
        self.assertEqual(TelecomPlan.objects.get(name="批次 A").company_commission, Decimal("4500"))
        self.assertIn("4500", r.content.decode())            # 管理員自己建的,回應裡看得到


class SaleTests(_Shop):
    def test_both_numbers_are_written_on_the_sale_line(self):
        """店員開的單一樣兩個都記;公司佣金收成整數元(金額一律整數)。"""
        doc = self.sell(self.plan)
        line = SalesOrderItem.objects.get(so_id=doc["id"])
        self.assertEqual((line.commission, line.company_commission), (Decimal("6000"), Decimal("10001")))

    def test_a_plan_without_it_leaves_the_line_empty_not_zero(self):
        doc = self.sell(self.old)
        line = SalesOrderItem.objects.get(so_id=doc["id"])
        self.assertEqual((line.commission, line.company_commission), (Decimal("3000"), None))

    def test_changing_the_plan_later_does_not_touch_the_sale(self):
        doc = self.sell(self.plan)
        TelecomPlan.objects.filter(pk=self.plan.pk).update(commission=1, company_commission=2)
        line = SalesOrderItem.objects.get(so_id=doc["id"])
        self.assertEqual((line.commission, line.company_commission), (Decimal("6000"), Decimal("10001")))
        self.assertEqual(Decimal(self.c.admin.get(f"{SALES}{doc['id']}/").json()["items"][0]["company_commission"]),
                         Decimal("10001"))

    def test_what_the_client_sends_does_not_count(self):
        """兩個佣金都以方案為準:單上送來的不算(店員不能在單上自己填)。"""
        doc = self.sell(self.plan, commission="1", company_commission="2")
        line = SalesOrderItem.objects.get(so_id=doc["id"])
        self.assertEqual((line.commission, line.company_commission), (Decimal("6000"), Decimal("10001")))
        doc = self.sell(self.old, client=self.c.admin, company_commission="7777")
        self.assertIsNone(SalesOrderItem.objects.get(so_id=doc["id"]).company_commission)

    def test_a_clerk_never_receives_it_on_a_sale(self):
        doc = self.sell(self.plan)
        self.assertNotIn("company_commission", doc["items"][0])            # 建單的回應
        for r in (self.c.clerk.get(f"{SALES}{doc['id']}/"), self.c.clerk.get(SALES)):
            self.assertEqual(r.status_code, 200)
            self.assertNotIn("company_commission", r.content.decode())
            self.assertNotIn("10001", r.content.decode())
        seen = self.c.admin.get(f"{SALES}{doc['id']}/").json()["items"][0]
        self.assertEqual((Decimal(seen["commission"]), Decimal(seen["company_commission"])),
                         (Decimal("6000"), Decimal("10001")))

    def test_a_line_without_a_plan_has_neither(self):
        r = self.c.admin.post(SALES, {
            "customer": self.c.customer.id, "warehouse": self.c.wh.id, "tax_method": "untaxed",
            "doc_date": "2026-10-09", "payments": [{"method": self.c.cash.id, "amount": "390"}],
            # 沒有方案的那一行就算送了公司佣金(管理員送的也一樣)也不收:這個數字只從方案來
            "items": [{"product": self.c.case.id, "qty": 1, "unit_price": "390", "company_commission": "999"}],
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content.decode())
        line = SalesOrderItem.objects.get(so_id=r.json()["id"])
        self.assertEqual((line.commission, line.company_commission), (Decimal("0"), None))


class WithoutARequestTests(_Shop):
    def test_code_that_serializes_without_a_request_gets_the_safe_version(self):
        """程式內部自己轉資料、沒有帶「是誰在看」的時候,一律當成不是管理員(寧可少給)。"""
        from apps.parties.serializers import TelecomPlanSerializer

        from .serializers import SalesOrderItemSerializer

        self.assertNotIn("company_commission", TelecomPlanSerializer(self.plan).data)
        doc = self.sell(self.plan)
        line = SalesOrderItem.objects.get(so_id=doc["id"])
        data = SalesOrderItemSerializer(line).data
        self.assertNotIn("company_commission", data)
        self.assertIn("commission", data)


class ReportTests(_Shop):
    def setUp(self):
        super().setUp()
        self.sell(self.plan)
        self.sell(self.plan)
        self.sell(self.old)

    def ask(self, client, *measures):
        return client.post(QUERY, {"measures": list(measures), "dimensions": [],
                                   "period": {"from": "2026-10-01", "to": "2026-10-31"}}, format="json")

    def total(self, r, key):
        body = r.json()
        return Decimal(str(body["totals"][key]))

    def test_the_menu_only_offers_it_to_managers(self):
        def keys(client):
            return {m["key"] for m in client.get("/api/v1/analytics/catalog/").json()["measures"]}

        self.assertIn("staff_commission", keys(self.c.clerk))
        self.assertNotIn("company_commission", keys(self.c.clerk))
        self.assertLessEqual({"staff_commission", "company_commission"}, keys(self.c.admin))

    def test_a_clerk_cannot_query_it(self):
        r = self.ask(self.c.clerk, "company_commission")
        self.assertEqual(r.status_code, 400, r.content.decode())
        self.assertIn("沒有權限", r.json()["detail"])
        self.assertNotIn("20002", r.content.decode())
        self.assertEqual(self.ask(self.c.clerk, "staff_commission", "company_commission").status_code, 400)
        r = self.ask(self.c.clerk, "staff_commission")
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.assertEqual(self.total(r, "staff_commission"), Decimal("15000"))

    def test_a_manager_gets_both_totals(self):
        r = self.ask(self.c.admin, "staff_commission", "company_commission")
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.assertEqual(self.total(r, "staff_commission"), Decimal("15000"))       # 6000 + 6000 + 3000
        self.assertEqual(self.total(r, "company_commission"), Decimal("20002"))     # 10001 × 2;沒設定的那一筆不算

    def test_a_number_calculated_from_it_is_also_managers_only(self):
        """之後有人加一個「由公司佣金算出來的」指標、忘了寫誰能看:照樣只有管理員看得到。"""
        from apps.analytics import catalog

        made = catalog.Derived("commission_gap_test", "佣金差額(測試用)", ("company_commission", "staff_commission"),
                               lambda v: v["company_commission"] - v["staff_commission"])
        catalog.MEASURES[made.key] = made
        self.addCleanup(catalog.MEASURES.pop, made.key, None)
        self.assertFalse(catalog.may_see(made.key, "tenant_user"))
        self.assertTrue(catalog.may_see(made.key, "tenant_admin"))
        self.assertTrue(catalog.may_see("staff_commission", "tenant_user"))
        self.assertEqual(self.ask(self.c.clerk, made.key).status_code, 400)
        clerk_menu = {m["key"] for m in self.c.clerk.get("/api/v1/analytics/catalog/").json()["measures"]}
        self.assertNotIn(made.key, clerk_menu)

    def test_a_calculated_number_can_carry_its_own_limit(self):
        """算它用到的都是誰都能看的,但這個指標自己寫了只給管理員:照它自己的。"""
        from apps.analytics import catalog

        made = catalog.Derived("double_staff_test", "兩倍業務員佣金(測試用)", ("staff_commission",),
                               lambda v: v["staff_commission"] * 2, roles=catalog.MANAGERS)
        catalog.MEASURES[made.key] = made
        self.addCleanup(catalog.MEASURES.pop, made.key, None)
        self.assertFalse(catalog.may_see(made.key, "tenant_user"))
        self.assertFalse(catalog.may_see(made.key, None))
        self.assertTrue(catalog.may_see(made.key, "platform_admin"))
        self.assertEqual(self.ask(self.c.clerk, made.key).status_code, 400)
        self.assertEqual(self.ask(self.c.admin, made.key).status_code, 200)
