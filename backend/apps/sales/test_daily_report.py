"""銷貨日報的資料端點:期間內全部的銷貨單與銷退(不再只有前 50 張)、會員與商品條件、鎖門市、權限。"""
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from apps.backup.tests.factory import Company
from apps.parties.models import Customer, Member, SalesPerson
from apps.sales import daily_report
from apps.sales.models import SalesOrder, SalesOrderItem
from apps.tenants.models import UserProfile

URL = "/api/v1/sales-daily-report/"


def today():
    return timezone.localdate()


class _Shop(TestCase):
    def setUp(self):
        c = self.c = Company("a", "甲通訊行", "甲")
        self.w1, self.w2 = c.warehouses
        c.purchase(phone_serials=["甲IMEI1", "甲IMEI2"], case_qty=100)
        c.purchase(warehouse=self.w2, case_qty=20)

    def report(self, client=None, **params):
        r = (client or self.c.admin).get(URL, {"from": today(), "to": today(), **params})
        self.assertEqual(r.status_code, 200, r.content.decode())
        return r.json()

    def give_back(self, so):
        return self.c._post("/api/v1/sales-returns/", {"original_so": so["id"], "payment_method": "cash"})


class EverythingIsThereTests(_Shop):
    def test_more_than_fifty_orders(self):
        for _ in range(60):
            self.c.sell(case_qty=1)
        # 原因:銷貨單清單一頁固定 50 張,要求一頁 500 張它不理 —— 以前的銷貨日報就是拿這一頁自己加總
        old = self.c.admin.get("/api/v1/sales-orders/", {"doc_date__gte": today(), "page_size": 500}).json()
        self.assertEqual((old["count"], len(old["results"])), (60, 50))
        data = self.report()
        self.assertEqual(len(data["orders"]), 60)
        self.assertFalse(data["truncated"])
        self.assertEqual(sum(Decimal(it["amount"]) for o in data["orders"] for it in o["items"]), Decimal(60 * 390))
        numbers = [o["no"] for o in data["orders"]]
        self.assertEqual(numbers, sorted(numbers))                       # 照日期、單號排

    def test_over_the_limit_says_so(self):
        for _ in range(3):
            self.give_back(self.c.sell(case_qty=1))
        with mock.patch.object(daily_report, "MAX_DOCS", 2):
            data = self.report()
        self.assertTrue(data["truncated"])
        self.assertEqual((len(data["orders"]), len(data["returns"]), data["limit"]), (2, 2, 2))
        self.assertFalse(self.report()["truncated"])

    def test_what_a_line_carries(self):
        so = self.c.sell(serial_no="甲IMEI1", case_qty=2)
        data = self.report()
        self.assertEqual((data["from"], data["to"], data["warehouse"], data["searching"]),
                         (today().isoformat(), today().isoformat(), None, False))
        order = data["orders"][0]
        self.assertEqual(
            {k: order[k] for k in ("id", "no", "is_void", "warehouse_name", "sales_person_name", "customer_name", "member_name")},
            {"id": so["id"], "no": so["no"], "is_void": False, "warehouse_name": self.w1.name,
             "sales_person_name": self.c.sales_person.name, "customer_name": self.c.customer.name, "member_name": None},
        )
        phone, case = order["items"]
        self.assertEqual(
            {k: phone[k] for k in ("product_name", "qty", "unit_price", "amount", "untaxed_amount", "cost_at_post",
                                   "staff_cost", "serials", "matched", "product_counts_margin")},
            {"product_name": self.c.phone.name, "qty": 1, "unit_price": "25000.00", "amount": "25000.00",
             "untaxed_amount": "25000.00", "cost_at_post": "20000.00", "staff_cost": "20000.00",
             "serials": [{"serial_no": "甲IMEI1"}], "matched": True, "product_counts_margin": True},
        )
        self.assertEqual((case["qty"], case["amount"], case["cost_at_post"], case["serials"]), (2, "780.00", "200.00", []))
        # 跟銷貨單清單那一支給的是同一個數字(畫面的合計算法沒有動,靠的是欄位名稱與數字都一樣)
        listed = self.c.admin.get(f"/api/v1/sales-orders/{so['id']}/").json()
        for mine, theirs in zip(order["items"], listed["items"]):
            for key in ("qty", "unit_price", "amount", "untaxed_amount", "cost_at_post", "staff_cost",
                        "product_name", "product_counts_margin", "product_warehouse_type"):
                self.assertEqual(mine[key], theirs[key], key)
        self.assertEqual(order["customer_name"], listed["customer_name"])

    def test_staff_cost_falls_back_to_actual_cost(self):
        so = self.c.sell(case_qty=1)
        SalesOrderItem.objects.filter(so_id=so["id"]).update(staff_cost=None)          # 舊單沒有記
        self.assertEqual(self.report()["orders"][0]["items"][0]["staff_cost"], "100.00")
        SalesOrderItem.objects.filter(so_id=so["id"]).update(staff_cost=Decimal("130"))
        self.assertEqual(self.report()["orders"][0]["items"][0]["staff_cost"], "130.00")

    def test_customer_is_the_source_recorded_on_the_order(self):
        # 跟銷貨單清單同一個規則:這張單記的來源名稱優先(之後客戶改名、會員換來源都不影響這張單)
        so = self.c.sell(case_qty=1)
        SalesOrder.objects.filter(pk=so["id"]).update(source_name="巨城直客")
        self.assertEqual(self.report()["orders"][0]["customer_name"], "巨城直客")
        sr = self.give_back(so)
        self.assertEqual(self.report()["returns"][0]["customer_name"], "巨城直客")
        listed = self.c.admin.get(f"/api/v1/sales-returns/{sr['id']}/").json()
        self.assertEqual(listed["customer_name"], "巨城直客")
        SalesOrder.objects.filter(pk=so["id"]).update(source_name="")            # 舊單沒有記:用客戶
        data = self.report()
        self.assertEqual((data["orders"][0]["customer_name"], data["returns"][0]["customer_name"]),
                         (self.c.customer.name, self.c.customer.name))

    def test_voided_orders_are_marked_not_dropped(self):
        so = self.c.sell(case_qty=1)
        self.assertEqual(self.c.admin.post(f"/api/v1/sales-orders/{so['id']}/void/").status_code, 200)
        self.assertEqual([(o["no"], o["is_void"]) for o in self.report()["orders"]], [(so["no"], True)])


