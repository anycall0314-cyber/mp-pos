"""新增商品前的防重複關卡(開發計畫 §3.4、§10.1)。

重點:每一個建新品的入口都過同一道關卡,不能靠換入口或直接打 API 繞過。
"""
import io
import threading

from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIClient

from apps.identity import services as identity_services
from apps.identity.dedup import DuplicateProduct, guard_new_product
from apps.identity.models import ProductAlias, ProductDistinctDecision
from apps.inventory.models import Warehouse
from apps.parties.models import Supplier
from apps.tenants.models import Tenant, UserProfile

from .import_service import import_products_from_file
from .models import Brand, Category, Condition, PhoneModel, PhoneSeries, Product

STANDARD_NAME = "Reno16 側翻皮套／藍"


class _Base(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="測試通訊行", code="demo")
        self.cat = Category.objects.create(tenant=self.tenant, code="LC", name="皮套")
        self.wh = Warehouse.objects.create(tenant=self.tenant, code="NY", name="湳雅店")
        self.sup = Supplier.objects.create(tenant=self.tenant, name="大盤商A")
        self.std = Product.objects.create(
            tenant=self.tenant, category=self.cat, name=STANDARD_NAME,
            requires_serial=False,
        )
        self.user = get_user_model().objects.create_user(username="clerk", password="x")
        UserProfile.objects.create(
            user=self.user, role="tenant_user", tenant=self.tenant,
            default_warehouse=self.wh,
        )
        self.client_ = APIClient()
        self.client_.force_authenticate(self.user)

    def _post(self, name, **extra):
        body = {"name": name, "category": self.cat.id, "requires_serial": False, **extra}
        return self.client_.post("/api/v1/products/", body, format="json")


