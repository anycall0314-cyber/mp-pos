from django.test import SimpleTestCase, TestCase

from apps.backup.tests.factory import Company
from apps.catalog import brand_names, device_expand
from apps.catalog.models import Brand, Category, CategoryBrand, PhoneSeries, Product
from apps.tenants import abilities
from apps.tenants.models import UserProfile

BRANDS = "/api/v1/brands/"
CATS = "/api/v1/categories/"


class SplitTests(SimpleTestCase):
    """品牌的中文 / 英文兩格(owner 2026-10-17)。"""

    def test_one_box_goes_to_the_right_half(self):
        s = brand_names.split
        self.assertEqual(s("膜總裁 MOCEO"), ("膜總裁", "MOCEO"), "中文一段、英文一段:拆成兩格")
        self.assertEqual(s("MOCEO 膜總裁"), ("膜總裁", "MOCEO"), "順序不拘")
        self.assertEqual(s("犀牛盾 Rhino Shield"), ("犀牛盾", "Rhino Shield"))
        self.assertEqual(s("AI膜速箱"), ("AI膜速箱", ""), "黏在一起的整段算中文")
        self.assertEqual(s("IMOS"), ("", "IMOS"))
        self.assertEqual(s("  "), ("", ""))
        self.assertEqual(brand_names.join("三星", "Samsung"), "三星 Samsung")
        self.assertEqual(brand_names.join("", "IMOS"), "IMOS")


