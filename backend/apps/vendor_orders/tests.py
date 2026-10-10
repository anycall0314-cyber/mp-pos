"""廠商叫貨(第一步:叫貨)。自動測試不打真的膜總裁:對外的那一個口(`standard._call`)換成假的。

假的膜總裁照那個專案實際的行為寫(2026-10-10 讀過程式、打過「讀」的):
- 金鑰不對 → 401;商品清單回這個帳號的價錢;
- 下單:同一把金鑰 + 同一把鑰匙已經成立過 → 409 帶單號;成功只回單號 / 總額 / 運費;被擋(400)不佔鑰匙。
"""
import http.server
import json
import threading
import urllib.parse
from decimal import Decimal
from unittest import mock

from django.test import SimpleTestCase, TestCase, override_settings

from apps.backup import registry
from apps.backup.tests.factory import Company
from apps.backup.tests.test_backup_restore import _Base as BackupBase
from apps.tenants.models import UserProfile

from . import secrets, services, standard
from .models import Vendor, VendorCategory, VendorLink, VendorOrder, VendorSecret

KEY = "mk_live_" + "a1B2c3D4" * 5 + "xyz"          # 測試用的假金鑰
OTHER_KEY = "mk_live_" + "Z9y8X7w6" * 5 + "abc"
MOCEO_BASE = "https://moceo.test/api/v1"            # 測試裡膜總裁的網址(假的;請求會被 FakeVendor 接走)
CLIENT = standard.Client(MOCEO_BASE, "膜總裁")
LINKS = "/api/v1/vendor-links/"
ORDERS = "/api/v1/vendor-orders/"
CATALOG = "/api/v1/vendor-orders/catalog/"
SYNC = "/api/v1/vendor-orders/sync/"
PRODUCTS = [
    {"sku": "G02", "name": "高透亮面", "kind": "片材規格", "unit": "片", "size": "125*196", "pack_qty": 25,
     "unit_price": 150, "specs": []},
    {"sku": "G01", "name": "D3O 7H", "kind": "片材規格", "unit": "片", "size": None, "pack_qty": 10,
     "unit_price": 280, "specs": []},
    {"sku": "S09", "name": "套裝(未報價)", "kind": "片材規格", "unit": "片", "size": None, "pack_qty": 5,
     "unit_price": None, "specs": []},
    {"sku": "M01", "name": "膜速箱", "kind": "膜速箱", "unit": "片", "size": None, "pack_qty": 5, "unit_price": 70,
     "specs": [{"id": 901, "code": "K43", "name": "iPhone 15 Pro", "unit_price": 75},
               {"id": 902, "code": "K44", "name": None, "unit_price": 70}]},
]


def ensure_vendor(code="moceo", name="膜總裁", base=MOCEO_BASE, prefix="mk_live_", categories=("保護貼",), **more):
    """名單上要有這一家(不靠資料庫變更放進去的那一筆:別的測試清過整個資料庫之後它就不在了)。"""
    vendor, _ = Vendor.objects.update_or_create(code=code, defaults=dict(
        name=name, api_base=base, key_prefix=prefix, protocol=Vendor.Protocol.STANDARD, is_active=True, **more))
    vendor.categories.set([VendorCategory.objects.get_or_create(name=n)[0] for n in categories])
    return vendor


class FakeNet:
    """好幾家假的廠商:照請求打到哪個網址,交給哪一家(各自的金鑰、各自的訂單)。打到名單以外的網址就是錯。"""

    def __init__(self, **by_base):
        self.by_base = by_base

    def __call__(self, method, path, key, body=None, timeout=15, *, base, name="廠商"):
        return self.by_base[base](method, path, key, body, timeout, base=base, name=name)


class FakeVendor:
    """假的膜總裁。`script` 排的是接下來幾次下單要發生什麼事:
    "down" = 連不上(沒成立);"lost" = 成立了但回應沒回來;(狀態碼, 原因) = 明確被擋。"""

    def __init__(self, keys=None, order_prefix="MO"):
        self.calls, self.script = [], []
        self.bases = []             # 每一個請求打到哪個網址
        self.order_prefix = order_prefix
        self.keys = {KEY} if keys is None else set(keys)
        self.placed = {}            # (金鑰, 鑰匙) → 那張單
        self.outside = []           # 不是從 POS 叫的單
        self.shipping_fee = 0
        self.price_drift = 0        # 下單時每片比清單貴多少(模擬清單與實際不一樣)
        self.read_down = False
        self.sandbox = True         # 這把金鑰是不是沙盒;None = 回應裡沒有這一欄(舊版的膜總裁)

    def posts(self):
        return [c for c in self.calls if c[0] == "POST"]

    def __call__(self, method, path, key, body=None, timeout=15, *, base=None, name="廠商"):
        self.bases.append(base)
        reply = self._answer(method, path, key, body)
        if reply.status != 401 and self.sandbox is not None:     # 金鑰驗過之後的每一個回應都帶,錯誤的也帶
            reply.data["sandbox"] = self.sandbox
        return reply

    def _answer(self, method, path, key, body):
        self.calls.append((method, path, key, body))
        if method == "GET" and self.read_down:
            raise standard.Unreachable("連不到膜總裁(URLError)")
        if key not in self.keys:
            return standard.Reply(401, {"ok": False, "error": "金鑰無效或已作廢"})
        if method == "GET" and path == "/products":
            return standard.Reply(200, {"ok": True, "products": PRODUCTS})
        if method == "GET" and path.startswith("/orders?"):
            mine = [o for (k, _), o in self.placed.items() if k == key]
            return standard.Reply(200, {"ok": True, "orders": [self._row(o) for o in [*self.outside, *mine]]})
        if method == "GET" and path.startswith("/orders/"):
            no = urllib.parse.unquote(path.split("/orders/", 1)[1])
            hit = [o for (k, _), o in self.placed.items() if k == key and o["order_no"] == no] \
                + [o for o in self.outside if o["order_no"] == no]
            if not hit:
                return standard.Reply(404, {"ok": False, "error": "找不到這張單"})
            return standard.Reply(200, {"ok": True, "order": self._detail(hit[0])})
        assert (method, path) == ("POST", "/orders"), (method, path)
        outcome = self.script.pop(0) if self.script else "ok"
        if outcome == "down":
            raise standard.Unreachable("連不到膜總裁(URLError)")
        if isinstance(outcome, tuple):
            return standard.Reply(outcome[0], {"ok": False, "error": outcome[1]})
        slot = (key, body["idempotency_key"])
        if slot in self.placed:
            return standard.Reply(409, {"ok": False, "error": "這個 idempotency_key 已經用過了",
                                     "order_no": self.placed[slot]["order_no"]})
        price = {p["sku"]: p["unit_price"] for p in PRODUCTS}
        spec_price = {s["id"]: s["unit_price"] for p in PRODUCTS for s in p["specs"]}
        goods = sum((spec_price.get(i["spec_id"], price[i["sku"]]) + self.price_drift) * i["qty"] for i in body["items"])
        order = {"order_no": f"{self.order_prefix}-20261010-{len(self.placed) + 1:03d}", "total_amount": goods + self.shipping_fee,
                 "shipping_fee": self.shipping_fee, "status": "待審核", "body": body,
                 "payment_method": body["payment_method"], "delivery_method": body["delivery_method"],
                 "items": [self.line(i["sku"], i["qty"], spec_id=i["spec_id"], drift=self.price_drift) for i in body["items"]]}
        self.placed[slot] = order
        if outcome == "lost":
            raise standard.Unreachable("連不到膜總裁(TimeoutError)")
        return standard.Reply(200, {"ok": True, "order_no": order["order_no"], "total_amount": order["total_amount"],
                                 "shipping_fee": order["shipping_fee"]})

    @staticmethod
    def line(sku, qty, *, spec_id=None, shipped=0, free=False, drift=0):
        """查單時的一行(欄位照膜總裁 2026-10-10 實際回的)。`free` = 瑕疵補發的免費列。"""
        product = next(p for p in PRODUCTS if p["sku"] == sku)
        spec = next((x for x in product["specs"] if x["id"] == spec_id), None)
        unit = 0 if free else (spec["unit_price"] if spec else product["unit_price"]) + drift
        return {"sku": sku, "name": product["name"], "unit": product["unit"], "pack_qty": product["pack_qty"],
                "spec_id": spec_id, "spec_code": spec["code"] if spec else None, "spec_name": spec["name"] if spec else None,
                "sale_type": "加購", "is_reissue": free, "qty": qty, "shipped_qty": shipped, "unit_price": unit,
                "subtotal": unit * qty}

    def find(self, order_no):
        return next(o for o in [*self.placed.values(), *self.outside] if o["order_no"] == order_no)

    def ship(self, order_no, **by_sku):
        """廠商出貨:`ship(單號)` 全出;`ship(單號, G02=25)` 只出這幾個。"""
        for item in self.find(order_no)["items"]:
            item["shipped_qty"] = by_sku.get(item["sku"], 0) if by_sku else item["qty"]

    def _detail(self, o):
        row = {**self._row(o), "shipping_fee": o.get("shipping_fee", 0), "payment_method": o.get("payment_method", "月結"),
               "delivery_method": o.get("delivery_method", "宅配")}
        if "items" in o:
            row["items"] = o["items"]
        return row

    @staticmethod
    def _row(o):
        return {"order_no": o["order_no"], "ordered_at": o.get("ordered_at", "2026-10-10T10:43:59+08:00"),
                "status": o.get("status", "待審核"), "payment_status": o.get("payment_status", "月結未到期"),
                "logistics_status": o.get("logistics_status", ""), "shipping_method": o.get("shipping_method", ""),
                "tracking_no": o.get("tracking_no", ""), "total_amount": o["total_amount"]}


