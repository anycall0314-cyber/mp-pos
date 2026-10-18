"""M1-E 第二段:從品名認適用機型(`accessory_names`)與一次整理(`shop_tidy`)。品名都是店裡真的寫法,資料是假的。"""
from django.test import SimpleTestCase, TestCase

from apps.backup.tests.factory import Company
from apps.catalog import accessory_names as an
from apps.catalog import shop_tidy
from apps.catalog.views import _fitting_accessory_ids
from apps.catalog.models import Brand, Category, CategoryBrand, DeviceModel, PhoneModel, Product, ProductRelation
from apps.tenants.models import Tenant

MODELS = [
    ("Apple", n) for n in ("iPhone 5", "iPhone 5s", "iPhone SE", "iPhone 6", "iPhone 6 Plus", "iPhone 7 Plus", "iPhone 11",
                           "iPhone 11 Pro", "iPhone 11 Pro Max", "iPhone 15 Pro Max", "iPhone 16e", "iPhone 17e", "iPhone 17",
                           "iPhone XR", "iPad (2019)", "iPad (2020)", "iPad 9", "iPad 10", "iPad 11 (A16)", "iPad 5", "iPad 6",
                           "iPad Air 2", "iPad Air (2020)", "iPad Air 5 (M1)", "iPad Air 11吋 (M2)", "iPad Air 13吋 (M2)",
                           "iPad Air 11吋 (M3)", "iPad Air 13吋 (M3)", "iPad mini 4", "iPad mini (2019)",
                           "iPad Pro (2018) 11 吋", "iPad Pro (2020) 11 吋", "iPad Pro (2020) 12.9 吋",
                           "iPad Pro 11吋 (M4)", "iPad Pro 13吋 (M4)")
] + [
    ("Samsung", n) for n in ("Galaxy S 25 Ultra", "Galaxy S6", "Galaxy S8", "Galaxy Tab S6 Lite", "Galaxy Tab S10 FE 5G",
                             "Galaxy Tab S10 FE Wi-Fi", "Galaxy A51", "Galaxy A51 5G", "Galaxy M53 5G", "Galaxy A 53 5G",
                             "Galaxy A 16 5G")
] + [
    ("OPPO", "Find X9 Ultra"), ("OPPO", "OPPO Reno15 Pro Max"), ("OPPO", "RENO 12"), ("OPPO", "Reno 7 Pro"),
    ("Xiaomi", "Redmi Note 15 Pro+ 5G"), ("Xiaomi", "Redmi Pad 2"), ("Xiaomi", "Redmi Pad 2 9.7"), ("POCO", "POCO C85"), ("Xiaomi", "Xiaomi Pad 7"), ("Google", "Pixel 7 Pro"),
    ("ASUS", "ROG Phone 5s"), ("ASUS", "ZenFone 6 (ZS630KL)"), ("Nokia", "Nokia T21"), ("VIVO", "vivo X300 Pro"),
    ("HUAWEI", "HUAWEI P30 Pro 頂配版"), ("HUAWEI", "HUAWEI P30 Pro 高配版"), ("HTC", "Desire 22 Pro"),
]


class ParseTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.idx = an.build_index([(i, name, brand) for i, (brand, name) in enumerate(MODELS)])

    def fits(self, name):
        return sorted(self.idx.names[m] for m in an.parse(name, self.idx).models)

    def test_iphone_shorthand(self):
        self.assertEqual(self.fits("背蓋/DAP/IP6+/多工插卡"), ["iPhone 6 Plus"])
        self.assertEqual(self.fits("保貼/IP7P/亮"), ["iPhone 7 Plus"], "7 沒有 Pro:P = Plus")
        self.assertEqual(self.fits("背蓋/IMOS/IP11P/黑"), ["iPhone 11 Pro"], "11 有 Pro:P = Pro")
        self.assertEqual(self.fits("背蓋/IMOS/IP16E/17E/磁吸/黑"), ["iPhone 16e", "iPhone 17e"], "後面那幾款省略 IP")
        self.assertEqual(self.fits("邊框/IP6-金屬防爆"), ["iPhone 6"])
        self.assertEqual(self.fits("邊框/IP6-DEVIA"), ["iPhone 6"])
        self.assertEqual(self.fits("維修料/XR/LCD"), ["iPhone XR"])

    def test_the_brand_in_front_decides_where_to_look(self):
        self.assertEqual(self.fits("背蓋/IP5/5S/SE/真皮"), ["iPhone 5", "iPhone 5s", "iPhone SE"], "5S 不是 ROG Phone 5s")
        self.assertEqual(self.fits("鏡頭環/IP11/12/單環/藍寶石"), ["iPhone 11"], "12 不是 Reno 12")
        self.assertEqual(self.fits("皮套/小米-PAD7/7PRO/筆槽"), ["Xiaomi Pad 7"], "7PRO 不是 Pixel 7 Pro / Reno 7 Pro")
        self.assertEqual(self.fits("9H/滿/SAM/S25U/黑"), ["Galaxy S 25 Ultra"])
        self.assertEqual(self.fits("空壓/SAM/M53(5G)"), ["Galaxy M53 5G"], "M53 不是 A53")
        self.assertEqual(self.fits("空壓/SAM/A51"), ["Galaxy A51"], "沒寫 5G 的先找沒有 5G 的那一支")
        self.assertEqual(self.fits("皮套/OPPO/RENO15PM/黑"), ["OPPO Reno15 Pro Max"])
        self.assertEqual(self.fits("背蓋/太空盾/KI/OPPO/FIND/X9U/磁支+掛/黑"), ["Find X9 Ultra"])
        self.assertEqual(self.fits("皮套/紅米-NOTE15P+(5G)/黑"), ["Redmi Note 15 Pro+ 5G"])
        self.assertEqual(self.fits("背蓋/VIVO/X300PRO超聲波"), ["vivo X300 Pro"], "顏色 / 款式黏在後面")
        self.assertEqual(self.fits("空壓/HTC/D22PRO"), ["Desire 22 Pro"])

    def test_tablets_and_editions(self):
        self.assertEqual(self.fits("皮套/平板/SAM/S10FE/筆槽/黑"), ["Galaxy Tab S10 FE 5G", "Galaxy Tab S10 FE Wi-Fi"],
                         "寫了平板就找 Tab;5G / Wi-Fi 版配件通用")
        self.assertEqual(self.fits("保貼/華為/P30PRO/霧"), ["HUAWEI P30 Pro 頂配版", "HUAWEI P30 Pro 高配版"])
        self.assertEqual(self.fits("皮套/平板/SAM/S6/黑"), [], "寫了平板、沒有 Tab S6:不能掛到手機 Galaxy S6(複審 P1)")
        self.assertEqual(self.fits("空壓/SAM/M53(4G)"), [], "寫明 4G、只有 M53 5G:不能對到 5G 那一支(複審 P1)")
        self.assertEqual(self.fits("空壓/SAM/A51(4G)"), ["Galaxy A51"], "有沒寫連線的那一支就是它")
        self.assertEqual(self.fits("9H/平板/紅米-PAD2/9.7吋"), ["Redmi Pad 2 9.7"], "後面的尺寸挑對那一支")
        self.assertEqual(self.fits("9H/平板/紅米-PAD2/11吋"), ["Redmi Pad 2"])

    def test_ipad_shorthand(self):
        """owner 2026-10-16:「iPad皮套是我最頭痛的，很常找不到，也看不懂」。代數 / 尺寸 / 年份照 Apple 的查表。"""
        f = self.fits
        self.assertEqual(f("皮套/平板/DAP/IPAD7/8/10.2/立架黑"), ["iPad (2019)", "iPad (2020)"], "IPAD7/8 = 第 7、8 代")
        self.assertEqual(f("皮套/IPAD/10.2/旋轉支架/黑"), ["iPad (2019)", "iPad (2020)", "iPad 9"], "只寫尺寸:10.2 吋的都算")
        self.assertEqual(f("9H/平板/IMOS/低藍光/IPAD/7.8.9/10.2吋"), ["iPad (2019)", "iPad (2020)", "iPad 9"])
        self.assertEqual(f("皮套/平板/DAP/IPAD/10/11代/筆槽/黑"), ["iPad 10", "iPad 11 (A16)"])
        self.assertEqual(f("9H/平板/IPAD/AIR2/IPAD5/6/9.7"), ["iPad 5", "iPad 6", "iPad Air 2"])
        self.assertEqual(f("皮套/平板/IPAD/AIR4-8/11吋/筆槽/黑"),
                         ["iPad Air (2020)", "iPad Air 11吋 (M2)", "iPad Air 11吋 (M3)", "iPad Air 5 (M1)"], "4-8 是範圍、11 吋含 10.9")
        self.assertEqual(f("皮套/平板/IPAD/AIR6/7/13吋/筆槽/黑"), ["iPad Air 13吋 (M2)", "iPad Air 13吋 (M3)"])
        self.assertEqual(f("9H/平板/IPAD/AIR/11吋(2024/2025)"), ["iPad Air 11吋 (M2)", "iPad Air 11吋 (M3)"], "年份被斜線拆開也認")
        self.assertEqual(f("皮套/平板/IPAD/PRO/11吋(2024)/筆槽/黑"), ["iPad Pro 11吋 (M4)"])
        self.assertEqual(f("皮套/平板/DAP/IPAD/PRO11吋/2020/粉"), ["iPad Pro (2020) 11 吋"])
        self.assertEqual(f("皮套/平板/IPAD/12.9(2020)/三折綠"), ["iPad Pro (2020) 12.9 吋"], "12.9 吋只有 Pro")
        self.assertEqual(f("9H/平板/ANANK/PRO/11吋(2024)/類紙膜"), ["iPad Pro 11吋 (M4)"], "寫了平板、沒寫 IPAD 也認")
        self.assertEqual(f("保貼/平板/IPAD-MINI4/MINI5-亮"), ["iPad mini (2019)", "iPad mini 4"])
        r = an.parse("皮套/IPAD/AIR4-7/PRO11/旋轉支架/黑", self.idx)
        self.assertEqual(sorted(self.idx.names[m] for m in r.models),
                         ["iPad Air (2020)", "iPad Air 11吋 (M2)", "iPad Air 11吋 (M3)", "iPad Air 5 (M1)"], "Air 6、7 只要 11 吋")
        self.assertEqual(r.unsure, ["PRO11"], "Pro 11 吋沒寫年份:好幾代機身不一樣,交給 owner")
        self.assertEqual(an.parse("皮套/平板/DAP/IPAD/PRO/11/三折金", self.idx).unsure, ["PRO/11"])
        self.assertEqual(an.parse("保貼/平板/IPAD-MINI-亮", self.idx).unsure, ["MINI"])
        self.assertEqual(an.parse("9H/平板/IPAD/PRO/10.5吋", self.idx).unsure, [], "寫清楚了、型號庫沒有:不問")
        only_m4 = an.build_index([(1, "iPad Pro 11吋 (M4)", "Apple", "tablet"), (2, "iPad mini 6", "Apple", "tablet")])
        r = an.parse("皮套/平板/DAP/IPAD/PRO/11/三折金", only_m4)
        self.assertEqual((r.models, r.unsure), (set(), ["PRO/11"]), "型號庫只有一台 Pro 11 吋也不掛(複審 P1)")
        self.assertEqual(an.parse("保貼/平板/IPAD-MINI-亮", only_m4).models, set())
        loose = an.parse("ipad/pro/11", self.idx, loose=True)
        self.assertEqual(len(loose.models), 3, "搜尋時沒寫年份的也全部算")

    def test_does_not_guess(self):
        self.assertEqual(self.fits("背蓋/T21/IP15PM/全透磁吸"), ["iPhone 15 Pro Max"], "沒寫品牌的 T21 不是 Nokia T21")
        self.assertEqual(self.fits("保貼/SE-NEO/亮"), [], "SE-NEO 是 Sony Ericsson,不是 iPhone SE")
        self.assertEqual(self.fits("保貼/SE暢動系列"), [], "沒寫品牌的 SE 不猜")
        self.assertEqual(self.fits("皮套/SAM/S6-LITE/桃"), [], "S6-LITE 是平板 Tab S6 Lite,不拆成 S6")
        self.assertEqual(self.fits("皮套/ASUS/6吋"), [], "6吋是尺寸")
        self.assertEqual(self.fits("觸控筆/STYLUS/防誤觸/IPAD專用"), [], "只寫 IPAD 不知道是哪一台")
        self.assertEqual(self.fits("背蓋/太空盾/MATTO/A16/磁吸"), [], "沒寫品牌的 A16 不猜")


