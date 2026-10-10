"""廠商叫貨區:多廠商 + 平台定的廠商類別(地基)。假的廠商在 tests.py(`FakeVendor` / `FakeNet`)。

要守住的:**一把金鑰只會送到它所屬那一家的網址**;每一家的商品、叫貨單、進度、入庫各走各的;
名單只有平台管理員能改;停用的廠商不能叫新的貨、但已經叫的單照樣處理得完;「誰能叫貨」每家門市 × 每家廠商各自決定。
"""
import importlib
from unittest import mock

from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from apps.backup import registry
from apps.backup.tests.factory import Company
from apps.catalog.models import Product, SupplierProduct
from apps.parties.models import Supplier
from apps.purchasing.models import PurchaseOrder
from apps.tenants.models import UserProfile

from . import secrets, standard
from .models import Vendor, VendorCategory, VendorLink, VendorOrder, VendorSecret
from .tests import CATALOG, KEY, LINKS, MOCEO_BASE, ORDERS, SYNC, FakeNet, FakeVendor, _Shop, ensure_vendor

ACME_BASE = "https://acme.test/order-api"
ACME_KEY = "acme-" + "Q7w8E9r0" * 4            # 這一家的金鑰沒有固定的開頭
P_CATEGORIES = "/api/v1/platform/vendor-categories/"
P_VENDORS = "/api/v1/platform/vendors/"
ADOPT = "/api/v1/vendor-orders/adopt/"


class _TwoVendors(_Shop):
    """名單上兩家:膜總裁(保護貼)、乙配件(配件、保護貼)。各自的網址、各自的金鑰、各自的訂單。"""

    def setUp(self):
        super().setUp()
        self.acme = ensure_vendor("acme", "乙配件", ACME_BASE, "", ("配件", "保護貼"), sort_order=5)
        self.acme_site = FakeVendor(keys={ACME_KEY})
        patcher = mock.patch.object(standard, "_call", FakeNet(**{MOCEO_BASE: self.vendor, ACME_BASE: self.acme_site}))
        patcher.start()
        self.addCleanup(patcher.stop)

    def open_both(self):
        self.assertEqual(self.link().status_code, 200)
        r = self.link(vendor="acme", key=ACME_KEY)
        self.assertEqual(r.status_code, 200, r.content.decode())

    def rows(self, client=None):
        return {(x["warehouse"], x["provider"]): x for x in (client or self.admin).get(LINKS).json()["results"]}


