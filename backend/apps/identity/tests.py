"""商品識別資料層測試(離線可跑)。

證明:
1. normalize() 把寫法差異抹平(全形/大小寫/空白/容量單位)。
2. ProductAlias 存檔自動算 normalized_value。
3. 防重複:同一條碼不能指向兩個商品;同廠商同料號不重複;停用後可再加。
4. 待確認區同批同行不重複。
"""
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.catalog.models import Category, Product
from apps.parties.models import Supplier
from apps.tenants.models import Tenant

from .models import IntakeBatch, IntakeItem, ProductAlias
from .normalize import normalize, normalize_capacity


class NormalizeTests(TestCase):
    def test_writing_style_flattened(self):
        self.assertEqual(normalize(" 128 gb "), "128gb")
        self.assertEqual(normalize("iPhone15 128G 黑"), "iphone15128gb黑")
        self.assertEqual(normalize("1 TB"), "1tb")
        # 全形英數 → 半形
        self.assertEqual(normalize("ＡＢ１２"), "ab12")

    def test_capacity(self):
        self.assertEqual(normalize_capacity("128 G"), "128gb")
        self.assertEqual(normalize_capacity("1tb"), "1tb")
        self.assertEqual(normalize_capacity("256GB"), "256gb")


class AliasTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="測試通訊行", code="demo")
        self.cat = Category.objects.create(tenant=self.tenant, code="PH", name="手機")
        self.sup = Supplier.objects.create(tenant=self.tenant, name="大盤商A")

    def _product(self, name):
        return Product.objects.create(tenant=self.tenant, category=self.cat, name=name)

    def _alias(self, product, kind, value, supplier=None):
        return ProductAlias.objects.create(
            tenant=self.tenant, product=product, supplier=supplier, kind=kind, value=value,
        )

    def test_normalized_value_auto_filled(self):
        p = self._product("iPhone 15 128GB 黑")
        a = self._alias(p, ProductAlias.Kind.VENDOR_NAME, "iPhone15 128G 黑", self.sup)
        self.assertEqual(a.normalized_value, "iphone15128gb黑")

    def test_barcode_unique_across_suppliers(self):
        """同一條碼(正規化後相同)不能指向兩個商品,不分廠商。"""
        a, b = self._product("A"), self._product("B")
        self._alias(a, ProductAlias.Kind.BARCODE, "471 0001")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self._alias(b, ProductAlias.Kind.BARCODE, "4710001")

    def test_vendor_sku_unique_per_supplier(self):
        a, b = self._product("A"), self._product("B")
        self._alias(a, ProductAlias.Kind.VENDOR_SKU, "IP15-128-BK", self.sup)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self._alias(b, ProductAlias.Kind.VENDOR_SKU, "ip15 128 bk", self.sup)

    def test_inactive_alias_frees_the_key(self):
        """停用(軟刪)後,同一個 key 可以重新指派給別的商品。"""
        a, b = self._product("A"), self._product("B")
        old = self._alias(a, ProductAlias.Kind.BARCODE, "4710001")
        old.is_active = False
        old.save()
        # 不應再撞唯一約束
        self._alias(b, ProductAlias.Kind.BARCODE, "4710001")
        self.assertEqual(
            ProductAlias.objects.filter(is_active=True, normalized_value="4710001").count(), 1
        )


class MatchEngineTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="測試通訊行", code="demo")
        self.cat = Category.objects.create(tenant=self.tenant, code="PH", name="手機")
        self.sup = Supplier.objects.create(tenant=self.tenant, name="大盤商A")
        self.p128 = Product.objects.create(
            tenant=self.tenant, category=self.cat, name="iPhone 15 128GB 黑", capacity="128GB",
        )
        self.p256 = Product.objects.create(
            tenant=self.tenant, category=self.cat, name="iPhone 15 256GB 黑", capacity="256GB",
        )

    def test_taught_alias_auto_matches(self):
        from .services import match_line
        ProductAlias.objects.create(
            tenant=self.tenant, product=self.p128, supplier=self.sup,
            kind=ProductAlias.Kind.VENDOR_NAME, value="APPLE IP15 128 黑",
        )
        r = match_line(self.tenant, self.sup, "apple ip15 128 黑")
        self.assertEqual(r["status"], IntakeItem.MatchStatus.AUTO_MATCHED)
        self.assertEqual(r["matched_product"], self.p128)

    def test_barcode_auto_matches(self):
        from .services import match_line
        self.p128.barcode = "4710001234567"
        self.p128.save()
        r = match_line(self.tenant, self.sup, "隨便打", raw_barcode="4710001234567")
        self.assertEqual(r["status"], IntakeItem.MatchStatus.AUTO_MATCHED)
        self.assertEqual(r["confidence"], 100)

    def test_similar_name_goes_to_review(self):
        from .services import match_line
        r = match_line(self.tenant, self.sup, "iPhone 15 128GB 黑")
        # 名稱模糊不夠格自動,進待確認、列候選
        self.assertEqual(r["status"], IntakeItem.MatchStatus.NEEDS_REVIEW)
        self.assertTrue(r["candidates"])

    def test_capacity_conflict_blocks_automatch(self):
        from .services import match_line
        # 單據講 256,但把 128 的別名餵進來會不會誤對?這裡測純名稱情境:
        r = match_line(self.tenant, self.sup, "iPhone 15 256GB 黑")
        # 應對到 256 那筆(非衝突),128 那筆因容量不同被標 conflict
        top = r["candidates"][0]
        self.assertEqual(top["product_id"], self.p256.id)
        conflicts = [c for c in r["candidates"] if c["conflict"]]
        self.assertTrue(any(c["product_id"] == self.p128.id for c in conflicts))

    def test_run_intake_from_text(self):
        from .services import run_intake_from_text
        ProductAlias.objects.create(
            tenant=self.tenant, product=self.p128, supplier=self.sup,
            kind=ProductAlias.Kind.VENDOR_NAME, value="IP15 128 黑",
        )
        text = "IP15 128 黑 x2 @35000\n某個沒見過的東西 x1 @100"
        batch = run_intake_from_text(self.tenant, text, supplier=self.sup)
        items = list(batch.items.order_by("line_no"))
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].match_status, IntakeItem.MatchStatus.AUTO_MATCHED)
        self.assertEqual(items[0].raw_qty, 2)
        self.assertEqual(items[1].match_status, IntakeItem.MatchStatus.UNKNOWN)


