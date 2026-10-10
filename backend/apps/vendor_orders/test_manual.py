"""半自動的廠商(廠商那邊什麼都不用改)。跑法:manage.py test apps.vendor_orders.test_manual

要守住的:**半自動的每一步都不打任何外部系統**;價目表只有平台管理員能改、所有店家同一份;叫貨單 POS 自己成立、同一把鑰匙只有一張;
傳了沒 / 進度 / 取消是人記的;到貨照店家叫的單入庫、單價是入庫的人填的、同一批貨不入兩次。
"""
from decimal import Decimal as D

from django.contrib.auth import get_user_model

from apps.backup import registry
from apps.backup.tests.factory import Company
from apps.catalog.models import Product, SupplierProduct
from apps.inventory.models import StockBalance
from apps.purchasing.models import PurchaseOrder
from apps.tenants.models import UserProfile

from .models import Vendor, VendorCategory, VendorItem, VendorLink, VendorOrder, VendorReceipt, VendorSecret
from .tests import CATALOG, KEY, LINKS, ORDERS, SYNC, _Shop

P_VENDORS = "/api/v1/platform/vendors/"
P_ITEM = "/api/v1/platform/vendor-items/"
ADOPT = "/api/v1/vendor-orders/adopt/"
MAPPINGS = "/api/v1/vendor-orders/mappings/"
C01, H01, C02, X09 = "C01||p", "H01||p", "C02||p", "X09||p"


class _Manual(_Shop):
    """名單上多一家半自動的「乙配件」:價目表四項(快充線 1M 有參考價、充電頭沒有、快充線 2M、一項停賣的)。"""

    def setUp(self):
        super().setUp()
        self.acme = Vendor.objects.create(code="acme", name="乙配件", protocol=Vendor.Protocol.MANUAL,
                                          contact="LINE @acme", sort_order=5)
        self.acme.categories.set([VendorCategory.objects.get_or_create(name="配件")[0]])
        item = lambda sku, name, **more: VendorItem.objects.create(vendor=self.acme, sku=sku, name=name, **more)
        self.c01 = item("C01", "快充線", spec="1M", kind="線材", unit="條", pack_qty=10, ref_price=45, sort_order=1)
        self.h01 = item("H01", "20W 充電頭", kind="充電器", unit="個", pack_qty=5, sort_order=2)            # 沒有參考價
        self.c02 = item("C02", "快充線", spec="2M", kind="線材", unit="條", pack_qty=10, ref_price=60, sort_order=3)
        self.x09 = item("X09", "停賣的線", unit="條", pack_qty=10, ref_price=30, is_active=False, sort_order=4)
        # 另一家半自動的廠商,有自己的價目表:兩家的品項互不相干
        self.gamma = Vendor.objects.create(code="gamma", name="丁零件", protocol=Vendor.Protocol.MANUAL, sort_order=6)
        VendorItem.objects.create(vendor=self.gamma, sku="G99", name="丁家的螢幕", unit="片", pack_qty=1, ref_price=900)
        self.cable = self.product("甲 快充線 1M")
        self.head = self.product("甲 20W 充電頭")
        self.vendor.calls.clear()

    def product(self, name, **extra):
        return Product.objects.create(tenant=self.t, category=self.c.cat_case, name=name,
                                      **{"requires_serial": False, "list_price": 199, **extra})

    def open(self, store=None, client=None, **extra):
        body = {"warehouse": (store or self.wh1).id, "vendor": "acme", "opened": True, "ship_name": "甲湳雅店",
                "ship_phone": "035551234", "ship_address": "新竹市湳雅街 1 號", **extra}
        return (client or self.admin).post(LINKS, body, format="json")

    def buy(self, lines=None, key="draft-m001", client=None, store=None, **extra):
        body = {"request_key": key, "warehouse": (store or self.wh1).id, "vendor": "acme",
                "lines": [{"key": "C01", "packs": 2}, {"key": "H01", "packs": 1}] if lines is None else lines, **extra}
        return (client or self.clerk).post(ORDERS, body, format="json")

    def row(self, client=None, store=None):
        rows = (client or self.admin).get(LINKS).json()["results"]
        return next(x for x in rows if x["provider"] == "acme" and x["warehouse"] == (store or self.wh1).id)

    def stock(self, product, warehouse=None):
        got = StockBalance.objects.filter(tenant=self.t, product=product, warehouse=warehouse or self.wh1).first()
        return (got.qty, got.weighted_avg_cost) if got else (0, D("0"))

    def assertNothingWentOut(self):
        self.assertEqual(self.vendor.calls, [], "半自動的不能打任何外部系統")