class _Shop(TestCase):
    def setUp(self):
        self.c = Company("a", "甲通訊行", "甲")
        self.t = self.c.tenant
        self.wh1, self.wh2 = self.c.warehouses
        self.admin, self.clerk = self.c.admin, self.c.clerk
        self.moceo = ensure_vendor()
        self.vendor = FakeVendor()
        patcher = mock.patch.object(standard, "_call", self.vendor)
        patcher.start()
        self.addCleanup(patcher.stop)

    def link(self, store=None, client=None, **extra):
        body = {"warehouse": (store or self.wh1).id, "vendor": "moceo", "key": KEY, "ship_name": "甲湳雅店",
                "ship_phone": "035551234", "ship_address": "新竹市湳雅街 1 號", "invoice_email": "a@b.com", **extra}
        return (client or self.admin).post(LINKS, body, format="json")

    def order(self, lines=None, key="draft-0001", client=None, store=None, **extra):
        body = {"request_key": key, "warehouse": (store or self.wh1).id, "vendor": "moceo",
                "lines": [{"key": "G02", "packs": 2}] if lines is None else lines, **extra}
        return (client or self.clerk).post(ORDERS, body, format="json")

    def turn_off(self, *keys):
        UserProfile.objects.filter(user=self.c.clerk_user).update(denied_abilities=list(keys))
        self.c.clerk_user.profile.refresh_from_db()

    def assertNoKeyIn(self, response):
        text = response.content.decode()
        self.assertNotIn(KEY, text)
        self.assertNotIn(KEY[12:], text)


