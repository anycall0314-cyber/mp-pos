"""商品防重複:共用叫法比對的測試(開發計畫 §10.1)。

要在 PostgreSQL 上跑(唯一約束與並發那幾條在 SQLite 上不成立)。
"""
import threading

from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection, transaction
from django.test import SimpleTestCase, TestCase, TransactionTestCase
from rest_framework.test import APIClient

from apps.catalog.models import Category, PhoneModel, Product, ProductRelation
from apps.inventory.models import StockBalance, Warehouse
from apps.parties.models import Supplier
from apps.tenants.models import Tenant, UserProfile

from . import services
from .models import IntakeItem, ProductAlias
from .product_match import (
    COVERS,
    EXACT,
    RELATED,
    SAME_ITEM_LEVELS,
    MatchResult,
    compare,
    find_candidates,
    is_broad_phrase,
    parse_features,
)

# 使用者確認是同一款商品的四種叫法(開發計畫 §3.1)
FOUR_PHRASINGS = [
    "reno16 皮套 藍色",
    "reno-16 側翻皮套 藍",
    "reno16/側翻/藍",
    "reno16/皮套/側翻藍",
]
STANDARD_NAME = "Reno16 側翻皮套／藍"


def _feat(text):
    f = parse_features(text)
    return sorted(f.codes), sorted(f.colors), sorted(f.words)


class ParseTests(SimpleTestCase):
    """寫法差異要拆成同一組特徵;真正的差異要留著。"""

    def test_standard_name(self):
        self.assertEqual(_feat(STANDARD_NAME), (["RENO16"], ["藍"], ["側翻", "皮套"]))

    def test_case_width_hyphen_slash(self):
        base = _feat("reno16 側翻皮套 藍")
        for text in [
            "RENO16 側翻皮套 藍",
            "Reno-16 側翻皮套 藍",
            "reno16/側翻皮套/藍",
            "ｒｅｎｏ１６　側翻皮套　藍",   # 全形
            "藍 側翻皮套 reno16",          # 換字序
            "reno 16 側翻皮套 藍",         # 機型中間有空白
        ]:
            self.assertEqual(_feat(text), base, text)

    def test_blue_synonyms(self):
        self.assertEqual(parse_features("藍").colors, parse_features("藍色").colors)

    def test_glued_style_and_color(self):
        """「側翻藍」連寫 → 側翻 + 藍。"""
        self.assertEqual(_feat("側翻藍"), ([], ["藍"], ["側翻"]))
        self.assertEqual(_feat("荔枝黑"), ([], ["黑"], ["荔枝"]))
        self.assertEqual(_feat("磁吸支架銀"), ([], ["銀"], ["支架", "磁吸"]))

    def test_modified_color_is_its_own_color(self):
        """深藍 / 淺藍 / 丁香紫 不能被當成藍 / 紫。"""
        self.assertEqual(parse_features("深藍").colors, {"深藍"})
        self.assertEqual(parse_features("淺藍色").colors, {"淺藍"})
        self.assertEqual(parse_features("丁香紫").colors, {"丁香紫"})
        self.assertNotIn("藍", parse_features("深藍").colors)

    def test_color_char_inside_other_words_not_split(self):
        """紅米 / 藍光 / 鋁合金 裡的顏色字不是顏色。"""
        for text in ["紅米", "抗藍光", "鋁合金", "藍牙耳機"]:
            self.assertEqual(parse_features(text).colors, frozenset(), text)

    def test_model_suffix_kept(self):
        self.assertEqual(parse_features("reno16 pro").codes, {"RENO16PRO"})
        self.assertEqual(parse_features("IP13PM").codes, {"IP13PM"})
        self.assertEqual(parse_features("iPhone 15 Pro Max 256GB").codes, {"IPHONE15PROMAX"})

    def test_units_are_not_models(self):
        """20W、128GB、11吋 是規格,不會被接成機型。"""
        f = parse_features("PD 20W 充電頭")
        self.assertEqual(f.codes, frozenset())
        self.assertIn("20W", f.words)
        self.assertIn("128GB", parse_features("iPhone 15 128G 黑").words)
        self.assertIn("11吋", parse_features("IPAD/PRO/11吋").words)

    def test_continuation_models(self):
        """RENO15/15F:後面省略字首的機型要補回來。"""
        self.assertEqual(parse_features("滿/OPPO/RENO15/15F/黑").codes, {"RENO15", "RENO15F"})

    def test_space_vs_slash_model(self):
        """同一個東西,一邊用空白一邊用斜線寫,兩個方向都要對得上。"""
        a, b = parse_features("SONY 10-VI 側翻黑"), parse_features("SONY/10-VI/側翻黑")
        self.assertEqual(compare(a, b).level, EXACT)
        self.assertEqual(compare(b, a).level, EXACT)


class CompareTests(SimpleTestCase):
    def setUp(self):
        self.std = parse_features(STANDARD_NAME)

    def _cmp(self, text):
        return compare(parse_features(text), self.std)

    def test_four_phrasings_all_match(self):
        for text in FOUR_PHRASINGS:
            v = self._cmp(text)
            self.assertIsNotNone(v, text)
            self.assertIn(v.level, (EXACT, COVERS), text)
            self.assertFalse(v.conflict, text)

    def test_missing_style_is_insufficient_not_exact(self):
        """只寫「皮套」沒寫側翻 → 資訊不足,不直接當成同一款。"""
        v = self._cmp("reno16 皮套 藍色")
        self.assertEqual(v.level, COVERS)
        self.assertTrue(any("側翻" in d for d in v.differences))

    def test_different_model_not_a_candidate(self):
        self.assertIsNone(self._cmp("reno16 pro 側翻皮套 藍"))
        self.assertIsNone(self._cmp("reno15 側翻皮套 藍"))

    def test_different_color_is_flagged(self):
        for text in ["reno16 側翻皮套 深藍", "reno16 側翻皮套 黑"]:
            v = self._cmp(text)
            self.assertEqual(v.level, RELATED, text)
            self.assertTrue(v.conflict, text)
            self.assertTrue(any("顏色不同" in d for d in v.differences), text)

    def test_different_material_brand_pack_not_merged(self):
        for text in ["reno16 真皮側翻皮套 藍", "DAP reno16 側翻皮套 藍", "reno16 側翻皮套 藍 2入"]:
            v = self._cmp(text)
            self.assertEqual(v.level, RELATED, text)
            self.assertTrue(v.differences, text)

    def test_broad_phrases(self):
        for text in ["reno16", "皮套", "藍", "側翻皮套"]:
            self.assertTrue(is_broad_phrase(text), text)
        self.assertFalse(is_broad_phrase("reno16 側翻皮套 藍"))


class _Base(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="測試通訊行", code="demo")
        self.cat = Category.objects.create(
            tenant=self.tenant, code="LC", name="皮套"
        )
        self.sup = Supplier.objects.create(tenant=self.tenant, name="大盤商A")
        self.wh = Warehouse.objects.create(tenant=self.tenant, code="NY", name="湳雅店")
        self.wh2 = Warehouse.objects.create(tenant=self.tenant, code="MS", name="民生店")
        self.std = self._product(STANDARD_NAME)

    def _product(self, name, **kw):
        kw.setdefault("requires_serial", False)
        kw.setdefault("category", self.cat)
        return Product.objects.create(tenant=self.tenant, name=name, **kw)

    def _user(self, name, role, tenant=None, warehouse=None, locked=None):
        user = get_user_model().objects.create_user(username=name, password="x")
        UserProfile.objects.create(
            user=user, role=role, tenant=tenant or self.tenant,
            default_warehouse=warehouse,
            is_warehouse_locked=(role == "tenant_user") if locked is None else locked,
        )
        return user

    def _client(self, user):
        c = APIClient()
        c.force_authenticate(user)
        return c


