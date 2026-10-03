"""商品防重複:API 層測試(開發計畫 §10.1)。

涵蓋各入口共用同一批候選、零庫存 / 停用、鎖倉、租戶隔離、
以及既有的銷貨可選規則與 IMEI / 中文搜尋安全閥不被放寬。
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.identity.models import ProductAlias
from apps.inventory.models import ProductSerial, StockBalance, Warehouse
from apps.parties.models import Supplier
from apps.tenants.models import Tenant, UserProfile

from .models import Category, Product

FOUR_PHRASINGS = [
    "reno16 皮套 藍色",
    "reno-16 側翻皮套 藍",
    "reno16/側翻/藍",
    "reno16/皮套/側翻藍",
]


class _ApiBase(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="測試通訊行", code="demo")
        self.cat = Category.objects.create(tenant=self.tenant, code="LC", name="皮套")
        self.wh = Warehouse.objects.create(tenant=self.tenant, code="NY", name="湳雅店")
        self.wh2 = Warehouse.objects.create(tenant=self.tenant, code="MS", name="民生店")
        self.sup = Supplier.objects.create(tenant=self.tenant, name="大盤商A")
        self.std = Product.objects.create(
            tenant=self.tenant, category=self.cat, name="Reno16 側翻皮套／藍",
            requires_serial=False,
        )
        self.clerk = self._client("clerk", "tenant_user", warehouse=self.wh)
        self.admin = self._client("boss", "tenant_admin")

    def _client(self, name, role, tenant=None, warehouse=None):
        user = get_user_model().objects.create_user(username=name, password="x")
        UserProfile.objects.create(
            user=user, role=role, tenant=tenant or self.tenant,
            default_warehouse=warehouse, is_warehouse_locked=(role == "tenant_user"),
        )
        c = APIClient()
        c.force_authenticate(user)
        return c

    def _search_ids(self, client, q, **params):
        r = client.get("/api/v1/products/", {"search": q, **params})
        self.assertEqual(r.status_code, 200, r.content)
        return [p["id"] for p in r.json()["results"]]

    def _resolve(self, client, q, **params):
        r = client.get("/api/v1/products/resolve/", {"q": q, **params})
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()


class SearchEntryPointsTests(_ApiBase):
    def test_four_phrasings_found_by_general_search(self):
        """商品管理 / 進貨下拉用的 `?search=` 也找得到,而且排在長得像的前面。"""
        for name in [
            "Reno16 Pro 側翻皮套／藍", "Reno15 側翻皮套／藍", "Reno16 側翻皮套／深藍",
            "Reno16 側翻皮套／黑", "Reno16 磁吸殼／藍", "Reno16 掛繩／藍",
        ]:
            Product.objects.create(
                tenant=self.tenant, category=self.cat, name=name, requires_serial=False
            )
        for q in FOUR_PHRASINGS:
            ids = self._search_ids(self.clerk, q)
            self.assertTrue(ids, q)
            self.assertEqual(ids[0], self.std.id, q)

    def test_store_abbreviation_found_by_general_search(self):
        """店內縮寫(IP13PM)與完整機型名是兩套寫法,字面相似度對不起來,
        要靠共用比對查機型主檔才找得到。"""
        from .models import PhoneModel

        PhoneModel.objects.create(
            tenant=self.tenant, code="iphone-13-pro-max",
            name="iPhone 13 Pro Max", match_key="iphone 13 pro max",
        )
        case = Product.objects.create(
            tenant=self.tenant, category=self.cat, name="DAP/IP13PM/側翻藍",
            requires_serial=False,
        )
        ids = self._search_ids(self.clerk, "iphone 13 pro max 側翻皮套 藍色")
        self.assertEqual(ids[:1], [case.id])

    def test_four_phrasings_found_by_resolve_with_reasons(self):
        for q in FOUR_PHRASINGS:
            data = self._resolve(self.clerk, q)
            self.assertEqual(data["status"], "candidates", q)
            top = data["candidates"][0]
            self.assertEqual(top["product"]["id"], self.std.id, q)
            self.assertTrue(top["reasons"], q)
            self.assertTrue(top["selectable"], q)

    def test_alias_reachable_from_general_search(self):
        ProductAlias.objects.create(
            tenant=self.tenant, product=self.std,
            kind=ProductAlias.Kind.LEGACY_NAME, value="歐珀十六海洋套",
        )
        self.assertEqual(self._search_ids(self.clerk, "歐珀十六海洋套"), [self.std.id])
        self.assertEqual(self._resolve(self.clerk, "歐珀十六海洋套")["status"], "existing")

    def test_zero_stock_variants(self):
        """本店無 StockBalance 列 / 本店 0 / 只有他店有庫存,都找得到且顯示 0。"""
        def qty():
            return self._resolve(self.clerk, "reno16/側翻/藍")["candidates"][0]["product"]["stock_qty"]

        self.assertEqual(qty(), 0)                                   # 完全沒有餘額列
        StockBalance.objects.create(
            tenant=self.tenant, product=self.std, warehouse=self.wh, qty=0
        )
        self.assertEqual(qty(), 0)                                   # 本店 0
        StockBalance.objects.create(
            tenant=self.tenant, product=self.std, warehouse=self.wh2, qty=7
        )
        self.assertEqual(qty(), 0)                                   # 只有他店有

    def test_locked_clerk_cannot_peek_other_store_stock(self):
        StockBalance.objects.create(
            tenant=self.tenant, product=self.std, warehouse=self.wh2, qty=7
        )
        data = self._resolve(self.clerk, "reno16/側翻/藍", warehouse=self.wh2.id)
        self.assertEqual(data["candidates"][0]["product"]["stock_qty"], 0)
        # 管理員不鎖倉,可以看指定門市
        data = self._resolve(self.admin, "reno16/側翻/藍", warehouse=self.wh2.id)
        self.assertEqual(data["candidates"][0]["product"]["stock_qty"], 7)

    def test_locked_clerk_without_a_store_sees_no_stock(self):
        """鎖倉但沒設門市的帳號:帶 warehouse 參數也看不到任何一店的庫存。"""
        StockBalance.objects.create(
            tenant=self.tenant, product=self.std, warehouse=self.wh2, qty=7
        )
        nowhere = self._client("nowhere", "tenant_user")   # default_warehouse=None
        for params in ({}, {"warehouse": self.wh2.id}):
            data = self._resolve(nowhere, "reno16/側翻/藍", **params)
            self.assertEqual(data["candidates"][0]["product"]["stock_qty"], 0, params)

    def test_secondhand_filter(self):
        used = Product.objects.create(
            tenant=self.tenant, category=self.cat, name="中古 Reno16 側翻皮套 藍",
            is_secondhand=True,
        )
        ids = [c["product"]["id"] for c in
               self._resolve(self.clerk, "reno16 側翻 藍", is_secondhand="false")["candidates"]]
        self.assertIn(self.std.id, ids)
        self.assertNotIn(used.id, ids)


class InactiveProductApiTests(_ApiBase):
    def setUp(self):
        super().setUp()
        self.std.is_active = False
        self.std.save()

    def test_resolve_shows_inactive_but_not_selectable(self):
        top = self._resolve(self.clerk, "reno16/側翻/藍")["candidates"][0]
        self.assertEqual(top["product"]["id"], self.std.id)
        self.assertFalse(top["is_active"])
        self.assertFalse(top["selectable"])
        self.assertFalse(top["can_restore"])
        self.assertTrue(self._resolve(self.admin, "reno16/側翻/藍")["candidates"][0]["can_restore"])

    def test_search_does_not_reactivate(self):
        self._resolve(self.clerk, "reno16/側翻/藍")
        self._search_ids(self.clerk, "reno16/側翻/藍")
        self.std.refresh_from_db()
        self.assertFalse(self.std.is_active)

    def test_purchase_search_with_active_filter_excludes_it(self):
        self.assertEqual(self._search_ids(self.clerk, "reno16/側翻/藍", is_active="true"), [])

    def test_only_admin_can_restore(self):
        url = f"/api/v1/products/{self.std.id}/restore/"
        self.assertEqual(self.clerk.post(url).status_code, 403)
        r = self.clerk.patch(
            f"/api/v1/products/{self.std.id}/", {"is_active": True}, format="json"
        )
        self.assertEqual(r.status_code, 403)
        self.std.refresh_from_db()
        self.assertFalse(self.std.is_active)

        self.assertEqual(self.admin.post(url).status_code, 200)
        self.std.refresh_from_db()
        self.assertTrue(self.std.is_active)


class ExistingSalesRulesTests(_ApiBase):
    """放寬找商品的方式,不能順便放寬銷貨可選與搜尋安全閥。"""

    def test_zero_stock_physical_not_sales_pickable(self):
        for q in FOUR_PHRASINGS:
            ids = self._search_ids(self.clerk, q, sales_pickable="true", is_active="true")
            self.assertNotIn(self.std.id, ids, q)
        StockBalance.objects.create(
            tenant=self.tenant, product=self.std, warehouse=self.wh, qty=1
        )
        self.assertIn(
            self.std.id,
            self._search_ids(self.clerk, "reno16/側翻/藍", sales_pickable="true"),
        )

    def test_virtual_product_still_pickable(self):
        fee = Product.objects.create(
            tenant=self.tenant, category=self.cat, name="Reno16 側翻皮套 貼膜工資",
            is_virtual=True, requires_serial=False,
        )
        ids = self._search_ids(self.clerk, "reno16 側翻皮套 貼膜工資", sales_pickable="true")
        self.assertEqual(ids, [fee.id])

    def test_chinese_query_does_not_match_sku(self):
        """「中古 11」不能因為品號含 11 就把不相干的商品帶出來。"""
        cat = Category.objects.create(tenant=self.tenant, code="A11", name="雜項")
        unrelated = Product.objects.create(
            tenant=self.tenant, category=cat, name="透明殼", requires_serial=False
        )
        self.assertIn("11", unrelated.sku)
        used = Product.objects.create(
            tenant=self.tenant, category=self.cat, name="中古iPhone11"
        )
        ids = self._search_ids(self.clerk, "中古 11")
        self.assertIn(used.id, ids)
        self.assertNotIn(unrelated.id, ids)

    def test_short_number_does_not_match_imei(self):
        """「18 pro 256」不能命中 IMEI 裡有 18 的機器。"""
        phone = Product.objects.create(
            tenant=self.tenant, category=self.cat, name="iPhone 15 128GB 黑"
        )
        ProductSerial.objects.create(
            tenant=self.tenant, product=phone, warehouse=self.wh,
            serial_no="351800000000001",
        )
        self.assertNotIn(phone.id, self._search_ids(self.clerk, "18 pro 256"))
        # 完整 IMEI 仍然找得到
        self.assertEqual(self._search_ids(self.clerk, "351800000000001"), [phone.id])


class TenantIsolationTests(_ApiBase):
    def setUp(self):
        super().setUp()
        self.other = Tenant.objects.create(name="別家通訊行", code="other")
        self.other_cat = Category.objects.create(tenant=self.other, code="LC", name="皮套")
        self.other_wh = Warehouse.objects.create(tenant=self.other, code="X", name="別家店")
        self.other_sup = Supplier.objects.create(tenant=self.other, name="別家盤商")
        self.other_product = Product.objects.create(
            tenant=self.other, category=self.other_cat, name="Reno16 側翻皮套 藍",
            requires_serial=False,
        )
        StockBalance.objects.create(
            tenant=self.other, product=self.other_product, warehouse=self.other_wh, qty=9
        )
        self.outsider = self._client("outsider", "tenant_admin", tenant=self.other)

    def test_candidates_and_stock_stay_in_own_tenant(self):
        mine = [c["product"]["id"] for c in self._resolve(self.clerk, "reno16 側翻 藍")["candidates"]]
        self.assertEqual(mine, [self.std.id])
        theirs = self._resolve(self.outsider, "reno16 側翻 藍")["candidates"]
        self.assertEqual([c["product"]["id"] for c in theirs], [self.other_product.id])
        self.assertEqual(self._search_ids(self.outsider, "reno16 側翻 藍"), [self.other_product.id])

    def test_cannot_alias_other_tenants_product_or_supplier(self):
        r = self.outsider.post("/api/v1/identity/aliases/", {
            "product": self.std.id, "kind": "legacy_name", "value": "偷掛別家",
        }, format="json")
        self.assertEqual(r.status_code, 400, r.content)
        r = self.outsider.post("/api/v1/identity/aliases/", {
            "product": self.other_product.id, "supplier": self.sup.id,
            "kind": "vendor_name", "value": "偷用別家廠商",
        }, format="json")
        self.assertEqual(r.status_code, 400, r.content)
        r = self.outsider.post("/api/v1/identity/aliases/remember/", {
            "product": self.std.id, "value": "偷掛別家",
        }, format="json")
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(ProductAlias.objects.count(), 0)

    def test_cannot_read_or_restore_other_tenants_product(self):
        self.std.is_active = False
        self.std.save()
        self.assertEqual(
            self.outsider.post(f"/api/v1/products/{self.std.id}/restore/").status_code, 404
        )
        alias = ProductAlias.objects.create(
            tenant=self.tenant, product=self.std,
            kind=ProductAlias.Kind.LEGACY_NAME, value="海洋套",
        )
        self.assertEqual(
            self.outsider.get(f"/api/v1/identity/aliases/{alias.id}/").status_code, 404
        )
        self.assertEqual(self._resolve(self.outsider, "海洋套")["status"], "none")


class AliasApiTests(_ApiBase):
    def test_remember_then_conflict(self):
        other = Product.objects.create(
            tenant=self.tenant, category=self.cat, name="Reno16 掀蓋皮套／藍",
            requires_serial=False,
        )
        body = {"product": self.std.id, "value": "OPPO16代保護套-海洋"}
        r = self.clerk.post("/api/v1/identity/aliases/remember/", body, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["action"], "created")
        # 店員再把同一句話記到別款 → 衝突,不改動
        r = self.clerk.post(
            "/api/v1/identity/aliases/remember/", {**body, "product": other.id}, format="json"
        )
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()["owner"]["id"], self.std.id)
        self.assertEqual(
            ProductAlias.objects.get(is_active=True, verified=True).product_id, self.std.id
        )

    def test_broad_phrase_reported_as_keyword(self):
        r = self.clerk.post(
            "/api/v1/identity/aliases/remember/",
            {"product": self.std.id, "value": "reno16"}, format="json",
        )
        self.assertEqual(r.json()["action"], "keyword")
        self.assertFalse(r.json()["alias"]["verified"])

    def test_manual_create_conflict_is_409_not_500(self):
        other = Product.objects.create(
            tenant=self.tenant, category=self.cat, name="Reno16 掀蓋皮套／藍",
            requires_serial=False,
        )
        body = {"product": self.std.id, "kind": "legacy_name", "value": "OPPO16代保護套-海洋"}
        r = self.clerk.post("/api/v1/identity/aliases/", body, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertTrue(r.json()["verified"])
        self.assertEqual(r.json()["created_by_name"], "clerk")
        r = self.clerk.post(
            "/api/v1/identity/aliases/", {**body, "product": other.id}, format="json"
        )
        self.assertEqual(r.status_code, 409, r.content)

    def test_manual_create_cannot_make_broad_phrase_a_confirmed_alias(self):
        """別名管理畫面(一般 CRUD)不能繞過「籠統叫法只能當關鍵字」。"""
        for phrase in ["reno16", "皮套", "藍", "reno16 藍"]:
            r = self.clerk.post("/api/v1/identity/aliases/", {
                "product": self.std.id, "kind": "legacy_name", "value": phrase,
                "verified": True,
            }, format="json")
            self.assertEqual(r.status_code, 201, (phrase, r.content))
            self.assertFalse(r.json()["verified"], phrase)
            self.assertNotEqual(self._resolve(self.clerk, phrase)["status"], "existing", phrase)
        # 管理員事後也不能把它升級成已確認
        alias = ProductAlias.objects.get(value="reno16")
        r = self.admin.patch(
            f"/api/v1/identity/aliases/{alias.id}/", {"verified": True}, format="json"
        )
        self.assertEqual(r.status_code, 400, r.content)
        alias.refresh_from_db()
        self.assertFalse(alias.verified)

    def test_admin_must_ask_explicitly_to_repoint(self):
        other = Product.objects.create(
            tenant=self.tenant, category=self.cat, name="Reno16 掀蓋皮套／藍",
            requires_serial=False,
        )
        url = "/api/v1/identity/aliases/remember/"
        body = {"product": self.std.id, "value": "OPPO16代保護套-海洋"}
        self.assertEqual(self.clerk.post(url, body, format="json").status_code, 200)
        moved = {**body, "product": other.id}
        # 管理員沒明講要改指 → 一樣先看到衝突
        self.assertEqual(self.admin.post(url, moved, format="json").status_code, 409)
        # 店員不能改指
        r = self.clerk.post(url, {**moved, "repoint": True}, format="json")
        self.assertEqual(r.status_code, 403)
        r = self.admin.post(url, {**moved, "repoint": True}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["action"], "repointed")
        self.assertEqual(
            ProductAlias.objects.get(is_active=True, verified=True).product_id, other.id
        )

    def test_identifier_cannot_be_claimed_twice_across_sources(self):
        """查詢時條碼欄 / 條碼別名、別名表 / 來源表、各種名稱別名是一起看的;
        寫入時也要一起看,不能把同一個識別寫到不同來源、指到不同商品。"""
        from .models import SupplierProduct

        other = Product.objects.create(
            tenant=self.tenant, category=self.cat, name="Reno16 掀蓋皮套／藍",
            requires_serial=False, barcode="4710001234567",
        )
        url = "/api/v1/identity/aliases/"
        # 條碼已經是別的商品主檔上的條碼
        r = self.clerk.post(url, {
            "product": self.std.id, "kind": "barcode", "value": "4710001234567",
        }, format="json")
        self.assertEqual(r.status_code, 409, r.content)
        # 料號已經在來源表指到別的商品
        SupplierProduct.objects.create(
            tenant=self.tenant, product=other, supplier=self.sup, vendor_sku="RN16-BL",
        )
        r = self.clerk.post(url, {
            "product": self.std.id, "kind": "vendor_sku", "value": "rn16 bl",
            "supplier": self.sup.id,
        }, format="json")
        self.assertEqual(r.status_code, 409, r.content)
        # 同一句話:一邊是舊品名、一邊是原廠型號
        r = self.clerk.post(url, {
            "product": other.id, "kind": "oem_model", "value": "歐珀 CPH2631 海洋",
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertTrue(r.json()["verified"])
        r = self.clerk.post(url, {
            "product": self.std.id, "kind": "legacy_name", "value": "歐珀cph2631/海洋",
        }, format="json")
        self.assertEqual(r.status_code, 409, r.content)
        self.assertEqual(
            ProductAlias.objects.filter(product=self.std, verified=True).count(), 0
        )

    def test_edit_cannot_reactivate_or_repoint_around_the_rules(self):
        other = Product.objects.create(
            tenant=self.tenant, category=self.cat, name="Reno16 掀蓋皮套／藍",
            requires_serial=False,
        )
        # 舊資料:一條停用中的、籠統的「已確認」別名
        broad = ProductAlias.objects.create(
            tenant=self.tenant, product=self.std, kind=ProductAlias.Kind.LEGACY_NAME,
            value="reno16", is_active=False,
        )
        r = self.admin.patch(
            f"/api/v1/identity/aliases/{broad.id}/", {"is_active": True}, format="json"
        )
        self.assertEqual(r.status_code, 400, r.content)
        # 直接把別名改到別的商品 / 換一句話:不行,要停用再新增(才留得下紀錄)
        ok = ProductAlias.objects.create(
            tenant=self.tenant, product=self.std, kind=ProductAlias.Kind.LEGACY_NAME,
            value="OPPO16代保護套-海洋",
        )
        for body in ({"product": other.id}, {"value": "OPPO16代保護套-深海"},
                     {"kind": "oem_model"}, {"supplier": self.sup.id}):
            r = self.admin.patch(f"/api/v1/identity/aliases/{ok.id}/", body, format="json")
            self.assertEqual(r.status_code, 400, (body, r.content))
        ok.refresh_from_db()
        self.assertEqual((ok.product_id, ok.value), (self.std.id, "OPPO16代保護套-海洋"))
        # 停用後別人認領了同一句話,原本那條就不能再啟用
        self.assertEqual(self.admin.patch(
            f"/api/v1/identity/aliases/{ok.id}/", {"is_active": False}, format="json"
        ).status_code, 200)
        ProductAlias.objects.create(
            tenant=self.tenant, product=other, kind=ProductAlias.Kind.LEGACY_NAME,
            value="OPPO16代保護套-海洋",
        )
        r = self.admin.patch(
            f"/api/v1/identity/aliases/{ok.id}/", {"is_active": True}, format="json"
        )
        self.assertEqual(r.status_code, 409, r.content)

    def test_only_admin_can_change_or_disable(self):
        alias = ProductAlias.objects.create(
            tenant=self.tenant, product=self.std,
            kind=ProductAlias.Kind.LEGACY_NAME, value="海洋套",
        )
        url = f"/api/v1/identity/aliases/{alias.id}/"
        self.assertEqual(
            self.clerk.patch(url, {"is_active": False}, format="json").status_code, 403
        )
        self.assertEqual(self.clerk.delete(url).status_code, 403)
        r = self.admin.patch(url, {"is_active": False}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        alias.refresh_from_db()
        self.assertFalse(alias.is_active)
        self.assertEqual(alias.updated_by.username, "boss")
