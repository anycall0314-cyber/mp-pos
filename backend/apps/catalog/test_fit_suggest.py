"""新增配件時照品名先勾好適用機型(V2;owner 2026-10-18「你一路做完」)。規則在 `fit_suggest.py`。全部是假資料。"""
from django.test import TestCase

from apps.backup.tests.factory import Company
from apps.catalog import device_share
from apps.catalog.models import Brand, Category, DeviceModel, PhoneModel


class SuggestTests(TestCase):
    def setUp(self):
        self.c = Company("a", "甲通訊行", "甲")
        t = self.c.tenant
        apple = Brand.objects.create(tenant=t, code="AP", name="Apple")
        samsung = Brand.objects.create(tenant=t, code="SA", name="Samsung")
        for uid, name, brand, cat in [("u-15pm", "iPhone 15 Pro Max", apple, "phone"), ("u-16pm", "iPhone 16 Pro Max", apple, "phone"),
                                      ("u-17pm", "iPhone 17 Pro Max", apple, "phone"), ("u-s25", "Galaxy S25", samsung, "phone"),
                                      ("u-pro11", "iPad Pro (2018) 11 吋", apple, "tablet")]:
            DeviceModel.objects.create(uid=uid, category=cat, brand=brand.name, name=name, content_hash=uid)
            PhoneModel.objects.create(tenant=t, code=uid, name=name, match_key=name.casefold(), brand=brand, device_uid=uid)
        self.glass = Category.objects.create(tenant=t, code="PP", name="玻璃貼")
        self.case = self.c.cat_case
        device_share.set_rule("u-16pm", "u-15pm", screen=True, body=False)
        device_share.set_rule("u-17pm", "u-16pm", screen=True, body=False)

    def get(self, **params):
        r = self.c.admin.get("/api/v1/products/fit-suggest/", params)
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        return [m["model_name"] for m in body["models"]], [m["model_name"] for m in body["shared"]], body["unsure"]

    def test_the_name_gives_the_model_and_the_glass_also_gets_the_shared_new_ones(self):
        self.assertEqual(self.get(name="9H/IMOS/IP15PM/防窺", category=self.glass.id),
                         (["iPhone 15 Pro Max"], ["iPhone 16 Pro Max", "iPhone 17 Pro Max"], []))   # 一路往下
        self.assertEqual(self.get(name="皮套/IP15PM/黑", category=self.case.id),
                         (["iPhone 15 Pro Max"], [], []))                                         # 殼:機身沒勾
        self.assertEqual(self.get(name="9H/SAM/S25", category=self.glass.id), (["Galaxy S25"], [], []))

    def test_a_model_picked_by_hand_brings_the_shared_ones_too(self):
        self.assertEqual(self.get(keys="iphone 16 pro max", category=self.glass.id), ([], ["iPhone 17 Pro Max"], []))
        self.assertEqual(self.get(keys="iphone 15 pro max,iphone 16 pro max", category=self.glass.id),
                         ([], ["iPhone 17 Pro Max"], []))                                         # 已經挑的不重複帶

    def test_unclear_names_are_not_guessed(self):
        self.assertEqual(self.get(name="皮套/IPAD/PRO/11吋", category=self.case.id), ([], [], ["PRO/11吋"]))
        self.assertEqual(self.get(name="9H/防窺", category=self.glass.id), ([], [], []))
        self.assertEqual(self.get(name="", category=self.glass.id), ([], [], []))

    def test_another_companys_category_is_not_used(self):
        other = Company("b", "乙通訊行", "乙")
        glass_b = Category.objects.create(tenant=other.tenant, code="PP", name="玻璃貼")
        self.assertEqual(self.get(name="9H/IP15PM", category=glass_b.id), (["iPhone 15 Pro Max"], [], []))
        r = other.admin.get("/api/v1/products/fit-suggest/", {"name": "9H/IP15PM", "category": glass_b.id}).json()
        self.assertEqual((r["models"], r["shared"]), ([], []))                                    # 乙沒有這些機型