class PlatformListTests(_Shop):
    def setUp(self):
        super().setUp()
        root = get_user_model().objects.create_user(username="root", password="pw-12345")
        UserProfile.objects.create(user=root, role="platform_admin")          # 平台管理員不屬於任何公司
        self.root = self.c.client(root)

    def test_only_the_platform_admin_can_see_or_change_the_lists(self):
        category = VendorCategory.objects.get(name="保護貼")
        for client in (self.admin, self.clerk):
            for call in (lambda c: c.get(P_CATEGORIES), lambda c: c.get(P_VENDORS),
                         lambda c: c.post(P_CATEGORIES, {"name": "配件"}, format="json"),
                         lambda c: c.patch(f"{P_CATEGORIES}{category.id}/", {"name": "改名"}, format="json"),
                         lambda c: c.post(P_VENDORS, {"code": "evil", "name": "壞人", "api_base": "https://evil.test"}, format="json"),
                         lambda c: c.patch(f"{P_VENDORS}{self.moceo.id}/", {"api_base": "https://evil.test"}, format="json")):
                self.assertEqual(call(client).status_code, 403)
        self.moceo.refresh_from_db()
        self.assertEqual((self.moceo.api_base, Vendor.objects.count(), VendorCategory.objects.count()), (MOCEO_BASE, 1, 1))

    def test_categories_are_added_renamed_ordered_and_switched_off_but_never_deleted(self):
        r = self.root.post(P_CATEGORIES, {"name": " 配件 ", "sort_order": 2}, format="json")
        self.assertEqual((r.status_code, r.json()["name"], r.json()["sort_order"], r.json()["is_active"]), (201, "配件", 2, True))
        pk = r.json()["id"]
        for bad in ({"name": "配件"}, {"name": ""}, {"name": "字" * 21}, {"name": 5}, {}, {"name": "零件", "sort_order": -1},
                    {"name": "零件", "sort_order": "1"}, {"name": "零件", "sort_order": True}, {"name": "零件", "is_active": "yes"}):
            self.assertEqual(self.root.post(P_CATEGORIES, bad, format="json").status_code, 400, bad)
        r = self.root.patch(f"{P_CATEGORIES}{pk}/", {"name": "配件週邊", "sort_order": 0, "is_active": False}, format="json")
        self.assertEqual((r.status_code, r.json()["name"], r.json()["sort_order"], r.json()["is_active"]), (200, "配件週邊", 0, False))
        self.assertEqual(self.root.patch(f"{P_CATEGORIES}{pk}/", {"name": "保護貼"}, format="json").status_code, 400)   # 撞名
        self.assertEqual(self.root.patch(f"{P_CATEGORIES}{pk}/", {"name": "配件週邊"}, format="json").status_code, 200)  # 自己的名字不算撞
        self.assertEqual(self.root.patch(f"{P_CATEGORIES}999999/", {"name": "x"}, format="json").status_code, 404)
        self.assertEqual(self.root.delete(f"{P_CATEGORIES}{pk}/").status_code, 405)
        listed = self.root.get(P_CATEGORIES).json()["results"]
        self.assertEqual([(c["name"], c["is_active"], c["vendors"]) for c in listed], [("保護貼", True, 1), ("配件週邊", False, 0)])

    def test_a_vendor_is_one_row_with_a_code_that_never_changes(self):
        parts = self.root.post(P_CATEGORIES, {"name": "維修零件"}, format="json").json()["id"]
        film = VendorCategory.objects.get(name="保護貼").id
        r = self.root.post(P_VENDORS, {"code": "acme", "name": " 乙配件 ", "api_base": "https://acme.test/order-api/ ",
                                       "categories": [parts, film], "key_prefix": "ak_"}, format="json")
        self.assertEqual(r.status_code, 201, r.content.decode())
        got = r.json()
        self.assertEqual((got["code"], got["name"], got["api_base"], got["key_prefix"], sorted(got["categories"]),
                          got["protocol"], got["is_active"]),
                         ("acme", "乙配件", "https://acme.test/order-api", "ak_", sorted([parts, film]), "standard", True))
        pk = got["id"]
        r = self.root.patch(f"{P_VENDORS}{pk}/", {"name": "乙配件行", "categories": [parts], "is_active": False,
                                                 "sort_order": 3, "key_prefix": ""}, format="json")
        self.assertEqual((r.status_code, r.json()["name"], r.json()["categories"], r.json()["is_active"], r.json()["sort_order"],
                          r.json()["key_prefix"]), (200, "乙配件行", [parts], False, 3, ""))
        # 代碼建了不能改;同一個代碼送回來不算改
        self.assertEqual(self.root.patch(f"{P_VENDORS}{pk}/", {"code": "acme2"}, format="json").status_code, 400)
        self.assertEqual(self.root.patch(f"{P_VENDORS}{pk}/", {"code": "acme", "name": "乙配件"}, format="json").status_code, 200)
        self.assertEqual(self.root.delete(f"{P_VENDORS}{pk}/").status_code, 405)
        self.assertEqual(self.root.patch(f"{P_VENDORS}999999/", {"name": "x"}, format="json").status_code, 404)
        self.assertEqual(Vendor.objects.get(pk=pk).code, "acme")
        ok = {"name": "丙", "api_base": "https://c.test/api"}
        if not VendorCategory.objects.filter(pk=1).exists():        # 讓「是」(True)真的有一號可以撞:它不是類別的編號
            VendorCategory.objects.create(pk=1, name="一號類別")
        for bad in ({**ok, "code": "acme"}, {**ok, "code": "A1"}, {**ok, "code": "-ab"}, {**ok, "code": "a"}, {**ok, "code": "有中文"},
                    {**ok, "code": "x" * 21}, {**ok, "code": 5}, ok, {**ok, "code": "c1", "name": ""}, {**ok, "code": "c1", "name": "字" * 41},
                    {**ok, "code": "c1", "categories": [999999]}, {**ok, "code": "c1", "categories": "保護貼"},
                    {**ok, "code": "c1", "categories": [True]}, {**ok, "code": "c1", "key_prefix": "有 空白"},
                    {**ok, "code": "c1", "key_prefix": "x" * 21}, {**ok, "code": "c1", "protocol": "telepathy"},
                    {**ok, "code": "c1", "is_active": 1}, {**ok, "code": "c1", "sort_order": 10000}):
            r = self.root.post(P_VENDORS, bad, format="json")
            self.assertEqual(r.status_code, 400, (bad, r.content.decode()))
        self.assertEqual(sorted(Vendor.objects.values_list("code", flat=True)), ["acme", "moceo"])

    def test_the_address_keys_get_sent_to_must_be_a_plain_https_address(self):
        """這個網址決定每家門市的金鑰會被送到哪裡。"""
        for bad in ("http://acme.test/api", "acme.test/api", "ftp://acme.test", "https://", "https:///api", "",
                    "https://user:pw@acme.test/api", "https://acme.test/api?key=1", "https://acme.test/api#x",
                    "https://acme.test:port/api", "https://acme .test/api", "https://" + "a" * 200 + ".test", None, 5):
            r = self.root.post(P_VENDORS, {"code": "acme", "name": "乙", "api_base": bad}, format="json")
            self.assertEqual(r.status_code, 400, (bad, r.content.decode()))
            r = self.root.patch(f"{P_VENDORS}{self.moceo.id}/", {"api_base": bad}, format="json")
            self.assertEqual(r.status_code, 400, (bad, r.content.decode()))
        self.moceo.refresh_from_db()
        self.assertEqual((self.moceo.api_base, Vendor.objects.count()), (MOCEO_BASE, 1))
        r = self.root.patch(f"{P_VENDORS}{self.moceo.id}/", {"api_base": "https://new.moceo.test:8443/api/v2//"}, format="json")
        self.assertEqual((r.status_code, r.json()["api_base"]), (200, "https://new.moceo.test:8443/api/v2"))

    def test_the_list_shows_how_many_stores_opened_each_vendor_and_never_a_key(self):
        self.link()
        self.link(store=self.wh2)
        r = self.root.get(P_VENDORS)
        self.assertNoKeyIn(r)
        self.assertEqual([(v["code"], v["stores"]) for v in r.json()["results"]], [("moceo", 2)])
        self.assertEqual(r.json()["protocols"], [{"value": "standard", "label": "全自動(標準格式)"}])

    def test_the_lists_are_not_company_data(self):
        registry.check_registry()
        self.assertEqual({registry.REGISTRY[f"vendor_orders.{name}"].kind for name in ("Vendor", "VendorCategory")}, {registry.EXCLUDED})
        self.assertFalse(any(f.name == "tenant" for f in Vendor._meta.get_fields()))
        # 公司的資料只記代碼,沒有外鍵指到平台的名單(備份搬到別台,那邊的編號不一樣)
        for model in (VendorLink, VendorOrder):
            self.assertEqual(model._meta.get_field("provider").get_internal_type(), "CharField")


