"""廠商叫貨(第二步:到貨變進貨單)。假的膜總裁在 tests.py(`FakeVendor`);這裡不打真的。

owner 2026-10-10 定的三件事各有測試:成本 = 實際付出去的金額(不除 1.05)、貨到付款記現金、運費照門市的設定算不算進成本。
"""
import threading
import time
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.db import connections
from django.test import SimpleTestCase, TransactionTestCase

from apps.backup.tests.factory import Company
from apps.catalog.models import Product, SupplierProduct
from apps.inventory.models import StockBalance
from apps.parties.models import Supplier
from apps.purchasing.models import PurchaseOrder
from apps.purchasing import services as purchasing_services

from . import moceo, receiving, services
from .models import VendorLink, VendorOrder, VendorReceipt, VendorReceiptItem
from .tests import KEY, LINKS, ORDERS, SYNC, FakeVendor, _Shop

D = Decimal
ADOPT = "/api/v1/vendor-orders/adopt/"
G02, G02_FREE, G01 = "G02||p", "G02||r", "G01||p"
BOX_901, BOX_902 = "M01|901|p", "M01|902|p"


class _Arrival(_Shop):
    """甲湳雅店叫了 G02 兩包(50 片 × 150 = 7,500)。店裡有兩個按數量管的膜。"""

    lines = None
    link_extra = {}

    def setUp(self):
        super().setUp()
        self.assertEqual(self.link(**self.link_extra).status_code, 200)
        self.film = self.product("甲 高透亮面保護貼")
        self.film2 = self.product("甲 D3O 保護貼")
        self.o = self.order(lines=self.lines).json()
        self.no = self.o["vendor_order_no"]

    def product(self, name, **extra):
        return Product.objects.create(tenant=self.t, category=self.c.cat_case, name=name,
                                      **{"requires_serial": False, "list_price": 390, **extra})

    def plan(self, order=None, client=None):
        return (client or self.clerk).get(f"{ORDERS}{(order or self.o)['id']}/receiving/")

    def take(self, lines, key="recv-0001", order=None, client=None, **extra):
        body = {"request_key": key, "lines": lines, **extra}
        return (client or self.clerk).post(f"{ORDERS}{(order or self.o)['id']}/receive/", body, format="json")

    def line(self, key=G02, qty=50, product=None):
        return {"key": key, "qty": qty, "product": (product or self.film).id}

    def stock(self, product=None, warehouse=None):
        row = StockBalance.objects.filter(tenant=self.t, product=product or self.film,
                                          warehouse=warehouse or self.wh1).first()
        return (row.qty, row.weighted_avg_cost) if row else (0, D("0"))

    def assertNothingReceived(self):
        self.assertEqual((PurchaseOrder.objects.filter(tenant=self.t).count(), VendorReceipt.objects.count(),
                          SupplierProduct.objects.count(), self.stock()[0]), (0, 0, 0, 0))


class PlanTests(_Arrival):
    lines = [{"key": "G02", "packs": 2}, {"key": "M01#901", "packs": 1}]

    def test_it_shows_what_was_ordered_shipped_and_already_received(self):
        self.vendor.ship(self.no, G02=25)
        self.vendor.find(self.no).update(status="部分出貨", logistics_status="已取件", tracking_no="SF123")
        self.vendor.calls.clear()
        before = VendorOrder.objects.get(pk=self.o["id"]).updated_at
        r = self.plan()
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.assertNoKeyIn(r)
        got = r.json()
        self.assertEqual((got["vendor_order_no"], got["vendor_status"], got["vendor_logistics_status"],
                          got["vendor_tracking_no"]), (self.no, "部分出貨", "已取件", "SF123"))
        rows = {row["key"]: row for row in got["lines"]}
        self.assertEqual(set(rows), {G02, BOX_901})
        film = rows[G02]
        self.assertEqual((film["qty"], film["shipped_qty"], film["received_qty"], film["remaining_qty"],
                          film["suggested_qty"], film["unit_price"], film["product"], film["is_reissue"]),
                         (50, 25, 0, 50, 25, "150.00", None, False))
        box = rows[BOX_901]
        self.assertEqual((box["spec_id"], box["spec_label"], box["qty"], box["suggested_qty"], box["unit_price"]),
                         (901, "K43 iPhone 15 Pro", 5, 0, "75.00"))
        self.assertEqual((got["shipping_fee"], got["freight_into_cost"], got["freight_left"], got["supplier"]),
                         ("0.00", True, "0.00", None))
        # 只是看:沒有寫任何東西、只跟廠商讀
        self.assertEqual([c[:2] for c in self.vendor.calls], [("GET", f"/orders/{self.no}")])
        self.assertEqual(VendorOrder.objects.get(pk=self.o["id"]).updated_at, before)
        self.assertNothingReceived()

    def test_the_suggestion_is_what_the_vendor_shipped_and_the_store_has_not_taken_in(self):
        for qty, shipped, received, want in [(50, 0, 0, 0), (50, 25, 0, 25), (50, 50, 0, 50), (50, 50, 25, 25),
                                             (50, 25, 25, 0), (50, 25, 40, 0), (50, 80, 0, 50), (50, 50, 60, 0)]:
            self.assertEqual(receiving.suggested_qty(qty, shipped, received), want, (qty, shipped, received))

    def test_a_reply_that_cannot_be_understood_is_not_received(self):
        """少算一行,庫存就少一行而且沒有人會發現:有一行看不懂就整張不給入。"""
        good = FakeVendor.line("G02", 50)
        for bad in [{**good, "qty": "50"}, {**good, "qty": 0}, {**good, "sku": ""}, {**good, "unit_price": None},
                    {**good, "unit_price": -1}, {**good, "spec_id": "901"}, {**good, "qty": True}, "G02"]:
            with self.assertRaises(services.VendorError, msg=bad):
                receiving.lines_of([good, bad])
        for nothing in (None, [], {}):
            with self.assertRaises(services.VendorError):
                receiving.lines_of(nothing)
        self.vendor.find(self.no)["items"][0]["qty"] = "50"
        r = self.plan()
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "膜總裁回的明細有一行看不懂,先不要入庫"))
        r = self.take([self.line()])
        self.assertEqual(r.status_code, 400, r.content.decode())
        self.assertNothingReceived()

    def test_the_same_item_on_several_vendor_lines_is_one_line(self):
        self.vendor.find(self.no)["items"] += [FakeVendor.line("G02", 25, shipped=25, drift=-30),
                                               FakeVendor.line("G02", 5, shipped=5, free=True)]
        rows = {row["key"]: row for row in self.plan().json()["lines"]}
        # 50 × 150 + 25 × 120 = 10,500 / 75 = 140;免費補發的自己一行
        self.assertEqual((rows[G02]["qty"], rows[G02]["shipped_qty"], rows[G02]["unit_price"]), (75, 25, "140.00"))
        self.assertEqual((rows[G02_FREE]["qty"], rows[G02_FREE]["unit_price"], rows[G02_FREE]["is_reissue"]),
                         (5, "0.00", True))


