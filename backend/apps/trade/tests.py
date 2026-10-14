"""批發(賣家那一半)。跑法:manage.py test apps.trade

甲通訊行當賣家,乙、丙當買家。買家那一側一律走 `api.handle`(平台內與對外是同一支):看得到什麼、下單、取消、查單、對帳。
要守住的:
1. 中古機一台一筆:進貨就上架、價錢照規則;賣掉、不在庫就從清單消失;出貨之前不露序號、任何時候不露成本。
2. 一台同時只會被一張單訂著;被訂走的那一台門市要賣,一定要明講(同行那一行當下取消),不會兩邊都賣出。
3. 出貨 = 一張銷貨單(庫存與成本只有那一份帳);同一把鑰匙不會出兩次;取消出貨兩邊的數字一起回去。
4. 沒有核准的同行看不到按數量賣的商品與價錢;不往來的什麼都看不到;別人的單碰不到。
5. 收款由舊到新銷單;出貨取消、作廢收款之後欠多少自己會對。
"""
from decimal import Decimal as D
from unittest import mock

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.backup.tests.factory import Company
from apps.catalog.models import Product
from apps.inventory.models import ProductSerial, StockBalance
from apps.sales.models import SalesOrder, SalesReturn
from apps.tenants.models import UserProfile

from . import api, listing, orders, partners, payments
from .models import TradeOrder, TradeOrderLine, TradePartner, TradePayment, TradeSetting, TradeShipment, TradeUnit

T = "/api/v1/trade/"
S = TradeOrder.Status


class _Helpers:
    """建三家公司與常用的動作(一般測試與「兩條連線」的測試共用)。"""

    def setUp(self):
        self.a = Company("a", "甲通訊行", "甲")
        self.b = Company("b", "乙通訊行", "乙")
        self.c = Company("c", "丙通訊行", "丙")
        self.seller = self.a.tenant
        self.wh1, self.wh2 = self.a.warehouses
        self.used = Product.objects.create(
            tenant=self.seller, category=self.a.cat_phone, name="甲 中古 iPhone 13 128GB", is_secondhand=True, list_price=15000)
        self.keys = 0

    # ── 賣家這邊 ──
    def open_shop(self, **extra):
        body = {"is_open": True, "unit_rule": "price_minus", "unit_value": 1000, **extra}
        r = self.a.admin.post(T + "settings/", body, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        return r.json()

    def stock_units(self, *sns, warehouse=None, **entry):
        """進幾台中古機(每一台成本 12000、門市賣 16000、A 級)。回那幾台。"""
        rows = [{"sn": sn, "grade": "A", "cost": "12000", "price": "16000", "battery": 90, "note": "小刮", **entry} for sn in sns]
        self.a._post("/api/v1/purchase-orders/", {
            "supplier": self.a.supplier.id, "warehouse": (warehouse or self.wh1).id, "tax_method": "untaxed",
            "items": [{"product": self.used.id, "qty": len(rows), "unit_price": "12000", "serial_numbers": rows}]})
        return [ProductSerial.objects.get(tenant=self.seller, serial_no=sn) for sn in sns]

    def offer(self, product, **extra):
        r = self.a.admin.post(T + "products/", {"rows": [{"product": product.id, "is_listed": True, **extra}]}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())

    def approve(self, buyer, percent=90):
        """發代碼給這個買家、對方輸入 → 核准的往來對象。"""
        r = self.a.admin.post(T + "invites/", {"percent": percent}, format="json")
        self.assertEqual(r.status_code, 201, r.content.decode())
        return partners.join(buyer.tenant, r.json()["code"])

    def seller_order(self, order_no, client=None):
        order = TradeOrder.objects.get(tenant=self.seller, no=order_no)
        r = (client or self.a.admin).get(f"{T}orders/{order.id}/")
        self.assertEqual(r.status_code, 200, r.content.decode())
        return r.json()

    def ship(self, order_no, lines=None, client=None, expect=200, key=None, warehouse=None, **extra):
        """把這張單還沒出的全部出掉(中古機刷訂的那一台)。`lines` 可以自己給。"""
        data = self.seller_order(order_no)
        if lines is None:
            lines = [{"line": line["id"], "qty": line["open_qty"],
                      "serials": [line["unit"]["serial"]] if line["unit"] else []} for line in data["lines"] if line["open_qty"]]
        self.keys += 1
        body = {"request_key": key or f"ship-{self.keys:04d}", "warehouse": (warehouse or self.wh1).id, "lines": lines, **extra}
        r = (client or self.a.admin).post(f"{T}orders/{data['id']}/ship/", body, format="json")
        self.assertEqual(r.status_code, expect, r.content.decode())
        return r.json()

    # ── 買家那一側(規格的那一支) ──
    def call(self, buyer, method, path, body=None):
        partner = partners.ensure(self.seller, buyer.tenant) if method == "POST" and path == "/orders" \
            else partners.view_as(self.seller, buyer.tenant)
        return api.handle(self.seller, partner, method, path, body, store=f"{buyer.tag}一店")

    def products(self, buyer):
        status, data = self.call(buyer, "GET", "/products")
        self.assertEqual(status, 200, data)
        return {p["sku"]: p for p in data["products"]}

    def unit_spec(self, buyer, serial):
        """這一台在買家看到的清單上的編號(規格的 id)。"""
        return TradeUnit.objects.get(serial=serial).id

    def buy(self, buyer, items, key=None, expect=200, **extra):
        self.keys += 1
        body = {"idempotency_key": key or f"{buyer.tenant.code}-key-{self.keys:04d}", "items": items, **extra}
        status, data = self.call(buyer, "POST", "/orders", body)
        self.assertEqual(status, expect, data)
        return data

    def buy_unit(self, buyer, serial, **extra):
        return self.buy(buyer, [{"sku": self.used.sku, "spec_id": self.unit_spec(buyer, serial), "qty": 1}], **extra)

    def detail(self, buyer, order_no, expect=200):
        status, data = self.call(buyer, "GET", f"/orders/{order_no}")
        self.assertEqual(status, expect, data)
        return data.get("order", data)


class _Trade(_Helpers, TestCase):
    pass


class ListingTests(_Trade):
    def test_used_phones_go_on_the_list_as_they_are_bought_in(self):
        self.open_shop()
        one, = self.stock_units("U001")
        unit = TradeUnit.objects.get(serial=one)
        # 門市賣 16000、規則是減 1000
        self.assertEqual((unit.is_listed, unit.price), (True, D("15000")))
        row = self.products(self.b)[self.used.sku]
        self.assertEqual((row["per_unit"], row["condition"], row["unit_price"]), (True, "中古", None))
        self.assertEqual(row["specs"], [{"id": unit.id, "code": "A 級", "name": "電池 90% 小刮", "unit_price": 15000}])

    def test_the_three_price_rules(self):
        for rule, value, want in (("price_minus", 1500, 14500), ("price_percent", 90, 14400), ("cost_plus", 800, 12800)):
            with self.subTest(rule=rule):
                self.open_shop(unit_rule=rule, unit_value=value)
                one, = self.stock_units(f"R-{rule}")
                self.assertEqual(TradeUnit.objects.get(serial=one).price, D(want))

    def test_a_unit_without_its_own_price_uses_the_product_price(self):
        self.open_shop()
        one, = self.stock_units("U002", price="")
        self.assertEqual(TradeUnit.objects.get(serial=one).price, D("14000"))      # 商品的門市價 15000 − 1000

    def test_a_price_that_does_not_come_out_positive_is_not_listed_and_does_not_block_the_purchase(self):
        self.open_shop(unit_value=20000)
        one, = self.stock_units("U003")
        self.assertEqual(one.status, "in_stock")
        self.assertFalse(TradeUnit.objects.filter(serial=one).exists())

    def test_nothing_is_listed_when_the_shop_is_not_open_or_auto_listing_is_off(self):
        self.stock_units("U004")
        self.open_shop(auto_list_units=False)
        self.stock_units("U005")
        self.assertEqual(TradeUnit.objects.count(), 0)

    def test_the_form_can_say_per_unit_not_to_list_or_give_its_own_price(self):
        self.open_shop()
        no, mine = self.stock_units("U006")[0], None
        TradeUnit.objects.all().delete()
        no, = self.stock_units("U007", wholesale_list=False)
        mine, = self.stock_units("U008", wholesale_price=13333)
        self.assertFalse(TradeUnit.objects.filter(serial=no).exists())
        self.assertEqual(TradeUnit.objects.get(serial=mine).price, D("13333"))

    def test_new_phones_are_not_listed_unit_by_unit(self):
        self.open_shop()
        self.a.purchase(phone_serials=["N001"])
        self.assertEqual(TradeUnit.objects.count(), 0)

    def test_buying_from_a_walk_in_customer_lists_it_too(self):
        from apps.parties.models import Member

        self.open_shop()
        member = Member.objects.create(tenant=self.seller, name="王小明", phone="0911222333")
        body = {"member": member.id, "warehouse": self.wh1.id, "product": self.used.id, "sn": "W001", "condition_grade": "B",
                "custom_unit_price": "12000", "acquisition_price": "9000", "payment_method_code": "cash"}
        r = self.a.admin.post("/api/v1/sales-orders/secondhand-acquisition/", body, format="json")
        self.assertEqual(r.status_code, 201, r.content.decode())
        self.assertEqual(TradeUnit.objects.get(serial__serial_no="W001").price, D("11000"))
        r = self.a.admin.post("/api/v1/sales-orders/secondhand-acquisition/",
                              {**body, "sn": "W002", "wholesale_list": False}, format="json")
        self.assertEqual(r.status_code, 201, r.content.decode())
        self.assertFalse(TradeUnit.objects.filter(serial__serial_no="W002").exists())

    def test_listing_by_hand_and_taking_off(self):
        one, two = self.stock_units("U010", "U011")
        self.open_shop()
        r = self.a.admin.get(T + "units/")
        self.assertEqual((r.json()["total"], {u["serial_no"] for u in r.json()["results"]}), (2, {"U010", "U011"}))
        self.assertEqual(r.json()["results"][0]["auto_price"], 15000)
        r = self.a.admin.post(T + "units/list/", {"rows": [{"serial": one.id}, {"serial": two.id, "price": 14200}]}, format="json")
        self.assertEqual(r.json(), {"listed": 2})
        self.assertEqual({u.serial_id: u.price for u in TradeUnit.objects.all()}, {one.id: D("15000"), two.id: D("14200")})
        self.assertEqual(self.a.admin.get(T + "units/").json()["total"], 0)                 # 預設只列還沒上架的
        self.assertEqual(self.a.admin.get(T + "units/?state=listed").json()["total"], 2)
        r = self.a.admin.post(T + "units/unlist/", {"serials": [one.id]}, format="json")
        self.assertEqual(r.json(), {"unlisted": 1})
        self.assertEqual(len(self.products(self.b)[self.used.sku]["specs"]), 1)

    def test_only_used_phones_in_stock_can_be_listed(self):
        self.open_shop()
        self.a.purchase(phone_serials=["N002"])
        new = ProductSerial.objects.get(serial_no="N002")
        r = self.a.admin.post(T + "units/list/", {"rows": [{"serial": new.id, "price": 100}]}, format="json")
        self.assertEqual(r.status_code, 400)
        gone, = self.stock_units("U012")
        TradeUnit.objects.all().delete()
        ProductSerial.objects.filter(pk=gone.id).update(status="rma")
        r = self.a.admin.post(T + "units/list/", {"rows": [{"serial": gone.id}]}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("維修中", r.json()["detail"])
        # 別家公司的中古機(就算它本身是可以上架的那一種)
        theirs = Product.objects.create(tenant=self.b.tenant, category=self.b.cat_phone, name="乙 中古機", is_secondhand=True, list_price=9000)
        other = ProductSerial.objects.create(tenant=self.b.tenant, product=theirs, serial_no="X1", warehouse=self.b.wh)
        r = self.a.admin.post(T + "units/list/", {"rows": [{"serial": other.id, "price": 100}]}, format="json")
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "有一台找不到"))
        self.assertEqual(TradeUnit.objects.count(), 0)

    def test_listing_by_hand_needs_a_price_when_the_rule_cannot_give_one(self):
        one, = self.stock_units("U016")
        self.open_shop(unit_value=20000)                    # 門市價 16000 − 20000:算不出正的
        self.assertIsNone(self.a.admin.get(T + "units/").json()["results"][0]["auto_price"])
        r = self.a.admin.post(T + "units/list/", {"rows": [{"serial": one.id}]}, format="json")
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "U016 算不出批發價,請填"))
        for bad in (0, -1, 1.5, "abc", True, 10_000_000):
            self.assertEqual(self.a.admin.post(T + "units/list/", {"rows": [{"serial": one.id, "price": bad}]}, format="json").status_code, 400, bad)
        self.assertEqual(TradeUnit.objects.count(), 0)
        self.assertEqual(self.a.admin.post(T + "units/list/", {"rows": [{"serial": one.id, "price": 9000}]}, format="json").json(), {"listed": 1})

    def test_after_intake_only_lists_units_that_are_sold_one_by_one(self):
        self.open_shop()
        self.a.purchase(phone_serials=["N003"])
        new = ProductSerial.objects.get(serial_no="N003")
        self.assertEqual(listing.after_intake(self.seller, [new], wanted={new.id: {"list": True, "price": D("100")}}), 0)
        self.assertEqual(TradeUnit.objects.count(), 0)

    def test_a_unit_sold_over_the_counter_leaves_the_list_and_does_not_come_back_by_itself(self):
        self.open_shop()
        one, two = self.stock_units("U013", "U014")
        sale = self.a._post("/api/v1/sales-orders/", {
            "customer": self.a.customer.id, "warehouse": self.wh1.id, "tax_method": "untaxed",
            "items": [{"product": self.used.id, "qty": 1, "unit_price": "16000", "serial_ids": [one.id]}],
            "payments": [{"method": "cash", "amount": "16000"}]})
        self.assertEqual([s["id"] for s in self.products(self.b)[self.used.sku]["specs"]], [TradeUnit.objects.get(serial=two).id])
        self.assertFalse(TradeUnit.objects.get(serial=one).is_listed)
        self.a._post(f"/api/v1/sales-orders/{sale['id']}/void/", {})
        one.refresh_from_db()
        self.assertEqual(one.status, "in_stock")
        self.assertEqual(len(self.products(self.b)[self.used.sku]["specs"]), 1)

    def test_a_unit_that_is_not_in_stock_right_now_is_not_for_sale(self):
        self.open_shop()
        one, = self.stock_units("U015")
        for status in ("in_transit", "rma", "lost", "returned"):
            ProductSerial.objects.filter(pk=one.id).update(status=status)
            self.assertNotIn(self.used.sku, self.products(self.b), status)
        ProductSerial.objects.filter(pk=one.id).update(status="in_stock")
        self.assertIn(self.used.sku, self.products(self.b))             # 調到了、修好了:還是這家公司的貨