class SeedTests(TestCase):
    def test_the_existing_vendor_becomes_the_first_row_of_the_list(self):
        seed = importlib.import_module("apps.vendor_orders.migrations.0003_vendor_registry").seed_first_vendor
        Vendor.objects.all().delete()
        VendorCategory.objects.all().delete()
        with override_settings(MOCEO_API_BASE="https://moceo.example/api/v1"):
            seed(django_apps, None)
            seed(django_apps, None)             # 再跑一次不會多一筆
        vendor = Vendor.objects.get()
        self.assertEqual((vendor.code, vendor.name, vendor.api_base, vendor.key_prefix, vendor.protocol, vendor.is_active,
                          [c.name for c in vendor.categories.all()]),
                         ("moceo", "膜總裁", "https://moceo.example/api/v1", "mk_live_", "standard", True, ["保護貼"]))
        # 已經有的那一筆(平台管理員改過的)不會被蓋回去
        Vendor.objects.filter(code="moceo").update(api_base="https://changed.test/api", name="改過的名字")
        seed(django_apps, None)
        self.assertEqual(Vendor.objects.get().api_base, "https://changed.test/api")


class LinkListTests(_TwoVendors):
    def test_every_store_gets_one_row_per_vendor_and_the_categories_only_filter_vendors(self):
        VendorCategory.objects.create(name="停掉的類別", is_active=False)
        VendorCategory.objects.filter(name="配件").update(sort_order=1)
        VendorCategory.objects.filter(name="保護貼").update(sort_order=2)
        self.link()
        got = self.admin.get(LINKS).json()
        film, parts = VendorCategory.objects.get(name="保護貼").id, VendorCategory.objects.get(name="配件").id
        self.assertEqual(got["categories"], [{"id": parts, "name": "配件"}, {"id": film, "name": "保護貼"}])     # 停用的不列、照排序
        rows = {(x["warehouse"], x["provider"]): x for x in got["results"]}
        self.assertEqual(set(rows), {(self.wh1.id, "moceo"), (self.wh1.id, "acme"), (self.wh2.id, "moceo"), (self.wh2.id, "acme")})
        self.assertEqual([(x["provider"], x["provider_label"]) for x in got["results"][:2]], [("moceo", "膜總裁"), ("acme", "乙配件")])
        mine, other = rows[(self.wh1.id, "moceo")], rows[(self.wh1.id, "acme")]
        self.assertEqual((mine["has_key"], mine["categories"], mine["vendor_active"], mine["clerk_ordering"]), (True, [film], True, True))
        self.assertEqual((other["has_key"], sorted(other["categories"]), other["saved"], other["ship_name"]),
                         (False, sorted([film, parts]), False, "甲湳雅店"))
        # 鎖在門市的店員:只有自己門市的那幾列
        self.assertEqual(set(self.rows(self.clerk)), {(self.wh1.id, "moceo"), (self.wh1.id, "acme")})

    def test_with_two_vendors_every_request_has_to_say_which_one(self):
        self.open_both()
        for r in (self.clerk.get(CATALOG), self.clerk.post(SYNC, {"warehouse": self.wh1.id}, format="json"),
                  self.clerk.post(ORDERS, {"request_key": "draft-0001", "warehouse": self.wh1.id,
                                           "lines": [{"key": "G02", "packs": 1}]}, format="json"),
                  self.admin.post(LINKS, {"warehouse": self.wh1.id, "ship_name": "x"}, format="json"),
                  self.admin.post(f"{LINKS}{self.wh1.id}/remove-key/"),
                  self.clerk.post(ADOPT, {"warehouse": self.wh1.id, "order_no": "MO-1"}, format="json")):
            self.assertEqual((r.status_code, r.json()["detail"]), (400, "要指定廠商"), r.content.decode())
        for bad in (5, ["moceo"], {"code": "moceo"}, True):          # 代碼只能是字
            r = self.clerk.post(SYNC, {"warehouse": self.wh1.id, "vendor": bad}, format="json")
            self.assertEqual((r.status_code, r.json()["detail"]), (400, "廠商不對"), bad)
        r = self.clerk.get(f"{CATALOG}?vendor=nobody")
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "廠商名單上沒有「nobody」這一家,請平台管理員處理"))
        self.assertEqual((VendorOrder.objects.count(), VendorSecret.objects.count()), (0, 2))
        # 只剩一家在合作:不講就是那一家
        Vendor.objects.filter(code="acme").update(is_active=False)
        r = self.clerk.get(CATALOG)
        self.assertEqual((r.status_code, r.json()["vendor"]), (200, "moceo"))