class ReturnTests(_Shop):
    def test_returns_are_negative_and_on_the_day_returned(self):
        so = self.c.sell(serial_no="甲IMEI1", case_qty=2)
        sr = self.give_back(so)
        data = self.report()
        self.assertEqual(len(data["orders"]), 1)                        # 原銷貨單照樣在(它沒有作廢)
        back = data["returns"][0]
        self.assertEqual(
            {k: back[k] for k in ("id", "no", "original_so", "original_so_no", "warehouse_name", "sales_person_name", "customer_name")},
            {"id": sr["id"], "no": sr["no"], "original_so": so["id"], "original_so_no": so["no"],
             "warehouse_name": self.w1.name, "sales_person_name": self.c.sales_person.name,
             "customer_name": self.c.customer.name},
        )
        phone, case = back["items"]
        self.assertEqual(
            {k: phone[k] for k in ("qty", "unit_price", "amount", "untaxed_amount", "cost_at_post", "staff_cost", "serials")},
            {"qty": -1, "unit_price": "25000.00", "amount": "-25000.00", "untaxed_amount": "-25000.00",
             "cost_at_post": "-20000.00", "staff_cost": "-20000.00", "serials": [{"serial_no": "甲IMEI1"}]},
        )
        self.assertEqual((case["qty"], case["amount"], case["cost_at_post"]), (-2, "-780.00", "-200.00"))
        # 退的每一行剛好把原單那一行沖掉
        sold = data["orders"][0]["items"]
        for a, b in zip(sold, back["items"]):
            for key in ("amount", "untaxed_amount", "cost_at_post", "staff_cost"):
                self.assertEqual(Decimal(a[key]) + Decimal(b[key]), 0, key)

    def test_listed_on_the_day_it_came_back(self):
        so = self.c.sell(case_qty=1)
        sr = self.give_back(so)
        SalesOrder.objects.filter(pk=so["id"]).update(doc_date=today() - timedelta(days=3))
        data = self.report()
        self.assertEqual(([o["no"] for o in data["orders"]], [r["no"] for r in data["returns"]]), ([], [sr["no"]]))
        later = self.c.sell(case_qty=1)                                   # 今天另外賣一張
        earlier = self.report(**{"from": today() - timedelta(days=3), "to": today() - timedelta(days=1)})
        self.assertEqual(([o["no"] for o in earlier["orders"]], earlier["returns"]), ([so["no"]], []))   # 迄日之後的不列
        self.assertEqual([o["no"] for o in self.report()["orders"]], [later["no"]])

    def test_voided_returns_are_not_listed(self):
        sr = self.give_back(self.c.sell(case_qty=1))
        self.assertEqual(self.c.admin.post(f"/api/v1/sales-returns/{sr['id']}/void/", {}, format="json").status_code, 200)
        self.assertEqual(self.report()["returns"], [])


