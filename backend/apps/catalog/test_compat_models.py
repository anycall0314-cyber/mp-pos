"""相容機型:清單打字搜尋不出錯;存檔先確認每個機型都對得到東西,對不到就整筆退回、不刪舊的。

2026-10-09 讀討論稿時對照程式查出來的兩個洞(原本:搜尋回 500;手打或沒有手機商品的機型被默默丟掉,
批次「覆寫」會刪了舊的、新的又沒建、畫面說成功)。
"""
from django.test import TestCase

from apps.backup.tests.factory import Company

from .models import Brand, PhoneModel, PhoneSeries, Product, ProductRelation


class _Shop(TestCase):
    def setUp(self):
        self.c = Company("a", "甲通訊行", "甲")
        self.t = self.c.tenant
        self.apple = Brand.objects.create(tenant=self.t, code="apple", name="Apple")
        self.iphone = PhoneSeries.objects.create(tenant=self.t, brand=self.apple, code="iphone", name="iPhone")
        self.m17 = self.model("iPhone 17", 17)
        self.m18 = self.model("iPhone 18", 18)            # 只有機型主檔,沒有手機商品
        self.phone17 = self.host("iPhone 17 256GB 黑色 全新", self.m17, 17)
        self.case = Product.objects.create(tenant=self.t, category=self.c.cat_case, name="IMOS/IP17/透", requires_serial=False)

    def model(self, name, generation):
        return PhoneModel.objects.create(tenant=self.t, code=name.lower().replace(" ", "-"), name=name,
                                         match_key=name.lower(), brand=self.apple, series=self.iphone, generation=generation)

    def host(self, name, model, generation, **more):
        return Product.objects.create(tenant=self.t, category=self.c.cat_phone, name=name, brand=self.apple,
                                      series=self.iphone, generation=generation, phone_model=model, **more)

    def keys_of(self, product):
        return sorted(ProductRelation.objects.filter(accessory_product=product).values_list("host_model_key", flat=True))

    def patch(self, product, **body):
        return self.c.admin.patch(f"/api/v1/products/{product.id}/", body, format="json")


class PickerSearchTests(_Shop):
    URL = "/api/v1/products/phone-models/"

    def names(self, **params):
        r = self.c.admin.get(self.URL, params)
        self.assertEqual(r.status_code, 200, r.content.decode()[:300])
        return [row["model_name"] for row in r.json()]

    def test_typing_in_the_list_is_not_an_error(self):
        every = self.names()
        self.assertEqual(every, sorted(every))
        self.assertIn("iPhone 17", every)
        self.assertGreater(len(every), 1)                                        # 還有工廠建的那一支手機
        self.assertEqual(self.names(search="17"), ["iPhone 17"])                 # 商品名
        self.assertEqual(self.names(search="IPHONE 17"), ["iPhone 17"])          # 不分大小寫
        self.assertIn("iPhone 17", self.names(search="iphone"))
        self.assertEqual(self.names(search="沒有這個"), [])

    def test_search_by_the_series_name(self):
        """商品名裡沒有系列的字,靠系列名稱找到。"""
        galaxy = PhoneSeries.objects.create(tenant=self.t, brand=self.apple, code="galaxy", name="Galaxy")
        Product.objects.create(tenant=self.t, category=self.c.cat_phone, name="S25 256GB 黑", brand=self.apple,
                               series=galaxy, generation=25)
        self.assertEqual(self.names(search="galaxy"), ["Galaxy 25"])

    def test_another_company_is_not_listed(self):
        b = Company("b", "乙通訊行", "乙")
        r = b.admin.get(self.URL, {"search": "iphone"})
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("iPhone 17", [row["model_name"] for row in r.json()])
        self.assertEqual(b.admin.get(self.URL, {"search": "17"}).json(), [])


