"""「新增手機型號」每個容量各自的建議售價(owner 2026-10-08:以前整批只有一個價錢,建完要一個一個改)。"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.inventory.models import Warehouse
from apps.tenants.models import Tenant, UserProfile

from .models import Brand, Category, Condition, PhoneModel, PhoneSeries, Product

URL = "/api/v1/products/create-phone-model/"


class PhoneWizardPriceTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="測試通訊行", code="demo")
        wh = Warehouse.objects.create(tenant=self.tenant, code="NY", name="湳雅店")
        user = get_user_model().objects.create_user(username="clerk", password="x")
        UserProfile.objects.create(user=user, role="tenant_user", tenant=self.tenant, default_warehouse=wh)
        self.api = APIClient()
        self.api.force_authenticate(user)
        self.brand = Brand.objects.create(tenant=self.tenant, code="apple", name="Apple")
        self.series = PhoneSeries.objects.create(tenant=self.tenant, brand=self.brand, code="iphone", name="iPhone")
        self.phones = Category.objects.create(tenant=self.tenant, code="PH", name="手機")
        self.new = Condition.objects.create(tenant=self.tenant, code="new", name="全新", sort_order=1)
        self.used = Condition.objects.create(tenant=self.tenant, code="used", name="中古機", sort_order=2,
                                             is_secondhand=True, tracks_unit_condition=True)

    def payload(self, **over):
        return {
            "brand_id": self.brand.id, "series_id": self.series.id, "generation": 17,
            "main_category_id": self.phones.id, "condition_ids": [self.new.id],
            "capacities": ["256GB", "512GB"], "colors": ["黑色", "白色"],
            **over,
        }

    def post(self, **over):
        return self.api.post(URL, self.payload(**over), format="json")

    def prices(self):
        """{品名: 建議售價}(資料庫裡現在的)"""
        return {p.name: p.list_price for p in Product.objects.filter(category=self.phones)}

    # ── 每個容量各自的價錢 ──
    def test_each_capacity_gets_its_own_price(self):
        r = self.post(list_prices={"256GB": "29900", "512GB": "36900"})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self.prices(), {
            "iPhone 17 256GB 黑色 全新": Decimal("29900"), "iPhone 17 256GB 白色 全新": Decimal("29900"),
            "iPhone 17 512GB 黑色 全新": Decimal("36900"), "iPhone 17 512GB 白色 全新": Decimal("36900"),
        })
        # 回來的每一列也帶著價錢
        self.assertEqual({m["name"]: m["list_price"] for m in r.json()["main"]}, {
            "iPhone 17 256GB 黑色 全新": "29900", "iPhone 17 256GB 白色 全新": "29900",
            "iPhone 17 512GB 黑色 全新": "36900", "iPhone 17 512GB 白色 全新": "36900",
        })

    def test_preview_shows_the_price_of_every_row_and_creates_nothing(self):
        r = self.post(list_prices={"256GB": "29900", "512GB": "36900"}, dry_run=True)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(sorted((m["capacity"], m["list_price"]) for m in r.json()["main"]),
                         [("256GB", "29900"), ("256GB", "29900"), ("512GB", "36900"), ("512GB", "36900")])
        self.assertEqual(self.prices(), {})
        self.assertEqual(Product.objects.filter(tenant=self.tenant).count(), 0)
        self.assertEqual(PhoneModel.objects.filter(tenant=self.tenant).count(), 0)   # 機型主檔也沒有多

    def test_every_condition_of_a_capacity_shares_the_price(self):
        """同一個容量不分品況都是這個價錢(已拆封、中古機另外逐台定價,這個只是預設)。"""
        r = self.post(condition_ids=[self.new.id, self.used.id], colors=["黑色"],
                      list_prices={"256GB": "29900", "512GB": "36900"})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self.prices(), {
            "iPhone 17 256GB 黑色 全新": Decimal("29900"), "iPhone 17 256GB 黑色 中古機": Decimal("29900"),
            "iPhone 17 512GB 黑色 全新": Decimal("36900"), "iPhone 17 512GB 黑色 中古機": Decimal("36900"),
        })

    # ── 沒給、給空的:用整批那一個(舊的呼叫端只給 list_price) ──
    def test_single_price_alone_still_applies_to_everything(self):
        r = self.post(list_price="19900")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self.prices(), {
            "iPhone 17 256GB 黑色 全新": Decimal("19900"), "iPhone 17 256GB 白色 全新": Decimal("19900"),
            "iPhone 17 512GB 黑色 全新": Decimal("19900"), "iPhone 17 512GB 白色 全新": Decimal("19900"),
        })

    def test_a_capacity_left_blank_falls_back_to_the_single_price(self):
        r = self.post(list_price="19900", list_prices={"256GB": "29900", "512GB": ""}, colors=["黑色"])
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self.prices(), {
            "iPhone 17 256GB 黑色 全新": Decimal("29900"), "iPhone 17 512GB 黑色 全新": Decimal("19900"),
        })

    def test_nothing_given_means_zero(self):
        r = self.post(colors=["黑色"], capacities=["256GB"])
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self.prices(), {"iPhone 17 256GB 黑色 全新": Decimal("0")})
        self.assertEqual(r.json()["main"][0]["list_price"], "0")

    def test_zero_is_a_real_zero_not_a_blank(self):
        """明講 0 就是 0,不會退回整批那一個。"""
        r = self.post(list_price="19900", list_prices={"256GB": "0", "512GB": 0}, colors=["黑色"])
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(set(self.prices().values()), {Decimal("0")})

    # ── 金額一律整數元 ──
    def test_prices_are_rounded_to_whole_dollars(self):
        r = self.post(list_prices={"256GB": "29900.5", "512GB": 36900.4}, colors=["黑色"])
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self.prices(), {
            "iPhone 17 256GB 黑色 全新": Decimal("29901"), "iPhone 17 512GB 黑色 全新": Decimal("36900"),
        })

    # ── 寫錯的要講,不能悄悄變成 0 元 ──
    def test_price_for_a_capacity_that_is_not_being_created_is_refused(self):
        r = self.post(list_prices={"256G": "29900", "512GB": "36900"})          # 256G ≠ 256GB
        self.assertEqual(r.status_code, 400, r.content)
        self.assertIn("256G", r.json()["detail"])
        self.assertEqual(self.prices(), {})

    def test_bad_prices_are_refused(self):
        for bad, word in (({"256GB": "abc"}, "數字"), ({"256GB": "-1"}, "負"), ({"256GB": "NaN"}, "數字"),
                          ({"256GB": "Infinity"}, "數字"), ("29900", "list_prices"), (["29900"], "list_prices")):
            with self.subTest(bad=bad):
                r = self.post(list_prices=bad)
                self.assertEqual(r.status_code, 400, r.content)
                self.assertIn(word, r.json()["detail"])
        for bad in ("abc", "-5"):
            with self.subTest(single=bad):
                self.assertEqual(self.post(list_price=bad).status_code, 400)
        self.assertEqual(self.prices(), {})

    def test_a_price_too_big_for_the_column_is_refused_already_at_preview(self):
        """欄位放得下的最大是 999,999,999,999。更大的在預覽就要講,不能預覽過了、按建立才出錯。"""
        for big in ("1000000000000", "999999999999.5", "1e28", 10 ** 15):
            for dry in (True, False):
                with self.subTest(big=big, dry_run=dry):
                    r = self.post(list_prices={"256GB": big}, dry_run=dry)
                    self.assertEqual(r.status_code, 400, r.content)
                    self.assertIn("256GB", r.json()["detail"])
                    self.assertIn("太大", r.json()["detail"])
        self.assertEqual(self.post(list_price="1e28", dry_run=True).status_code, 400)
        self.assertEqual(self.prices(), {})
        # 剛好放得下的最大值存得進去
        r = self.post(list_prices={"256GB": "999999999999", "512GB": "999999999998.5"}, colors=["黑色"])
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(set(self.prices().values()), {Decimal("999999999999")})

    def test_tiny_and_exponent_forms_follow_the_same_rounding(self):
        r = self.post(list_prices={"256GB": "1e-3", "512GB": "1e3"}, colors=["黑色"])
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self.prices(), {
            "iPhone 17 256GB 黑色 全新": Decimal("0"), "iPhone 17 512GB 黑色 全新": Decimal("1000"),
        })

    def test_the_same_capacity_given_twice_is_refused(self):
        """`"256GB"` 與 `" 256GB "` 去掉空白是同一個容量:哪一個價錢算數要看順序,不猜。"""
        for pair in ({"256GB": "29900", " 256GB ": "0"}, {" 256GB ": "0", "256GB": "29900"},
                     {"256GB": "29900", "256GB ": "29900"}):
            with self.subTest(pair=pair):
                r = self.post(list_prices=pair)
                self.assertEqual(r.status_code, 400, r.content)
                self.assertIn("兩次", r.json()["detail"])
        self.assertEqual(self.prices(), {})

    def test_single_price_given_as_other_empty_values_is_still_zero(self):
        """整批那一個以前給 false / [] / {} 都當成 0(直接打 API 的舊寫法),照舊。只有空白也是沒填。"""
        for n, empty in enumerate((False, [], {}, None, "", 0, "   ")):
            with self.subTest(empty=empty):
                r = self.post(list_price=empty, colors=["黑色"], capacities=["256GB"], generation=20 + n)
                self.assertEqual(r.status_code, 200, r.content)
                self.assertEqual(r.json()["main"][0]["list_price"], "0")

    def test_the_message_names_the_capacity(self):
        r = self.post(list_prices={"256GB": "29900", "512GB": "x"})
        self.assertEqual(r.status_code, 400, r.content)
        self.assertIn("512GB", r.json()["detail"])

    def test_blank_capacities_and_their_prices_are_simply_dropped(self):
        """容量那一串裡混了空的(範本帶進來的):那一個不建,它的價錢也不算寫錯,其餘照建。"""
        r = self.post(capacities=["256GB", "", "   "], colors=["黑色"],
                      list_prices={"256GB": "29900", "": "1", "   ": "2"})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self.prices(), {"iPhone 17 256GB 黑色 全新": Decimal("29900")})

    def test_capacity_keys_are_matched_after_trimming(self):
        r = self.post(capacities=[" 256GB "], colors=["黑色"], list_prices={" 256GB": "29900"})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self.prices(), {"iPhone 17 256GB 黑色 全新": Decimal("29900")})