class LinkTests(_Shop):
    def test_a_manager_saves_the_key_encrypted_and_only_a_hint_comes_back(self):
        r = self.link()
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.assertNoKeyIn(r)
        self.assertEqual((r.json()["has_key"], r.json()["key_hint"], r.json()["saved"]), (True, KEY[:12], True))
        secret = VendorSecret.objects.get()
        self.assertNotIn(KEY, secret.wrapped)
        self.assertNotIn(KEY[12:], secret.wrapped)
        self.assertEqual(secrets.reveal(secret.link), KEY)
        self.assertEqual(secret.fingerprint, secrets.fingerprint(KEY))
        # 存之前拿它去打過一次廠商(確認廠商認得)
        self.assertEqual([c[:3] for c in self.vendor.calls], [("GET", "/products", KEY)])
        self.assertNoKeyIn(self.admin.get(LINKS))

    def test_every_store_is_listed_and_a_store_without_settings_starts_from_its_own_address(self):
        self.wh2.address, self.wh2.phone = "新竹市民生路 9 號", "035559999"
        self.wh2.save()
        self.link()
        rows = {row["warehouse"]: row for row in self.admin.get(LINKS).json()["results"]}
        self.assertEqual(set(rows), {self.wh1.id, self.wh2.id})
        self.assertEqual((rows[self.wh1.id]["has_key"], rows[self.wh2.id]["has_key"], rows[self.wh2.id]["saved"]),
                         (True, False, False))
        self.assertEqual((rows[self.wh2.id]["ship_name"], rows[self.wh2.id]["ship_phone"], rows[self.wh2.id]["ship_address"]),
                         ("甲民生店", "035559999", "新竹市民生路 9 號"))
        self.assertEqual(rows[self.wh1.id]["choices"]["payment_method"], ["月結", "貨到付款", "匯款"])

    def test_a_clerk_cannot_change_it_and_never_sees_the_hint(self):
        self.link()
        r = self.link(client=self.clerk, ship_name="我家")
        self.assertEqual(r.status_code, 403, r.content.decode())
        self.assertEqual(self.clerk.post(f"{LINKS}{self.wh1.id}/remove-key/").status_code, 403)
        self.assertEqual(VendorLink.objects.get().ship_name, "甲湳雅店")
        rows = self.clerk.get(LINKS).json()["results"]
        self.assertEqual([row["warehouse"] for row in rows], [self.wh1.id])          # 鎖在門市:只有自己那一家
        self.assertNotIn("key_hint", rows[0])
        self.assertEqual(rows[0]["has_key"], True)

    def test_a_key_the_vendor_does_not_know_is_not_saved(self):
        for key, text in ((OTHER_KEY, "不認得這把金鑰"), ("abc", "不像膜總裁的金鑰"), ("mk_live_ 有空白 " + "x" * 20, "不像"),
                          ("mk_test_" + "x" * 30, "不像")):
            r = self.link(key=key)
            self.assertEqual((r.status_code, text in r.json()["detail"]), (400, True), (key[:10], r.content.decode()))
            self.assertNotIn(key, r.content.decode())
        self.vendor.read_down = True
        r = self.link()
        self.assertEqual((r.status_code, "連不到膜總裁" in r.json()["detail"]), (400, True))
        self.assertEqual((VendorSecret.objects.count(), VendorLink.objects.count()), (0, 0))

    def test_settings_without_a_key_changing_and_removing_the_key(self):
        r = self.admin.post(LINKS, {"warehouse": self.wh1.id, "ship_name": "甲", "ship_phone": "03", "ship_address": "新竹",
                                    "invoice_email": "a@b.com"}, format="json")
        self.assertEqual((r.status_code, r.json()["has_key"], r.json()["saved"]), (200, False, True))
        self.assertEqual(self.vendor.calls, [])                                     # 沒有給金鑰就不打廠商
        self.link()
        self.vendor.keys.add(OTHER_KEY)
        r = self.link(key=OTHER_KEY)
        self.assertEqual(r.json()["key_hint"], OTHER_KEY[:12])
        self.assertEqual((VendorSecret.objects.count(), secrets.reveal(VendorLink.objects.get())), (1, OTHER_KEY))
        # 只改別的欄位、沒送金鑰:金鑰不動
        r = self.admin.post(LINKS, {"warehouse": self.wh1.id, "payment_method": "貨到付款"}, format="json")
        self.assertEqual((r.json()["payment_method"], r.json()["has_key"], r.json()["ship_name"]), ("貨到付款", True, "甲湳雅店"))
        r = self.admin.post(f"{LINKS}{self.wh1.id}/remove-key/")
        self.assertEqual((r.status_code, r.json()["has_key"], r.json()["key_hint"]), (200, False, ""))
        self.assertEqual((VendorSecret.objects.count(), VendorLink.objects.count()), (0, 1))

    def test_the_defaults_must_make_a_sendable_order(self):
        for extra, text in (({"ship_address": ""}, "宅配要有收件人"), ({"payment_method": "刷卡"}, "付款方式只能是"),
                            ({"delivery_method": "快遞"}, "取貨方式只能是"), ({"invoice_type": "公司"}, "統一編號與抬頭"),
                            ({"invoice_type": "三聯"}, "發票只能是"), ({"ship_name": "長" * 61}, "太長"),
                            ({"ship_name": 5}, "格式不對"), ({"invoice_email": ""}, "要有發票信箱"),
                            ({"invoice_email": "不是信箱"}, "要有發票信箱"), ({"invoice_email": "a@b"}, "要有發票信箱")):
            r = self.link(**extra)
            self.assertEqual((r.status_code, text in r.json()["detail"]), (400, True), (extra, r.content.decode()))
        self.assertEqual(VendorLink.objects.count(), 0)
        r = self.link(delivery_method="自取", ship_address="", invoice_type="公司", buyer_tax_id="12345678", buyer_name="甲企業社")
        self.assertEqual(r.status_code, 200, r.content.decode())

    def test_another_company_cannot_touch_or_see_it(self):
        self.link()
        other = Company("b", "乙通訊行", "乙")
        r = other.admin.post(LINKS, {"warehouse": self.wh1.id, "key": KEY, "ship_name": "x", "ship_phone": "1",
                                     "ship_address": "y", "invoice_email": "a@b.com"}, format="json")
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "找不到這家門市"))
        self.assertEqual({row["warehouse"] for row in other.admin.get(LINKS).json()["results"]},
                         {w.id for w in other.warehouses})
        self.assertFalse(any(row["has_key"] for row in other.admin.get(LINKS).json()["results"]))
        self.assertEqual(other.admin.post(f"{LINKS}{self.wh1.id}/remove-key/").status_code, 400)
        self.assertEqual(VendorSecret.objects.count(), 1)

    def test_the_key_is_not_part_of_a_company_backup(self):
        registry.check_registry()                      # 登記有問題會直接丟錯
        self.assertEqual(registry.REGISTRY["vendor_orders.VendorSecret"].kind, registry.EXCLUDED)
        self.assertIn("vendor_orders.VendorSecret", registry.CLEARED_ON_RESTORE)
        for label in ("vendor_orders.VendorLink", "vendor_orders.VendorOrder", "vendor_orders.VendorOrderItem"):
            self.assertEqual(registry.REGISTRY[label].kind, registry.COMPANY, label)
        self.assertNotIn("wrapped", [f.name for f in VendorLink._meta.get_fields()])

    def test_a_key_that_can_no_longer_be_read_counts_as_not_set(self):
        self.link()
        with override_settings(SECRET_KEY="系統金鑰換過了"):
            self.assertIsNone(secrets.reveal(VendorLink.objects.get()))
            r = self.clerk.get(f"{CATALOG}?warehouse={self.wh1.id}")
            self.assertEqual((r.status_code, "還沒有設定膜總裁的金鑰" in r.json()["detail"]), (400, True))


class SandboxTests(_Shop):
    """膜總裁每個回應都講這把金鑰是不是沙盒(金鑰一律 mk_live_ 開頭,看不出來)。"""

    def row(self, client=None):
        return {r["warehouse"]: r for r in (client or self.clerk).get(LINKS).json()["results"]}[self.wh1.id]

    def test_the_flag_is_kept_shown_to_everyone_and_follows_what_the_vendor_says(self):
        self.assertEqual((self.link().json()["sandbox"], self.row()["sandbox"], self.row(self.admin)["sandbox"]),
                         (True, True, True))
        r = self.order()
        self.assertEqual((r.status_code, r.json()["is_test"]), (201, True))
        self.vendor.sandbox = False                       # 膜總裁那邊把這把改成正式的
        self.assertEqual(self.clerk.get(CATALOG).status_code, 200)
        self.assertEqual(self.row()["sandbox"], False)
        r = self.order(key="draft-0002")
        self.assertEqual((r.status_code, r.json()["is_test"]), (201, False))
        self.vendor.sandbox = None                        # 回應裡沒有那一欄:不知道,不當成是也不當成不是
        self.clerk.get(CATALOG)
        self.assertIsNone(self.row()["sandbox"])
        r = self.order(key="draft-0003")
        self.assertEqual((r.status_code, r.json()["is_test"]), (201, None))
        self.admin.post(f"{LINKS}{self.wh1.id}/remove-key/")
        self.assertEqual((self.row()["sandbox"], self.row()["has_key"]), (None, False))

    def test_a_test_environment_only_takes_sandbox_keys(self):
        with override_settings(VENDOR_SANDBOX_ONLY=True):
            for flag in (False, None, "true", 1):
                self.vendor.sandbox = flag
                r = self.link()
                self.assertEqual((r.status_code, "只能用膜總裁的沙盒(測試)金鑰" in r.json()["detail"]), (400, True), flag)
            self.assertEqual(VendorSecret.objects.count(), 0)
            self.vendor.sandbox = True
            self.assertEqual(self.link().status_code, 200)
            self.assertEqual(self.order().status_code, 201)
            # 存的時候是沙盒,之後膜總裁那邊改成正式的:看商品、叫貨都擋下來,不會送出去
            self.vendor.sandbox = False
            posts = len(self.vendor.posts())
            for r in (self.clerk.get(CATALOG), self.order(key="draft-0002")):
                self.assertEqual((r.status_code, "只能用膜總裁的沙盒(測試)金鑰" in r.json()["detail"]), (400, True))
            self.assertEqual((len(self.vendor.posts()), VendorOrder.objects.count()), (posts, 1))
        # 正式環境(沒有開這個設定):正式金鑰照常用
        self.assertEqual(self.link().status_code, 200)
        self.assertEqual(self.order(key="draft-0003").status_code, 201)

    def test_in_a_test_environment_sending_again_asks_first_whether_the_key_is_still_sandbox(self):
        """同一把金鑰在廠商那邊被改成正式的(指紋不變):「再送一次」不能在測試環境下出真的單。"""
        with override_settings(VENDOR_SANDBOX_ONLY=True):
            self.link()
            self.vendor.script = ["down"]                    # 第一次沒送到:不確定
            first = self.order().json()
            self.assertEqual((first["state"], len(self.vendor.placed)), ("unknown", 0))
            self.vendor.sandbox = False                      # 這把金鑰之後變成正式的
            posts = len(self.vendor.posts())
            for r in (self.clerk.post(f"{ORDERS}{first['id']}/resend/"), self.order()):
                self.assertEqual((r.status_code, "只能用膜總裁的沙盒(測試)金鑰" in r.json()["detail"]), (400, True), r.content.decode())
            self.assertEqual((len(self.vendor.posts()), len(self.vendor.placed)), (posts, 0))     # 沒有送出去
            order = VendorOrder.objects.get()
            self.assertEqual((order.state, order.sending_since), ("unknown", None))               # 留著、沒有卡在送出中
            self.vendor.read_down = True                     # 問不到是不是沙盒:也不送
            r = self.clerk.post(f"{ORDERS}{first['id']}/resend/")
            self.assertEqual((r.status_code, r.json()["detail"], len(self.vendor.posts())), (400, "連不到膜總裁,請稍後再試", posts))
            self.assertEqual(VendorOrder.objects.get().state, "unknown")
            self.vendor.read_down, self.vendor.sandbox = False, True      # 改回沙盒:可以確認了
            r = self.clerk.post(f"{ORDERS}{first['id']}/resend/")
            self.assertEqual((r.status_code, r.json()["state"], r.json()["is_test"], len(self.vendor.placed)), (200, "placed", True, 1))
        # 正式環境:再送之前不多問這一次
        self.vendor.script = ["down"]
        second = self.order(key="draft-0002").json()
        calls = len(self.vendor.calls)
        self.clerk.post(f"{ORDERS}{second['id']}/resend/")
        self.assertEqual([c[0] for c in self.vendor.calls[calls:]], ["POST"])


