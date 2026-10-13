"""只給指定公司的廠商、kcimos 的價目匯入。跑法:manage.py test apps.vendor_orders.test_kcimos

owner 2026-10-13:「再來我想做串接kcimos，帳號有三個，做手機玩家的串接就好」「未稅是我的實際成本」「Kcimos只有手機玩家看得到沒錯」

要守住的:
- 平台上的公司是互相競爭的經銷商。**只給指定公司的廠商,名單以外的公司看不到它、看不到它的價目、不能開通 / 連品名 / 叫貨**,
  而且講的話跟「代碼打錯」一模一樣(不透露有這一家)。開關開著、名單空的 = 沒有人看得到。
- 以前設定過、後來被收回的公司:已經叫的單照樣查得到、入得了庫;新的不能叫、價目不能看。
- kcimos 的快照匯成價目表:一建就是只給指定的公司;可以重跑、不重複;停產的停用;沒報價的不帶參考價;參考價 = 網站的未稅價。
- 匯入不連 kcimos、不動庫存、不成立任何單。
"""
import io
import json
import os
import tempfile
import threading
import time
from decimal import Decimal as D

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connections
from django.test import TransactionTestCase

from apps.backup.tests.factory import Company
from apps.catalog.models import Product
from apps.inventory.models import StockBalance
from apps.tenants.models import UserProfile

from . import kcimos, vendors
from .models import Vendor, VendorItem, VendorLink, VendorOrder
from .tests import CATALOG, LINKS, ORDERS, SYNC, _Shop

P_VENDORS = "/api/v1/platform/vendors/"
MAPPINGS = "/api/v1/vendor-orders/mappings/"
NOT_LISTED = "廠商名單上沒有「kc」這一家,請平台管理員處理"


def snapshot(products=None, schema=kcimos.SCHEMA):
    products = products if products is not None else [
        product("2685", "(3D黑邊)imos 低藍光玻璃貼 iPhone 18 Pro", 547, category="imos iPhone 18 系列專區", subcategory="低藍光"),
        product("2636", "藍寶石鏡頭貼for SAMSUNG Galaxy Z Fold 7(黑框)$750", 333, category="iMOS鏡頭貼 (非蘋果)", subcategory="藍鏡"),
        product("2736", "OEM (2.5D防窺) 強化玻璃保貼 18 Pro Max (預購中)", 9999999, flags=["名稱標示預購"], availability="缺貨中請先預購"),
        product("1500", "舊款保護貼(停產請勿下單)", 200, flags=[kcimos.STOPPED]),
        product("1800", "保固卡", 0, flags=["零採購價待確認"]),
        product("1900", "沒報價的殼", 9999, flags=["9999價格待確認"]),
    ]
    return {"metadata": {"schema": schema, "captured_date": "2026-10-11"}, "products": products}


def product(pk, name, price, *, category="分類", subcategory="子分類", flags=(), availability="供應中"):
    return {"supplier_product_id": pk, "name": name, "purchase_price": price, "retail_price": price * 2,
            "category": category, "subcategory": subcategory, "flags": list(flags), "availability": availability}


class _TwoCompanies(_Shop):
    """甲通訊行(名單上)與乙通訊行(名單以外);一家只給甲的半自動廠商「kc」,價目兩項。"""

    def setUp(self):
        super().setUp()
        self.other = Company("b", "乙通訊行", "乙")
        self.kc = Vendor.objects.create(code="kc", name="只給甲的批發", protocol=Vendor.Protocol.MANUAL,
                                        is_private=True, only_for="a", sort_order=9)
        self.item = VendorItem.objects.create(vendor=self.kc, sku="K1", name="低藍光玻璃貼", unit="片", ref_price=547)
        VendorItem.objects.create(vendor=self.kc, sku="K2", name="鏡頭貼", unit="片", ref_price=333)
        self.film = Product.objects.create(tenant=self.t, category=self.c.cat_case, name="甲 低藍光貼",
                                           requires_serial=False, list_price=1390)
        self.vendor.calls.clear()

    def open(self, company=None, **extra):
        c = company or self.c
        body = {"warehouse": c.wh.id, "vendor": "kc", "opened": True, "ship_name": "收件人",
                "ship_phone": "035551234", "ship_address": "新竹市湳雅街 1 號", **extra}
        return c.admin.post(LINKS, body, format="json")

    def buy(self, company=None, key="draft-k001", **extra):
        c = company or self.c
        body = {"request_key": key, "warehouse": c.wh.id, "vendor": "kc", "lines": [{"key": "K1", "packs": 2}], **extra}
        return c.admin.post(ORDERS, body, format="json")

    def listed(self, company):
        return {row["provider"] for row in company.admin.get(LINKS).json()["results"]}


