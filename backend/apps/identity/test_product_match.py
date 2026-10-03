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