class ManyUnitsTests(_Trade):
    """同一個型號在庫幾百台:先照型號看、一個型號一次列完、篩出來的整群定同一個價(owner 2026-10-14)。"""

    def many(self, n, start=0, **entry):
        return self.stock_units(*[f"M{i:04d}" for i in range(start, start + n)], **entry)

    def put(self, rows, client=None, expect=200, **seen):
        r = (client or self.a.admin).post(T + "units/list/", {"rows": rows, **seen}, format="json")
        self.assertEqual(r.status_code, expect, r.content.decode())
        return r.json()

    def test_the_model_list_counts_each_model_by_state(self):
        one, two, three = self.many(3)
        far, = self.stock_units("M9000", warehouse=self.wh2)
        other = Product.objects.create(tenant=self.seller, category=self.a.cat_phone, name="甲 中古 iPhone 12 64GB", is_secondhand=True, list_price=9000)
        self.a._post("/api/v1/purchase-orders/", {
            "supplier": self.a.supplier.id, "warehouse": self.wh1.id, "tax_method": "untaxed",
            "items": [{"product": other.id, "qty": 1, "unit_price": "6000", "serial_numbers": [{"sn": "K0001", "grade": "B", "cost": "6000", "price": "9000"}]}]})
        self.a.purchase(phone_serials=["N100"])                                   # 全新機不在這份清單
        self.open_shop()
        self.put([{"serial": one.id}, {"serial": two.id}])
        self.buy_unit(self.b, two)                                                # 被訂走的不算上架中
        rows = {r["name"]: r for r in self.a.admin.get(T + "units/models/").json()["results"]}
        self.assertEqual(set(rows), {self.used.name, other.name})
        self.assertEqual(rows[self.used.name], {"product": self.used.id, "name": self.used.name, "sku": self.used.sku,
                                                "total": 4, "unlisted": 2, "listed": 1, "held": 1})
        self.assertEqual((rows[other.name]["total"], rows[other.name]["unlisted"]), (1, 1))
        there = self.a.admin.get(f"{T}units/models/?warehouse={self.wh2.id}").json()["results"]
        self.assertEqual([(r["name"], r["total"]) for r in there], [(self.used.name, 1)])
        # 鎖門市的店員只算自己那一間(另一間的那一台不在裡面)
        mine = {r["name"]: r["total"] for r in self.a.clerk.get(f"{T}units/models/?warehouse={self.wh2.id}").json()["results"]}
        self.assertEqual(mine, {self.used.name: 3, other.name: 1})
        self.assertEqual(self.b.admin.get(T + "units/models/").json()["results"], [])

    def test_one_model_comes_back_whole(self):
        self.many(3)
        other = Product.objects.create(tenant=self.seller, category=self.a.cat_phone, name="甲 中古 iPhone 12 64GB", is_secondhand=True, list_price=9000)
        ProductSerial.objects.create(tenant=self.seller, product=other, serial_no="K0002", warehouse=self.wh1)
        self.open_shop()
        got = self.a.admin.get(f"{T}units/?state=all&product={self.used.id}&limit=1500").json()
        self.assertEqual((got["total"], {u["product"] for u in got["results"]}, len(got["results"])), (3, {self.used.id}, 3))
        self.assertEqual(self.a.admin.get(f"{T}units/?state=all&limit=1500").json()["total"], 4)
        with mock.patch("apps.trade.views.UNIT_PAGE_MAX", 2):                     # 上限是清單自己的,不是別的清單那個 500
            got = self.a.admin.get(f"{T}units/?state=all&product={self.used.id}&limit=1500").json()
        self.assertEqual((got["total"], len(got["results"])), (3, 2))

    def test_a_whole_group_gets_one_price_without_a_query_per_unit(self):
        units = self.many(40)
        self.open_shop()
        self.put([{"serial": u.id, "price": 15500} for u in units[:10]])          # 其中十台本來就上架了(另一個價)
        with CaptureQueriesContext(connection) as seen:
            got = self.put([{"serial": u.id, "price": 12000} for u in units])
        self.assertEqual(got, {"listed": 40})
        self.assertLess(len(seen), 30, len(seen))                                 # 一台一句的話至少 80 句
        self.assertEqual(set(TradeUnit.objects.values_list("price", "is_listed", "listed_by_id")), {(D("12000"), True, self.a.admin_user.id)})
        self.assertEqual(TradeUnit.objects.count(), 40)
        self.assertEqual({s["unit_price"] for s in self.products(self.b)[self.used.sku]["specs"]}, {12000})
        # 下架也是整群
        r = self.a.admin.post(T + "units/unlist/", {"serials": [u.id for u in units]}, format="json")
        self.assertEqual(r.json(), {"unlisted": 40})
        self.assertNotIn(self.used.sku, self.products(self.b))

    def test_one_unit_that_cannot_be_listed_stops_the_whole_batch(self):
        one, two, three = self.many(3)
        self.open_shop()
        self.put([{"serial": one.id, "price": 15000}])
        ProductSerial.objects.filter(pk=three.id).update(status="sold", warehouse=None)      # 剛被門市賣掉
        got = self.put([{"serial": one.id, "price": 11000}, {"serial": two.id, "price": 11000}, {"serial": three.id, "price": 11000}], expect=400)
        self.assertIn("M0002", got["detail"])
        self.assertEqual(list(TradeUnit.objects.values_list("serial_id", "price")), [(one.id, D("15000"))])   # 前兩台也沒有動
        got = self.put([{"serial": one.id, "price": 11000}, {"serial": two.id, "price": -5}], expect=400)
        self.assertEqual(list(TradeUnit.objects.values_list("serial_id", "price")), [(one.id, D("15000"))])

    def test_two_thousand_go_through_and_one_more_does_not(self):
        self.open_shop()
        ProductSerial.objects.bulk_create([
            ProductSerial(tenant=self.seller, product=self.used, serial_no=f"T{i:05d}", warehouse=self.wh1, condition_grade="A")
            for i in range(2001)])
        ids = list(ProductSerial.objects.filter(tenant=self.seller, serial_no__startswith="T").order_by("id").values_list("id", flat=True))
        got = self.put([{"serial": i, "price": 9000} for i in ids], expect=400)
        self.assertEqual((got["detail"], TradeUnit.objects.count()), ("一次最多上架 2000 台", 0))
        with CaptureQueriesContext(connection) as seen:
            got = self.put([{"serial": i, "price": 9000} for i in ids[:2000]])
        self.assertEqual((got, TradeUnit.objects.filter(is_listed=True, price=9000).count()), ({"listed": 2000}, 2000))
        self.assertLess(len(seen), 40, len(seen))
        got = self.a.admin.get(f"{T}units/?state=listed&product={self.used.id}&limit=2000").json()
        self.assertEqual((got["total"], len(got["results"])), (2000, 2000))                 # 一個型號的 2,000 台一次列得完

    def test_what_is_sent_must_be_what_the_screen_was_looking_at(self):
        """畫面換門市 / 換型號的那一下手上可能還是上一份清單:送出時帶著它看的是什麼,對不上就整批不動(複審 P0)。"""
        here, also = self.many(2)
        there, = self.stock_units("M9002", warehouse=self.wh2)
        other = Product.objects.create(tenant=self.seller, category=self.a.cat_phone, name="甲 中古 iPhone 12 64GB", is_secondhand=True, list_price=9000)
        odd = ProductSerial.objects.create(tenant=self.seller, product=other, serial_no="K0003", warehouse=self.wh1)
        self.open_shop()
        rows = [{"serial": here.id, "price": 9000}, {"serial": there.id, "price": 9000}]
        # 畫面現在選的是另一間門市,送來的卻有這一間的(上一份清單)
        got = self.put(rows, expect=400, product=self.used.id, warehouse=self.wh2.id)
        self.assertEqual(got["detail"], "M0000 不在畫面選的那一間門市,請重新整理")
        got = self.put([{"serial": here.id, "price": 9000}, {"serial": odd.id, "price": 9000}], expect=400, product=self.used.id)
        self.assertEqual(got["detail"], "K0003 不是畫面上那個型號的,請重新整理")
        self.assertEqual(TradeUnit.objects.count(), 0)
        self.assertEqual(self.put(rows, product=self.used.id), {"listed": 2})                # 門市選「全部」:兩間的都可以
        self.assertEqual(self.put([{"serial": here.id, "price": 8000}, {"serial": also.id, "price": 8000}],
                                  product=self.used.id, warehouse=self.wh1.id), {"listed": 2})
        # 下架也一樣
        r = self.a.admin.post(T + "units/unlist/", {"serials": [here.id, there.id], "product": self.used.id, "warehouse": self.wh1.id}, format="json")
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "M9002 不在畫面選的那一間門市,請重新整理"))
        r = self.a.admin.post(T + "units/unlist/", {"serials": [here.id], "product": other.id}, format="json")
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "M0000 不是畫面上那個型號的,請重新整理"))
        self.assertEqual(TradeUnit.objects.filter(is_listed=True).count(), 3)
        r = self.a.admin.post(T + "units/unlist/", {"serials": [here.id], "product": self.used.id, "warehouse": self.wh1.id}, format="json")
        self.assertEqual(r.json(), {"unlisted": 1})

    def test_there_is_a_ceiling_on_how_many_at_once(self):
        one, two, three = self.many(3)
        self.open_shop()
        with mock.patch.object(listing, "MAX_ROWS", 2):
            got = self.put([{"serial": u.id} for u in (one, two, three)], expect=400)
            self.assertEqual(got["detail"], "一次最多上架 2 台")
            r = self.a.admin.post(T + "units/unlist/", {"serials": [one.id, two.id, three.id]}, format="json")
            self.assertEqual((r.status_code, r.json()["detail"]), (400, "一次最多下架 2 台"))
        self.assertEqual(TradeUnit.objects.count(), 0)

    def test_a_clerk_tied_to_one_store_only_touches_that_store(self):
        here, = self.many(1)
        there, = self.stock_units("M9001", warehouse=self.wh2)
        self.open_shop()
        got = self.put([{"serial": here.id, "price": 9000}, {"serial": there.id, "price": 9000}], client=self.a.clerk, expect=400)
        self.assertEqual(got["detail"], "M9001 不在你的門市")
        self.assertEqual(TradeUnit.objects.count(), 0)
        self.assertEqual(self.put([{"serial": here.id, "price": 9000}], client=self.a.clerk), {"listed": 1})
        self.put([{"serial": there.id, "price": 9000}])                           # 管理員不鎖門市
        r = self.a.clerk.post(T + "units/unlist/", {"serials": [here.id, there.id]}, format="json")
        self.assertEqual(r.json(), {"unlisted": 1})
        self.assertEqual(set(TradeUnit.objects.filter(is_listed=True).values_list("serial_id", flat=True)), {there.id})


