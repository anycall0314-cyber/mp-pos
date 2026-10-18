"""新的 iPad 自己算第幾代(V3;owner 2026-10-18「你一路做完」):表上沒有的 iPad 照名稱與上市年份算,
店內寫法(`AIR9/11吋`、`MINI8`、`IPAD12`)對得到每天自動加進型號庫的新 iPad。規則在 `accessory_names._ipad_specs`。"""
from django.test import SimpleTestCase, TestCase

from apps.backup.tests.factory import Company
from apps.catalog import accessory_names as an
from apps.catalog.models import Brand, Category, DeviceModel, PhoneModel


class SpecTests(SimpleTestCase):
    def specs(self, *rows):
        got = an._ipad_specs([(i, name, launched) for i, (name, launched) in enumerate(rows)])
        return [got.get(i) for i in range(len(rows))]

    def test_the_other_way_the_catalog_writes_them_matches_apple(self):
        """測試站型號庫真的有、表上沒有的 12 支(寫法是「系列 (年份) 尺寸」):算出來的代數跟 Apple 的一樣。"""
        rows = [("iPad mini (2021)", "2021-11"), ("iPad (2021)", "2021-11"), ("iPad Air (2022)", "2022-04"),
                ("iPad (2022)", "2022-12-05"), ("iPad Air (2024) 13 吋", "2024-06"), ("iPad Pro (2024) 11 吋", "2024-06-24"),
                ("iPad Pro (2024) 13 吋", "2024-06-24"), ("iPad Air (2024) 11 吋", "2024-06-24"), ("iPad mini (2024)", "2024-11"),
                ("iPad Air (2025) 11 吋", "2025-03-01"), ("iPad Air (2025) 13 吋", "2025-03-01"), ("iPad (2025)", "2025-03-01")]
        self.assertEqual(self.specs(*rows), [
            ("MINI", 6, "8.3", 2021), ("", 9, "10.2", 2021), ("AIR", 5, "10.9", 2022), ("", 10, "10.9", 2022),
            ("AIR", 6, "13", 2024), ("PRO", 0, "11", 2024), ("PRO", 0, "13", 2024), ("AIR", 6, "11", 2024),
            ("MINI", 7, "8.3", 2024), ("AIR", 7, "11", 2025), ("AIR", 7, "13", 2025), ("", 11, "11", 2025)])

    def test_new_ones_come_after_the_last_known_generation(self):
        self.assertEqual(self.specs(("iPad Air 11吋 (M5)", "2027-03"), ("iPad Air 13吋 (M5)", "2027-03"),
                                    ("iPad Air (2028) 11 吋", ""), ("iPad mini (A19 Pro)", "2026-10"),
                                    ("iPad 12 (A18)", "2027-02"), ("iPad Pro 11吋 (M6)", "2027-05")), [
            ("AIR", 9, "11", 2027), ("AIR", 9, "13", 2027), ("AIR", 10, "11", 2028),   # 表上最後是 2026 的 Air 8
            ("MINI", 8, "8.3", 2026), ("", 12, "11", 2027), ("PRO", 0, "11", 2027)])

    def test_the_same_year_is_the_same_generation(self):
        # 表上 2014 年是 Air 2、之前沒有 Air:同一年就是第 2 代(不是從 0 往上數)
        self.assertEqual(self.specs(("iPad Air (2014)", "")), [("AIR", 2, "9.7", 2014)])

    def test_the_table_still_wins_and_unclear_ones_are_left_out(self):
        self.assertEqual(self.specs(("iPad Air 5 (M1)", "2099-01"), ("iPad Air 11吋", ""), ("Galaxy Tab S10", "2026-01"),
                                    ("iPad Pro 11吋 (M4)", "")),
                         [("AIR", 5, "10.9", 2022), None, None, ("PRO", 0, "11", 2024)])   # 看不出年份的不算


class StoreWordsTests(TestCase):
    def setUp(self):
        self.c = Company("a", "甲通訊行", "甲")
        t = self.c.tenant
        apple = Brand.objects.create(tenant=t, code="AP", name="Apple")
        for uid, name, launched in [("u-air8", "iPad Air (2026) 11 吋", "2026-03"), ("u-air9", "iPad Air 11吋 (M5)", "2027-03"),
                                    ("u-air9l", "iPad Air 13吋 (M5)", "2027-03")]:
            DeviceModel.objects.create(uid=uid, category="tablet", brand="Apple", name=name, launched=launched, content_hash=uid)
            PhoneModel.objects.create(tenant=t, code=uid, name=name, match_key=name.casefold(), brand=apple, device_uid=uid)
        self.case = Category.objects.create(tenant=t, code="LC2", name="皮套2")

    def names(self, text):
        r = self.c.admin.get("/api/v1/products/fit-suggest/", {"name": text, "category": self.case.id}).json()
        return [m["model_name"] for m in r["models"]]

    def test_the_store_way_of_writing_finds_the_new_ipad(self):
        self.assertEqual(self.names("皮套/IPAD/AIR9/11吋"), ["iPad Air 11吋 (M5)"])
        self.assertEqual(self.names("皮套/IPAD/AIR8-9/11吋"), ["iPad Air (2026) 11 吋", "iPad Air 11吋 (M5)"])
        self.assertEqual(self.names("皮套/IPAD/AIR/11吋(2027)"), ["iPad Air 11吋 (M5)"])
        self.assertEqual(self.names("皮套/IPAD/AIR9"), [])          # 11、13 吋都有:沒寫尺寸不猜
