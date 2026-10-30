"""個人收購的收購價要算進商品的平均成本(owner 2026-10-30:「整理後,平均成本、總成本都只有維修成本,沒有含收購成本」)。

跟進貨同一個算法:(全公司在庫台數 × 現在的平均成本 + 收購價)÷(台數 + 1)。舊資料由 inventory 0024 重算一次。
"""
from decimal import Decimal
from importlib import import_module

from django.apps import apps as django_apps
from django.test import TestCase

from apps.backup.tests.factory import Company
from apps.catalog.models import Product
from apps.inventory.models import ProductSerial
from apps.parties.models import Member
from apps.sales.services import acquire_secondhand_from_member

D = Decimal
REPAIRS = "/api/v1/repair-orders/"


class BuybackCostTests(TestCase):
    def setUp(self):
        self.c = Company("a", "甲通訊行", "甲")
        self.used = Product.objects.create(
            tenant=self.c.tenant, category=self.c.cat_phone, name="甲 中古 iPhone 13",
            is_secondhand=True, list_price=12000,
        )
        self.member = Member.objects.create(tenant=self.c.tenant, name="王小明", phone="0911222333")

    def buy(self, imei, price, product=None):
        serial, _ = acquire_secondhand_from_member(
            tenant=self.c.tenant, member=self.member, warehouse=self.c.wh, secondhand_product=product or self.used,
            imei=imei, condition_grade="C", custom_unit_price=None, acquisition_price=price,
            payment_method_code="cash",
        )
        return serial

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