# ── 平台:半自動的廠商與價目表 ──────────────────────────────────────────────────
class PlatformTests(_Manual):
    def setUp(self):
        super().setUp()
        root = get_user_model().objects.create_user(username="root", password="pw-12345")
        UserProfile.objects.create(user=root, role="platform_admin")
        self.root = self.c.client(root)
        self.items = f"{P_VENDORS}{self.acme.id}/items/"

    def test_a_vendor_without_a_system_needs_no_address(self):
        r = self.root.post(P_VENDORS, {"code": "beta", "name": "丙廠", "protocol": "manual", "order_email": " boss@beta.tw ",
                                       "contact": " LINE @beta "}, format="json")
        self.assertEqual(r.status_code, 201, r.content.decode())
        self.assertEqual((r.json()["protocol"], r.json()["api_base"], r.json()["order_email"], r.json()["contact"], r.json()["items"]),
                         ("manual", "", "boss@beta.tw", "LINE @beta", 0))
        # 全自動的一樣要有網址
        r = self.root.post(P_VENDORS, {"code": "gamma", "name": "丁廠", "protocol": "standard"}, format="json")
        self.assertEqual(r.status_code, 400, r.content.decode())
        for bad in ({"api_base": "http://x.test/api"}, {"order_email": "不是信箱"}, {"contact": "x" * 121}, {"protocol": "fax"}):
            r = self.root.post(P_VENDORS, {"code": "delta", "name": "戊廠", "protocol": "manual", **bad}, format="json")
            self.assertEqual(r.status_code, 400, (bad, r.content.decode()))
        self.assertEqual(sorted(Vendor.objects.values_list("code", flat=True)), ["acme", "beta", "gamma", "moceo"])
        # 全自動的改成半自動:網址可以留著、也可以清掉;改回全自動沒有網址不行
        r = self.root.patch(f"{P_VENDORS}{Vendor.objects.get(code='beta').id}/", {"protocol": "standard"}, format="json")
        self.assertEqual(r.status_code, 400, r.content.decode())

    def test_the_list_counts_opened_stores_and_items(self):
        self.assertEqual(self.open().status_code, 200)
        self.link()                                          # 膜總裁那一家也開通(有金鑰)
        got = {v["code"]: (v["stores"], v["items"], v["protocol_label"]) for v in self.root.get(P_VENDORS).json()["results"]}
        self.assertEqual(got, {"moceo": (1, 0, "全自動(標準格式)"), "acme": (1, 3, "半自動(人工傳單)"),
                               "gamma": (0, 1, "半自動(人工傳單)")})
        self.assertEqual(self.open(opened=False).status_code, 200)
        self.assertEqual({v["code"]: v["stores"] for v in self.root.get(P_VENDORS).json()["results"]}["acme"], 0)

    def test_only_the_platform_admin_touches_the_price_list(self):
        for client in (self.admin, self.clerk):
            for method, url, body in (("get", self.items, None), ("post", self.items, {"name": "偷加的"}),
                                      ("patch", f"{P_ITEM}{self.c01.id}/", {"ref_price": 1}),
                                      ("post", f"{self.items}import/", {"rows": [{"name": "偷貼的"}], "apply": True})):
                r = getattr(client, method)(url, body, format="json") if body is not None else getattr(client, method)(url)
                self.assertEqual(r.status_code, 403, (method, url))
        self.c01.refresh_from_db()
        self.assertEqual((VendorItem.objects.filter(vendor=self.acme).count(), self.c01.ref_price), (4, D("45.00")))
        r = self.root.get(self.items)
        self.assertEqual([(i["sku"], i["is_active"], i["ref_price"]) for i in r.json()["results"]],
                         [("C01", True, "45.00"), ("H01", True, None), ("C02", True, "60.00"), ("X09", False, "30.00")])

    def test_adding_one_item_gives_it_a_number_when_none_is_typed(self):
        r = self.root.post(self.items, {"name": " 傳輸線 ", "spec": "0.5M", "unit": "條", "pack_qty": "20", "ref_price": "1,200.5"},
                           format="json")
        self.assertEqual(r.status_code, 201, r.content.decode())
        self.assertEqual((r.json()["sku"], r.json()["name"], r.json()["pack_qty"], r.json()["ref_price"], r.json()["is_active"]),
                         ("N0001", "傳輸線", 20, "1200.50", True))
        self.assertEqual(self.root.post(self.items, {"name": "行動電源"}, format="json").json()["sku"], "N0002")
        r = self.root.post(self.items, {"name": "自己編號的", "sku": "PB-01"}, format="json")
        self.assertEqual((r.status_code, r.json()["sku"], r.json()["pack_qty"], r.json()["ref_price"]), (201, "PB-01", 1, None))
        for bad in ({"name": ""}, {"name": "x" * 201}, {"name": "重複的料號", "sku": "C01"}, {"name": "有空白", "sku": "A 1"},
                    {"name": "有井號", "sku": "A#1"}, {"name": "有直線", "sku": "A|1"}, {"name": "包", "pack_qty": 0},
                    {"name": "包", "pack_qty": 1.5}, {"name": "包", "pack_qty": True}, {"name": "價", "ref_price": -1},
                    {"name": "價", "ref_price": "1.234"}, {"name": "價", "ref_price": "abc"}, {"name": "價", "ref_price": True}):
            r = self.root.post(self.items, bad, format="json")
            self.assertEqual(r.status_code, 400, (bad, r.content.decode()))
        self.assertEqual(VendorItem.objects.filter(vendor=self.acme).count(), 7)

    def test_an_item_can_be_changed_or_switched_off_but_not_renumbered(self):
        url = f"{P_ITEM}{self.c01.id}/"
        r = self.root.patch(url, {"name": "快充線(編織)", "ref_price": None, "is_active": False, "pack_qty": 12}, format="json")
        self.assertEqual((r.status_code, r.json()["name"], r.json()["ref_price"], r.json()["is_active"], r.json()["pack_qty"]),
                         (200, "快充線(編織)", None, False, 12), r.content.decode())
        r = self.root.patch(url, {"sku": "C99"}, format="json")
        self.assertEqual((r.status_code, "料號建了不能改" in r.json()["detail"]), (400, True))
        self.assertEqual(self.root.patch(url, {"sku": "C01", "unit": "組"}, format="json").status_code, 200)      # 帶原本的料號不算改
        self.assertEqual(self.root.patch(f"{P_ITEM}999999/", {"name": "x"}, format="json").status_code, 404)
        self.assertEqual(self.root.delete(url).status_code, 405)                                                 # 只能停用,不能刪

    def test_a_vendor_with_its_own_system_has_no_price_list(self):
        for r in (self.root.get(f"{P_VENDORS}{self.moceo.id}/items/"),
                  self.root.post(f"{P_VENDORS}{self.moceo.id}/items/", {"name": "x"}, format="json"),
                  self.root.post(f"{P_VENDORS}{self.moceo.id}/items/import/", {"rows": [{"name": "x"}]}, format="json")):
            self.assertEqual((r.status_code, "不用建價目表" in r.json()["detail"]), (400, True))
        self.assertEqual(self.root.get(f"{P_VENDORS}999999/items/").status_code, 404)

    def test_pasting_a_sheet_is_previewed_first_and_nothing_is_saved_until_confirmed(self):
        rows = [
            {"name": "快充線", "spec": "1M", "ref_price": "48"},                  # 沒料號:品名 + 規格對到 C01 → 更新價錢
            {"sku": "H01", "name": "20W 充電頭", "unit": "", "pack_qty": ""},      # 空著的格子 = 不改 → 沒變
            {"name": "行動電源", "spec": "10000mAh", "unit": "個", "pack_qty": "4", "ref_price": "$1,250"},   # 新的,系統給料號
            {"sku": "PB-02", "name": "行動電源", "spec": "20000mAh"},              # 新的,自己的料號
            {"name": "磁吸支架"},                                                  # 新的,系統給下一個料號
        ]
        r = self.root.post(f"{self.items}import/", {"rows": rows}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        got = r.json()
        self.assertEqual((got["applied"], got["counts"]), (False, {"new": 3, "update": 1, "same": 1, "error": 0}))
        self.assertEqual([(x["line"], x["action"], x["sku"], x["changes"]) for x in got["rows"]], [
            (1, "update", "C01", {"ref_price": "48.00"}),
            (2, "same", "H01", {}),
            (3, "new", "N0001", {"pack_qty": "4", "name": "行動電源", "spec": "10000mAh", "unit": "個", "ref_price": "1250.00"}),
            (4, "new", "PB-02", {"pack_qty": "1", "name": "行動電源", "spec": "20000mAh"}),
            (5, "new", "N0002", {"pack_qty": "1", "name": "磁吸支架"}),
        ])
        self.c01.refresh_from_db()
        self.assertEqual((VendorItem.objects.filter(vendor=self.acme).count(), self.c01.ref_price), (4, D("45.00")))          # 預覽不存
        r = self.root.post(f"{self.items}import/", {"rows": rows, "apply": True}, format="json")
        self.assertEqual((r.status_code, r.json()["applied"]), (200, True), r.content.decode())
        self.c01.refresh_from_db()
        self.h01.refresh_from_db()
        self.assertEqual((self.c01.ref_price, self.c01.unit, self.h01.unit, self.h01.pack_qty), (D("48.00"), "條", "個", 5))
        new = {i.sku: (i.name, i.spec, i.unit, i.pack_qty, i.ref_price, i.is_active) for i in VendorItem.objects.filter(sku__in=["N0001", "PB-02", "N0002"])}
        self.assertEqual(new, {"N0001": ("行動電源", "10000mAh", "個", 4, D("1250.00"), True),
                               "PB-02": ("行動電源", "20000mAh", "", 1, None, True), "N0002": ("磁吸支架", "", "", 1, None, True)})
        # 同一份再貼一次:全部沒變,不會多出重複的
        r = self.root.post(f"{self.items}import/", {"rows": rows, "apply": True}, format="json")
        self.assertEqual((r.json()["counts"]["same"], VendorItem.objects.filter(vendor=self.acme).count()), (5, 7))

    def test_updating_by_number_leaves_blank_cells_alone_including_the_spec(self):
        """複審 2026-10-11:照料號更新價錢、沒貼規格那一欄 → 原本的規格(1M)不能被清掉。品名一定有,所以品名照貼上來的改。"""
        rows = [{"sku": "C01", "name": "快充線", "ref_price": "48"},                          # 規格、種類、單位、一包幾個都空著
                {"sku": "C02", "name": "快充線(新款)", "spec": "2.0M", "pack_qty": "12"}]
        preview = self.root.post(f"{self.items}import/", {"rows": rows}, format="json").json()
        self.assertEqual([(x["action"], x["sku"], x["changes"]) for x in preview["rows"]],
                         [("update", "C01", {"ref_price": "48.00"}),
                          ("update", "C02", {"name": "快充線(新款)", "spec": "2.0M", "pack_qty": "12"})])
        r = self.root.post(f"{self.items}import/", {"rows": rows, "apply": True}, format="json")
        self.assertEqual((r.status_code, r.json()["applied"]), (200, True), r.content.decode())
        self.c01.refresh_from_db()
        self.c02.refresh_from_db()
        self.assertEqual((self.c01.name, self.c01.spec, self.c01.kind, self.c01.unit, self.c01.pack_qty, self.c01.ref_price),
                         ("快充線", "1M", "線材", "條", 10, D("48.00")))
        self.assertEqual((self.c02.name, self.c02.spec, self.c02.pack_qty, self.c02.ref_price), ("快充線(新款)", "2.0M", 12, D("60.00")))

    def test_a_number_someone_typed_is_not_handed_out_again_in_the_same_sheet(self):
        """複審 2026-10-11:同一批裡有人自己填了 N0001、另一列讓系統給號 → 不能兩列都是 N0001(存的時候會撞)。"""
        rows = [{"sku": "N0001", "name": "甲"}, {"name": "乙"}, {"sku": "N0003", "name": "丙"}, {"name": "丁"}]
        preview = self.root.post(f"{self.items}import/", {"rows": rows}, format="json").json()
        self.assertEqual([(x["action"], x["sku"]) for x in preview["rows"]],
                         [("new", "N0001"), ("new", "N0004"), ("new", "N0003"), ("new", "N0005")])
        r = self.root.post(f"{self.items}import/", {"rows": rows, "apply": True}, format="json")
        self.assertEqual((r.status_code, r.json()["applied"]), (200, True), r.content.decode())
        self.assertEqual(dict(VendorItem.objects.filter(vendor=self.acme, sku__startswith="N").values_list("sku", "name")),
                         {"N0001": "甲", "N0004": "乙", "N0003": "丙", "N0005": "丁"})

    def test_one_bad_row_keeps_the_whole_sheet_out(self):
        VendorItem.objects.create(vendor=self.acme, sku="C01B", name="快充線", spec="1M")            # 價目表上兩項同名同規格
        rows = [{"name": "好的一列", "ref_price": "10"}, {"name": ""}, {"name": "價錢亂寫", "ref_price": "十塊"},
                {"sku": "DUP", "name": "甲"}, {"sku": "DUP", "name": "乙"}, {"name": "同名", "spec": "A"}, {"name": "同名", "spec": "A"},
                {"name": "快充線", "spec": "1M"}, "不是一列"]
        preview = self.root.post(f"{self.items}import/", {"rows": rows}, format="json").json()
        self.assertEqual([x["action"] for x in preview["rows"]], ["new", "error", "error", "new", "error", "new", "error", "error", "error"])
        self.assertEqual(["重複" in preview["rows"][4]["problem"], "不只一項" in preview["rows"][7]["problem"]], [True, True])
        r = self.root.post(f"{self.items}import/", {"rows": rows, "apply": True}, format="json")
        self.assertEqual((r.status_code, r.json()["applied"], r.json()["detail"]), (400, False, "有幾列有問題,整批都沒有存"))
        self.assertEqual(VendorItem.objects.filter(vendor=self.acme).count(), 5)
        for bad in ({}, {"rows": []}, {"rows": "x"}, {"rows": [{"name": "a"}] * 1001}):
            self.assertEqual(self.root.post(f"{self.items}import/", bad, format="json").status_code, 400, str(bad)[:40])

    def test_the_price_list_is_not_company_data(self):
        registry.check_registry()
        self.assertEqual(registry.REGISTRY["vendor_orders.VendorItem"].kind, registry.EXCLUDED)
        self.assertFalse(any(f.name == "tenant" for f in VendorItem._meta.get_fields()))


# ── 店家:開通(沒有金鑰)與商品清單 ────────────────────────────────────────────
class OpenTests(_Manual):
    def test_a_manager_opens_it_without_any_key(self):
        before = self.row()
        self.assertEqual((before["manual"], before["ready"], before["opened"], before["has_key"], before["contact"], before["saved"]),
                         (True, False, False, False, "LINE @acme", False))
        r = self.open(invoice_email="")                       # 發票那幾格是全自動那一套要的,這裡不用填
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.assertEqual((r.json()["ready"], r.json()["opened"], r.json()["has_key"]), (True, True, False))
        self.assertEqual((VendorSecret.objects.count(), VendorLink.objects.get(provider="acme").opened), (0, True))
        self.assertEqual(self.row(self.clerk)["ready"], True)            # 店員看得到這家開通了
        self.assertEqual(self.open(opened=False).json()["ready"], False)  # 可以關掉
        self.assertNothingWentOut()

    def test_what_cannot_be_done_when_opening(self):
        self.assertEqual(self.open(client=self.clerk).status_code, 403)                 # 只有管理員
        r = self.open(key=KEY)
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "「乙配件」不用金鑰(按「開通」就可以叫貨)"))
        self.assertEqual(self.open(opened="yes").status_code, 400)
        r = self.open(ship_address="")                                                  # 宅配沒有地址
        self.assertEqual((r.status_code, "宅配要有收件人" in r.json()["detail"]), (400, True))
        self.assertEqual(self.open(ship_address="", delivery_method="自取").status_code, 200)
        self.assertEqual(self.open(payment_method="記帳").status_code, 400)
        Vendor.objects.filter(code="acme").update(is_active=False)
        VendorLink.objects.filter(provider="acme").update(opened=False)
        r = self.open()
        self.assertEqual((r.status_code, "已經停用" in r.json()["detail"]), (400, True))      # 停用的廠商不能新開通
        self.assertEqual(self.open(opened=False, ship_name="改個名字").status_code, 200)      # 改別的設定可以
        # 全自動的廠商不看「開通」這一格
        self.assertEqual(self.link(opened=True).json()["opened"], False)

    def test_the_catalog_is_the_platforms_price_list(self):
        r = self.clerk.get(f"{CATALOG}?vendor=acme")
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "這家門市還沒有開通乙配件,請管理員到「系統設定 → 叫貨串接」開通"))
        self.assertEqual(self.open().status_code, 200)
        r = self.clerk.get(f"{CATALOG}?vendor=acme")
        self.assertEqual(r.status_code, 200, r.content.decode())
        got = r.json()
        self.assertEqual((got["manual"], got["vendor"], [x["key"] for x in got["rows"]]), (True, "acme", ["C01", "H01", "C02"]))
        self.assertEqual(got["rows"][0], {
            "key": "C01", "sku": "C01", "spec_id": None, "spec_label": "1M", "name": "快充線", "kind": "線材", "size": "",
            "unit": "條", "pack_qty": 10, "unit_price": "45.00", "pack_price": "450.00"})
        self.assertEqual((got["rows"][1]["unit_price"], got["rows"][1]["pack_price"]), (None, None))     # 沒有參考價
        self.assertNotIn("G99", r.content.decode())                                                     # 別家廠商的品項不在這裡
        self.assertEqual(self.clerk.get(f"{CATALOG}?vendor=moceo").json().get("manual"), None)          # 全自動那一家沒開通:400
        self.assertEqual(self.open(clerk_ordering=False).status_code, 200)
        self.assertEqual(self.clerk.get(f"{CATALOG}?vendor=acme").status_code, 403)                     # 只限管理員叫貨
        self.assertEqual(self.admin.get(f"{CATALOG}?vendor=acme&warehouse={self.wh1.id}").status_code, 200)
        self.assertNothingWentOut()