class ReceiveTests(_Arrival):
    def test_it_becomes_a_purchase_order_at_the_amount_actually_paid(self):
        self.vendor.find(self.no).update(status="備貨中", tracking_no="SF777")
        r = self.take([self.line()])          # 廠商還沒按出貨也可以入(只提醒不擋:貨已經在店裡了)
        self.assertEqual(r.status_code, 201, r.content.decode())
        self.assertNoKeyIn(r)
        self.assertEqual((r.json()["order"]["vendor_status"], r.json()["order"]["vendor_tracking_no"]), ("備貨中", "SF777"))
        po = PurchaseOrder.objects.get(tenant=self.t)
        item = po.items.get()
        # 含稅 150 就是成本 150:不除 1.05(142.86)、不另外算稅
        self.assertEqual((po.tax_method, po.subtotal, po.tax_amount, po.total_cost), ("untaxed", 7500, 0, 7500))
        self.assertEqual((item.product_id, item.qty, item.billed_qty, item.unit_price, item.unit_landed_cost, item.amount),
                         (self.film.id, 50, 50, D("150.00"), D("150.00"), 7500))
        self.assertEqual(self.stock(), (50, D("150.00")))
        self.assertEqual((po.warehouse_id, po.supplier.name, po.payment_method, po.created_by, po.is_void),
                         (self.wh1.id, "膜總裁", None, self.c.clerk_user, False))
        self.assertIn(self.no, po.note)
        # 供應商自動建一筆、記在這家門市的串接上;下次同一筆
        self.assertEqual(VendorLink.objects.get().supplier, po.supplier)
        self.assertEqual(Supplier.objects.filter(tenant=self.t, name="膜總裁").count(), 1)
        receipt = r.json()["order"]["receipts"]
        self.assertEqual([(x["purchase_order"], x["purchase_order_no"], x["is_void"], x["qty"], x["total_cost"], x["freight"],
                           x["created_by"]) for x in receipt],
                         [(po.id, po.no, False, 50, "7500.00", "0.00", "a-clerk")])
        row = VendorReceiptItem.objects.get()
        self.assertEqual((row.sku, row.spec_id, row.is_reissue, row.qty, row.unit_price, row.product_id),
                         ("G02", None, False, 50, D("150.00"), self.film.id))

    def test_cash_on_delivery_is_recorded_as_paid_in_cash(self):
        o = self.order(key="draft-0002", payment_method="貨到付款").json()
        self.assertEqual(self.take([self.line()], order=o).status_code, 201)
        self.assertEqual(PurchaseOrder.objects.get(tenant=self.t).payment_method, self.c.cash)

    def test_the_payment_method_is_the_one_the_vendor_has_now(self):
        """叫貨時是月結、廠商事後改成貨到付款:付的是現金,進貨單要記得到(複審 2026-10-10)。反過來也一樣。"""
        self.vendor.find(self.no)["payment_method"] = "貨到付款"
        self.assertEqual((self.o["payment_method"], self.plan().json()["payment_method"]), ("月結", "貨到付款"))
        r = self.take([self.line(qty=20)])
        self.assertEqual((r.status_code, r.json()["order"]["payment_method"]), (201, "貨到付款"))     # 叫貨紀錄跟著寫現在的
        self.assertEqual(PurchaseOrder.objects.get(tenant=self.t).payment_method, self.c.cash)
        # 廠商沒有回這一格:用叫貨單上記的(剛剛寫回來的貨到付款)
        self.vendor.find(self.no)["payment_method"] = None
        self.assertEqual(self.take([self.line(qty=5)], key="recv-0002").status_code, 201)
        self.assertEqual(PurchaseOrder.objects.filter(tenant=self.t).order_by("id").last().payment_method, self.c.cash)
        # 反過來:叫貨時貨到付款、廠商改成月結 → 不記現金
        other = self.order(key="draft-0002", payment_method="貨到付款").json()
        self.vendor.find(other["vendor_order_no"])["payment_method"] = "月結"
        r = self.take([self.line(qty=20)], key="recv-0003", order=other)
        self.assertEqual((r.status_code, r.json()["order"]["payment_method"]), (201, "月結"))
        self.assertIsNone(PurchaseOrder.objects.filter(tenant=self.t).order_by("id").last().payment_method)

    def test_the_price_is_what_the_vendor_says_now_and_the_screen_cannot_set_it(self):
        item = self.vendor.find(self.no)["items"][0]
        item.update(subtotal=7000)          # 廠商事後整行少算 500:以這一行實際要付的為準(7,000 / 50 = 140)
        r = self.take([{**self.line(), "unit_price": "1", "amount": "1", "billed_qty": 0}])
        self.assertEqual(r.status_code, 201, r.content.decode())
        po = PurchaseOrder.objects.get(tenant=self.t)
        self.assertEqual((po.total_cost, po.items.get().unit_price, po.items.get().billed_qty), (7000, D("140.00"), 50))
        self.assertEqual(self.stock(), (50, D("140.00")))

    def test_the_same_request_twice_is_one_receipt(self):
        first = self.take([self.line(qty=20)])
        again = self.take([self.line(qty=20)])
        self.assertEqual((first.status_code, again.status_code), (201, 200))
        self.assertEqual(first.json()["receipt"], again.json()["receipt"])
        self.assertEqual((PurchaseOrder.objects.filter(tenant=self.t).count(), self.stock()[0]), (1, 20))
        # 那把鑰匙是這張叫貨單的:拿去別張用不算數
        other = self.order(key="draft-0002").json()
        r = self.take([self.line(qty=20)], order=other)
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "這把鑰匙是另一張叫貨單的入庫"))
        r = self.take([self.line(qty=1)], key="x")
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "這一次入庫的編號不對,請重新整理頁面再試"))
        self.assertEqual(self.stock()[0], 20)

    def test_it_can_arrive_in_parts_but_never_more_than_was_ordered(self):
        self.vendor.ship(self.no, G02=25)
        self.assertEqual(self.take([self.line(qty=25)]).status_code, 201)
        row = self.plan().json()["lines"][0]
        self.assertEqual((row["received_qty"], row["remaining_qty"], row["suggested_qty"]), (25, 25, 0))
        self.vendor.ship(self.no)
        self.assertEqual(self.plan().json()["lines"][0]["suggested_qty"], 25)
        r = self.take([self.line(qty=26)], key="recv-0002")
        self.assertEqual((r.status_code, r.json()["detail"]),
                         (400, "「高透亮面」最多還能入 25 個(叫 50、已經入 25)"))
        self.assertEqual(self.take([self.line(qty=25)], key="recv-0002").status_code, 201)
        r = self.take([self.line(qty=1)], key="recv-0003")
        self.assertEqual((r.status_code, "最多還能入 0 個" in r.json()["detail"]), (400, True))
        self.assertEqual((self.stock()[0], PurchaseOrder.objects.filter(tenant=self.t).count()), (50, 2))
        self.assertEqual([x["qty"] for x in self.clerk.get(f"{ORDERS}{self.o['id']}/").json()["receipts"]], [25, 25])

    def test_a_voided_purchase_order_makes_those_pieces_open_again(self):
        first = self.take([self.line()]).json()["order"]["receipts"][0]
        r = self.admin.post(f"/api/v1/purchase-orders/{first['purchase_order']}/void/")
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.assertEqual(self.stock()[0], 0)
        row = self.plan().json()["lines"][0]
        self.assertEqual((row["received_qty"], row["remaining_qty"]), (0, 50))
        self.assertEqual(self.take([self.line()], key="recv-0002").status_code, 201)
        self.assertEqual(self.stock()[0], 50)
        self.assertEqual([(x["is_void"], x["qty"]) for x in self.clerk.get(f"{ORDERS}{self.o['id']}/").json()["receipts"]],
                         [(True, 50), (False, 50)])

    def test_free_replacement_pieces_come_in_but_cost_nothing(self):
        self.vendor.find(self.no)["items"].append(FakeVendor.line("G02", 5, shipped=5, free=True))
        r = self.take([self.line(), self.line(G02_FREE, 5)])
        self.assertEqual(r.status_code, 201, r.content.decode())
        po = PurchaseOrder.objects.get(tenant=self.t)
        self.assertEqual([(i.qty, i.billed_qty, i.unit_price, i.amount) for i in po.items.all()],
                         [(50, 50, D("150.00"), 7500), (5, 0, D("0.00"), 0)])
        self.assertEqual(po.total_cost, 7500)
        self.assertEqual(self.stock(), (55, D("136.36")))        # 7,500 / 55
        self.assertEqual(sorted(VendorReceiptItem.objects.values_list("is_reissue", "qty")), [(False, 50), (True, 5)])
        # 兩種各算各的:免費的入過了,付錢的還可以再入
        r = self.take([self.line(G02_FREE, 1)], key="recv-0002")
        self.assertEqual((r.status_code, "最多還能入 0 個" in r.json()["detail"]), (400, True))

    def test_what_is_sent_must_be_complete(self):
        for nothing in (None, [], {}):
            r = self.take(nothing)
            self.assertEqual((r.status_code, r.json()["detail"]), (400, "這一次沒有要入庫的東西"), nothing)
        for lines in ([{"key": G02, "qty": 0, "product": self.film.id}], [{"key": G02, "qty": 5}],
                      [{"key": G02, "qty": "5", "product": self.film.id}], [{"qty": 5, "product": self.film.id}],
                      [self.line(qty=5), self.line(qty=5)], ["G02"], [{"key": G02, "qty": True, "product": self.film.id}]):
            r = self.take(lines)
            self.assertEqual(r.status_code, 400, (lines, r.content.decode()))
        r = self.take([self.line("G99||p", 5)])
        self.assertEqual((r.status_code, "現在沒有這一行" in r.json()["detail"]), (400, True))
        self.assertNothingReceived()

    def test_only_a_plain_counted_product_of_this_company_takes_the_goods(self):
        other = Company("b", "乙通訊行", "乙")
        for product, word in [(self.c.phone, "只能入到按數量管的一般商品"), (self.c.retired, "已經停用"),
                              (other.case, "對到的商品找不到"),
                              (self.product("甲 中古", is_secondhand=True), "只能入到按數量管的一般商品"),
                              (self.product("甲 手續費", is_virtual=True), "只能入到按數量管的一般商品")]:
            r = self.take([self.line(product=product)])
            self.assertEqual((r.status_code, word in r.json()["detail"]), (400, True), r.content.decode())
        self.assertNothingReceived()

    def test_one_bad_line_stops_the_whole_receipt(self):
        o = self.order(key="draft-0002", lines=[{"key": "G02", "packs": 1}, {"key": "G01", "packs": 1}]).json()
        r = self.take([self.line(qty=25), self.line(G01, 11, self.film2)], order=o)
        self.assertEqual(r.status_code, 400, r.content.decode())
        self.assertNothingReceived()

    def test_the_vendor_has_to_answer_first(self):
        self.vendor.read_down = True
        for r in (self.plan(), self.take([self.line()])):
            self.assertEqual((r.status_code, r.json()["detail"]), (400, "連不到膜總裁,請稍後再試"))
        self.vendor.read_down = False
        self.admin.post(f"{LINKS}{self.wh1.id}/remove-key/")
        r = self.take([self.line()])
        self.assertEqual((r.status_code, "還沒有設定膜總裁的金鑰" in r.json()["detail"]), (400, True))
        self.assertNothingReceived()

    def test_an_order_that_is_not_certain_cannot_be_received(self):
        self.vendor.script = ["lost"]
        unsure = self.order(key="draft-0002").json()
        self.assertEqual(unsure["state"], "unknown")
        for r in (self.plan(unsure), self.take([self.line()], order=unsure)):
            self.assertEqual((r.status_code, r.json()["detail"]), (400, "這張叫貨單還沒有確定成立,不能入庫"))
        self.assertNothingReceived()

    def test_who_may_receive_and_for_which_store(self):
        self.link(store=self.wh2)
        far = self.order(client=self.admin, store=self.wh2, key="draft-wh2a").json()
        # 鎖在自己門市的店員:別家門市的叫貨單當作不存在
        for r in (self.plan(far), self.take([self.line()], order=far),
                  self.clerk.post(f"{ORDERS}{far['id']}/issue/", {"note": "x"}, format="json")):
            self.assertEqual(r.status_code, 404, r.content.decode())
        self.assertEqual(self.clerk.post(ADOPT, {"warehouse": self.wh2.id, "order_no": "MO-1"}, format="json").status_code, 403)
        # 別家公司
        other = Company("b", "乙通訊行", "乙")
        for r in (self.plan(client=other.admin), self.take([self.line()], client=other.admin)):
            self.assertEqual(r.status_code, 404)
        # 「進貨入庫」被關掉:四支都不行(看得到叫貨單,但入不了庫)
        self.turn_off("purchase")
        for r in (self.plan(), self.take([self.line()]),
                  self.clerk.post(ADOPT, {"warehouse": self.wh1.id, "order_no": self.no}, format="json"),
                  self.clerk.post(f"{ORDERS}{self.o['id']}/issue/", {"note": "x"}, format="json")):
            self.assertEqual(r.status_code, 403, r.content.decode())
        self.assertEqual(self.clerk.get(f"{ORDERS}{self.o['id']}/").status_code, 200)
        self.assertNothingReceived()
        # 「廠商叫貨」被關掉、「進貨入庫」開著:照樣可以入庫(收貨的人不一定是叫貨的人)
        self.turn_off("vendor_order")
        self.assertEqual(self.take([self.line()]).status_code, 201)
        # 管理員入別家門市的:進的是那一家的庫存
        self.assertEqual(self.take([self.line()], key="recv-wh2a", order=far, client=self.admin).status_code, 201)
        self.assertEqual((self.stock()[0], self.stock(warehouse=self.wh2)[0]), (50, 50))


