"""庫存查詢聽得懂通訊行的寫法(owner 2026-10-09:「還要再帶入通訊的常用語彙,比如 IP=IPHONE, U=Ultra, +=Plus」)。

品名都是舊系統裡真的有的寫法。上半是語彙表本身(不碰資料庫),下半是庫存查詢那支 API。
"""
import re

from django.db import connection
from django.test import SimpleTestCase, TestCase

from apps.backup.tests.factory import Company
from apps.identity.models import ProductAlias
from apps.inventory.models import StockBalance

from . import shop_terms
from .models import Product
from .shop_terms import matches, word_patterns


class WordingTests(SimpleTestCase):
    def check(self, rows):
        for typed, text, found in rows:
            with self.subTest(typed=typed, text=text):
                self.assertEqual(matches(typed, text), found)

    def test_ip_is_iphone(self):
        self.check([
            ("iphone17", "IP17/256G/黑/100%", True),
            ("iphone 17", "IMOS/IP17PRO/磁吸支架/透", True),
            ("IP17", "iPhone 17 256GB 黑色 全新", True),
            ("IP17", "APPLE-IPHONE17黑512G", True),
            ("iphone", "IP6/亮", True),
            ("IP", "iPhone 17 256GB 黑色 全新", True),
            ("IPXS", "APPLE-IPHONEXS MAX灰256G", True),
            ("iphone se", "APPLE-IPHONE SE(2代)白128", True),
            # 不是 iPhone 的
            ("iphone", "平板/IPAD7/8/10.2吋", False),
            ("iphone", "SAM/FLIP7/外螢幕", False),
            ("IP17", "IP16/128G", False),
        ])

    def test_the_old_system_wrote_new_iphones_as_apple_number(self):
        self.check([
            ("IP18PM", "APPLE-18PM/1TB/紅", True),
            ("iphone 18 pro max", "APPLE-18PM/1TB/紅", True),
            ("IP6S+", "APPLE-I6S PLUS灰128G", True),
            ("iphone", "APPLE-18PRO/512G/銀", True),
            # APPLE 後面不是數字就不是在講 iPhone;別牌的 I9300 也不是
            ("iphone", "APPLE/WATCH/44MM/黑", False),
            ("IP9", "9H/半/SAM/S3/I9300", False),
        ])

    def test_pm_is_pro_max(self):
        self.check([
            ("IP17PM", "iPhone 17 Pro Max 256GB 黑色 全新", True),
            ("IP17PM", "APPLE-IPHONE17 P MAX灰256", True),
            ("IP11PM", "IP11PMAX/256G/綠", True),
            ("iphone 17 pro max", "IP17PM/512G/93%/銀/H", True),
            ("17 pro max", "IMOS/IP17PM/磁吸支架/黑", True),
            ("IP17 PM", "IP17PM/256G/藍", True),
            ("17 p max", "IP17PM/256G/藍", True),
            ("pro max", "IP14PM/128G/銀", True),
            ("PM", "APPLE-IPHONE12 P MAX藍128", True),
            ("IP17PM", "IP17PRO/256G", False),
            ("IP17PM", "IP17/256G", False),
            ("pro max", "IP14P/128G", False),
        ])

    def test_p_after_a_number_is_pro_and_pro_also_shows_pro_max(self):
        """打 Pro 連 Pro Max 也出來:照字面本來就會(PRO 是 PRO MAX 的開頭)。"""
        self.check([
            ("17 pro", "IP17P/玻璃貼", True),
            ("IP17PRO", "IP17P/玻璃貼", True),
            ("IP17P", "iPhone 17 Pro 256GB", True),
            ("17 pro", "IP17PM/256G", True),
            ("IP17P", "iPhone 17 Pro Max 256GB", True),
            ("IP17PRO", "IP17PM/256G", True),
            ("17PRO", "APPLE-IPHONE17 P MAX灰256", True),
            ("RENO10P+", "OPPO/RENO10PRO+/側翻黑", True),
            ("pixel 10 pro", "GOOGLE/PIXEL-10PROXL/黑", True),
            ("17 pro", "IP17 PINK殼", False),
            ("17 pro", "IP17/256G", False),
            ("IP16PRO", "APPLE-IPHONE16 PLUS黑128G", False),
        ])

    def test_plus_sign_is_plus(self):
        self.check([
            ("IP16+", "APPLE-IPHONE16 PLUS粉紅256", True),
            ("16 plus", "IMOS/IP16+/亞麻綠", True),
            ("IP16 PLUS", "IP16+", True),
            ("S25 plus", "DAP/SAM/S25+/柔幻極光/黑", True),
            ("S25+", "Galaxy S25 Plus 256GB", True),
            ("plus", "SAM-S10+-128G-白", True),
            # 記憶體 + 容量的那個加號不是 Plus
            ("plus", "OPPO/RENO11/12+256G/綠/R", False),
            ("S25 plus", "SAM/S25FE/8+256G/黑", False),
        ])

    def test_u_after_a_number_is_ultra(self):
        self.check([
            ("S25U", "Galaxy S25 Ultra 256GB 鈦黑 全新", True),
            ("S25 ultra", "DAP/SAM/S25U/柔幻磁吸/深藍", True),
            ("S25 U", "三星-S25U 12/256鈦黑", True),
            ("S25ULTRA", "SAM/S25U", True),
            ("ultra", "SAM/S22U/荔枝桃", True),
            ("U", "SAM/S25U/黑", True),
            # 別的字裡的 U 不算
            ("S25 U", "SAM/S25/UAG殼", False),
            ("S25 U", "SAM/S25 UAG殼", False),
            ("S25U", "SAM/S25 UAG殼", False),
            ("U", "SAM/S25-UAG殼", False),
            ("ultra", "UAG/IP17/黑", False),
            ("S25U", "SAM/S25/黑", False),
        ])

    def test_fold_flip_and_zenfone(self):
        self.check([
            ("ZFLIP7", "SAM/FLIP7/外螢幕", True),
            ("FLIP7", "Galaxy Z Flip7 256GB", True),
            ("fold 6", "三星-Z FOLD6 12/512曜星銀", True),
            ("ZFOLD7", "SAM/FOLD7/鋁合金/黑", True),
            ("zenfone 10", "ASUS/ZF9/ZF10", True),
            ("ZF10", "ASUS ZenFone 10 256GB", True),
            ("ZF10", "ASUS/ZF9", False),
        ])

    def test_brands_in_either_language(self):
        self.check([
            ("三星 A07", "SAM/A07/黑", True),
            ("SAM A07", "三星-A07 4/128裸光紫", True),
            ("galaxy a56", "三星-A56 8/256賞櫻粉", True),
            ("samsung s25", "Galaxy S25 256GB", True),
            ("huawei p30", "華為/P30/牛仔黑", True),
            ("華為 P30", "HUAWEI/P30/甲殼藍", True),
            ("redmi note14", "紅米-NOTE14P(5G)/黑", True),
            ("紅米 note 14", "小米-紅米NOTE14 PRO 12/256紫", True),
            ("蘋果", "APPLE/WATCH/44MM/黑", True),
            ("原廠三星充電器", "原廠 SAM 充電器", True),
            ("三星 A07", "OPPO/A07/黑", False),
            ("三星", "SAMPLE/殼", False),
        ])

    def test_capacity_with_or_without_the_unit(self):
        self.check([
            ("IP17 256G", "APPLE-IPHONE17黑256", True),
            ("IP17 256GB", "IP17/256G/黑", True),
            ("IP17 256", "iPhone 17 256GB 黑色", True),
            ("256G", "三星-S25U 12/256鈦黑", True),
            ("IP18PM 1T", "APPLE-18PM/1TB/紅", True),
            ("IP18PM 1TB", "APPLE-IPHONE18 P MAX藍1T", True),
            ("256G", "IP17/2560", False),
            ("256G", "IP17/512G", False),
            # 5G 是網路不是容量:不會變成「單獨一個 5」
            ("5G", "紅米-NOTE5/黑", False),
            ("5G", "紅米-NOTE14P(5G)/黑", True),
        ])

    def test_colour_with_or_without_the_word(self):
        self.check([
            ("IP17 黑色", "IP17/256G/黑/100%", True),
            ("IP17 黑", "iPhone 17 256GB 黑色 全新", True),
            ("牛仔黑色", "華為/P30/牛仔黑", True),
            ("IP17 黑色", "IP17/256G/白", False),
        ])

    def test_spaces_and_hyphens_inside_a_model_do_not_matter(self):
        self.check([
            ("X200", "VIVO X 200 Pro 256GB", True),
            ("S4-MINI", "SAM/S4MINI/黑", True),
            ("S4MINI", "9H/半/SAM/S4-MINI", True),
            ("PIXEL10", "GOOGLE-PIXEL 10 PRO 16/128黑", True),
            ("NOTE5", "SAM-NOTE5-黑", True),
        ])

    def test_a_model_is_matched_from_its_first_letter(self):
        self.check([
            ("A17", "SAM/A17/黑", True),
            ("A17", "三星-A 17 8/256", True),
            ("A17", "REMAX/2.4A 17W", False),
            ("S25", "IP15PLUS 256GB", False),
        ])

    def test_a_number_alone_is_that_number(self):
        self.check([
            ("iphone 17", "IP17PM/512G", True),
            ("iphone 17", "IMOS/CPF60低藍光/IP18P/17/16P", True),
            ("iphone 17", "IP16PM/256G/金/R/251017", False),
            ("IP17 256", "IP17/2560", False),
            ("6.7", "保貼/6.7吋", True),
            ("6.7", "保貼/16.7吋", False),
        ])

    def test_every_word_must_be_found(self):
        self.check([
            ("IP17 256 黑", "IP17/256G/黑/100%", True),
            ("IP17 256 黑", "IP17/256G/白", False),
            ("IP17/256G/黑", "APPLE-IPHONE17黑256G", True),
            ("中古,IP15、256", "中古 IP15PM/256G/藍", True),
        ])
        self.assertTrue(matches("中古 IP15 256", "IP15PM/256G/藍/76%/Z", "中古"))   # 類別另外一格
        self.assertFalse(matches("中古 IP15 256", "IP15PM/256G/藍/76%/Z", "手機"))

    def test_what_is_typed_literally_is_always_found(self):
        """每個字的比對式都把「照字面」留著:原本找得到的不會因為語彙表而找不到。"""
        names = ["SAM/FLIP17", "FLIP7 IPAD", "RA17W", "8+256G", "TOP MAX", "XA17", "UAGIP", "SPROMAX", "256GB", "IP8+64G灰", "黑色素", "三星堆"]
        for name in names:
            for size in (2, 3, 4, len(name)):
                for start in range(0, len(name) - size + 1):
                    typed = name[start:start + size]
                    if " " in typed or "/" in typed or len(typed) <= 2 or typed.isdigit():
                        continue    # 會被拆成兩個字、或是太短 / 單獨數字(那兩種另外有規則)
                    with self.subTest(typed=typed, name=name):
                        self.assertTrue(matches(typed, name))

    def test_full_width_and_lower_case(self):
        self.assertTrue(matches("ｉｐ１７ｐｍ", "iPhone 17 Pro Max"))
        self.assertTrue(matches("ip17pm", "IP17PM/512G"))
        self.assertTrue(matches("s25u", "sam/s25u/黑"))
        self.assertTrue(matches("IP17PM", "ip17pm/512g"))
        self.assertTrue(matches("SAM a07", "Sam/A07/黑"))
        self.assertTrue(matches("iphone 17 pro max", "IpHoNe 17 pRo mAx"))
        # 「後面不能還是英文字」這種條件,小寫也算英文字
        self.assertFalse(matches("17 pro", "ip17 pink殼"))
        self.assertFalse(matches("U", "sam/s25-uag殼"))
        self.assertFalse(matches("A17", "remax/2.4a 17w"))
        self.assertFalse(matches("iphone", "zflip7/殼"))

    def test_which_spaces_count_inside_a_model(self):
        """型號中間可以隔著的:半形空白、Tab、不斷行空白(網頁貼上的)、全形空白、連字號。別的不算。"""
        for gap in (" ", "\t", "\u00a0", "\u3000", "-", "  ", " - "):
            with self.subTest(gap=repr(gap)):
                self.assertTrue(matches("IP17PM", f"iPhone{gap}17{gap}Pro{gap}Max"))
                self.assertTrue(matches("pro max", f"IP17{gap}PM"))
        for gap in ("\u0085", "\u2003", "/", "_", ".", "\n"):
            with self.subTest(gap=repr(gap)):
                self.assertFalse(matches("IP17PM", f"IP17{gap}PM"))
                self.assertFalse(matches("pro max", f"IP17{gap}PM"))

    def test_patterns_spell_everything_out(self):
        """交出去的比對式不靠引擎自己認空白 / 數字 / 大小寫(兩個引擎認的不一樣):裡面不會有 \\d、\\s、沒寫明大小寫的英文字。"""
        for typed in ("IP17PM", "iphone 17 pro max", "S25 U", "16 plus", "256G", "1T", "三星 A07", "ZFLIP7", "zenfone 10", "RENO10P+", "É", "(5G)", "17", "IP"):
            for pattern in word_patterns(typed):
                with self.subTest(typed=typed):
                    self.assertNotIn("\\d", pattern)
                    self.assertNotIn("\\s", pattern)
                    outside = re.sub(r"\\.|\[[^\]]*\]", "", pattern)      # 拿掉跳脫的字與字元類別,剩下的不該有英文字
                    self.assertIsNone(re.search(r"[A-Za-z]", outside), outside)

    def test_the_step_that_spells_things_out(self):
        """`TERMS` 裡照習慣寫的 \\d、\\s、大寫(在類別裡面、外面都一樣)交出去之前都要寫明。"""
        sp = shop_terms._SPACES
        self.assertEqual(
            shop_terms._portable(r"A\sB\d[\sA-Z\d.]\.(?<!x)(?:y|\+)"),
            f"[Aa][{sp}][Bb][0-9][{sp}A-Za-z0-9.]\\.(?<![Xx])(?:[Yy]|\\+)",
        )
        self.assertEqual(sp, " \t\u00a0\u3000")

    def test_letters_outside_english(self):
        self.assertTrue(matches("É17", "é17/黑"))
        self.assertTrue(matches("é17", "É17/黑"))
        # 土耳其文有點的大寫 İ 不是英文的 I:不當成英文字母擋在前面,也不當成 I
        self.assertTrue(matches("iphone 17", "İIP17"))
        self.assertFalse(matches("IP17", "İP17"))

    def test_strange_characters_are_just_characters(self):
        for typed in ("(5G)", "[黑", "A*", "IP17?", "C++", "\\", "^$", ".*", "100%", "(((", "a|b", "{3}", "IP17)("):
            with self.subTest(typed=typed):
                for pattern in word_patterns(typed):
                    re.compile(pattern)     # 編得過
        self.assertTrue(matches("(5G)", "紅米-NOTE14P(5G)/黑"))
        self.assertFalse(matches(".*", "IP17"))
        self.assertTrue(matches("100%", "IP17/256G/黑/100%"))

    def test_too_much_is_left_to_the_plain_search(self):
        self.assertEqual(word_patterns(""), [])
        self.assertEqual(word_patterns("   "), [])
        self.assertEqual(len(word_patterns(" ".join(["A"] * shop_terms.MAX_WORDS))), shop_terms.MAX_WORDS)
        self.assertEqual(word_patterns(" ".join(["A"] * (shop_terms.MAX_WORDS + 1))), [])
        self.assertEqual(len(word_patterns("A" * shop_terms.MAX_WORD_LEN)), 1)
        self.assertEqual(word_patterns("A" * (shop_terms.MAX_WORD_LEN + 1)), [])
        self.assertFalse(matches("", "IP17"))