class CatalogTests(_Shop):
    def setUp(self):
        super().setUp()
        self.link()
        self.vendor.calls.clear()

    def test_the_rows_are_what_can_be_ordered_with_the_price_per_pack(self):
        r = self.clerk.get(f"{CATALOG}?warehouse={self.wh1.id}")
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.assertNoKeyIn(r)
        rows = {row["key"]: row for row in r.json()["rows"]}
        self.assertEqual(list(rows), ["G02", "G01", "S09", "M01#901", "M01#902"])
        self.assertEqual({k: rows["G02"][k] for k in ("sku", "name", "unit", "size", "pack_qty", "unit_price", "pack_price", "spec_id")},
                         {"sku": "G02", "name": "高透亮面", "unit": "片", "size": "125*196", "pack_qty": 25,
                          "unit_price": "150.00", "pack_price": "3750.00", "spec_id": None})
        # 沒有報價的:單價是空的(不是 0)
        self.assertEqual((rows["S09"]["unit_price"], rows["S09"]["pack_price"]), (None, None))
        # 有規格的商品一個規格一列,價錢是那一格自己的
        self.assertEqual((rows["M01#901"]["spec_id"], rows["M01#901"]["spec_label"], rows["M01#901"]["unit_price"],
                          rows["M01#901"]["pack_price"]), (901, "K43 iPhone 15 Pro", "75.00", "375.00"))
        self.assertEqual((rows["M01#902"]["spec_label"], rows["M01#902"]["unit_price"]), ("K44", "70.00"))
        self.assertNotIn("M01", rows)

    def test_who_may_look(self):
        self.assertEqual(self.clerk.get(f"{CATALOG}?warehouse={self.wh2.id}").status_code, 403)      # 別家門市
        self.assertEqual(self.clerk.get(CATALOG).status_code, 200)                                   # 沒指定 = 自己門市
        r = self.admin.get(f"{CATALOG}?warehouse={self.wh2.id}")                                     # 那一家沒設金鑰
        self.assertEqual((r.status_code, "還沒有設定膜總裁的金鑰" in r.json()["detail"]), (400, True))
        self.assertEqual(self.admin.get(CATALOG).status_code, 400)                                   # 沒鎖門市的要指定
        self.turn_off("vendor_order")
        r = self.clerk.get(CATALOG)
        self.assertEqual((r.status_code, "「廠商叫貨」" in r.json()["detail"]), (403, True))
        self.assertEqual(len(self.vendor.calls), 1)                                                  # 被擋的都沒有打廠商

    def test_vendor_trouble_is_said_plainly(self):
        self.vendor.read_down = True
        r = self.clerk.get(CATALOG)
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "連不到膜總裁,請稍後再試"))
        self.vendor.read_down = False
        self.vendor.keys.clear()                    # 金鑰在膜總裁那邊被作廢了
        r = self.clerk.get(CATALOG)
        self.assertEqual((r.status_code, "不認得這家門市的金鑰" in r.json()["detail"]), (400, True))
        self.assertNoKeyIn(r)

    def test_rows_that_cannot_be_understood_are_skipped(self):
        rows = services.rows_from([
            {"sku": "A1", "name": "好的", "pack_qty": 10, "unit_price": 5.5, "unit": "片"},
            {"sku": "", "name": "沒有料號"}, {"name": "沒有料號"}, "不是物件", None, {"sku": "A2"},
            {"sku": "A3", "name": "包數亂填", "pack_qty": "10", "unit_price": "150"},
            {"sku": "A4", "name": "負的", "pack_qty": 0, "unit_price": -1},
            {"sku": "A5", "name": "規格亂填", "pack_qty": 5, "unit_price": 9,
             "specs": [{"id": "x"}, "y", {"id": True}, {"id": 7, "code": "K7", "unit_price": True}]},
        ])
        self.assertEqual([(r["key"], r["pack_qty"], r["unit_price"]) for r in rows], [
            ("A1", 10, Decimal("5.50")), ("A3", 1, None), ("A4", 1, None), ("A5#7", 5, None)])
        self.assertEqual(services.rows_from("不是清單"), [])