class FreightTests(_Arrival):
    lines = [{"key": "G02", "packs": 2}, {"key": "G01", "packs": 1}]          # 7,500 + 2,800

    def setUp(self):
        _Shop.setUp(self)
        self.vendor.shipping_fee = 200
        self.assertEqual(self.link(**self.link_extra).status_code, 200)
        self.film, self.film2 = self.product("甲 高透亮面保護貼"), self.product("甲 D3O 保護貼")
        self.o = self.order(lines=self.lines).json()
        self.no = self.o["vendor_order_no"]

    def both(self):
        return [self.line(), self.line(G01, 10, self.film2)]

    def test_freight_goes_into_cost_split_by_what_each_line_cost(self):
        self.assertEqual(self.plan().json()["freight_left"], "200.00")
        r = self.take(self.both())
        self.assertEqual(r.status_code, 201, r.content.decode())
        po = PurchaseOrder.objects.get(tenant=self.t)
        # 200 照貨款比例:G02 拿 146(7,500 / 10,300),剩下的 54 給 G01 —— 加起來一定是 200
        self.assertEqual({i.product_id: (i.unit_price, i.amount) for i in po.items.all()},
                         {self.film.id: (D("152.92"), 7646), self.film2.id: (D("285.40"), 2854)})
        self.assertEqual((po.total_cost, VendorReceipt.objects.get().freight), (10500, 200))
        self.assertEqual((self.stock(), self.stock(self.film2)), ((50, D("152.92")), (10, D("285.40"))))
        self.assertEqual(VendorReceiptItem.objects.get(sku="G02").unit_price, D("150.00"))     # 這裡記的是廠商的單價
        self.assertEqual(self.plan().json()["freight_left"], "0.00")

    def test_in_parts_each_receipt_carries_its_share_and_the_last_takes_the_rest(self):
        self.assertEqual(self.take([self.line()]).status_code, 201)
        self.assertEqual((VendorReceipt.objects.get().freight, self.stock(), self.plan().json()["freight_left"]),
                         (146, (50, D("152.92")), "54.00"))
        self.assertEqual(self.take([self.line(G01, 4, self.film2)], key="recv-0002").status_code, 201)
        # 4 / 10 的 G01:200 × 1,120 / 10,300 = 21.7 → 22
        self.assertEqual(VendorReceipt.objects.order_by("id").last().freight, 22)
        self.assertEqual(self.take([self.line(G01, 6, self.film2)], key="recv-0003").status_code, 201)
        self.assertEqual([r.freight for r in VendorReceipt.objects.order_by("id")], [146, 22, 32])
        self.assertEqual(sum(po.total_cost for po in PurchaseOrder.objects.filter(tenant=self.t)), 10500)

    def test_a_voided_receipt_gives_its_freight_back(self):
        first = self.take(self.both()).json()["order"]["receipts"][0]
        self.assertEqual(self.admin.post(f"/api/v1/purchase-orders/{first['purchase_order']}/void/").status_code, 200)
        self.assertEqual(self.plan().json()["freight_left"], "200.00")
        self.assertEqual(self.take(self.both(), key="recv-0002").status_code, 201)
        self.assertEqual(VendorReceipt.objects.order_by("id").last().freight, 200)

    def test_free_pieces_carry_no_freight(self):
        self.vendor.find(self.no)["items"].append(FakeVendor.line("G02", 5, free=True))
        self.assertEqual(self.take([self.line(G02_FREE, 5)]).status_code, 201)
        self.assertEqual((VendorReceipt.objects.get().freight, self.stock()), (0, (5, D("0.00"))))
        self.assertEqual(self.plan().json()["freight_left"], "200.00")

    def test_a_store_can_keep_freight_out_of_cost(self):
        r = self.link(key="", freight_into_cost=False)
        self.assertEqual((r.status_code, r.json()["freight_into_cost"]), (200, False))
        self.assertEqual(self.plan().json()["freight_into_cost"], False)
        self.assertEqual(self.take(self.both()).status_code, 201)
        po = PurchaseOrder.objects.get(tenant=self.t)
        self.assertEqual((po.total_cost, VendorReceipt.objects.get().freight, self.stock()), (10300, 0, (50, D("150.00"))))
        self.assertIn("運費 200 沒有算進成本", po.note)