class RoutingTests(_TwoVendors):
    def test_a_key_only_ever_goes_to_the_vendor_it_belongs_to(self):
        self.open_both()
        self.clerk.get(f"{CATALOG}?vendor=moceo")
        self.clerk.get(f"{CATALOG}?vendor=acme")
        self.order(key="draft-moceo1")
        self.order(key="draft-acme01", vendor="acme")
        self.clerk.post(SYNC, {"warehouse": self.wh1.id, "vendor": "moceo"}, format="json")
        self.clerk.post(SYNC, {"warehouse": self.wh1.id, "vendor": "acme"}, format="json")
        self.assertEqual(({c[2] for c in self.vendor.calls}, set(self.vendor.bases)), ({KEY}, {MOCEO_BASE}))
        self.assertEqual(({c[2] for c in self.acme_site.calls}, set(self.acme_site.bases)), ({ACME_KEY}, {ACME_BASE}))
        self.assertTrue(self.vendor.posts() and self.acme_site.posts())

    def test_a_key_pasted_under_the_wrong_vendor_is_not_saved(self):
        r = self.link(vendor="acme", key=KEY)             # 膜總裁的金鑰貼到乙配件那一張卡
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "乙配件不認得這把金鑰(打錯、或已經作廢),沒有存"))
        self.assertEqual((VendorSecret.objects.count(), self.vendor.calls), (0, []))          # 膜總裁那邊沒有收到任何請求
        r = self.link(key=ACME_KEY)                       # 反過來:樣子就不對(膜總裁的金鑰有固定的開頭),連問都不問
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "這不像膜總裁的金鑰(要以 mk_live_ 開頭、中間沒有空白)"))
        self.assertEqual((VendorSecret.objects.count(), self.vendor.calls), (0, []))
        r = self.link(vendor="acme", key="有 空白" * 5)
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "這不像乙配件的金鑰(中間沒有空白)"))
        self.assertEqual(self.acme_site.calls[1:], [])

    def test_a_vendor_without_an_address_is_never_contacted(self):
        ensure_vendor("noapi", "丙廠商", "", "", ("配件",))
        r = self.link(vendor="noapi", key=ACME_KEY)
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "「丙廠商」還沒有設定怎麼連線,請平台管理員處理"))
        self.assertEqual((self.vendor.calls, self.acme_site.calls, VendorSecret.objects.count()), ([], [], 0))

    def test_each_vendor_has_its_own_settings_catalog_orders_and_progress(self):
        self.open_both()
        self.admin.post(LINKS, {"warehouse": self.wh1.id, "vendor": "acme", "payment_method": "貨到付款",
                                "ship_address": "新竹市配件路 9 號"}, format="json")
        rows = self.rows()
        self.assertEqual((rows[(self.wh1.id, "moceo")]["payment_method"], rows[(self.wh1.id, "acme")]["payment_method"],
                          rows[(self.wh1.id, "acme")]["ship_address"], rows[(self.wh1.id, "moceo")]["ship_address"]),
                         ("月結", "貨到付款", "新竹市配件路 9 號", "新竹市湳雅街 1 號"))
        a = self.order(key="draft-moceo1").json()
        b = self.order(key="draft-acme01", vendor="acme", lines=[{"key": "G01", "packs": 3}]).json()
        # 兩家各自編號,單號剛好一樣也沒關係(廠商單號只在同一家廠商裡不重複)
        self.assertEqual((a["vendor_order_no"], b["vendor_order_no"]), ("MO-20261010-001", "MO-20261010-001"))
        self.assertEqual([(o["provider"], o["provider_label"], o["payment_method"], o["ship_address"], o["items"][0]["sku"])
                          for o in (a, b)],
                         [("moceo", "膜總裁", "月結", "新竹市湳雅街 1 號", "G02"), ("acme", "乙配件", "貨到付款", "新竹市配件路 9 號", "G01")])
        listed = lambda q: [o["id"] for o in self.clerk.get(f"{ORDERS}{q}").json()["results"]]          # noqa: E731
        self.assertEqual((listed("?vendor=moceo"), listed("?vendor=acme"), listed("")), ([a["id"]], [b["id"]], [b["id"], a["id"]]))
        # 更新進度:只問那一家、只動那一家的單;「不是從這裡叫的」也是那一家的
        self.acme_site.placed[(ACME_KEY, "pos-a-draft-acme01")]["status"] = "已出貨"
        self.acme_site.outside = [{"order_no": "AC-OUT-1", "total_amount": 500}]
        self.vendor.calls.clear()
        r = self.clerk.post(SYNC, {"warehouse": self.wh1.id, "vendor": "acme"}, format="json")
        self.assertEqual(([(o["id"], o["vendor_status"]) for o in r.json()["results"]], [x["order_no"] for x in r.json()["others"]]),
                         ([(b["id"], "已出貨")], ["AC-OUT-1"]))
        self.assertEqual((self.vendor.calls, VendorOrder.objects.get(pk=a["id"]).vendor_status), ([], ""))

    def test_messages_name_the_vendor_they_are_about(self):
        self.open_both()
        self.acme_site.read_down = True
        r = self.clerk.get(f"{CATALOG}?vendor=acme")
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "連不到乙配件,請稍後再試"))
        self.acme_site.read_down = False
        self.acme_site.script = [(400, "庫存不足")]
        r = self.order(key="draft-acme01", vendor="acme")
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "乙配件沒有收這張單:庫存不足"))
        self.admin.post(f"{LINKS}{self.wh1.id}/remove-key/", {"vendor": "acme"}, format="json")
        r = self.clerk.get(f"{CATALOG}?vendor=acme")
        self.assertEqual((r.status_code, "還沒有設定乙配件的金鑰" in r.json()["detail"]), (400, True))
        # 拿掉的是乙配件那一把;膜總裁的還在
        self.assertEqual(self.clerk.get(f"{CATALOG}?vendor=moceo").status_code, 200)

    def test_one_draft_key_belongs_to_one_vendor(self):
        self.open_both()
        a = self.order(key="draft-0001").json()
        r = self.order(key="draft-0001", vendor="acme")
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "這把鑰匙是另一家廠商的叫貨單"))
        self.assertEqual((self.acme_site.posts(), VendorOrder.objects.count()), ([], 1))
        self.assertEqual(self.order(key="draft-0001").json()["id"], a["id"])

    def test_goods_from_each_vendor_are_received_under_that_vendor(self):
        self.open_both()
        film = Product.objects.create(tenant=self.t, category=self.c.cat_case, name="甲 保護貼", requires_serial=False)
        cable = Product.objects.create(tenant=self.t, category=self.c.cat_case, name="甲 充電線", requires_serial=False)
        a = self.order(key="draft-moceo1").json()
        b = self.order(key="draft-acme01", vendor="acme").json()
        self.vendor.calls.clear()
        r = self.clerk.post(f"{ORDERS}{b['id']}/receive/", {"request_key": "recv-acme01",
                                                          "lines": [{"key": "G02||p", "qty": 50, "product": cable.id}]}, format="json")
        self.assertEqual(r.status_code, 201, r.content.decode())
        self.assertEqual(self.vendor.calls, [])                 # 乙配件的單只問乙配件
        po = PurchaseOrder.objects.get(tenant=self.t)
        self.assertEqual((po.supplier.name, po.note), ("乙配件", "乙配件 MO-20261010-001 到貨入庫"))
        r = self.clerk.post(f"{ORDERS}{a['id']}/receive/", {"request_key": "recv-moceo1",
                                                          "lines": [{"key": "G02||p", "qty": 50, "product": film.id}]}, format="json")
        self.assertEqual(r.status_code, 201, r.content.decode())
        # 同一個料號 G02 在兩家是兩回事:各記各的、各自的供應商
        self.assertEqual(sorted(SupplierProduct.objects.values_list("platform", "supplier__name", "vendor_sku", "product__name")),
                         [("acme", "乙配件", "G02", "甲 充電線"), ("moceo", "膜總裁", "G02", "甲 保護貼")])
        self.assertEqual(sorted(Supplier.objects.filter(tenant=self.t, name__in=["膜總裁", "乙配件"]).values_list("name", flat=True)),
                         ["乙配件", "膜總裁"])
        # 「不是從這裡叫的」:認進來的是那一家的單
        self.acme_site.outside = [{"order_no": "AC-OUT-1", "total_amount": 1500, "items": [FakeVendor.line("G02", 10, shipped=10)]}]
        r = self.clerk.post(ADOPT, {"warehouse": self.wh1.id, "vendor": "acme", "order_no": "AC-OUT-1"}, format="json")
        self.assertEqual((r.status_code, r.json()["provider"], r.json()["source"]), (200, "acme", "outside"))
        r = self.clerk.post(ADOPT, {"warehouse": self.wh1.id, "vendor": "moceo", "order_no": "AC-OUT-1"}, format="json")
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "膜總裁:找不到這張單"))

    def test_two_vendors_can_use_the_same_order_number_for_orders_placed_elsewhere(self):
        """兩家廠商各自編號:電話叫的單在兩家剛好都是 SO-0001,兩張都要認得進來(複審 2026-10-10:第二張會出錯)。"""
        self.open_both()
        for site in (self.vendor, self.acme_site):
            site.outside = [{"order_no": "SO-0001", "total_amount": 1500, "items": [FakeVendor.line("G02", 10, shipped=10)]}]
        got = {}
        for code in ("moceo", "acme"):
            r = self.clerk.post(ADOPT, {"warehouse": self.wh1.id, "vendor": code, "order_no": "SO-0001"}, format="json")
            self.assertEqual((r.status_code, r.json().get("provider"), r.json().get("vendor_order_no")), (200, code, "SO-0001"),
                             r.content.decode())
            got[code] = r.json()["id"]
        self.assertNotEqual(got["moceo"], got["acme"])
        # 再認一次是各自原本那一筆
        for code in ("moceo", "acme"):
            r = self.clerk.post(ADOPT, {"warehouse": self.wh1.id, "vendor": code, "order_no": "SO-0001"}, format="json")
            self.assertEqual(r.json()["id"], got[code])
        self.assertEqual(VendorOrder.objects.filter(vendor_order_no="SO-0001").count(), 2)
        # 鑰匙放得進欄位(廠商代碼最長 20、單號最長 40)
        from .receiving import outside_key
        self.assertLessEqual(len(outside_key("x" * 20, "y" * 40)), VendorOrder._meta.get_field("request_key").max_length)
        self.assertNotEqual(outside_key("ab", "c"), outside_key("a", "bc"))


