"""新增類別不用填代碼(全站檢視 D6):系統給這家公司還沒用過的 C01、C02…;代碼是品號開頭,不能重複。"""
from unittest import mock

from django.test import TestCase

from apps.backup.tests.factory import Company
from apps.catalog import serializers as catalog_serializers
from apps.catalog.models import Category, Product

URL = "/api/v1/categories/"


class CategoryCodeTests(TestCase):
    def setUp(self):
        self.c = Company("a", "甲通訊行", "甲")

    def create(self, name, **extra):
        r = self.c.admin.post(URL, {"name": name, "kind": "general", **extra}, format="json")
        self.assertEqual(r.status_code, 201, r.content.decode())
        return r.json()

    def test_blank_code_gets_the_next_free_one_and_products_use_it(self):
        first = self.create("吊飾")
        second = self.create("家電")
        self.assertEqual((first["code"], second["code"]), ("C01", "C02"))
        Category.objects.filter(pk=first["id"]).delete()                     # 空出來的號下次再用
        self.assertEqual(self.create("貼紙")["code"], "C01")
        # 別家公司的號不算
        other = Company("b", "乙通訊行", "乙")
        r = other.admin.post(URL, {"name": "吊飾", "kind": "general"}, format="json")
        self.assertEqual(r.json()["code"], "C01")
        # 建出來的商品品號用這個開頭
        p = Product.objects.create(tenant=self.c.tenant, category_id=second["id"], name="甲 小風扇", requires_serial=False)
        self.assertTrue(p.sku.startswith("C02"), p.sku)

    def test_typed_code_still_works_and_duplicates_are_refused(self):
        self.assertEqual(self.create("掛繩", code="LY")["code"], "LY")
        r = self.c.admin.post(URL, {"name": "掛繩二", "kind": "general", "code": "LY"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_two_people_creating_at_once_skip_to_the_next_number(self):
        self.create("吊飾")                                                   # C01 已經有了
        real = catalog_serializers._next_category_code
        calls = []

        def stale(tenant):
            # 第一次拿到的是別人剛用掉的 C01(查的時候還沒看到),第二次才查到真的
            calls.append(1)
            return "C01" if len(calls) == 1 else real(tenant)

        with mock.patch.object(catalog_serializers, "_next_category_code", side_effect=stale):
            got = self.create("家電")
        self.assertEqual(got["code"], "C02")
        self.assertEqual(len(calls), 2)