class FindCandidatesTests(_Base):
    def test_four_phrasings_recall_one_product_without_aliases(self):
        """只建一筆標準商品、沒有任何別名,四種寫法都要找得到它。"""
        self.assertEqual(ProductAlias.objects.count(), 0)
        for text in FOUR_PHRASINGS:
            r = find_candidates(self.tenant, text)
            self.assertEqual(r.status, MatchResult.CANDIDATES, text)
            self.assertEqual(r.candidates[0].product_id, self.std.id, text)
            self.assertTrue(r.candidates[0].reasons, text)

    def test_features_never_yield_existing(self):
        """特徵再像也只是候選,不會變成「就是這個」。"""
        r = find_candidates(self.tenant, "reno-16 側翻皮套 藍")
        self.assertEqual(r.candidates[0].level, EXACT)
        self.assertEqual(r.status, MatchResult.CANDIDATES)

    def test_two_blue_cases_both_listed_none_picked(self):
        other = self._product("Reno16 掀蓋皮套／藍")
        r = find_candidates(self.tenant, "reno16 皮套 藍色")
        self.assertEqual(r.status, MatchResult.CANDIDATES)
        self.assertEqual({c.product_id for c in r.candidates}, {self.std.id, other.id})
        self.assertTrue(all(c.level == COVERS for c in r.candidates))
        # 進貨待確認區也一樣:不自動對應
        m = services.match_line(self.tenant, self.sup, "reno16 皮套 藍色")
        self.assertIsNone(m["matched_product"])
        self.assertNotEqual(m["status"], IntakeItem.MatchStatus.AUTO_MATCHED)
        self.assertEqual(len(m["candidates"]), 2)

    def test_zero_stock_and_inactive_are_found(self):
        self.assertFalse(StockBalance.objects.filter(product=self.std).exists())
        self.assertEqual(find_candidates(self.tenant, "reno16/側翻/藍").product_ids, [self.std.id])
        self.std.is_active = False
        self.std.save()
        r = find_candidates(self.tenant, "reno16/側翻/藍")
        self.assertEqual(r.product_ids, [self.std.id])
        self.assertFalse(r.candidates[0].is_active)

    def test_not_merged_with_similar_products(self):
        pro = self._product("Reno16 Pro 側翻皮套／藍")
        navy = self._product("Reno16 側翻皮套／深藍")
        r = find_candidates(self.tenant, "reno16 側翻皮套 藍")
        by_id = {c.product_id: c for c in r.candidates}
        self.assertEqual(by_id[self.std.id].level, EXACT)
        self.assertNotIn(pro.id, by_id)                 # 不同機型不列
        self.assertEqual(by_id[navy.id].level, RELATED)  # 不同顏色列出但標差異
        self.assertTrue(by_id[navy.id].differences)

    def test_related_fallback_when_nothing_matches_fully(self):
        """完整條件沒有結果時,退回同機型的相關商品並標明差異。"""
        r = find_candidates(self.tenant, "reno16 側翻皮套 紅")
        self.assertEqual(r.product_ids, [self.std.id])
        self.assertEqual(r.candidates[0].level, RELATED)
        self.assertIn("顏色不同", "".join(r.candidates[0].differences))

    def test_abbreviation_via_phone_model_master(self):
        """有機型主檔時認得店內縮寫:IP13PM = iPhone 13 Pro Max。"""
        PhoneModel.objects.create(
            tenant=self.tenant, code="iphone-13-pro-max",
            name="iPhone 13 Pro Max", match_key="iphone 13 pro max",
        )
        PhoneModel.objects.create(
            tenant=self.tenant, code="iphone-13-pro",
            name="iPhone 13 Pro", match_key="iphone 13 pro",
        )
        case = self._product("DAP/IP13PM/側翻藍")
        r = find_candidates(self.tenant, "iphone 13 pro max 側翻皮套 藍色")
        self.assertEqual(r.candidates[0].product_id, case.id)
        # 13 Pro 不是 13 Pro Max
        self.assertEqual(find_candidates(self.tenant, "iphone 13 pro 側翻 藍").product_ids, [])

    def test_compatible_model_relation_counts_once(self):
        """共用多機型的配件只有一個商品,不因多條相容關係重複出現。"""
        models = [
            PhoneModel.objects.create(
                tenant=self.tenant, code=f"reno-{n}", name=f"Reno {n}", match_key=f"reno {n}",
            ) for n in (12, 13)
        ]
        glass = self._product("滿版玻璃貼 黑")
        for m in models:
            ProductRelation.objects.create(
                tenant=self.tenant, host_model=m, host_model_key=m.match_key,
                accessory_product=glass,
            )
        r = find_candidates(self.tenant, "reno13 滿版 黑")
        self.assertEqual(r.product_ids.count(glass.id), 1)

    def test_other_tenant_invisible(self):
        other = Tenant.objects.create(name="別家", code="other")
        cat = Category.objects.create(tenant=other, code="LC", name="皮套")
        Product.objects.create(tenant=other, category=cat, name="Reno16 側翻皮套 藍")
        r = find_candidates(self.tenant, "reno16 側翻 藍")
        self.assertEqual(r.product_ids, [self.std.id])

    def test_barcode_and_alias_disagree_is_conflict(self):
        other = self._product("Reno16 掀蓋皮套／藍", barcode="4710001234567")
        ProductAlias.objects.create(
            tenant=self.tenant, product=self.std,
            kind=ProductAlias.Kind.BARCODE, value="4710001234567",
        )
        r = find_candidates(self.tenant, "", barcode="4710001234567")
        self.assertEqual(r.status, MatchResult.CONFLICT)
        self.assertEqual(set(r.product_ids), {self.std.id, other.id})


