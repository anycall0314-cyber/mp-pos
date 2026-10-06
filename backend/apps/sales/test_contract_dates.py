"""門號合約的日期:續約記原合約到期日、攜碼記生效日、新辦當天生效;合約到期日存檔當下算好。

到期日是之後「合約快到期」統計與提醒的依據,算錯會提醒錯人、或該提醒的沒提醒。
"""
from datetime import date
from decimal import Decimal
from importlib import import_module

from django.apps import apps as django_apps
from django.test import SimpleTestCase, TestCase

from apps.backup.tests.factory import Company
from apps.catalog.models import Product
from apps.core.dates import add_months
from apps.parties.models import Carrier, SimCard, TelecomPlan
from apps.sales.models import SalesOrder, SalesOrderItem

D = Decimal


class AddMonthsTests(SimpleTestCase):
    def test_same_day_n_months_later(self):
        self.assertEqual(add_months(date(2026, 10, 6), 24), date(2028, 10, 6))
        self.assertEqual(add_months(date(2026, 10, 6), 30), date(2029, 4, 6))
        self.assertEqual(add_months(date(2026, 12, 31), 1), date(2027, 1, 31))

    def test_month_without_that_day_lands_on_its_last_day(self):
        self.assertEqual(add_months(date(2027, 1, 31), 1), date(2027, 2, 28))
        self.assertEqual(add_months(date(2026, 8, 31), 30), date(2029, 2, 28))
        self.assertEqual(add_months(date(2026, 2, 28), 24), date(2028, 2, 28))  # 2028 是閏年,仍落在 28