class FreightRuleTests(SimpleTestCase):
    """運費怎麼分,直接測那兩個算法(不經過資料庫)。"""

    ON, OFF = SimpleNamespace(freight_into_cost=True), SimpleNamespace(freight_into_cost=False)

    @staticmethod
    def line(sku, qty, amount, free=False):
        return receiving.Line(sku=sku, spec_id=None, is_reissue=free, qty=qty, amount=D(amount))

    def share(self, lines, fee, spent, got, now, link=None):
        picked = [(line, now[line.sku]) for line in lines if line.sku in now]
        return receiving._freight_share(link or self.ON, D(fee), D(spent), lines, {receiving.line_key(k, None, False): v
                                                                                 for k, v in got.items()}, picked)

    def test_each_receipt_takes_its_share_and_the_one_that_completes_the_order_takes_what_is_left(self):
        a, b = self.line("A", 50, 7500), self.line("B", 10, 2800)
        self.assertEqual(self.share([a, b], 200, 0, {}, {"A": 50, "B": 10}), 200)
        self.assertEqual(self.share([a, b], 200, 0, {}, {"A": 50}), 146)
        # 四捨五入掉的零頭由最後一次補回來:五次各 29(145)+ 最後一次拿剩下的 55,不是照比例的 54
        self.assertEqual(self.share([a, b], 200, 0, {}, {"A": 10}), 29)
        self.assertEqual(self.share([a, b], 200, 145, {"A": 50}, {"B": 10}), 55)
        self.assertEqual(self.share([a, b], 200, 145, {"A": 50}, {"B": 9}), 49)          # 還沒入完:照比例

    def test_a_share_is_never_more_than_what_is_left(self):
        lines = [self.line("A", 1, 100), self.line("B", 1, 100), self.line("C", 1, 100), self.line("D", 1, 1)]
        # 5 元運費、三行各 1.66 → 各進位成 2:第三次只剩 1,不能再拿 2(加起來會比運費多)
        self.assertEqual(self.share(lines, 5, 0, {}, {"A": 1}), 2)
        self.assertEqual(self.share(lines, 5, 4, {"A": 1, "B": 1}, {"C": 1}), 1)
        self.assertEqual(self.share(lines, 5, 5, {"A": 1, "B": 1, "C": 1}, {"D": 1}), 0)
        # 廠商事後把運費改少了、已經算進去的比現在的運費還多:不再算,也不倒扣
        self.assertEqual(self.share(lines, 3, 4, {"A": 1, "B": 1}, {"C": 1, "D": 1}), 0)

    def test_nothing_is_added_when_the_store_says_no_or_nothing_was_paid_for(self):
        a, free = self.line("A", 50, 7500), self.line("A", 5, 0, free=True)
        self.assertEqual(self.share([a], 200, 0, {}, {"A": 50}, link=self.OFF), 0)
        self.assertEqual(self.share([a], 0, 0, {}, {"A": 50}), 0)
        self.assertEqual(receiving._freight_share(self.ON, D(200), D(0), [a, free], {}, [(free, 5)]), 0)
        # 付錢的都入完了、最後一次只剩免費補發的:剩下的零頭不掛在它身上(沒有可以加成本的行)
        self.assertEqual(receiving._freight_share(self.ON, D(200), D(199), [a, free], {a.key: 50}, [(free, 5)]), 0)

    def test_the_share_is_split_across_lines_in_whole_dollars_and_always_adds_up(self):
        a, b, c = self.line("A", 10, 1000), self.line("B", 10, 1000), self.line("C", 10, 1000)
        free = self.line("A", 5, 0, free=True)
        self.assertEqual(receiving._spread(D(100), [(a, 10), (b, 10), (c, 10), (free, 5)]),
                         {a.key: 33, b.key: 33, c.key: 34})          # 最後一行拿剩下的;免費的不分
        self.assertEqual(receiving._spread(D(0), [(a, 10), (b, 10)]), {a.key: 0, b.key: 0})
        self.assertEqual(receiving._spread(D(1), [(a, 10), (b, 10), (c, 10)]), {a.key: 0, b.key: 0, c.key: 1})
        self.assertEqual(receiving._spread(D(50), [(free, 5)]), {})