class StoppedVendorTests(_TwoVendors):
    def setUp(self):
        super().setUp()
        self.open_both()
        self.placed = self.order(key="draft-acme01", vendor="acme").json()
        self.acme_site.script = ["lost"]
        self.unsure = self.order(key="draft-acme02", vendor="acme").json()
        Vendor.objects.filter(code="acme").update(is_active=False)

    def test_no_new_orders_and_no_new_keys(self):
        posts = len(self.acme_site.posts())
        r = self.clerk.get(f"{CATALOG}?vendor=acme")
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "「乙配件」已經停用,不能叫新的貨"))
        r = self.order(key="draft-acme03", vendor="acme")
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "「乙配件」已經停用,不能叫新的貨"))
        r = self.link(vendor="acme", key=ACME_KEY)
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "「乙配件」已經停用,不能新開通或換金鑰"))
        r = self.link(store=self.wh2, vendor="acme", key="")
        self.assertEqual(r.status_code, 400, r.content.decode())           # 沒設定過的門市不能新開
        self.assertEqual((len(self.acme_site.posts()), VendorOrder.objects.count(), VendorLink.objects.filter(provider="acme").count()),
                         (posts, 2, 1))
        # 名單:設定過的那家門市還看得到這一家(紀錄要看),沒設定過的門市不列
        rows = self.rows()
        self.assertEqual((rows[(self.wh1.id, "acme")]["vendor_active"], (self.wh2.id, "acme") in rows), (False, False))

    def test_what_was_already_ordered_can_still_be_finished(self):
        self.assertEqual([o["id"] for o in self.clerk.get(f"{ORDERS}?vendor=acme").json()["results"]],
                         [self.unsure["id"], self.placed["id"]])
        r = self.clerk.post(f"{ORDERS}{self.unsure['id']}/resend/")               # 確認不確定的那一張
        self.assertEqual((r.status_code, r.json()["state"]), (200, "placed"), r.content.decode())
        # 同一把鑰匙再來:回原本那一張(不會被「已經停用」擋在外面)
        r = self.order(key="draft-acme01", vendor="acme")
        self.assertEqual((r.status_code, r.json()["id"]), (200, self.placed["id"]))
        self.assertEqual(self.clerk.post(SYNC, {"warehouse": self.wh1.id, "vendor": "acme"}, format="json").status_code, 200)
        cable = Product.objects.create(tenant=self.t, category=self.c.cat_case, name="甲 充電線", requires_serial=False)
        self.assertEqual(self.clerk.get(f"{ORDERS}{self.placed['id']}/receiving/").status_code, 200)
        r = self.clerk.post(f"{ORDERS}{self.placed['id']}/receive/", {"request_key": "recv-acme01",
                                                                    "lines": [{"key": "G02||p", "qty": 50, "product": cable.id}]}, format="json")
        self.assertEqual(r.status_code, 201, r.content.decode())
        # 設定還改得了(入庫供應商、運費);金鑰可以拿掉
        r = self.link(vendor="acme", key="", freight_into_cost=False)
        self.assertEqual((r.status_code, r.json()["freight_into_cost"]), (200, False))
        r = self.admin.post(f"{LINKS}{self.wh1.id}/remove-key/", {"vendor": "acme"}, format="json")
        self.assertEqual((r.status_code, r.json()["has_key"]), (200, False))

    def test_a_code_that_is_no_longer_on_the_list_is_shown_but_cannot_be_acted_on(self):
        """備份還原到別台、那邊的名單沒有這一家:單照樣看得到(名稱寫代碼),不能再對廠商做任何事。"""
        Vendor.objects.filter(code="acme").delete()
        got = {o["id"]: o for o in self.clerk.get(ORDERS).json()["results"]}
        self.assertEqual((got[self.placed["id"]]["provider"], got[self.placed["id"]]["provider_label"]), ("acme", "acme"))
        self.assertNotIn((self.wh1.id, "acme"), self.rows())
        wrong = "廠商名單上沒有「acme」這一家,請平台管理員處理"
        for r in (self.clerk.post(f"{ORDERS}{self.unsure['id']}/resend/"), self.clerk.get(f"{ORDERS}{self.placed['id']}/receiving/"),
                  self.clerk.post(SYNC, {"warehouse": self.wh1.id, "vendor": "acme"}, format="json"),
                  self.clerk.post(f"{ORDERS}{self.placed['id']}/receive/", {"request_key": "recv-acme01", "lines": [
                      {"key": "G02||p", "qty": 1, "product": self.c.case.id}]}, format="json")):
            self.assertEqual((r.status_code, r.json()["detail"]), (400, wrong), r.content.decode())
        self.assertEqual(VendorOrder.objects.get(pk=self.unsure["id"]).state, "unknown")          # 沒有被改成別的狀態