class PlaceTests(_Shop):
    def setUp(self):
        super().setUp()
        self.link(buyer_tax_id="")
        self.vendor.calls.clear()

    def test_packs_become_pieces_and_no_price_is_sent(self):
        r = self.order([{"key": "G02", "packs": 2}, {"key": "M01#901", "packs": 3}], note=" 下午再送 ")
        self.assertEqual(r.status_code, 201, r.content.decode())
        self.assertNoKeyIn(r)
        self.assertEqual([c[:3] for c in self.vendor.calls], [("GET", "/products", KEY), ("POST", "/orders", KEY)])
        self.assertEqual(self.vendor.posts()[0][3], {
            "idempotency_key": "pos-a-draft-0001",
            "items": [{"sku": "G02", "spec_id": None, "qty": 50}, {"sku": "M01", "spec_id": 901, "qty": 15}],
            "payment_method": "月結", "delivery_method": "宅配",
            "invoice": {"type": "個人", "email": "a@b.com"},
            "ship_to": {"name": "甲湳雅店", "phone": "035551234", "address": "新竹市湳雅街 1 號"},
            "note": "下午再送",
        })
        got = r.json()
        self.assertEqual((got["state"], got["vendor_order_no"], got["total_amount"], got["shipping_fee"],
                          got["expected_goods"], got["amount_matches"], got["warehouse"], got["created_by"]),
                         ("placed", "MO-20261010-001", "8625.00", "0.00", "8625.00", True, self.wh1.id, "a-clerk"))
        self.assertEqual([(i["sku"], i["spec_id"], i["name"], i["pack_qty"], i["packs"], i["qty"], i["unit_price"])
                          for i in got["items"]],
                         [("G02", None, "高透亮面", 25, 2, 50, "150.00"), ("M01", 901, "膜速箱", 5, 3, 15, "75.00")])
        self.assertEqual(VendorOrder.objects.get().key_fingerprint, secrets.fingerprint(KEY))

    def test_what_the_screen_sends_about_price_address_or_invoice_is_ignored(self):
        r = self.order([{"key": "G02", "packs": 1, "unit_price": "1", "qty": 999, "pack_qty": 1, "name": "便宜"}],
                       ship_name="我家", ship_phone="0900", ship_address="別的地方", invoice_type="公司",
                       buyer_tax_id="99999999", buyer_name="別人", total_amount="1")
        self.assertEqual(r.status_code, 201, r.content.decode())
        sent = self.vendor.posts()[0][3]
        self.assertEqual((sent["items"], sent["ship_to"]["address"], sent["invoice"]),
                         ([{"sku": "G02", "spec_id": None, "qty": 25}], "新竹市湳雅街 1 號", {"type": "個人", "email": "a@b.com"}))
        self.assertEqual((r.json()["expected_goods"], r.json()["ship_name"]), ("3750.00", "甲湳雅店"))

    def test_payment_and_delivery_can_be_chosen_per_order(self):
        r = self.order(payment_method="貨到付款", delivery_method="自取")
        self.assertEqual(r.status_code, 201, r.content.decode())
        sent = self.vendor.posts()[0][3]
        self.assertEqual((sent["payment_method"], sent["delivery_method"], "ship_to" in sent, "note" in sent),
                         ("貨到付款", "自取", False, False))
        for extra, text in (({"payment_method": "刷卡"}, "付款方式只能是"), ({"delivery_method": "快遞"}, "取貨方式只能是")):
            r = self.order(key="draft-0002", **extra)
            self.assertEqual((r.status_code, text in r.json()["detail"]), (400, True), extra)
        self.assertEqual(len(self.vendor.posts()), 1)

    def test_lines_that_cannot_be_ordered_never_reach_the_vendor(self):
        for lines, text in (([], "至少要叫一項"), (None, None), ("G02", "至少要叫一項"),
                            ([{"key": "NOPE", "packs": 1}], "現在沒有在賣"), ([{"key": "M01", "packs": 1}], "現在沒有在賣"),
                            ([{"key": "S09", "packs": 1}], "還沒有報價"), ([{"key": "G02", "packs": 0}], "包數要是"),
                            ([{"key": "G02", "packs": -1}], "包數要是"), ([{"key": "G02", "packs": "2"}], "包數要是"),
                            ([{"key": "G02", "packs": 1.5}], "包數要是"), ([{"key": "G02", "packs": True}], "包數要是"),
                            ([{"key": "G02", "packs": 10000}], "包數要是"), ([{"key": "G02"}], "包數要是"),
                            ([{"key": "G02", "packs": 1}, {"key": "G02", "packs": 2}], "重複了"), (["x"], "現在沒有在賣"),
                            ([{"key": "G02", "packs": 1}] * 101, "最多 100 項")):
            if lines is None:
                continue
            r = self.order(lines, key="draft-bad1")
            self.assertEqual((r.status_code, text in r.json()["detail"]), (400, True), (lines, r.content.decode()))
        for key in ("", "短", "有 空白-1234", "x" * 51, 12345678, None):
            r = self.order(key=key)
            self.assertEqual((r.status_code, "編號不對" in r.json()["detail"]), (400, True), key)
        self.assertEqual((self.vendor.posts(), VendorOrder.objects.count()), ([], 0))

    def test_a_refusal_leaves_nothing_behind_and_the_same_key_works_after_fixing(self):
        self.vendor.script = [(400, "月結額度不足，請改用其他付款方式")]
        r = self.order()
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "膜總裁沒有收這張單:月結額度不足，請改用其他付款方式"))
        self.assertEqual(VendorOrder.objects.count(), 0)
        r = self.order(payment_method="貨到付款")                          # 同一把鑰匙,改了付款方式再送
        self.assertEqual((r.status_code, r.json()["state"], r.json()["payment_method"]), (201, "placed", "貨到付款"))
        self.assertEqual([p[3]["idempotency_key"] for p in self.vendor.posts()], ["pos-a-draft-0001"] * 2)
        for status, reason in ((401, "金鑰無效或已作廢"), (429, "太頻繁"), (404, "沒有這個位址")):
            self.vendor.script = [(status, reason)]
            r = self.order(key=f"draft-r{status}")
            self.assertEqual((r.status_code, reason in r.json()["detail"]), (400, True), status)
        self.assertEqual(VendorOrder.objects.count(), 1)

    def test_no_clear_answer_means_unknown_and_sending_again_cannot_make_two(self):
        self.vendor.script = ["lost"]                                       # 成立了,但回應沒回來
        r = self.order()
        self.assertEqual((r.status_code, r.json()["state"], r.json()["vendor_order_no"]), (201, "unknown", ""))
        self.assertIn("連不到膜總裁", r.json()["problem"])
        r = self.order()                                                    # 畫面拿同一把鑰匙再送
        self.assertEqual((r.status_code, r.json()["state"], r.json()["vendor_order_no"], r.json()["problem"]),
                         (200, "placed", "MO-20261010-001", ""))
        # 廠商只回單號:總額另外查到了;運費不知道,所以「對不對得上」先空著
        self.assertEqual((r.json()["total_amount"], r.json()["shipping_fee"], r.json()["amount_matches"]),
                         ("7500.00", None, None))
        self.assertEqual((len(self.vendor.placed), VendorOrder.objects.count()), (1, 1))
        r = self.order()                                                    # 已成立:原樣回,不再打廠商
        posts = len(self.vendor.posts())
        self.assertEqual((r.status_code, r.json()["vendor_order_no"], len(self.vendor.posts())), (200, "MO-20261010-001", posts))

    def test_unknown_because_it_never_arrived_is_placed_by_sending_again(self):
        self.vendor.script = ["down"]
        first = self.order().json()
        self.assertEqual((first["state"], len(self.vendor.placed)), ("unknown", 0))
        r = self.clerk.post(f"{ORDERS}{first['id']}/resend/")
        self.assertEqual((r.status_code, r.json()["state"], r.json()["vendor_order_no"], r.json()["amount_matches"]),
                         (200, "placed", "MO-20261010-001", True))
        self.assertEqual([p[3]["idempotency_key"] for p in self.vendor.posts()], ["pos-a-draft-0001"] * 2)
        self.assertEqual([p[3]["items"] for p in self.vendor.posts()][0], [p[3]["items"] for p in self.vendor.posts()][1])
        r = self.clerk.post(f"{ORDERS}{first['id']}/resend/")              # 已成立再按:不再送
        self.assertEqual((r.json()["state"], len(self.vendor.posts())), ("placed", 2))

    def test_sending_again_keeps_the_original_lines_even_if_the_screen_changed(self):
        self.vendor.script = ["down"]
        self.order([{"key": "G02", "packs": 2}])
        r = self.order([{"key": "G01", "packs": 9}], payment_method="貨到付款")
        self.assertEqual((r.status_code, r.json()["state"]), (200, "placed"))
        sent = self.vendor.posts()[-1][3]
        self.assertEqual((sent["items"], sent["payment_method"]), ([{"sku": "G02", "spec_id": None, "qty": 50}], "月結"))

    def test_sending_again_and_being_refused(self):
        self.vendor.script = ["down", (400, "庫存不足")]
        first = self.order().json()
        r = self.clerk.post(f"{ORDERS}{first['id']}/resend/")              # 內容被擋 = 先前那一次也沒有成立
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "膜總裁沒有收這張單:庫存不足"))
        self.assertEqual(VendorOrder.objects.count(), 0)
        self.vendor.script = ["lost", (401, "金鑰無效或已作廢"), (429, "太頻繁"), "down"]
        first = self.order(key="draft-0002").json()
        for text in ("沒辦法確認:金鑰無效或已作廢", "沒辦法確認:太頻繁", "連不到膜總裁"):   # 這幾種證明不了沒成立
            r = self.clerk.post(f"{ORDERS}{first['id']}/resend/")
            self.assertEqual((r.status_code, r.json()["state"], text in r.json()["problem"]), (200, "unknown", True), text)
        r = self.clerk.post(f"{ORDERS}{first['id']}/resend/")
        self.assertEqual((r.json()["state"], r.json()["vendor_order_no"], len(self.vendor.placed)), ("placed", "MO-20261010-001", 1))

    def test_after_the_key_was_replaced_sending_again_is_refused(self):
        """廠商的防重複是看「金鑰 + 鑰匙」:換了金鑰再送,同一把鑰匙也會變成第二張單。"""
        self.vendor.script = ["lost"]
        first = self.order().json()
        self.vendor.keys.add(OTHER_KEY)
        self.link(key=OTHER_KEY)
        posts = len(self.vendor.posts())
        for r in (self.clerk.post(f"{ORDERS}{first['id']}/resend/"), self.order()):
            self.assertEqual((r.status_code, "金鑰換過了" in r.json()["detail"]), (400, True), r.content.decode())
        self.assertEqual((len(self.vendor.posts()), len(self.vendor.placed)), (posts, 1))
        self.assertEqual(VendorOrder.objects.get().state, "unknown")
        self.admin.post(f"{LINKS}{self.wh1.id}/remove-key/")
        r = self.clerk.post(f"{ORDERS}{first['id']}/resend/")
        self.assertEqual((r.status_code, "現在沒有膜總裁的金鑰" in r.json()["detail"]), (400, True))
        self.link()                                                          # 換回原本那一把:可以確認了
        r = self.clerk.post(f"{ORDERS}{first['id']}/resend/")
        self.assertEqual((r.json()["state"], r.json()["vendor_order_no"], len(self.vendor.placed)), ("placed", "MO-20261010-001", 1))

    def test_an_order_still_being_sent_is_not_sent_twice(self):
        from datetime import timedelta
        from django.utils import timezone

        self.vendor.script = ["down"]
        first = self.order().json()
        VendorOrder.objects.filter(pk=first["id"]).update(state="sending", sending_since=timezone.now())
        posts = len(self.vendor.posts())
        for r in (self.clerk.post(f"{ORDERS}{first['id']}/resend/"), self.order()):
            self.assertEqual((r.status_code, "正在送出" in r.json()["detail"]), (409, True))
        self.assertEqual(len(self.vendor.posts()), posts)
        # 「送出中」卡太久(那一次沒有回來):可以再送
        VendorOrder.objects.filter(pk=first["id"]).update(sending_since=timezone.now() - timedelta(minutes=5))
        r = self.clerk.post(f"{ORDERS}{first['id']}/resend/")
        self.assertEqual((r.status_code, r.json()["state"]), (200, "placed"))

    def test_the_vendor_total_is_checked_against_what_the_screen_showed(self):
        self.vendor.shipping_fee = 120
        r = self.order()
        self.assertEqual((r.json()["total_amount"], r.json()["shipping_fee"], r.json()["expected_goods"], r.json()["amount_matches"]),
                         ("7620.00", "120.00", "7500.00", True))
        self.vendor.price_drift = 1                                          # 廠商實際收的跟清單不一樣
        r = self.order(key="draft-0002")
        self.assertEqual((r.json()["total_amount"], r.json()["expected_goods"], r.json()["amount_matches"]),
                         ("7670.00", "7500.00", False))

    def test_who_may_order_and_for_which_store(self):
        r = self.order(store=self.wh2)                                       # 店員指別家門市
        self.assertEqual(r.status_code, 403, r.content.decode())
        r = self.order(client=self.admin, store=self.wh2, key="draft-wh2a")  # 那一家沒設
        self.assertEqual((r.status_code, "還沒有設定膜總裁的金鑰" in r.json()["detail"]), (400, True))
        r = self.order(client=self.admin, key="draft-boss")                  # 管理員替湳雅店叫
        self.assertEqual((r.status_code, r.json()["created_by"]), (201, "a-boss"))
        self.turn_off("vendor_order")
        r = self.order(key="draft-0003")
        self.assertEqual((r.status_code, "「廠商叫貨」" in r.json()["detail"]), (403, True))
        first = VendorOrder.objects.get()
        self.assertEqual(self.clerk.post(f"{ORDERS}{first.id}/resend/").status_code, 403)
        self.assertEqual(self.clerk.post(SYNC, {"warehouse": self.wh1.id}, format="json").status_code, 403)
        self.assertEqual(self.clerk.get(ORDERS).status_code, 200)            # 看照舊
        self.assertEqual(len(self.vendor.posts()), 1)
        from rest_framework.test import APIClient

        for method, url in (("get", LINKS), ("post", LINKS), ("get", CATALOG), ("get", ORDERS), ("post", ORDERS), ("post", SYNC)):
            self.assertEqual(getattr(APIClient(), method)(url).status_code, 401, url)

    def test_a_key_from_another_store_or_company_is_not_this_order(self):
        self.vendor.script = ["lost"]
        self.order(key="draft-same")
        self.link(store=self.wh2)
        r = self.order(client=self.admin, store=self.wh2, key="draft-same")
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "這把鑰匙是另一家門市的叫貨單"))
        other = Company("b", "乙通訊行", "乙")
        other.admin.post(LINKS, {"warehouse": other.wh.id, "key": KEY, "ship_name": "乙", "ship_phone": "1", "ship_address": "x",
                                 "invoice_email": "b@b.com"}, format="json")
        r = other.clerk.post(ORDERS, {"request_key": "draft-same", "warehouse": other.wh.id,
                                      "lines": [{"key": "G01", "packs": 1}]}, format="json")
        self.assertEqual((r.status_code, r.json()["state"]), (201, "placed"))        # 另一家公司:是它自己的另一張單
        self.assertEqual(self.vendor.posts()[-1][3]["idempotency_key"], "pos-b-draft-same")
        mine = VendorOrder.objects.get(tenant=self.t)
        self.assertEqual(other.admin.get(f"{ORDERS}{mine.id}/").status_code, 404)
        self.assertEqual(other.admin.post(f"{ORDERS}{mine.id}/resend/").status_code, 404)
        self.assertEqual([o["warehouse"] for o in other.admin.get(ORDERS).json()["results"]], [other.wh.id])