class MappingTests(_Arrival):
    lines = [{"key": "G02", "packs": 1}, {"key": "M01#901", "packs": 1}, {"key": "M01#902", "packs": 1}]

    def test_the_first_receiver_picks_the_product_and_the_next_time_it_is_already_there(self):
        self.assertIsNone(self.plan().json()["lines"][0]["product"])
        self.assertEqual(self.take([self.line(qty=10)]).status_code, 201)
        row = SupplierProduct.objects.get()
        self.assertEqual((row.product_id, row.supplier.name, row.platform, row.vendor_sku, row.source_name, row.pack_qty,
                          row.confirmed_by, row.is_active),
                         (self.film.id, "膜總裁", "moceo", "G02", "高透亮面", 25, self.c.clerk_user, True))
        rows = {x["key"]: x for x in self.plan().json()["lines"]}
        self.assertEqual(rows[G02]["product"], {"id": self.film.id, "sku": self.film.sku, "name": self.film.name,
                                                "is_active": True})
        self.assertIsNone(rows[BOX_901]["product"])
        # 另一張叫貨單的同一個料號:也帶得出來
        again = self.order(key="draft-0002").json()
        self.assertEqual(self.plan(again).json()["lines"][0]["product"]["id"], self.film.id)

    def test_each_spec_of_one_item_is_its_own_product(self):
        r = self.take([self.line(BOX_901, 5, self.film), self.line(BOX_902, 5, self.film2)])
        self.assertEqual(r.status_code, 201, r.content.decode())
        self.assertEqual(dict(SupplierProduct.objects.values_list("vendor_sku", "product_id")),
                         {"M01#spec901": self.film.id, "M01#spec902": self.film2.id})
        self.assertEqual((self.stock(self.film), self.stock(self.film2)), ((5, D("75.00")), (5, D("70.00"))))
        rows = {x["key"]: x for x in self.plan().json()["lines"]}
        self.assertEqual((rows[BOX_901]["product"]["id"], rows[BOX_902]["product"]["id"], rows[G02]["product"]),
                         (self.film.id, self.film2.id, None))

    def test_once_set_a_clerk_cannot_point_it_elsewhere_but_a_manager_can(self):
        self.assertEqual(self.take([self.line(qty=10)]).status_code, 201)
        r = self.take([self.line(qty=5, product=self.film2)], key="recv-0002")
        self.assertEqual((r.status_code, r.json()["detail"]),
                         (400, f"「高透亮面」已經對到「{self.film.name}」,要改請管理員"))
        self.assertEqual((self.stock(self.film2)[0], SupplierProduct.objects.get().product_id), (0, self.film.id))
        r = self.take([self.line(qty=5, product=self.film2)], key="recv-0002", client=self.admin)
        self.assertEqual(r.status_code, 201, r.content.decode())
        self.assertEqual(sorted(SupplierProduct.objects.values_list("product_id", "is_active")),
                         sorted([(self.film.id, False), (self.film2.id, True)]))
        self.assertEqual((self.stock(self.film)[0], self.stock(self.film2)[0]), (10, 5))
        self.assertEqual(self.plan().json()["lines"][0]["product"]["id"], self.film2.id)

    def test_a_name_the_store_already_taught_for_this_supplier_is_respected(self):
        """別名表先認領的(拍照入庫教過的):一樣算數,而且這裡改不了它(要到那個商品把叫法拿掉)。"""
        from apps.identity.models import ProductAlias
        from apps.identity.normalize import alias_key

        supplier = Supplier.objects.create(tenant=self.t, name="膜總裁")
        ProductAlias.objects.create(tenant=self.t, product=self.film, supplier=supplier, kind=ProductAlias.Kind.VENDOR_SKU,
                                    value="G02", normalized_value=alias_key("G02"), verified=True)
        self.assertEqual(self.link(key="", supplier=supplier.id).status_code, 200)
        self.assertEqual(self.plan().json()["lines"][0]["product"]["id"], self.film.id)
        r = self.take([self.line(qty=5, product=self.film2)], client=self.admin)
        self.assertEqual((r.status_code, "在商品的其他叫法裡已經對到" in r.json()["detail"]), (400, True), r.content.decode())
        self.assertEqual(self.take([self.line(qty=5)]).status_code, 201)
        self.assertEqual(SupplierProduct.objects.count(), 0)