class BareModelTests(_Base):
    """沒寫品牌字首的機型寫法(11PM、13P、11 pro max、DAP 13P、單獨一個數字)要對得上機型。

    新手不會打店裡的 `IP11PM`。是不是機型由機型主檔決定(`build_index` 本來就收了這些寫法);
    原則:**只會多對上,不會讓原本找得到的變成找不到** —— 沒對上的那些字照原本當一般的字比。
    """

    def setUp(self):
        super().setUp()
        for name in [
            "iPhone 11", "iPhone 11 Pro", "iPhone 11 Pro Max", "iPhone 12",
            "iPhone 13 Pro", "iPhone 13 Pro Max", "iPhone 17 Pro Max", "iPhone 18 Pro Max",
            "iPhone 7", "iPhone 7 Plus", "iPhone 16", "iPhone 16 Plus",
        ]:
            PhoneModel.objects.create(
                tenant=self.tenant, code=name.lower().replace(" ", "-"),
                name=name, match_key=name.lower(),
            )
        self.rhino = self._product("犀牛盾/IP11PM/淺灰")
        self.rhino_pro = self._product("犀牛盾/IP11P/黑")
        self.rhino_12 = self._product("犀牛盾/IP12/淺灰")
        self.dap = self._product("DAP/IP13P/柔幻極光/黑")
        self.imos = self._product("IMOS/IP18PM/17PM/歐拉盾/暮影黑")
        self.battery = self._product("11PRO/認證電池")

    def _ids(self, text, **kw):
        return find_candidates(self.tenant, text, **kw).product_ids

    def _cand(self, text, product, **kw):
        r = find_candidates(self.tenant, text, **kw)
        for c in r.candidates:
            if c.product_id == product.id:
                return c
        self.fail(f"「{text}」找不到 {product.name};候選:{r.product_ids}")

    def test_parse_records_bare_writings_without_touching_words(self):
        f = parse_features("犀牛盾 11PM")
        self.assertEqual(f.bare, frozenset({("11PM", ("11PM",))}))
        self.assertIn("11PM", f.words)
        f = parse_features("犀牛盾 11 pro max 灰")
        self.assertEqual(f.bare, frozenset({("11PROMAX", ("11", "PRO", "MAX"))}))
        self.assertTrue({"11", "PRO", "MAX"} <= f.words)       # 每一塊照樣各自是一個字
        self.assertEqual(f.aux, frozenset())
        # 11PRO MAX 講的是 11 Pro Max,不另外再當成 11PRO
        self.assertEqual(parse_features("11PRO MAX").bare, frozenset({("11PROMAX", ("11PRO", "MAX"))}))
        self.assertEqual(parse_features("極空戰甲 16+ 透").bare, frozenset({("16+", ("16",))}))
        # 單位不是機型;前面有英文字首的(RENO 16 PRO、DAP 13 PRO)原本就會接成型號,不在這裡
        self.assertEqual(parse_features("REMAX 20W 128GB 11吋 5G 4K 2M 3A").bare, frozenset())
        self.assertEqual(parse_features("reno 16 pro").bare, frozenset())
        self.assertEqual(parse_features("reno 16 pro").codes, frozenset({"RENO16PRO"}))

    def test_bare_model_finds_the_product(self):
        self.assertEqual(self._ids("犀牛盾 11PM"), [self.rhino.id])
        c = self._cand("犀牛盾 11PM", self.rhino)
        self.assertEqual(c.level, COVERS)
        self.assertIn("機型相符", c.reasons)
        self.assertEqual(c.differences, ["商品另有:淺灰"])   # 不會把品名的 IP11PM 當成多出來的
        # 沒對上的照原本的:別的機型的殼列在後面當相關,講的是「商品沒有」(跟改之前一樣),不會被排除
        ids = self._ids("犀牛盾 11PM 淺灰")
        self.assertEqual(ids[0], self.rhino.id)
        other = self._cand("犀牛盾 11PM 淺灰", self.rhino_12)
        self.assertEqual(other.level, RELATED)
        self.assertEqual(other.differences, ["商品沒有:11PM"])

    def test_spaced_bare_model(self):
        """`11 pro max`(空白隔開、沒字首):三個字合起來是 11 Pro Max;顏色不同照樣要標出來。"""
        c = self._cand("犀牛盾 11 pro max 灰", self.rhino)
        self.assertEqual(c.level, RELATED)
        self.assertTrue(c.conflict)
        self.assertEqual(c.differences, ["顏色不同(輸入 灰 / 商品 淺灰)"])
        self.assertIn("機型相符", c.reasons)
        # 11 Pro 的那一個:11 pro max 不是它的機型,而且裡面的 11 也不能被當成「單獨一個數字」
        self.assertNotIn(self.rhino_pro.id, self._ids("犀牛盾 11 pro max 灰"))
        eleven = self._product("犀牛盾/IP11/灰")
        self.assertNotIn(eleven.id, self._ids("犀牛盾 11 pro max 灰"))
        # (單獨打 11 的時候才會當成 iPhone 11 來比)
        self.assertEqual(self._cand("犀牛盾 11 灰", eleven).differences, ["只寫了數字 11,當成 iPhone 11 來比"])
        # 13 pro(不是 13 pro max)
        self.assertEqual(self._ids("柔幻極光 13 pro")[0], self.dap.id)
        # 講了兩個機型、只對上一個:對上的算機型,另一個照原本當一個字沒對上
        c = self._cand("柔幻極光 13P 11PM 黑", self.dap)
        self.assertEqual(c.level, RELATED)
        self.assertEqual(c.differences, ["商品沒有:11PM"])

    def test_brand_glued_to_bare_model(self):
        """`DAP 13P` 會被接成 DAP13P(品牌 + 沒字首的機型):後半是這個商品的機型才拆回來。"""
        c = self._cand("DAP 13P 黑", self.dap)
        self.assertEqual(c.level, COVERS)               # 商品另有 柔幻 / 極光
        self.assertIn("機型相符", c.reasons)
        self.assertEqual(self._ids("dap 13 pro 黑")[0], self.dap.id)
        # 品牌不一樣的列為相關、講出差在哪
        c = self._cand("IMOS 13P 黑", self.dap)
        self.assertEqual(c.level, RELATED)
        self.assertEqual(c.differences, ["商品沒有:IMOS"])
        # 後半不是這個商品的機型 → 跟改之前一樣:這個型號沒對上,不是候選
        self.assertEqual(self._ids("DAP 13PM 黑"), [])
        # 主檔認得接起來的那一串(RENO16)就不拆
        PhoneModel.objects.create(tenant=self.tenant, code="reno-16", name="Reno 16", match_key="reno 16")
        self.assertNotIn(self._product("某牌/IP16/RENO紀念殼").id, self._ids("reno 16 紀念殼"))

    def test_plus_and_p(self):
        """7 沒有 Pro → `7P` = 7 Plus;`16+` = 16 Plus,不是 16。沒對上的那一個照原本列為相關。"""
        plus = self._product("太空盾/IP7P/透")
        base = self._product("太空盾/IP7/透")
        for text in ["太空盾 7 plus 透", "太空盾 7P 透"]:
            self.assertEqual(self._ids(text)[0], plus.id, text)
            self.assertEqual(self._cand(text, plus).level, EXACT, text)
            self.assertEqual(self._cand(text, base).level, RELATED, text)
        six = self._product("極空戰甲/IP16/透")
        six_plus = self._product("極空戰甲/IP16+/透")
        self.assertEqual(self._ids("極空戰甲 16+ 透")[0], six_plus.id)
        self.assertEqual(self._cand("極空戰甲 16+ 透", six_plus).level, EXACT)
        c = self._cand("極空戰甲 16+ 透", six)             # 16+ 的 16 不能被當成 iPhone 16
        self.assertEqual(c.level, RELATED)
        self.assertEqual(c.differences, ["商品沒有:16"])

    def test_plain_number_is_weak_evidence(self):
        """`犀牛盾 12 淺灰`、`DAP 12 全覆蓋 粉`:數字當成 iPhone 那一代 —— 找得到,但只列為相關、講清楚是猜的。"""
        c = self._cand("犀牛盾 12 淺灰", self.rhino_12)
        self.assertEqual(c.level, RELATED)
        self.assertFalse(c.conflict)
        self.assertEqual(c.differences, ["只寫了數字 12,當成 iPhone 12 來比"])
        self.assertIn("數字 12 對上機型", c.reasons)
        self.assertNotIn("機型相符", c.reasons)
        # 排在「同品牌、別的機型」前面
        self.assertEqual(self._ids("犀牛盾 12 淺灰")[0], self.rhino_12.id)
        dap12 = self._product("DAP/IP12/全覆蓋/粉")
        self.assertEqual(self._ids("DAP 12 全覆蓋 粉"), [dap12.id])
        self.assertEqual(self._cand("DAP 12 全覆蓋 粉", dap12).level, RELATED)
        # 品牌不對(前半那個字不在品名裡)不拆;數字不是這個商品的世代不算
        self.assertEqual(self._ids("IMOS 12 全覆蓋 粉"), [])
        self.assertNotIn(dap12.id, self._ids("DAP 11 全覆蓋 粉"))
        # 只靠一個數字不成立(不然打到 12 就帶出所有 iPhone 12 的東西)
        pack = self._product("某牌/保護貼/12/入門款")
        self.assertEqual(self._ids("某牌 保護貼 12 入門款"), [pack.id])
        # 品名照字面就有這個數字的,當一般的字比
        literal = self._product("某牌/IP12/12/雙入")
        c = self._cand("某牌 12 雙入", literal)
        self.assertEqual(c.reasons, ["12、某牌、雙入 相符"])
        # 不是 iPhone 的商品不會因為一個數字被當成對上機型
        charger = self._product("REMAX/快充頭/白")
        c = self._cand("REMAX 快充頭 12 白", charger)
        self.assertEqual(c.differences, ["商品沒有:12"])

    def test_plain_number_never_makes_two_products_the_same_item(self):
        """防重複:`某牌/保護貼/12`(12 可能是 12 片)跟 `某牌/IP12/保護貼` 不能被判成同一款。"""
        existing = self._product("某牌/IP12/保護貼")
        r = find_candidates(self.tenant, "某牌/保護貼/12", symmetric=True)
        self.assertNotIn(existing.id, [c.product_id for c in r.candidates if c.level in SAME_ITEM_LEVELS])
        qty = self._product("某牌/玻璃貼/12")
        r = find_candidates(self.tenant, "某牌/IP12/玻璃貼", symmetric=True)
        self.assertNotIn(qty.id, [c.product_id for c in r.candidates if c.level in SAME_ITEM_LEVELS])
        # 只打「12 黑」:iPhone 12 的黑色東西頂多是相關,不是同一款等級
        black = self._product("太空盾/IP12/黑")
        self.assertEqual(self._cand("12 黑", black).level, RELATED)

    def test_name_lists_several_models(self):
        self.assertEqual(self._ids("歐拉盾 18PM"), [self.imos.id])
        self.assertEqual(self._ids("歐拉盾 17PM"), [self.imos.id])

    def test_product_name_written_bare(self):
        """品名本身沒寫字首(`11PRO/認證電池`):打全名找得到,而且不把 11PRO 當成商品多出來的東西。"""
        c = self._cand("iPhone 11 Pro 電池", self.battery)
        self.assertEqual(c.level, COVERS)
        self.assertEqual(c.differences, ["商品另有:認證"])
        self.assertIn("機型相符", c.reasons)
        self.assertEqual(self._cand("IP11P 電池", self.battery).differences, ["商品另有:認證"])
        self.assertEqual(self._cand("11 pro 認證電池", self.battery).level, EXACT)
        # 照字面打的照舊排第一;同機型的別種東西(11 Pro 的殼)跟打 `IP11P 電池` 一樣列在後面
        ids = self._ids("11PRO 電池")
        self.assertEqual(ids[0], self.battery.id)
        self.assertEqual(ids, self._ids("IP11P 電池"))
        self.assertEqual(self._cand("11PRO 電池", self.rhino_pro).differences, ["商品沒有:電池"])
        # 11 Pro Max 的電池不是這一個
        self.assertNotIn(self.battery.id, self._ids("iPhone 11 Pro Max 電池"))

    def test_bare_token_is_not_guessed_when_the_name_already_says_another_model(self):
        """`11PRO` 可以是 iPhone 11 Pro 也可以是 Pixel 11 Pro:品名寫了別的型號的,不能被當成 iPhone 的東西。"""
        for name in ["Pixel 11", "Pixel 11 Pro"]:
            PhoneModel.objects.create(
                tenant=self.tenant, code=name.lower().replace(" ", "-"),
                name=name, match_key=name.lower(),
            )
        pixel = self._product("GOOGLE/PIXEL-11/11PRO黑")
        pixel12 = self._product("GOOGLE/PIXEL-12/11PRO桃")     # 機型主檔沒有 Pixel 12 也一樣
        for p in (pixel, pixel12):
            self.assertNotIn(p.id, self._ids("IP11P"))
            self.assertNotIn(p.id, self._ids("iPhone 11 Pro 黑"))
            self.assertNotIn(p.id, find_candidates(self.tenant, "IP11P", symmetric=True).product_ids)
        # 品名裡照字面就有這串字、但商品是別的機型:照原本當一般的字對上(不會因為「它是別的機型」被排除)
        badge = self._product("某牌/IP12/11PM紀念款")
        c = self._cand("某牌 11PM 紀念款", badge)
        self.assertEqual(c.reasons, ["11PM、某牌、紀念款 相符"])
        self.assertEqual(c.differences, ["商品另有:IP12"])

    def test_ambiguous_bare_token_does_not_widen_the_product(self):
        """主檔裡 `11PRO` 同時是 iPhone 11 Pro 與 Pixel 11 Pro:不能把兩個都算成商品的機型。"""
        models = {}
        for name in ["Pixel 11", "Pixel 11 Pro"]:
            models[name] = PhoneModel.objects.create(
                tenant=self.tenant, code=name.lower().replace(" ", "-"),
                name=name, match_key=name.lower(),
            )
        iphone = PhoneModel.objects.get(tenant=self.tenant, name="iPhone 11 Pro")
        # 商品已經指定是 iPhone 11 Pro:Pixel 11 Pro 的東西不是它(改之前是 None,現在也要是)
        fixed = self._product("11PRO/電池", phone_model=iphone)
        for text in ["PIXEL11PRO/電池", "pixel 11 pro 電池"]:
            self.assertNotIn(fixed.id, self._ids(text), text)
            self.assertNotIn(fixed.id, find_candidates(self.tenant, text, symmetric=True).product_ids, text)
        self.assertEqual(self._cand("iPhone 11 Pro 電池", fixed).level, EXACT)
        # 指定的那一個機型還是認得品名的 11PRO(用店裡的寫法找,11PRO 不算商品多出來的)
        c = self._cand("IP11P 電池", fixed)
        self.assertEqual((c.level, c.differences), (EXACT, []))
        # 沒指定機型、又分不出是哪一牌:不猜(跟改之前一樣找不到),照字面打的照舊
        self.assertNotIn(self.battery.id, self._ids("iPhone 11 Pro 電池"))
        self.assertNotIn(self.battery.id, self._ids("pixel 11 pro 電池"))
        self.assertEqual(self._ids("11PRO 認證電池")[0], self.battery.id)

    def test_brand_plus_plain_number_never_uses_another_brands_number(self):
        """主檔有 Reno 12(縮寫表會登記 `12`):`DAP 12 黑` 不能因此跟 `DAP/RENO12/黑` 變成同一款。"""
        PhoneModel.objects.create(tenant=self.tenant, code="reno-12", name="Reno 12", match_key="reno 12")
        reno = self._product("DAP/RENO12/黑")
        self.assertEqual(self._ids("DAP 12 黑"), [])               # 改之前也是沒有候選
        # 用斜線寫(不會被接成 DAP12)的時候跟改之前一樣:只是「相關、商品沒有 12」,防重複不會當成同一款
        r = find_candidates(self.tenant, "DAP/12/黑", symmetric=True)
        hit = [c for c in r.candidates if c.product_id == reno.id]
        self.assertEqual([(c.level, c.differences) for c in hit], [(RELATED, ["商品沒有:12"])])
        # iPhone 12 的那一個還是找得到,而且只是相關
        dap12 = self._product("DAP/IP12/黑")
        c = self._cand("DAP 12 黑", dap12)
        self.assertEqual(c.level, RELATED)
        self.assertEqual(c.differences, ["只寫了數字 12,當成 iPhone 12 來比"])

    def test_a_guessed_number_stays_a_doubt_even_next_to_a_named_model(self):
        """`某牌/IP11PM/保護貼/12` 的 12 可能是 12 片:旁邊的 IP11PM 對上了,不能證明 12 也是機型。"""
        both = self._product("某牌/IP11PM/IP12/保護貼")
        c = self._cand("某牌/IP11PM/保護貼/12", both)
        self.assertEqual(c.level, RELATED)
        self.assertEqual(c.differences, ["只寫了數字 12,當成 iPhone 12 來比"])
        self.assertEqual(c.reasons[:2], ["機型相符", "數字 12 對上機型"])
        same = [x.product_id for x in find_candidates(self.tenant, "某牌/IP11PM/保護貼/12", symmetric=True).candidates
                if x.level in SAME_ITEM_LEVELS]
        self.assertNotIn(both.id, same)
        # 反過來(既有的是寫 12 的那個,要新建寫 IP12 的)也不能變成同一款
        qty = self._product("某廠/IP11PM/玻璃貼/12")
        same = [x.product_id for x in find_candidates(self.tenant, "某廠/IP11PM/IP12/玻璃貼", symmetric=True).candidates
                if x.level in SAME_ITEM_LEVELS]
        self.assertNotIn(qty.id, same)

    def test_plain_mode_is_the_old_comparison(self):
        """`plain=True` = 不認這些新寫法,就是改之前的比法(防重複拿它回答「這個結果以前有沒有」)。"""
        from .product_match import MatchContext
        ids = MatchContext(self.tenant)._model_ids
        f = parse_features

        def both(q, name):
            return (compare(f(q), f(name), model_ids=ids), compare(f(q), f(name), model_ids=ids, plain=True))

        new, old = both("犀牛盾 11PM", "犀牛盾/IP11PM/淺灰")              # 沒字首的寫法
        self.assertEqual((new.level, old), (COVERS, None))
        new, old = both("iPhone 11 Pro 電池", "11PRO/認證電池")           # 品名自己沒字首
        self.assertEqual((new.level, old), (COVERS, None))
        new, old = both("DAP 13P 黑", "DAP/IP13P/柔幻極光/黑")            # 品牌 + 機型被接成一串
        self.assertEqual((new.level, old), (COVERS, None))
        new, old = both("犀牛盾 12 淺灰", "犀牛盾/IP12/淺灰")             # 單獨一個數字
        self.assertEqual(new.differences, ["只寫了數字 12,當成 iPhone 12 來比"])
        self.assertEqual((old.level, old.differences, old.via_new), (RELATED, ["商品沒有:12"], False))

    def test_an_old_explicit_difference_is_not_turned_into_the_same_item(self):
        """防重複:以前就是「相關、顏色明確不同」的,不能因為新寫法也對上了就去做反向比對、變成同一款。"""
        black = self._product("犀牛盾/11PM/黑")
        r = find_candidates(self.tenant, "犀牛盾/11PM/透/黑", symmetric=True)
        hit = [c for c in r.candidates if c.product_id == black.id]
        self.assertEqual([(c.level, c.conflict) for c in hit], [(RELATED, True)])
        self.assertEqual(hit[0].differences, ["顏色不同(輸入 透 / 商品 黑)"])
        self.assertNotIn(black.id, find_candidates(
            self.tenant, "犀牛盾/11PM/透/黑", symmetric=True, with_related=False).product_ids)
        # 帶一個單獨數字的也一樣
        film = self._product("某牌/IP12/黑/保護貼")
        r = find_candidates(self.tenant, "某牌/12/IP12/黑/白/保護貼", symmetric=True)
        hit = [c for c in r.candidates if c.product_id == film.id]
        self.assertEqual([(c.level, c.conflict) for c in hit], [(RELATED, True)])

    def test_reverse_check_does_not_use_the_new_reading_to_merge_different_colours(self):
        """防重複:`11PM/透/黑` 對 `IP11PM/黑` —— 寫成 `IP11PM/透/黑` 時是顏色不同的兩個東西,沒寫字首也一樣。"""
        black = self._product("IP11PM/黑")
        for new_name in ["11PM/透/黑", "IP11PM/透/黑"]:
            r = find_candidates(self.tenant, new_name, symmetric=True)
            same = [c.product_id for c in r.candidates if c.level in SAME_ITEM_LEVELS]
            self.assertNotIn(black.id, same, new_name)
        hit = [c for c in find_candidates(self.tenant, "11PM/透/黑", symmetric=True).candidates
               if c.product_id == black.id]
        self.assertEqual([(c.level, c.conflict) for c in hit], [(RELATED, True)])
        # 反過來(既有的沒寫字首、要新建寫了字首而且多一個顏色的)也一樣
        bare = self._product("某殼/11PM/黑")
        same = [c.product_id for c in find_candidates(self.tenant, "某殼/IP11PM/透/黑", symmetric=True).candidates
                if c.level in SAME_ITEM_LEVELS]
        self.assertNotIn(bare.id, same)
        # 沒有明確不同、只是新品名多寫了東西:列為相關(「既有商品沒寫機型字首」在反向比對裡仍算太籠統 —— 原本的規則,沒動)
        more = self._product("某套/11PM/黑")
        hit = [c for c in find_candidates(self.tenant, "某套/IP11PM/磁吸/黑", symmetric=True).candidates
               if c.product_id == more.id]
        self.assertEqual([(c.level, c.conflict, c.differences) for c in hit], [(RELATED, False, ["商品沒有:磁吸"])])

    def test_an_alias_result_cannot_hide_the_main_names_explicit_difference(self):
        """防重複:主品名顏色明確不同;現在某個其他叫法的結果比較好看,也不能因此升成同一款。"""
        black = self._product("IP11PM/黑")
        ProductAlias.objects.create(
            tenant=self.tenant, product=black, kind=ProductAlias.Kind.LEGACY_NAME,
            value="DAP/11PM", verified=False,
        )
        r = find_candidates(self.tenant, "DAP 11PM / IP11PM / 透 / 黑", symmetric=True)
        same = [c.product_id for c in r.candidates if c.level in SAME_ITEM_LEVELS]
        self.assertNotIn(black.id, same)

    def test_a_short_alias_cannot_guess_a_model_the_main_name_contradicts(self):
        """主品名寫了 PIXEL11PRO(主檔還沒有這一支),其他叫法是 `11PRO/電池`:不能從叫法猜成 iPhone 11 Pro。"""
        pixel = self._product("GOOGLE/PIXEL11PRO/電池")
        ProductAlias.objects.create(
            tenant=self.tenant, product=pixel, kind=ProductAlias.Kind.LEGACY_NAME,
            value="11PRO/電池", verified=False,
        )
        for sym in (False, True):
            self.assertNotIn(
                pixel.id, find_candidates(self.tenant, "iPhone 11 Pro 電池", symmetric=sym).product_ids, sym)
        # 照字面打這個叫法,照舊找得到(跟改之前一樣:叫法字面完全相同)
        c = self._cand("11PRO 電池", pixel)
        self.assertEqual(c.level, EXACT)
        self.assertEqual(c.reasons[0], "其他叫法「11PRO/電池」")
        self.assertNotIn("機型相符", c.reasons)
        # 主品名沒有寫型號的,叫法裡的沒字首機型可以用
        plain_named = self._product("某牌/行動電源/白")
        ProductAlias.objects.create(
            tenant=self.tenant, product=plain_named, kind=ProductAlias.Kind.LEGACY_NAME,
            value="13P/行動電源", verified=False,
        )
        self.assertIn(plain_named.id, self._ids("iPhone 13 Pro 行動電源"))

    def test_new_related_does_not_cancel_the_reverse_check(self):
        """防重複:正向因為新認得的寫法冒出一個「相關(顏色不同)」時,原本靠反向成立的同一款不能不見。"""
        PhoneModel.objects.create(tenant=self.tenant, code="reno-16-pro", name="Reno 16 Pro", match_key="reno 16 pro")
        existing = self._product("RENO 16 PRO / 黑")
        r = find_candidates(self.tenant, "DAP 16PRO / RENO / 16PRO / 黑 / 白", symmetric=True, with_related=False)
        hit = [c for c in r.candidates if c.product_id == existing.id]
        self.assertEqual([c.level for c in hit], ["subset"])

    def test_unknown_or_ambiguous_tokens_stay_plain_words(self):
        """主檔不認得的寫法、或認得但不是這個商品的機型:照原本當一個字,**不會排除原本找得到的**。"""
        charger = self._product("REMAX/20W/快充頭")
        self.assertEqual(self._ids("REMAX 20W 快充頭"), [charger.id])
        other = self._product("某牌/IP12/線/黑")
        c = self._cand("某牌 99ZZ 線 黑", other)            # 主檔不認得 99ZZ
        self.assertEqual((c.level, c.differences), (RELATED, ["商品沒有:99ZZ"]))
        c = self._cand("某牌 13P 線 黑", other)             # 主檔認得 13P,但這個商品是 iPhone 12 的
        self.assertEqual((c.level, c.differences), (RELATED, ["商品沒有:13P"]))
        generic = self._product("某牌/快充線/白")            # 通用配件,沒有任何機型資訊
        c = self._cand("某牌 快充線 13P 白", generic)
        self.assertEqual((c.level, c.differences), (RELATED, ["商品沒有:13P"]))

    def test_without_a_model_master_nothing_changes(self):
        """沒有機型主檔的公司:這些寫法就只是字,結果跟改之前一樣。"""
        other = Tenant.objects.create(name="沒有機型主檔", code="nomaster")
        cat = Category.objects.create(tenant=other, code="BC", name="背蓋")
        p = Product.objects.create(tenant=other, name="犀牛盾/IP11PM/淺灰", category=cat, requires_serial=False)
        for text in ["犀牛盾 11PM", "犀牛盾 11 pro max 淺灰", "犀牛盾 11 pro max", "DAP 13P 黑", "犀牛盾 11"]:
            self.assertEqual(find_candidates(other, text).product_ids, [], text)
        self.assertEqual(find_candidates(other, "犀牛盾 IP11PM").product_ids, [p.id])
        c = find_candidates(other, "犀牛盾 11PM 淺灰").candidates[0]
        self.assertEqual((c.level, c.differences), (RELATED, ["商品沒有:11PM"]))

    def test_new_name_written_bare_is_seen_as_the_same_item(self):
        """防重複用的對稱比對:要建 `犀牛盾/11PM/淺灰`,已經有 `犀牛盾/IP11PM/淺灰` → 同一款。"""
        r = find_candidates(self.tenant, "犀牛盾/11PM/淺灰", symmetric=True)
        self.assertEqual(r.candidates[0].product_id, self.rhino.id)
        self.assertEqual(r.candidates[0].level, EXACT)

    def test_words_written_apart_still_match_literally(self):
        """空白隔開的那幾塊照樣各自是一個字:另一邊用斜線分開寫、或只打其中一塊,都跟以前一樣。"""
        band = self._product("小米手環/8/PRO/黑")
        self.assertEqual(self._cand("小米手環 8 pro 黑", band).level, EXACT)
        glued = self._product("某手環 9 PRO 黑")
        c = self._cand("某手環 9 黑", glued)
        self.assertEqual((c.level, c.differences), (COVERS, ["商品另有:PRO"]))
        odd = self._product("某牌/11/PRO/MAX/收納包")        # 主檔認得 11 PRO MAX,但品名照字面就有這三塊
        c = self._cand("某牌 11 pro max 收納包", odd)
        self.assertEqual(c.level, EXACT)
        self.assertNotIn("機型相符", c.reasons)