# ── 叫貨:POS 自己成立 ─────────────────────────────────────────────────────────
class OrderTests(_Manual):
    def setUp(self):
        super().setUp()
        self.assertEqual(self.open().status_code, 200)

    def test_an_order_is_made_here_and_nothing_is_sent_anywhere(self):
        r = self.buy(note="請週五前到")
        self.assertEqual(r.status_code, 201, r.content.decode())
        got = r.json()
        order = VendorOrder.objects.get()
        self.assertEqual((got["manual"], got["state"], got["source"], got["vendor_order_no"], got["provider_label"]),
                         (True, "placed", "pos", f"VO-{order.id:06d}", "乙配件"))
        self.assertEqual([(i["sku"], i["name"], i["spec_label"], i["pack_qty"], i["packs"], i["qty"], i["unit_price"]) for i in got["items"]],
                         [("C01", "快充線", "1M", 10, 2, 20, "45.00"), ("H01", "20W 充電頭", "", 5, 1, 5, None)])
        self.assertEqual((got["expected_goods"], got["total_amount"], got["shipping_fee"], got["is_test"]), ("900.00", None, None, None))
        self.assertEqual((got["sent_at"], got["sent_how"], got["progress_note"], got["cancelled_at"], got["created_by"]),
                         (None, "", "", None, "a-clerk"))
        self.assertEqual(got["message"], "\n".join([
            "【叫貨】甲通訊行 甲湳雅店", f"單號 VO-{order.id:06d}({order.created_at.astimezone().strftime('%Y-%m-%d')})",
            "1. 快充線 1M × 2 包(共 20 條)", "2. 20W 充電頭 × 1 包(共 5 個)",
            "收件:甲湳雅店 035551234 新竹市湳雅街 1 號", "付款:月結", "備註:請週五前到"]))
        self.assertNotIn("45", got["message"])                               # 不寫價錢
        self.assertNothingWentOut()

    def test_the_same_key_never_makes_a_second_order(self):
        first = self.buy().json()
        again = self.buy(lines=[{"key": "C02", "packs": 9}])
        self.assertEqual((again.status_code, again.json()["id"], len(again.json()["items"])), (200, first["id"], 2))
        self.assertEqual(VendorOrder.objects.count(), 1)
        self.assertEqual(self.buy(key="draft-m002").status_code, 201)
        self.assertEqual(sorted(VendorOrder.objects.values_list("vendor_order_no", flat=True)),
                         sorted(f"VO-{pk:06d}" for pk in VendorOrder.objects.values_list("id", flat=True)))
        # 這把鑰匙是別家門市 / 別家廠商的單
        self.assertEqual(self.open(store=self.wh2).status_code, 200)
        r = self.buy(client=self.admin, store=self.wh2)
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "這把鑰匙是另一家門市的叫貨單"))
        self.link()
        r = self.order(key="draft-m001")                                    # 同一把鑰匙拿去跟膜總裁叫
        self.assertEqual((r.status_code, "另一家廠商" in r.json()["detail"]), (400, True), r.content.decode())
        real = self.order(key="draft-real9")                                # 反過來:膜總裁那張單的鑰匙拿來跟這一家叫
        self.assertEqual(real.status_code, 201, real.content.decode())
        r = self.buy(key="draft-real9")
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "這把鑰匙是另一家廠商的叫貨單"))

    def test_what_is_ordered_comes_from_the_price_list_not_from_the_screen(self):
        r = self.buy(lines=[{"key": "C01", "packs": 3, "name": "亂寫", "pack_qty": 999, "unit_price": "1", "qty": 7}])
        item = r.json()["items"][0]
        self.assertEqual((item["name"], item["pack_qty"], item["qty"], item["unit_price"]), ("快充線", 10, 30, "45.00"))
        for n, bad in enumerate(([{"key": "X09", "packs": 1}], [{"key": "NOPE", "packs": 1}], [{"key": "G99", "packs": 1}],
                                 [{"key": "C01", "packs": 0}],
                                 [{"key": "C01", "packs": 1}, {"key": "C01", "packs": 2}], [], "x")):
            r = self.buy(lines=bad, key=f"draft-bad{n:03d}")
            self.assertEqual(r.status_code, 400, (bad, r.content.decode()))
        self.assertEqual(VendorOrder.objects.count(), 1)

    def test_who_may_order(self):
        self.turn_off("vendor_order")
        self.assertEqual(self.buy().status_code, 403)
        self.turn_off()
        self.assertEqual(self.open(clerk_ordering=False).status_code, 200)
        self.assertEqual(self.buy().status_code, 403)                        # 這家門市設成只限管理員叫
        self.assertEqual(self.buy(client=self.admin, key="draft-boss1").status_code, 201)
        self.assertEqual(self.buy(store=self.wh2, key="draft-other").status_code, 403)     # 鎖在門市的店員指別家
        self.assertEqual(self.open(clerk_ordering=True).status_code, 200)
        other = Company("b", "乙通訊行", "乙")
        r = other.admin.post(ORDERS, {"request_key": "draft-theirs", "warehouse": self.wh1.id, "vendor": "acme",
                                      "lines": [{"key": "C01", "packs": 1}]}, format="json")
        self.assertEqual(r.status_code, 400, r.content.decode())             # 別家公司:找不到這家門市
        self.assertEqual(VendorOrder.objects.count(), 1)

    def test_a_closed_store_or_a_stopped_vendor_cannot_order_but_the_old_key_still_answers(self):
        first = self.buy().json()
        self.assertEqual(self.open(opened=False).status_code, 200)
        r = self.buy(key="draft-m002")
        self.assertEqual((r.status_code, "還沒有開通" in r.json()["detail"]), (400, True))
        self.assertEqual((self.buy().status_code, self.buy().json()["id"]), (200, first["id"]))       # 先前那一張照樣回得了
        self.assertEqual(self.open().status_code, 200)
        Vendor.objects.filter(code="acme").update(is_active=False)
        r = self.buy(key="draft-m003")
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "「乙配件」已經停用,不能叫新的貨"))
        self.assertEqual(VendorOrder.objects.count(), 1)

    def test_no_shipping_details_no_delivery_order(self):
        VendorLink.objects.filter(provider="acme").update(ship_address="")
        r = self.buy()
        self.assertEqual((r.status_code, "宅配要有收件人" in r.json()["detail"]), (400, True))
        r = self.buy(delivery_method="自取", payment_method="貨到付款")
        self.assertEqual((r.status_code, r.json()["delivery_method"], r.json()["payment_method"]), (201, "自取", "貨到付款"))
        self.assertIn("取貨:自取", r.json()["message"])
        self.assertNotIn("收件", r.json()["message"])

    def test_whether_it_was_passed_on_is_recorded_by_hand(self):
        o = self.buy().json()
        url = f"{ORDERS}{o['id']}/sent/"
        r = self.clerk.post(url, {"sent": True}, format="json")
        self.assertEqual((r.status_code, r.json()["sent_how"], r.json()["sent_by"], bool(r.json()["sent_at"])), (200, "manual", "a-clerk", True))
        first = r.json()["sent_at"]
        r = self.admin.post(url, {"sent": True}, format="json")              # 已經標過:時間與人不換
        self.assertEqual((r.json()["sent_at"], r.json()["sent_by"]), (first, "a-clerk"))
        r = self.clerk.post(url, {"sent": False}, format="json")
        self.assertEqual((r.json()["sent_at"], r.json()["sent_how"], r.json()["sent_by"]), (None, "", ""))
        for bad in ({}, {"sent": "yes"}, {"sent": 1}):
            self.assertEqual(self.clerk.post(url, bad, format="json").status_code, 400, bad)
        self.turn_off("vendor_order")
        self.assertEqual(self.clerk.post(url, {"sent": True}, format="json").status_code, 403)     # 傳單是叫貨的人的事
        self.assertEqual(self.clerk.post(f"{ORDERS}999999/sent/", {"sent": True}, format="json").status_code, 403)
        self.turn_off()
        self.assertEqual(self.clerk.post(f"{ORDERS}999999/sent/", {"sent": True}, format="json").status_code, 404)
        self.assertNothingWentOut()

    def test_progress_is_a_line_someone_writes(self):
        o = self.buy().json()
        url = f"{ORDERS}{o['id']}/progress/"
        self.assertEqual(self.clerk.post(url, {"note": "  廠商說週三出  "}, format="json").json()["progress_note"], "廠商說週三出")
        self.turn_off("vendor_order")                                         # 收貨的人也可以記
        self.assertEqual(self.clerk.post(url, {"note": "到一半"}, format="json").json()["progress_note"], "到一半")
        self.turn_off("vendor_order", "purchase")
        self.assertEqual(self.clerk.post(url, {"note": "x"}, format="json").status_code, 403)
        self.turn_off()
        for bad in ({}, {"note": 5}, {"note": "字" * 201}):
            self.assertEqual(self.clerk.post(url, bad, format="json").status_code, 400, str(bad)[:20])
        self.assertEqual(self.clerk.post(url, {"note": ""}, format="json").json()["progress_note"], "")

    def test_cancelling_is_only_a_mark_here_and_can_be_undone(self):
        o = self.buy().json()
        url = f"{ORDERS}{o['id']}/cancel/"
        r = self.clerk.post(url, {"cancelled": True}, format="json")
        self.assertEqual((r.status_code, bool(r.json()["cancelled_at"]), r.json()["cancelled_by"], r.json()["state"]), (200, True, "a-clerk", "placed"))
        when = r.json()["cancelled_at"]
        self.assertEqual(self.admin.post(url, {"cancelled": True}, format="json").json()["cancelled_at"], when)
        self.assertEqual(self.clerk.get(f"{ORDERS}{o['id']}/receiving/").status_code, 200)            # 取消了,貨到了照樣入得了庫
        r = self.clerk.post(url, {"cancelled": False}, format="json")
        self.assertEqual((r.json()["cancelled_at"], r.json()["cancelled_by"]), (None, ""))
        self.assertEqual(self.clerk.post(url, {"cancelled": "是"}, format="json").status_code, 400)
        self.turn_off("vendor_order")
        self.assertEqual(self.clerk.post(url, {"cancelled": True}, format="json").status_code, 403)
        self.assertEqual(VendorOrder.objects.count(), 1)

    def test_orders_sent_to_a_real_system_have_none_of_these(self):
        self.link()
        real = self.order(key="draft-real1").json()
        self.assertEqual((real["manual"], real["message"]), (False, ""))
        for name, body in (("sent", {"sent": True}), ("progress", {"note": "x"}), ("cancel", {"cancelled": True})):
            r = self.clerk.post(f"{ORDERS}{real['id']}/{name}/", body, format="json")
            self.assertEqual((r.status_code, r.json()["detail"]), (400, "這張叫貨單是直接送到廠商系統的,不用人工標記"), name)

    def test_there_is_no_system_to_ask_so_these_do_nothing_outside(self):
        o = self.buy().json()
        r = self.clerk.post(SYNC, {"warehouse": self.wh1.id, "vendor": "acme"}, format="json")
        self.assertEqual((r.status_code, r.json()["others"], [x["id"] for x in r.json()["results"]]), (200, [], [o["id"]]))
        r = self.clerk.post(f"{ORDERS}{o['id']}/resend/")
        self.assertEqual((r.status_code, r.json()["id"], r.json()["state"]), (200, o["id"], "placed"))
        r = self.clerk.post(ADOPT, {"warehouse": self.wh1.id, "vendor": "acme", "order_no": "LINE-001"}, format="json")
        self.assertEqual((r.status_code, "沒有系統可以查單" in r.json()["detail"]), (400, True))
        self.assertEqual(VendorOrder.objects.count(), 1)
        self.assertNothingWentOut()

    def test_another_company_sees_none_of_it(self):
        o = self.buy().json()
        other = Company("b", "乙通訊行", "乙")
        self.assertEqual(other.admin.get(ORDERS).json()["results"], [])
        for name, body in (("sent", {"sent": True}), ("progress", {"note": "x"}), ("cancel", {"cancelled": True}),
                           ("receive", {"request_key": "recv-theirs1", "lines": []})):
            self.assertEqual(other.admin.post(f"{ORDERS}{o['id']}/{name}/", body, format="json").status_code, 404, name)
        self.assertEqual(other.admin.get(f"{ORDERS}{o['id']}/receiving/").status_code, 404)

    def test_linking_names_uses_the_price_list(self):
        r = self.clerk.get(MAPPINGS, {"vendor": "acme"})
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.assertEqual([(x["key"], x["name"], x["spec_label"], x["pack_qty"], x["product"]) for x in r.json()["rows"]],
                         [("C01", "快充線", "1M", 10, None), ("H01", "20W 充電頭", "", 5, None), ("C02", "快充線", "2M", 10, None)])
        self.assertNotIn("price", r.content.decode())
        r = self.clerk.post(MAPPINGS, {"vendor": "acme", "key": "C01", "product": self.cable.id}, format="json")
        self.assertEqual((r.status_code, r.json()["product"]["id"]), (200, self.cable.id), r.content.decode())
        saved = SupplierProduct.objects.get()
        self.assertEqual((saved.supplier.name, saved.platform, saved.vendor_sku, saved.source_name, saved.variant, saved.pack_qty),
                         ("乙配件", "acme", "C01", "快充線", "1M", 10))
        self.assertEqual(self.clerk.post(MAPPINGS, {"vendor": "acme", "key": "X09", "product": self.cable.id}, format="json").status_code, 400)
        self.assertEqual(self.open(opened=False).status_code, 200)
        self.assertEqual(self.clerk.get(MAPPINGS, {"vendor": "acme"}).status_code, 400)
        self.assertNothingWentOut()