class SingleCreateTests(_Base):
    def test_other_phrasings_are_stopped_with_candidates(self):
        for name in [
            "reno16 皮套 藍色",          # 少寫側翻
            "reno-16 側翻皮套 藍",       # 寫法不同
            "藍色 側翻皮套 RENO16",      # 換字序
            "reno16/皮套/側翻藍",        # 連寫
        ]:
            r = self._post(name)
            self.assertEqual(r.status_code, 409, (name, r.content))
            body = r.json()
            self.assertEqual(body["kind"], "similar", name)
            self.assertEqual(body["candidates"][0]["id"], self.std.id, name)
        self.assertEqual(Product.objects.count(), 1)

    def test_more_specific_name_is_also_stopped(self):
        """前一個人建得比較籠統,下一個人寫得比較細 —— 一樣是可能重複。"""
        Product.objects.create(
            tenant=self.tenant, category=self.cat, name="Reno17 皮套 藍",
            requires_serial=False,
        )
        r = self._post("Reno17 側翻皮套 藍")
        self.assertEqual(r.status_code, 409, r.content)
        self.assertEqual(r.json()["candidates"][0]["level"], "subset")

    def test_distinct_reason_lets_it_through_and_is_recorded(self):
        r = self._post("Reno16 側翻皮套 藍 2入", distinct_reason="兩入組合包")
        self.assertEqual(r.status_code, 201, r.content)
        d = ProductDistinctDecision.objects.get()
        self.assertEqual(d.product_id, r.json()["id"])
        self.assertEqual(d.reason, "兩入組合包")
        self.assertEqual(d.decided_by, self.user)
        self.assertEqual(d.similar_products[0]["id"], self.std.id)

    def test_blank_or_one_char_reason_is_not_enough(self):
        for reason in ["", " ", "x", "。。", "..", "- -"]:
            r = self._post("reno16 皮套 藍色", distinct_reason=reason)
            self.assertEqual(r.status_code, 409, reason)

    def test_brand_material_pack_variants_must_say_why(self):
        """多寫了品牌 / 材質 / 包裝:確實可能是不同款,但要寫下來才建。"""
        for name in [
            "DAP Reno16 側翻皮套 藍", "Reno16 真皮側翻皮套 藍", "Reno16 側翻皮套 藍 2入",
        ]:
            r = self._post(name)
            self.assertEqual(r.status_code, 409, (name, r.content))
            self.assertEqual(r.json()["kind"], "similar", name)

    def test_vague_existing_name_does_not_block_specific_new_product(self):
        """既有商品只叫「皮套 藍」(沒寫機型),不該讓每個新機型的皮套都被問一次。"""
        Product.objects.create(
            tenant=self.tenant, category=self.cat, name="皮套 藍", requires_serial=False
        )
        r = self._post("Reno20 側翻皮套 藍")
        self.assertEqual(r.status_code, 201, r.content)

    def test_really_different_products_need_no_reason(self):
        for name in [
            "Reno16 Pro 側翻皮套／藍",    # 不同機型
            "Reno15 側翻皮套／藍",        # 不同代
            "Reno16 側翻皮套／深藍",      # 不同顏色
            "Reno16 磁吸殼／藍",          # 不同款
        ]:
            r = self._post(name)
            self.assertEqual(r.status_code, 201, (name, r.content))
        self.assertEqual(ProductDistinctDecision.objects.count(), 0)

    def test_exact_same_name_points_at_the_existing_product(self):
        """一字不差的同名:回候選(看得到是哪一筆),而且不能用理由繞過。"""
        r = self._post(STANDARD_NAME, distinct_reason="我就是要再建一個")
        self.assertEqual(r.status_code, 409, r.content)
        body = r.json()
        self.assertEqual(body["code"], "duplicate_product")
        self.assertEqual(body["kind"], "identifier")
        self.assertEqual(body["candidates"][0]["id"], self.std.id)
        self.assertEqual(Product.objects.count(), 1)

    def test_same_barcode_cannot_be_bypassed(self):
        self.std.barcode = "4710001234567"
        self.std.save()
        r = self._post(
            "完全不一樣的名字", barcode="4710001234567", distinct_reason="我說它不一樣",
        )
        self.assertEqual(r.status_code, 409, r.content)
        self.assertEqual(r.json()["kind"], "identifier")
        self.assertEqual(Product.objects.count(), 1)

    def test_name_that_is_a_confirmed_alias_cannot_be_bypassed(self):
        ProductAlias.objects.create(
            tenant=self.tenant, product=self.std,
            kind=ProductAlias.Kind.LEGACY_NAME, value="歐珀十六海洋套",
        )
        r = self._post("歐珀十六海洋套", distinct_reason="我說它不一樣")
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()["kind"], "identifier")

    def test_inactive_product_still_counts(self):
        self.std.is_active = False
        self.std.save()
        r = self._post("reno16 側翻皮套 藍")
        self.assertEqual(r.status_code, 409)
        self.assertFalse(r.json()["candidates"][0]["is_active"])

    def test_secondhand_and_new_are_separate(self):
        used_cat = Category.objects.create(
            tenant=self.tenant, code="AA", name="中古機", is_secondhand_default=True
        )
        Product.objects.create(
            tenant=self.tenant, category=used_cat, name="iPhone 15 128GB 黑"
        )
        phone_cat = Category.objects.create(tenant=self.tenant, code="PH", name="手機")
        r = self.client_.post(
            "/api/v1/products/",
            {"name": "iPhone 15 128GB 黑 全新", "category": phone_cat.id},
            format="json",
        )
        self.assertEqual(r.status_code, 201, r.content)

    def test_other_tenant_products_do_not_block(self):
        other = Tenant.objects.create(name="別家", code="other")
        cat = Category.objects.create(tenant=other, code="LC", name="皮套")
        user = get_user_model().objects.create_user(username="other", password="x")
        UserProfile.objects.create(user=user, role="tenant_admin", tenant=other,
                                   is_warehouse_locked=False)
        c = APIClient()
        c.force_authenticate(user)
        r = c.post("/api/v1/products/", {
            "name": STANDARD_NAME, "category": cat.id, "requires_serial": False,
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content)


class EditExistingTests(_Base):
    """改既有商品也過關卡,不然可以先用無關的名字建檔再改名繞過。"""

    def setUp(self):
        super().setUp()
        self.std.barcode = "4710001234567"
        self.std.save()
        self.other = Product.objects.create(
            tenant=self.tenant, category=self.cat, name="完全無關的東西",
            requires_serial=False,
        )
        admin = get_user_model().objects.create_user(username="boss", password="x")
        UserProfile.objects.create(
            user=admin, role="tenant_admin", tenant=self.tenant, is_warehouse_locked=False
        )
        self.admin = APIClient()
        self.admin.force_authenticate(admin)
        self.url = f"/api/v1/products/{self.other.id}/"

    def test_cannot_take_another_products_barcode(self):
        r = self.client_.patch(
            self.url, {"barcode": "4710001234567", "distinct_reason": "我說可以"},
            format="json",
        )
        self.assertEqual(r.status_code, 409, r.content)
        self.assertEqual(r.json()["kind"], "identifier")
        self.other.refresh_from_db()
        self.assertEqual(self.other.barcode, "")

    def test_cannot_rename_to_an_existing_name(self):
        r = self.client_.patch(
            self.url, {"name": STANDARD_NAME, "distinct_reason": "我說可以"}, format="json"
        )
        self.assertEqual(r.status_code, 409, r.content)
        self.assertEqual(r.json()["candidates"][0]["id"], self.std.id)

    def test_rename_to_similar_needs_reason(self):
        r = self.client_.patch(self.url, {"name": "reno-16 側翻皮套 藍"}, format="json")
        self.assertEqual(r.status_code, 409, r.content)
        self.assertEqual(r.json()["candidates"][0]["id"], self.std.id)
        r = self.client_.patch(
            self.url, {"name": "reno-16 側翻皮套 藍", "distinct_reason": "門市展示品"},
            format="json",
        )
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(ProductDistinctDecision.objects.get().product, self.other)

    def test_unrelated_edits_are_not_questioned(self):
        """改售價、存自己原本的品名與條碼,不會被自己擋到。"""
        r = self.client_.patch(
            f"/api/v1/products/{self.std.id}/",
            {"list_price": "590", "name": self.std.name, "barcode": "4710001234567"},
            format="json",
        )
        self.assertEqual(r.status_code, 200, r.content)

    def test_a_product_is_not_its_own_duplicate(self):
        """改成自己的別名、或只是換個寫法,不會被自己擋到。"""
        ProductAlias.objects.create(
            tenant=self.tenant, product=self.std,
            kind=ProductAlias.Kind.LEGACY_NAME, value="OPPO16代保護套-海洋",
        )
        url = f"/api/v1/products/{self.std.id}/"
        r = self.client_.patch(url, {"name": "OPPO16代保護套-海洋"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        r = self.client_.patch(url, {"name": "Reno16 側翻皮套 藍色"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)

    def test_bulk_edit_cannot_spread_one_barcode(self):
        third = Product.objects.create(
            tenant=self.tenant, category=self.cat, name="另一個無關的東西",
            requires_serial=False,
        )
        r = self.admin.post("/api/v1/products/bulk-edit/", {
            "ids": [self.other.id, third.id], "patch": {"barcode": "4719990001112"},
        }, format="json")
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(Product.objects.filter(barcode="4719990001112").count(), 0)


class OtherEntryPointsTests(_Base):
    def test_bulk_rows_are_checked_one_by_one(self):
        body = {
            "common": {"category": self.cat.id, "requires_serial": False},
            "items": [{"name": "Reno20 側翻皮套 黑"}, {"name": "reno16 皮套 藍色"}],
        }
        r = self.client_.post("/api/v1/products/bulk/", body, format="json")
        self.assertEqual(r.status_code, 409, r.content)
        errs = r.json()["errors"]
        self.assertEqual([e["line"] for e in errs], [2])
        self.assertEqual(errs[0]["duplicate"]["candidates"][0]["id"], self.std.id)
        self.assertEqual(Product.objects.count(), 1)       # 整批回滾

        # 那一列自己說明差異才放行;不能整批一次帶過
        body["items"][1]["distinct_reason"] = "無側翻的平價款"
        r = self.client_.post("/api/v1/products/bulk/", body, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(Product.objects.count(), 3)
        self.assertEqual(ProductDistinctDecision.objects.count(), 1)

    def test_bulk_catches_duplicates_inside_the_same_batch(self):
        body = {
            "common": {"category": self.cat.id, "requires_serial": False},
            "items": [{"name": "Reno20 側翻皮套 黑"}, {"name": "reno-20/側翻/黑"}],
        }
        r = self.client_.post("/api/v1/products/bulk/", body, format="json")
        self.assertEqual(r.status_code, 409, r.content)
        self.assertEqual([e["line"] for e in r.json()["errors"]], [2])

    def test_intake_new_product(self):
        batch = identity_services.run_intake_from_text(
            self.tenant, "reno16 皮套 藍色 x1 @150", supplier=self.sup, warehouse=self.wh
        )
        item = batch.items.get()
        url = f"/api/v1/identity/intake-items/{item.id}/new-product/"
        body = {"category": self.cat.id, "requires_serial": False}
        r = self.client_.post(url, body, format="json")
        self.assertEqual(r.status_code, 409, r.content)
        self.assertEqual(r.json()["candidates"][0]["id"], self.std.id)
        self.assertEqual(Product.objects.count(), 1)

        r = self.client_.post(url, {**body, "distinct_reason": "非側翻的平價款"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(Product.objects.count(), 2)
        self.assertEqual(ProductDistinctDecision.objects.get().decided_by, self.user)

    def test_import_skips_possible_duplicates_instead_of_deciding(self):
        csv = (
            "品名,類別,品號\n"
            "reno16 皮套 藍色,皮套,X-001\n"
            "Reno20 側翻皮套 黑,皮套,X-002\n"
            "reno-20/側翻/黑,皮套,X-003\n"       # 跟上一列是同一款
        ).encode("utf-8-sig")
        report = import_products_from_file(
            self.tenant, io.BytesIO(csv), "p.csv", dry_run=False
        )
        self.assertEqual([r["sku"] for r in report["success_rows"]], ["X-002"])
        self.assertEqual({r["sku"] for r in report["skip_rows"]}, {"X-001", "X-003"})
        self.assertTrue(all("可能相同" in r["reason"] for r in report["skip_rows"]))
        self.assertEqual(Product.objects.count(), 2)

    def test_phone_model_wizard(self):
        brand = Brand.objects.create(tenant=self.tenant, code="oppo", name="OPPO")
        series = PhoneSeries.objects.create(
            tenant=self.tenant, brand=brand, code="find", name="Find"
        )
        cond = Condition.objects.create(tenant=self.tenant, code="new", name="全新")
        phone_cat = Category.objects.create(tenant=self.tenant, code="PH", name="手機")
        # 舊品號:沒分品況
        Product.objects.create(
            tenant=self.tenant, category=phone_cat, name="Find 9 256GB 黑"
        )
        payload = {
            "brand_id": brand.id, "series_id": series.id, "generation": 9,
            "main_category_id": phone_cat.id,
            "condition_ids": [cond.id], "capacities": ["256GB"], "colors": ["黑", "白"],
        }
        url = "/api/v1/products/create-phone-model/"

        preview = self.client_.post(url, {**payload, "dry_run": True}, format="json")
        self.assertEqual(preview.status_code, 200, preview.content)
        self.assertEqual(
            [d["name"] for d in preview.json()["possible_duplicates"]],
            ["Find 9 256GB 黑 全新"],
        )

        r = self.client_.post(url, payload, format="json")
        self.assertEqual(r.status_code, 409, r.content)
        self.assertEqual(Product.objects.filter(category=phone_cat).count(), 1)

        # 維修零件也一樣在預覽就查(不然預覽沒地方填理由,按建立才被擋)
        Product.objects.create(
            tenant=self.tenant, category=self.cat, name="Find 9 電池 副廠",
            requires_serial=False,
        )
        with_parts = {**payload, "colors": ["白"], "dry_run": True,
                      "parts_items": [{"name": "電池", "code": "BAT"}]}
        dup = self.client_.post(url, with_parts, format="json").json()["possible_duplicates"]
        self.assertEqual([d["name"] for d in dup], ["Find 9 電池"])

        # 同一批裡自己重複(顏色同時填了「白」跟「白色」):預覽就要看得到
        twice = {**payload, "colors": ["白", "白色"], "dry_run": True}
        dup = self.client_.post(url, twice, format="json").json()["possible_duplicates"]
        self.assertEqual([d["name"] for d in dup], ["Find 9 256GB 白色 全新"])
        self.assertEqual(dup[0]["candidates"][0]["name"], "Find 9 256GB 白 全新")

        # 一句理由套整批不行:要對到被擋的那一筆
        r = self.client_.post(
            url, {**payload, "distinct_reason": "舊品號沒分品況"}, format="json"
        )
        self.assertEqual(r.status_code, 409, r.content)
        r = self.client_.post(url, {
            **payload,
            "distinct_reasons": {"Find 9 256GB 白 全新": "寫錯列"},
        }, format="json")
        self.assertEqual(r.status_code, 409, r.content)

        r = self.client_.post(url, {
            **payload,
            "distinct_reasons": {"Find 9 256GB 黑 全新": "舊品號沒分品況"},
        }, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(Product.objects.filter(category=phone_cat).count(), 3)
        d = ProductDistinctDecision.objects.get()
        self.assertEqual(d.product.name, "Find 9 256GB 黑 全新")
        self.assertEqual(d.reason, "舊品號沒分品況")


class PhoneWizardMainUnitTests(_Base):
    """「新增手機型號」排出來的主機:名字很像、但一定不是同一個商品的,不該要人逐筆寫「哪裡不同」。

    owner 2026-10-07 在測試站要建 iPhone 17:40 列每一列都被要求說明 —— 全新 / 已拆封的對上叫 `IP17/黑` 的皮套,
    中古機的對上同一批裡的「中古機(保固內)」。資料庫裡根本還沒有任何 iPhone 17 手機。
    """

    URL = "/api/v1/products/create-phone-model/"

    def setUp(self):
        super().setUp()
        self.brand = Brand.objects.create(tenant=self.tenant, code="apple", name="Apple")
        self.series = PhoneSeries.objects.create(
            tenant=self.tenant, brand=self.brand, code="iphone", name="iPhone"
        )
        self.phones = Category.objects.create(tenant=self.tenant, code="PH", name="手機")
        mk = lambda code, name, order, **kw: Condition.objects.create(   # noqa: E731
            tenant=self.tenant, code=code, name=name, sort_order=order, **kw)
        self.new = mk("new", "全新", 1)
        self.opened = mk("open", "已拆封", 2, tracks_unit_condition=True)
        self.used_w = mk("usedw", "中古機(保固內)", 3, is_secondhand=True, tracks_unit_condition=True)
        self.used = mk("used", "中古機", 4, is_secondhand=True, tracks_unit_condition=True)
        # 機型主檔有 iPhone 17:店裡配件寫的 `IP17` 才認得出是這個機型
        self.model = PhoneModel.objects.create(
            tenant=self.tenant, code="iphone-17", name="iPhone 17", match_key="iphone 17",
            brand=self.brand, series=self.series, generation=17,
        )
        # 皮套就叫「機型 / 顏色」
        for color in ("黑", "藍"):
            Product.objects.create(tenant=self.tenant, category=self.cat,
                                   name=f"IP17/{color}", requires_serial=False)

    def payload(self, **over):
        return {
            "brand_id": self.brand.id, "series_id": self.series.id, "generation": 17,
            "main_category_id": self.phones.id,
            "condition_ids": [self.new.id], "capacities": ["256G"], "colors": ["黑色"],
            **over,
        }

    def flagged(self, **over):
        r = self.client_.post(self.URL, {**self.payload(**over), "dry_run": True}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        return {d["name"]: [c["name"] for c in d["candidates"]] for d in r.json()["possible_duplicates"]}

    def phones_now(self):
        return sorted(Product.objects.filter(category=self.phones).values_list("name", flat=True))

    def test_the_reported_case_needs_no_reasons(self):
        """四個品況 × 兩個容量 × 兩個顏色:沒有一列需要說明,直接建得起來。"""
        every = {
            "condition_ids": [self.new.id, self.opened.id, self.used_w.id, self.used.id],
            "capacities": ["256G", "512G"], "colors": ["黑色", "藍色"],
        }
        self.assertEqual(self.flagged(**every), {})
        r = self.client_.post(self.URL, self.payload(**every), format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(len(self.phones_now()), 16)
        self.assertEqual(ProductDistinctDecision.objects.count(), 0)

    def test_accessory_with_a_bare_model_name_is_not_the_phone(self):
        self.assertEqual(self.flagged(), {})                                # 皮套 `IP17/黑` 不算

    def test_another_condition_of_the_same_model_is_not_a_duplicate(self):
        """先建了「中古機(保固內)」,之後再補「中古機」:同一個機型、品況不同,本來就是兩個品號。"""
        r = self.client_.post(self.URL, self.payload(condition_ids=[self.used_w.id]), format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self.flagged(condition_ids=[self.used.id]), {})
        r = self.client_.post(self.URL, self.payload(condition_ids=[self.used.id]), format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self.phones_now(), ["iPhone 17 256G 黑色 中古機", "iPhone 17 256G 黑色 中古機(保固內)"])

    def test_same_condition_written_twice_in_one_batch_is_still_caught(self):
        """同一個品況裡顏色寫了「藍」又寫「藍色」:這才是真的重複,照樣要抓(預覽與正式建立都是)。"""
        twice = {"condition_ids": [self.used_w.id, self.used.id], "colors": ["藍", "藍色"]}
        self.assertEqual(self.flagged(**twice), {
            "iPhone 17 256G 藍色 中古機(保固內)": ["iPhone 17 256G 藍 中古機(保固內)"],
            "iPhone 17 256G 藍色 中古機": ["iPhone 17 256G 藍 中古機"],
        })
        r = self.client_.post(self.URL, self.payload(**twice), format="json")
        self.assertEqual(r.status_code, 409, r.content)
        self.assertEqual(sorted(i["name"] for i in r.json()["items"]),
                         ["iPhone 17 256G 藍色 中古機", "iPhone 17 256G 藍色 中古機(保固內)"])
        self.assertEqual(self.phones_now(), [])                            # 整批沒建

    def test_an_old_phone_without_condition_is_still_caught(self):
        """以前用一般表單建的手機(追蹤序號、沒掛機型也沒分品況):真的可能是同一個,照樣提醒。"""
        Product.objects.create(tenant=self.tenant, category=self.phones, name="iPhone 17 256G 黑色")
        self.assertEqual(self.flagged(), {"iPhone 17 256G 黑色 全新": ["iPhone 17 256G 黑色"]})
        r = self.client_.post(self.URL, self.payload(), format="json")
        self.assertEqual(r.status_code, 409, r.content)
        r = self.client_.post(self.URL, {
            **self.payload(), "distinct_reasons": {"iPhone 17 256G 黑色 全新": "舊的沒分品況"},
        }, format="json")
        self.assertEqual(r.status_code, 200, r.content)                    # 說明了就建得起來

    def test_a_quantity_item_that_states_a_capacity_is_still_caught(self):
        """不追蹤序號、但名字寫了容量的:多半是以前建錯的手機,不能當成配件略過 —— 放在哪個類別都一樣。"""
        Product.objects.create(tenant=self.tenant, category=self.phones,
                               name="iPhone 17 256G 黑色", requires_serial=False)
        self.assertEqual(self.flagged(), {"iPhone 17 256G 黑色 全新": ["iPhone 17 256G 黑色"]})
        r = self.client_.post(self.URL, self.payload(), format="json")
        self.assertEqual(r.status_code, 409, r.content)

    def test_a_quantity_item_with_capacity_in_another_category_is_still_caught(self):
        other = Category.objects.create(tenant=self.tenant, code="GD", name="商品")
        Product.objects.create(tenant=self.tenant, category=other,
                               name="iPhone 17 256G 黑", requires_serial=False)
        self.assertEqual(self.flagged(), {"iPhone 17 256G 黑色 全新": ["iPhone 17 256G 黑"]})

    def test_capacity_kept_in_its_own_field_counts(self):
        """容量沒寫在品名、寫在容量那一格的,一樣算有寫容量。"""
        Product.objects.create(tenant=self.tenant, category=self.cat, name="iPhone 17 黑色",
                               capacity="256G", requires_serial=False)
        self.assertEqual(self.flagged(), {"iPhone 17 256G 黑色 全新": ["iPhone 17 黑色"]})

    def test_an_accessory_filed_under_the_phone_category_is_not_the_phone(self):
        """有的店配件就建在手機類別裡:不追蹤序號、沒寫容量,一樣不是這支手機。"""
        Product.objects.create(tenant=self.tenant, category=self.phones,
                               name="IP17 黑色", requires_serial=False)
        self.assertEqual(self.flagged(), {})

    def test_a_serial_tracked_item_is_always_caught(self):
        """追蹤序號的商品不管放在哪個類別、名字有沒有寫容量,都可能是同一支手機。"""
        tablets = Category.objects.create(tenant=self.tenant, code="TB", name="平板")
        Product.objects.create(tenant=self.tenant, category=tablets, name="iPhone 17 256G 黑色")
        Product.objects.create(tenant=self.tenant, category=self.cat, name="IP17 黑色")   # 沒寫容量,但追蹤序號
        found = self.flagged()
        self.assertEqual(list(found), ["iPhone 17 256G 黑色 全新"])
        self.assertEqual(sorted(found["iPhone 17 256G 黑色 全新"]), ["IP17 黑色", "iPhone 17 256G 黑色"])

    def test_an_old_phone_with_the_same_condition_is_still_caught(self):
        """品況一樣、名字只差一點的既有手機:這就是重複。"""
        Product.objects.create(tenant=self.tenant, category=self.phones, name="iPhone 17 256G 黑",
                               condition=self.new)
        self.assertEqual(self.flagged(), {"iPhone 17 256G 黑色 全新": ["iPhone 17 256G 黑"]})

    def test_accessories_do_not_crowd_out_a_real_duplicate(self):
        """候選只列前五個:六個叫法像 `IP17/黑` 的配件不能把真正重複的那支手機擠掉。"""
        for name in ("IP17 黑", "黑 IP17", "IP17／黑", "IP17/黑色", "IP17 黑色", "黑色/IP17"):
            Product.objects.create(tenant=self.tenant, category=self.cat, name=name, requires_serial=False)
        Product.objects.create(tenant=self.tenant, category=self.phones, name="iPhone 17 256G 黑色")
        self.assertEqual(self.flagged(), {"iPhone 17 256G 黑色 全新": ["iPhone 17 256G 黑色"]})

    def test_what_counts_as_a_written_capacity(self):
        """「有沒有寫容量」只認「數字 + GB / TB」(常見的 G、T 簡寫會補成 GB、TB),別的字、別的數字不算。"""
        from apps.identity.product_match import has_capacity, parse_features

        says = lambda text: has_capacity(parse_features(text))             # noqa: E731
        for text in ("iPhone 17 256G 黑", "iPhone 17 512GB 黑色 全新", "iPad Pro 1TB 銀", "256g",
                     "256G/黑", "256GB黑色", "256 G", "１２８ＧＢ", "1T", "1024GB", "8GB"):
            self.assertTrue(says(text), text)
        for text in ("IP17/黑", "IP17 黑色 全新", "太空盾/極空戰甲/IP17/透", "行動電源 10000mAh", "充電線 2M", "17",
                     # 認不出來的容量寫法(沒有單位、不在簡寫清單裡的 G):精靈遇到這種就不排除配件,見下一個測試
                     "iPhone 17 256 黑色", "1024G", "8G"):
            self.assertFalse(says(text), text)

    def test_capacity_typed_in_a_form_we_cannot_read_keeps_asking(self):
        """精靈的容量欄什麼都收。打 `256`(沒單位)、`1024G` 這種認不出來的寫法時,不能把同樣寫法的既有手機當成配件略過。"""
        for capacity in ("256", "1024G"):
            with self.subTest(capacity=capacity):
                old = Product.objects.create(tenant=self.tenant, category=self.phones,
                                             name=f"iPhone 17 {capacity} 黑色", requires_serial=False)
                new = f"iPhone 17 {capacity} 黑色 全新"
                found = self.flagged(capacities=[capacity])
                self.assertIn(old.name, found.get(new, []), found)
                r = self.client_.post(self.URL, self.payload(capacities=[capacity]), format="json")
                self.assertEqual(r.status_code, 409, r.content)
                self.assertFalse(Product.objects.filter(name=new).exists())
                old.delete()

    def test_a_phone_matched_through_its_other_name_is_not_an_accessory(self):
        """品名的容量認不出來(`256` 沒單位)、但另外登記了一個寫清楚的叫法的手機:是靠那個叫法對上的,它有寫容量,要照樣提醒。"""
        old = Product.objects.create(tenant=self.tenant, category=self.phones,
                                     name="iPhone 17 256 黑色", requires_serial=False)
        self.assertEqual(self.flagged(), {})          # 沒有那個叫法時本來就對不上(256 對 256G,比對的老問題)
        ProductAlias.objects.create(
            tenant=self.tenant, product=old, kind=ProductAlias.Kind.LEGACY_NAME,
            value="iPhone 17 256GB 黑色 台版 全新",
        )
        self.assertEqual(self.flagged(), {"iPhone 17 256G 黑色 全新": ["iPhone 17 256 黑色"]})
        r = self.client_.post(self.URL, self.payload(), format="json")
        self.assertEqual(r.status_code, 409, r.content)
        self.assertFalse(Product.objects.filter(name="iPhone 17 256G 黑色 全新").exists())
        # 皮套就算也登記了別的叫法(沒寫容量的),一樣不算
        case = Product.objects.get(name="IP17/黑")
        ProductAlias.objects.create(
            tenant=self.tenant, product=case, kind=ProductAlias.Kind.LEGACY_NAME, value="iPhone 17 黑色 皮套",
        )
        self.assertEqual(list(self.flagged()), ["iPhone 17 256G 黑色 全新"])
        self.assertEqual(self.flagged()["iPhone 17 256G 黑色 全新"], ["iPhone 17 256 黑色"])

    def test_only_the_capacity_box_decides_whether_capacity_is_readable(self):
        """機型後綴或顏色裡剛好有 `8GB`(記憶體)不算:容量那一格填 `256` 就是認不出來,同樣寫法的既有手機要照樣提醒。"""
        # (1) 後綴裡有 8GB
        oppo = Brand.objects.create(tenant=self.tenant, code="oppo", name="OPPO")
        reno = PhoneSeries.objects.create(tenant=self.tenant, brand=oppo, code="reno", name="Reno")
        Product.objects.create(tenant=self.tenant, category=self.phones,
                               name="Reno16 黑色 256", requires_serial=False)
        by_suffix = {"brand_id": oppo.id, "series_id": reno.id, "generation": 16,
                     "model_suffix": "8GB", "capacities": ["256"]}
        self.assertEqual(self.flagged(**by_suffix), {"Reno 16 8GB 256 黑色 全新": ["Reno16 黑色 256"]})
        r = self.client_.post(self.URL, self.payload(**by_suffix), format="json")
        self.assertEqual(r.status_code, 409, r.content)
        # (2) 顏色裡有 8GB
        Product.objects.create(tenant=self.tenant, category=self.phones,
                               name="iPhone 17 256 黑色", requires_serial=False)
        by_color = {"capacities": ["256"], "colors": ["8GB黑色"]}
        found = self.flagged(**by_color)
        self.assertIn("iPhone 17 256 黑色", found.get("iPhone 17 256 8GB黑色 全新", []), found)
        r = self.client_.post(self.URL, self.payload(**by_color), format="json")
        self.assertEqual(r.status_code, 409, r.content)
        self.assertEqual(Product.objects.filter(name__endswith="全新").count(), 0)   # 兩次都沒有建出來
        # 反過來:容量那一格寫得清楚(256G)時,後綴裡有沒有 8GB 都照樣排除皮套
        self.assertEqual(self.flagged(model_suffix="8GB"), {})

    def test_general_form_is_unchanged(self):
        """只有精靈排出來的主機這樣比;一般表單建一個名字像配件的商品,照舊要說明。"""
        r = self._post("IP17 黑")
        self.assertEqual(r.status_code, 409, r.content)
        self.assertEqual(r.json()["kind"], DuplicateProduct.SIMILAR)
        # 一般表單建一個名字像手機(有寫容量)的:照舊拿皮套來問(這個入口不知道人要建的是不是主機)
        r = self._post("iPhone 17 256G 黑")
        self.assertEqual(r.status_code, 409, r.content)
        self.assertEqual(r.json()["kind"], DuplicateProduct.SIMILAR)
        self.assertIn("IP17/黑", [c["name"] for c in r.json()["candidates"]])


class ConcurrentCreateTests(TransactionTestCase):
    """同一個條碼同時被兩個人拿來建檔 → 只會建出一個。"""

    def test_same_barcode(self):
        if connection.vendor != "postgresql":
            self.skipTest("需要 PostgreSQL")
        tenant = Tenant.objects.create(name="測試通訊行", code="demo")
        cat = Category.objects.create(tenant=tenant, code="LC", name="皮套")
        barrier = threading.Barrier(4)
        results = []

        def work(i):
            try:
                barrier.wait(timeout=10)
                with transaction.atomic():
                    guard_new_product(tenant, name=f"完全不同的東西{i}號", barcode="4719999")
                    Product.objects.create(
                        tenant=tenant, category=cat, name=f"完全不同的東西{i}號",
                        barcode="4719999", requires_serial=False,
                    )
                results.append("created")
            except DuplicateProduct as dup:
                results.append(dup.kind)
            except Exception as exc:  # noqa: BLE001
                results.append(repr(exc))
            finally:
                connection.close()

        threads = [threading.Thread(target=work, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        self.assertEqual(sorted(results), ["created"] + ["identifier"] * 3)
        self.assertEqual(Product.objects.filter(barcode="4719999").count(), 1)