class WhoMayOrderTests(_TwoVendors):
    """員工帳號的「廠商叫貨」是總開關;每家門市 × 每家廠商另外一格:店員也可 / 只限管理。"""

    def setUp(self):
        super().setUp()
        self.open_both()
        self.acme_site.script = ["lost"]
        self.unsure = self.order(key="draft-acme02", vendor="acme").json()
        r = self.link(vendor="acme", key="", clerk_ordering=False)
        self.assertEqual((r.status_code, r.json()["clerk_ordering"]), (200, False))

    def test_clerks_are_kept_out_of_that_one_vendor_only(self):
        posts = len(self.acme_site.posts())
        wrong = "這家門市設定只有管理員可以跟乙配件叫貨"
        for r in (self.clerk.get(f"{CATALOG}?vendor=acme"), self.order(key="draft-acme03", vendor="acme"),
                  self.clerk.post(f"{ORDERS}{self.unsure['id']}/resend/")):
            self.assertEqual((r.status_code, r.json()["detail"]), (403, wrong), r.content.decode())
        self.assertEqual((len(self.acme_site.posts()), VendorOrder.objects.count()), (posts, 1))
        # 另一家照常;這一家管理員照常
        self.assertEqual(self.clerk.get(f"{CATALOG}?vendor=moceo").status_code, 200)
        self.assertEqual(self.order(key="draft-moceo1").status_code, 201)
        self.assertEqual(self.admin.get(f"{CATALOG}?vendor=acme&warehouse={self.wh1.id}").status_code, 200)
        self.assertEqual(self.order(key="draft-acme04", vendor="acme", client=self.admin).status_code, 201)
        self.assertEqual(self.admin.post(f"{ORDERS}{self.unsure['id']}/resend/").json()["state"], "placed")

    def test_records_progress_and_receiving_stay_open_to_clerks(self):
        self.assertIn(self.unsure["id"], [o["id"] for o in self.clerk.get(f"{ORDERS}?vendor=acme").json()["results"]])
        self.assertEqual(self.clerk.post(SYNC, {"warehouse": self.wh1.id, "vendor": "acme"}, format="json").status_code, 200)
        placed = self.order(key="draft-acme05", vendor="acme", client=self.admin).json()
        self.assertEqual(self.clerk.get(f"{ORDERS}{placed['id']}/receiving/").status_code, 200)       # 入庫看的是「進貨入庫」
        # 店員看得到這一格(畫面要知道這一家對他是灰的),但改不了
        self.assertEqual(self.rows(self.clerk)[(self.wh1.id, "acme")]["clerk_ordering"], False)
        self.assertEqual(self.link(vendor="acme", key="", clerk_ordering=True, client=self.clerk).status_code, 403)
        self.assertFalse(VendorLink.objects.get(provider="acme").clerk_ordering)

    def test_the_setting_is_a_plain_yes_or_no_and_new_stores_start_open(self):
        for bad in ("no", 0, None, "false"):
            self.assertEqual(self.link(vendor="acme", key="", clerk_ordering=bad).status_code, 400, bad)
        self.assertFalse(VendorLink.objects.get(provider="acme").clerk_ordering)
        self.assertEqual(self.link(vendor="acme", key="").json()["clerk_ordering"], False)      # 沒帶這一格 = 不動
        rows = self.rows()
        self.assertEqual((rows[(self.wh1.id, "moceo")]["clerk_ordering"], rows[(self.wh2.id, "acme")]["clerk_ordering"]), (True, True))
        self.assertEqual(self.link(vendor="acme", key="", clerk_ordering=True).json()["clerk_ordering"], True)
        self.assertEqual(self.clerk.get(f"{CATALOG}?vendor=acme").status_code, 200)


class OtherCompanyTests(_TwoVendors):
    def test_the_list_is_shared_but_keys_orders_and_settings_are_not(self):
        self.open_both()
        mine = self.order(key="draft-acme01", vendor="acme").json()
        other = Company("b", "乙通訊行", "乙")
        rows = {(x["warehouse_name"], x["provider"]): x for x in other.admin.get(LINKS).json()["results"]}
        self.assertEqual({p for _, p in rows}, {"moceo", "acme"})                 # 名單一樣
        self.assertFalse(any(x["has_key"] or x["saved"] for x in rows.values()))   # 別家公司的金鑰與設定跟它無關
        r = other.admin.get(f"{CATALOG}?vendor=acme&warehouse={other.wh.id}")
        self.assertEqual((r.status_code, "還沒有設定乙配件的金鑰" in r.json()["detail"]), (400, True))
        self.assertEqual(other.admin.get(f"{ORDERS}{mine['id']}/").status_code, 404)
        self.assertEqual(other.admin.get(ORDERS).json()["results"], [])
        self.assertEqual(secrets.reveal(VendorLink.objects.get(tenant=self.t, provider="acme")), ACME_KEY)