class ListAndSyncTests(_Shop):
    def setUp(self):
        super().setUp()
        self.link()
        self.link(store=self.wh2)
        self.a = self.order().json()
        self.b = self.order(client=self.admin, store=self.wh2, key="draft-wh2a", lines=[{"key": "G01", "packs": 1}]).json()

    def test_a_locked_clerk_only_sees_the_own_store(self):
        self.assertEqual([o["id"] for o in self.clerk.get(ORDERS).json()["results"]], [self.a["id"]])
        self.assertEqual(self.clerk.get(f"{ORDERS}?warehouse={self.wh2.id}").status_code, 403)
        self.assertEqual(self.clerk.get(f"{ORDERS}{self.b['id']}/").status_code, 404)
        self.assertEqual(self.clerk.get(f"{ORDERS}{self.a['id']}/").json()["vendor_order_no"], "MO-20261010-001")
        self.assertEqual([o["id"] for o in self.admin.get(ORDERS).json()["results"]], [self.b["id"], self.a["id"]])
        self.assertEqual([o["id"] for o in self.admin.get(f"{ORDERS}?warehouse={self.wh2.id}").json()["results"]], [self.b["id"]])
        self.assertNoKeyIn(self.admin.get(ORDERS))

    def test_sync_updates_progress_and_lists_orders_not_placed_here(self):
        mine = self.vendor.placed[(KEY, "pos-a-draft-0001")]
        mine.update(status="已出貨", payment_status="月結未到期", logistics_status="已建立託運單", shipping_method="順豐",
                    tracking_no="SF0210089346149", ordered_at="2026-10-10T10:43:59+08:00")
        self.vendor.outside = [{"order_no": "MO-20261008-007", "total_amount": 3750, "status": "已完成",
                                "ordered_at": "2026-10-08T09:00:00+08:00"}]
        r = self.clerk.post(SYNC, {"warehouse": self.wh1.id}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.assertNoKeyIn(r)
        got = r.json()["results"][0]
        self.assertEqual((got["id"], got["vendor_status"], got["vendor_logistics_status"], got["vendor_shipping_method"],
                          got["vendor_tracking_no"], got["vendor_payment_status"]),
                         (self.a["id"], "已出貨", "已建立託運單", "順豐", "SF0210089346149", "月結未到期"))
        self.assertTrue(got["status_checked_at"] and got["vendor_ordered_at"])
        # 兩家門市共用同一把金鑰:另一家從 POS 叫的不算「不是從這裡叫的」(也不讓這家的店員看到)
        self.assertEqual(r.json()["others"], [{
            "order_no": "MO-20261008-007", "ordered_at": "2026-10-08T09:00:00+08:00", "status": "已完成",
            "payment_status": "月結未到期", "logistics_status": "", "shipping_method": "", "tracking_no": "",
            "total_amount": "3750.00"}])
        self.assertEqual(len(r.json()["results"]), 1)

    def test_sync_needs_a_working_key(self):
        self.assertEqual(self.clerk.post(SYNC, {"warehouse": self.wh2.id}, format="json").status_code, 403)
        self.vendor.read_down = True
        r = self.clerk.post(SYNC, {"warehouse": self.wh1.id}, format="json")
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "連不到膜總裁,請稍後再試"))
        self.admin.post(f"{LINKS}{self.wh1.id}/remove-key/")
        r = self.clerk.post(SYNC, {}, format="json")
        self.assertEqual((r.status_code, "還沒有設定膜總裁的金鑰" in r.json()["detail"]), (400, True))

    def test_reading_never_writes_to_the_vendor(self):
        self.vendor.calls.clear()
        self.clerk.get(ORDERS)
        self.clerk.get(f"{ORDERS}{self.a['id']}/")
        self.clerk.get(LINKS)
        self.assertEqual(self.vendor.calls, [])
        self.clerk.post(SYNC, {"warehouse": self.wh1.id}, format="json")
        self.clerk.get(CATALOG)
        self.assertEqual([c[0] for c in self.vendor.calls], ["GET", "GET"])