class ConditionTests(_Shop):
    def setUp(self):
        super().setUp()
        c = self.c
        self.member = Member.objects.create(tenant=c.tenant, name="王小明", phone="0911222333")
        self.other_customer = Customer.objects.create(tenant=c.tenant, name="甲同行", phone="0922000111")
        self.other_person = SalesPerson.objects.create(tenant=c.tenant, code="S2", name="甲二號")
        self.plain = c.sell(serial_no="甲IMEI1", case_qty=2)
        self.with_member = c._post("/api/v1/sales-orders/", {
            "customer": self.other_customer.id, "member": self.member.id, "warehouse": self.w1.id,
            "tax_method": "untaxed", "sales_person": self.other_person.id,
            "items": [{"product": c.case.id, "qty": 1, "unit_price": "390"}],
            "payments": [{"method": "cash", "amount": "390"}],
        })
        self.elsewhere = c.sell(warehouse=self.w2, case_qty=3)

    def numbers(self, **params):
        data = self.report(**params)
        return [o["no"] for o in data["orders"]], [r["no"] for r in data["returns"]]

    def test_each_condition(self):
        all_three = sorted(o["no"] for o in (self.plain, self.with_member, self.elsewhere))
        self.assertEqual(self.numbers()[0], all_three)
        self.assertEqual(self.numbers(warehouse=self.w2.id)[0], [self.elsewhere["no"]])
        self.assertEqual(self.numbers(sales_person=self.other_person.id)[0], [self.with_member["no"]])
        self.assertEqual(self.numbers(customer=self.other_customer.id)[0], [self.with_member["no"]])
        self.assertEqual(self.numbers(member=self.member.id)[0], [self.with_member["no"]])
        self.assertEqual(self.report(member=self.member.id)["orders"][0]["member_name"], "王小明")
        self.assertEqual(self.numbers(member=self.member.id + 999)[0], [])

    def test_returns_follow_the_same_conditions(self):
        back = self.give_back(self.with_member)
        self.give_back(self.elsewhere)
        self.assertEqual(len(self.numbers()[1]), 2)
        for cond in ({"member": self.member.id}, {"customer": self.other_customer.id},
                     {"sales_person": self.other_person.id}, {"warehouse": self.w1.id}):
            self.assertEqual(self.numbers(**cond)[1], [back["no"]], cond)
        self.assertEqual(self.numbers(sales_person=self.c.sales_person.id)[1], [self.numbers(warehouse=self.w2.id)[1][0]])

    def test_searching_marks_the_lines_that_match(self):
        data = self.report(search="iphone 128")
        self.assertTrue(data["searching"])
        self.assertEqual([o["no"] for o in data["orders"]], [self.plain["no"]])
        self.assertEqual([(i["product_name"], i["matched"]) for i in data["orders"][0]["items"]],
                         [(self.c.phone.name, True), (self.c.case.name, False)])     # 同一張單的皮套那一行沒對上
        by_code = self.report(search="imei1")                              # 那一行的那一台的碼
        self.assertEqual([i["matched"] for i in by_code["orders"][0]["items"]], [True, False])
        self.assertEqual([o["no"] for o in by_code["orders"]], [self.plain["no"]])
        cases = self.report(search=self.c.case.sku)
        self.assertEqual(len(cases["orders"]), 3)
        self.assertEqual(self.report(search="iphone 皮套")["orders"], [])   # 每一段要在同一行對得上
        self.assertEqual(self.report(search="沒有這個東西")["orders"], [])

    def test_searching_returns_too(self):
        back = self.give_back(self.plain)
        self.give_back(self.elsewhere)                                    # 只有皮套的那一張銷退
        self.assertEqual(len(self.report()["returns"]), 2)
        data = self.report(search="iphone")
        self.assertEqual([r["no"] for r in data["returns"]], [back["no"]])            # 沒有對得上的行的那一張不列
        self.assertEqual([i["matched"] for i in data["returns"][0]["items"]], [True, False])
        self.assertEqual(self.report(search=self.c.case.sku, member=self.member.id)["returns"], [])


