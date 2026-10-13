"""平台內的同行當廠商:買家那一半(叫貨頁)× 賣家那一半(批發單),兩邊在同一台伺服器。跑法:manage.py test apps.vendor_orders.test_platform

甲通訊行開放批發;乙(核准的同行)、丙(沒有往來)當買家。買家這邊走的是原本的叫貨端點,賣家那邊走批發的端點。
要守住的:
1. 誰看得到這家「廠商」是賣家那邊的規則;自己看不到自己;平台管理員的廠商名單上沒有它(那是各家自己的往來)。
2. 不用金鑰:管理員開通(或輸入往來代碼)才叫得了;買家看不到賣家的成本,出貨之前看不到序號。
3. 手機到貨:賣家出貨單上的每一台直接變成買家庫存裡的那幾台(碼、成色、電池、備註、成本),同一台不會入兩次。
4. 中古機連品名只要連一次(記在商品那一層);帶序號的只能連到帶序號的商品,中古對中古、全新對全新。
5. 買家可以自己取消還沒出的;被賣家設成不往來、賣家關掉批發之後,已經叫的單照樣查得到、入得了庫。
"""
from decimal import Decimal as D

from django.test import TestCase

from apps.backup.tests.factory import Company
from apps.catalog.models import Product, SupplierProduct
from apps.inventory.models import ProductSerial, StockBalance
from apps.purchasing.models import PurchaseOrder
from apps.tenants.models import UserProfile
from apps.trade.models import TradeOrder, TradePartner, TradeUnit

from . import platform, standard
from .models import Vendor, VendorLink, VendorOrder, VendorReceipt, VendorReceiptItem

T = "/api/v1/trade/"
V = "/api/v1/vendor-orders/"
LINKS = "/api/v1/vendor-links/"