class MatchLineIdentifierConflictTests(_Base):
    """待確認入庫遇到「同一個識別碼指到兩個商品」要回衝突,不能任選一筆自動對應。"""

    def test_two_products_share_a_barcode(self):
        self.std.barcode = "4710001234567"
        self.std.save()
        other = self._product("Reno16 掀蓋皮套／藍", barcode="4710001234567")
        m = services.match_line(self.tenant, self.sup, "隨便寫", raw_barcode="4710001234567")
        self.assertEqual(m["status"], IntakeItem.MatchStatus.CONFLICT)
        self.assertIsNone(m["matched_product"])
        self.assertEqual({c["product_id"] for c in m["candidates"]}, {self.std.id, other.id})

    def test_alias_and_supplier_source_disagree_on_vendor_sku(self):
        from apps.catalog.models import SupplierProduct

        other = self._product("Reno16 掀蓋皮套／藍")
        ProductAlias.objects.create(
            tenant=self.tenant, product=self.std, supplier=self.sup,
            kind=ProductAlias.Kind.VENDOR_SKU, value="RN16-BL",
        )
        SupplierProduct.objects.create(
            tenant=self.tenant, product=other, supplier=self.sup, vendor_sku="rn16 bl",
        )
        m = services.match_line(self.tenant, self.sup, "隨便寫", raw_vendor_sku="RN16-BL")
        self.assertEqual(m["status"], IntakeItem.MatchStatus.CONFLICT)
        self.assertIsNone(m["matched_product"])
        self.assertEqual({c["product_id"] for c in m["candidates"]}, {self.std.id, other.id})

    def test_barcode_and_name_alias_point_to_different_products(self):
        other = self._product("Reno16 掀蓋皮套／藍", barcode="4710001234567")
        ProductAlias.objects.create(
            tenant=self.tenant, product=self.std, supplier=self.sup,
            kind=ProductAlias.Kind.VENDOR_NAME, value="OPPO16代保護套-海洋",
        )
        m = services.match_line(
            self.tenant, self.sup, "OPPO16代保護套-海洋", raw_barcode="4710001234567"
        )
        self.assertEqual(m["status"], IntakeItem.MatchStatus.CONFLICT)
        self.assertEqual({c["product_id"] for c in m["candidates"]}, {self.std.id, other.id})