class ReplyRuleTests(SimpleTestCase):
    """廠商回的每一種樣子算成立、沒成立、還是不知道。分錯的後果:當成沒成立會再開一張;當成成立會以為有貨要來。"""

    def outcome(self, status, data):
        with mock.patch.object(standard, "_call", return_value=standard.Reply(status, data)):
            try:
                return CLIENT.place(KEY, {})
            except standard.Unreachable:
                return "unknown"

    def test_what_counts_as_placed_refused_or_unknown(self):
        placed = self.outcome(200, {"ok": True, "order_no": "MO-1", "total_amount": 100, "shipping_fee": 0, "sandbox": True})
        self.assertEqual((placed.order_no, placed.total_amount, placed.replay, placed.sandbox), ("MO-1", 100, False, True))
        replay = self.outcome(409, {"ok": False, "error": "用過了", "order_no": "MO-1", "sandbox": False})
        self.assertEqual((replay.order_no, replay.total_amount, replay.replay, replay.sandbox), ("MO-1", None, True, False))
        for flag in ("true", 1, None, "yes"):                 # 只認明講的 true / false
            self.assertIsNone(self.outcome(200, {"ok": True, "order_no": "MO-1", "sandbox": flag}).sandbox, flag)
        self.assertIsNone(self.outcome(200, {"ok": True, "order_no": "MO-1"}).sandbox)
        for status, data in ((400, {"ok": False, "error": "庫存不足"}), (401, {"ok": False, "error": "金鑰無效或已作廢"}),
                             (422, {"ok": False}), (429, {"ok": False, "error": "太頻繁"}), (404, {})):
            got = self.outcome(status, data)
            self.assertIsInstance(got, standard.Rejected, status)
            self.assertEqual(got.status, status)
        self.assertEqual(self.outcome(422, {"ok": False}).reason, "膜總裁回 HTTP 422")
        for status, data in ((500, {"ok": False, "error": "我們這邊的問題"}), (502, {}), (503, {"ok": False}),
                             (408, {"ok": False}), (409, {"ok": False, "error": "用過了", "order_no": None}),
                             (409, {"ok": False}), (200, {"ok": True}), (200, {"ok": True, "order_no": ""}),
                             (200, {"ok": False, "order_no": "MO-1"}), (200, {"ok": True, "order_no": 5}),
                             (201, {"ok": True, "order_no": "MO-1"}), (302, {})):
            self.assertEqual(self.outcome(status, data), "unknown", (status, data))

    def test_what_a_key_looks_like(self):
        self.assertTrue(standard.looks_like_key(KEY, "mk_live_"))
        for bad in ("", None, 5, "mk_live_", "mk_live_short", "sk_live_" + "x" * 30, "mk_live_" + "x" * 30 + " ",
                    "mk_live_" + "金" * 30, "mk_live_" + "x" * 200):
            self.assertFalse(standard.looks_like_key(bad, "mk_live_"), bad)
        # 這家廠商沒有固定的開頭:只看長度、沒有空白、是不是一般的英數字
        self.assertTrue(standard.looks_like_key("sk_live_" + "x" * 30))
        self.assertTrue(standard.looks_like_key("sk_live_" + "x" * 30, ""))
        for bad in ("", None, "short", "x" * 30 + " y", "金" * 30, "x" * 201):
            self.assertFalse(standard.looks_like_key(bad), bad)


class _Handler(http.server.BaseHTTPRequestHandler):
    seen, answer = [], (200, b'{"ok": true, "products": []}')

    def _serve(self):
        size = int(self.headers.get("Content-Length") or 0)
        type(self).seen.append((self.command, self.path, dict(self.headers), self.rfile.read(size)))
        status, body = type(self).answer
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    do_GET = do_POST = _serve

    def log_message(self, *args):
        pass