class BrandNameTests(TestCase):
    def setUp(self):
        self.c = Company("a", "甲通訊行", "甲")
        self.t = self.c.tenant
        self.moceo = Brand.objects.create(tenant=self.t, code="moceo", name_zh="膜總裁", name_en="MOCEO")

    def test_the_shown_name_is_made_from_the_two_halves(self):
        self.assertEqual(self.moceo.name, "膜總裁 MOCEO")
        b = Brand.objects.create(tenant=self.t, code="dap", name="DAP")
        self.assertEqual((b.name_zh, b.name_en, b.name), ("", "DAP", "DAP"), "只給顯示名稱的(舊寫法)自動分")
        b.name_zh = "達普"
        b.save(update_fields=["name_zh"])
        b.refresh_from_db()
        self.assertEqual(b.name, "達普 DAP", "只存其中一格,顯示名稱也跟著存")

    def test_either_half_or_the_whole_name_finds_the_same_brand(self):
        for text in ("膜總裁", "moceo", "MOCEO", "膜總裁 MOCEO", " 膜總裁  moceo "):
            self.assertEqual(brand_names.find_brand(self.t, text), self.moceo, text)
        self.assertIsNone(brand_names.find_brand(self.t, "IMOS"))
        other = Company("b", "乙通訊行", "乙")
        self.assertIsNone(brand_names.find_brand(other.tenant, "MOCEO"), "別家的不算")

    def test_the_catalog_and_tidy_find_a_brand_by_its_english_name(self):
        samsung = Brand.objects.create(tenant=self.t, code="samsung", name_zh="三星", name_en="Samsung")
        before = Brand.objects.filter(tenant=self.t).count()
        self.assertEqual(device_expand._brand(self.t, "Samsung"), samsung, "型號庫寫 Samsung:補了中文名也是同一個")
        self.assertEqual(device_expand._brand(self.t, "三星"), samsung)
        self.assertEqual(Brand.objects.filter(tenant=self.t).count(), before)
        made = device_expand._brand(self.t, "犀牛盾 RhinoShield")
        self.assertEqual((made.name_zh, made.name_en), ("犀牛盾", "RhinoShield"))

    def test_the_brand_page_takes_two_halves_and_refuses_a_spelling_another_brand_has(self):
        a = self.c.admin
        r = a.post(BRANDS, {"name_zh": "太空盾"}, format="json")
        self.assertEqual(r.status_code, 201, r.content.decode())
        self.assertEqual((r.json()["name"], r.json()["name_en"]), ("太空盾", ""))
        self.assertTrue(r.json()["code"], "代碼沒給就自動產")
        r = a.post(BRANDS, {"name_zh": "", "name_en": " "}, format="json")
        self.assertEqual(r.status_code, 400, "至少一格")
        r = a.post(BRANDS, {"name_en": "moceo"}, format="json")
        self.assertEqual(r.status_code, 400, "英文跟膜總裁那一個一樣:同一個廠牌要用合併")
        self.assertIn("合併", str(r.json()))
        r = a.patch(f"{BRANDS}{self.moceo.pk}/", {"name_en": "MOCEO TW"}, format="json")
        self.assertEqual((r.status_code, r.json()["name"]), (200, "膜總裁 MOCEO TW"))
        r = a.post(BRANDS, {"name": "IMOS"}, format="json")
        self.assertEqual((r.status_code, r.json()["name_en"]), (201, "IMOS"), "舊的呼叫端只送 name 照樣能建")

    def test_a_phone_brand_keeps_its_english_name(self):
        """型號庫每天自動新增新機時照英文(Samsung)找品牌;拿掉英文會多建一個,同一支手機的庫存拆兩邊。"""
        samsung = Brand.objects.create(tenant=self.t, code="samsung", name="Samsung")
        PhoneSeries.objects.create(tenant=self.t, brand=samsung, code="gs", name="Galaxy S")
        r = self.c.admin.patch(f"{BRANDS}{samsung.pk}/", {"name_zh": "三星", "name_en": ""}, format="json")
        self.assertEqual(r.status_code, 400)
        r = self.c.admin.patch(f"{BRANDS}{samsung.pk}/", {"name_zh": "三星"}, format="json")
        self.assertEqual((r.status_code, r.json()["name"]), (200, "三星 Samsung"), "補中文可以")
        r = self.c.admin.patch(f"{BRANDS}{self.moceo.pk}/", {"name_en": ""}, format="json")
        self.assertEqual((r.status_code, r.json()["name"]), (200, "膜總裁"), "配件廠牌可以只留中文")

    def test_only_changing_order_does_not_recheck_names(self):
        # 舊資料可能已經有大小寫不同的兩個(IMOS / imos);只改排序、啟用不能被擋
        Brand.objects.create(tenant=self.t, code="imos", name="IMOS")
        dup = Brand.objects.create(tenant=self.t, code="imos2", name="imos")
        r = self.c.admin.patch(f"{BRANDS}{dup.pk}/", {"sort_order": 9, "is_active": False}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        r = self.c.admin.patch(f"{BRANDS}{dup.pk}/", {"name_zh": "", "name_en": "imos", "sort_order": 3}, format="json")
        self.assertEqual(r.status_code, 200, "品牌頁連沒改的名字一起送:照樣能存(複審 P2)")

    def test_the_two_halves_together_must_fit(self):
        r = self.c.admin.post(BRANDS, {"name_zh": "牌" * 40, "name_en": "A" * 40}, format="json")
        self.assertEqual(r.status_code, 400, "合起來 81 字超過顯示名稱的長度:擋下來,不是 500(複審 P2)")

    def test_typing_an_existing_english_name_in_the_product_form_picks_that_brand(self):
        case = Category.objects.get(tenant=self.t, name="皮套")
        before = Brand.objects.filter(tenant=self.t).count()
        r = self.c.admin.post(f"{CATS}{case.pk}/brands/", {"name": "moceo"}, format="json")
        self.assertEqual((r.status_code, r.json()["linked_brand"]), (200, self.moceo.pk))
        self.assertEqual(Brand.objects.filter(tenant=self.t).count(), before, "打英文不會多建一個")
        r = self.c.admin.post(f"{CATS}{case.pk}/brands/", {"name": "膜總裁 MOCEO"}, format="json")
        self.assertEqual(r.json()["linked_brand"], self.moceo.pk)


class MergeTests(TestCase):
    """紅隊:同一個廠牌中英文各建一次、「太空盾 / 真太空盾」,沒有合併就修不回來。"""

    def setUp(self):
        self.c = Company("a", "甲通訊行", "甲")
        t = self.t = self.c.tenant
        self.case = Category.objects.get(tenant=t, name="皮套")
        self.back = Category.objects.create(tenant=t, code="BK", name="背蓋")
        self.zh = Brand.objects.create(tenant=t, code="mz", name_zh="膜總裁")
        self.en = Brand.objects.create(tenant=t, code="me", name_en="MOCEO")
        CategoryBrand.objects.create(tenant=t, category=self.case, brand=self.zh)
        CategoryBrand.objects.create(tenant=t, category=self.case, brand=self.en)
        CategoryBrand.objects.create(tenant=t, category=self.back, brand=self.en)
        mk = lambda name, b: Product.objects.create(tenant=t, category=self.case, name=name, brand=b, requires_serial=False)  # noqa: E731
        self.p1, self.p2, self.p3 = mk("皮套/膜總裁/1", self.zh), mk("皮套/MOCEO/2", self.en), mk("皮套/MOCEO/3", self.en)

    def url(self, b):
        return f"{BRANDS}{b.pk}/merge/"

    def test_merging_moves_products_and_links_and_fills_the_missing_half(self):
        r = self.c.admin.post(self.url(self.en), {"into": self.zh.pk}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.assertEqual((r.json()["moved"], r.json()["brand"]["name"]), (2, "膜總裁 MOCEO"))
        self.assertFalse(Brand.objects.filter(pk=self.en.pk).exists())
        self.assertEqual({p.brand_id for p in Product.objects.filter(pk__in=[self.p1.pk, self.p2.pk, self.p3.pk])}, {self.zh.pk})
        self.assertEqual(sorted(CategoryBrand.objects.filter(brand=self.zh).values_list("category__name", flat=True)), ["皮套", "背蓋"],
                         "兩個都掛在皮套的只留一個;只有 MOCEO 掛的背蓋搬過來")

    def test_a_phone_brand_other_company_or_itself_cannot_be_merged(self):
        apple = Brand.objects.create(tenant=self.t, code="apple", name="Apple")
        PhoneSeries.objects.create(tenant=self.t, brand=apple, code="ip", name="iPhone")
        r = self.c.admin.post(self.url(apple), {"into": self.zh.pk}, format="json")
        self.assertEqual(r.status_code, 400, "底下有手機型號的不併")
        self.assertTrue(Brand.objects.filter(pk=apple.pk).exists())
        self.assertEqual(self.c.admin.post(self.url(self.en), {"into": self.en.pk}, format="json").status_code, 400)
        other = Company("b", "乙通訊行", "乙")
        theirs = Brand.objects.create(tenant=other.tenant, code="x", name="X")
        self.assertEqual(self.c.admin.post(self.url(self.en), {"into": theirs.pk}, format="json").status_code, 400, "併到別家的不行")
        self.assertEqual(other.admin.post(self.url(self.en), {"into": theirs.pk}, format="json").status_code, 400, "別家不能併我的")
        self.assertEqual(Product.objects.filter(brand=self.en).count(), 2, "都沒有動")

    def test_merging_needs_the_product_setup_ability(self):
        UserProfile.objects.filter(user=self.c.clerk_user).update(denied_abilities=[abilities.EDIT_PRODUCTS])
        self.c.clerk_user.profile.refresh_from_db()
        self.assertEqual(self.c.clerk.post(self.url(self.en), {"into": self.zh.pk}, format="json").status_code, 403)
        self.assertTrue(Brand.objects.filter(pk=self.en.pk).exists())
