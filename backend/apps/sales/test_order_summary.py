"""會員 / 客戶頁的「N 筆 · 累計 · 最近」:伺服器照清單同一套條件算全部,不是畫面拿第一頁自己加。"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.backup.tests.factory import Company
from apps.parties.models import Customer, Member
from apps.sales.models import SalesOrder

URL = "/api/v1/sales-orders/summary/"


def today():
    return timezone.localdate()


class _Shop(TestCase):
    def setUp(self):
        c = self.c = Company("a", "甲通訊行", "甲")
        self.w1, self.w2 = c.warehouses
        c.purchase(case_qty=200)
        c.purchase(warehouse=self.w2, case_qty=20)
        self.member = Member.objects.create(tenant=c.tenant, name="王小明", phone="0911222333")

    def summary(self, client=None, **params):
        r = (client or self.c.admin).get(URL, params)
        self.assertEqual(r.status_code, 200, r.content.decode())
        return r.json()

    def sell(self, qty=1, member=None, customer=None, warehouse=None):
        return self.c._post("/api/v1/sales-orders/", {
            "customer": (customer or self.c.customer).id, "member": member.id if member else None,
            "warehouse": (warehouse or self.w1).id, "tax_method": "untaxed", "sales_person": self.c.sales_person.id,
            "items": [{"product": self.c.case.id, "qty": qty, "unit_price": "390"}],
            "payments": [{"method": "cash", "amount": str(390 * qty)}],
        })

    def void(self, so):
        return self.c._post(f"/api/v1/sales-orders/{so['id']}/void/", {})


class AllOfThemTests(_Shop):
    def test_more_than_one_page_of_orders(self):
        """以前畫面拿清單第一頁自己加:第 51 張之後的不算。"""
        for _ in range(60):
            self.sell()
        listing = self.c.admin.get("/api/v1/sales-orders/", {"customer": self.c.customer.id}).json()
        self.assertEqual((listing["count"], len(listing["results"])), (60, 50))
        self.assertEqual(self.summary(customer=self.c.customer.id),
                         {"count": 60, "total": "23400.00", "last_date": today().isoformat()})

    def test_nothing_yet(self):
        self.sell()
        self.assertEqual(self.summary(member=self.member.id), {"count": 0, "total": "0.00", "last_date": None})

    def test_void_orders_are_left_out(self):
        self.sell(qty=1, member=self.member)
        gone = self.sell(qty=5, member=self.member)
        self.sell(qty=2, member=self.member)
        self.void(gone)
        self.assertEqual(self.summary(member=self.member.id),
                         {"count": 2, "total": "1170.00", "last_date": today().isoformat()})

    def test_the_last_day_is_the_latest_one_still_standing(self):
        old, mid, new = (self.sell(member=self.member) for _ in range(3))
        SalesOrder.objects.filter(pk=old["id"]).update(doc_date=today() - timedelta(days=40))
        SalesOrder.objects.filter(pk=mid["id"]).update(doc_date=today() - timedelta(days=7))
        self.void(new)
        self.assertEqual(self.summary(member=self.member.id)["last_date"], (today() - timedelta(days=7)).isoformat())


    def test_the_total_is_what_was_charged_tax_and_all(self):
        """總額 = 單上的總額(含稅),不是未稅小計。"""
        so = self.c._post("/api/v1/sales-orders/", {
            "customer": self.c.customer.id, "member": self.member.id, "warehouse": self.w1.id,
            "tax_method": "taxable_excluded", "sales_person": self.c.sales_person.id,
            "items": [{"product": self.c.case.id, "qty": 1, "unit_price": "400"}],
            "payments": [{"method": "cash", "amount": "420"}],
        })
        self.assertEqual((so["subtotal"], so["total"]), ("400.00", "420.00"))
        self.assertEqual(self.summary(member=self.member.id)["total"], "420.00")

    def test_an_order_with_two_lines_is_one_order(self):
        self.c.purchase(phone_serials=["甲IMEI9"])
        so = self.c.sell(serial_no="甲IMEI9", case_qty=2)                 # 手機一行 + 皮套一行
        got = self.summary(customer=self.c.customer.id)
        self.assertEqual((got["count"], got["total"]), (1, so["total"]))
        self.assertEqual(so["total"], "25780.00")


class SameAsTheListTests(_Shop):
    def test_member_and_customer_are_told_apart(self):
        other = Customer.objects.create(tenant=self.c.tenant, name="甲企業客戶")
        self.sell(qty=1, member=self.member)
        self.sell(qty=2, member=self.member, customer=other)
        self.sell(qty=4)
        self.assertEqual(self.summary(member=self.member.id)["total"], "1170.00")
        self.assertEqual(self.summary(customer=other.id)["total"], "780.00")
        self.assertEqual(self.summary(customer=self.c.customer.id)["total"], "1950.00")
        self.assertEqual(self.summary(member=self.member.id, customer=other.id)["count"], 1)
        self.assertEqual(self.summary()["count"], 3)

    def test_the_dates_narrow_it_like_the_list(self):
        old = self.sell(qty=3, member=self.member)
        self.sell(qty=1, member=self.member)
        SalesOrder.objects.filter(pk=old["id"]).update(doc_date=today() - timedelta(days=40))
        got = self.summary(member=self.member.id, doc_date__gte=(today() - timedelta(days=5)).isoformat())
        self.assertEqual((got["count"], got["total"]), (1, "390.00"))
        got = self.summary(member=self.member.id, doc_date__lte=(today() - timedelta(days=5)).isoformat())
        self.assertEqual((got["count"], got["total"]), (1, "1170.00"))

    def test_a_locked_clerk_only_gets_their_store(self):
        self.sell(qty=1, member=self.member)
        self.sell(qty=2, member=self.member)
        self.sell(qty=4, member=self.member, warehouse=self.w2)
        self.assertEqual(self.summary(member=self.member.id)["total"], "2730.00")
        mine = self.summary(self.c.clerk, member=self.member.id)
        self.assertEqual((mine["count"], mine["total"]), (2, "1170.00"))
        seen = self.c.clerk.get("/api/v1/sales-orders/", {"member": self.member.id}).json()
        self.assertEqual(seen["count"], mine["count"])                  # 跟他清單上看到的同一批

    def test_another_company_is_not_counted(self):
        b = Company("b", "乙通訊行", "乙")
        b.purchase(case_qty=10)
        b.sell(case_qty=3)
        self.sell(qty=1)
        self.assertEqual(self.summary()["count"], 1)
        theirs = self.c.admin.get(URL, {"customer": b.customer.id})
        self.assertTrue(theirs.status_code == 400 or theirs.json()["count"] == 0, theirs.content.decode())

    def test_needs_a_login(self):
        self.assertEqual(APIClient().get(URL).status_code, 401)