class SaveTests(_Shop):
    def test_a_model_with_a_phone_product_is_linked_as_before(self):
        r = self.patch(self.case, related_host_keys=["iphone 17"])
        self.assertEqual(r.status_code, 200, r.content.decode())
        rel = ProductRelation.objects.get(accessory_product=self.case)
        self.assertEqual((rel.host_model_key, rel.host_product_id, rel.host_model_id),
                         ("iphone 17", self.phone17.id, self.m17.id))
        self.assertEqual(r.json()["related_hosts"][0]["model_name"], "iPhone 17")

    def test_a_model_with_no_phone_product_can_be_linked_through_the_master(self):
        r = self.patch(self.case, related_host_keys=["iphone 18", " IPHONE 17 "])
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.assertEqual(self.keys_of(self.case), ["iphone 17", "iphone 18"])
        rel = ProductRelation.objects.get(accessory_product=self.case, host_model_key="iphone 18")
        self.assertEqual((rel.host_product_id, rel.host_model_id), (None, self.m18.id))
        shown = {h["model_key"]: h for h in r.json()["related_hosts"]}
        self.assertEqual(shown["iphone 18"]["model_name"], "iPhone 18")     # 主檔的名稱,不是小寫的 key
        self.assertIsNone(shown["iphone 18"]["sample_sku_id"])
        # 再存一次(清單沒變)不會多一筆、不會出錯
        self.assertEqual(self.patch(self.case, related_host_keys=["iphone 18", "iphone 17"]).status_code, 200)
        self.assertEqual(ProductRelation.objects.filter(accessory_product=self.case).count(), 2)

    def test_a_phone_product_that_was_deactivated_still_links_through_the_master(self):
        Product.objects.filter(pk=self.phone17.pk).update(is_active=False)
        self.assertEqual(self.patch(self.case, related_host_keys=["iphone 17"]).status_code, 200)
        rel = ProductRelation.objects.get(accessory_product=self.case)
        self.assertEqual((rel.host_product_id, rel.host_model_id), (None, self.m17.id))

    def test_a_model_nobody_has_is_refused_and_nothing_is_touched(self):
        self.patch(self.case, related_host_keys=["iphone 17"])
        r = self.patch(self.case, related_host_keys=["iphone 18", "ip99 手打的"], name="改掉的名字")
        self.assertEqual(r.status_code, 400, r.content.decode())
        self.assertIn("ip99 手打的", r.json()["detail"])
        self.assertNotIn("iphone 18", r.json()["detail"])          # 對得到的不列
        # 舊的關係原封不動、對得到的那一個也沒有先建、商品其他欄位沒被改
        self.assertEqual(self.keys_of(self.case), ["iphone 17"])
        self.case.refresh_from_db()
        self.assertEqual(self.case.name, "IMOS/IP17/透")

    def test_the_message_does_not_run_on_forever(self):
        r = self.patch(self.case, related_host_keys=[f"手打{i}" for i in range(9)])
        self.assertEqual(r.status_code, 400)
        self.assertIn("等 9 個", r.json()["detail"])
        self.assertEqual(r.json()["detail"].count("手打"), 5)

    def test_an_empty_list_clears_and_leaving_it_out_keeps(self):
        self.patch(self.case, related_host_keys=["iphone 17", "iphone 18"])
        self.assertEqual(self.patch(self.case, spec="玻璃").status_code, 200)          # 沒帶 = 不動
        self.assertEqual(self.keys_of(self.case), ["iphone 17", "iphone 18"])
        self.assertEqual(self.patch(self.case, related_host_keys=["iphone 18"]).status_code, 200)
        self.assertEqual(self.keys_of(self.case), ["iphone 18"])
        self.assertEqual(self.patch(self.case, related_host_keys=[]).status_code, 200)
        self.assertEqual(self.keys_of(self.case), [])

    def test_creating_with_a_model_nobody_has_creates_nothing(self):
        body = {"name": "DAP/IP17/柔幻磁吸/黑", "category": self.c.cat_case.id, "requires_serial": False}
        r = self.c.admin.post("/api/v1/products/", {**body, "related_host_keys": ["手打的機型"]}, format="json")
        self.assertEqual(r.status_code, 400, r.content.decode())
        self.assertIn("手打的機型", r.json()["detail"])
        self.assertFalse(Product.objects.filter(tenant=self.t, name=body["name"]).exists())
        r = self.c.admin.post("/api/v1/products/", {**body, "related_host_keys": ["iphone 18"]}, format="json")
        self.assertEqual(r.status_code, 201, r.content.decode())
        self.assertEqual(self.keys_of(Product.objects.get(tenant=self.t, name=body["name"])), ["iphone 18"])

    def test_a_phone_is_not_linked_to_its_own_model(self):
        """主機自己就是那個機型:照舊不建關係、也不算錯。"""
        Product.objects.filter(pk=self.phone17.pk).update(requires_serial=False)
        r = self.patch(self.phone17, related_host_keys=["iphone 17"])
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.assertEqual(self.keys_of(self.phone17), [])

    def test_another_companys_model_does_not_count(self):
        b = Company("b", "乙通訊行", "乙")
        PhoneModel.objects.create(tenant=b.tenant, code="iphone-19", name="iPhone 19", match_key="iphone 19")
        r = self.patch(self.case, related_host_keys=["iphone 19"])
        self.assertEqual(r.status_code, 400)
        self.assertIn("iphone 19", r.json()["detail"])


class BulkOverwriteTests(_Shop):
    URL = "/api/v1/products/bulk-edit/"

    def setUp(self):
        super().setUp()
        self.film = Product.objects.create(tenant=self.t, category=self.c.cat_case, name="IMOS/IP17/9H", requires_serial=False)
        for p in (self.case, self.film):
            self.assertEqual(self.patch(p, related_host_keys=["iphone 17"]).status_code, 200)

    def overwrite(self, keys):
        return self.c.admin.post(self.URL, {"ids": [self.case.id, self.film.id], "patch": {"related_host_keys": keys}}, format="json")

    def test_overwriting_with_a_model_nobody_has_keeps_what_was_there(self):
        r = self.overwrite(["iphone 18", "手打的機型"])
        self.assertEqual(r.status_code, 400, r.content.decode())
        said = {e["name"]: e["errors"]["detail"] for e in r.json()["errors"]}
        self.assertEqual(set(said), {"IMOS/IP17/透", "IMOS/IP17/9H"})
        self.assertIn("手打的機型", said["IMOS/IP17/透"])
        self.assertEqual((self.keys_of(self.case), self.keys_of(self.film)), (["iphone 17"], ["iphone 17"]))

    def test_overwriting_with_models_from_the_master_works(self):
        r = self.overwrite(["iphone 18"])
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.assertEqual((self.keys_of(self.case), self.keys_of(self.film)), (["iphone 18"], ["iphone 18"]))