class ContractDateTests(TestCase):
    def setUp(self):
        self.c = Company("a", "甲通訊行", "甲")
        self.carrier = Carrier.objects.create(tenant=self.c.tenant, code="CHT", name="中華電信")
        self.plans = {
            kind: TelecomPlan.objects.create(
                tenant=self.c.tenant, carrier=self.carrier, name=f"599 {kind}",
                monthly_fee=599, contract_months=months, kind=kind,
            )
            for kind, months in (("new", 24), ("portin", 30), ("renewal", 24))
        }
        Product.objects.filter(pk=self.c.case.pk).update(
            allows_telecom_line=True, allows_commission=True)
        self.c.purchase(case_qty=9)
        self.cards = iter(
            SimCard.objects.create(tenant=self.c.tenant, vendor=self.carrier, card_no=f"8988600000{i}")
            for i in range(3)
        )

    def sell(self, kind, expect=201, **line):
        item = {"product": self.c.case.id, "qty": 1, "unit_price": "0",
                "msisdn": "0912345678", "telecom_plan": self.plans[kind].id if kind else None,
                **line}
        if kind in ("new", "portin"):
            item["sim_card"] = next(self.cards).id
        resp = self.c.admin.post("/api/v1/sales-orders/", {
            "customer": self.c.customer.id, "warehouse": self.c.wh.id, "tax_method": "untaxed",
            "doc_date": "2026-10-06", "items": [item], "payments": [],
        }, format="json")
        self.assertEqual(resp.status_code, expect, resp.content)
        return resp.json()

    def line(self, doc):
        return SalesOrderItem.objects.get(so_id=doc["id"])

    def doc_date(self, doc):
        return SalesOrder.objects.get(pk=doc["id"]).doc_date

    def test_new_line_starts_on_the_document_date_whatever_was_sent(self):
        # 新辦當天生效:起算日 = 單據日期(伺服器存檔時決定)。送來的值不算數 ——
        # 半夜前送出沒到、過了半夜原樣重送的那一張,送來的是前一天
        for sent in ("2020-01-01", None):
            with self.subTest(sent=sent):
                extra = {"activation_date": sent} if sent else {}
                doc = self.sell("new", **extra)
                item, day = self.line(doc), self.doc_date(doc)
                self.assertEqual(item.activation_date, day)
                self.assertEqual(item.contract_end, add_months(day, 24))
                self.assertEqual(item.contract_months, 24)
                self.assertEqual(doc["items"][0]["contract_end"], add_months(day, 24).isoformat())

    def test_port_in_counts_from_the_effective_date_the_clerk_entered(self):
        doc = self.sell("portin", activation_date="2026-10-20")
        self.assertEqual(self.line(doc).contract_end, date(2029, 4, 20))

    def test_renewal_counts_from_the_renewal_date_not_the_old_contract(self):
        # 遠傳 / 台哥大:當天續約,續約日 = 開單日
        doc = self.sell("renewal", activation_date="2026-10-06", prev_contract_end="2026-12-31")
        item = self.line(doc)
        self.assertEqual(item.prev_contract_end, date(2026, 12, 31))  # 只是記錄
        self.assertEqual(item.contract_end, date(2028, 10, 6))
        # 中華電信:先入帳,續約日比開單日晚
        doc = self.sell("renewal", activation_date="2026-10-20")
        self.assertEqual(self.line(doc).contract_end, date(2028, 10, 20))

    def test_missing_date_leaves_the_end_date_empty_instead_of_guessing(self):
        doc = self.sell("renewal", prev_contract_end="2026-12-31")
        self.assertIsNone(self.line(doc).contract_end)
        doc = self.sell("portin")
        self.assertIsNone(self.line(doc).contract_end)

    def test_old_contract_end_only_makes_sense_on_a_renewal(self):
        body = self.sell("portin", expect=400, activation_date="2026-10-06",
                         prev_contract_end="2026-12-31")
        self.assertIn("不是續約", str(body))
        body = self.sell(None, expect=400, prev_contract_end="2026-12-31", msisdn="")
        self.assertIn("不是續約", str(body))

    def test_end_date_cannot_be_set_from_outside(self):
        doc = self.sell("renewal", activation_date="2026-10-06", contract_end="2099-01-01")
        self.assertEqual(self.line(doc).contract_end, date(2028, 10, 6))

    def test_contract_keeps_its_own_months_when_the_plan_is_edited_later(self):
        doc = self.sell("renewal", activation_date="2026-10-06")
        self.assertEqual(self.line(doc).contract_months, 24)
        TelecomPlan.objects.filter(pk=self.plans["renewal"].pk).update(contract_months=30)
        self.assertEqual(self.line(doc).contract_end, date(2028, 10, 6))
        # 事後改續約日:到期日用這一張當初的 24 個月重算,不是方案現在的 30 個月
        self.change(doc, activation_date="2026-10-28")
        item = self.line(doc)
        self.assertEqual((item.contract_months, item.contract_end), (24, date(2028, 10, 28)))
        # 方案改了之後才開的單用新的月數
        later = self.sell("renewal", activation_date="2026-10-06")
        self.assertEqual(self.line(later).contract_end, date(2029, 4, 6))

    def test_migration_fills_in_lines_saved_before_the_end_date_existed(self):
        new = self.sell("new")
        renewal = self.sell("renewal", activation_date="2026-10-06")
        undated = self.sell("portin")
        voided = self.sell("renewal", activation_date="2026-10-06")
        self.c.admin.post(f"/api/v1/sales-orders/{voided['id']}/void/")
        SalesOrderItem.objects.update(contract_end=None, contract_months=None)
        import_module("apps.sales.migrations.0017_contract_dates").backfill(django_apps, None)
        self.assertEqual(self.line(new).contract_end, add_months(self.doc_date(new), 24))
        self.assertEqual(self.line(renewal).contract_end, date(2028, 10, 6))
        self.assertEqual(self.line(renewal).contract_months, 24)
        # 沒有起算日的:月數抄下來,到期日留空(不猜)
        self.assertEqual((self.line(undated).contract_months, self.line(undated).contract_end),
                         (30, None))
        self.assertIsNone(self.line(voided).contract_end)  # 作廢的單不補

    def test_voiding_clears_the_end_date_so_reminders_skip_it(self):
        doc = self.sell("renewal", activation_date="2026-10-06")
        self.assertEqual(self.line(doc).contract_end, date(2028, 10, 6))
        self.assertEqual(
            self.c.admin.post(f"/api/v1/sales-orders/{doc['id']}/void/").status_code, 200)
        item = self.line(doc)
        self.assertIsNone(item.contract_end)
        self.assertEqual(item.activation_date, date(2026, 10, 6))  # 起算日留著當紀錄

    def test_a_contract_needs_its_phone_number_whichever_kind_it_is(self):
        # 畫面會擋,伺服器也要擋(別的入口、舊版畫面):沒有門號的合約之後認不出來是誰的
        for kind in ("new", "portin", "renewal"):
            with self.subTest(kind=kind):
                body = self.sell(kind, expect=400, activation_date="2026-10-06", msisdn="  ")
                self.assertIn("門號要填", str(body))
        self.assertEqual(SalesOrderItem.objects.count(), 0)

    def test_the_phone_line_product_cannot_be_sold_without_a_plan(self):
        # 門號商品 = 虛擬、可以填門號。這一行就是在記一份合約:沒有方案不收
        line = Product.objects.create(
            tenant=self.c.tenant, category=self.c.cat_case, name="門號方案",
            is_virtual=True, allows_telecom_line=True, allows_commission=True)

        def sell(expect, **item):
            resp = self.c.admin.post("/api/v1/sales-orders/", {
                "customer": self.c.customer.id, "warehouse": self.c.wh.id, "tax_method": "untaxed",
                "items": [{"product": line.id, "qty": 1, "unit_price": "0", **item}], "payments": [],
            }, format="json")
            self.assertEqual(resp.status_code, expect, resp.content)
            return resp.content.decode()

        self.assertIn("要選方案", sell(400))
        self.assertIn("要選方案", sell(400, msisdn="0912345678"))
        self.assertIn("門號要填", sell(400, telecom_plan=self.plans["renewal"].id))
        sell(201, telecom_plan=self.plans["renewal"].id, msisdn="0912345678",
             activation_date="2026-10-06")
        # 不是門號商品的(手機、配件)照樣可以不帶方案賣
        self.c._post("/api/v1/sales-orders/", {
            "customer": self.c.customer.id, "warehouse": self.c.wh.id, "tax_method": "untaxed",
            "items": [{"product": self.c.case.id, "qty": 1, "unit_price": "0"}], "payments": [],
        })

    def test_a_line_with_a_plan_is_one_number_so_quantity_must_be_one(self):
        body = self.sell("renewal", expect=400, activation_date="2026-10-06", qty=2)
        self.assertIn("數量只能是 1", str(body))

    # ── 存了之後改日期(中華電信先入帳、續約日往後延) ──────────────
    def change(self, doc, expect=200, client=None, **body):
        item = self.line(doc)
        resp = (client or self.c.admin).post(
            f"/api/v1/sales-orders/{doc['id']}/contract-dates/",
            {"item": item.id, **body}, format="json")
        self.assertEqual(resp.status_code, expect, resp.content)
        return resp.json()

    def test_renewal_date_can_be_moved_after_saving_and_the_end_date_follows(self):
        doc = self.sell("renewal", activation_date="2026-10-06")
        before = SalesOrderItem.objects.filter(so_id=doc["id"]).values(
            "amount", "commission", "cost_at_post", "untaxed_amount").get()
        body = self.change(doc, activation_date="2026-10-28", prev_contract_end="2026-11-30")
        item = self.line(doc)
        self.assertEqual(item.activation_date, date(2026, 10, 28))
        self.assertEqual(item.prev_contract_end, date(2026, 11, 30))
        self.assertEqual(item.contract_end, date(2028, 10, 28))
        self.assertEqual(body["items"][0]["contract_end"], "2028-10-28")
        # 只動日期:金額、佣金、成本都沒變
        after = SalesOrderItem.objects.filter(so_id=doc["id"]).values(
            "amount", "commission", "cost_at_post", "untaxed_amount").get()
        self.assertEqual(before, after)

    def test_dates_on_a_voided_order_cannot_be_changed(self):
        doc = self.sell("renewal", activation_date="2026-10-06")
        self.assertEqual(
            self.c.admin.post(f"/api/v1/sales-orders/{doc['id']}/void/").status_code, 200)
        body = self.change(doc, expect=400, activation_date="2026-10-28")
        self.assertIn("已作廢", str(body))
        self.assertEqual(self.line(doc).activation_date, date(2026, 10, 6))

    def test_change_is_refused_when_it_makes_no_sense(self):
        # 新辦當天生效:沒有日期可以改
        new = self.sell("new")
        started = self.line(new).activation_date
        self.assertIn("新辦", str(self.change(new, expect=400, activation_date="2026-11-01")))
        self.assertEqual(self.line(new).activation_date, started)
        portin = self.sell("portin", activation_date="2026-10-06")
        self.assertIn("不是續約", str(self.change(
            portin, expect=400, activation_date="2026-10-06", prev_contract_end="2026-12-31")))
        self.change(portin, expect=400)  # 起算日沒給
        # 不是這張單上的明細
        other = self.sell("renewal", activation_date="2026-10-06")
        resp = self.c.admin.post(
            f"/api/v1/sales-orders/{new['id']}/contract-dates/",
            {"item": self.line(other).id, "activation_date": "2026-11-01"}, format="json")
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertEqual(self.line(other).activation_date, date(2026, 10, 6))
        # 沒有門號方案的那一行沒有合約日期可以改
        plain = self.c._post("/api/v1/sales-orders/", {
            "customer": self.c.customer.id, "warehouse": self.c.wh.id, "tax_method": "untaxed",
            "items": [{"product": self.c.case.id, "qty": 1, "unit_price": "0"}], "payments": [],
        })
        self.assertIn("沒有門號方案", str(self.change(plain, expect=400, activation_date="2026-11-01")))

    def test_clerk_locked_to_another_store_cannot_change_it(self):
        doc = self.sell("renewal", activation_date="2026-10-06")
        from apps.tenants.models import UserProfile
        UserProfile.objects.filter(user=self.c.clerk_user).update(
            default_warehouse=self.c.warehouses[1], is_warehouse_locked=True)
        from django.contrib.auth import get_user_model
        # 重新從資料庫拿這個帳號(原本那個物件還記著改之前的門市)
        other_store = self.c.client(get_user_model().objects.get(pk=self.c.clerk_user.pk))
        self.change(doc, expect=404, client=other_store, activation_date="2026-10-28")
        self.assertEqual(self.line(doc).activation_date, date(2026, 10, 6))
