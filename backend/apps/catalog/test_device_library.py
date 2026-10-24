"""新增手機型號先從型號庫選(全站檢視 D10):找得到的照每天自動建品號同一套規則建,已經建了的只能去看(不建第二套)。全部是假資料。"""
from django.test import TestCase

from apps.backup.tests.factory import Company
from apps.catalog import device_catalog
from apps.catalog.models import Condition, PhoneModel, Product
from apps.catalog.test_device_catalog import NEW26, S25U, catalog

URL = "/api/v1/products/device-library/"
BUILD = "/api/v1/products/device-library/build/"


class DeviceLibraryTests(TestCase):
    def setUp(self):
        c = self.c = Company("a", "甲通訊行", "甲")
        for i, (code, n, used) in enumerate([("new", "全新", False), ("open", "已拆封", False), ("used", "中古機", True)]):
            Condition.objects.create(tenant=c.tenant, code=code, name=n, is_secondhand=used, sort_order=i)
        device_catalog.sync(catalog(S25U, NEW26), source="test")

    def find(self, q, client=None):
        r = (client or self.c.admin).get(URL, {"search": q})
        self.assertEqual(r.status_code, 200, r.content.decode())
        return r.json()["results"]

    def test_search_shows_what_this_company_already_built(self):
        rows = self.find("galaxy s25")
        self.assertEqual([(r["uid"], r["built"]) for r in rows], [("u-s25u", 0)])
        self.assertEqual((rows[0]["capacities"], rows[0]["colors"]), (["256GB", "512GB"], ["鈦黑", "鈦銀"]))
        self.assertEqual(self.find("x"), [])                          # 一個字不找

    def test_preview_writes_nothing_then_build_matches_the_daily_rules_and_only_once(self):
        before = Product.objects.for_tenant(self.c.tenant).count()
        r = self.c.admin.post(BUILD, {"uid": "u-a57", "preview": True}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.assertEqual((r.json()["total"], r.json()["created"]), (3, {"全新": 1, "已拆封": 1, "中古機": 1}))
        self.assertEqual(Product.objects.for_tenant(self.c.tenant).count(), before)
        self.assertFalse(PhoneModel.objects.for_tenant(self.c.tenant).filter(device_uid="u-a57").exists())

        r = self.c.admin.post(BUILD, {"uid": "u-a57"}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.assertEqual(r.json()["total"], 3)
        names = sorted(Product.objects.for_tenant(self.c.tenant).filter(phone_model_id=r.json()["phone_model"])
                       .values_list("name", flat=True))
        self.assertEqual(names, ["Galaxy A57 5G 128GB 冰藍 中古機", "Galaxy A57 5G 128GB 冰藍 全新",
                                 "Galaxy A57 5G 128GB 冰藍 已拆封"])
        self.assertEqual(self.find("a57")[0]["built"], 3)
        # 已經建了:不能再建第二套
        r = self.c.admin.post(BUILD, {"uid": "u-a57"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("已經建了", r.json()["detail"])
        self.assertEqual(self.c.admin.post(BUILD, {"uid": "no-such"}, format="json").status_code, 404)

    def test_staff_without_product_editing_cannot_build(self):
        r = self.c.admin.patch(f"/api/v1/staff-accounts/{self.c.clerk_user.id}/",
                               {"abilities": {"edit_products": False}}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.c.clerk_user.profile.refresh_from_db()
        self.assertEqual(self.find("a57", self.c.clerk)[0]["built"], 0)         # 看照舊
        self.assertEqual(self.c.clerk.post(BUILD, {"uid": "u-a57"}, format="json").status_code, 403)
        self.assertFalse(PhoneModel.objects.for_tenant(self.c.tenant).filter(device_uid="u-a57").exists())

    def test_a_renamed_product_of_the_same_spec_is_not_built_again(self):
        """公司原本就有這支(還沒對到型號庫)、品號被人改過名字:從型號庫建只補沒有的,不再建一個同規格的(複審 P1)。"""
        r = self.c.admin.post(BUILD, {"uid": "u-a57"}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        pm = PhoneModel.objects.get(pk=r.json()["phone_model"])
        new = Product.objects.for_tenant(self.c.tenant).get(phone_model=pm, condition__name="全新")
        Product.objects.filter(pk=new.pk).update(name="Galaxy A57 5G 128GB 冰藍 全新 公司貨")   # 人改過品名
        Product.objects.filter(phone_model=pm).exclude(pk=new.pk).delete()                       # 只剩那一個全新
        PhoneModel.objects.filter(pk=pm.pk).update(device_uid="")                                # 像是舊精靈建的、還沒對上
        r = self.c.admin.post(BUILD, {"uid": "u-a57"}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.assertEqual((r.json()["linked"], r.json()["created"]), (1, {"已拆封": 1, "中古機": 1}))
        self.assertEqual(Product.objects.for_tenant(self.c.tenant).filter(phone_model=pm, condition__name="全新").count(), 1)

