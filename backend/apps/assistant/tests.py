"""進貨單 end-to-end spike。

證明整條管線接上既有帳本:
  進貨單文字 → interpret(解析+對應主檔) → 提案 → confirm → commit_purchase_order
             → 真的建立 ProductSerial / StockMovement / 更新加權平均。

用 DeterministicParser,不需 LLM、不需網路,可離線重複跑。
"""
from decimal import Decimal

from django.test import TestCase

from apps.catalog.models import Category, Product
from apps.inventory.models import ProductSerial, StockMovement
from apps.parties.models import Supplier
from apps.inventory.models import Warehouse
from apps.purchasing.models import PurchaseOrder
from apps.tenants.models import Tenant

from . import services
from .models import CommandLog
from .parsers import DeterministicParser


class AssistantPurchaseSpikeTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="測試通訊行", code="demo")
        self.warehouse = Warehouse.objects.create(tenant=self.tenant, code="MAIN", name="門市")
        self.supplier = Supplier.objects.create(tenant=self.tenant, name="大盤商A")
        self.category = Category.objects.create(tenant=self.tenant, code="PH", name="手機")
        self.parser = DeterministicParser()

    def _product(self, name, **kwargs):
        return Product.objects.create(
            tenant=self.tenant, category=self.category, name=name, **kwargs
        )

    # ── 快樂路徑:一句話進貨單 → 過帳 ────────────────────────────
    def test_purchase_doc_end_to_end(self):
        product = self._product("iPhone 15 Pro 256GB 黑", list_price=Decimal("38900"))
        raw = (
            "#進貨 供應商=大盤商A 倉庫=門市\n"
            "iPhone 15 Pro 256GB 黑 x2 @35000 序號=356111111111111,356222222222222"
        )

        cmd = services.interpret(
            self.tenant, raw, source=CommandLog.Source.PURCHASE_DOC, parser=self.parser
        )
        # 尚未過帳:提案就緒、帳本不動
        self.assertEqual(cmd.status, CommandLog.Status.AWAITING_CONFIRM, cmd.message)
        self.assertEqual(PurchaseOrder.objects.count(), 0)
        payload = cmd.proposal["payload"]
        self.assertEqual(payload["supplier"], self.supplier.id)
        self.assertEqual(payload["warehouse"], self.warehouse.id)
        self.assertEqual(payload["items"][0]["product"], product.id)
        self.assertEqual(payload["items"][0]["qty"], 2)

        # 確認 → 真正過帳
        cmd = services.confirm(cmd)
        self.assertEqual(cmd.status, CommandLog.Status.COMMITTED, cmd.message)
        self.assertEqual(cmd.result_doc_type, "purchase_order")

        po = PurchaseOrder.objects.get(pk=cmd.result_doc_id)
        self.assertFalse(po.is_void)
        self.assertTrue(po.no.startswith("PO-"))

        serials = ProductSerial.objects.filter(product=product)
        self.assertEqual(serials.count(), 2)
        self.assertTrue(all(s.status == ProductSerial.Status.IN_STOCK for s in serials))
        self.assertEqual(
            set(serials.values_list("serial_no", flat=True)),
            {"356111111111111", "356222222222222"},
        )
        self.assertEqual(
            StockMovement.objects.filter(
                ref_doc_type="purchase_order",
                ref_doc_id=po.id,
                movement_type=StockMovement.MovementType.PURCHASE_IN,
            ).count(),
            2,
        )
        # 加權平均:35000 含稅 → 未稅 33333.33
        product.refresh_from_db()
        self.assertEqual(product.weighted_avg_cost, Decimal("33333.33"))

    # ── 消歧義:同名多筆 → 追問,不過帳 ─────────────────────────
    def test_ambiguous_product_needs_clarification(self):
        self._product("iPhone 15 128GB 黑")
        self._product("iPhone 15 128GB 白")
        raw = "#進貨 供應商=大盤商A 倉庫=門市\niPhone 15 128GB x1 @28000"

        cmd = services.interpret(
            self.tenant, raw, source=CommandLog.Source.PURCHASE_DOC, parser=self.parser
        )
        self.assertEqual(cmd.status, CommandLog.Status.NEEDS_CLARIFICATION)
        self.assertTrue(any(c["field"].endswith("product") for c in cmd.clarification))
        self.assertGreaterEqual(len(cmd.clarification[0]["candidates"]), 2)
        self.assertEqual(PurchaseOrder.objects.count(), 0)

    # ── 防呆網:序號數不符 → 既有 service 擋下,原子回滾 ───────────
    def test_serial_count_mismatch_is_blocked_by_ledger(self):
        self._product("Samsung S25 256GB 黑")
        raw = "#進貨 供應商=大盤商A 倉庫=門市\nSamsung S25 256GB 黑 x2 @30000 序號=SN-ONLY-ONE"

        cmd = services.interpret(
            self.tenant, raw, source=CommandLog.Source.PURCHASE_DOC, parser=self.parser
        )
        self.assertEqual(cmd.status, CommandLog.Status.AWAITING_CONFIRM)

        cmd = services.confirm(cmd)
        self.assertEqual(cmd.status, CommandLog.Status.FAILED)
        self.assertIn("序號", cmd.message)
        # 帳本必須完全沒被寫入(atomic 回滾)
        self.assertEqual(PurchaseOrder.objects.count(), 0)
        self.assertEqual(ProductSerial.objects.count(), 0)
        self.assertEqual(StockMovement.objects.count(), 0)

    # ── parser 單元:進貨單文字 → Intent ──────────────────────────
    def test_deterministic_parser_shape(self):
        raw = (
            "#進貨 供應商=大盤商A 倉庫=門市 課稅=應稅外加\n"
            "iPhone 15 Pro 256GB 黑 x2 @35000 序號=A1,A2\n"
            "保護貼 x10 @50"
        )
        intent = self.parser.parse(raw)
        self.assertEqual(intent["action"], "create_purchase_order")
        self.assertEqual(intent["supplier_query"], "大盤商A")
        self.assertEqual(intent["tax_method"], "taxable_excluded")
        self.assertEqual(len(intent["items"]), 2)
        self.assertEqual(intent["items"][0]["qty"], 2)
        self.assertEqual(intent["items"][0]["serial_numbers"], ["A1", "A2"])
        self.assertEqual(intent["items"][1]["qty"], 10)