class AliasLearningTests(_Base):
    def test_specific_phrase_becomes_existing_next_time(self):
        phrase = "OPPO16代掀蓋式保護套-海洋"
        self.assertEqual(find_candidates(self.tenant, phrase).status, MatchResult.NONE)
        alias, action, _ = services.remember_phrase(self.tenant, self.std, phrase)
        self.assertEqual(action, "created")
        self.assertTrue(alias.verified)
        r = find_candidates(self.tenant, phrase)
        self.assertEqual(r.status, MatchResult.EXISTING)
        self.assertEqual(r.product_ids, [self.std.id])

    def test_alias_words_are_searchable(self):
        """記過的叫法,打一部分也找得到(別名接上一般搜尋)。"""
        services.remember_phrase(self.tenant, self.std, "歐珀十六 海洋藍側翻套")
        r = find_candidates(self.tenant, "歐珀十六")
        self.assertEqual(r.product_ids, [self.std.id])
        self.assertIn("其他叫法", r.candidates[0].reasons[0])

    def test_broad_phrase_is_keyword_only(self):
        """`reno16` 不會變成唯一別名。"""
        for phrase in ["reno16", "皮套", "藍"]:
            alias, action, _ = services.remember_phrase(self.tenant, self.std, phrase)
            self.assertEqual(action, "keyword", phrase)
            self.assertFalse(alias.verified, phrase)
            self.assertNotEqual(
                find_candidates(self.tenant, phrase).status, MatchResult.EXISTING, phrase
            )

    def test_ambiguous_phrase_is_keyword_only(self):
        """同一句話有兩款都符合 → 只能當關鍵字,而且兩款都記得進去。"""
        other = self._product("Reno16 掀蓋皮套／藍")
        a1, act1, _ = services.remember_phrase(self.tenant, self.std, "reno16 皮套 藍")
        a2, act2, _ = services.remember_phrase(self.tenant, other, "reno16 皮套 藍")
        self.assertEqual((act1, act2), ("keyword", "keyword"))
        r = find_candidates(self.tenant, "reno16 皮套 藍")
        self.assertEqual(r.status, MatchResult.CANDIDATES)
        self.assertEqual(set(r.product_ids), {self.std.id, other.id})

    def test_phrase_that_is_only_part_of_the_name_is_keyword_only(self):
        """「reno16 藍」少講了款式:現在只有一款符合,也不能學成唯一別名。"""
        alias, action, _ = services.remember_phrase(self.tenant, self.std, "reno16 藍")
        self.assertEqual(action, "keyword")
        self.assertFalse(alias.verified)

    def test_confirmed_alias_stops_being_automatic_when_a_sibling_arrives(self):
        """舊別名不能把後來才進的同系列別款蓋掉。"""
        ProductAlias.objects.create(
            tenant=self.tenant, product=self.std, supplier=self.sup,
            kind=ProductAlias.Kind.VENDOR_NAME, value="reno16 藍",
        )
        self.assertEqual(
            find_candidates(self.tenant, "reno16 藍", supplier=self.sup).status,
            MatchResult.EXISTING,
        )
        m = services.match_line(self.tenant, self.sup, "reno16 藍")
        self.assertEqual(m["status"], IntakeItem.MatchStatus.AUTO_MATCHED)

        other = self._product("Reno16 掀蓋皮套／藍")
        r = find_candidates(self.tenant, "reno16 藍", supplier=self.sup)
        self.assertEqual(r.status, MatchResult.CANDIDATES)
        self.assertEqual(set(r.product_ids), {self.std.id, other.id})
        m = services.match_line(self.tenant, self.sup, "reno16 藍")
        self.assertIsNone(m["matched_product"])
        self.assertEqual(m["status"], IntakeItem.MatchStatus.NEEDS_REVIEW)
        self.assertEqual({c["product_id"] for c in m["candidates"]}, {self.std.id, other.id})

    def test_conflict_is_reported_not_silently_repointed(self):
        other = self._product("Reno16 掀蓋皮套／藍")
        phrase = "OPPO16代保護套-海洋"
        services.remember_phrase(self.tenant, self.std, phrase)
        alias, action, owner = services.remember_phrase(self.tenant, other, phrase)
        self.assertEqual(action, "conflict")
        self.assertEqual(owner, self.std)
        self.assertEqual(
            ProductAlias.objects.get(is_active=True, verified=True).product, self.std
        )

    def test_admin_can_repoint_and_history_is_kept(self):
        other = self._product("Reno16 掀蓋皮套／藍")
        phrase = "OPPO16代保護套-海洋"
        services.remember_phrase(self.tenant, self.std, phrase)
        _, action, _ = services.remember_phrase(
            self.tenant, other, phrase, can_repoint=True
        )
        self.assertEqual(action, "repointed")
        self.assertEqual(ProductAlias.objects.filter(is_active=False).count(), 1)
        self.assertEqual(find_candidates(self.tenant, phrase).product_ids, [other.id])

    def test_edit_works_on_current_state_not_a_stale_copy(self):
        """兩個管理員同時改同一條別名:一個停用、一個只改備註。後者手上是舊資料,
        不能把「啟用中」一起寫回去、悄悄取消前者的停用。"""
        alias = ProductAlias.objects.create(
            tenant=self.tenant, product=self.std,
            kind=ProductAlias.Kind.LEGACY_NAME, value="OPPO16代保護套-海洋",
        )
        stale = ProductAlias.objects.get(pk=alias.pk)
        services.update_alias(alias, {"is_active": False})
        services.update_alias(stale, {"note": "店內舊叫法"})
        alias.refresh_from_db()
        self.assertFalse(alias.is_active)
        self.assertEqual(alias.note, "店內舊叫法")

    def test_reactivating_from_a_stale_copy_still_goes_through_the_rules(self):
        """手上那份還顯示「啟用中」,其實已經被停用、而且別的商品認領了同一句話。
        這時候送「啟用」不能因為手上的舊資料看起來沒變就跳過檢查。"""
        alias = ProductAlias.objects.create(
            tenant=self.tenant, product=self.std,
            kind=ProductAlias.Kind.BARCODE, value="4710001234567",
        )
        stale = ProductAlias.objects.get(pk=alias.pk)
        services.update_alias(alias, {"is_active": False})
        # 停用之後,這個條碼被登記在另一個商品的主檔上(這種衝突資料庫約束擋不到)
        self._product("Reno16 掀蓋皮套／藍", barcode="4710001234567")
        with self.assertRaises(services.AliasOwnedElsewhere):
            services.update_alias(stale, {"is_active": True})
        alias.refresh_from_db()
        self.assertFalse(alias.is_active)

    def test_generic_alias_unique_constraint(self):
        """通用別名(不分廠商)同一句話只能有一筆已確認的。"""
        other = self._product("Reno16 掀蓋皮套／藍")
        kw = dict(tenant=self.tenant, kind=ProductAlias.Kind.LEGACY_NAME, value="海洋套")
        ProductAlias.objects.create(product=self.std, **kw)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ProductAlias.objects.create(product=other, **kw)
        # 關鍵字不受限
        ProductAlias.objects.create(product=other, verified=False, **kw)

    def test_operator_recorded(self):
        user = self._user("clerk", "tenant_user", warehouse=self.wh)
        alias, _, _ = services.remember_phrase(
            self.tenant, self.std, "OPPO16代保護套-海洋", user=user
        )
        self.assertEqual(alias.created_by, user)
        self.assertEqual(alias.source, ProductAlias.Source.LEARNED)