class LinkSettingTests(_Arrival):
    def test_the_supplier_and_the_freight_rule_are_set_by_a_manager(self):
        row = self.admin.get(LINKS).json()["results"][0]
        self.assertEqual((row["supplier"], row["supplier_name"], row["freight_into_cost"]), (None, "", True))
        r = self.link(key="", supplier=self.c.supplier.id, freight_into_cost=False)
        self.assertEqual((r.status_code, r.json()["supplier"], r.json()["supplier_name"], r.json()["freight_into_cost"]),
                         (200, self.c.supplier.id, "甲大盤商", False))
        # 沒帶這兩格 = 不動
        self.assertEqual(self.link(key="", ship_name="新收件人").json()["supplier"], self.c.supplier.id)
        self.assertEqual(self.plan().json()["supplier"], {"id": self.c.supplier.id, "name": "甲大盤商"})
        self.assertEqual(self.take([self.line()]).status_code, 201)
        self.assertEqual(PurchaseOrder.objects.get(tenant=self.t).supplier, self.c.supplier)
        self.assertFalse(Supplier.objects.filter(tenant=self.t, name="膜總裁").exists())
        self.assertEqual(self.link(key="", supplier=None).json()["supplier"], None)

    def test_a_supplier_already_named_after_the_vendor_is_used_instead_of_making_another(self):
        mine = Supplier.objects.create(tenant=self.t, name="膜總裁")
        Supplier.objects.create(tenant=Company("b", "乙通訊行", "乙").tenant, name="膜總裁")
        self.assertEqual(self.take([self.line()]).status_code, 201)
        self.assertEqual((PurchaseOrder.objects.get(tenant=self.t).supplier, VendorLink.objects.get().supplier,
                          Supplier.objects.filter(tenant=self.t, name="膜總裁").count()), (mine, mine, 1))

    def test_bad_values_and_other_people(self):
        other = Company("b", "乙通訊行", "乙")
        if not Supplier.objects.filter(pk=1).exists():          # 讓「是」(True)真的有一號可以撞:它不是編號
            Supplier.objects.create(pk=1, tenant=self.t, name="一號供應商")
        self.assertEqual(Supplier.objects.get(pk=1).tenant, self.t)
        for extra in ({"supplier": other.supplier.id}, {"supplier": "x"}, {"supplier": True}, {"supplier": 999999},
                      {"freight_into_cost": "no"}, {"freight_into_cost": 0}):
            r = self.link(key="", **extra)
            self.assertEqual(r.status_code, 400, (extra, r.content.decode()))
        self.assertEqual(self.link(key="", client=self.clerk, freight_into_cost=False).status_code, 403)
        link = VendorLink.objects.get()
        self.assertEqual((link.supplier, link.freight_into_cost), (None, True))