class IntakeFlowTests(TestCase):
    """整條:貼文字 → 識別 → (教/選) → 過帳成進貨單。"""

    def setUp(self):
        from apps.inventory.models import Warehouse
        self.tenant = Tenant.objects.create(name="測試通訊行", code="demo")
        self.wh = Warehouse.objects.create(tenant=self.tenant, code="MAIN", name="門市")
        self.cat = Category.objects.create(tenant=self.tenant, code="PH", name="手機")
        self.sup = Supplier.objects.create(tenant=self.tenant, name="大盤商A")
        self.product = Product.objects.create(
            tenant=self.tenant, category=self.cat, name="iPhone 15 Pro 256GB 黑",
        )

    def test_taught_alias_then_intake_commits(self):
        from apps.purchasing.models import PurchaseOrder
        from apps.inventory.models import ProductSerial
        from .services import commit_batch, run_intake_from_text
        # 先教一條廠商別名
        ProductAlias.objects.create(
            tenant=self.tenant, product=self.product, supplier=self.sup,
            kind=ProductAlias.Kind.VENDOR_NAME, value="IP15PRO 256 黑",
        )
        batch = run_intake_from_text(
            self.tenant, "IP15PRO 256 黑 x2 @35000 序號=A1,A2",
            supplier=self.sup, warehouse=self.wh,
        )
        item = batch.items.get(line_no=1)
        self.assertEqual(item.match_status, IntakeItem.MatchStatus.AUTO_MATCHED)
        self.assertEqual(item.matched_product, self.product)
        batch.refresh_from_db()
        self.assertEqual(batch.status, IntakeBatch.Status.RESOLVED)
        # 過帳:走既有帳本,建 2 筆序號
        po = commit_batch(batch)
        self.assertTrue(po.no.startswith("PO-"))
        batch.refresh_from_db()
        self.assertEqual(batch.status, IntakeBatch.Status.COMMITTED)
        self.assertEqual(batch.committed_purchase_order_id, po.id)
        self.assertEqual(ProductSerial.objects.filter(product=self.product).count(), 2)

    def test_manual_match_learns_alias_then_auto_next_time(self):
        """北極星機制:第一次認不出 → 人選一個 → 系統學別名 → 下次同講法自動。"""
        from .services import match_line, resolve_item_match, run_intake_from_text
        text = "蘋果15P 256 黑色"
        batch = run_intake_from_text(self.tenant, f"{text} x1 @35000", supplier=self.sup)
        item = batch.items.get(line_no=1)
        # 第一次:別名庫沒有 → 不會自動對應
        self.assertNotEqual(item.match_status, IntakeItem.MatchStatus.AUTO_MATCHED)
        # 人選這個商品(learn_alias 預設 True)
        resolve_item_match(item, self.product)
        self.assertEqual(
            ProductAlias.objects.filter(product=self.product, supplier=self.sup).count(), 1
        )
        # 下次同一家、同一講法 → 自動對應
        r = match_line(self.tenant, self.sup, text)
        self.assertEqual(r["status"], IntakeItem.MatchStatus.AUTO_MATCHED)
        self.assertEqual(r["matched_product"], self.product)


class IntakeTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="測試通訊行", code="demo")

    def test_line_no_unique_in_batch(self):
        batch = IntakeBatch.objects.create(tenant=self.tenant)
        IntakeItem.objects.create(tenant=self.tenant, batch=batch, line_no=1, raw_text="x")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                IntakeItem.objects.create(tenant=self.tenant, batch=batch, line_no=1, raw_text="y")