class ConcurrentAliasTests(TransactionTestCase):
    """兩個人同時把同一句話記到不同商品 → 只會有一筆已確認的對應。"""

    def test_concurrent_remember(self):
        if connection.vendor != "postgresql":
            self.skipTest("需要 PostgreSQL")
        tenant = Tenant.objects.create(name="測試通訊行", code="demo")
        cat = Category.objects.create(tenant=tenant, code="LC", name="皮套")
        products = [
            Product.objects.create(
                tenant=tenant, category=cat, name=f"Reno16 側翻皮套／藍 {i}",
                requires_serial=False,
            ) for i in range(4)
        ]
        barrier = threading.Barrier(len(products))
        results, errors = [], []

        def work(product):
            try:
                barrier.wait(timeout=10)
                _, action, _ = services.remember_phrase(
                    tenant, product, "OPPO16代保護套-海洋"
                )
                results.append(action)
            except Exception as exc:  # noqa: BLE001
                errors.append(repr(exc))
            finally:
                connection.close()

        threads = [threading.Thread(target=work, args=(p,)) for p in products]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        self.assertEqual(errors, [])
        self.assertEqual(results.count("created"), 1)
        self.assertEqual(results.count("conflict"), len(products) - 1)
        self.assertEqual(
            ProductAlias.objects.filter(is_active=True, verified=True).count(), 1
        )

    def test_match_and_new_product_do_not_deadlock(self):
        """「對應既有商品」與「建新品」同時處理同一個名稱 + 條碼。兩條路要用同一個
        順序取鎖,不然會互等、被資料庫砍掉一筆(使用者看到 500)。
        (取鎖順序相反時不是每次都撞得到,所以這裡多跑幾輪。)"""
        if connection.vendor != "postgresql":
            self.skipTest("需要 PostgreSQL")
        from apps.identity.dedup import DuplicateProduct
        from apps.parties.models import Supplier

        tenant = Tenant.objects.create(name="測試通訊行", code="demo")
        cat = Category.objects.create(tenant=tenant, code="LC", name="皮套")
        sup = Supplier.objects.create(tenant=tenant, name="大盤商A")
        existing = Product.objects.create(
            tenant=tenant, category=cat, name="完全無關的既有商品", requires_serial=False
        )
        errors = []
        for round_no in range(6):
            name, barcode = f"XYZ{round_no}9 新款殼 紅", f"47199900{round_no}"
            items = []
            for _ in range(2):
                batch = services.run_intake_from_lines(
                    tenant, [{"raw_name": name, "barcode": barcode, "qty": 1, "unit_cost": 10}],
                    supplier=sup,
                )
                items.append(batch.items.get())
            barrier = threading.Barrier(2)

            def match():
                try:
                    barrier.wait(timeout=10)
                    services.resolve_item_match(items[0], existing)
                except Exception as exc:  # noqa: BLE001
                    errors.append(repr(exc))
                finally:
                    connection.close()

            def create():
                try:
                    barrier.wait(timeout=10)
                    services.resolve_item_new_product(
                        items[1], {"category": cat.id, "requires_serial": False}
                    )
                except DuplicateProduct:
                    pass          # 對方先把條碼認領走了:正常結果
                except Exception as exc:  # noqa: BLE001
                    errors.append(repr(exc))
                finally:
                    connection.close()

            threads = [threading.Thread(target=match), threading.Thread(target=create)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=30)
        self.assertEqual(errors, [])

    def test_concurrent_manual_create(self):
        """別名管理畫面那條路(create_alias)並發也只會有一筆已確認的,不會 500。"""
        if connection.vendor != "postgresql":
            self.skipTest("需要 PostgreSQL")
        tenant = Tenant.objects.create(name="測試通訊行", code="demo")
        cat = Category.objects.create(tenant=tenant, code="LC", name="皮套")
        products = [
            Product.objects.create(
                tenant=tenant, category=cat, name=f"Reno16 側翻皮套／藍 {i}",
                requires_serial=False,
            ) for i in range(4)
        ]
        barrier = threading.Barrier(len(products))
        results, errors = [], []

        def work(product):
            try:
                barrier.wait(timeout=10)
                _, action = services.create_alias(
                    tenant, product, ProductAlias.Kind.LEGACY_NAME, "OPPO16代保護套-海洋"
                )
                results.append(action)
            except Exception as exc:  # noqa: BLE001
                errors.append(repr(exc))
            finally:
                connection.close()

        threads = [threading.Thread(target=work, args=(p,)) for p in products]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        self.assertEqual(errors, [])
        self.assertEqual(sorted(results), ["conflict"] * 3 + ["created"])
        self.assertEqual(
            ProductAlias.objects.filter(is_active=True, verified=True).count(), 1
        )


