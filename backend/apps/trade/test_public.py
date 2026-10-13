"""對外的接法:不在這套 POS 上的系統用金鑰來買(`/api/trade/v2/…`),以及這套 POS 當買家、跟外面照 v2 的賣家買。跑法:manage.py test apps.trade.test_public

要守住的:
1. 金鑰只在發的那一次看得到(資料庫只有雜湊);換一把舊的立刻失效;沒有金鑰 / 不認得的金鑰什麼都拿不到。
2. 一把金鑰只認得一家賣家的一個同行:看不到別的同行的單、賣家的成本、出貨之前的序號。
3. 不往來 / 賣家關掉批發:看商品與下單回 403,自己已經有的單照樣查得到。賣家的資料還原中:一律 503。
4. 每分鐘有上限。建外部同行、換金鑰只有管理員。
5. 外面的單在賣家那邊分得出來(對外、怎麼聯絡、怎麼取貨、預收多少)。
6. 這套 POS 當買家:只有平台標成新格式的廠商才會問「會哪些」;會的才出現取消、對帳單,入庫帶序號。
"""
import json
from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.backup.tests.factory import Company
from apps.catalog.models import Product
from apps.inventory.models import ProductSerial, StockBalance
from apps.tenants.models import UserProfile
from apps.vendor_orders import standard
from apps.vendor_orders.models import Vendor, VendorOrder

from . import keys
from .models import TradeKey, TradeOrder, TradeOrderLine, TradePartner, TradeUnit

T = "/api/v1/trade/"
P = "/api/trade/v2"