class OpenToTests(_TwoCompanies):
    def test_who_a_vendor_is_open_to(self):
        everyone = Vendor(code="x", name="x")
        self.assertTrue(vendors.open_to(everyone, self.other.tenant))
        self.assertTrue(vendors.open_to(everyone, None))
        self.assertEqual((vendors.open_to(self.kc, self.t), vendors.open_to(self.kc, self.other.tenant)), (True, False))
        self.assertFalse(vendors.open_to(self.kc, None))
        # 開關開著、名單空的 = 沒有任何公司(不會因為名單一時是空的就變成全部)
        nobody = Vendor(code="y", name="y", is_private=True, only_for="")
        self.assertEqual((vendors.open_to(nobody, self.t), vendors.open_to(nobody, self.other.tenant)), (False, False))
        # 名單只有開關開著才有作用;代碼前後的空白、重複的不影響;要整個代碼一樣(不是開頭像就算)
        self.assertTrue(vendors.open_to(Vendor(code="z", name="z", is_private=False, only_for="b"), self.t))
        self.assertEqual(vendors.company_codes(Vendor(only_for=" a , b,,a ")), ["a", "b"])
        Company("ab", "甲乙通訊行", "甲乙")
        self.assertFalse(vendors.open_to(self.kc, Company("a2", "甲二通訊行", "甲二").tenant))


class OutsiderTests(_TwoCompanies):
    """名單以外的公司(乙):這家廠商對它來說不存在。"""

    def test_it_is_not_on_the_list_and_cannot_be_opened(self):
        self.assertEqual((self.listed(self.c) >= {"kc"}, "kc" in self.listed(self.other)), (True, False))
        r = self.open(self.other)
        self.assertEqual((r.status_code, r.json()["detail"]), (400, NOT_LISTED))
        self.assertFalse(VendorLink.objects.filter(tenant=self.other.tenant).exists())

    def test_prices_names_mapping_ordering_and_progress_all_say_no_such_vendor(self):
        store = self.other.wh.id
        calls = [
            self.other.admin.get(CATALOG, {"warehouse": store, "vendor": "kc"}),
            self.other.admin.get(MAPPINGS, {"warehouse": store, "vendor": "kc"}),
            self.other.admin.post(MAPPINGS, {"warehouse": store, "vendor": "kc", "key": "K1||", "product": None}, format="json"),
            self.buy(self.other),
            self.other.admin.get(ORDERS, {"warehouse": store, "vendor": "kc"}),
            self.other.admin.post(SYNC, {"warehouse": store, "vendor": "kc"}, format="json"),
        ]
        for r in calls:
            self.assertEqual((r.status_code, r.json()["detail"]), (400, NOT_LISTED), r.content.decode())
            self.assertNotIn("只給甲的批發", r.content.decode())       # 連名字都不講
            self.assertNotIn("547", r.content.decode())
        # 跟真的打錯代碼講的一樣
        wrong = self.other.admin.get(CATALOG, {"warehouse": store, "vendor": "nope"})
        self.assertEqual(wrong.json()["detail"], NOT_LISTED.replace("kc", "nope"))
        self.assertFalse(VendorOrder.objects.exists())

    def test_the_only_vendor_shortcut_does_not_fall_onto_a_hidden_vendor(self):
        """沒講廠商時「名單上只有一家就是它」:算的是這家公司看得到的。乙只看得到膜總裁那一家,不會被帶到 kc。"""
        r = self.other.admin.get(CATALOG, {"warehouse": self.other.wh.id})
        self.assertNotIn("K1", r.content.decode())
        self.assertNotIn("低藍光玻璃貼", r.content.decode())
        Vendor.objects.filter(code="moceo").update(is_active=False)        # 甲:看得到的只剩 kc
        self.open()
        got = self.c.admin.get(CATALOG, {"warehouse": self.c.wh.id})
        self.assertEqual(got.status_code, 200, got.content.decode())
        self.assertIn("低藍光玻璃貼", got.content.decode())
        again = self.other.admin.get(CATALOG, {"warehouse": self.other.wh.id})   # 乙:一家都沒有
        self.assertEqual((again.status_code, again.json()["detail"]), (400, "要指定廠商"))

    def test_an_empty_list_hides_it_from_everyone(self):
        Vendor.objects.filter(pk=self.kc.pk).update(only_for="")
        self.assertNotIn("kc", self.listed(self.c))
        self.assertEqual(self.open().json()["detail"], NOT_LISTED)