class WhoSeesWhatTests(_Trade):
    def setUp(self):
        super().setUp()
        self.open_shop()
        self.one, = self.stock_units("U100")
        self.a.purchase(case_qty=10, phone_serials=["N100", "N101"])
        self.offer(self.a.case)
        self.offer(self.a.phone, price=23000)

    def test_a_dealer_with_no_dealings_sees_only_the_used_phones(self):
        self.assertEqual(set(self.products(self.b)), {self.used.sku})
        self.assertIn(self.seller, partners.sellers_for(self.b.tenant))
        # 光是看,不會在賣家那邊多一筆往來對象
        self.assertEqual(TradePartner.objects.count(), 0)
        # 也訂不到按數量賣的(他沒有價錢)
        got = self.buy(self.b, [{"sku": self.a.case.sku, "spec_id": None, "qty": 1}], expect=400)
        self.assertEqual(got["code"], "not_available")
        self.assertEqual(TradeOrder.objects.count(), 0)

    def test_used_phones_only_for_approved_dealers_when_platform_selling_is_off(self):
        self.open_shop(units_to_all=False)
        self.assertEqual(self.call(self.b, "GET", "/products"), (403, {"ok": False, "error": "這家沒有開放給你", "code": "forbidden"}))
        self.assertEqual(self.call(self.b, "GET", "/capabilities")[0], 403)
        self.assertNotIn(self.seller, partners.sellers_for(self.b.tenant))
        self.assertEqual(self.buy_unit(self.b, self.one, expect=403)["code"], "forbidden")
        self.approve(self.b)
        self.assertEqual(set(self.products(self.b)), {self.used.sku, self.a.case.sku, self.a.phone.sku})
        self.assertIn(self.seller, partners.sellers_for(self.b.tenant))

    def test_an_approved_dealer_gets_his_own_prices(self):
        self.approve(self.b, percent=90)
        rows = self.products(self.b)
        case, phone = rows[self.a.case.sku], rows[self.a.phone.sku]
        self.assertEqual((case["unit_price"], case["available"], case["requires_serial"], case["per_unit"]), (351, "有貨", False, False))
        self.assertEqual((phone["unit_price"], phone["requires_serial"]), (23000, True))      # 固定批發價不看折數
        self.assertNotIn("available_qty", case)
        self.open_shop(show_qty=True)
        self.assertEqual(self.products(self.b)[self.a.case.sku]["available_qty"], 10)
        # 丙沒有往來:還是只看得到中古機
        self.assertEqual(set(self.products(self.c)), {self.used.sku})

    def test_nobody_sees_cost_or_serial_numbers_before_shipping(self):
        self.approve(self.b)
        text = str(self.call(self.b, "GET", "/products")) + str(self.call(self.b, "GET", "/capabilities"))
        order = self.buy_unit(self.b, self.one)
        text += str(self.detail(self.b, order["order_no"])) + str(self.call(self.b, "GET", "/orders"))
        for secret in ("U100", "N100", "12000", "20000", "cost"):
            self.assertNotIn(secret, text)

    def test_a_blocked_dealer_sees_nothing(self):
        partner = self.approve(self.b)
        r = self.a.admin.post(f"{T}partners/{partner.id}/", {"status": "blocked"}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.assertEqual(self.call(self.b, "GET", "/products")[0], 403)
        self.assertEqual(self.call(self.b, "GET", "/capabilities")[0], 403)
        self.assertEqual(self.buy_unit(self.b, self.one, expect=403)["code"], "forbidden")
        self.assertNotIn(self.seller, partners.sellers_for(self.b.tenant))

    def test_a_blocked_dealer_still_sees_the_orders_he_already_has(self):
        partner = self.approve(self.b)
        order = self.buy_unit(self.b, self.one)
        self.ship(order["order_no"])
        self.a.admin.post(f"{T}partners/{partner.id}/", {"status": "blocked"}, format="json")
        mine = self.detail(self.b, order["order_no"])
        self.assertEqual((mine["status"], mine["shipments"][0]["items"][0]["serials"][0]["sn"]), ("已出貨", "U100"))
        self.assertEqual([o["order_no"] for o in self.call(self.b, "GET", "/orders")[1]["orders"]], [order["order_no"]])
        self.assertEqual(self.call(self.b, "GET", "/statements")[1]["totals"]["due"], 15000)

    def test_a_closed_shop_is_invisible_and_takes_no_orders(self):
        self.approve(self.b)
        self.open_shop(is_open=False)
        self.assertEqual(self.call(self.b, "GET", "/products")[0], 403)
        self.assertEqual(self.buy_unit(self.b, self.one, expect=403)["code"], "forbidden")
        self.assertEqual(partners.sellers_for(self.b.tenant), [])

    def test_a_seller_is_not_on_its_own_list(self):
        self.assertEqual(partners.sellers_for(self.seller), [])

    def test_used_phones_are_listed_unit_by_unit_not_as_goods(self):
        r = self.a.admin.post(T + "products/", {"rows": [{"product": self.used.id, "is_listed": True}]}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("請用上架", r.json()["detail"])
        other = self.b.case
        self.assertEqual(self.a.admin.post(T + "products/", {"rows": [{"product": other.id}]}, format="json").status_code, 400)

    def test_a_product_that_is_switched_off_leaves_the_list(self):
        self.approve(self.b)
        Product.objects.filter(pk=self.a.case.id).update(is_active=False)
        self.assertNotIn(self.a.case.sku, self.products(self.b))
        self.assertEqual(self.buy(self.b, [{"sku": self.a.case.sku, "spec_id": None, "qty": 1}], expect=400)["code"], "not_available")

    def test_an_invite_code_works_once_and_not_for_the_issuer(self):
        r = self.a.admin.post(T + "invites/", {"percent": 85, "terms": "月結"}, format="json")
        code = r.json()["code"]
        self.assertEqual(len(code), 8)
        self.assertNotIn(code, str(self.a.admin.get(T + "partners/").json()))        # 之後查不到代碼本身
        with self.assertRaises(partners.TradeError):
            partners.join(self.seller, code)
        partner = partners.join(self.b.tenant, f" {code.lower()} ")
        self.assertEqual((partner.status, partner.percent, partner.terms, partner.name), ("approved", 85, "月結", "乙通訊行"))
        with self.assertRaises(partners.TradeError):
            partners.join(self.c.tenant, code)
        with self.assertRaises(partners.TradeError):
            partners.join(self.c.tenant, "ZZZZZZZZ")
        self.assertEqual(TradePartner.objects.count(), 1)

    def test_an_expired_invite_does_not_work(self):
        from django.utils import timezone

        from .models import TradeInvite

        code = self.a.admin.post(T + "invites/", {}, format="json").json()["code"]
        TradeInvite.objects.update(expires_at=timezone.now())
        with self.assertRaises(partners.TradeError):
            partners.join(self.b.tenant, code)

    def test_one_dealer_cannot_reach_another_dealers_order(self):
        order = self.buy_unit(self.b, self.one)
        self.assertEqual(self.detail(self.c, order["order_no"], expect=404)["code"], "not_found")
        self.assertEqual(self.call(self.c, "POST", f"/orders/{order['order_no']}/cancel")[0], 404)
        self.assertEqual(self.call(self.c, "GET", "/orders")[1]["orders"], [])
        self.assertEqual(TradeOrder.objects.get().status, S.ACCEPTED)
        # 丙自己也是這個賣家的往來對象(訂過另一台)之後,一樣碰不到乙的單、清單只有自己的
        two, = self.stock_units("U101")
        mine = self.buy_unit(self.c, two)
        self.assertEqual(self.detail(self.c, order["order_no"], expect=404)["code"], "not_found")
        self.assertEqual(self.call(self.c, "POST", f"/orders/{order['order_no']}/cancel")[0], 404)
        self.assertEqual(self.call(self.c, "POST", f"/orders/{order['order_no']}/received", {"items": []})[0], 404)
        self.assertEqual([o["order_no"] for o in self.call(self.c, "GET", "/orders")[1]["orders"]], [mine["order_no"]])
        self.assertEqual([o["order_no"] for o in self.call(self.b, "GET", "/orders")[1]["orders"]], [order["order_no"]])
        self.assertEqual(self.detail(self.c, mine["order_no"])["order_no"], mine["order_no"])
        self.assertEqual(TradeOrder.objects.get(no=order["order_no"]).status, S.ACCEPTED)


class OrderTests(_Trade):
    def setUp(self):
        super().setUp()
        self.open_shop()
        self.one, self.two = self.stock_units("U200", "U201")
        self.a.purchase(case_qty=10, phone_serials=["N200", "N201", "N202"])
        self.offer(self.a.case)
        self.offer(self.a.phone, price=23000)
        self.approve(self.b)

    def test_ordering_a_used_phone_holds_that_one_unit(self):
        got = self.buy_unit(self.b, self.one, payment_method="月結", delivery_method="宅配", note="週五前到",
                            ship_to={"name": "乙一店", "phone": "035550000", "address": "新竹市"})
        self.assertEqual((got["ok"], got["status"], got["total_amount"], got["shipping_fee"]), (True, "已接單", 15000, 0))
        order = TradeOrder.objects.get()
        line = order.lines.get()
        self.assertEqual((order.no, order.buyer_store, order.ship_name, order.note), (got["order_no"], "乙一店", "乙一店", "週五前到"))
        # 付款方式是賣家跟這個同行講好的(發代碼時定的匯款),買家送「月結」不算
        self.assertEqual(order.payment_method, "匯款")
        self.assertEqual((line.unit_id, line.holding, line.unit_price, line.unit_label), (self.one.id, True, D("15000"), "A 級 電池 90% 小刮"))
        # 那一台從清單上消失,另一台還在
        self.assertEqual([s["id"] for s in self.products(self.c)[self.used.sku]["specs"]], [TradeUnit.objects.get(serial=self.two).id])
        # 別人訂同一台:訂不到
        again = self.buy(self.c, [{"sku": self.used.sku, "spec_id": TradeUnit.objects.get(serial=self.one).id, "qty": 1}], expect=400)
        self.assertEqual(again["code"], "unit_gone")
        self.assertEqual(TradeOrder.objects.count(), 1)

    def test_the_same_key_gives_back_the_same_order(self):
        first = self.buy_unit(self.b, self.one, key="b-same-key-01")
        again = self.buy_unit(self.b, self.one, key="b-same-key-01", expect=409)
        self.assertEqual((again["order_no"], again["ok"]), (first["order_no"], False))
        self.assertEqual(TradeOrder.objects.count(), 1)

    def test_a_refused_order_does_not_use_up_the_key(self):
        spec = TradeUnit.objects.get(serial=self.one).id
        self.buy(self.b, [{"sku": self.used.sku, "spec_id": spec, "qty": 2}], key="retry-key-1", expect=400)
        self.buy(self.b, [{"sku": self.used.sku, "spec_id": spec, "qty": 1}], key="retry-key-1")
        self.assertEqual(TradeOrder.objects.count(), 1)

    def test_what_gets_refused(self):
        spec = TradeUnit.objects.get(serial=self.one).id
        for items, code in (
            ([], "empty"),
            ([{"sku": "NOPE", "spec_id": None, "qty": 1}], "not_available"),
            ([{"sku": self.used.sku, "spec_id": None, "qty": 1}], "bad_item"),
            ([{"sku": self.used.sku, "spec_id": 999999, "qty": 1}], "not_available"),
            ([{"sku": self.a.case.sku, "spec_id": 5, "qty": 1}], "bad_item"),
            ([{"sku": self.a.case.sku, "spec_id": None, "qty": 0}], "bad_qty"),
            ([{"sku": self.a.case.sku, "spec_id": None, "qty": 11}], "out_of_stock"),
            ([{"sku": self.a.case.sku, "spec_id": None, "qty": 1}, {"sku": self.a.case.sku, "spec_id": None, "qty": 1}], "duplicate"),
            ([{"sku": self.a.retired.sku, "spec_id": None, "qty": 1}], "not_available"),
            ([{"sku": self.used.sku, "spec_id": spec, "qty": 1}, {"sku": self.a.case.sku, "spec_id": None, "qty": 99}], "out_of_stock"),
        ):
            with self.subTest(code=code, items=items):
                self.assertEqual(self.buy(self.b, items, expect=400)["code"], code)
        self.assertEqual(self.call(self.b, "POST", "/orders", {"idempotency_key": "short", "items": []})[1]["code"], "bad_key")
        # 規格(哪一台)要是那個商品底下的:拿別的商品的那一台來配不算
        other = Product.objects.create(tenant=self.seller, category=self.a.cat_phone, name="甲 中古 Pixel 8", is_secondhand=True, list_price=9000)
        self.assertEqual(self.buy(self.b, [{"sku": other.sku, "spec_id": spec, "qty": 1}], expect=400)["code"], "unit_gone")
        self.assertEqual((TradeOrder.objects.count(), TradeOrderLine.objects.count()), (0, 0))

    def test_goods_ordered_by_one_dealer_are_not_offered_again(self):
        self.approve(self.c)
        self.open_shop(show_qty=True)
        self.buy(self.b, [{"sku": self.a.case.sku, "spec_id": None, "qty": 7}, {"sku": self.a.phone.sku, "spec_id": None, "qty": 2}])
        rows = self.products(self.c)
        self.assertEqual((rows[self.a.case.sku]["available_qty"], rows[self.a.phone.sku]["available_qty"]), (3, 1))
        self.assertEqual(self.buy(self.c, [{"sku": self.a.case.sku, "spec_id": None, "qty": 4}], expect=400)["code"], "out_of_stock")
        self.buy(self.c, [{"sku": self.a.case.sku, "spec_id": None, "qty": 3}])
        self.assertEqual(self.products(self.b)[self.a.case.sku]["available"], "缺貨")

    def test_prices_are_the_sellers_and_frozen_on_the_order(self):
        got = self.buy(self.b, [{"sku": self.a.case.sku, "spec_id": None, "qty": 4, "unit_price": 1}], total_amount=4)
        self.assertEqual(got["total_amount"], 1404)                  # 390 × 90% = 351
        TradePartner.objects.update(percent=50)
        self.assertEqual(self.detail(self.b, got["order_no"])["items"][0]["unit_price"], 351)

    def test_when_the_seller_wants_to_accept_by_hand(self):
        self.open_shop(auto_accept=False)
        self.assertIn("accept", self.call(self.b, "GET", "/capabilities")[1]["capabilities"])
        got = self.buy_unit(self.b, self.one)
        self.assertEqual(got["status"], "待接單")
        self.assertEqual(self.ship(got["order_no"], expect=400)["detail"], "這張單還沒接單")
        order = TradeOrder.objects.get()
        r = self.a.clerk.post(f"{T}orders/{order.id}/accept/", {}, format="json")
        self.assertEqual((r.status_code, r.json()["status_text"]), (200, "已接單"))
        self.assertEqual(self.a.clerk.post(f"{T}orders/{order.id}/accept/", {}, format="json").status_code, 400)

    def test_rejecting_frees_the_unit(self):
        self.open_shop(auto_accept=False)
        got = self.buy_unit(self.b, self.one)
        order = TradeOrder.objects.get()
        r = self.a.admin.post(f"{T}orders/{order.id}/reject/", {"reason": "這台有人要了"}, format="json")
        self.assertEqual((r.status_code, r.json()["status_text"], r.json()["close_reason"]), (200, "已拒絕", "這台有人要了"))
        mine = self.detail(self.b, got["order_no"])
        self.assertEqual((mine["status"], mine["items"], mine["close_reason"]), ("已拒絕", [], "這台有人要了"))
        self.assertEqual(len(self.products(self.c)[self.used.sku]["specs"]), 2)

    def test_an_accepted_order_cannot_be_rejected(self):
        self.buy_unit(self.b, self.one)
        order = TradeOrder.objects.get()
        r = self.a.admin.post(f"{T}orders/{order.id}/reject/", {}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual((TradeOrder.objects.get().status, TradeOrderLine.objects.get().holding), (S.ACCEPTED, True))

    def test_dropping_part_of_a_line(self):
        got = self.buy(self.b, [{"sku": self.a.case.sku, "spec_id": None, "qty": 4}])
        data = self.seller_order(got["order_no"])
        line = data["lines"][0]["id"]
        for qty in (5, 0, -1, "2", True):
            r = self.a.admin.post(f"{T}orders/{data['id']}/drop/", {"line": line, "qty": qty}, format="json")
            self.assertEqual(r.status_code, 400, qty)
        r = self.a.admin.post(f"{T}orders/{data['id']}/drop/", {"line": line, "qty": 3}, format="json")
        self.assertEqual((r.status_code, r.json()["lines"][0]["open_qty"], r.json()["status_text"]), (200, 1, "已接單"))
        mine = self.detail(self.b, got["order_no"])
        self.assertEqual((mine["items"][0]["qty"], mine["total_amount"], mine["cancelled_items"][0]["qty"]), (1, 351, 3))

    def test_the_buyer_can_cancel_what_has_not_shipped(self):
        got = self.buy(self.b, [{"sku": self.used.sku, "spec_id": TradeUnit.objects.get(serial=self.one).id, "qty": 1},
                               {"sku": self.a.case.sku, "spec_id": None, "qty": 3}])
        status, data = self.call(self.b, "POST", f"/orders/{got['order_no']}/cancel")
        self.assertEqual((status, data["status"]), (200, "已取消"))
        order = TradeOrder.objects.get()
        self.assertEqual((order.status, order.closed_by_buyer, order.close_reason), (S.CANCELLED, True, "買家取消"))
        self.assertFalse(TradeOrderLine.objects.filter(holding=True).exists())
        self.assertEqual(len(self.products(self.c)[self.used.sku]["specs"]), 2)
        status, data = self.call(self.b, "POST", f"/orders/{got['order_no']}/cancel")
        self.assertEqual((status, data["code"]), (400, "not_cancellable"))

    def test_cancelling_after_part_has_shipped_keeps_the_shipped_part(self):
        got = self.buy(self.b, [{"sku": self.used.sku, "spec_id": TradeUnit.objects.get(serial=self.one).id, "qty": 1},
                               {"sku": self.a.case.sku, "spec_id": None, "qty": 3}])
        data = self.seller_order(got["order_no"])
        case_line = next(line for line in data["lines"] if not line["per_unit"])
        self.ship(got["order_no"], lines=[{"line": case_line["id"], "qty": 2, "serials": []}])
        self.assertEqual(self.detail(self.b, got["order_no"])["status"], "部分出貨")
        status, data = self.call(self.b, "POST", f"/orders/{got['order_no']}/cancel")
        self.assertEqual((status, data["status"]), (200, "已出貨"))
        mine = self.detail(self.b, got["order_no"])
        self.assertEqual([(i["sku"], i["qty"], i["shipped_qty"]) for i in mine["items"]], [(self.a.case.sku, 2, 2)])
        self.assertEqual({(i["sku"], i["qty"]) for i in mine["cancelled_items"]}, {(self.used.sku, 1), (self.a.case.sku, 1)})
        self.assertEqual(mine["total_amount"], 702)

    def test_the_seller_drops_one_unit_and_ships_the_rest(self):
        got = self.buy(self.b, [{"sku": self.used.sku, "spec_id": TradeUnit.objects.get(serial=u).id, "qty": 1} for u in (self.one, self.two)])
        data = self.seller_order(got["order_no"])
        r = self.a.clerk.post(f"{T}orders/{data['id']}/drop/", {"line": data["lines"][0]["id"], "reason": "找不到這一台"}, format="json")
        self.assertEqual((r.status_code, r.json()["status_text"]), (200, "已接單"))
        self.assertEqual([line["open_qty"] for line in r.json()["lines"]], [0, 1])
        shipped = self.ship(got["order_no"])
        self.assertEqual(shipped["status_text"], "已出貨")
        self.assertEqual(self.detail(self.b, got["order_no"])["total_amount"], 15000)
        # 不出的那一台回到清單上
        self.assertEqual([s["id"] for s in self.products(self.c)[self.used.sku]["specs"]], [TradeUnit.objects.get(serial=self.one).id])
        self.assertEqual(self.a.clerk.post(f"{T}orders/{data['id']}/drop/", {"line": data["lines"][1]["id"]}, format="json").status_code, 400)

    def test_dropping_everything_cancels_the_order(self):
        got = self.buy_unit(self.b, self.one)
        order = TradeOrder.objects.get()
        r = self.a.admin.post(f"{T}orders/{order.id}/drop/", {"reason": "不賣了"}, format="json")
        self.assertEqual((r.json()["status_text"], r.json()["closed_by_buyer"], r.json()["close_reason"]), ("已取消", False, "不賣了"))
        self.assertEqual(self.detail(self.b, got["order_no"])["status"], "已取消")


class ShippingTests(_Trade):
    def setUp(self):
        super().setUp()
        self.open_shop()
        self.one, self.two = self.stock_units("U300", "U301")
        self.a.purchase(case_qty=10, phone_serials=["N300", "N301", "N302"])
        self.offer(self.a.case)
        self.offer(self.a.phone, price=23000)
        self.approve(self.b)

    def scan(self, code, client=None, warehouse=None, expect=200):
        r = (client or self.a.clerk).post(T + "scan/", {"code": code, "warehouse": (warehouse or self.wh1).id}, format="json")
        self.assertEqual(r.status_code, expect, r.content.decode())
        return r.json()

    def test_scan_a_unit_and_it_finds_the_order_then_shipping_writes_one_sales_order(self):
        got = self.buy_unit(self.b, self.one)
        found = self.scan("u-300")
        order = TradeOrder.objects.get()
        line = order.lines.get()
        self.assertEqual((found["serial"], found["sn"], found["lines"]),
                         (self.one.id, "U300", [{"order": order.id, "order_no": order.no, "line": line.id, "open_qty": 1}]))
        data = self.ship(got["order_no"], client=self.a.clerk, lines=[{"line": line.id, "qty": 1, "serials": [found["serial"]]}])
        self.assertEqual((data["status_text"], data["owed"], data["due"], data["payment_status"]), ("已出貨", 15000, 15000, "未收款"))
        so = SalesOrder.objects.get(tenant=self.seller, note__startswith="批發")
        self.assertEqual((so.total, so.customer.kind, so.customer.name, so.source_name, so.warehouse_id, so.is_void),
                         (D("15000"), "peer", "乙通訊行", "乙通訊行", self.wh1.id, False))
        self.assertEqual([(p.method, p.amount) for p in so.payments.all()], [("peer", D("15000"))])
        # 「同行記帳」不進當日現金,而且是停用的:門市結帳的付款方式不會列出它
        from apps.tenants.models import PaymentMethod

        credit = PaymentMethod.objects.get(tenant=self.seller, code="peer")
        self.assertEqual((credit.kind, credit.is_active, credit.name), ("non_cash", False, "同行記帳"))
        item = so.items.get()
        self.assertEqual((item.product_id, item.cost_at_post, [x.serial_id for x in item.serials.all()]), (self.used.id, D("12000"), [self.one.id]))
        self.one.refresh_from_db()
        self.assertEqual((self.one.status, self.one.warehouse_id), ("sold", None))
        self.assertFalse(TradeUnit.objects.get(serial=self.one).is_listed)
        shipment = TradeShipment.objects.get()
        self.assertEqual((shipment.no, shipment.sales_order_id, shipment.goods_amount), (f"{order.no}-1", so.id, D("15000")))
        # 買家這時候才看得到序號與機況
        mine = self.detail(self.b, got["order_no"])
        self.assertEqual(mine["status"], "已出貨")
        self.assertEqual(mine["shipments"][0]["items"], [{
            "sku": self.used.sku, "spec_id": TradeUnit.objects.get(serial=self.one).id, "qty": 1,
            "serials": [{"imei": "", "sn": "U300", "grade": "A", "battery": 90, "note": "小刮"}]}])
        self.assertEqual(mine["items"][0]["shipped_qty"], 1)

    def test_the_same_key_does_not_ship_twice(self):
        got = self.buy_unit(self.b, self.one)
        self.ship(got["order_no"], key="ship-same-01")
        self.ship(got["order_no"], key="ship-same-01", lines=[{"line": TradeOrderLine.objects.get().id, "qty": 1, "serials": [self.one.id]}])
        self.assertEqual((TradeShipment.objects.count(), SalesOrder.objects.filter(note__startswith="批發").count()), (1, 1))
        other = self.buy_unit(self.b, self.two)
        r = self.ship(other["order_no"], key="ship-same-01", expect=400)
        self.assertIn("另一張批發單", r["detail"])

    def test_new_phones_need_exactly_as_many_scans_and_accessories_come_off_the_shelf(self):
        got = self.buy(self.b, [{"sku": self.a.phone.sku, "spec_id": None, "qty": 2}, {"sku": self.a.case.sku, "spec_id": None, "qty": 4}])
        data = self.seller_order(got["order_no"])
        phone_line, case_line = data["lines"]
        n = {s.serial_no: s.id for s in ProductSerial.objects.filter(serial_no__startswith="N3")}
        found = self.scan("N300")
        self.assertEqual(found["lines"], [{"order": data["id"], "order_no": data["no"], "line": phone_line["id"], "open_qty": 2}])
        bad = self.ship(got["order_no"], expect=400, lines=[{"line": phone_line["id"], "qty": 2, "serials": [n["N300"]]}])
        self.assertIn("要出 2 台,刷了 1 台", bad["detail"])
        bad = self.ship(got["order_no"], expect=400, lines=[{"line": phone_line["id"], "qty": 1, "serials": [self.one.id]}])
        self.assertIn("不屬於商品", bad["detail"])
        bad = self.ship(got["order_no"], expect=400, lines=[{"line": case_line["id"], "qty": 5, "serials": []}])
        self.assertIn("還沒出的只有 4 個", bad["detail"])
        done = self.ship(got["order_no"], lines=[{"line": phone_line["id"], "qty": 2, "serials": [n["N300"], n["N301"]]},
                                                {"line": case_line["id"], "qty": 4, "serials": []}])
        self.assertEqual((done["status_text"], done["owed"]), ("已出貨", 23000 * 2 + 351 * 4))
        self.assertEqual(StockBalance.objects.get(tenant=self.seller, product=self.a.case, warehouse=self.wh1).qty, 6)
        mine = self.detail(self.b, got["order_no"])
        self.assertEqual([[x["sn"] for x in i["serials"]] for i in mine["shipments"][0]["items"]], [["N300", "N301"], []])

    def test_a_shipment_that_cannot_post_changes_nothing(self):
        got = self.buy(self.b, [{"sku": self.used.sku, "spec_id": TradeUnit.objects.get(serial=self.one).id, "qty": 1},
                               {"sku": self.a.case.sku, "spec_id": None, "qty": 4}])
        StockBalance.objects.filter(product=self.a.case).update(qty=3)       # 門市先賣掉了
        bad = self.ship(got["order_no"], expect=400)
        self.assertIn("不足銷售", bad["detail"])
        self.one.refresh_from_db()
        self.assertEqual((self.one.status, TradeShipment.objects.count(), SalesOrder.objects.filter(note__startswith="批發").count()),
                         ("in_stock", 0, 0))
        line = TradeOrderLine.objects.get(unit=self.one)
        self.assertEqual((line.holding, line.shipped_qty), (True, 0))          # 那一台還是被這張單訂著

    def test_a_used_phone_line_ships_only_the_unit_that_was_ordered(self):
        got = self.buy_unit(self.b, self.one)
        line = TradeOrderLine.objects.get()
        bad = self.ship(got["order_no"], expect=400, lines=[{"line": line.id, "qty": 1, "serials": [self.two.id]}])
        self.assertIn("要刷那一台", bad["detail"])
        self.assertEqual(self.scan("U301", expect=400)["detail"], "U301(甲 中古 iPhone 13 128GB)沒有同行訂")
        ProductSerial.objects.filter(pk=self.one.id).update(status="rma")
        self.assertEqual(self.scan("U300", expect=400)["detail"], "U300 現在是「維修中」,不能出貨")
        self.assertEqual(self.scan("沒有這個碼", expect=400)["detail"], "找不到這個碼")

    def test_a_unit_ships_from_the_store_it_is_in(self):
        far, = self.stock_units("U310", warehouse=self.wh2)
        got = self.buy_unit(self.b, far)
        self.assertIn("要由那一家出貨", self.scan("U310", client=self.a.admin, expect=400)["detail"])
        self.assertIn("不在銷貨倉內", self.ship(got["order_no"], expect=400)["detail"])
        # 鎖在湳雅店的店員不能替民生店出貨
        line = TradeOrderLine.objects.get(unit=far)
        r = self.a.clerk.post(f"{T}orders/{line.order_id}/ship/", {
            "request_key": "ship-far-001", "warehouse": self.wh2.id, "lines": [{"line": line.id, "qty": 1, "serials": [far.id]}]}, format="json")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.ship(got["order_no"], warehouse=self.wh2)["status_text"], "已出貨")

    def test_shipping_fee_is_a_line_on_the_sales_order_and_part_of_what_is_owed(self):
        got = self.buy_unit(self.b, self.one)
        data = self.ship(got["order_no"], shipping_fee=120, tracking_no="SF123", shipping_method="順豐")
        self.assertEqual((data["owed"], data["shipments"][0]["shipping_fee"], data["shipments"][0]["tracking_no"]), (15120, 120, "SF123"))
        so = SalesOrder.objects.get(note__startswith="批發")
        self.assertEqual((so.total, sorted(i.product.name for i in so.items.all())), (D("15120"), ["批發運費", "甲 中古 iPhone 13 128GB"]))
        mine = self.detail(self.b, got["order_no"])
        self.assertEqual((mine["shipping_fee"], mine["total_amount"], mine["tracking_no"], mine["shipping_method"]), (120, 15120, "SF123", "順豐"))
        self.assertEqual(self.ship(self.buy_unit(self.b, self.two)["order_no"], shipping_fee=-1, expect=400)["detail"], "運費要是 0 到 99999 的整數")

    def test_cancelling_a_shipment_puts_everything_back(self):
        got = self.buy(self.b, [{"sku": self.used.sku, "spec_id": TradeUnit.objects.get(serial=self.one).id, "qty": 1},
                               {"sku": self.a.case.sku, "spec_id": None, "qty": 4}])
        data = self.ship(got["order_no"])
        shipment = data["shipments"][0]
        # 批發出貨開的銷貨單不能從銷貨單那邊作廢
        r = self.a.admin.post(f"/api/v1/sales-orders/{shipment['sales_order']}/void/", {}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("請到「批發單」取消那一次出貨", r.json()["detail"])
        self.assertFalse(SalesOrder.objects.get(pk=shipment["sales_order"]).is_void)
        r = self.a.admin.post(f"{T}shipments/{shipment['id']}/void/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        back = r.json()
        self.assertEqual((back["status_text"], back["owed"], [l["open_qty"] for l in back["lines"]], back["shipments"][0]["is_void"]),
                         ("已接單", 0, [1, 4], True))
        self.one.refresh_from_db()
        self.assertEqual((self.one.status, self.one.warehouse_id), ("in_stock", self.wh1.id))
        self.assertTrue(SalesOrder.objects.get(pk=shipment["sales_order"]).is_void)
        self.assertEqual(StockBalance.objects.get(tenant=self.seller, product=self.a.case, warehouse=self.wh1).qty, 10)
        self.assertTrue(TradeOrderLine.objects.get(unit=self.one).holding)        # 回到被這張單訂著:別人訂不到
        self.assertEqual(self.detail(self.b, got["order_no"])["shipments"], [])
        self.assertEqual(self.a.admin.post(f"{T}shipments/{shipment['id']}/void/", {}, format="json").status_code, 400)
        again = self.ship(got["order_no"])
        self.assertEqual((again["status_text"], [s["no"] for s in again["shipments"]]), ("已出貨", [f"{again['no']}-1", f"{again['no']}-2"]))

    def test_cancelling_a_shipment_needs_the_void_ability(self):
        got = self.buy_unit(self.b, self.one)
        shipment = self.ship(got["order_no"])["shipments"][0]
        UserProfile.objects.filter(user=self.a.clerk_user).update(denied_abilities=["void_sales"])
        self.a.clerk_user.profile.refresh_from_db()
        self.assertEqual(self.a.clerk.post(f"{T}shipments/{shipment['id']}/void/", {}, format="json").status_code, 403)
        self.assertFalse(TradeShipment.objects.get().is_void)

    def test_a_clerk_cannot_cancel_another_stores_shipment(self):
        far, = self.stock_units("U320", warehouse=self.wh2)
        shipment = self.ship(self.buy_unit(self.b, far)["order_no"], warehouse=self.wh2)["shipments"][0]
        self.assertEqual(self.a.clerk.post(f"{T}shipments/{shipment['id']}/void/", {}, format="json").status_code, 403)
        self.assertFalse(TradeShipment.objects.get().is_void)

    def test_the_buyer_reports_what_it_has_received(self):
        """買家回報「到現在為止收了多少」(整張單現在的樣子):收的不能比算數的已出多、序號要是這張單出過的。"""
        got = self.buy(self.b, [{"sku": self.used.sku, "spec_id": TradeUnit.objects.get(serial=self.one).id, "qty": 1},
                               {"sku": self.a.case.sku, "spec_id": None, "qty": 4}])
        no, spec = got["order_no"], TradeUnit.objects.get(serial=self.one).id
        unit = {"sku": self.used.sku, "spec_id": spec, "received_qty": 1, "serials": [{"imei": "", "sn": "U300"}]}
        cases = {"sku": self.a.case.sku, "spec_id": None, "received_qty": 4, "serials": []}
        # 還沒出貨:什麼都不能收
        self.assertEqual(self.call(self.b, "POST", f"/orders/{no}/received", {"items": [cases]})[1]["code"], "over_received")
        data = self.seller_order(no)
        case_line = next(l for l in data["lines"] if not l["per_unit"])
        unit_line = next(l for l in data["lines"] if l["per_unit"])
        self.ship(no, lines=[{"line": case_line["id"], "qty": 2, "serials": []}, {"line": unit_line["id"], "qty": 1, "serials": [self.one.id]}])
        for bad in ([cases],                                                              # 出 2 收 4
                    [{**unit, "serials": []}], [{**unit, "serials": [{"imei": "", "sn": "U301"}]}],   # 序號不對
                    [{**cases, "received_qty": -1}], [{**cases, "sku": "NOPE"}], [unit, unit], "abc", None):
            status, body = self.call(self.b, "POST", f"/orders/{no}/received", {"items": bad})
            self.assertEqual(status, 400, bad)
        self.assertEqual(sorted(l.received_qty for l in TradeOrderLine.objects.all()), [0, 0])
        status, body = self.call(self.b, "POST", f"/orders/{no}/received", {"items": [unit, {**cases, "received_qty": 2}]})
        self.assertEqual((status, body["ok"]), (200, True))
        from .models import TradeShipmentSerial

        self.assertEqual((sorted(l.received_qty for l in TradeOrderLine.objects.all()), TradeShipmentSerial.objects.get().received), ([1, 2], True))
        self.assertEqual(self.detail(self.b, no)["items"][0]["received_qty"] + self.detail(self.b, no)["items"][1]["received_qty"], 3)
        # 別人不能替他報;再報一次空的 = 都沒收(買家把進貨單作廢了)
        self.assertEqual(self.call(self.c, "POST", f"/orders/{no}/received", {"items": []})[0], 404)
        self.assertEqual(self.call(self.b, "POST", f"/orders/{no}/received", {"items": []})[0], 200)
        self.assertEqual((sorted(l.received_qty for l in TradeOrderLine.objects.all()), TradeShipmentSerial.objects.get().received), ([0, 0], False))
        self.assertIn("receipts", self.call(self.b, "GET", "/capabilities")[1]["capabilities"])

    def test_a_whole_return_of_the_sales_order_takes_it_off_the_books(self):
        got = self.buy_unit(self.b, self.one)
        data = self.ship(got["order_no"])
        so = SalesOrder.objects.get(pk=data["shipments"][0]["sales_order"])
        SalesReturn.objects.create(tenant=self.seller, original_so=so, warehouse=self.wh1, customer=so.customer)
        after = self.seller_order(got["order_no"])
        self.assertEqual((after["owed"], after["shipments"][0]["returned"]), (0, True))
        self.assertEqual(self.detail(self.b, got["order_no"])["shipments"], [])


class RetailConflictTests(_Trade):
    """紅隊第 1 條:掛在批發上的那一台被同行訂了,現場客人也要。"""

    def setUp(self):
        super().setUp()
        self.open_shop()
        self.one, self.two = self.stock_units("U400", "U401")
        self.got = self.buy_unit(self.b, self.one)

    def sell(self, serial, expect=201, **extra):
        r = self.a.clerk.post("/api/v1/sales-orders/", {
            "customer": self.a.customer.id, "warehouse": self.wh1.id, "tax_method": "untaxed",
            "items": [{"product": self.used.id, "qty": 1, "unit_price": "16000", "serial_ids": [serial.id]}],
            "payments": [{"method": "cash", "amount": "16000"}], **extra}, format="json")
        self.assertEqual(r.status_code, expect, r.content.decode())
        return r.json()

    def test_selling_a_held_unit_is_stopped_until_the_clerk_says_so(self):
        bad = self.sell(self.one, expect=400)
        order = TradeOrder.objects.get()
        self.assertEqual(bad["code"], "trade_hold")
        # 錯誤回應裡的值一律是字(框架轉的);畫面把 serial 原樣帶回 release_trade_units 就可以
        self.assertEqual(bad["units"], [{"serial": str(self.one.id), "serial_no": "U400", "name": "甲 中古 iPhone 13 128GB",
                                         "order_no": order.no, "partner": "乙通訊行"}])
        self.assertIn("已經被同行「乙通訊行」訂走", bad["detail"])
        self.one.refresh_from_db()
        self.assertEqual((self.one.status, SalesOrder.objects.filter(tenant=self.seller, total=16000).count()), ("in_stock", 0))
        self.assertTrue(TradeOrderLine.objects.get().holding)
        # 講的是別台不算
        self.sell(self.one, expect=400, release_trade_units=[self.two.id])

    def test_selling_it_to_the_walk_in_customer_cancels_the_dealers_line_right_away(self):
        self.sell(self.one, release_trade_units=[str(self.one.id)])        # 畫面帶回來的是錯誤回應裡的那個字
        self.one.refresh_from_db()
        order = TradeOrder.objects.get()
        line = order.lines.get()
        self.assertEqual((self.one.status, line.holding, line.cancelled_qty, order.status, order.close_reason, order.closed_by_buyer),
                         ("sold", False, 1, S.CANCELLED, "賣家改賣給現場客人", False))
        mine = self.detail(self.b, self.got["order_no"])
        self.assertEqual((mine["status"], mine["close_reason"], mine["items"]), ("已取消", "賣家改賣給現場客人", []))
        # 不會兩邊都賣出:那張批發單出不了貨
        self.assertEqual(self.ship(self.got["order_no"], expect=400, lines=[{"line": line.id, "qty": 1, "serials": [self.one.id]}])["detail"],
                         "這張單現在是「已取消」,不能出貨")

    def test_a_unit_nobody_ordered_sells_as_usual(self):
        self.sell(self.two)
        self.assertEqual(TradeOrder.objects.get().status, S.ACCEPTED)


class PaymentTests(_Trade):
    def setUp(self):
        super().setUp()
        self.open_shop()
        self.one, self.two, self.three = self.stock_units("U500", "U501", "U502")
        self.first = self.buy_unit(self.b, self.one)["order_no"]
        self.second = self.buy_unit(self.b, self.two)["order_no"]
        self.partner = TradePartner.objects.get()

    def pay(self, amount, client=None, expect=201, key=None, **extra):
        self.keys += 1
        r = (client or self.a.admin).post(T + "payments/", {
            "partner": self.partner.id, "amount": amount, "request_key": key or f"pay-{self.keys:05d}", **extra}, format="json")
        self.assertEqual(r.status_code, expect, r.content.decode())
        return r.json()

    def test_only_shipped_goods_are_owed(self):
        self.ship(self.first)
        book = self.a.admin.get(f"{T}partners/{self.partner.id}/ledger/").json()
        self.assertEqual((book["partner"]["owed"], book["partner"]["due"], [o["no"] for o in book["orders"]]), (15000, 15000, [self.first]))

    def test_one_payment_settles_orders_oldest_first(self):
        self.ship(self.first)
        self.ship(self.second)
        book = self.pay(20000, method="匯款", note="10 月貨款", received_on="2026-10-10")
        self.assertEqual([(o["no"], o["paid"], o["due"], o["payment_status"]) for o in book["orders"]],
                         [(self.first, 15000, 0, "已收款"), (self.second, 5000, 10000, "收了一部分")])
        self.assertEqual((book["partner"]["due"], book["partner"]["credit"], book["payments"][0]["method"], book["payments"][0]["received_on"]),
                         (10000, 0, "匯款", "2026-10-10"))
        # 買家那邊看到的是同一份數字
        status, mine = self.call(self.b, "GET", "/statements")
        self.assertEqual([(o["order_no"], o["shipped_amount"], o["paid_amount"], o["due_amount"], o["payment_status"]) for o in mine["orders"]],
                         [(self.first, 15000, 15000, 0, "已收款"), (self.second, 15000, 5000, 10000, "收了一部分")])
        self.assertEqual((mine["totals"], mine["credit"]), ({"shipped": 30000, "paid": 20000, "due": 10000}, 0))
        self.assertEqual(self.detail(self.b, self.second)["payment_status"], "收了一部分")
        book = self.pay(12000)
        self.assertEqual((book["partner"]["due"], book["partner"]["credit"]), (0, 2000))       # 多收的留著,下一張出貨時自動抵
        third = self.buy_unit(self.b, self.three)["order_no"]
        self.assertEqual(self.ship(third)["paid"], 2000)

    def test_voiding_a_payment_or_a_shipment_makes_the_numbers_right_again(self):
        first = self.ship(self.first)
        self.ship(self.second)
        book = self.pay(15000)
        self.a.admin.post(f"{T}shipments/{first['shipments'][0]['id']}/void/", {}, format="json")
        book = self.a.admin.get(f"{T}partners/{self.partner.id}/ledger/").json()
        self.assertEqual([(o["no"], o["paid"]) for o in book["orders"]], [(self.second, 15000)])   # 那筆錢改算在還有出貨的那一張
        r = self.a.admin.post(f"{T}payments/{book['payments'][0]['id']}/void/", {}, format="json")
        self.assertEqual((r.status_code, r.json()["partner"]["due"], r.json()["payments"][0]["is_void"]), (200, 15000, True))
        self.assertEqual(self.a.admin.post(f"{T}payments/{book['payments'][0]['id']}/void/", {}, format="json").status_code, 400)

    def test_the_same_key_records_once_and_bad_amounts_are_refused(self):
        self.ship(self.first)
        self.pay(1000, key="pay-same-0001")
        self.pay(1000, key="pay-same-0001")
        self.assertEqual(TradePayment.objects.count(), 1)
        for amount in (0, -5, 1.5, "100", None, True, 100_000_000):
            self.pay(amount, expect=400)
        self.pay(100, expect=400, received_on="2999-01-01")
        self.pay(100, expect=400, received_on="昨天")
        self.assertEqual(TradePayment.objects.count(), 1)

    def test_money_and_partners_are_for_managers_only(self):
        self.ship(self.first)
        self.pay(100, client=self.a.clerk, expect=403)
        for url in (f"{T}partners/", f"{T}partners/{self.partner.id}/ledger/", f"{T}products/"):
            self.assertEqual(self.a.clerk.get(url).status_code, 403, url)
        for url, body in ((f"{T}settings/", {"is_open": False}), (f"{T}invites/", {}), (f"{T}partners/{self.partner.id}/", {"percent": 1}),
                          (f"{T}products/", {"rows": [{"product": self.a.case.id}]})):
            self.assertEqual(self.a.clerk.post(url, body, format="json").status_code, 403, url)
        self.assertTrue(TradeSetting.objects.get(tenant=self.seller).is_open)


class AccessTests(_Trade):
    def setUp(self):
        super().setUp()
        self.open_shop()
        self.one, = self.stock_units("U600")
        self.got = self.buy_unit(self.b, self.one)
        self.order = TradeOrder.objects.get()

    def test_a_clerk_without_the_ability_cannot_touch_wholesale(self):
        UserProfile.objects.filter(user=self.a.clerk_user).update(denied_abilities=["trade_sell"])
        self.a.clerk_user.profile.refresh_from_db()
        line = self.order.lines.get()
        for method, url, body in (
            ("get", f"{T}orders/", None), ("get", f"{T}orders/{self.order.id}/", None), ("get", f"{T}units/", None),
            ("get", f"{T}summary/", None), ("get", f"{T}settings/", None), ("get", f"{T}units/models/", None),
            ("post", f"{T}scan/", {"code": "U600", "warehouse": self.wh1.id}),
            ("post", f"{T}orders/{self.order.id}/ship/", {"request_key": "ship-x-0001", "warehouse": self.wh1.id,
                                                          "lines": [{"line": line.id, "qty": 1, "serials": [self.one.id]}]}),
            ("post", f"{T}orders/{self.order.id}/drop/", {}), ("post", f"{T}units/unlist/", {"serials": [self.one.id]}),
            ("post", f"{T}units/list/", {"rows": [{"serial": self.one.id}]}),
        ):
            r = getattr(self.a.clerk, method)(url, body, format="json") if body is not None else getattr(self.a.clerk, method)(url)
            self.assertEqual(r.status_code, 403, url)
        self.assertEqual((TradeOrder.objects.get().status, TradeShipment.objects.count()), (S.ACCEPTED, 0))

    def test_another_company_cannot_see_or_ship_it(self):
        line = self.order.lines.get()
        self.assertEqual(self.b.admin.get(f"{T}orders/").json()["total"], 0)
        self.assertEqual(self.b.admin.get(f"{T}orders/{self.order.id}/").status_code, 404)
        r = self.b.admin.post(f"{T}orders/{self.order.id}/ship/", {"request_key": "ship-y-0001", "warehouse": self.b.wh.id,
                                                                   "lines": [{"line": line.id, "qty": 1, "serials": [self.one.id]}]}, format="json")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(self.b.admin.post(f"{T}orders/{self.order.id}/drop/", {}, format="json").status_code, 404)
        partner = TradePartner.objects.get()
        self.assertEqual(self.b.admin.post(f"{T}partners/{partner.id}/", {"percent": 1}, format="json").status_code, 404)
        self.assertEqual(self.b.admin.post(f"{T}payments/", {"partner": partner.id, "amount": 1, "request_key": "pay-z-00001"},
                                           format="json").status_code, 404)
        self.assertEqual(self.b.admin.get(f"{T}units/?state=all").json()["total"], 0)

    def test_the_order_list_and_the_counter_on_top(self):
        self.assertEqual(self.a.clerk.get(f"{T}summary/").json(), {"pending": 0, "to_ship": 1})
        rows = self.a.clerk.get(f"{T}orders/").json()
        self.assertEqual((rows["total"], rows["results"][0]["no"], rows["results"][0]["lines"][0]["unit"]["serial_no"]), (1, self.order.no, "U600"))
        self.ship(self.got["order_no"])
        self.assertEqual(self.a.clerk.get(f"{T}orders/").json()["total"], 0)
        self.assertEqual(self.a.clerk.get(f"{T}orders/?state=closed").json()["total"], 1)
        self.assertEqual(self.a.clerk.get(f"{T}orders/?state=all&q=U600").json()["total"], 1)
        self.assertEqual(self.a.clerk.get(f"{T}orders/?state=all&q=找不到").json()["total"], 0)


# ── 兩條連線同時來(真的鎖;不是只看發出去的查詢) ───────────────────────────────
import threading  # noqa: E402
import time  # noqa: E402

from django.db import connections  # noqa: E402
from django.db.utils import OperationalError  # noqa: E402
from django.test import TransactionTestCase  # noqa: E402


class TwoAtOnceTests(_Helpers, TransactionTestCase):
    """鎖的順序:序號 → 批發單 → 庫存餘額(`base.py`)。每一條都是「另一條連線握著鎖做完一件事、過 1 秒才提交」,
    這邊的動作要等它、而且看到的是它提交之後的樣子。"""

    def setUp(self):
        super().setUp()
        self.open_shop()
        self.one, self.two = self.stock_units("U700", "U701")

    def meanwhile(self, statements, hold=1.0):
        """另一條連線照順序做這幾句、握著 `hold` 秒才提交。回來時它已經握著鎖了。"""
        holding = threading.Event()

        def work():
            other = connections.create_connection("default")
            try:
                other.ensure_connection()
                other.set_autocommit(False)
                with other.cursor() as cur:
                    for sql, args in statements:
                        cur.execute(sql, args)
                holding.set()
                time.sleep(hold)
                other.commit()
            finally:
                other.close()

        t = threading.Thread(target=work)
        t.start()
        self.addCleanup(t.join)
        self.assertTrue(holding.wait(5))
        return time.monotonic()

    LOCK_SERIAL = "SELECT 1 FROM inventory_productserial WHERE id = %s FOR NO KEY UPDATE"

    def test_ordering_waits_for_whoever_has_the_unit_and_then_sees_it_is_gone(self):
        # 另一邊(門市)鎖著那一台、把它賣掉
        began = self.meanwhile([(self.LOCK_SERIAL, [self.one.id]),
                                ("UPDATE inventory_productserial SET status = 'sold', warehouse_id = NULL WHERE id = %s", [self.one.id])])
        got = self.buy_unit(self.b, self.one, expect=400)
        self.assertGreater(time.monotonic() - began, 0.5)
        self.assertEqual(got["code"], "unit_gone")
        self.assertEqual(TradeOrder.objects.count(), 0)

    def test_listing_waits_for_the_counter_sale_and_does_not_put_a_sold_unit_back(self):
        # 另一邊(門市)鎖著那一台、把它賣掉;這邊同時把兩台一起改價
        began = self.meanwhile([(self.LOCK_SERIAL, [self.one.id]),
                                ("UPDATE inventory_productserial SET status = 'sold', warehouse_id = NULL WHERE id = %s", [self.one.id])])
        r = self.a.admin.post(T + "units/list/", {"rows": [{"serial": self.two.id, "price": 9000}, {"serial": self.one.id, "price": 9000}]}, format="json")
        self.assertGreater(time.monotonic() - began, 0.5)
        self.assertEqual(r.status_code, 400, r.content.decode())
        self.assertIn("U700", r.json()["detail"])
        self.assertEqual(set(TradeUnit.objects.values_list("price", flat=True)), {D("15000")})     # 整批沒動(另一台也是)

    def test_the_counter_sale_waits_and_then_sees_the_unit_was_just_ordered(self):
        # 先有一張單的一行指著這一台但沒有訂著(不出過);另一邊鎖著那一台、把那一行改成訂著(= 剛被同行訂走)
        got = self.buy_unit(self.b, self.one)
        line = TradeOrderLine.objects.get()
        TradeOrderLine.objects.filter(pk=line.pk).update(holding=False)
        began = self.meanwhile([(self.LOCK_SERIAL, [self.one.id]),
                                ("UPDATE trade_tradeorderline SET holding = true WHERE id = %s", [line.id])])
        r = self.a.clerk.post("/api/v1/sales-orders/", {
            "customer": self.a.customer.id, "warehouse": self.wh1.id, "tax_method": "untaxed",
            "items": [{"product": self.used.id, "qty": 1, "unit_price": "16000", "serial_ids": [self.one.id]}],
            "payments": [{"method": "cash", "amount": "16000"}]}, format="json")
        self.assertGreater(time.monotonic() - began, 0.5)
        self.assertEqual((r.status_code, r.json().get("code")), (400, "trade_hold"), r.content.decode())
        self.one.refresh_from_db()
        self.assertEqual((self.one.status, got["status"]), ("in_stock", "已接單"))

    def test_taking_a_unit_back_waits_for_the_order_and_does_not_cancel_twice(self):
        # 另一邊(買家)鎖著那張單、自己取消了
        self.buy_unit(self.b, self.one)
        order, line = TradeOrder.objects.get(), TradeOrderLine.objects.get()
        began = self.meanwhile([
            ("SELECT 1 FROM trade_tradeorder WHERE id = %s FOR UPDATE", [order.id]),
            ("UPDATE trade_tradeorderline SET holding = false, cancelled_qty = 1 WHERE id = %s", [line.id]),
            ("UPDATE trade_tradeorder SET status = 'cancelled', closed_by_buyer = true, close_reason = '買家取消' WHERE id = %s", [order.id])])
        r = self.a.clerk.post("/api/v1/sales-orders/", {
            "customer": self.a.customer.id, "warehouse": self.wh1.id, "tax_method": "untaxed",
            "items": [{"product": self.used.id, "qty": 1, "unit_price": "16000", "serial_ids": [self.one.id]}],
            "payments": [{"method": "cash", "amount": "16000"}], "release_trade_units": [self.one.id]}, format="json")
        self.assertGreater(time.monotonic() - began, 0.5)
        self.assertEqual(r.status_code, 201, r.content.decode())
        order.refresh_from_db()
        line.refresh_from_db()
        self.assertEqual((line.cancelled_qty, order.close_reason, order.closed_by_buyer), (1, "買家取消", True))

    def test_shipping_waits_for_the_unit_without_holding_the_order(self):
        """出貨先鎖要出的那幾台、才鎖批發單。等那一台的時候如果已經握著批發單,就會跟「門市抽回這一台」互相等(死結)。"""
        got = self.buy_unit(self.b, self.one)
        order, line = TradeOrder.objects.get(), TradeOrderLine.objects.get()
        began = self.meanwhile([(self.LOCK_SERIAL, [self.one.id]),
                                ("UPDATE inventory_productserial SET status = 'sold', warehouse_id = NULL WHERE id = %s", [self.one.id])],
                               hold=1.5)
        result = {}

        def ship():
            try:
                result["r"] = self.a.admin.post(f"{T}orders/{order.id}/ship/", {
                    "request_key": "ship-race-001", "warehouse": self.wh1.id,
                    "lines": [{"line": line.id, "qty": 1, "serials": [self.one.id]}]}, format="json")
            finally:
                connections.close_all()

        t = threading.Thread(target=ship)
        t.start()
        time.sleep(0.6)                      # 出貨這時候應該卡在等那一台
        third = connections.create_connection("default")
        try:
            third.ensure_connection()
            third.set_autocommit(False)
            with third.cursor() as cur:
                try:
                    cur.execute("SELECT 1 FROM trade_tradeorder WHERE id = %s FOR UPDATE NOWAIT", [order.id])
                    order_was_free = True
                except OperationalError:
                    order_was_free = False
            third.rollback()
        finally:
            third.close()
        t.join(10)
        self.assertGreater(time.monotonic() - began, 1.0)
        self.assertTrue(order_was_free, "出貨在等序號的時候已經鎖住批發單了")
        self.assertEqual(result["r"].status_code, 400, result["r"].content.decode())
        self.assertIn("不可銷貨", result["r"].json()["detail"])
        self.assertEqual((TradeShipment.objects.count(), TradeOrderLine.objects.get().holding, got["status"]), (0, True, "已接單"))
