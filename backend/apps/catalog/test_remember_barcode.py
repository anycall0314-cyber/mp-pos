"""記住條碼(owner 2026-10-23「此權限作為開關形式,可以讓管理員指派」):員工帳號預設不開、管理員勾了才能記;
記成已確認的條碼別名(記下是誰記的),之後刷這個碼對到那個商品。"""
from django.test import TestCase

from apps.backup.tests.factory import Company
from apps.catalog.models import Product
from apps.identity.models import ProductAlias
from apps.tenants import abilities

EAN = "4712345678901"


class RememberBarcodeTests(TestCase):
    def setUp(self):
        self.c = Company("a", "甲通訊行", "甲")
        self.case = self.c.case
        Product.objects.filter(pk=self.case.pk).update(barcode="OLD-LC-01")     # 舊品號佔著條碼那一格

    def remember(self, product=None, code=EAN, client=None):
        return (client or self.c.admin).post(
            f"/api/v1/products/{(product or self.case).id}/remember-barcode/", {"code": code}, format="json")

    def grant(self, on=True):
        r = self.c.admin.patch(f"/api/v1/staff-accounts/{self.c.clerk_user.id}/",
                               {"abilities": {"remember_barcode": on}}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        return r.json()

    def test_clerks_cannot_until_a_manager_turns_it_on(self):
        self.assertFalse(abilities.can(self.c.clerk_user, "remember_barcode"))
        self.assertEqual(self.remember(client=self.c.clerk).status_code, 403)
        row = self.grant()
        self.assertTrue(row["abilities"]["remember_barcode"])
        self.c.clerk_user.profile.refresh_from_db()
        self.assertIn("+remember_barcode", self.c.clerk_user.profile.denied_abilities)
        self.assertEqual(self.remember(client=self.c.clerk).status_code, 200)
        self.assertFalse(self.grant(False)["abilities"]["remember_barcode"])
        self.c.clerk_user.profile.refresh_from_db()      # 測試用的帳號物件會留著上一次讀到的設定(真的請求每次重讀)
        self.assertEqual(self.remember(code="4712345678918", client=self.c.clerk).status_code, 403)
        # 其他項目照舊預設開著;管理員一律可以
        self.assertTrue(abilities.can(self.c.clerk_user, "edit_products"))
        self.assertTrue(abilities.can(self.c.admin_user, "remember_barcode"))

    def test_the_barcode_is_remembered_with_who_and_then_matches_exactly(self):
        r = self.remember()
        self.assertEqual((r.status_code, r.json()["action"]), (200, "created"), r.content.decode())
        alias = ProductAlias.objects.get(kind="barcode", value=EAN)
        self.assertEqual((alias.product_id, alias.verified, alias.created_by_id), (self.case.id, True, self.c.admin_user.id))
        got = self.c.admin.get("/api/v1/products/", {"search": EAN}).json()
        rows = got["results"] if isinstance(got, dict) else got
        hit = next(p for p in rows if p["id"] == self.case.id)
        self.assertEqual((hit["barcode"], hit["barcodes"]), ("OLD-LC-01", [EAN]))
        self.assertEqual(self.remember().json()["action"], "kept")                 # 再記一次:不重複
        self.assertEqual(self.remember(code="OLD-LC-01").json()["action"], "kept")  # 本來就是它的條碼

    def test_codes_that_belong_to_something_else_are_refused(self):
        other = Product.objects.create(tenant=self.c.tenant, category=self.c.cat_case, name="甲 另一個皮套",
                                       requires_serial=False, barcode="4719999999999")
        r = self.remember(code="4719999999999")
        self.assertEqual(r.status_code, 409)
        self.assertIn("甲 另一個皮套", r.json()["detail"])
        r = self.remember(code=other.sku.lower())                                   # 別的商品的品號
        self.assertEqual(r.status_code, 409)
        self.assertIn("甲 另一個皮套", r.json()["detail"])
        self.assertEqual(self.remember(product=other, code=EAN).status_code, 200)    # 先記給別的商品
        r = self.remember(code=EAN)
        self.assertEqual(r.status_code, 409)
        self.assertIn("甲 另一個皮套", r.json()["detail"])
        r = self.remember(code="4719-9999-99999")                                   # 同一個條碼換個寫法(複審 P1)
        self.assertEqual(r.status_code, 409)
        self.assertIn("甲 另一個皮套", r.json()["detail"])
        r = self.remember(code="4712 3456 78901")                                   # 別的商品另外記的條碼換個寫法
        self.assertEqual(r.status_code, 409)
        self.c.purchase(phone_serials=["SNAB12345678"])
        r = self.remember(code="SNAB12345678")
        self.assertEqual(r.status_code, 409)
        self.assertIn("序號", r.json()["detail"])
        r = self.remember(code="356938035643809")                                   # 還沒進過的 IMEI 也不行(複審 P1)
        self.assertEqual(r.status_code, 400)
        self.assertIn("IMEI", r.json()["detail"])
        self.assertEqual(ProductAlias.objects.filter(product=self.case, kind="barcode").count(), 0)
