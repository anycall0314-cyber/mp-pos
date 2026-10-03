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
from .models import Brand, Category, Condition, PhoneSeries, Product

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