class _Both(TestCase):
    def setUp(self):
        self.a = Company("a", "甲通訊行", "甲")
        self.b = Company("b", "乙通訊行", "乙")
        self.c = Company("c", "丙通訊行", "丙")
        self.used = Product.objects.create(
            tenant=self.a.tenant, category=self.a.cat_phone, name="甲 中古 iPhone 13 128GB", is_secondhand=True, list_price=15000)
        r = self.a.admin.post(T + "settings/", {"is_open": True, "unit_rule": "price_minus", "unit_value": 1000}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.vendor = Vendor.objects.get(protocol="platform")
        self.code = self.vendor.code
        rows = [{"sn": sn, "grade": "A", "cost": "12000", "price": "16000", "battery": 90, "note": "小刮"} for sn in ("U001", "U002")]
        self.a._post("/api/v1/purchase-orders/", {
            "supplier": self.a.supplier.id, "warehouse": self.a.wh.id, "tax_method": "untaxed",
            "items": [{"product": self.used.id, "qty": 2, "unit_price": "12000", "serial_numbers": rows}]})
        self.a.purchase(case_qty=10, phone_serials=["N001", "N002", "N003"])
        r = self.a.admin.post(T + "products/", {"rows": [{"product": self.a.case.id, "is_listed": True},
                                                         {"product": self.a.phone.id, "is_listed": True, "price": 23000}]}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.keys = 0
        # 買家這邊的商品:一個中古機、一支全新機、一個皮套(工廠建好的)
        self.b_used = Product.objects.create(
            tenant=self.b.tenant, category=self.b.cat_phone, name="乙 中古 iPhone 13", is_secondhand=True, list_price=17000)

    def join(self, buyer=None, percent=90):
        """賣家發代碼、買家的管理員輸入。"""
        code = self.a.admin.post(T + "invites/", {"percent": percent, "terms": "月結"}, format="json").json()["code"]
        r = (buyer or self.b).admin.post(V + "join/", {"code": code}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        return r.json()

    def catalog(self, buyer=None, client=None, expect=200):
        buyer = buyer or self.b
        r = (client or buyer.clerk).get(f"{V}catalog/?warehouse={buyer.wh.id}&vendor={self.code}")
        self.assertEqual(r.status_code, expect, r.content.decode())
        return {row["key"]: row for row in r.json()["rows"]} if expect == 200 else r.json()

    def unit_key(self, sn):
        return f"{self.used.sku}#{TradeUnit.objects.get(serial__serial_no=sn).id}"

    def order(self, lines, buyer=None, expect=201, key=None, client=None):
        buyer = buyer or self.b
        self.keys += 1
        r = (client or buyer.clerk).post(V, {"request_key": key or f"draft-p{self.keys:04d}", "warehouse": buyer.wh.id,
                                             "vendor": self.code, "lines": lines}, format="json")
        self.assertEqual(r.status_code, expect, r.content.decode())
        return r.json()

    def seller_ship(self, order_no, lines=None, **extra):
        order = TradeOrder.objects.get(no=order_no)
        data = self.a.admin.get(f"{T}orders/{order.id}/").json()
        if lines is None:
            lines = [{"line": l["id"], "qty": l["open_qty"], "serials": [l["unit"]["serial"]] if l["unit"] else []}
                     for l in data["lines"] if l["open_qty"]]
        self.keys += 1
        r = self.a.admin.post(f"{T}orders/{order.id}/ship/", {"request_key": f"ship-p{self.keys:04d}", "warehouse": self.a.wh.id,
                                                              "lines": lines, **extra}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        return r.json()

    def plan(self, order, buyer=None, expect=200):
        r = (buyer or self.b).admin.get(f"{V}{order['id']}/receiving/")
        self.assertEqual(r.status_code, expect, r.content.decode())
        return {l["key"]: l for l in r.json()["lines"]} if expect == 200 else r.json()

    def receive(self, order, lines, buyer=None, expect=201, key=None):
        self.keys += 1
        r = (buyer or self.b).admin.post(f"{V}{order['id']}/receive/", {"request_key": key or f"recv-p{self.keys:04d}", "lines": lines},
                                         format="json")
        self.assertEqual(r.status_code, expect, r.content.decode())
        return r.json()


class WhoSeesTheSellerTests(_Both):
    def links(self, company, client=None):
        rows = (client or company.admin).get(LINKS).json()["results"]
        return {(r["warehouse_name"], r["provider"]): r for r in rows if r["provider"] == self.code}

    def test_opening_wholesale_puts_the_dealer_on_the_vendor_list_under_a_stable_code(self):
        self.assertEqual((self.vendor.code, self.vendor.name, self.vendor.seller_id, self.vendor.is_active),
                         (f"d-{self.a.tenant.backup_uuid.hex[:12]}", "甲通訊行", self.a.tenant.id, True))
        self.assertEqual([c.name for c in self.vendor.categories.all()], ["同行批發"])
        # 從來沒開過的公司不會多一筆
        self.b.admin.post(T + "settings/", {"show_qty": True}, format="json")
        self.assertEqual(Vendor.objects.filter(protocol="platform").count(), 1)

    def test_a_dealer_does_not_see_itself_and_strangers_see_it_only_while_it_sells_used_phones_to_everyone(self):
        self.assertEqual(self.links(self.a), {})
        seen = self.links(self.c)
        self.assertEqual({k[0] for k in seen}, {"丙湳雅店", "丙民生店"})
        self.assertEqual({(r["platform"], r["manual"], r["ready"], r["opened"]) for r in seen.values()}, {(True, False, False, False)})
        self.a.admin.post(T + "settings/", {"units_to_all": False}, format="json")
        self.assertEqual(self.links(self.c), {})
        r = self.c.clerk.get(f"{V}catalog/?warehouse={self.c.wh.id}&vendor={self.code}")
        self.assertEqual((r.status_code, r.json()["detail"]), (400, f"廠商名單上沒有「{self.code}」這一家,請平台管理員處理"))

    def test_the_platform_admins_vendor_list_does_not_show_dealers(self):
        from django.contrib.auth import get_user_model

        boss = get_user_model().objects.create_user(username="platform-boss", password="pw-12345")
        UserProfile.objects.create(user=boss, role="platform_admin", is_warehouse_locked=False)
        client = Company.client(boss)
        listing = client.get("/api/v1/platform/vendors/").json()
        self.assertNotIn(self.code, [v["code"] for v in listing["results"]])
        self.assertNotIn("platform", [p["value"] for p in listing["protocols"]])
        self.assertEqual(client.patch(f"/api/v1/platform/vendors/{self.vendor.id}/", {"name": "改名"}, format="json").status_code, 404)
        r = client.post("/api/v1/platform/vendors/", {"code": "fake", "name": "假的", "protocol": "platform"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_entering_an_invite_code_opens_every_store(self):
        got = self.join()
        self.assertEqual(got, {"vendor": self.code, "name": "甲通訊行"})
        partner = TradePartner.objects.get()
        self.assertEqual((partner.status, partner.percent, partner.terms, partner.name), ("approved", 90, "月結", "乙通訊行"))
        links = self.links(self.b)
        self.assertEqual({(k[0], r["ready"], r["opened"], r["ship_name"]) for k, r in links.items()},
                         {("乙湳雅店", True, True, "乙湳雅店"), ("乙民生店", True, True, "乙民生店")})

    def test_only_a_manager_can_join_and_a_wrong_code_does_nothing(self):
        code = self.a.admin.post(T + "invites/", {}, format="json").json()["code"]
        self.assertEqual(self.b.clerk.post(V + "join/", {"code": code}, format="json").status_code, 403)
        r = self.b.admin.post(V + "join/", {"code": "ZZZZZZZZ"}, format="json")
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "代碼不對或已經過期,請跟對方再要一個"))
        self.assertEqual(self.a.admin.post(V + "join/", {"code": code}, format="json").status_code, 400)       # 自己發的
        self.assertEqual((TradePartner.objects.count(), VendorLink.objects.count()), (0, 0))

    def test_a_store_that_is_not_opened_cannot_order_and_a_key_is_refused(self):
        r = self.c.clerk.get(f"{V}catalog/?warehouse={self.c.wh.id}&vendor={self.code}")
        self.assertEqual(r.status_code, 400)
        self.assertIn("還沒有開通甲通訊行", r.json()["detail"])
        r = self.c.admin.post(LINKS, {"warehouse": self.c.wh.id, "vendor": self.code, "key": "mk_live_" + "x" * 30}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("不用金鑰", r.json()["detail"])
        self.assertEqual(self.c.clerk.post(LINKS, {"warehouse": self.c.wh.id, "vendor": self.code, "opened": True}, format="json").status_code, 403)
        r = self.c.admin.post(LINKS, {"warehouse": self.c.wh.id, "vendor": self.code, "opened": True, "delivery_method": "自取"}, format="json")
        self.assertEqual((r.status_code, r.json()["ready"]), (200, True))
        # 沒有往來的同行:只看得到中古機(平台販售)
        self.assertEqual({row["sku"] for row in self.catalog(self.c).values()}, {self.used.sku})

    def test_trying_to_order_from_a_seller_that_is_not_open_to_you_leaves_nothing_behind(self):
        self.a.admin.post(T + "settings/", {"units_to_all": False}, format="json")
        client = platform.client(self.vendor)
        got = client.place(f"platform:{self.c.tenant.id}:{self.c.wh.id}", {"idempotency_key": "c-try-0001", "items": []})
        self.assertEqual((got.status, got.reason), (403, "這家沒有開放給你"))
        self.assertEqual((TradePartner.objects.count(), TradeOrder.objects.count()), (0, 0))

    def test_the_token_cannot_be_anything_else(self):
        client = platform.client(self.vendor)
        for bad in ("", "mk_live_abc", "platform:", "platform:1", f"platform:{self.b.tenant.id}:{self.a.wh.id}", "platform:x:y", None):
            with self.assertRaises(standard.Unreachable, msg=bad):
                client.products(bad)
        # 賣家自己的門市也不行(自己不跟自己買)
        with self.assertRaises(standard.Unreachable):
            client.products(f"platform:{self.a.tenant.id}:{self.a.wh.id}")


class OrderingTests(_Both):
    def setUp(self):
        super().setUp()
        self.join()

    def test_the_buyer_sees_units_and_goods_with_his_prices_and_no_cost_or_serials(self):
        r = self.b.clerk.get(f"{V}catalog/?warehouse={self.b.wh.id}&vendor={self.code}")
        self.assertEqual((r.status_code, r.json()["platform"], r.json()["manual"]), (200, True, False))
        rows = self.catalog()
        one = rows[self.unit_key("U001")]
        self.assertEqual((one["per_unit"], one["requires_serial"], one["spec_label"], one["unit_price"], one["condition"], one["name"]),
                         (True, True, "A 級 電池 90% 小刮", "15000.00", "中古", "甲 中古 iPhone 13 128GB"))
        self.assertEqual((rows[self.a.phone.sku]["unit_price"], rows[self.a.phone.sku]["requires_serial"], rows[self.a.phone.sku]["per_unit"]),
                         ("23000.00", True, False))
        self.assertEqual((rows[self.a.case.sku]["unit_price"], rows[self.a.case.sku]["available"]), ("351.00", "有貨"))
        text = r.content.decode()
        for secret in ("U001", "U002", "N001", "12000", "20000"):
            self.assertNotIn(secret, text)

    def test_an_order_lands_on_the_sellers_side_as_a_wholesale_order(self):
        got = self.order([{"key": self.unit_key("U001"), "packs": 1}, {"key": self.a.phone.sku, "packs": 2}, {"key": self.a.case.sku, "packs": 4}])
        seller = TradeOrder.objects.get()
        self.assertEqual((got["state"], got["vendor_order_no"], got["total_amount"], got["amount_matches"], got["can_cancel"]),
                         ("placed", seller.no, "62404.00", True, True))
        self.assertEqual(got["payment_method"], "月結")
        self.assertEqual([(i["sku"], i["qty"], i["unit_price"]) for i in got["items"]],
                         [(self.used.sku, 1, "15000.00"), (self.a.phone.sku, 2, "23000.00"), (self.a.case.sku, 4, "351.00")])
        # 賣家看到的:哪一個同行的哪一間門市、怎麼取貨(這家門市沒有填地址 → 加入時預設自取)、
        # 付款方式是賣家跟他講好的那一種(買家送什麼都不看)
        self.assertEqual((seller.partner.name, seller.buyer_store, seller.delivery_method, seller.payment_method, seller.status),
                         ("乙通訊行", "乙湳雅店", "自取", "月結", "accepted"))
        self.assertEqual(sorted(l.qty for l in seller.lines.all()), [1, 2, 4])
        # 同一把鑰匙再來:同一張,賣家那邊也只有一張
        again = self.order([{"key": self.a.case.sku, "packs": 1}], key=got["request_key"], expect=200)
        self.assertEqual((again["id"], TradeOrder.objects.count(), VendorOrder.objects.count()), (got["id"], 1, 1))

    def test_delivery_carries_the_stores_address_to_the_seller(self):
        VendorLink.objects.filter(tenant=self.b.tenant, warehouse=self.b.wh).update(
            delivery_method="宅配", ship_name="乙湳雅店 陳先生", ship_phone="0912000111", ship_address="新竹市光復路 1 號")
        self.order([{"key": self.a.case.sku, "packs": 1, "ship_name": "別的地方"}])
        seller = TradeOrder.objects.get()
        self.assertEqual((seller.delivery_method, seller.ship_name, seller.ship_phone, seller.ship_address),
                         ("宅配", "乙湳雅店 陳先生", "0912000111", "新竹市光復路 1 號"))

    def test_the_payment_terms_on_the_buyers_record_are_the_sellers(self):
        TradePartner.objects.update(terms="匯款")
        r = self.b.clerk.post(V, {"request_key": "draft-pay-01", "warehouse": self.b.wh.id, "vendor": self.code,
                                  "lines": [{"key": self.a.case.sku, "packs": 1}], "payment_method": "月結"}, format="json")
        self.assertEqual((r.status_code, r.json()["payment_method"], TradeOrder.objects.get().payment_method), (201, "匯款", "匯款"))
        TradePartner.objects.update(terms="現金")
        TradeOrder.objects.update(payment_method="貨到付款")        # 賣家那邊之後改了這張單的講法
        mine = self.b.clerk.post(V + "sync/", {"warehouse": self.b.wh.id, "vendor": self.code}, format="json").json()["results"][0]
        self.assertEqual(mine["payment_method"], "貨到付款")

    def test_a_unit_can_only_be_ordered_once(self):
        r = self.order([{"key": self.unit_key("U001"), "packs": 2}], expect=400)
        self.assertEqual(r["detail"], "「甲 中古 iPhone 13 128GB」是一台一筆的,同一台只能訂 1")
        self.order([{"key": self.unit_key("U001"), "packs": 1}])
        self.assertNotIn(self.unit_key("U001"), self.catalog())
        self.assertEqual((VendorOrder.objects.count(), TradeOrder.objects.count()), (1, 1))

    def test_the_seller_saying_no_leaves_no_order_behind(self):
        r = self.order([{"key": self.a.case.sku, "packs": 11}], expect=400)
        self.assertIn("庫存不夠", r["detail"])
        self.assertEqual((VendorOrder.objects.count(), TradeOrder.objects.count()), (0, 0))

    def test_progress_follows_the_seller(self):
        got = self.order([{"key": self.unit_key("U001"), "packs": 1}, {"key": self.a.case.sku, "packs": 4}])
        seller = self.a.admin.get(f"{T}orders/{TradeOrder.objects.get().id}/").json()
        case_line = next(l for l in seller["lines"] if not l["per_unit"])
        self.seller_ship(got["vendor_order_no"], lines=[{"line": case_line["id"], "qty": 4, "serials": []}], shipping_fee=120, tracking_no="SF99")
        r = self.b.clerk.post(V + "sync/", {"warehouse": self.b.wh.id, "vendor": self.code}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        mine = r.json()["results"][0]
        self.assertEqual((mine["vendor_status"], mine["vendor_tracking_no"], mine["total_amount"], mine["shipping_fee"], r.json()["others"]),
                         ("部分出貨", "SF99", "16524.00", "120.00", []))
        # 賣家那一台不出了:金額跟著變
        unit_line = next(l for l in seller["lines"] if l["per_unit"])
        self.a.admin.post(f"{T}orders/{seller['id']}/drop/", {"line": unit_line["id"]}, format="json")
        mine = self.b.clerk.post(V + "sync/", {"warehouse": self.b.wh.id, "vendor": self.code}, format="json").json()["results"][0]
        self.assertEqual((mine["vendor_status"], mine["total_amount"], mine["can_cancel"]), ("已出貨", "1524.00", False))

    def test_the_buyer_cancels_what_has_not_shipped(self):
        got = self.order([{"key": self.unit_key("U001"), "packs": 1}])
        r = self.b.clerk.post(f"{V}{got['id']}/cancel/", {"cancelled": True}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.assertEqual((r.json()["vendor_status"], r.json()["can_cancel"], r.json()["total_amount"]), ("已取消", False, "0.00"))
        seller = TradeOrder.objects.get()
        self.assertEqual((seller.status, seller.closed_by_buyer), ("cancelled", True))
        self.assertIn(self.unit_key("U001"), self.catalog())            # 那一台回到清單上
        again = self.b.clerk.post(f"{V}{got['id']}/cancel/", {"cancelled": True}, format="json")
        self.assertEqual(again.status_code, 400)
        self.assertEqual(self.b.clerk.post(f"{V}{got['id']}/cancel/", {"cancelled": False}, format="json").status_code, 400)

    def test_cancelling_needs_the_ordering_ability_and_the_right_company(self):
        got = self.order([{"key": self.unit_key("U001"), "packs": 1}])
        UserProfile.objects.filter(user=self.b.clerk_user).update(denied_abilities=["vendor_order"])
        self.b.clerk_user.profile.refresh_from_db()
        self.assertEqual(self.b.clerk.post(f"{V}{got['id']}/cancel/", {"cancelled": True}, format="json").status_code, 403)
        self.assertEqual(self.c.admin.post(f"{V}{got['id']}/cancel/", {"cancelled": True}, format="json").status_code, 404)
        self.assertEqual(TradeOrder.objects.get().status, "accepted")


class ReceivingTests(_Both):
    def setUp(self):
        super().setUp()
        self.join()
        self.o = self.order([{"key": self.unit_key("U001"), "packs": 1}, {"key": self.unit_key("U002"), "packs": 1},
                             {"key": self.a.phone.sku, "packs": 2}, {"key": self.a.case.sku, "packs": 4}])
        seller = self.a.admin.get(f"{T}orders/{TradeOrder.objects.get().id}/").json()
        self.sl = {("unit", l["unit"]["serial_no"]) if l["unit"] else (l["sku"],): l for l in seller["lines"]}
        self.n = {s.serial_no: s.id for s in ProductSerial.objects.filter(tenant=self.a.tenant, serial_no__startswith="N0")}

    def ship_all_but_u002(self):
        self.seller_ship(self.o["vendor_order_no"], lines=[
            {"line": self.sl[("unit", "U001")]["id"], "qty": 1, "serials": [self.sl[("unit", "U001")]["unit"]["serial"]]},
            {"line": self.sl[(self.a.phone.sku,)]["id"], "qty": 2, "serials": [self.n["N001"], self.n["N002"]]},
            {"line": self.sl[(self.a.case.sku,)]["id"], "qty": 4, "serials": []}])

    def keys(self, plan):
        return {(("unit" if l["per_unit"] else l["sku"]), l["spec_label"] or "", l["suggested_qty"]): k for k, l in plan.items()}

    def test_before_anything_ships_there_is_nothing_to_receive(self):
        plan = self.plan(self.o)
        self.assertEqual({(l["sku"], l["suggested_qty"], len(l["serials"])) for l in plan.values()},
                         {(self.used.sku, 0, 0), (self.a.phone.sku, 0, 0), (self.a.case.sku, 0, 0)})
        self.assertNotIn("U001", str(plan))

    def test_shipped_phones_arrive_with_their_serials_and_become_stock(self):
        self.ship_all_but_u002()
        plan = self.plan(self.o)
        by = {(l["sku"], l["spec_id"]): l for l in plan.values()}
        u1 = next(l for l in plan.values() if l["serials"] and l["serials"][0]["sn"] == "U001")
        phones, cases = by[(self.a.phone.sku, None)], by[(self.a.case.sku, None)]
        self.assertEqual((u1["requires_serial"], u1["per_unit"], u1["suggested_qty"], u1["serials"]),
                         (True, True, 1, [{"imei": "", "sn": "U001", "grade": "A", "battery": 90, "note": "小刮"}]))
        self.assertEqual((phones["suggested_qty"], [s["sn"] for s in phones["serials"]], cases["suggested_qty"]), (2, ["N001", "N002"], 4))
        got = self.receive(self.o, [
            {"key": u1["key"], "qty": 1, "product": self.b_used.id},
            {"key": phones["key"], "qty": 2, "product": self.b.phone.id},
            {"key": cases["key"], "qty": 4, "product": self.b.case.id}])
        po = PurchaseOrder.objects.get(tenant=self.b.tenant)
        self.assertEqual((po.total_cost, po.supplier.name, po.warehouse_id), (D("62404"), "甲通訊行", self.b.wh.id))
        mine = {s.serial_no: s for s in ProductSerial.objects.filter(tenant=self.b.tenant)}
        self.assertEqual(set(mine), {"U001", "N001", "N002"})
        u = mine["U001"]
        self.assertEqual((u.product_id, u.status, u.warehouse_id, u.purchase_unit_cost, u.condition_grade, u.battery_health, u.condition_note),
                         (self.b_used.id, "in_stock", self.b.wh.id, D("15000"), "A", 90, "小刮"))
        self.assertEqual((mine["N001"].product_id, mine["N001"].purchase_unit_cost), (self.b.phone.id, D("23000")))
        self.assertEqual(StockBalance.objects.get(tenant=self.b.tenant, product=self.b.case, warehouse=self.b.wh).qty, 4)
        item = VendorReceiptItem.objects.get(product=self.b_used)
        self.assertEqual(item.serials, [{"imei": "", "sn": "U001"}])
        self.assertEqual(got["order"]["receipts"][0]["purchase_order_no"], po.no)
        # 賣家那邊那一台是已售、買家這邊是在庫:兩家公司各記各的
        self.assertEqual(ProductSerial.objects.get(tenant=self.a.tenant, serial_no="U001").status, "sold")

    def test_the_same_unit_is_not_received_twice_and_the_next_shipment_shows_only_the_new_one(self):
        self.ship_all_but_u002()
        plan = self.plan(self.o)
        u1 = next(l for l in plan.values() if l["serials"] and l["serials"][0]["sn"] == "U001")
        self.receive(self.o, [{"key": u1["key"], "qty": 1, "product": self.b_used.id}])
        plan = self.plan(self.o)
        self.assertEqual((plan[u1["key"]]["suggested_qty"], plan[u1["key"]]["serials"], plan[u1["key"]]["received_qty"]), (0, [], 1))
        bad = self.receive(self.o, [{"key": u1["key"], "qty": 1, "product": self.b_used.id}], expect=400)
        self.assertIn("最多還能入 0 個", bad["detail"])
        self.assertEqual(ProductSerial.objects.filter(tenant=self.b.tenant).count(), 1)
        # 賣家把另一台也出了:這次只列新的那一台,而且對照已經記住了(中古機連一次,每一台都算)
        self.seller_ship(self.o["vendor_order_no"], lines=[
            {"line": self.sl[("unit", "U002")]["id"], "qty": 1, "serials": [self.sl[("unit", "U002")]["unit"]["serial"]]}])
        plan = self.plan(self.o)
        u2 = next(l for l in plan.values() if l["serials"] and l["serials"][0]["sn"] == "U002")
        self.assertEqual((u2["suggested_qty"], u2["product"]["id"]), (1, self.b_used.id))
        self.assertEqual(SupplierProduct.objects.filter(tenant=self.b.tenant, product=self.b_used, is_active=True).count(), 1)
        self.receive(self.o, [{"key": u2["key"], "qty": 1, "product": self.b_used.id, "was": self.b_used.id}])
        self.assertEqual(set(ProductSerial.objects.filter(tenant=self.b.tenant).values_list("serial_no", flat=True)), {"U001", "U002"})

    def test_only_what_the_seller_shipped_can_be_received(self):
        self.seller_ship(self.o["vendor_order_no"], lines=[
            {"line": self.sl[(self.a.phone.sku,)]["id"], "qty": 1, "serials": [self.n["N001"]]}])
        plan = self.plan(self.o)
        phones = next(l for l in plan.values() if l["sku"] == self.a.phone.sku)
        self.assertEqual((phones["suggested_qty"], phones["shipped_qty"], phones["qty"]), (1, 1, 2))
        for qty, serials in ((2, None), (1, ["N002"]), (1, ["N001", "N002"]), (0, None)):
            body = {"key": phones["key"], "qty": qty, "product": self.b.phone.id, **({"serials": serials} if serials else {})}
            self.receive(self.o, [body], expect=400)
        self.assertEqual((ProductSerial.objects.filter(tenant=self.b.tenant).count(), VendorReceipt.objects.count()), (0, 0))
        self.receive(self.o, [{"key": phones["key"], "qty": 1, "product": self.b.phone.id, "serials": ["n-001"]}])
        self.assertEqual(list(ProductSerial.objects.filter(tenant=self.b.tenant).values_list("serial_no", flat=True)), ["N001"])

    def test_serial_lines_go_only_into_matching_products(self):
        self.ship_all_but_u002()
        plan = self.plan(self.o)
        u1 = next(l for l in plan.values() if l["serials"] and l["serials"][0]["sn"] == "U001")
        phones = next(l for l in plan.values() if l["sku"] == self.a.phone.sku)
        cases = next(l for l in plan.values() if l["sku"] == self.a.case.sku)
        for line, product, why in (
            (u1, self.b.case, "要對到帶序號的商品"), (u1, self.b.phone, "要對到中古機 / 已拆封的商品"),
            (phones, self.b_used, "不能對到中古機 / 已拆封的商品"), (phones, self.b.case, "要對到帶序號的商品"),
            (cases, self.b.phone, "只能入到按數量管的一般商品"), (cases, self.b_used, "只能入到按數量管的一般商品"),
            (u1, self.a.phone, "對到的商品找不到"),
        ):
            bad = self.receive(self.o, [{"key": line["key"], "qty": line["suggested_qty"], "product": product.id}], expect=400)
            self.assertIn(why, bad["detail"], (line["sku"], product.name))
        self.assertEqual((ProductSerial.objects.filter(tenant=self.b.tenant).count(), SupplierProduct.objects.filter(tenant=self.b.tenant).count()), (0, 0))

    def test_linking_names_ahead_of_time_lists_a_used_model_once(self):
        r = self.b.clerk.get(f"{V}mappings/?warehouse={self.b.wh.id}&vendor={self.code}")
        self.assertEqual(r.status_code, 200, r.content.decode())
        rows = r.json()["rows"]
        # 訂走的那兩台不在清單上了 → 先再進兩台
        self.assertEqual([(x["sku"], x.get("requires_serial"), x.get("per_unit")) for x in rows],
                         [(self.a.phone.sku, True, False), (self.a.case.sku, None, None)])
        more = [{"sn": sn, "grade": "B", "cost": "9000", "price": "13000"} for sn in ("U010", "U011")]
        self.a._post("/api/v1/purchase-orders/", {"supplier": self.a.supplier.id, "warehouse": self.a.wh.id, "tax_method": "untaxed",
                                                  "items": [{"product": self.used.id, "qty": 2, "unit_price": "9000", "serial_numbers": more}]})
        rows = self.b.clerk.get(f"{V}mappings/?warehouse={self.b.wh.id}&vendor={self.code}").json()["rows"]
        used = [x for x in rows if x["sku"] == self.used.sku]
        self.assertEqual([(x["per_unit"], x["spec_label"], x["product"]) for x in used], [(True, "", None)])
        body = {"warehouse": self.b.wh.id, "vendor": self.code, "key": used[0]["key"]}
        self.assertEqual(self.b.clerk.post(V + "mappings/", {**body, "product": self.b.phone.id}, format="json").status_code, 400)
        r = self.b.clerk.post(V + "mappings/", {**body, "product": self.b_used.id}, format="json")
        self.assertEqual((r.status_code, r.json()["product"]["id"]), (200, self.b_used.id))
        # 叫貨頁上每一台都帶著連好的店內商品
        self.assertEqual({row["product"]["id"] for key, row in self.catalog().items() if row["sku"] == self.used.sku}, {self.b_used.id})

    def test_a_voided_purchase_lets_the_units_be_received_again(self):
        self.ship_all_but_u002()
        plan = self.plan(self.o)
        u1 = next(l for l in plan.values() if l["serials"] and l["serials"][0]["sn"] == "U001")
        self.receive(self.o, [{"key": u1["key"], "qty": 1, "product": self.b_used.id}])
        po = PurchaseOrder.objects.get(tenant=self.b.tenant)
        self.b._post(f"/api/v1/purchase-orders/{po.id}/void/", {})
        plan = self.plan(self.o)
        self.assertEqual((plan[u1["key"]]["suggested_qty"], plan[u1["key"]]["received_qty"]), (1, 0))
        self.receive(self.o, [{"key": u1["key"], "qty": 1, "product": self.b_used.id, "was": self.b_used.id}])
        self.assertEqual(ProductSerial.objects.filter(tenant=self.b.tenant, serial_no="U001", status="in_stock").count(), 1)

    def test_goods_on_the_way_can_still_be_received_after_the_seller_stops_dealing(self):
        self.ship_all_but_u002()
        partner = TradePartner.objects.get()
        self.a.admin.post(f"{T}partners/{partner.id}/", {"status": "blocked"}, format="json")
        self.assertEqual(self.catalog(expect=400)["detail"], f"廠商名單上沒有「{self.code}」這一家,請平台管理員處理")
        self.order([{"key": self.a.case.sku, "packs": 1}], expect=400)
        plan = self.plan(self.o)
        cases = next(l for l in plan.values() if l["sku"] == self.a.case.sku)
        self.receive(self.o, [{"key": cases["key"], "qty": 4, "product": self.b.case.id}])
        self.assertEqual(StockBalance.objects.get(tenant=self.b.tenant, product=self.b.case, warehouse=self.b.wh).qty, 4)

    def test_goods_on_the_way_can_still_be_received_after_the_seller_closes_wholesale(self):
        self.ship_all_but_u002()
        self.a.admin.post(T + "settings/", {"is_open": False}, format="json")
        self.vendor.refresh_from_db()
        self.assertFalse(self.vendor.is_active)
        self.order([{"key": self.a.case.sku, "packs": 1}], expect=400)
        plan = self.plan(self.o)
        phones = next(l for l in plan.values() if l["sku"] == self.a.phone.sku)
        self.receive(self.o, [{"key": phones["key"], "qty": 2, "product": self.b.phone.id}])
        self.assertEqual(ProductSerial.objects.filter(tenant=self.b.tenant).count(), 2)

    # ── 複審第一輪:買家收進去的貨,賣家不能再變回自己的庫存;退掉的出貨不能再入一次 ──
    def receive_everything_shipped(self):
        plan = self.plan(self.o)
        mine = {True: self.b_used.id, self.a.phone.sku: self.b.phone.id, self.a.case.sku: self.b.case.id}
        lines = [{"key": l["key"], "qty": l["suggested_qty"], "product": mine[True if l["per_unit"] else l["sku"]]}
                 for l in plan.values() if l["suggested_qty"]]
        return self.receive(self.o, lines)

    def seller_view(self):
        return self.a.admin.get(f"{T}orders/{TradeOrder.objects.get().id}/").json()

    def test_once_the_buyer_has_received_the_seller_cannot_cancel_the_shipment_or_return_it(self):
        self.ship_all_but_u002()
        self.receive_everything_shipped()
        seller = self.seller_view()
        shipment = seller["shipments"][0]
        self.assertEqual(sorted((l["shipped_qty"], l["received_qty"]) for l in seller["lines"]), [(0, 0), (1, 1), (2, 2), (4, 4)])
        why = "買家已經把這一次出的貨入庫了;要退貨請對方先作廢那張進貨單,再回來處理"
        r = self.a.admin.post(f"{T}shipments/{shipment['id']}/void/", {}, format="json")
        self.assertEqual((r.status_code, r.json()["detail"]), (400, why))
        r = self.a.admin.post("/api/v1/sales-returns/", {"original_so": shipment["sales_order"], "payment_method": "peer"}, format="json")
        self.assertEqual(r.status_code, 400, r.content.decode())
        self.assertIn(why, r.content.decode())
        # 同一台只在買家那邊在庫;賣家那邊還是已售、那一次出貨還算數
        self.assertEqual(ProductSerial.objects.get(tenant=self.a.tenant, serial_no="U001").status, "sold")
        self.assertEqual(ProductSerial.objects.get(tenant=self.b.tenant, serial_no="U001").status, "in_stock")
        self.assertFalse(self.seller_view()["shipments"][0]["is_void"])
        # 買家把那張進貨單作廢(貨退回去)→ 賣家才取消得了
        po = PurchaseOrder.objects.get(tenant=self.b.tenant)
        self.b._post(f"/api/v1/purchase-orders/{po.id}/void/", {})
        self.assertEqual(sorted(l["received_qty"] for l in self.seller_view()["lines"]), [0, 0, 0, 0])
        r = self.a.admin.post(f"{T}shipments/{shipment['id']}/void/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.assertEqual(ProductSerial.objects.get(tenant=self.a.tenant, serial_no="U001").status, "in_stock")
        self.assertFalse(ProductSerial.objects.filter(tenant=self.b.tenant, status="in_stock").exists())
        # 取消掉的那一次出貨,買家再打開入庫:沒有東西可以入,硬送也不收
        plan = self.plan(self.o)
        self.assertEqual({(l["shipped_qty"], l["suggested_qty"], len(l["serials"])) for l in plan.values()}, {(0, 0, 0)})
        cases = next(l for l in plan.values() if l["sku"] == self.a.case.sku)
        bad = self.receive(self.o, [{"key": cases["key"], "qty": 4, "product": self.b.case.id, "was": self.b.case.id}], expect=400)
        self.assertIn("還沒出的不能先入", bad["detail"])

    def test_a_shipment_the_seller_took_back_as_a_return_cannot_be_received_again(self):
        """賣家整張銷退(貨退回去了)之後,買家那張叫貨單不能再把同一批貨入一次。"""
        seller = self.seller_view()
        case_line = next(l for l in seller["lines"] if l["sku"] == self.a.case.sku)
        shipped = self.seller_ship(self.o["vendor_order_no"], lines=[{"line": case_line["id"], "qty": 4, "serials": []}])
        self.receive_everything_shipped()
        self.assertEqual(StockBalance.objects.get(tenant=self.b.tenant, product=self.b.case, warehouse=self.b.wh).qty, 4)
        po = PurchaseOrder.objects.get(tenant=self.b.tenant)
        self.b._post(f"/api/v1/purchase-orders/{po.id}/void/", {})
        so = shipped["shipments"][0]["sales_order"]
        self.a._post("/api/v1/sales-returns/", {"original_so": so, "payment_method": "peer"})
        self.assertEqual(StockBalance.objects.get(tenant=self.a.tenant, product=self.a.case, warehouse=self.a.wh).qty, 10)
        after = self.seller_view()
        self.assertEqual((after["owed"], after["shipments"][0]["returned"]), (0, True))
        plan = self.plan(self.o)
        cases = next(l for l in plan.values() if l["sku"] == self.a.case.sku)
        self.assertEqual((cases["shipped_qty"], cases["suggested_qty"], cases["received_qty"], cases["strict_shipped"]), (0, 0, 0, True))
        bad = self.receive(self.o, [{"key": cases["key"], "qty": 4, "product": self.b.case.id, "was": self.b.case.id}], expect=400)
        self.assertIn("現在算數的出貨是 0 個", bad["detail"])
        self.assertEqual(StockBalance.objects.get(tenant=self.b.tenant, product=self.b.case, warehouse=self.b.wh).qty, 0)
        self.assertEqual(PurchaseOrder.objects.filter(tenant=self.b.tenant, is_void=False).count(), 0)

    def test_goods_the_seller_has_not_shipped_cannot_be_received_early(self):
        plan = self.plan(self.o)
        cases = next(l for l in plan.values() if l["sku"] == self.a.case.sku)
        bad = self.receive(self.o, [{"key": cases["key"], "qty": 1, "product": self.b.case.id}], expect=400)
        self.assertIn("還沒出的不能先入", bad["detail"])
        self.assertEqual((VendorReceipt.objects.count(), SupplierProduct.objects.filter(tenant=self.b.tenant).count()), (0, 0))

    def test_with_two_shipments_only_what_the_buyer_has_not_received_can_be_cancelled(self):
        seller = self.seller_view()
        case_line = next(l for l in seller["lines"] if l["sku"] == self.a.case.sku)
        for _ in range(2):
            self.seller_ship(self.o["vendor_order_no"], lines=[{"line": case_line["id"], "qty": 2, "serials": []}])
        plan = self.plan(self.o)
        cases = next(l for l in plan.values() if l["sku"] == self.a.case.sku)
        self.receive(self.o, [{"key": cases["key"], "qty": 3, "product": self.b.case.id}])
        first, second = self.seller_view()["shipments"]
        # 出了 4、買家收了 3:取消任何一次(2 個)都會讓收的比出的多
        self.assertEqual(self.a.admin.post(f"{T}shipments/{second['id']}/void/", {}, format="json").status_code, 400)
        po = PurchaseOrder.objects.get(tenant=self.b.tenant)
        self.b._post(f"/api/v1/purchase-orders/{po.id}/void/", {})
        plan = self.plan(self.o)
        self.receive(self.o, [{"key": cases["key"], "qty": 2, "product": self.b.case.id, "was": self.b.case.id}])
        # 出了 4、買家收了 2:可以取消一次,第二次就不行了
        self.assertEqual(self.a.admin.post(f"{T}shipments/{second['id']}/void/", {}, format="json").status_code, 200)
        self.assertEqual(self.a.admin.post(f"{T}shipments/{first['id']}/void/", {}, format="json").status_code, 400)
        self.assertEqual(StockBalance.objects.get(tenant=self.a.tenant, product=self.a.case, warehouse=self.a.wh).qty, 8)

    def test_while_the_sellers_data_is_being_restored_nothing_reaches_it(self):
        """複審第一輪 P1:賣家的資料還原中(公司維護鎖),買家這一側進來的請求不經過賣家的登入驗證 —— 一律當成連不到,不改到賣家的資料。"""
        from apps.backup.models import TenantMaintenance

        self.ship_all_but_u002()
        code = self.a.admin.post(T + "invites/", {}, format="json").json()["code"]
        lock = TenantMaintenance.objects.create(tenant=self.a.tenant, active=True)
        before = (TradeOrder.objects.count(), TradePartner.objects.count())
        self.assertEqual(self.catalog(expect=400)["detail"], "連不到甲通訊行,請稍後再試")
        with self.assertRaises(standard.Unreachable):          # 下單 = 沒有明確的答覆(不知道有沒有成立),賣家那邊什麼都沒有多
            platform.client(self.vendor).place(f"platform:{self.b.tenant.id}:{self.b.wh.id}",
                                               {"idempotency_key": "b-during-restore", "items": [{"sku": self.a.case.sku, "spec_id": None, "qty": 1}]})
        r = self.c.admin.post(V + "join/", {"code": code}, format="json")
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "對方的資料還原中,請稍後再試"))
        self.assertEqual(self.b.clerk.post(f"{V}{self.o['id']}/cancel/", {"cancelled": True}, format="json").status_code, 400)
        self.assertEqual(self.plan(self.o, expect=400)["detail"], "連不到甲通訊行,請稍後再試")
        self.assertEqual((TradeOrder.objects.count(), TradePartner.objects.count(), TradeOrder.objects.get().status), (*before, "accepted"))
        # 還原做完:代碼還能用、貨照樣入得了
        lock.active = False
        lock.save()
        self.assertEqual(self.c.admin.post(V + "join/", {"code": code}, format="json").status_code, 200)
        self.receive_everything_shipped()
        self.assertEqual(ProductSerial.objects.filter(tenant=self.b.tenant, status="in_stock").count(), 3)

    def test_receiving_is_refused_while_the_seller_is_being_restored(self):
        from apps.backup.models import TenantMaintenance

        self.ship_all_but_u002()
        plan = self.plan(self.o)
        cases = next(l for l in plan.values() if l["sku"] == self.a.case.sku)
        TenantMaintenance.objects.create(tenant=self.a.tenant, active=True)
        self.receive(self.o, [{"key": cases["key"], "qty": 4, "product": self.b.case.id}], expect=400)
        self.assertEqual((VendorReceipt.objects.count(), PurchaseOrder.objects.filter(tenant=self.b.tenant).count()), (0, 0))

    def test_another_company_cannot_receive_it(self):
        self.ship_all_but_u002()
        self.assertEqual(self.c.admin.get(f"{V}{self.o['id']}/receiving/").status_code, 404)
        self.assertEqual(self.c.admin.post(f"{V}{self.o['id']}/receive/", {"request_key": "recv-x-0001", "lines": []}, format="json").status_code, 404)


# ── 兩條連線同時來(複審第二輪修的兩處) ─────────────────────────────────────────
import threading  # noqa: E402
import time  # noqa: E402

from django.db import connections  # noqa: E402
from django.db.utils import OperationalError  # noqa: E402
from django.test import TransactionTestCase  # noqa: E402


class TwoAtOnceTests(TransactionTestCase):
    def setUp(self):
        _Both.setUp(self)
        _Both.join(self)
        self.o = _Both.order(self, [{"key": self.a.phone.sku, "packs": 2}, {"key": self.a.case.sku, "packs": 4}])
        seller = self.a.admin.get(f"{T}orders/{TradeOrder.objects.get().id}/").json()
        self.phone_line, self.case_line = seller["lines"]
        self.n = {s.serial_no: s.id for s in ProductSerial.objects.filter(tenant=self.a.tenant, serial_no__startswith="N0")}

    # 這個類別不能繼承 _Both(它是一般的 TestCase):常用的動作借過來用
    seller_ship, plan, receive = _Both.seller_ship, _Both.plan, _Both.receive

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

    def test_voiding_one_receipt_does_not_wipe_what_another_receipt_just_reported(self):
        """「作廢 A 的進貨單」與「入庫 B」同時來:作廢那一邊要等入庫做完、照**那之後**的樣子回報,不能拿先前算好的蓋掉 B。
        這裡用另一條連線扮「入庫 B」:鎖著買家的叫貨單與賣家的批發單,把 B 記成已收(買家那張進貨單生效、賣家那邊已收 2),一秒後提交。"""
        self.seller_ship(self.o["vendor_order_no"], lines=[{"line": self.case_line["id"], "qty": 4, "serials": []}])
        self.seller_ship(self.o["vendor_order_no"], lines=[{"line": self.phone_line["id"], "qty": 2, "serials": [self.n["N001"], self.n["N002"]]}])
        plan = self.plan(self.o)
        cases = next(l for l in plan.values() if l["sku"] == self.a.case.sku)
        phones = next(l for l in plan.values() if l["sku"] == self.a.phone.sku)
        self.receive(self.o, [{"key": cases["key"], "qty": 4, "product": self.b.case.id}])
        self.receive(self.o, [{"key": phones["key"], "qty": 2, "product": self.b.phone.id}])
        po_cases, po_phones = PurchaseOrder.objects.filter(tenant=self.b.tenant).order_by("id")
        # 先把 B(手機)那一次弄成「還沒入」的樣子:進貨單作廢中、賣家那邊已收 0
        PurchaseOrder.objects.filter(pk=po_phones.id).update(is_void=True)
        from apps.trade.models import TradeOrderLine, TradeShipmentSerial

        TradeOrderLine.objects.filter(pk=self.phone_line["id"]).update(received_qty=0)
        TradeShipmentSerial.objects.update(received=False)
        seller_order = TradeOrder.objects.get()
        began = self.meanwhile([
            ("SELECT 1 FROM vendor_orders_vendororder WHERE id = %s FOR UPDATE", [self.o["id"]]),
            ("SELECT 1 FROM trade_tradeorder WHERE id = %s FOR UPDATE", [seller_order.id]),
            ("UPDATE purchasing_purchaseorder SET is_void = false WHERE id = %s", [po_phones.id]),
            ("UPDATE trade_tradeorderline SET received_qty = 2 WHERE id = %s", [self.phone_line["id"]]),
            ("UPDATE trade_tradeshipmentserial SET received = true", []),
        ])
        r = self.b.admin.post(f"/api/v1/purchase-orders/{po_cases.id}/void/", {}, format="json")
        self.assertGreater(time.monotonic() - began, 0.5)
        self.assertEqual(r.status_code, 200, r.content.decode())
        got = {l.id: l.received_qty for l in TradeOrderLine.objects.all()}
        self.assertEqual((got[self.case_line["id"]], got[self.phone_line["id"]]), (0, 2))        # A 清掉了、B 還在
        self.assertEqual(TradeShipmentSerial.objects.filter(received=True).count(), 2)
        # 所以賣家取消不了 B 的那一次出貨
        phone_shipment = self.a.admin.get(f"{T}orders/{seller_order.id}/").json()["shipments"][1]
        self.assertEqual(self.a.admin.post(f"{T}shipments/{phone_shipment['id']}/void/", {}, format="json").status_code, 400)

    def test_a_return_waits_for_the_wholesale_order_without_holding_the_sales_order(self):
        """整張銷退照批發的順序鎖(批發單在銷貨單之前)。等批發單的時候如果已經握著銷貨單,就會跟同一次出貨的「取消出貨」互相等(死結)。"""
        shipped = self.seller_ship(self.o["vendor_order_no"], lines=[{"line": self.case_line["id"], "qty": 4, "serials": []}])
        so_id = shipped["shipments"][0]["sales_order"]
        began = self.meanwhile([("SELECT 1 FROM trade_tradeorder WHERE id = %s FOR UPDATE", [shipped["id"]])], hold=1.5)
        result = {}

        def give_back():
            try:
                result["r"] = self.a.admin.post("/api/v1/sales-returns/", {"original_so": so_id, "payment_method": "peer"}, format="json")
            finally:
                connections.close_all()

        t = threading.Thread(target=give_back)
        t.start()
        time.sleep(0.6)                      # 銷退這時候應該卡在等批發單
        third = connections.create_connection("default")
        try:
            third.ensure_connection()
            third.set_autocommit(False)
            with third.cursor() as cur:
                try:
                    cur.execute("SELECT 1 FROM sales_salesorder WHERE id = %s FOR UPDATE NOWAIT", [so_id])
                    sales_order_was_free = True
                except OperationalError:
                    sales_order_was_free = False
            third.rollback()
        finally:
            third.close()
        t.join(10)
        self.assertGreater(time.monotonic() - began, 1.0)
        self.assertTrue(sales_order_was_free, "銷退在等批發單的時候已經鎖住銷貨單了")
        self.assertEqual(result["r"].status_code, 201, result["r"].content.decode())