class OutsideOrderTests(_Arrival):
    """電話、LINE、廠商後台代下的單:貨一樣會到,要入得了庫。"""

    def setUp(self):
        super().setUp()
        self.vendor.outside = [{"order_no": "MO-20261008-007", "total_amount": 3850, "shipping_fee": 100, "status": "已出貨",
                                "payment_method": "貨到付款", "ordered_at": "2026-10-08T09:00:00+08:00",
                                "items": [FakeVendor.line("G02", 25, shipped=25)]}]

    def adopt(self, order_no="MO-20261008-007", store=None, client=None):
        return (client or self.clerk).post(ADOPT, {"warehouse": (store or self.wh1).id, "order_no": order_no}, format="json")

    def others(self):
        return [o["order_no"] for o in self.clerk.post(SYNC, {"warehouse": self.wh1.id}, format="json").json()["others"]]

    def test_it_is_taken_in_once_and_then_received_like_any_other(self):
        self.assertEqual(self.others(), ["MO-20261008-007"])
        r = self.adopt()
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.assertNoKeyIn(r)
        got = r.json()
        self.assertEqual((got["source"], got["state"], got["vendor_order_no"], got["warehouse"], got["total_amount"],
                          got["shipping_fee"], got["payment_method"], got["vendor_status"], got["items"], got["is_test"]),
                         ("outside", "placed", "MO-20261008-007", self.wh1.id, "3850.00", "100.00", "貨到付款", "已出貨", [], True))
        self.assertEqual(self.adopt().json()["id"], got["id"])                 # 再認一次是同一筆
        self.assertEqual(VendorOrder.objects.filter(vendor_order_no="MO-20261008-007").count(), 1)
        self.assertEqual(self.others(), [])                                    # 認進來之後不再列在「不是從這裡叫的」
        self.assertIn(got["id"], [o["id"] for o in self.clerk.get(ORDERS).json()["results"]])
        self.assertEqual(self.vendor.posts()[1:], [])                          # 認領不會跟廠商下單
        row = self.plan(got).json()["lines"][0]
        self.assertEqual((row["qty"], row["suggested_qty"], row["unit_price"]), (25, 25, "150.00"))
        self.assertEqual(self.take([self.line(qty=25)], order=got).status_code, 201)
        po = PurchaseOrder.objects.get(tenant=self.t)
        self.assertEqual((po.total_cost, po.payment_method, self.stock()), (3850, self.c.cash, (25, D("154.00"))))

    def test_only_an_order_this_key_can_see_and_only_into_one_store(self):
        self.vendor.calls.clear()
        for bad in ("", "MO 1", "../orders", "MO/1", None, 7, "x" * 41):
            r = self.adopt(bad)
            self.assertEqual((r.status_code, r.json()["detail"]), (400, "單號不對"), bad)
        self.assertEqual(self.vendor.calls, [])          # 樣子不對的單號不會送出去
        r = self.adopt("MO-20260101-999")
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "膜總裁:找不到這張單"))
        self.assertEqual(VendorOrder.objects.count(), 1)
        # 兩家門市共用一把金鑰:一張單只會在一家
        self.link(store=self.wh2)
        self.assertEqual(self.adopt().status_code, 200)
        r = self.adopt(store=self.wh2, client=self.admin)
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "這張單已經在「甲湳雅店」那一家"))
        # 從 POS 叫的那一張拿去「認」:回的就是原來那一張
        self.assertEqual(self.adopt(self.no).json()["id"], self.o["id"])
        self.assertEqual(VendorOrder.objects.count(), 2)

    def test_a_reply_without_lines_is_not_taken_in(self):
        del self.vendor.outside[0]["items"]
        r = self.adopt()
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "膜總裁沒有回這張單的明細,先不要入庫"))
        self.assertEqual(VendorOrder.objects.count(), 1)

    def test_an_uncertain_order_taken_in_this_way_ends_up_as_one_order(self):
        """叫貨時斷線(不確定)→ 有人先從「不是從這裡叫的」把它認進來、入了一半 → 之後按「再送一次」確認是同一張:
        只留一筆,入過的那一半跟著過來(不然還能再入一整張)。"""
        self.vendor.script = ["lost"]
        unsure = self.order(key="draft-0002").json()
        real_no = self.vendor.placed[(KEY, "pos-a-draft-0002")]["order_no"]
        self.assertIn(real_no, self.others())
        twin = self.adopt(real_no).json()
        self.assertEqual(self.take([self.line(qty=20)], order=twin).status_code, 201)
        self.clerk.post(f"{ORDERS}{twin['id']}/issue/", {"note": "少一包"}, format="json")
        r = self.clerk.post(f"{ORDERS}{unsure['id']}/resend/")
        self.assertEqual((r.status_code, r.json()["state"], r.json()["vendor_order_no"]), (200, "placed", real_no))
        self.assertEqual(list(VendorOrder.objects.filter(vendor_order_no=real_no).values_list("id", "source")),
                         [(unsure["id"], "pos")])
        self.assertEqual(([x["qty"] for x in r.json()["receipts"]], r.json()["issue_note"]), ([20], "少一包"))
        row = self.plan(unsure).json()["lines"][0]
        self.assertEqual((row["received_qty"], row["remaining_qty"]), (20, 30))


class IssueNoteTests(_Arrival):
    def test_what_went_wrong_on_arrival_stays_on_the_order(self):
        url = f"{ORDERS}{self.o['id']}/issue/"
        r = self.clerk.post(url, {"note": "  G02 少一包,已經跟膜總裁講  "}, format="json")
        self.assertEqual((r.status_code, r.json()["issue_note"]), (200, "G02 少一包,已經跟膜總裁講"))
        self.assertEqual(self.clerk.post(url, {}, format="json").status_code, 400)
        self.assertEqual(self.clerk.post(url, {"note": "字" * 400}, format="json").json()["issue_note"], "字" * 300)
        # 入庫時一起寫
        r = self.take([self.line(qty=25)], issue_note="另一包送錯規格")
        self.assertEqual((r.status_code, r.json()["order"]["issue_note"]), (201, "另一包送錯規格"))
        self.assertEqual(self.clerk.post(url, {"note": ""}, format="json").json()["issue_note"], "")

    def test_refreshing_progress_does_not_wipe_it(self):
        stale = VendorOrder.objects.get(pk=self.o["id"])          # 別人手上那一份舊的
        self.clerk.post(f"{ORDERS}{self.o['id']}/issue/", {"note": "少一包"}, format="json")
        services._apply(stale, {"status": "已出貨"})
        fresh = VendorOrder.objects.get(pk=self.o["id"])
        self.assertEqual((fresh.issue_note, fresh.vendor_status), ("少一包", "已出貨"))
        self.clerk.post(SYNC, {"warehouse": self.wh1.id}, format="json")
        self.assertEqual(VendorOrder.objects.get(pk=self.o["id"]).issue_note, "少一包")