class WireTests(SimpleTestCase):
    """真的走一次 HTTP(對本機開的一個小伺服器):金鑰放在哪、內容怎麼編、各種回法怎麼算。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}/api/v1"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        super().tearDownClass()

    def setUp(self):
        _Handler.seen.clear()

    def test_the_key_travels_in_the_header_only_and_the_body_is_utf8_json(self):
        _Handler.answer = (200, json.dumps({"ok": True, "order_no": "MO-1", "total_amount": 1, "shipping_fee": 0}).encode())
        got = standard.Client(self.base + "/", "膜總裁").place(KEY, {"idempotency_key": "pos-a-1", "note": "下午再送"})
        self.assertEqual(got.order_no, "MO-1")
        method, path, headers, body = _Handler.seen[0]
        self.assertEqual((method, path, headers["Authorization"], headers["Content-Type"]),
                         ("POST", "/api/v1/orders", f"Bearer {KEY}", "application/json"))
        self.assertNotIn(KEY, path)
        self.assertEqual(json.loads(body.decode("utf-8")), {"idempotency_key": "pos-a-1", "note": "下午再送"})

    def test_answers_and_failures(self):
        standard_ = standard.Client(self.base, "膜總裁")
        if True:
            _Handler.answer = (400, '{"ok": false, "error": "月結額度不足"}'.encode())
            got = standard_.place(KEY, {})
            self.assertEqual((type(got), got.reason), (standard.Rejected, "月結額度不足"))
            with self.assertRaises(standard.Refused) as ctx:
                standard_.products(KEY)
            self.assertEqual((ctx.exception.status, ctx.exception.reason), (400, "月結額度不足"))
            for answer in ((502, b"<html>Bad Gateway</html>"), (200, b"<html>login</html>"), (200, b'["not", "an object"]'),
                           (400, b"\xff\xfe"), (500, b'{"ok": false, "error": "x"}')):
                _Handler.answer = answer
                with self.assertRaises(standard.Unreachable, msg=answer) as ctx:
                    standard_.place(KEY, {})
                self.assertNotIn(KEY, str(ctx.exception))
            with self.assertRaises(standard.Unreachable):
                standard_.products(KEY)                 # 讀的那幾支:對方出錯(5xx)也是沒有答覆
            _Handler.answer = (200, b'{"ok": true, "order": {"total_amount": 5}}')
            self.assertEqual(standard_.order(KEY, "MO 1/2"), {"total_amount": 5})
            self.assertEqual(_Handler.seen[-1][1], "/api/v1/orders/MO%201%2F2")
        with self.assertRaises(standard.Unreachable) as ctx:       # 沒有人在聽
            standard.Client("http://127.0.0.1:1/api/v1", "乙廠商").place(KEY, {})
        self.assertNotIn(KEY, str(ctx.exception))
        self.assertIn("連不到乙廠商", str(ctx.exception))          # 訊息講的是那一家的名字


class BackupTests(BackupBase):
    """公司備份:串接設定與叫貨單跟著走;金鑰不進備份,還原之後要重新貼(還原會把門市換成新的列,舊金鑰先清掉)。"""

    def test_orders_and_settings_survive_a_restore_but_the_key_does_not(self):
        a = self.a
        ensure_vendor()
        vendor = FakeVendor()
        with mock.patch.object(standard, "_call", vendor):
            r = a.admin.post(LINKS, {"warehouse": a.wh.id, "key": KEY, "ship_name": "甲湳雅店", "ship_phone": "035551234",
                                     "ship_address": "新竹市湳雅街 1 號", "payment_method": "貨到付款",
                                     "invoice_email": "a@b.com", "supplier": a.supplier.id,
                                     "freight_into_cost": False}, format="json")
            self.assertEqual(r.status_code, 200, r.content.decode())
            r = a.clerk.post(ORDERS, {"request_key": "draft-0001", "warehouse": a.wh.id,
                                      "lines": [{"key": "G02", "packs": 2}]}, format="json")
            self.assertEqual((r.status_code, r.json()["vendor_order_no"]), (201, "MO-20261010-001"))
            # 到貨入了 30 片(第二步):入庫紀錄、它開的進貨單、料號對到哪個品號都要跟著走
            r = a.clerk.post(f"{ORDERS}{r.json()['id']}/receive/", {
                "request_key": "recv-0001", "issue_note": "少 20 片",
                "lines": [{"key": "G02||p", "qty": 30, "product": a.case.id}]}, format="json")
            self.assertEqual(r.status_code, 201, r.content.decode())
            po_no = r.json()["order"]["receipts"][0]["purchase_order_no"]
            job = self.backup(a)
            old_store = a.wh.id
            done = self.rollback(a, self.path(job))
            self.assertEqual(done.status, "done", done.error)
            a.reload()
            self.assertNotEqual(a.wh.id, old_store)
            self.assertEqual(VendorSecret.objects.count(), 0)
            # 測試用的連線一直拿著還原之前讀到的帳號(門市是舊的那一列);正式環境每個請求重新讀
            from django.contrib.auth import get_user_model
            a.clerk = a.client(get_user_model().objects.get(pk=a.clerk_user.pk))
            row = {x["warehouse"]: x for x in a.admin.get(LINKS).json()["results"]}[a.wh.id]
            self.assertEqual((row["saved"], row["has_key"], row["key_hint"], row["payment_method"], row["ship_address"]),
                             (True, False, "", "貨到付款", "新竹市湳雅街 1 號"))
            orders = a.clerk.get(ORDERS).json()["results"]
            self.assertEqual([(o["warehouse"], o["vendor_order_no"], o["state"], o["total_amount"], o["items"][0]["qty"])
                              for o in orders], [(a.wh.id, "MO-20261010-001", "placed", "7500.00", 50)])
            self.assertEqual((orders[0]["issue_note"], orders[0]["source"],
                              [(x["purchase_order_no"], x["qty"], x["is_void"], x["total_cost"]) for x in orders[0]["receipts"]]),
                             ("少 20 片", "pos", [(po_no, 30, False, "4500.00")]))
            from apps.catalog.models import SupplierProduct
            from apps.purchasing.models import PurchaseOrder
            from .models import VendorReceipt, VendorReceiptItem
            receipt, item = VendorReceipt.objects.get(), VendorReceiptItem.objects.get()
            self.assertEqual((receipt.purchase_order, receipt.order.warehouse_id, item.product, item.qty),
                             (PurchaseOrder.objects.get(tenant=a.tenant, no=po_no), a.wh.id, a.case, 30))
            link = VendorLink.objects.get(tenant=a.tenant)
            self.assertEqual((link.supplier, link.freight_into_cost), (a.supplier, False))     # 還原後是新的那一列
            self.assertEqual(SupplierProduct.objects.get(tenant=a.tenant, vendor_sku="G02").product, a.case)
            # 沒有金鑰:叫不了貨;同一把鑰匙的那一張還是認得(不會再開一張)
            calls = len(vendor.calls)
            r = a.clerk.post(ORDERS, {"request_key": "draft-0002", "warehouse": a.wh.id,
                                      "lines": [{"key": "G02", "packs": 1}]}, format="json")
            self.assertEqual((r.status_code, "還沒有設定膜總裁的金鑰" in r.json()["detail"]), (400, True))
            r = a.clerk.post(ORDERS, {"request_key": "draft-0001", "warehouse": a.wh.id,
                                      "lines": [{"key": "G02", "packs": 2}]}, format="json")
            self.assertEqual((r.status_code, r.json()["vendor_order_no"], len(vendor.calls)), (200, "MO-20261010-001", calls))