class InsiderTests(_TwoCompanies):
    """名單上的公司(甲):跟一般的半自動廠商一樣用。"""

    def test_it_opens_sees_prices_maps_and_orders(self):
        self.assertEqual(self.open().status_code, 200)
        rows = self.c.admin.get(CATALOG, {"warehouse": self.c.wh.id, "vendor": "kc"}).json()["rows"]
        self.assertEqual({(r["sku"], r["unit_price"]) for r in rows}, {("K1", "547.00"), ("K2", "333.00")})
        key = next(r["key"] for r in rows if r["sku"] == "K1")
        m = self.c.admin.post(MAPPINGS, {"warehouse": self.c.wh.id, "vendor": "kc", "key": key, "product": self.film.id}, format="json")
        self.assertEqual(m.status_code, 200, m.content.decode())
        r = self.c.admin.post(ORDERS, {"request_key": "draft-k001", "warehouse": self.c.wh.id, "vendor": "kc",
                                       "lines": [{"key": key, "packs": 2, "was": self.film.id}]}, format="json")
        self.assertEqual(r.status_code, 201, r.content.decode())
        self.assertEqual(self.vendor.calls, [])                             # 半自動:不打任何外部系統

    def test_taken_back_later_keeps_old_orders_but_nothing_new(self):
        """甲開通、叫過貨之後,平台把這家廠商改成只給別人:已經叫的單照樣查得到、對照與進度照樣看得到;價目不能看、不能再叫、不能重新開通。"""
        self.open()
        first = self.buy()
        self.assertEqual(first.status_code, 201, first.content.decode())
        Vendor.objects.filter(pk=self.kc.pk).update(only_for="b")
        store = self.c.wh.id
        self.assertIn("kc", self.listed(self.c))                             # 設定過的留在清單上(紀錄還要看)
        self.assertEqual(self.c.admin.get(ORDERS, {"warehouse": store, "vendor": "kc"}).status_code, 200)
        self.assertEqual(self.c.admin.get(f"{ORDERS}{first.json()['id']}/").status_code, 200)
        self.assertEqual(self.c.admin.post(SYNC, {"warehouse": store, "vendor": "kc"}, format="json").status_code, 200)
        self.assertEqual(self.c.admin.get(CATALOG, {"warehouse": store, "vendor": "kc"}).json()["detail"], NOT_LISTED)
        again = self.buy(key="draft-k002")
        self.assertEqual((again.status_code, again.json()["detail"]), (400, "「只給甲的批發」沒有開放給這家公司,不能叫新的貨"))
        same = self.buy()                                                    # 同一把鑰匙回頭確認先前那一張:照樣回得了
        self.assertEqual((same.status_code, same.json()["id"]), (200, first.json()["id"]))
        self.assertEqual(VendorOrder.objects.filter(tenant=self.t).count(), 1)
        VendorLink.objects.filter(tenant=self.t, provider="kc").update(opened=False)
        reopen = self.open()
        self.assertEqual((reopen.status_code, reopen.json()["detail"]), (400, "「只給甲的批發」沒有開放給這家公司,不能新開通或換金鑰"))
        # 現在名單上的乙:可以開通
        self.assertEqual(self.open(self.other).status_code, 200)


    def test_taken_back_later_the_receiving_page_shows_only_what_that_order_had(self):
        """複審 2026-10-13 第 1 條:被收回之後,舊單的入庫面板與對照那一頁不能再列出廠商**現在**的品項與參考價
        (之後才加的新品、調過的價 —— 那已經是別家公司的進價)。叫過的那一行照樣入得了庫。"""
        self.open()
        first = self.buy().json()
        url = f"{ORDERS}{first['id']}/receiving/"
        before = self.c.admin.get(url).json()
        self.assertEqual([(x["sku"], x["unit_price"]) for x in before["extras"]], [("K2", "333.00")])   # 還看得到時:可以加沒叫的品項
        Vendor.objects.filter(pk=self.kc.pk).update(only_for="b")
        VendorItem.objects.create(vendor=self.kc, sku="K3", name="之後才有的新品", unit="片", ref_price=560)
        VendorItem.objects.filter(pk=self.item.pk).update(ref_price=600)
        r = self.c.admin.get(url)
        self.assertEqual(r.status_code, 200, r.content.decode())
        got = r.json()
        self.assertEqual(got["extras"], [])
        self.assertEqual([(x["sku"], x["unit_price"]) for x in got["lines"]], [("K1", "547.00")])      # 這張單當時的價,不是現在的 600
        for secret in ("之後才有的新品", "560", "600", "鏡頭貼", "333"):
            self.assertNotIn(secret, r.content.decode(), secret)
        m = self.c.admin.get(MAPPINGS, {"warehouse": self.c.wh.id, "vendor": "kc"})
        self.assertEqual((m.status_code, m.json()["detail"]), (400, NOT_LISTED))
        self.assertNotIn("之後才有的新品", m.content.decode())
        # 入庫:硬加一項這張單沒叫的(價目表上現在有的)不行;只入叫過的那一行可以
        take = lambda key, lines: self.c.admin.post(f"{ORDERS}{first['id']}/receive/", {"request_key": key, "freight": 0, "lines": lines}, format="json")
        k1 = {"key": got["lines"][0]["key"], "qty": 2, "product": self.film.id, "unit_price": "547"}
        sneaky = take("recv-k001", [k1, {"key": before["extras"][0]["key"], "qty": 1, "product": self.film.id, "unit_price": "333"}])
        self.assertEqual(sneaky.status_code, 400, sneaky.content.decode())
        self.assertIn("不在這張叫貨單上", sneaky.json()["detail"])
        done = take("recv-k002", [k1])
        self.assertIn(done.status_code, (200, 201), done.content.decode())

    def test_taken_back_later_an_extra_received_before_keeps_its_old_name_and_can_be_redone(self):
        """複審 2026-10-13 第二輪:這張單沒叫、但當時加收入庫過的品項 —— 被收回之後照**當時入庫記下來的**料號與品名列,
        不讀廠商現在的價目表(改過的名字、規格、一包幾個、價錢都不能帶出來);那張進貨單作廢之後,要能照原單重入。"""
        self.open()
        first = self.buy().json()
        url = f"{ORDERS}{first['id']}/receiving/"
        before = self.c.admin.get(url).json()
        k1 = {"key": before["lines"][0]["key"], "qty": 2, "product": self.film.id, "unit_price": "547"}
        k2 = {"key": before["extras"][0]["key"], "qty": 3, "product": self.film.id, "unit_price": "333"}
        take = lambda key, lines: self.c.admin.post(f"{ORDERS}{first['id']}/receive/", {"request_key": key, "freight": 0, "lines": lines}, format="json")
        got = take("recv-k001", [k1, k2])                                   # 還看得到時:加收一項沒叫的
        self.assertIn(got.status_code, (200, 201), got.content.decode())
        Vendor.objects.filter(pk=self.kc.pk).update(only_for="b")
        VendorItem.objects.filter(vendor=self.kc, sku="K2").update(name="改名後的鏡頭貼", spec="新規格", pack_qty=10, ref_price=400)
        r = self.c.admin.get(url)
        self.assertEqual(r.status_code, 200, r.content.decode())
        lines = {x["sku"]: x for x in r.json()["lines"]}
        self.assertEqual((lines["K2"]["name"], lines["K2"]["spec_label"], lines["K2"]["pack_qty"], lines["K2"]["unit_price"], lines["K2"]["received_qty"]),
                         ("鏡頭貼", "", 1, None, 3))
        for secret in ("改名後的鏡頭貼", "新規格", "400"):
            self.assertNotIn(secret, r.content.decode(), secret)
        self.assertEqual(r.json()["extras"], [])
        # 打錯了、把那張進貨單作廢:K2 回到「已入 0」,還在面板上、照原單重入得了,記下來的品名還是當時的
        po = self.c.admin.get(f"{ORDERS}{first['id']}/").json()["receipts"][0]["purchase_order"]
        self.assertEqual(self.c.admin.post(f"/api/v1/purchase-orders/{po}/void/").status_code, 200)
        again = self.c.admin.get(url).json()
        self.assertEqual([(x["sku"], x["name"], x["received_qty"]) for x in again["lines"]], [("K1", "低藍光玻璃貼", 0), ("K2", "鏡頭貼", 0)])
        redo = take("recv-k002", [k1, k2])
        self.assertIn(redo.status_code, (200, 201), redo.content.decode())
        from .models import VendorReceiptItem
        self.assertEqual(sorted(VendorReceiptItem.objects.filter(receipt__request_key="recv-k002").values_list("sku", "name", "qty")),
                         [("K1", "低藍光玻璃貼", 2), ("K2", "鏡頭貼", 3)])
        self.assertNotIn("改名後的鏡頭貼", self.c.admin.get(f"{ORDERS}{first['id']}/").content.decode())
        # 從來沒入過的品項還是不能加
        k3 = VendorItem.objects.create(vendor=self.kc, sku="K3", name="之後才有的新品", unit="片", ref_price=560)
        no = take("recv-k003", [{"key": f"{k3.sku}||p", "qty": 1, "product": self.film.id, "unit_price": "560"}])
        self.assertEqual(no.status_code, 400, no.content.decode())

    def test_a_stopped_private_vendor_still_does_not_give_its_name_away(self):
        """複審 2026-10-13 第 3 條:先看這家公司看不看得到、才看廠商有沒有停用 —— 反過來的話「『某某』已經停用」會把名字講給名單以外的公司。"""
        Vendor.objects.filter(pk=self.kc.pk).update(is_active=False)
        for only_for in ("a", ""):
            Vendor.objects.filter(pk=self.kc.pk).update(only_for=only_for)
            r = self.other.admin.get(CATALOG, {"warehouse": self.other.wh.id, "vendor": "kc"})
            self.assertEqual((r.status_code, r.json()["detail"]), (400, NOT_LISTED), only_for)
            self.assertNotIn("只給甲的批發", r.content.decode())
        Vendor.objects.filter(pk=self.kc.pk).update(only_for="a")
        mine = self.c.admin.get(CATALOG, {"warehouse": self.c.wh.id, "vendor": "kc"})        # 名單上的公司:照樣講停用
        self.assertEqual(mine.json()["detail"], "「只給甲的批發」已經停用,不能叫新的貨")