# ── 到貨入庫:照店家叫的單、單價是入庫的人填的 ──────────────────────────────────
class ReceiveTests(_Manual):
    def setUp(self):
        super().setUp()
        self.assertEqual(self.open().status_code, 200)
        self.o = self.buy().json()              # 快充線 1M 兩包(20 條,參考價 45)、充電頭一包(5 個,沒有參考價)

    def plan(self, order=None, client=None):
        return (client or self.clerk).get(f"{ORDERS}{(order or self.o)['id']}/receiving/")

    def take(self, lines, key="recv-m001", order=None, client=None, **extra):
        body = {"request_key": key, "lines": lines, **extra}
        return (client or self.clerk).post(f"{ORDERS}{(order or self.o)['id']}/receive/", body, format="json")

    def line(self, key=C01, qty=20, product=None, price="45", **more):
        return {"key": key, "qty": qty, "product": (product or self.cable).id, "unit_price": price, **more}

    def test_the_page_lists_what_the_store_ordered_and_fills_in_nothing(self):
        r = self.plan()
        self.assertEqual(r.status_code, 200, r.content.decode())
        got = r.json()
        self.assertEqual((got["manual"], got["vendor_order_no"], got["payment_method"], got["shipping_fee"], got["freight_into_cost"],
                          got["supplier"], got["vendor_status"]), (True, self.o["vendor_order_no"], "月結", "0.00", True, None, ""))
        self.assertEqual([(x["key"], x["name"], x["spec_label"], x["qty"], x["received_qty"], x["remaining_qty"], x["suggested_qty"],
                           x["unit_price"], x["product"], x["is_reissue"]) for x in got["lines"]],
                         [(C01, "快充線", "1M", 20, 0, 20, 0, "45.00", None, False), (H01, "20W 充電頭", "", 5, 0, 5, 0, None, None, False)])
        # 這張單沒叫、價目表上有的:可以加(停賣的不列)
        self.assertEqual([(x["key"], x["unit_price"]) for x in got["extras"]], [(C02, "60.00")])
        self.assertNothingWentOut()

    def test_goods_go_in_at_the_price_the_receiver_types(self):
        r = self.take([self.line(price="42.5"), self.line(H01, 5, self.head, "118")])
        self.assertEqual(r.status_code, 201, r.content.decode())
        po = PurchaseOrder.objects.get(tenant=self.t)
        self.assertEqual((po.tax_method, po.total_cost, po.supplier.name, po.warehouse_id, po.payment_method, po.created_by.username),
                         ("untaxed", 1440, "乙配件", self.wh1.id, None, "a-clerk"))        # 42.5 × 20 + 118 × 5
        self.assertEqual(po.note, f"乙配件 {self.o['vendor_order_no']} 到貨入庫")
        self.assertEqual(sorted((i.product_id, i.qty, i.unit_price) for i in po.items.all()),
                         sorted([(self.cable.id, 20, D("42.50")), (self.head.id, 5, D("118.00"))]))
        self.assertEqual((self.stock(self.cable), self.stock(self.head)), ((20, D("42.50")), (5, D("118.00"))))
        receipt = VendorReceipt.objects.get()
        self.assertEqual(sorted((i.sku, i.qty, i.unit_price, i.product_id, i.is_reissue) for i in receipt.items.all()),
                         sorted([("C01", 20, D("42.50"), self.cable.id, False), ("H01", 5, D("118.00"), self.head.id, False)]))
        self.assertEqual(sorted(SupplierProduct.objects.values_list("vendor_sku", "product_id", "platform")),
                         sorted([("C01", self.cable.id, "acme"), ("H01", self.head.id, "acme")]))
        rows = {x["key"]: x for x in self.plan().json()["lines"]}
        self.assertEqual((rows[C01]["received_qty"], rows[C01]["remaining_qty"], rows[C01]["product"]["id"]), (20, 0, self.cable.id))
        self.assertEqual([x["qty"] for x in r.json()["order"]["receipts"]], [25])
        self.assertNothingWentOut()

    def test_every_line_needs_a_real_price(self):
        for bad in (None, "", "abc", -1, "1.234", 1.234, "10000000", 10000000, True, [], "1e2", "1,200", "+5"):
            r = self.take([{**self.line(), "unit_price": bad}])
            self.assertEqual((r.status_code, r.json()["detail"]), (400, "每一行都要填實際的單價(沒有收錢的填 0)"), repr(bad))
        r = self.take([{k: v for k, v in self.line().items() if k != "unit_price"}])
        self.assertEqual(r.status_code, 400)
        for odd in ("7", 0, -1, 1.5, True, []):                               # 畫面上「原本對到誰」亂寫的
            r = self.take([self.line(was=odd)])
            self.assertEqual((r.status_code, r.json()["detail"]), (400, "入庫的內容不完整(原本對到的品號不對)"), repr(odd))
        for bad in ([], "x", [self.line(qty=0)], [self.line(qty=100000)], [{**self.line(), "product": None}], [self.line(), self.line()]):
            self.assertEqual(self.take(bad).status_code, 400, str(bad)[:50])
        self.assertEqual((PurchaseOrder.objects.filter(tenant=self.t).count(), VendorReceipt.objects.count()), (0, 0))

    def test_no_charge_goods_go_in_without_a_cost(self):
        r = self.take([self.line(qty=20, price="45"), self.line(H01, 5, self.head, 0)])
        self.assertEqual(r.status_code, 201, r.content.decode())
        got = {i.product_id: (i.qty, i.billed_qty, i.unit_price) for i in PurchaseOrder.objects.get(tenant=self.t).items.all()}
        self.assertEqual(got, {self.cable.id: (20, 20, D("45.00")), self.head.id: (5, 0, D("0.00"))})
        self.assertEqual(self.stock(self.head)[0], 5)

    def test_freight_follows_the_stores_rule(self):
        r = self.take([self.line(price="45"), self.line(H01, 5, self.head, "100")], freight=140)       # 貨款 900 + 500
        self.assertEqual(r.status_code, 201, r.content.decode())
        po = PurchaseOrder.objects.get(tenant=self.t)
        self.assertEqual((po.total_cost, VendorReceipt.objects.get().freight, po.note), (1540, D("140.00"), f"乙配件 {self.o['vendor_order_no']} 到貨入庫"))
        self.assertEqual({i.product_id: i.unit_price for i in po.items.all()}, {self.cable.id: D("49.50"), self.head.id: D("110.00")})   # 90 / 50
        # 門市設成運費不算成本:單價不動,進貨單備註寫一筆
        VendorLink.objects.filter(provider="acme").update(freight_into_cost=False)
        other = self.buy(key="draft-m002").json()
        r = self.take([self.line(price="45")], key="recv-m002", order=other, freight="80")
        self.assertEqual(r.status_code, 400)                                  # 運費要是整數(數字)
        r = self.take([self.line(price="45")], key="recv-m002", order=other, freight=80)
        self.assertEqual(r.status_code, 201, r.content.decode())
        po = PurchaseOrder.objects.filter(tenant=self.t).order_by("id").last()
        self.assertEqual((po.total_cost, po.items.get().unit_price, VendorReceipt.objects.order_by("id").last().freight),
                         (900, D("45.00"), D("0.00")))
        self.assertIn("(運費 80 沒有算進成本)", po.note)
        for bad in (-1, 1.5, True, 10_000_000, "x"):
            self.assertEqual(self.take([self.line(price="45")], key="recv-m003", order=other, freight=bad).status_code, 400, repr(bad))

    def test_more_than_was_ordered_is_allowed(self):
        """廠商常常多送、併單;沒有它的系統可以對 —— 只提醒(畫面),不擋。"""
        r = self.take([self.line(qty=24)])
        self.assertEqual(r.status_code, 201, r.content.decode())
        row = self.plan().json()["lines"][0]
        self.assertEqual((row["qty"], row["received_qty"], row["remaining_qty"]), (20, 24, -4))
        self.assertEqual(self.take([self.line(qty=6)], key="recv-m002").status_code, 201)       # 入完了還可以再入
        self.assertEqual(self.stock(self.cable)[0], 30)

    def test_something_not_on_the_order_can_come_in_if_the_vendor_sells_it(self):
        longer = self.product("甲 快充線 2M")
        r = self.take([self.line(qty=10), self.line(C02, 10, longer, "58")])       # 1M 少到一包,多了一包 2M
        self.assertEqual(r.status_code, 201, r.content.decode())
        self.assertEqual((self.stock(self.cable)[0], self.stock(longer)), (10, (10, D("58.00"))))
        got = self.plan().json()
        self.assertEqual([(x["key"], x["qty"], x["received_qty"], x["product"] and x["product"]["id"]) for x in got["lines"]],
                         [(C01, 20, 10, self.cable.id), (H01, 5, 0, None), (C02, 0, 10, longer.id)])          # 入過的列在單上(叫 0)
        self.assertEqual(got["extras"], [])
        self.assertEqual(self.take([self.line(C02, 5, longer, "58")], key="recv-m002").status_code, 201)    # 入過的那一項可以再入
        # 價目表上沒有的、停賣又沒入過的:不行
        for key in ("NOPE||p", X09, "C01", "C01|1|p", "C01||r", "G99||p"):            # 最後一個是別家廠商價目表上的
            r = self.take([self.line(key, 1)], key="recv-m003")
            self.assertEqual((r.status_code, "價目表上現在也沒有" in r.json()["detail"]), (400, True), key)
        # 入過之後才停賣:還是可以入(那一批貨可能分兩次到)
        VendorItem.objects.filter(sku="C02").update(is_active=False)
        self.assertEqual(self.take([self.line(C02, 1, longer, "58")], key="recv-m004").status_code, 201)

    def test_the_same_delivery_is_never_taken_in_twice(self):
        first = self.take([self.line()])
        again = self.take([self.line(qty=3, price="1")])
        self.assertEqual((first.status_code, again.status_code, again.json()["receipt"]), (201, 200, first.json()["receipt"]))
        self.assertEqual((PurchaseOrder.objects.filter(tenant=self.t).count(), self.stock(self.cable)[0]), (1, 20))
        other = self.buy(key="draft-m002").json()
        r = self.take([self.line()], order=other)
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "這把鑰匙是另一張叫貨單的入庫"))
        self.assertEqual(self.take([self.line()], key="x").status_code, 400)

    def test_only_countable_goods_and_the_stale_screen_rule_still_hold(self):
        r = self.take([self.line(product=self.c.phone)])
        self.assertEqual((r.status_code, "只能入到按數量管的一般商品" in r.json()["detail"]), (400, True))
        self.assertEqual(self.take([self.line(qty=5)]).status_code, 201)                       # 第一次:記住對到 cable
        other = self.product("甲 別的線")
        r = self.take([self.line(qty=5, product=other)], key="recv-m002")                      # 舊畫面以為還沒對過
        self.assertEqual((r.status_code, "對照剛被改過" in r.json()["detail"]), (400, True), r.content.decode())
        self.assertEqual(self.take([self.line(qty=5, product=other, was=self.cable.id)], key="recv-m002").status_code, 201)
        self.assertEqual((self.stock(self.cable)[0], self.stock(other)[0]), (5, 5))

    def test_cash_on_delivery_is_paid_in_cash_and_a_voided_slip_gives_the_pieces_back(self):
        cod = self.buy(key="draft-m002", payment_method="貨到付款").json()
        r = self.take([self.line()], order=cod)
        self.assertEqual(r.status_code, 201, r.content.decode())
        po = PurchaseOrder.objects.get(tenant=self.t)
        self.assertEqual(po.payment_method, self.c.cash)
        self.assertEqual(self.admin.post(f"/api/v1/purchase-orders/{po.id}/void/").status_code, 200)
        row = self.plan(cod).json()["lines"][0]
        self.assertEqual((row["received_qty"], row["remaining_qty"], self.stock(self.cable)[0]), (0, 20, 0))
        self.assertEqual([x["is_void"] for x in self.clerk.get(f"{ORDERS}{cod['id']}/").json()["receipts"]], [True])

    def test_who_may_receive(self):
        self.turn_off("purchase")
        self.assertEqual((self.plan().status_code, self.take([self.line()]).status_code), (403, 403))
        self.turn_off("vendor_order")                                         # 只收貨的人可以
        self.assertEqual((self.plan().status_code, self.take([self.line()]).status_code), (200, 201))
        self.assertEqual(self.open(store=self.wh2).status_code, 200)
        theirs = self.buy(client=self.admin, store=self.wh2, key="draft-wh2a").json()
        self.assertEqual((self.plan(theirs).status_code, self.take([self.line()], key="recv-m009", order=theirs).status_code), (404, 404))
        self.assertNothingWentOut()

    def test_the_other_kind_of_order_is_untouched(self):
        """全自動(膜總裁)那一條路照舊:單價用廠商的、畫面送什麼都不看。"""
        self.link()
        real = self.order(key="draft-real1").json()
        film = self.product("甲 高透亮面保護貼")
        r = self.clerk.post(f"{ORDERS}{real['id']}/receive/", {"request_key": "recv-real1", "freight": 999, "lines": [
            {"key": "G02||p", "qty": 50, "product": film.id, "unit_price": "1"}]}, format="json")
        self.assertEqual(r.status_code, 201, r.content.decode())
        self.assertEqual(self.stock(film), (50, D("150.00")))