class AccessTests(_Shop):
    def test_locked_account_only_gets_its_own_store(self):
        mine = self.c.sell(case_qty=1)
        self.c.sell(warehouse=self.w2, case_qty=1)
        data = self.report(client=self.c.clerk, warehouse=self.w2.id)        # 網址帶別家的編號沒有用
        self.assertEqual((data["warehouse"], [o["no"] for o in data["orders"]]), (self.w1.id, [mine["no"]]))
        self.assertEqual(len(self.report()["orders"]), 2)

    def test_needs_the_sales_daily_ability(self):
        self.c.sell(case_qty=1)
        from django.contrib.auth import get_user_model

        self.assertEqual(self.c.clerk.get(URL, {"from": today(), "to": today()}).status_code, 200)   # 開著的時候可以
        UserProfile.objects.filter(user=self.c.clerk_user).update(denied_abilities=["report_sales_daily"])
        clerk = Company.client(get_user_model().objects.get(pk=self.c.clerk_user.pk))    # 重新讀帳號的設定
        r = clerk.get(URL, {"from": today(), "to": today()})
        self.assertEqual(r.status_code, 403)
        self.assertIn("銷貨日報", r.json()["detail"])
        self.assertEqual(self.c.admin.get(URL, {"from": today(), "to": today()}).status_code, 200)

    def test_other_companies_are_invisible(self):
        other = Company("b", "乙通訊行", "乙")
        other.purchase(case_qty=5)
        theirs = other.sell(case_qty=1)
        other._post("/api/v1/sales-returns/", {"original_so": theirs["id"], "payment_method": "cash"})
        mine = self.c.sell(case_qty=1)
        back = self.give_back(mine)
        data = self.report()
        self.assertEqual([o["id"] for o in data["orders"]], [mine["id"]])
        self.assertEqual([r["id"] for r in data["returns"]], [back["id"]])       # 別家公司的銷退也看不到
        self.assertEqual([o["no"] for o in self.report()["orders"]], [mine["no"]])
        self.assertEqual(self.report(warehouse=other.wh.id)["orders"], [])
        self.assertEqual(self.report(customer=other.customer.id)["orders"], [])

    def test_bad_conditions_and_login(self):
        from rest_framework.test import APIClient

        get = self.c.admin.get
        self.assertEqual(get(URL, {"from": today(), "to": today() - timedelta(days=1)}).status_code, 400)
        self.assertEqual(get(URL, {"from": today() - timedelta(days=366), "to": today()}).status_code, 400)
        self.assertEqual(get(URL, {"member": "abc"}).status_code, 400)
        self.assertIn(APIClient().get(URL).status_code, (401, 403))