class _Public(TestCase):
    def setUp(self):
        self.a = Company("a", "甲通訊行", "甲")
        self.b = Company("b", "乙通訊行", "乙")
        self.used = Product.objects.create(
            tenant=self.a.tenant, category=self.a.cat_phone, name="甲 中古 iPhone 13 128GB", is_secondhand=True, list_price=15000)
        r = self.a.admin.post(T + "settings/", {"is_open": True, "unit_rule": "price_minus", "unit_value": 1000}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        rows = [{"sn": sn, "grade": "A", "cost": "12000", "price": "16000", "battery": 90, "note": "小刮"} for sn in ("U001", "U002")]
        self.a._post("/api/v1/purchase-orders/", {
            "supplier": self.a.supplier.id, "warehouse": self.a.wh.id, "tax_method": "untaxed",
            "items": [{"product": self.used.id, "qty": 2, "unit_price": "12000", "serial_numbers": rows}]})
        self.a.purchase(case_qty=10, phone_serials=["N001", "N002"])
        self.a.admin.post(T + "products/", {"rows": [{"product": self.a.case.id, "is_listed": True}]}, format="json")
        made = self.external("外面的丁通訊", "0911-222-333 LINE @ding")
        self.partner, self.key = TradePartner.objects.get(pk=made["partner"]["id"]), made["key"]
        self.n = 0

    def external(self, name, contact, client=None, expect=201, **extra):
        r = (client or self.a.admin).post(T + "partners/external/", {"name": name, "contact": contact, **extra}, format="json")
        self.assertEqual(r.status_code, expect, r.content.decode())
        return r.json()

    def call(self, method, path, body=None, key=None, expect=None):
        client = APIClient()
        headers = {} if key is False else {"HTTP_AUTHORIZATION": f"Bearer {self.key if key is None else key}"}
        r = client.generic(method, P + path, data="" if body is None else json.dumps(body), content_type="application/json", **headers)
        if expect is not None:
            self.assertEqual(r.status_code, expect, r.content.decode())
        return r

    def unit(self, sn):
        return TradeUnit.objects.get(serial__serial_no=sn).id

    def buy(self, items, expect=200, **extra):
        self.n += 1
        return self.call("POST", "/orders", {"idempotency_key": f"ding-key-{self.n:04d}", "items": items, **extra}, expect=expect).json()

    def seller_ship(self, order_no):
        order = TradeOrder.objects.get(no=order_no)
        data = self.a.admin.get(f"{T}orders/{order.id}/").json()
        lines = [{"line": l["id"], "qty": l["open_qty"], "serials": [l["unit"]["serial"]] if l["unit"] else []} for l in data["lines"] if l["open_qty"]]
        self.n += 1
        r = self.a.admin.post(f"{T}orders/{order.id}/ship/", {"request_key": f"ship-pub-{self.n:04d}", "warehouse": self.a.wh.id, "lines": lines}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        return r.json()


class KeyTests(_Public):
    def test_the_key_is_shown_once_and_only_its_hash_is_kept(self):
        self.assertTrue(self.key.startswith("mpk_") and len(self.key) >= 40)
        row = TradeKey.objects.get()
        self.assertEqual((row.hint, row.partner_id, len(row.key_hash)), (self.key[:8], self.partner.id, 64))
        self.assertNotIn(self.key, json.dumps(list(TradeKey.objects.values("key_hash", "hint")), default=str))
        listing = self.a.admin.get(T + "partners/")
        self.assertNotIn(self.key, listing.content.decode())
        mine = next(p for p in listing.json()["partners"] if p["id"] == self.partner.id)
        self.assertEqual((mine["kind"], mine["status"], mine["terms"], mine["contact"], mine["key_hint"]),
                         ("external", "approved", "匯款", "0911-222-333 LINE @ding", self.key[:8]))

    def test_without_a_valid_key_there_is_nothing(self):
        invite = self.a.admin.post(T + "invites/", {}, format="json").json()["code"]
        for bad in (False, "", "mpk_" + "x" * 40, invite, self.key[:-1], self.key + "x", "Token abc"):
            for method, path in (("GET", "/products"), ("GET", "/capabilities"), ("GET", "/orders"), ("POST", "/orders"), ("GET", "/")):
                r = self.call(method, path, {} if method == "POST" else None, key=bad)
                self.assertEqual((r.status_code, r.json()), (401, {"ok": False, "error": "金鑰不對或已經作廢", "code": "unauthorized"}), (bad, path))
                self.assertEqual(r["Cache-Control"], "no-store")
        self.assertEqual(TradeOrder.objects.count(), 0)

    def test_a_new_key_kills_the_old_one(self):
        r = self.a.admin.post(f"{T}partners/{self.partner.id}/key/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        new = r.json()["key"]
        self.assertNotEqual(new, self.key)
        self.call("GET", "/products", expect=401)
        self.call("GET", "/products", key=new, expect=200)
        self.assertEqual(TradeKey.objects.count(), 1)

    def test_only_a_manager_of_that_company_issues_keys(self):
        self.external("別人", "09", client=self.a.clerk, expect=403)
        self.assertEqual(self.a.clerk.post(f"{T}partners/{self.partner.id}/key/", {}, format="json").status_code, 403)
        self.assertEqual(self.b.admin.post(f"{T}partners/{self.partner.id}/key/", {}, format="json").status_code, 404)
        for name, contact in (("", "09"), ("有名字", ""), ("x" * 121, "09")):
            self.external(name, contact, expect=400)
        self.assertEqual(TradePartner.objects.count(), 1)
        self.call("GET", "/products", expect=200)                      # 原本那一把沒有被換掉
        # 平台內的同行不用金鑰
        inside = TradePartner.objects.create(tenant=self.a.tenant, name="乙", buyer_uuid=self.b.tenant.backup_uuid, status="approved")
        self.assertEqual(self.a.admin.post(f"{T}partners/{inside.id}/key/", {}, format="json").status_code, 400)

    def test_the_hundred_and_twenty_first_call_in_a_minute_is_refused(self):
        for n in range(keys.PER_MINUTE):
            self.assertEqual(self.call("GET", "/orders").status_code, 200, n)
        self.assertEqual(self.call("GET", "/orders").status_code, 429)
        self.assertEqual(self.call("POST", "/orders", {"idempotency_key": "ding-limit-01", "items": []}).status_code, 429)
        self.assertEqual(TradeOrder.objects.count(), 0)

    def test_there_is_a_limit_per_minute(self):
        self.call("GET", "/capabilities", expect=200)
        TradeKey.objects.update(window_count=keys.PER_MINUTE)
        r = self.call("GET", "/capabilities", expect=429)
        self.assertEqual(r.json()["code"], "too_many")
        TradeKey.objects.update(window_start=timezone.now() - timedelta(seconds=61))
        self.call("GET", "/capabilities", expect=200)
        self.assertEqual(TradeKey.objects.get().window_count, 1)

    def test_the_sellers_restore_shuts_the_door(self):
        from apps.backup.models import TenantMaintenance

        TenantMaintenance.objects.create(tenant=self.a.tenant, active=True)
        for method, path in (("GET", "/products"), ("POST", "/orders"), ("GET", "/orders")):
            r = self.call(method, path, {"idempotency_key": "ding-restore-1", "items": []} if method == "POST" else None, expect=503)
            self.assertEqual(r.json()["code"], "maintenance")
        self.assertEqual(TradeOrder.objects.count(), 0)

    def test_keys_stay_out_of_company_backups(self):
        from apps.backup.registry import CLEARED_ON_RESTORE, EXCLUDED, REGISTRY

        self.assertEqual(REGISTRY["trade.TradeKey"].kind, EXCLUDED)
        self.assertIn("trade.TradeKey", CLEARED_ON_RESTORE)


class BuyingTests(_Public):
    def test_what_the_outside_buyer_sees(self):
        caps = self.call("GET", "/capabilities", expect=200).json()
        self.assertEqual((caps["ok"], caps["seller"]["name"], caps["buyer"]["name"], caps["buyer"]["payment_method"]),
                         (True, "甲通訊行", "外面的丁通訊", "匯款"))
        self.assertTrue({"products", "orders", "cancel", "shipments", "serials", "receipts", "statements", "units"} <= set(caps["capabilities"]))
        r = self.call("GET", "/products", expect=200)
        rows = {p["sku"]: p for p in r.json()["products"]}
        self.assertEqual(set(rows), {self.used.sku, self.a.case.sku})
        self.assertEqual((rows[self.a.case.sku]["unit_price"], len(rows[self.used.sku]["specs"])), (390, 2))
        for secret in ("U001", "U002", "12000"):
            self.assertNotIn(secret, r.content.decode())

    def test_an_order_over_http_lands_like_any_other_and_says_who_it_is(self):
        got = self.buy([{"sku": self.used.sku, "spec_id": self.unit("U001"), "qty": 1}, {"sku": self.a.case.sku, "spec_id": None, "qty": 2}],
                       delivery_method="宅配", ship_to={"name": "丁老闆", "phone": "0911222333", "address": "台中市西屯區 1 號"}, payment_method="月結")
        self.assertEqual((got["ok"], got["status"], got["total_amount"], got["payment_method"]), (True, "已接單", 15780, "匯款"))
        again = self.call("POST", "/orders", {"idempotency_key": "ding-key-0001", "items": []}, expect=409).json()
        self.assertEqual(again["order_no"], got["order_no"])
        row = self.a.clerk.get(f"{T}orders/").json()["results"][0]
        self.assertEqual((row["no"], row["partner_name"], row["partner_kind"], row["partner_contact"], row["delivery_method"], row["ship_name"],
                          row["ship_address"], row["payment_method"], row["credit"]),
                         (got["order_no"], "外面的丁通訊", "external", "0911-222-333 LINE @ding", "宅配", "丁老闆", "台中市西屯區 1 號", "匯款", 0))
        # 他先匯了錢:出貨的人在那張單上看得到預收多少
        self.a.admin.post(T + "payments/", {"partner": self.partner.id, "amount": 15780, "request_key": "pay-pub-00001"}, format="json")
        self.assertEqual(self.a.clerk.get(f"{T}orders/").json()["results"][0]["credit"], 15780)
        shipped = self.seller_ship(got["order_no"])
        self.assertEqual((shipped["status_text"], shipped["owed"], shipped["paid"], shipped["credit"]), ("已出貨", 15780, 15780, 0))
        mine = self.call("GET", f"/orders/{got['order_no']}", expect=200).json()["order"]
        self.assertEqual((mine["status"], mine["payment_status"], mine["shipments"][0]["items"][0]["serials"][0]["sn"]), ("已出貨", "已收款", "U001"))
        state = self.call("GET", "/statements", expect=200).json()
        self.assertEqual((state["totals"], state["orders"][0]["order_no"]), ({"shipped": 15780, "paid": 15780, "due": 0}, got["order_no"]))
        listed = self.call("GET", "/orders?limit=5", expect=200).json()["orders"]
        self.assertEqual([o["order_no"] for o in listed], [got["order_no"]])

    def test_an_order_has_to_say_how_it_is_collected(self):
        item = [{"sku": self.a.case.sku, "spec_id": None, "qty": 1}]
        for extra in ({"delivery_method": "宅配"}, {"delivery_method": "宅配", "ship_to": {"name": "丁", "phone": "09"}},
                      {"delivery_method": "快遞"}):
            self.assertEqual(self.buy(item, expect=400, **extra)["code"], "bad_ship", extra)
        self.assertEqual(TradeOrder.objects.count(), 0)
        self.buy(item)                                              # 沒講 = 自取
        self.assertEqual(TradeOrder.objects.get().delivery_method, "自取")

    def test_what_is_not_json_is_refused_politely(self):
        r = APIClient().generic("POST", P + "/orders", data="not json", content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {self.key}")
        self.assertEqual((r.status_code, r.json()["code"]), (400, "bad_json"))
        r = APIClient().generic("POST", P + "/orders", data="[1]", content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {self.key}")
        self.assertEqual((r.status_code, r.json()["code"]), (400, "bad_json"))
        self.assertEqual(self.call("GET", "/nothing-here", expect=404).json()["code"], "not_found")
        self.assertEqual(self.call("DELETE", "/orders").status_code, 405)

    def test_cancel_and_report_received_over_http(self):
        got = self.buy([{"sku": self.used.sku, "spec_id": self.unit("U001"), "qty": 1}, {"sku": self.a.case.sku, "spec_id": None, "qty": 2}])
        no = got["order_no"]
        self.seller_ship(no)
        body = {"items": [{"sku": self.used.sku, "spec_id": self.unit("U001"), "received_qty": 1, "serials": [{"imei": "", "sn": "U001"}]},
                          {"sku": self.a.case.sku, "spec_id": None, "received_qty": 2, "serials": []}]}
        self.call("POST", f"/orders/{no}/received", body, expect=200)
        self.assertEqual(sorted(l.received_qty for l in TradeOrderLine.objects.all()), [1, 2])
        shipment = self.a.admin.get(f"{T}orders/{TradeOrder.objects.get().id}/").json()["shipments"][0]
        self.assertEqual(self.a.admin.post(f"{T}shipments/{shipment['id']}/void/", {}, format="json").status_code, 400)
        other = self.buy([{"sku": self.used.sku, "spec_id": self.unit("U002"), "qty": 1}])
        self.assertEqual(self.call("POST", f"/orders/{other['order_no']}/cancel", {}, expect=200).json()["status"], "已取消")
        self.assertEqual(self.call("POST", f"/orders/{other['order_no']}/cancel", {}, expect=400).json()["code"], "not_cancellable")

    def test_since_is_read_the_way_urls_are_written(self):
        from urllib.parse import quote

        old = self.buy([{"sku": self.a.case.sku, "spec_id": None, "qty": 1}])
        new = self.buy([{"sku": self.a.case.sku, "spec_id": None, "qty": 1}])
        TradeOrder.objects.filter(no=old["order_no"]).update(changed_at=timezone.now() - timedelta(days=2))
        cut = timezone.localtime(timezone.now() - timedelta(days=1)).isoformat(timespec="seconds")       # 例 2026-10-13T06:10:00+08:00
        for written in (quote(cut, safe=""), cut, cut.replace("+", "%2B")):
            got = self.call("GET", f"/orders?limit=100&since={written}", expect=200).json()["orders"]
            self.assertEqual([o["order_no"] for o in got], [new["order_no"]], written)
        self.assertEqual(len(self.call("GET", "/orders?limit=100", expect=200).json()["orders"]), 2)
        for bad in ("yesterday", "2026-13-40T00:00:00", "%00"):
            self.assertEqual(self.call("GET", f"/orders?since={bad}", expect=400).json()["code"], "bad_since", bad)
        self.assertEqual(self.call("GET", "/statements?from=someday", expect=400).json()["code"], "bad_date")
        self.assertEqual(len(self.call("GET", "/statements?from=2020-01-01&to=2099-12-31", expect=200).json()["orders"]), 0)

    def test_a_report_with_the_wrong_shapes_is_refused_not_a_crash(self):
        got = self.buy([{"sku": self.a.case.sku, "spec_id": None, "qty": 2}])
        self.seller_ship(got["order_no"])
        row = {"sku": self.a.case.sku, "spec_id": None, "received_qty": 1, "serials": []}
        for bad in ({**row, "spec_id": []}, {**row, "spec_id": {}}, {**row, "spec_id": "x"}, {**row, "spec_id": True}, {**row, "sku": ["a"]},
                    {**row, "sku": None}, {**row, "received_qty": "1"}, {**row, "serials": "abc"}, {**row, "serials": [["x"]]}, [], "x", 5, None):
            r = self.call("POST", f"/orders/{got['order_no']}/received", {"items": [bad]})
            self.assertEqual((r.status_code, r.json()["code"]), (400, "bad_item"), bad)
        self.assertEqual(self.call("POST", f"/orders/{got['order_no']}/received", {"items": {"a": 1}}).status_code, 400)
        self.assertEqual(TradeOrderLine.objects.get().received_qty, 0)
        self.call("POST", f"/orders/{got['order_no']}/received", {"items": [row]}, expect=200)
        self.assertEqual(TradeOrderLine.objects.get().received_qty, 1)

    def test_an_unexpected_error_still_answers_in_the_agreed_shape(self):
        with mock.patch("apps.trade.api.handle", side_effect=RuntimeError("boom")), self.assertLogs("apps.trade.public_views", level="ERROR"):
            r = self.call("GET", "/products")
        self.assertEqual((r.status_code, r.json()), (500, {"ok": False, "error": "系統出錯了,請稍後再試", "code": "error"}))

    def test_one_key_cannot_reach_another_buyers_orders(self):
        mine = self.buy([{"sku": self.used.sku, "spec_id": self.unit("U001"), "qty": 1}])
        other = self.external("外面的戊", "0922")
        theirs = self.call("POST", "/orders", {"idempotency_key": "wu-key-00001", "items": [{"sku": self.used.sku, "spec_id": self.unit("U002"), "qty": 1}]},
                           key=other["key"], expect=200).json()
        for method, path in (("GET", f"/orders/{mine['order_no']}"), ("POST", f"/orders/{mine['order_no']}/cancel"),
                             ("POST", f"/orders/{mine['order_no']}/received")):
            self.assertEqual(self.call(method, path, {} if method == "POST" else None, key=other["key"]).status_code, 404, path)
        self.assertEqual([o["order_no"] for o in self.call("GET", "/orders", key=other["key"]).json()["orders"]], [theirs["order_no"]])
        self.assertEqual(TradeOrder.objects.get(no=mine["order_no"]).status, "accepted")
        # 同一把鑰匙(防重複用的)在兩個買家之間不相干
        again = self.call("POST", "/orders", {"idempotency_key": "ding-key-0001", "items": [{"sku": self.a.case.sku, "spec_id": None, "qty": 1}]},
                          key=other["key"], expect=200).json()
        self.assertNotEqual(again["order_no"], mine["order_no"])

    def test_blocked_or_closed_keeps_only_what_the_buyer_already_has(self):
        got = self.buy([{"sku": self.used.sku, "spec_id": self.unit("U001"), "qty": 1}])
        self.a.admin.post(f"{T}partners/{self.partner.id}/", {"status": "blocked"}, format="json")
        for method, path in (("GET", "/products"), ("GET", "/capabilities"), ("POST", "/orders")):
            body = {"idempotency_key": "ding-blocked-1", "items": [{"sku": self.a.case.sku, "spec_id": None, "qty": 1}]} if method == "POST" else None
            self.assertEqual(self.call(method, path, body, expect=403).json()["code"], "forbidden")
        self.call("GET", f"/orders/{got['order_no']}", expect=200)
        self.call("GET", "/statements", expect=200)
        self.a.admin.post(f"{T}partners/{self.partner.id}/", {"status": "approved"}, format="json")
        self.a.admin.post(T + "settings/", {"is_open": False}, format="json")
        self.call("GET", "/products", expect=403)
        self.call("GET", "/orders", expect=200)


# ── 這套 POS 當買家,跟外面照 v2 的賣家買(這裡的「外面」= 這台伺服器自己的對外端點)────────────────
def loop(method, path, key, body=None, timeout=15, *, base, name="廠商"):
    r = APIClient().generic(method, P + path, data="" if body is None else json.dumps(body), content_type="application/json",
                            HTTP_AUTHORIZATION=f"Bearer {key}")
    return standard.Reply(r.status_code, r.json())


class OutsideSellerTests(_Public):
    """乙通訊行(買家)照原本「貼金鑰」的做法,跟一家照 v2 的賣家(甲的對外端點)叫貨。"""

    V, LINKS = "/api/v1/vendor-orders/", "/api/v1/vendor-links/"

    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(standard, "_call", loop)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.vendor = Vendor.objects.create(code="ext-a", name="甲(對外)", protocol="standard", api_base="https://loop.test/api/trade/v2",
                                            key_prefix="mpk_", v2=True)
        self.b_used = Product.objects.create(tenant=self.b.tenant, category=self.b.cat_phone, name="乙 中古 iPhone 13", is_secondhand=True, list_price=17000)

    def link(self, expect=200, **extra):
        r = self.b.admin.post(self.LINKS, {"warehouse": self.b.wh.id, "vendor": "ext-a", "key": self.key, "delivery_method": "自取",
                                           "invoice_email": "b@example.com", **extra}, format="json")
        self.assertEqual(r.status_code, expect, r.content.decode())
        return r.json()

    def order(self, lines):
        self.n += 1
        r = self.b.clerk.post(self.V, {"request_key": f"draft-out-{self.n:04d}", "warehouse": self.b.wh.id, "vendor": "ext-a", "lines": lines}, format="json")
        self.assertEqual(r.status_code, 201, r.content.decode())
        return r.json()

    def test_saving_the_key_learns_what_the_seller_can_do_and_who_it_says_it_is(self):
        row = self.link()
        self.vendor.refresh_from_db()
        self.assertEqual((row["ready"], row["remote_name"], row["can_statement"], row["platform"]), (True, "甲通訊行", True, False))
        self.assertIn("cancel", self.vendor.capabilities)

    def test_a_vendor_not_marked_as_the_new_format_is_never_asked(self):
        Vendor.objects.filter(pk=self.vendor.pk).update(v2=False)
        calls = []

        def spy(method, path, key, body=None, timeout=15, *, base, name="廠商"):
            calls.append((method, path))
            return loop(method, path, key, body, timeout, base=base, name=name)

        with mock.patch.object(standard, "_call", spy):
            row = self.link()
        self.assertEqual(calls, [("GET", "/products")])
        self.vendor.refresh_from_db()
        self.assertEqual((row["remote_name"], row["can_statement"], self.vendor.capabilities), ("", False, None))
        got = self.order([{"key": self.a.case.sku, "packs": 1}])
        self.assertFalse(got["can_cancel"])
        r = self.b.clerk.post(f"{self.V}{got['id']}/cancel/", {"cancelled": True}, format="json")
        self.assertEqual((r.status_code, TradeOrder.objects.get().status), (400, "accepted"))
        # 不經過畫面的那一層直接叫也一樣:對方沒說會取消就不去打它
        from apps.vendor_orders import services

        with self.assertRaises(services.VendorError):
            services.cancel(VendorOrder.objects.get())
        self.assertEqual(TradeOrder.objects.get().status, "accepted")
        self.assertEqual(self.b.clerk.get(f"{self.V}statement/?warehouse={self.b.wh.id}&vendor=ext-a").status_code, 400)

    def test_ordering_progress_cancel_receiving_and_statement_all_work_over_http(self):
        self.link()
        r = self.b.clerk.get(f"{self.V}catalog/?warehouse={self.b.wh.id}&vendor=ext-a")
        rows = {x["key"]: x for x in r.json()["rows"]}
        unit_key = f"{self.used.sku}#{self.unit('U001')}"
        self.assertEqual((rows[unit_key]["per_unit"], rows[unit_key]["unit_price"], rows[self.a.case.sku]["unit_price"]), (True, "15000.00", "390.00"))
        got = self.order([{"key": unit_key, "packs": 1}, {"key": self.a.case.sku, "packs": 2}])
        self.assertEqual((got["state"], got["total_amount"], got["can_cancel"], got["payment_method"]), ("placed", "15780.00", True, "匯款"))
        spare = self.order([{"key": f"{self.used.sku}#{self.unit('U002')}", "packs": 1}])
        r = self.b.clerk.post(f"{self.V}{spare['id']}/cancel/", {"cancelled": True}, format="json")
        self.assertEqual((r.status_code, r.json()["vendor_status"]), (200, "已取消"))
        self.seller_ship(got["vendor_order_no"])
        plan = self.b.admin.get(f"{self.V}{got['id']}/receiving/").json()
        unit = next(l for l in plan["lines"] if l["per_unit"])
        cases = next(l for l in plan["lines"] if not l["per_unit"])
        self.assertEqual((unit["serials"][0]["sn"], unit["strict_shipped"], cases["suggested_qty"]), ("U001", True, 2))
        with self.captureOnCommitCallbacks(execute=True):
            r = self.b.admin.post(f"{self.V}{got['id']}/receive/", {"request_key": "recv-out-0001", "freight": 0, "lines": [
                {"key": unit["key"], "qty": 1, "product": self.b_used.id}, {"key": cases["key"], "qty": 2, "product": self.b.case.id}]}, format="json")
        self.assertEqual(r.status_code, 201, r.content.decode())
        self.assertEqual(ProductSerial.objects.get(tenant=self.b.tenant, serial_no="U001").status, "in_stock")
        self.assertEqual(StockBalance.objects.get(tenant=self.b.tenant, product=self.b.case, warehouse=self.b.wh).qty, 2)
        # 提交之後跟賣家報了收了多少 → 賣家取消不了那一次出貨
        seller = TradeOrder.objects.get(no=got["vendor_order_no"])
        self.assertEqual(sorted(l.received_qty for l in seller.lines.all()), [1, 2])
        shipment = self.a.admin.get(f"{T}orders/{seller.id}/").json()["shipments"][0]
        self.assertEqual(self.a.admin.post(f"{T}shipments/{shipment['id']}/void/", {}, format="json").status_code, 400)
        r = self.b.clerk.get(f"{self.V}statement/?warehouse={self.b.wh.id}&vendor=ext-a")
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.assertEqual((r.json()["totals"], r.json()["orders"][0]["order_no"], r.json()["orders"][0]["payment_status"]),
                         ({"shipped": 15780, "paid": 0, "due": 15780}, got["vendor_order_no"], "未收款"))

    def test_the_buyers_amounts_follow_the_seller_after_a_partial_shipment_and_a_cancel(self):
        """訂兩個(每個 390)、賣家先出一個並收運費 120、買家取消剩下的:買家這邊的總額與運費要是賣家現在的 510 / 120。"""
        self.link()
        got = self.order([{"key": self.a.case.sku, "packs": 2}])
        self.assertEqual((got["total_amount"], got["shipping_fee"]), ("780.00", "0.00"))
        seller = TradeOrder.objects.get()
        line = seller.lines.get()
        self.n += 1
        r = self.a.admin.post(f"{T}orders/{seller.id}/ship/", {"request_key": f"ship-pub-{self.n:04d}", "warehouse": self.a.wh.id,
                                                              "shipping_fee": 120, "lines": [{"line": line.id, "qty": 1, "serials": []}]}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        r = self.b.clerk.post(f"{self.V}{got['id']}/cancel/", {"cancelled": True}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.assertEqual((r.json()["vendor_status"], r.json()["total_amount"], r.json()["shipping_fee"]), ("已出貨", "510.00", "120.00"))
        # 之後按更新進度也是對方現在的數
        VendorOrder.objects.update(total_amount=1, shipping_fee=1)
        mine = self.b.clerk.post(self.V + "sync/", {"warehouse": self.b.wh.id, "vendor": "ext-a"}, format="json").json()["results"][0]
        self.assertEqual((mine["total_amount"], mine["shipping_fee"]), ("510.00", "120.00"))

    def test_the_statement_needs_the_ordering_ability(self):
        self.link()
        UserProfile.objects.filter(user=self.b.clerk_user).update(denied_abilities=["vendor_order"])
        self.b.clerk_user.profile.refresh_from_db()
        self.assertEqual(self.b.clerk.get(f"{self.V}statement/?warehouse={self.b.wh.id}&vendor=ext-a").status_code, 403)
        self.assertEqual(VendorOrder.objects.count(), 0)