def _device_model(uid, category, brand, name):
    return DeviceModel.objects.create(uid=uid, category=category, brand=brand, name=name, content_hash=uid)


class TidyTests(TestCase):
    def setUp(self):
        self.c = Company("JB", "甲通訊行", "甲")
        t = self.t = self.c.tenant
        cat = lambda code, name, **kw: Category.objects.create(tenant=t, code=code, name=name, **kw)   # noqa: E731
        self.watch = cat("WH", "手錶", holds_devices=True, needs_host_model=False)
        self.ear = cat("EP", "耳機/音訊", needs_host_model=False)
        self.band = cat("WB", "穿戴/周邊", needs_host_model=False)
        self.cable = cat("CH", "充電/線材", needs_host_model=False)
        self.back = cat("BK", "背蓋")
        self.sony = Brand.objects.create(tenant=t, code="sony", name="Sony")
        self.samsung = Brand.objects.create(tenant=t, code="samsung", name="Samsung")
        apple = Brand.objects.create(tenant=t, code="apple", name="Apple")
        _device_model("h1", "headphones", "Sony", "WF-1000XM6")
        pm = PhoneModel.objects.create(tenant=t, code="wf", name="WF-1000XM6", match_key="wf-1000xm6", brand=self.sony,
                                       device_uid="h1")
        self.ip17 = PhoneModel.objects.create(tenant=t, code="ip17", name="iPhone 17", match_key="iphone 17", brand=apple)
        PhoneModel.objects.create(tenant=t, code="s25u", name="Galaxy S 25 Ultra", match_key="galaxy s 25 ultra",
                                  brand=self.samsung)
        mk = lambda c, name, **kw: Product.objects.create(tenant=t, category=c, name=name, requires_serial=False, **kw)  # noqa: E731
        self.xm6 = mk(self.ear, "WF-1000XM6 黑 台版 全新", brand=self.sony, phone_model=pm)
        CategoryBrand.objects.create(tenant=t, category=self.ear, brand=self.sony)
        self.tws = mk(self.ear, "藍芽/YESIDO/TWS45/降噪入耳式")
        self.ear_case = mk(self.ear, "耳機套/AIRPODS4/彈蓋/象牙白")
        self.wired = mk(self.ear, "原耳/SAM/3.5MM")
        self.charger = mk(self.cable, "旅充/三星/EP-T2510/25W")
        self.dock = mk(self.cable, "台座/SAM/快充")                              # 台X 是副廠:SAM 是給三星用的
        self.dap = mk(self.back, "背蓋/DAP/IP17/透")
        self.s25 = mk(self.back, "9H/滿/SAM/S25U/黑")
        self.mine = mk(self.back, "背蓋/IMOS/IP17/磁吸", brand=self.sony)        # 已經有品牌的不動
        self.linked = mk(self.back, "背蓋/DAP/S25U/透")                          # 已經有適用機型的不動
        ProductRelation.objects.create(tenant=t, host_model=self.ip17, accessory_product=self.linked)
        self.answers = {"makers": ["DAP", "IMOS", "YESIDO"],
                        "wear": {"藍芽/YESIDO/TWS45/降噪入耳式": "earbuds", "耳機套/AIRPODS4/彈蓋/象牙白": "other"}}

    def fresh(self, p):
        return Product.objects.select_related("category", "brand").get(pk=p.pk)

    def test_a_dry_run_writes_nothing(self):
        before = (list(Category.objects.filter(tenant=self.t).values_list("name", flat=True)),
                  ProductRelation.objects.count(), list(Product.objects.filter(tenant=self.t).values_list("category", "brand")))
        r = shop_tidy.tidy(self.t, self.answers)
        self.assertEqual(r.renamed, ["充電/線材 → 傳輸線", "手錶 → 穿戴"])
        self.assertEqual(before, (list(Category.objects.filter(tenant=self.t).values_list("name", flat=True)),
                                  ProductRelation.objects.count(),
                                  list(Product.objects.filter(tenant=self.t).values_list("category", "brand"))))

    def test_it_does_the_three_things_and_leaves_what_was_already_set(self):
        r = shop_tidy.tidy(self.t, self.answers, confirm=True)
        names = set(Category.objects.filter(tenant=self.t).values_list("name", flat=True))
        self.assertTrue({"傳輸線", "穿戴"} <= names and not names & {"充電/線材", "手錶"})
        # 搬到穿戴:型號庫的耳機(規則)+ Jev 說是藍牙耳機的舊品名;耳機套、有線耳機不搬
        self.assertEqual({p.name: self.fresh(p).category.name for p in (self.xm6, self.tws, self.ear_case, self.wired)},
                         {self.xm6.name: "穿戴", self.tws.name: "穿戴", self.ear_case.name: "耳機/音訊", self.wired.name: "耳機/音訊"})
        self.assertEqual(r.moved, {"耳機/音訊": 2})
        self.assertTrue(CategoryBrand.objects.filter(category=self.watch, brand=self.sony).exists())
        self.assertFalse(CategoryBrand.objects.filter(category=self.ear, brand=self.sony).exists(), "舊類別沒有 Sony 了")
        # 廠牌:配件類別的 SAM 是手機品牌、不是廠牌;一般類別的手機品牌是原廠
        brand = lambda p: (self.fresh(p).brand.name if self.fresh(p).brand_id else None)   # noqa: E731
        self.assertEqual([brand(p) for p in (self.tws, self.wired, self.charger, self.dock, self.dap, self.s25, self.mine,
                                             self.ear_case)],
                         ["YESIDO", "Samsung", "Samsung", None, "DAP", None, "Sony", None])
        self.assertTrue(CategoryBrand.objects.filter(category=self.back, brand__name="DAP").exists())
        self.assertTrue(CategoryBrand.objects.filter(category=self.cable, brand=self.samsung).exists())
        # 適用機型:只有配件類別、只有還沒有的
        fits = lambda p: sorted(ProductRelation.objects.filter(accessory_product=p).values_list("host_model__name", flat=True))  # noqa: E731
        self.assertEqual((fits(self.dap), fits(self.s25), fits(self.linked), fits(self.charger)),
                         (["iPhone 17"], ["Galaxy S 25 Ultra"], ["iPhone 17"], []))
        self.assertEqual(ProductRelation.objects.get(accessory_product=self.dap).host_model_key, "iphone 17")
        # 再跑一次什麼都不變
        again = shop_tidy.tidy(self.t, self.answers, confirm=True)
        self.assertEqual((again.renamed, sum(again.moved.values()), sum(again.makers.values()), again.fit_links), ([], 0, 0, 0))

    def test_owner_picked_fits_and_unclear_ipads(self):
        apple = Brand.objects.get(tenant=self.t, name="Apple")
        PhoneModel.objects.create(tenant=self.t, code="pro11", name="iPad Pro (2020) 11 吋", match_key="ipad pro 2020 11",
                                  brand=apple)
        PhoneModel.objects.create(tenant=self.t, code="pro11m4", name="iPad Pro 11吋 (M4)", match_key="ipad pro 11 m4",
                                  brand=apple)
        unclear = Product.objects.create(tenant=self.t, category=self.back, name="皮套/平板/DAP/IPAD/PRO/11/三折金",
                                         requires_serial=False)
        r = shop_tidy.tidy(self.t, self.answers)
        self.assertIn(("背蓋", unclear.name, "PRO/11"), r.unsure, "沒寫年份的 Pro 11 吋不掛、列出來")
        with self.assertRaisesMessage(shop_tidy.TidyError, "iPad Pro 9"):
            shop_tidy.tidy(self.t, {**self.answers, "fits": {unclear.name: ["iPad Pro 9"]}}, confirm=True)
        self.assertFalse(ProductRelation.objects.filter(accessory_product=unclear).exists(), "名稱打錯整批不做")
        shop_tidy.tidy(self.t, {**self.answers, "fits": {unclear.name: ["iPad Pro (2020) 11 吋"]}}, confirm=True)
        self.assertEqual(list(ProductRelation.objects.filter(accessory_product=unclear).values_list("host_model__name", flat=True)),
                         ["iPad Pro (2020) 11 吋"])

    def test_a_brand_with_a_chinese_name_added_still_reads_the_same(self):
        """品牌補了中文名(「三星 Samsung」,owner 10-17)之後,查表照英文:機型、手機品牌字都照樣認得,不多建品牌。"""
        self.samsung.name_zh = "三星"
        self.samsung.save()
        shop_tidy.tidy(self.t, self.answers, confirm=True)
        fits = lambda p: sorted(ProductRelation.objects.filter(accessory_product=p).values_list("host_model__name", flat=True))  # noqa: E731
        self.assertEqual(fits(self.s25), ["Galaxy S 25 Ultra"])
        self.assertEqual((self.fresh(self.charger).brand_id, self.fresh(self.wired).brand_id), (self.samsung.pk, self.samsung.pk),
                         "旅充/三星、原耳/SAM:原廠的一般類別認得是同一個三星")
        self.assertEqual(Brand.objects.filter(tenant=self.t, name_en__iexact="samsung").count(), 1, "不多建一個 Samsung")

    def test_owner_picked_fits_fill_in_what_a_half_linked_product_is_missing(self):
        apple = Brand.objects.get(tenant=self.t, name="Apple")
        mk = lambda code, name: PhoneModel.objects.create(tenant=self.t, code=code, name=name, match_key=name.lower(),  # noqa: E731
                                                          brand=apple)
        air4, air5, pro = mk("air4", "iPad Air (2020)"), mk("air5", "iPad Air 5 (M1)"), mk("pro11", "iPad Pro (2018) 11 吋")
        half = Product.objects.create(tenant=self.t, category=self.back, name="9H/平板/IMOS/低藍光/IPAD/AIR4/5/PRO11",
                                      requires_serial=False)
        shop_tidy.tidy(self.t, self.answers, confirm=True)
        fits = lambda: sorted(ProductRelation.objects.filter(accessory_product=half).values_list("host_model__name", flat=True))  # noqa: E731
        self.assertEqual(fits(), ["iPad Air (2020)", "iPad Air 5 (M1)"], "Air 那一半先掛上,Pro 11 沒寫年份不掛")
        pick = {**self.answers, "fits": {half.name: [air4.name, air5.name, pro.name]}}
        r = shop_tidy.tidy(self.t, pick, confirm=True)
        self.assertEqual(fits(), ["iPad Air (2020)", "iPad Air 5 (M1)", "iPad Pro (2018) 11 吋"], "owner 指定的補上 Pro 11")
        self.assertEqual(r.fit_links, 1, "已經掛的不重掛")
        self.assertEqual(shop_tidy.tidy(self.t, pick, confirm=True).fit_links, 0, "再跑一次什麼都不變")

    def test_kinds_can_follow_another_company(self):
        other = Tenant.objects.create(name="測試", code="TEST")
        c = Category.objects.create(tenant=other, code="CH", name="充電/線材", needs_host_model=True)
        r = shop_tidy.tidy(other, {}, kinds_from=self.t, confirm=True)
        c.refresh_from_db()
        self.assertEqual((c.kind, c.name, r.kinds), ("general", "傳輸線", ["充電/線材:accessory → general"]))

    def test_kinds_still_follow_after_the_other_company_was_tidied_first(self):
        shop_tidy.tidy(self.t, self.answers, confirm=True)          # 手機玩家先跑:它的「充電/線材」已經是「傳輸線」
        other = Tenant.objects.create(name="測試", code="TEST")
        c = Category.objects.create(tenant=other, code="CH", name="充電/線材", needs_host_model=True)
        cable = Product.objects.create(tenant=other, category=c, name="IP5/副廠/2M", requires_serial=False)
        apple = Brand.objects.create(tenant=other, code="apple", name="Apple")
        PhoneModel.objects.create(tenant=other, code="ip5", name="iPhone 5", match_key="iphone 5", brand=apple)
        shop_tidy.tidy(other, {}, kinds_from=self.t, confirm=True)
        c.refresh_from_db()
        self.assertEqual((c.kind, c.name), ("general", "傳輸線"))
        self.assertFalse(ProductRelation.objects.filter(accessory_product=cable).exists(), "一般類別不掛適用機型")