class TwoPeopleTests(TransactionTestCase):
    """兩個人同時對同一張叫貨單按「確認入庫」(兩台平板、各自的鑰匙):只有一個入得進去。
    沒有先鎖住那張叫貨單再看「已經入了幾個」的話,兩邊都看到 0、都入 50 —— 庫存變成 100。"""

    def setUp(self):
        self.c = Company("a", "甲通訊行", "甲")
        self.vendor = FakeVendor()
        patcher = mock.patch.object(moceo, "_call", self.vendor)
        patcher.start()
        self.addCleanup(patcher.stop)
        # 供應商先指定好:第一次入庫建供應商時另外會鎖住串接那一列,那一把剛好也擋得住兩個人 ——
        # 這裡要測的是「叫貨單那一列的鎖」本身(平常每一次入庫靠的是它)
        r = self.c.admin.post(LINKS, {"warehouse": self.c.wh.id, "key": KEY, "ship_name": "甲湳雅店", "ship_phone": "035551234",
                                      "ship_address": "新竹市湳雅街 1 號", "invoice_email": "a@b.com",
                                      "supplier": self.c.supplier.id}, format="json")
        assert r.status_code == 200, r.content.decode()
        self.film = Product.objects.create(tenant=self.c.tenant, category=self.c.cat_case, name="甲 高透亮面保護貼",
                                           requires_serial=False, list_price=390)
        self.o = self.c.clerk.post(ORDERS, {"request_key": "draft-0001", "warehouse": self.c.wh.id,
                                            "lines": [{"key": "G02", "packs": 2}]}, format="json").json()

    def test_only_one_of_two_simultaneous_receipts_goes_in(self):
        order = VendorOrder.objects.get(pk=self.o["id"])
        real_commit = purchasing_services.commit_purchase_order
        start, results = threading.Barrier(2), {}

        def slow_commit(po):
            time.sleep(0.6)             # 握著鎖久一點:另一個人一定撞得到
            return real_commit(po)

        def work(key):
            try:
                start.wait(5)
                receipt, created = receiving.receive(
                    tenant=self.c.tenant, user=self.c.clerk_user, order=order, request_key=key,
                    lines=[{"key": G02, "qty": 50, "product": self.film.id}], manager=False)
                results[key] = "入庫" if created else "重複"
            except services.VendorError as exc:
                results[key] = str(exc)
            finally:
                connections.close_all()

        with mock.patch.object(receiving, "commit_purchase_order", slow_commit):
            threads = [threading.Thread(target=work, args=(key,)) for key in ("recv-aaaa", "recv-bbbb")]
            for t in threads:
                t.start()
            for t in threads:
                t.join(20)
        self.assertEqual(sorted(results.values()),
                         sorted(["入庫", "「高透亮面」最多還能入 0 個(叫 50、已經入 50)"]), results)
        balance = StockBalance.objects.get(tenant=self.c.tenant, product=self.film, warehouse=self.c.wh)
        self.assertEqual((balance.qty, PurchaseOrder.objects.filter(tenant=self.c.tenant).count(),
                          VendorReceipt.objects.count()), (50, 1, 1))

    def test_a_resend_while_the_first_is_still_running_waits_for_it_instead_of_failing_on_its_own(self):
        """入庫送出去、答覆沒回來,伺服器其實還在等廠商回明細;店員重新整理、用同一把鑰匙再送一次,這一次剛好連不到廠商。
        再送的這一次不能自己失敗、回「沒有入」—— 畫面會把它當成定論、之後換一把新鑰匙再入一次,而第一次稍後成立了。
        同一把鑰匙的請求要排隊:再送的這一次等第一次跑完,回的是同一次(連廠商都不用問)。"""
        order = VendorOrder.objects.get(pk=self.o["id"])
        real, entered, seen, results = self.vendor, threading.Event(), [], {}

        def flaky(method, path, key, body=None, timeout=15):
            seen.append(path)
            if len(seen) == 1:
                entered.set()
                time.sleep(0.8)             # 第一次:還在等廠商
                return real(method, path, key, body, timeout)
            raise moceo.Unreachable("連不到膜總裁(URLError)")

        def work(name):
            try:
                receipt, created = receiving.receive(
                    tenant=self.c.tenant, user=self.c.clerk_user, order=order, request_key="recv-samekey1",
                    lines=[{"key": G02, "qty": 20, "product": self.film.id}], manager=False)
                results[name] = ("入庫" if created else "同一次", receipt.id)
            except services.VendorError as exc:
                results[name] = (str(exc), None)
            finally:
                connections.close_all()

        with mock.patch.object(moceo, "_call", flaky):
            first = threading.Thread(target=work, args=("第一次",))
            first.start()
            self.assertTrue(entered.wait(5))
            again = threading.Thread(target=work, args=("再送一次",))
            again.start()
            first.join(20)
            again.join(20)
        self.assertEqual(results["第一次"][0], "入庫", results)
        self.assertEqual(results["再送一次"], ("同一次", results["第一次"][1]), results)
        self.assertEqual(len(seen), 1)          # 再送的那一次沒有再去問廠商
        balance = StockBalance.objects.get(tenant=self.c.tenant, product=self.film, warehouse=self.c.wh)
        self.assertEqual((balance.qty, PurchaseOrder.objects.filter(tenant=self.c.tenant).count(),
                          VendorReceipt.objects.count()), (20, 1, 1))