class PlatformTests(_TwoCompanies):
    def setUp(self):
        super().setUp()
        root = get_user_model().objects.create_user(username="platform-root", password="pw-12345")
        UserProfile.objects.create(user=root, role="platform_admin", tenant=None, is_warehouse_locked=False)
        self.root = Company.client(root)

    def patch(self, body, expect=200):
        r = self.root.patch(f"{P_VENDORS}{self.kc.id}/", body, format="json")
        self.assertEqual(r.status_code, expect, r.content.decode())
        return r.json()

    def test_the_platform_sees_and_sets_who_it_is_for(self):
        row = next(v for v in self.root.get(P_VENDORS).json()["results"] if v["code"] == "kc")
        self.assertEqual((row["is_private"], row["only_for"]), (True, ["a"]))
        got = self.patch({"only_for": ["a", " b ", "a"]})
        self.assertEqual(got["only_for"], ["a", "b"])
        self.assertIn("kc", self.listed(self.other))
        self.assertEqual(self.patch({"is_private": False})["is_private"], False)
        self.assertEqual(Vendor.objects.get(pk=self.kc.pk).only_for, "a,b")       # 關掉開關不清名單(再開回來還在)

    def test_a_company_code_that_does_not_exist_is_refused(self):
        self.assertEqual(self.patch({"only_for": ["a", "zz"]}, 400)["detail"], "沒有這家公司:zz")
        for odd in ("a", [1], None, [["a"]]):
            self.assertEqual(self.patch({"only_for": odd}, 400)["detail"], "給哪幾家公司要是公司代碼的清單", odd)
        self.assertEqual(self.patch({"is_private": "yes"}, 400)["detail"], "只給指定的公司只能是開或關")
        self.assertEqual(Vendor.objects.get(pk=self.kc.pk).only_for, "a")

    def test_a_new_vendor_can_start_private_and_shops_cannot_change_it(self):
        made = self.root.post(P_VENDORS, {"code": "solo", "name": "新的批發", "protocol": "manual",
                                          "is_private": True, "only_for": ["b"]}, format="json")
        self.assertEqual(made.status_code, 201, made.content.decode())
        self.assertEqual((made.json()["is_private"], made.json()["only_for"]), (True, ["b"]))
        self.assertEqual(("solo" in self.listed(self.c), "solo" in self.listed(self.other)), (False, True))
        self.assertEqual(self.c.admin.patch(f"{P_VENDORS}{self.kc.id}/", {"is_private": False}, format="json").status_code, 403)
        self.assertEqual(self.c.admin.get(P_VENDORS).status_code, 403)