class InactiveProductTests(_Base):
    def setUp(self):
        super().setUp()
        self.std.is_active = False
        self.std.save()
        self.batch = services.run_intake_from_text(
            self.tenant, "reno16/側翻/藍 x2 @150", supplier=self.sup, warehouse=self.wh
        )
        self.item = self.batch.items.get(line_no=1)

    def test_intake_lists_inactive_candidate_without_matching(self):
        self.assertIsNone(self.item.matched_product)
        self.assertEqual(self.item.candidates[0]["product_id"], self.std.id)
        self.assertFalse(self.item.candidates[0]["is_active"])

    def test_selecting_does_not_silently_reactivate(self):
        with self.assertRaises(services.IdentityError):
            services.resolve_item_match(self.item, self.std)
        self.std.refresh_from_db()
        self.assertFalse(self.std.is_active)

    def test_clerk_cannot_restore_via_intake(self):
        clerk = self._client(self._user("clerk", "tenant_user", warehouse=self.wh))
        url = f"/api/v1/identity/intake-items/{self.item.id}/match/"
        r = clerk.post(url, {"product": self.std.id}, format="json")
        self.assertEqual(r.status_code, 400)
        r = clerk.post(url, {"product": self.std.id, "restore": True}, format="json")
        self.assertEqual(r.status_code, 403)
        self.std.refresh_from_db()
        self.assertFalse(self.std.is_active)

    def test_admin_restores_explicitly(self):
        admin = self._client(self._user("boss", "tenant_admin"))
        url = f"/api/v1/identity/intake-items/{self.item.id}/match/"
        r = admin.post(url, {"product": self.std.id, "restore": True}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.std.refresh_from_db()
        self.assertTrue(self.std.is_active)


class IntakeCommitTests(_Base):
    def test_commit_adds_stock_to_existing_product_only(self):
        """四種叫法入庫後只增加既有商品的庫存,不多建商品,且查得到是誰確認的。"""
        clerk = self._user("clerk", "tenant_user", warehouse=self.wh)
        before = Product.objects.count()
        text = "\n".join(f"{p} x1 @150" for p in FOUR_PHRASINGS)
        batch = services.run_intake_from_text(
            self.tenant, text, supplier=self.sup, warehouse=self.wh, user=clerk
        )
        for item in batch.items.all():
            self.assertIsNone(item.matched_product)   # 模糊候選要人確認
            self.assertEqual(item.candidates[0]["product_id"], self.std.id)
            services.resolve_item_match(item, self.std, user=clerk)
        batch.refresh_from_db()
        po = services.commit_batch(batch, user=clerk)
        self.assertEqual(Product.objects.count(), before)
        self.assertEqual(
            StockBalance.objects.get(product=self.std, warehouse=self.wh).qty, 4
        )
        self.assertEqual(po.created_by, clerk)
        self.assertTrue(
            all(i.resolved_by == clerk for i in batch.items.all())
        )
        aliases = list(ProductAlias.objects.all())
        self.assertTrue(aliases)
        self.assertTrue(all(a.created_by == clerk for a in aliases))
