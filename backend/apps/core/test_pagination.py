"""全站清單的分頁:要多少給多少(最多 500)、要更少的照舊給 50、同分的列有固定的先後。"""
from unittest import mock

from django.db import connection
from django.db.models import F
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.backup.tests.factory import Company
from apps.core import pagination
from apps.parties.models import Supplier
from apps.sales.models import SalesOrder

URL = "/api/v1/suppliers/"


class _Suppliers(TestCase):
    """120 家供應商(原本那一家 + 119 家)。"""

    def setUp(self):
        c = self.c = Company("a", "甲通訊行", "甲")
        Supplier.objects.bulk_create(
            Supplier(tenant=c.tenant, code=f"T{i:03d}", name=f"廠商{i:03d}") for i in range(119))

    def page(self, **params):
        r = self.c.admin.get(URL, params)
        self.assertEqual(r.status_code, 200, r.content.decode())
        return r.json()


class HowManyTests(_Suppliers):
    def test_fifty_when_nothing_is_asked(self):
        data = self.page()
        self.assertEqual((data["count"], len(data["results"])), (120, 50))
        self.assertIsNotNone(data["next"])

    def test_asking_for_more_gets_more(self):
        """以前帶 page_size=200 它不理,只給 50 —— 畫面以為拿到全部。"""
        data = self.page(page_size=200)
        self.assertEqual((data["count"], len(data["results"])), (120, 120))
        self.assertIsNone(data["next"])
        self.assertEqual(len(self.page(page_size=100)["results"]), 100)

    def test_never_more_than_the_cap(self):
        self.assertEqual((pagination.MAX_PAGE_SIZE, pagination.Paging.max_page_size), (500, 500))
        with mock.patch.object(pagination.Paging, "max_page_size", 70):
            self.assertEqual(len(self.page(page_size=9999)["results"]), 70)

    def test_asking_for_fewer_still_gets_fifty(self):
        """刷條碼、搜尋下拉帶著 10、20,一直以來實際拿到的是 50;不讓它變少。"""
        for size in (1, 10, 20, 49, 50):
            with self.subTest(size=size):
                self.assertEqual(len(self.page(page_size=size)["results"]), 50)

    def test_nonsense_is_the_default(self):
        for size in ("abc", "0", "-5", "", "1.5"):
            with self.subTest(size=size):
                self.assertEqual(len(self.page(page_size=size)["results"]), 50)

    def test_the_next_page_keeps_the_size(self):
        first = self.page(page_size=100)
        self.assertIn("page_size=100", first["next"])
        second = self.page(page_size=100, page=2)
        self.assertEqual((len(second["results"]), second["next"]), (20, None))


class EveryoneOnceTests(_Suppliers):
    def walk(self, **params):
        seen, page = [], 1
        while True:
            data = self.page(page=page, **params)
            seen += [row["id"] for row in data["results"]]
            if not data["next"]:
                return seen
            page += 1

    def test_walking_the_pages_meets_everyone_once(self):
        everyone = set(Supplier.objects.filter(tenant=self.c.tenant).values_list("id", flat=True))
        for params in ({}, {"page_size": 100}, {"ordering": "name"}, {"ordering": "-created_at"}):
            with self.subTest(params=params):
                seen = self.walk(**params)
                self.assertEqual(len(seen), 120)
                self.assertEqual(set(seen), everyone)

    def test_rows_that_tie_are_told_apart_by_their_number(self):
        """同名的六十家:只照名稱排,每一次查的先後資料庫不保證一樣,翻頁就會重複 / 漏列。排序最後要有編號。"""
        Supplier.objects.filter(tenant=self.c.tenant).update(name="同一個名字")
        with CaptureQueriesContext(connection) as queries:
            self.page(ordering="name")
        listing = [q["sql"] for q in queries if "LIMIT" in q["sql"] and "parties_supplier" in q["sql"]]
        self.assertEqual(len(listing), 1, listing)
        self.assertRegex(listing[0], r'ORDER BY "parties_supplier"\."name" ASC, "parties_supplier"\."id" ASC LIMIT')
        self.assertEqual(sorted(self.walk(ordering="name")),
                         sorted(Supplier.objects.filter(tenant=self.c.tenant).values_list("id", flat=True)))


class StableTests(TestCase):
    def order(self, queryset):
        return pagination.stable(queryset).query.order_by

    def test_the_default_order_gets_the_number_at_the_end(self):
        self.assertEqual(list(Supplier._meta.ordering), ["sort_order", "code"])
        self.assertEqual(self.order(Supplier.objects.all()), ("sort_order", "code", "pk"))

    def test_an_asked_order_gets_the_number_at_the_end(self):
        self.assertEqual(self.order(Supplier.objects.order_by("-name")), ("-name", "pk"))
        by_expression = self.order(Supplier.objects.order_by(F("name").desc()))
        self.assertEqual((len(by_expression), by_expression[-1]), (2, "pk"))

    def test_no_order_at_all_goes_by_the_number(self):
        self.assertEqual(self.order(Supplier.objects.order_by()), ("pk",))

    def test_already_by_the_number_is_left_alone(self):
        for queryset in (
            SalesOrder.objects.order_by("-doc_date", "-id"),
            Supplier.objects.order_by("name", "pk"),
            Supplier.objects.order_by("-pk"),
        ):
            with self.subTest(order=queryset.query.order_by):
                self.assertIs(pagination.stable(queryset), queryset)

    def test_what_is_not_a_plain_list_is_left_alone(self):
        names = Supplier.objects.values("name")
        cut = Supplier.objects.all()[:5]
        both = Supplier.objects.filter(name="甲").union(Supplier.objects.filter(name="乙"))
        rows = [1, 2, 3]
        for thing in (names, cut, both, rows):
            self.assertIs(pagination.stable(thing), thing)