class ImportTests(_Shop):
    def test_rules_for_one_row(self):
        self.assertEqual([kcimos.ref_price(v) for v in (547, 9998, 9999, 9999999, 0, -1, None, "547", True, 1.5)],
                         [D(547), D(9998), None, None, None, None, None, None, None, None])
        rows = {r["sku"]: r["values"] for r in kcimos.rows(snapshot())}
        self.assertEqual(list(rows), ["KCIMOS-2685", "KCIMOS-2636", "KCIMOS-2736", "KCIMOS-1500", "KCIMOS-1800", "KCIMOS-1900"])
        self.assertEqual(rows["KCIMOS-2685"], {
            "name": "(3D黑邊)imos 低藍光玻璃貼 iPhone 18 Pro", "kind": "imos iPhone 18 系列專區", "spec": "低藍光",
            "unit": "", "pack_qty": 1, "ref_price": D(547), "is_active": True, "sort_order": 1})        # 參考價 = 網站的未稅價,不乘 1.05
        self.assertEqual([(rows[k]["ref_price"], rows[k]["is_active"]) for k in ("KCIMOS-2736", "KCIMOS-1500", "KCIMOS-1800", "KCIMOS-1900")],
                         [(None, True), (D(200), False), (None, True), (None, True)])                     # 沒報價的不帶價;停產的停用

    def test_a_bad_snapshot_is_refused_whole(self):
        for bad, why in ((snapshot(schema="other/1"), "這不是 kcimos 的商品快照"), ({"products": []}, "這不是 kcimos 的商品快照"),
                         (snapshot([]), "快照裡沒有商品"), (snapshot([product("26a", "x", 1)]), "商品編號不對"),
                         (snapshot([product("1", "x", 1), product("1", "y", 2)]), "商品編號 1 重複"),
                         (snapshot([product("1", "  ", 1)]), "沒有品名")):
            with self.assertRaisesMessage(kcimos.SnapshotError, why):
                kcimos.plan(bad, ["a"])
        for codes, why in (([], "要講這份價目是給哪一家公司的"), ([" "], "要講這份價目是給哪一家公司的"), (["a", "zz"], "沒有這家公司:zz")):
            with self.assertRaisesMessage(kcimos.SnapshotError, why):
                kcimos.plan(snapshot(), codes)
        self.assertFalse(Vendor.objects.filter(code="kcimos").exists())

    def test_preview_writes_nothing_and_apply_creates_the_vendor_already_private(self):
        todo = kcimos.plan(snapshot(), ["a"])
        self.assertEqual((len(todo["new"]), len(todo["changed"]), todo["same"], todo["stopped"], todo["unpriced"], todo["vendor_exists"]),
                         (6, 0, 0, 1, 3, False))
        self.assertFalse(Vendor.objects.filter(code="kcimos").exists())
        kcimos.apply(snapshot(), ["a"])
        vendor = Vendor.objects.get(code="kcimos")
        self.assertEqual((vendor.protocol, vendor.is_private, vendor.only_for, vendor.is_active), ("manual", True, "a", True))
        self.assertEqual(VendorItem.objects.filter(vendor=vendor).count(), 6)
        item = VendorItem.objects.get(vendor=vendor, sku="KCIMOS-2685")
        self.assertEqual((item.name, item.ref_price, item.kind, item.spec, item.pack_qty), (
            "(3D黑邊)imos 低藍光玻璃貼 iPhone 18 Pro", D("547.00"), "imos iPhone 18 系列專區", "低藍光", 1))
        # 別家公司從第一刻起就看不到
        other = Company("b", "乙通訊行", "乙")
        self.assertNotIn("kcimos", {row["provider"] for row in other.admin.get(LINKS).json()["results"]})
        self.assertIn("kcimos", {row["provider"] for row in self.admin.get(LINKS).json()["results"]})
        # 匯入不動庫存、不成立單、不打外部系統
        self.assertEqual((VendorOrder.objects.count(), StockBalance.objects.filter(tenant=self.t).count(), self.vendor.calls), (0, 0, []))

    def test_running_again_changes_only_what_changed_and_never_deletes(self):
        kcimos.apply(snapshot(), ["a"])
        self.assertEqual((lambda t: (len(t["new"]), len(t["changed"]), t["same"]))(kcimos.apply(snapshot(), ["a"])), (0, 0, 6))
        ids = dict(VendorItem.objects.values_list("sku", "id"))
        later = snapshot([
            product("2685", "(3D黑邊)imos 低藍光玻璃貼 iPhone 18 Pro", 560, category="imos iPhone 18 系列專區", subcategory="低藍光"),   # 漲價
            product("1500", "舊款保護貼(停產請勿下單)", 200),                                                                          # 又可以叫了
            product("3000", "新的品項", 100),
        ])
        todo = kcimos.apply(later, ["a"])
        self.assertEqual(([r["sku"] for r in todo["new"]], sorted(r["sku"] for r in todo["changed"]), todo["left_alone"]),
                         (["KCIMOS-3000"], ["KCIMOS-1500", "KCIMOS-2685"], 4))
        self.assertEqual(VendorItem.objects.count(), 7)                                # 快照裡不見的四項還在(不刪)
        self.assertEqual({sku: VendorItem.objects.get(sku=sku).id for sku in ids}, ids)   # 原本的沒有被換掉(對照與叫貨單靠它認)
        self.assertEqual((VendorItem.objects.get(sku="KCIMOS-2685").ref_price, VendorItem.objects.get(sku="KCIMOS-1500").is_active), (D("560.00"), True))
        self.assertEqual(VendorItem.objects.get(sku="KCIMOS-2636").ref_price, D("333.00"))

    def test_it_will_not_import_into_a_public_vendor_or_for_another_company(self):
        """這份是特定帳號的進價:名單上的 kcimos 不是「只給指定的公司」、或給的不是這一次講的那一家,就不匯。"""
        Company("b", "乙通訊行", "乙")
        public = Vendor.objects.create(code="kcimos", name="kcimos", protocol=Vendor.Protocol.MANUAL)
        with self.assertRaisesMessage(kcimos.SnapshotError, "現在是每一家公司都看得到"):
            kcimos.apply(snapshot(), ["a"])
        Vendor.objects.filter(pk=public.pk).update(is_private=True, only_for="b")
        with self.assertRaisesMessage(kcimos.SnapshotError, "現在是給 b,跟這一次講的 a 不一樣"):
            kcimos.apply(snapshot(), ["a"])
        Vendor.objects.filter(pk=public.pk).update(only_for="")
        with self.assertRaisesMessage(kcimos.SnapshotError, "現在是給 (沒有人)"):
            kcimos.apply(snapshot(), ["a"])
        Vendor.objects.filter(pk=public.pk).update(protocol=Vendor.Protocol.STANDARD, only_for="a")
        with self.assertRaisesMessage(kcimos.SnapshotError, "不是半自動的廠商"):
            kcimos.apply(snapshot(), ["a"])
        self.assertFalse(VendorItem.objects.exists())

    def test_the_command_previews_by_default_and_checks_the_database_name(self):
        path = os.path.join(tempfile.mkdtemp(), "snap.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(snapshot(), f, ensure_ascii=False)
        out = io.StringIO()
        call_command("import_kcimos_catalog", path, "--only-for", "a", stdout=out)
        self.assertIn("預覽(沒有寫):共 6 項 —— 新增 6、更新 0、一樣 0;其中停用 1、沒有參考價 3", out.getvalue())
        self.assertFalse(Vendor.objects.filter(code="kcimos").exists())
        with self.assertRaisesMessage(CommandError, "不是 somewhere_else"):
            call_command("import_kcimos_catalog", path, "--only-for", "a", "--apply", "--database-must-be", "somewhere_else")
        self.assertFalse(Vendor.objects.filter(code="kcimos").exists())
        out = io.StringIO()
        call_command("import_kcimos_catalog", path, "--only-for", "a", "--apply", stdout=out)
        self.assertIn("已匯入:共 6 項 —— 新增 6", out.getvalue())
        self.assertIn("kcimos 這家廠商是這一次建的", out.getvalue())
        self.assertEqual(VendorItem.objects.filter(vendor__code="kcimos").count(), 6)
        with self.assertRaisesMessage(CommandError, "快照檔讀不出來"):
            call_command("import_kcimos_catalog", path + ".nope", "--only-for", "a")
        with self.assertRaisesMessage(CommandError, "沒有這家公司:zz"):
            call_command("import_kcimos_catalog", path, "--only-for", "zz", "--apply")


class ImportRaceTests(TransactionTestCase):
    """複審 2026-10-13 第 2 條:匯入要**先鎖住廠商那一列、才核對**它是不是只給這幾家公司;還沒有這家廠商時自己建,同時有人也建了就整個不做。
    先核對再鎖的話,中間平台管理員建了 / 改成全部公司都看得到,這份進價就寫進一家公開的廠商。"""

    def setUp(self):
        Company("a", "甲通訊行", "甲")

    def meanwhile(self, statements, hold=1.0):
        """另一條連線執行這些 SQL、停一下再存檔。回傳時它已經做完、還沒存。"""
        holding = threading.Event()

        def work():
            other = connections.create_connection("default")
            try:
                other.ensure_connection()
                other.set_autocommit(False)
                with other.cursor() as cur:
                    for sql, params in statements:
                        cur.execute(sql, params)
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

    def test_someone_creating_a_public_kcimos_at_the_same_moment_stops_the_import(self):
        began = self.meanwhile([(
            "INSERT INTO vendor_orders_vendor (created_at, updated_at, code, name, protocol, api_base, key_prefix,"
            " order_email, contact, is_active, sort_order) VALUES (NOW(), NOW(), 'kcimos', '別人剛建的', 'manual', '', '', '', '', TRUE, 0)", [])])
        with self.assertRaisesMessage(kcimos.SnapshotError, "剛剛有人建了 kcimos 這家廠商:什麼都沒有匯"):
            kcimos.apply(snapshot(), ["a"])
        self.assertGreater(time.monotonic() - began, 0.5)
        vendor = Vendor.objects.get(code="kcimos")
        self.assertEqual((vendor.name, vendor.is_private), ("別人剛建的", False))
        self.assertFalse(VendorItem.objects.exists())                       # 一項都沒有寫進那家公開的廠商

    def test_a_vendor_being_made_public_at_the_same_moment_stops_the_import(self):
        vendor = Vendor.objects.create(code="kcimos", name="kcimos", protocol=Vendor.Protocol.MANUAL, is_private=True, only_for="a")
        began = self.meanwhile([
            ("SELECT 1 FROM vendor_orders_vendor WHERE id = %s FOR UPDATE", [vendor.pk]),
            ("UPDATE vendor_orders_vendor SET is_private = FALSE WHERE id = %s", [vendor.pk]),
        ])
        with self.assertRaisesMessage(kcimos.SnapshotError, "現在是每一家公司都看得到"):
            kcimos.apply(snapshot(), ["a"])
        self.assertGreater(time.monotonic() - began, 0.5)                   # 等他改完才核對
        self.assertFalse(VendorItem.objects.exists())