class StockQueryWordingTests(TestCase):
    URL = "/api/v1/products/stock-matrix/"
    NAMES = [
        "APPLE-IPHONE17 P MAX灰256", "IP17PM/512G/93%/銀/H", "iPhone 17 Pro Max 256GB 黑色 全新", "IP17/256G/黑/100%",
        "IMOS/IP16+/亞麻綠", "SAM/S25U/黑", "Galaxy S25 Ultra 256GB 鈦黑 全新", "三星-A07 4/128裸光紫", "APPLE-18PM/1TB/紅",
        "平板/IPAD7/10.2吋", "SAM/S25/UAG殼", "IP16PM/256G/金/R/251017",
    ]

    def setUp(self):
        self.c = Company("a", "甲通訊行", "甲")
        self.t = self.c.tenant
        self.p = {name: self.make(name) for name in self.NAMES}

    def make(self, name, category=None, **more):
        return Product.objects.create(tenant=self.t, category=category or self.c.cat_case, name=name,
                                      requires_serial=False, **more)

    def find(self, search, client=None, **more):
        r = (client or self.c.admin).get(self.URL, {"search": search, "in_stock_only": "false", **more})
        self.assertEqual(r.status_code, 200, r.content.decode())
        return sorted(row["name"] for row in r.json()["products"])

    def test_the_wordings_the_owner_named(self):
        """IP = iPhone、U = Ultra、+ = Plus —— 打哪一種都找得到同一批。"""
        pro_max = sorted(["APPLE-IPHONE17 P MAX灰256", "IP17PM/512G/93%/銀/H", "iPhone 17 Pro Max 256GB 黑色 全新"])
        for typed in ("IP17PM", "iphone 17 pro max", "iPhone17 PM", "17 pro max", "ip17 p max"):
            with self.subTest(typed=typed):
                self.assertEqual(self.find(typed), pro_max)
        ultra = sorted(["SAM/S25U/黑", "Galaxy S25 Ultra 256GB 鈦黑 全新"])
        for typed in ("S25U", "S25 ultra", "s25 u", "S25ULTRA"):
            with self.subTest(typed=typed):
                self.assertEqual(self.find(typed), ultra)
        for typed in ("IP16+", "16 plus", "iphone 16 plus", "IP16PLUS"):
            with self.subTest(typed=typed):
                self.assertEqual(self.find(typed), ["IMOS/IP16+/亞麻綠"])

    def test_word_by_word(self):
        self.assertEqual(self.find("IP17 256 黑"), sorted(["IP17/256G/黑/100%", "iPhone 17 Pro Max 256GB 黑色 全新"]))
        self.assertEqual(self.find("iphone 18 1tb 紅色"), ["APPLE-18PM/1TB/紅"])
        self.assertEqual(self.find("三星 A07"), ["三星-A07 4/128裸光紫"])
        self.assertEqual(self.find("sam a07 128"), ["三星-A07 4/128裸光紫"])
        self.assertEqual(self.find("iphone 17 白"), [])
        # 類別也算一個字
        self.assertEqual(self.find("皮套 S25U"), sorted(["SAM/S25U/黑", "Galaxy S25 Ultra 256GB 鈦黑 全新"]))
        self.assertEqual(self.find("手機 S25U"), [])

    def test_a_date_code_or_another_word_is_not_the_model(self):
        self.assertNotIn("IP16PM/256G/金/R/251017", self.find("iphone 17"))
        self.assertNotIn("SAM/S25/UAG殼", self.find("S25 U"))
        self.assertNotIn("平板/IPAD7/10.2吋", self.find("iphone"))

    def test_what_was_found_before_is_still_found(self):
        """原本的比法(整串字照字面,品號 / 品名 / 規格 / 條碼 / 類別)一個都不能少。"""
        odd = self.make("FLIP17 2.4A 17W 充電器", sku="ZZ-IP-0017", barcode="4710000017123", spec="快充 PD")
        for typed in ("ZZ-IP-0017", "zz-ip", "4710000017123", "0017123", "FLIP17 2.4A", "A 17W", "快充 PD", "IP17", "U", "IP", "+", "PM", "LC", "皮套"):
            with self.subTest(typed=typed):
                before = sorted(
                    p.name for p in Product.objects.filter(tenant=self.t, is_active=True)
                    if any(typed.lower() in (value or "").lower()
                           for value in (p.sku, p.name, p.spec, p.barcode, p.category.name, p.category.code))
                )
                now = self.find(typed)
                self.assertTrue(set(before) <= set(now), (typed, set(before) - set(now)))
        self.assertIn(odd.name, self.find("4710000017123"))

    def test_words_are_not_looked_up_inside_codes(self):
        """「iphone 17」的 17 不能對到條碼 / 品號裡的 17。"""
        self.make("IP15/128G/藍", sku="AA-17", barcode="4710000017999")
        self.make("IP15/128G/白", sku="AA-000018", barcode="17A4710000")
        for typed in ("iphone 17", "IP15 17", "ip15 128g 17"):
            with self.subTest(typed=typed):
                self.assertEqual([name for name in self.find(typed) if name.startswith("IP15/")], [])
        # 整串照字面打碼,照舊找得到
        self.assertIn("IP15/128G/藍", self.find("AA-17"))
        self.assertIn("IP15/128G/白", self.find("17A4710000"))

    def test_other_names_are_found_like_in_the_product_list(self):
        strap = self.make("太空盾/YOI/磁吸支架")
        ProductAlias.objects.create(tenant=self.t, product=strap, kind=ProductAlias.Kind.LEGACY_NAME,
                                    value="小黑環", verified=True)
        self.assertEqual(self.find("小黑環"), ["太空盾/YOI/磁吸支架"])
        listed = sorted(row["name"] for row in self.c.admin.get("/api/v1/products/", {"search": "小黑環"}).json()["results"])
        self.assertEqual(listed, ["太空盾/YOI/磁吸支架"])

    def test_another_company_is_never_shown(self):
        b = Company("b", "乙通訊行", "乙")
        Product.objects.create(tenant=b.tenant, category=b.cat_case, name="IP17PM/乙的", requires_serial=False)
        self.assertNotIn("IP17PM/乙的", self.find("iphone 17 pro max"))
        self.assertEqual(self.find("iphone 17 pro max", client=b.admin), ["IP17PM/乙的"])

    def test_filters_and_stock_still_apply(self):
        phone = self.make("iPhone 17 256GB 白色 全新", category=self.c.cat_phone)
        self.assertEqual(self.find("IP17", category_ids=str(self.c.cat_phone.id)), [phone.name])
        StockBalance.objects.create(tenant=self.t, product=self.p["IP17/256G/黑/100%"], warehouse=self.c.wh, qty=3)
        r = self.c.admin.get(self.URL, {"search": "iphone 17"})        # 預設只列有貨的
        self.assertEqual(r.status_code, 200, r.content.decode())
        rows = r.json()["products"]
        self.assertEqual([row["name"] for row in rows], ["IP17/256G/黑/100%"])
        self.assertEqual(rows[0]["stock_total"], 3)
        self.assertEqual(rows[0]["stock_by_warehouse"][str(self.c.wh.id)], 3)
        self.assertEqual(self.find("iphone 17", warehouse_ids=str(self.c.warehouses[1].id), in_stock_only="true"), [])
        # 停用的不列
        Product.objects.filter(pk=phone.pk).update(is_active=False)
        self.assertNotIn(phone.name, self.find("IP17"))

    def test_strange_input_is_not_an_error(self):
        for typed in ("(", "[", "\\", "*", "?", "+", "(5G)", "IP17)(", "a|b", "^$", ".*", "{3}", "%", "_", "'", '"', "🙂 IP17",
                      "A" * 300, " ".join(["IP17"] * 30), "IP17 " + "9" * 60, "\x00"):
            with self.subTest(typed=typed[:20]):
                r = self.c.admin.get(self.URL, {"search": typed, "in_stock_only": "false"})
                self.assertEqual(r.status_code, 200, r.content.decode()[:300])
        self.assertEqual(self.find(".*"), [])

    def test_the_database_reads_the_patterns_the_same_way_as_python(self):
        """比對式在 PostgreSQL(實際查詢)與 Python(上面的測試)要得到一樣的答案。"""
        typed = ["IP17PM", "iphone 17 pro max", "17 pro", "pro max", "PM", "IP", "U", "S25 U", "S25U", "plus", "+", "16+", "IP6S+", "ZFLIP7", "fold 6",
                 "zenfone 10", "三星 A07", "SAM", "huawei p30", "256G", "1T", "黑色", "A17", "17", "6.7", "X200", "S4-MINI", "(5G)", "100%", "RENO10P+", "原廠三星充電器",
                 "É17", "é17", "İP17", "K17", "ß", "ΣΑΜ", "samſ", "256"]
        texts = self.NAMES + ["IP17P/玻璃貼", "IP17 PINK殼", "OPPO/RENO11/12+256G/綠/R", "SAM-S10+-128G-白", "REMAX/2.4A 17W", "UAG/IP17/黑", "三星-Z FOLD6 12/512曜星銀",
                              "ASUS/ZF9/ZF10", "HUAWEI/P30/甲殼藍", "紅米-NOTE14P(5G)/黑", "保貼/16.7吋", "VIVO X 200 Pro 256GB", "9H/半/SAM/S4-MINI", "APPLE-I6S PLUS灰128G",
                              "9H/半/SAM/S3/I9300", "OPPO/RENO10PRO+/側翻黑", "原廠 SAM 充電器", "IP17/2560", "APPLE-IPHONE18 P MAX藍1T", "sam/s25u/黑", "SAMPLE/殼",
                              # 兩個引擎自己認的話會不一樣的:各種空白、別的文字的字母與數字(複審抓到的 U+0085 與 İ 在裡面)
                              "IP17\u0085PM", "İIP17", "İP17", "ıp17pm", "iPhone 17\u3000Pro\u00a0Max", "IP17\u00a0PM", "IP17\u2003PM", "IP17\tPM", "IP17\nPM",
                              "ip17pm/512g", "IpHoNe 17 pRo mAx", "ＩＰ１７ＰＭ", "IP１７", "17７", "S25\u3000U", "s25ｕ", "ſam/a07", "K17", "é17", "É17", "SAM/A０７", "256Ｇ", "٢٥٦G"]
        checked = 0
        with connection.cursor() as cursor:
            for query in typed:
                for pattern in word_patterns(query):
                    for text in texts:
                        cursor.execute("SELECT %s ~ %s", [text, pattern])
                        in_database = cursor.fetchone()[0]
                        self.assertEqual(in_database, bool(re.search(pattern, text)), (query, pattern, text))
                        checked += 1
        self.assertGreater(checked, 2000)

    def test_lower_case_names_and_odd_spaces_through_the_api(self):
        self.make("iphone 17\u3000pro\u00a0max 256gb 白")
        self.make("ip17pm/1tb/橘")
        self.make("IP17\u0085PM/怪空白")
        found = self.find("IP17PM")
        self.assertIn("iphone 17\u3000pro\u00a0max 256gb 白", found)
        self.assertIn("ip17pm/1tb/橘", found)
        self.assertNotIn("IP17\u0085PM/怪空白", found)
        self.assertIn("ip17pm/1tb/橘", self.find("IPHONE 17 PRO MAX 1T"))
