"""個人收購的成本與作廢(owner 2026-10-30)。

- 收購價要算進商品的平均成本(「整理後,平均成本、總成本都只有維修成本,沒有含收購成本」):跟進貨同一個算法
  (全公司在庫台數 × 現在的平均成本 + 收購價)÷(台數 + 1);舊資料由 inventory 0024 重算一次。
- 作廢收購單,收進來的那一台一起作廢(「可以」;以前錢退回去了機器還在庫存):收進來之後動過的不能作廢。
"""
from decimal import Decimal
from importlib import import_module

from django.apps import apps as django_apps
from django.test import TestCase
from django.utils import timezone

from apps.backup.tests.factory import Company
from apps.catalog.models import Product
from apps.inventory.models import ProductSerial, StockMovement
from apps.parties.models import Member
from apps.repairs.models import RepairOrder
from apps.sales.models import SalesOrder
from apps.sales.services import acquire_secondhand_from_member
from apps.trade.tests import _Helpers as _TradeHelpers

D = Decimal
REPAIRS = "/api/v1/repair-orders/"


class _Buyback:
    def setUp(self):
        self.c = Company("a", "甲通訊行", "甲")
        self.used = Product.objects.create(
            tenant=self.c.tenant, category=self.c.cat_phone, name="甲 中古 iPhone 13",
            is_secondhand=True, list_price=12000,
        )
        self.member = Member.objects.create(tenant=self.c.tenant, name="王小明", phone="0911222333")

    def buy(self, imei, price, product=None):
        return self.buy_order(imei, price, product)[0]

    def buy_order(self, imei, price, product=None):
        return acquire_secondhand_from_member(
            tenant=self.c.tenant, member=self.member, warehouse=self.c.wh, secondhand_product=product or self.used,
            imei=imei, condition_grade="C", custom_unit_price=None, acquisition_price=price,
            payment_method_code="cash",
        )

    def sell(self, serial):
        self.c._post("/api/v1/sales-orders/", {
            "customer": self.c.customer.id, "warehouse": self.c.wh.id, "tax_method": "untaxed",
            "sales_person": self.c.sales_person.id,
            "items": [{"product": serial.product_id, "qty": 1, "unit_price": "15000", "serial_ids": [serial.id]}],
            "payments": [{"method": "cash", "amount": "15000"}],
        })

    def avg(self, product=None):
        product = product or self.used
        product.refresh_from_db()
        return product.weighted_avg_cost

    def shown(self):
        """庫存查詢頁那一列(管理員):平均成本、數量。"""
        r = self.c.admin.get("/api/v1/products/stock-matrix/", {"search": self.used.name})
        self.assertEqual(r.status_code, 200, r.content.decode())
        row = next(p for p in r.json()["products"] if p["id"] == self.used.id)
        return D(row["weighted_avg_cost"]), row["stock_total"]

    def refurb(self, serial, charged=None):
        """送去整理;charged = 外包實際收的錢、完工。沒給 = 還在整理中。"""
        r = self.c.admin.post(REPAIRS, {
            "stock_serial": serial.id, "warehouse": self.c.wh.id, "received_date": "2026-10-30",
            "mode": "external", "external_vendor": self.c.supplier.id, "unlock_method": "none",
            "defect_description": "螢幕破、電池老化", "sales_person": self.c.sales_person.id,
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content.decode())
        pk = r.json()["id"]
        if charged is None:
            return
        self.assertEqual(self.c.admin.patch(f"{REPAIRS}{pk}/", {"external_quote_actual": charged}, format="json")
                         .status_code, 200)
        r = self.c.admin.post(f"{REPAIRS}{pk}/complete/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())


class BuybackCostTests(_Buyback, TestCase):

    def test_buyback_price_goes_into_the_average(self):
        self.buy("356938035643809", "10000")
        self.assertEqual(self.avg(), D("10000.00"))
        self.buy("356938035643817", "12000")
        self.assertEqual(self.shown(), (D("11000.00"), 2))          # 庫存查詢:平均 11,000 × 2 台 = 總成本 22,000

    def test_refurb_after_buyback_keeps_the_buyback_price(self):
        # owner 那一台:收購 3,000、外包整理 1,500 → 這一台 4,500,平均成本也是 4,500(不是只有 1,500)
        unit = self.buy("356938035643809", "3000")
        self.refurb(unit, "1500")
        unit.refresh_from_db()
        self.assertEqual(unit.purchase_unit_cost, D("4500.00"))
        self.assertEqual(self.shown(), (D("4500.00"), 1))
        # 再收一台 5,000:(4,500 + 5,000)÷ 2
        self.buy("356938035643817", "5000")
        self.assertEqual(self.avg(), D("4750.00"))

    def test_same_formula_as_purchase_after_a_sale(self):
        # 賣掉不改平均;下一台照「在庫台數 × 現在的平均 + 收購價」算(進貨、盤點入庫也是這樣算,不是重算在庫那幾台)
        self.buy("356938035643809", "10000")
        self.sell(self.buy("356938035643817", "12000"))
        self.assertEqual(self.avg(), D("11000.00"))
        self.buy("356938035643825", "14000")
        self.assertEqual(self.avg(), D("12500.00"))                 # (1 × 11,000 + 14,000)÷ 2

    def test_old_products_are_recomputed_once(self):
        a = self.buy("356938035643809", "3000")
        self.buy("356938035643817", "5000")
        self.refurb(a, "1500")
        self.refurb(self.buy("356938035643833", "6000"))             # 這一台還在整理中:也算
        sold_out = Product.objects.create(tenant=self.c.tenant, category=self.c.cat_phone, name="甲 中古 iPhone 12",
                                          is_secondhand=True, list_price=9000)
        self.sell(self.buy("356938035643825", "7000", product=sold_out))
        # 修好之前的樣子:收購價沒進平均,只剩整理費
        Product.objects.filter(pk=self.used.pk).update(weighted_avg_cost=D("750.00"))
        Product.objects.filter(pk=sold_out.pk).update(weighted_avg_cost=D("123.00"))
        self.c.purchase(phone_serials=["N0001"])                    # 沒有收購過的品號(新機)不動
        Product.objects.filter(pk=self.c.phone.pk).update(weighted_avg_cost=D("19999.00"))

        import_module("apps.inventory.migrations.0024_buyback_avg_cost").recompute(django_apps, None)
        self.assertEqual(self.avg(), D("5166.67"))                  # (3,000 + 1,500 + 5,000 + 6,000)÷ 3
        self.assertEqual(self.avg(sold_out), D("123.00"))          # 一台都沒有的不動
        self.assertEqual(self.avg(self.c.phone), D("19999.00"))
        self.assertEqual(ProductSerial.objects.filter(tenant=self.c.tenant, product=self.used).count(), 3)


class BuybackVoidTests(_Buyback, TestCase):
    def void(self, so, expect=200):
        r = self.c.admin.post(f"/api/v1/sales-orders/{so.id}/void/", {}, format="json")
        self.assertEqual(r.status_code, expect, r.content.decode())
        return r.json()

    def test_voiding_the_buyback_voids_the_unit(self):
        self.buy("356938035643809", "3000")
        unit, so = self.buy_order("356938035643817", "5000")
        self.assertEqual(self.avg(), D("4000.00"))
        self.void(so)
        unit.refresh_from_db()
        self.assertEqual((unit.status, unit.warehouse_id), (ProductSerial.Status.VOID, None))
        self.assertTrue(SalesOrder.objects.get(pk=so.pk).is_void)
        self.assertEqual(self.shown(), (D("3000.00"), 1))           # 平均成本扣回、少一台
        move = StockMovement.objects.get(serial=unit, movement_type=StockMovement.MovementType.VOID)
        self.assertEqual((move.from_warehouse_id, move.to_warehouse_id, move.ref_doc_id), (self.c.wh.id, None, so.id))
        # 進銷存表:收購作廢沖回進貨那一欄(今天 收 2 台、作廢 1 台 → 進貨 1,期末 1)
        flow = self.c.admin.get("/api/v1/stock-flow-report/", {"from": timezone.localdate(), "to": timezone.localdate()}).json()
        row = next(r for r in flow["rows"] if r["product"] == self.used.id)
        self.assertEqual((row["purchase"], row["adjust"], row["closing"]), (1, 0, 1))
        moves = self.c.admin.get("/api/v1/stock-movement-report/", {
            "from": timezone.localdate(), "to": timezone.localdate(), "kind": "trade_in_void"}).json()
        self.assertEqual([r["kind_label"] for r in moves["results"]], ["收購作廢"])
        # 碼放出來了:同一台可以重新收購
        again = self.buy("356938035643817", "4500")
        self.assertEqual(again.status, ProductSerial.Status.IN_STOCK)
        self.assertEqual(self.void(so, expect=400)["detail"], "此單已作廢")

    def test_a_unit_that_moved_cannot_be_voided(self):
        sold, sold_so = self.buy_order("356938035643809", "3000")
        self.sell(sold)
        self.assertIn("現在已售", self.void(sold_so, expect=400)["detail"])

        moved, moved_so = self.buy_order("356938035643817", "3000")
        ProductSerial.objects.filter(pk=moved.pk).update(warehouse=self.c.warehouses[1])
        self.assertIn("已經調到別家門市", self.void(moved_so, expect=400)["detail"])

        # 送去整理再取消:人在原門市、在庫,但動過
        fixed, fixed_so = self.buy_order("356938035643825", "3000")
        self.refurb(fixed)
        self.assertIn("現在整理中", self.void(fixed_so, expect=400)["detail"])
        order = RepairOrder.objects.get(stock_serial=fixed)
        r = self.c.admin.post(f"{REPAIRS}{order.id}/void/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        fixed.refresh_from_db()
        self.assertEqual(fixed.status, ProductSerial.Status.IN_STOCK)
        self.assertIn("賣過、調撥、整理或換貨過", self.void(fixed_so, expect=400)["detail"])

        # 擋下來的都沒有動到:單沒作廢、機器還在庫
        for unit, so in ((moved, moved_so), (fixed, fixed_so)):
            unit.refresh_from_db()
            self.assertEqual(unit.status, ProductSerial.Status.IN_STOCK)
            self.assertFalse(SalesOrder.objects.get(pk=so.pk).is_void)


class BuybackVoidHeldTests(_TradeHelpers, TestCase):
    def test_a_unit_held_by_a_dealer_cannot_be_voided(self):
        self.open_shop()
        member = Member.objects.create(tenant=self.seller, name="王小明", phone="0911222333")
        unit, so = acquire_secondhand_from_member(
            tenant=self.seller, member=member, warehouse=self.wh1, secondhand_product=self.used,
            imei="356938035643809", condition_grade="B", custom_unit_price=16000, acquisition_price="9000",
            payment_method_code="cash", wholesale={"list": True, "price": 14000},
        )
        self.buy_unit(self.b, unit)
        r = self.a.admin.post(f"/api/v1/sales-orders/{so.id}/void/", {}, format="json")
        self.assertEqual(r.status_code, 400, r.content.decode())
        self.assertIn("已經被同行「乙通訊行」訂走", r.json()["detail"])
        unit.refresh_from_db()
        self.assertEqual(unit.status, ProductSerial.Status.IN_STOCK)