class SearchByShopWordsTests(TestCase):
    """商品搜尋:打店內寫法(`皮套 ipad air 5`、`ip17pm`)也找得到掛了那支適用機型的配件;機型以外的字要對得上。"""

    def setUp(self):
        self.c = Company("JB", "甲通訊行", "甲")
        t = self.c.tenant
        apple = Brand.objects.create(tenant=t, code="apple", name="Apple")
        dap = Brand.objects.create(tenant=t, code="dap", name="DAP")
        pm = lambda name, key: PhoneModel.objects.create(tenant=t, code=key, name=name, match_key=key, brand=apple)  # noqa: E731
        air5, ip17pm = pm("iPad Air 5 (M1)", "ipad air 5 m1"), pm("iPhone 17 Pro Max", "iphone 17 pro max")
        glass_cat = Category.objects.create(tenant=t, code="PP", name="玻璃貼")
        mk = lambda c, n, m, b=None: (p := Product.objects.create(tenant=t, category=c, name=n, requires_serial=False, brand=b),  # noqa: E731
                                      ProductRelation.objects.create(tenant=t, host_model=m, accessory_product=p))[0]
        self.case = mk(self.c.cat_case, "皮套/平板/DAP/IPAD/AIR4/5/立架玫金", air5, dap)
        self.glass = mk(glass_cat, "9H/平板/DAP/IPAD/AIR4/5/10.9", air5)
        self.ip_case = mk(self.c.cat_case, "背蓋/IMOS/IP17PM/透", ip17pm)

    def names(self, q):
        return {p["name"] for p in self.c.admin.get("/api/v1/products/", {"search": q}).json()["results"]}

    def test_shop_words_and_the_other_words_must_match(self):
        self.assertTrue({self.case.name, self.glass.name} <= self.names("ipad air 5"))
        self.assertIn(self.case.name, self.names("皮套 ipad air 5"))
        self.assertIn(self.ip_case.name, self.names("ip17pm"))
        # 這一條規則自己帶出來的(會排在最前面):機型以外的字也要對得上
        fit = lambda q: set(Product.objects.filter(pk__in=_fitting_accessory_ids(self.c.tenant, q)).values_list("name", flat=True))  # noqa: E731
        self.assertEqual(fit("皮套 ipad air 5"), {self.case.name}, "「皮套」也要對得上:玻璃貼不帶")
        self.assertEqual(fit("ipad air 5"), {self.case.name, self.glass.name})
        self.assertEqual(fit("立架 ipad air 5"), {self.case.name}, "品名裡的字")
        self.assertEqual(fit("ipad air 5 皮套"), {self.case.name}, "寫在 iPad 後面的字也要對得上(複審 P1)")
        self.assertEqual(fit("ipad air 5 立架"), {self.case.name})
        self.assertEqual(fit("DAP ip17pm"), set(), "IP17PM 那一個是 IMOS 的")
        self.assertEqual(fit("ipad air 9"), set(), "對不到的機型不猜")
