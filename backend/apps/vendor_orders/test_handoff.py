"""把叫貨單送進廠商的下單網站:POS 這一側(代碼、進度、結果)。跑法:manage.py test apps.vendor_orders.test_handoff

owner 2026-10-13:kcimos「我就是要全自動，因為kcimos叫貨看冗長的品名是地獄體驗」。送單是小幫手在登入過的瀏覽器分頁裡做的;這裡不連 kcimos。
送出去就是真的訂單、不能自己取消。要守住的(動手前紅隊三條):
1. 不知道有沒有成立(待確認)就不能再送;要人選「訂單成立」或「沒有成立」。
2. 綁廠商網站的帳號:不是同一個帳號就不送。
3. 同一家門市 × 廠商同時只有一張叫貨單在送。
另外:代碼一次性、只存雜湊、會過期;小幫手的端點只對廠商網站的來源開跨來源;別家公司、沒權限的人碰不到。
"""
import hashlib
import json
import threading
import time
from datetime import timedelta
from decimal import Decimal as D

from django.db import connections
from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.backup.tests.factory import Company

from . import handoff, kcimos
from .models import Vendor, VendorHandoff, VendorItem, VendorLink, VendorOrder
from .test_kcimos import snapshot
from .tests import LINKS, ORDERS, _Shop

SITE = "http://kcimos.kv.idv.tw"
OPEN_URL = f"{SITE}/frontend/index.shtml#mppos="
State = VendorHandoff.State


def setup_kcimos(case):
    """甲通訊行的湳雅店、民生店都開通 kcimos(價目六項;2685 = 547 元、2636 = 333 元)。"""
    kcimos.apply(snapshot(), ["a"])
    for store in (case.wh1, case.wh2):
        r = case.admin.post(LINKS, {"warehouse": store.id, "vendor": "kcimos", "opened": True, "ship_name": "手機玩家",
                                    "ship_phone": "035551234", "ship_address": "新竹市湳雅街 18 號一樓"}, format="json")
        assert r.status_code == 200, r.content.decode()


def buy(case, key="draft-h001", lines=None, store=None, client=None):
    body = {"request_key": key, "warehouse": (store or case.wh1).id, "vendor": "kcimos",
            "lines": lines or [{"key": "KCIMOS-2685", "packs": 5}, {"key": "KCIMOS-2636", "packs": 2}]}
    r = (client or case.clerk).post(ORDERS, body, format="json")
    assert r.status_code == 201, r.content.decode()
    return r.json()


class _Site(_Shop):
    def setUp(self):
        super().setUp()
        setup_kcimos(self)
        self.o = buy(self)
        self.helper = APIClient()                      # 小幫手:沒有登入
        self.vendor.calls.clear()

    def start(self, order=None, client=None, expect=200):
        r = (client or self.clerk).post(f"{ORDERS}{(order or self.o)['id']}/handoff/", {}, format="json")
        self.assertEqual(r.status_code, expect, r.content.decode())
        return r.json()["url"].split("#mppos=")[1] if expect == 200 else r.json()

    def get(self, code, expect=200, **headers):
        r = self.helper.get(f"/api/v1/site-handoff/{code}/", **headers)
        self.assertEqual(r.status_code, expect, r.content.decode())
        return r.json()

    def step(self, code, step, body=None, expect=200):
        # 小幫手用 text/plain 送 JSON(不會先發預檢)
        r = self.helper.post(f"/api/v1/site-handoff/{code}/{step}/", json.dumps(body or {}), content_type="text/plain",
                             HTTP_ORIGIN=SITE)
        self.assertEqual(r.status_code, expect, r.content.decode())
        return r.json()

    def to_submitting(self, order=None, account="77", bind=True):
        code = self.start(order)
        self.step(code, "claim")
        self.step(code, "submitting", {"account": account, "bind": bind})
        return code

    def settle(self, back=None):
        """當成已經過了小幫手還可能在送的那段時間(之後才可以按「沒有成立」)。"""
        back = back or timedelta(minutes=handoff.DENY_WAIT_MINUTES, seconds=1)
        VendorHandoff.objects.filter(state=State.SUBMITTING).update(submitting_at=timezone.now() - back)

    def order_now(self, order=None, client=None):
        return (client or self.clerk).get(f"{ORDERS}{(order or self.o)['id']}/").json()

    def last(self, order=None):
        return VendorHandoff.objects.filter(order_id=(order or self.o)["id"]).order_by("-id").first()


class StartTests(_Site):
    def test_it_gives_a_one_time_link_and_keeps_only_the_hash(self):
        r = self.clerk.post(f"{ORDERS}{self.o['id']}/handoff/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        url = r.json()["url"]
        self.assertTrue(url.startswith(OPEN_URL), url)
        code = url[len(OPEN_URL):]
        self.assertGreaterEqual(len(code), 40)
        h = VendorHandoff.objects.get()
        self.assertEqual((h.state, h.code_hash, h.created_by, h.order_id),
                         (State.OPEN, hashlib.sha256(code.encode()).hexdigest(), self.c.clerk_user, self.o["id"]))
        self.assertNotIn(code, json.dumps(list(VendorHandoff.objects.values()), default=str))       # 代碼本身沒有存
        left = h.expires_at - timezone.now()
        self.assertTrue(timedelta(minutes=14) < left <= timedelta(minutes=15), left)
        self.assertEqual(self.vendor.calls, [])                                                     # 不打任何外部系統
        # 叫貨單知道自己可以送進廠商網站、現在沒有待確認的
        site = self.order_now()["site"]
        self.assertEqual((site["supported"], site["label"], site["pending"], site["external_order_no"]), (True, "kcimos", False, ""))
        self.assertEqual(site["memo"], f"MP POS {self.o['vendor_order_no']}")        # 待確認時畫面叫人找的就是這幾個字
        listed = self.clerk.get(ORDERS, {"warehouse": self.wh1.id}).json()["results"]
        self.assertEqual([x["site"]["supported"] for x in listed], [True])

    def test_pressing_again_makes_the_earlier_link_useless(self):
        first, second = self.start(), self.start()
        self.assertNotEqual(first, second)
        self.assertEqual(self.get(first, 400)["detail"], "這個代碼已經用過或過期了,請回 POS 重新按「自動送單」")
        self.assertEqual(self.get(second)["order_no"], self.o["vendor_order_no"])
        self.assertEqual(sorted(VendorHandoff.objects.values_list("state", flat=True)), [State.DROPPED, State.OPEN])

    def test_only_orders_that_can_go_to_the_site(self):
        """別種廠商、已經傳了、取消了、停用 / 被收回的廠商、料號認不出來的:都不發代碼。"""
        acme = Vendor.objects.create(code="acme", name="乙配件", protocol=Vendor.Protocol.MANUAL)
        VendorItem.objects.create(vendor=acme, sku="C01", name="快充線", ref_price=45)
        self.admin.post(LINKS, {"warehouse": self.wh1.id, "vendor": "acme", "opened": True, "ship_name": "x",
                                "ship_phone": "0", "ship_address": "y"}, format="json")
        other = self.clerk.post(ORDERS, {"request_key": "draft-acme1", "warehouse": self.wh1.id, "vendor": "acme",
                                         "lines": [{"key": "C01", "packs": 1}]}, format="json").json()
        self.assertEqual(self.start(other, expect=400)["detail"], "這家廠商不能從這裡直接送單")
        self.assertEqual(self.order_now(other)["site"]["supported"], False)

        cases = [
            (lambda: self.clerk.post(f"{ORDERS}{self.o['id']}/sent/", {"sent": True}, format="json"), "這張叫貨單已經傳給廠商了",
             lambda: self.clerk.post(f"{ORDERS}{self.o['id']}/sent/", {"sent": False}, format="json")),
            (lambda: self.clerk.post(f"{ORDERS}{self.o['id']}/cancel/", {"cancelled": True}, format="json"), "這張叫貨單已經取消了",
             lambda: self.clerk.post(f"{ORDERS}{self.o['id']}/cancel/", {"cancelled": False}, format="json")),
            (lambda: Vendor.objects.filter(code="kcimos").update(is_active=False), "「kcimos」已經停用,不能叫新的貨",
             lambda: Vendor.objects.filter(code="kcimos").update(is_active=True)),
            (lambda: Vendor.objects.filter(code="kcimos").update(only_for="b"), "「kcimos」沒有開放給這家公司,不能叫新的貨",
             lambda: Vendor.objects.filter(code="kcimos").update(only_for="a")),
            (lambda: VendorLink.objects.filter(provider="kcimos", warehouse=self.wh1).update(opened=False), "這家門市還沒有開通kcimos",
             lambda: VendorLink.objects.filter(provider="kcimos", warehouse=self.wh1).update(opened=True)),
        ]
        Company("b", "乙通訊行", "乙")
        for do, message, undo in cases:
            do()
            self.assertEqual(self.start(expect=400)["detail"], message)
            undo()
        self.start()                                                     # 都復原之後可以
        VendorOrder.objects.get(pk=self.o["id"]).items.filter(sku="KCIMOS-2636").update(sku="KC-2636")
        self.assertIn("對不到廠商網站的商品", self.start(expect=400)["detail"])

    def test_who_may_press_it(self):
        other = Company("b", "乙通訊行", "乙")
        self.start(client=other.admin, expect=404)                       # 別家公司
        away = buy(self, "draft-h002", store=self.wh2, client=self.admin)
        self.start(away, expect=404)                                     # 鎖在湳雅店的店員碰不到民生店的單
        self.turn_off("vendor_order")
        self.assertIn("沒有「廠商叫貨」的權限", self.start(expect=403)["detail"])
        self.turn_off()
        VendorLink.objects.filter(provider="kcimos", warehouse=self.wh1).update(clerk_ordering=False)
        self.assertIn("只有管理員可以跟kcimos叫貨", self.start(expect=403)["detail"])
        self.start(client=self.admin)
        self.assertEqual(VendorHandoff.objects.count(), 1)


class HelperTests(_Site):
    def test_the_helper_gets_what_to_put_in_the_cart(self):
        got = self.get(self.start(), HTTP_ORIGIN=SITE)
        self.assertEqual(got["lines"], [
            {"pk": "2685", "qty": 5, "name": "(3D黑邊)imos 低藍光玻璃貼 iPhone 18 Pro", "spec": "低藍光", "shop_name": "", "shop_sku": "",
             "ref_price": "547.00"},
            {"pk": "2636", "qty": 2, "name": "藍寶石鏡頭貼for SAMSUNG Galaxy Z Fold 7(黑框)$750", "spec": "藍鏡", "shop_name": "", "shop_sku": "",
             "ref_price": "333.00"}])
        self.assertEqual((got["order_no"], got["store"], got["memo"], got["account"]),
                         (self.o["vendor_order_no"], self.wh1.name, f"MP POS {self.o['vendor_order_no']}", ""))
        self.assertEqual(got["recipient"], {"name": "手機玩家", "phone": "035551234", "address": "新竹市湳雅街 18 號一樓"})
        self.assertEqual(self.last().state, State.OPEN)                  # 只是拿來看,還沒開始

    def test_the_cart_gets_packs_not_pieces(self):
        """kcimos 的一件 = POS 的一包。價目表上「一包 5 個」的品項叫 2 包:購物車放 2(不是 10 個)。"""
        VendorItem.objects.filter(vendor__code="kcimos", sku="KCIMOS-2636").update(pack_qty=5)
        order = buy(self, "draft-h009", lines=[{"key": "KCIMOS-2636", "packs": 2}])
        self.assertEqual([(i["packs"], i["qty"]) for i in order["items"]], [(2, 10)])
        self.assertEqual([(line["pk"], line["qty"]) for line in self.get(self.start(order))["lines"]], [("2636", 2)])

    def test_an_order_with_the_same_site_product_twice_cannot_go(self):
        """同一個 kcimos 商品在單上有兩行:購物車裡會併成一項還是兩項不知道,核對不了 —— 不自動送(不猜)。"""
        first = VendorOrder.objects.get(pk=self.o["id"]).items.order_by("line_no").first()
        first.pk, first.line_no = None, 9
        first.save()
        self.assertEqual(self.start(expect=400)["detail"], f"「{first.name}」在這張單上出現兩次,這張單不能自動送")
        self.assertEqual(VendorHandoff.objects.count(), 0)

    def test_the_steps_only_go_in_order(self):
        """還沒開始動購物車就說「要送了」、還沒說「要送了」就回報被拒:都不收(照順序才知道購物車是誰的、結果是哪一次的)。"""
        code = self.start()
        self.assertIn("已經不在進行中", self.step(code, "submitting", {"account": "77", "bind": True}, expect=400)["detail"])
        self.assertEqual((self.last().state, self.order_now()["site"]["pending"]), (State.OPEN, False))
        self.assertEqual(VendorLink.objects.get(provider="kcimos", warehouse=self.wh1).site_account, "")
        for state in (State.OPEN, State.CLAIMED):
            self.assertEqual(self.step(code, "failed", {"message": "x"}, expect=400)["detail"], "這一次送單不是「待確認」的狀態")
            self.assertEqual(self.last().state, state)
            if state == State.OPEN:
                self.step(code, "claim")

    def test_a_wrong_expired_or_used_code_gets_nothing(self):
        for bad in ("x" * 43, "short", "a" * 200):
            self.assertEqual(self.get(bad, 400)["detail"], "代碼不對,請回 POS 重新按「自動送單」")
        code = self.start()
        VendorHandoff.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.get(code, 400)["detail"], "這個代碼已經用過或過期了,請回 POS 重新按「自動送單」")
        self.assertEqual((self.last().state, self.last().problem), (State.DROPPED, "代碼過期"))
        self.assertEqual(self.step(code, "claim", expect=400)["detail"], "這個代碼已經用過或過期了,請回 POS 重新按「自動送單」")
        code = self.start()
        self.step(code, "claim")
        self.assertEqual(self.get(code, 400)["detail"], "這個代碼已經用過或過期了,請回 POS 重新按「自動送單」")    # 開始做了就不能再拿一次
        self.assertEqual(self.step(code, "nothing", expect=404)["detail"], "沒有這一步")

    def test_only_the_vendor_site_may_call_from_a_page(self):
        code = self.start()
        ok = self.helper.get(f"/api/v1/site-handoff/{code}/", HTTP_ORIGIN=SITE)
        self.assertEqual((ok["Access-Control-Allow-Origin"], ok["Cache-Control"]), (SITE, "no-store"))
        for origin in ("https://evil.example", "https://kcimos.kv.idv.tw", "http://kcimos.kv.idv.tw.evil.example"):
            self.assertNotIn("Access-Control-Allow-Origin", self.helper.get(f"/api/v1/site-handoff/{code}/", HTTP_ORIGIN=origin))
        pre = self.helper.options(f"/api/v1/site-handoff/{code}/claim/", HTTP_ORIGIN=SITE)
        self.assertEqual((pre.status_code, pre["Access-Control-Allow-Origin"]), (200, SITE))
        self.assertEqual(self.last().state, State.OPEN)                  # 預檢不算開始
        bad = self.helper.post(f"/api/v1/site-handoff/{code}/claim/", "{not json", content_type="text/plain", HTTP_ORIGIN=SITE)
        self.assertEqual(bad.status_code, 400)

    def test_one_order_at_a_time_for_a_store(self):
        """一個帳號只有一台購物車:同一家門市同時只准一張叫貨單在動它。別家門市(另一個串接)不相干;放太久的那一次不會一直擋著。"""
        second = buy(self, "draft-h002")
        a, b = self.start(), self.start(second)
        self.step(a, "claim")
        self.assertEqual(self.step(b, "claim", expect=400)["detail"], f"另一張叫貨單({self.o['vendor_order_no']})正在送,等它處理完再送這一張")
        away = buy(self, "draft-h003", store=self.wh2, client=self.admin)
        self.step(self.start(away, client=self.admin), "claim")           # 民生店:自己的串接,不受影響
        self.step(a, "release", {"reason": "人按取消"})
        self.assertEqual((self.last().state, self.last().problem), (State.DROPPED, "人按取消"))
        self.step(b, "claim")
        # 放進購物車之後沒有下文(分頁關掉了):過了時間就不擋別張單
        third = self.start()
        VendorHandoff.objects.filter(order_id=second["id"], state=State.CLAIMED).update(
            claimed_at=timezone.now() - timedelta(minutes=handoff.CLAIM_MINUTES, seconds=1))
        self.step(third, "claim")
        self.assertEqual((self.last(second).state, self.last(second).problem), (State.DROPPED, "放進購物車之後沒有下文"))
        self.assertEqual(self.step(b, "submitting", {"account": "77", "bind": True}, expect=400)["detail"],
                         "這一次送單已經不在進行中(可能放太久、或被另一張單接手),沒有送出;請回 POS 重新按「自動送單」")

    def test_starting_over_takes_over_from_the_earlier_try(self):
        """放進購物車之後分頁關掉了,人回 POS 重新按「自動送單」:新的這一次接手,不用等十分鐘;舊分頁再按送出不送。"""
        old = self.start()
        self.step(old, "claim")
        new = self.start()                                               # 還沒說「要送了」:可以重新發代碼
        self.step(new, "claim")
        states = list(VendorHandoff.objects.filter(order_id=self.o["id"]).order_by("id").values_list("state", "problem"))
        self.assertEqual(states, [(State.DROPPED, "同一張單重新送了"), (State.CLAIMED, "")])
        self.assertIn("已經不在進行中", self.step(old, "submitting", {"account": "77", "bind": True}, expect=400)["detail"])
        # 舊分頁這時候按取消:POS 講明「不是這一下才放掉的」—— 購物車現在是新的那一次在用,舊分頁不能清(複審第一輪 P1)
        self.assertEqual(self.step(old, "release", {"reason": "人按了取消"}), {"ok": True, "released": False})
        self.assertEqual(self.last().state, State.CLAIMED)
        # 新的那一次自己取消:是這一下才放掉的,可以清
        third = self.start()
        self.step(third, "claim")
        self.assertEqual(self.step(new, "release"), {"ok": True, "released": False})          # new 已經被 third 接手
        self.assertEqual(self.step(third, "release"), {"ok": True, "released": True})
        fourth = self.start()
        self.step(fourth, "claim")
        self.step(fourth, "submitting", {"account": "77", "bind": True})
        # 別張單的不接手(那是真的有人在送)
        second = buy(self, "draft-h002")
        self.assertIn("上一次送出還沒確認", self.step(self.start(second), "claim", expect=400)["detail"])

    def test_the_helper_is_told_up_front_when_another_order_is_in_the_way(self):
        """小幫手一開始拿內容時就講(它還沒動購物車):別張單待確認時購物車裡可能留著那一張的東西,不能讓人清了才知道不能送。
        只是先講一聲 —— 那一次的代碼還在,等前面那張處理完可以再按。"""
        self.to_submitting()
        second = buy(self, "draft-h002")
        code = self.start(second)
        self.assertEqual(self.get(code, expect=400)["detail"],
                         f"另一張叫貨單({self.o['vendor_order_no']})上一次送出還沒確認有沒有成立,等它處理完再送這一張")
        self.assertEqual(self.last(second).state, State.OPEN)                       # 沒有被收掉、也沒有被當成開始了
        self.settle()
        r = self.clerk.post(f"{ORDERS}{self.o['id']}/handoff/resolve/", {"placed": False}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.assertEqual(self.get(code)["order_no"], second["vendor_order_no"])     # 前面那張處理完:同一組代碼照樣可以用
        # 同一張單自己之前那一次(停在放進購物車)不擋:這一次會接手
        self.step(code, "claim")
        again = self.start(second)
        self.assertEqual(self.get(again)["order_no"], second["vendor_order_no"])
        self.assertEqual(self.last(second).state, State.OPEN)                       # 只看、不收(收是 claim 的事)
        self.assertEqual(VendorHandoff.objects.filter(order_id=second["id"], state=State.CLAIMED).count(), 1)

    def test_release_is_only_for_before_saying_it_is_being_sent(self):
        code = self.start()
        self.assertEqual(self.step(code, "release"), {"ok": True, "released": False})     # 還沒動購物車:沒有東西要清
        self.assertEqual(self.step(code, "release"), {"ok": True, "released": False})     # 再說一次沒關係
        self.assertEqual(self.last().state, State.DROPPED)
        code = self.to_submitting()
        self.assertEqual(self.step(code, "release", expect=400)["detail"],
                         "這一次已經說要送了,不能直接收回;請到 POS 的叫貨單確認有沒有成立")
        self.assertEqual(self.last().state, State.SUBMITTING)


class AccountTests(_Site):
    def test_the_first_order_binds_the_site_account_after_the_person_agrees(self):
        code = self.start()
        self.step(code, "claim")
        self.assertEqual(self.step(code, "submitting", {"account": "77"}, expect=400)["detail"], "這家門市還沒有綁 kcimos 帳號,沒有送出")
        self.assertEqual((self.last().state, VendorLink.objects.get(provider="kcimos", warehouse=self.wh1).site_account), (State.CLAIMED, ""))
        self.step(code, "submitting", {"account": "77", "bind": True})
        self.assertEqual(VendorLink.objects.get(provider="kcimos", warehouse=self.wh1).site_account, "77")
        self.assertEqual(VendorLink.objects.get(provider="kcimos", warehouse=self.wh2).site_account, "")     # 別家門市各綁各的
        self.assertEqual((self.last().state, self.last().account), (State.SUBMITTING, "77"))

    def test_another_account_is_refused_not_just_flagged(self):
        """這個瀏覽器登入的是別的 kcimos 帳號(收件人剛好一樣也一樣):不送。單不會下到別的帳號去。"""
        self.step(self.to_submitting(), "done", {"order_no": "SO20261013001"})
        second = buy(self, "draft-h002")
        code = self.start(second)
        self.assertEqual(self.get(code)["account"], "77")                # 小幫手先拿到綁的是哪一個,可以早一點停
        self.step(code, "claim")
        for wrong, bind in (("78", False), ("78", True), ("7", True)):
            self.assertEqual(self.step(code, "submitting", {"account": wrong, "bind": bind}, expect=400)["detail"],
                             "這個瀏覽器登入的不是這家門市綁定的 kcimos 帳號,沒有送出")
        self.assertEqual((self.last(second).state, VendorLink.objects.get(provider="kcimos", warehouse=self.wh1).site_account),
                         (State.CLAIMED, "77"))
        self.step(code, "submitting", {"account": "77"})                 # 同一個帳號:不用再同意一次

    def test_an_admin_can_forget_the_account_and_saving_settings_keeps_it(self):
        """綁錯帳號(登入的是另一家店的帳號就送了第一張):管理員解除,下一次送單重新問、重新綁。平常存設定不動它。"""
        self.step(self.to_submitting(), "done", {"order_no": "SO20261013001"})
        row = lambda: next(r for r in self.admin.get(LINKS).json()["results"]                     # noqa: E731
                           if r["provider"] == "kcimos" and r["warehouse"] == self.wh1.id)
        self.assertEqual(row()["site"], {"supported": True, "label": "kcimos", "bound": True})
        body = {"warehouse": self.wh1.id, "vendor": "kcimos", "ship_name": "手機玩家湳雅"}
        self.assertEqual(self.admin.post(LINKS, body, format="json").json()["site"]["bound"], True)
        self.assertEqual(VendorLink.objects.get(provider="kcimos", warehouse=self.wh1).site_account, "77")
        r = self.clerk.post(LINKS, {**body, "forget_site_account": True}, format="json")
        self.assertEqual(r.status_code, 403)
        r = self.admin.post(LINKS, {**body, "forget_site_account": "yes"}, format="json")
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "解除綁定只能是「要」"))
        self.assertEqual(VendorLink.objects.get(provider="kcimos", warehouse=self.wh1).site_account, "77")
        r = self.admin.post(LINKS, {**body, "forget_site_account": True}, format="json")
        self.assertEqual((r.status_code, r.json()["site"]["bound"]), (200, False))
        second = buy(self, "draft-h002")
        code = self.start(second)
        self.assertEqual(self.get(code)["account"], "")
        self.step(code, "claim")
        self.step(code, "submitting", {"account": "88", "bind": True})
        self.assertEqual(VendorLink.objects.get(provider="kcimos", warehouse=self.wh1).site_account, "88")

    def test_saving_settings_does_not_write_back_a_stale_account(self):
        """設定頁存的是它管的那幾格:整列重存的話,存檔前讀到的「還沒綁」會把同一瞬間綁好的帳號蓋回空的。"""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as seen:
            r = self.admin.post(LINKS, {"warehouse": self.wh1.id, "vendor": "kcimos", "ship_name": "手機玩家"}, format="json")
        self.assertEqual(r.status_code, 200)
        writes = [q["sql"] for q in seen if q["sql"].startswith("UPDATE") and "vendor_orders_vendorlink" in q["sql"]]
        self.assertEqual(len(writes), 1)
        self.assertNotIn("site_account", writes[0])

    def test_an_account_number_that_cannot_be_read_stops_it(self):
        code = self.start()
        self.step(code, "claim")
        for odd in (None, "", " ", 77, "a b", "x" * 41, "<script>"):
            self.assertEqual(self.step(code, "submitting", {"account": odd, "bind": True}, expect=400)["detail"],
                             "讀不到廠商網站的帳號編號,沒有送出", odd)
        self.assertEqual(self.last().state, State.CLAIMED)


class ResultTests(_Site):
    def test_done_marks_the_order_sent_with_the_site_order_number(self):
        code = self.to_submitting()
        self.assertEqual(self.order_now()["sent_at"], None)
        self.assertEqual(self.step(code, "done", {"order_no": "SO20261013001", "total": "3566", "shipping": 0}),
                         {"ok": True, "order_no": "SO20261013001"})
        o = VendorOrder.objects.get(pk=self.o["id"])
        self.assertEqual((o.external_order_no, o.sent_how, o.sent_by, o.total_amount, o.shipping_fee),
                         ("SO20261013001", "site", self.c.clerk_user, D("3566.00"), D("0.00")))
        self.assertIsNotNone(o.sent_at)
        self.assertIsNotNone(o.vendor_ordered_at)
        self.assertEqual((self.last().state, self.last().external_order_no, self.last().resolved_by), (State.DONE, "SO20261013001", None))
        site = self.order_now()["site"]
        self.assertEqual((site["pending"], site["external_order_no"]), (False, "SO20261013001"))
        # 回應沒回來、小幫手再報一次:照樣成功、不會變
        self.step(code, "done", {"order_no": "SO20261013001", "total": "3566"})
        self.assertEqual(self.step(code, "done", {"order_no": "SO20261013002"}, expect=400)["detail"],
                         "這一次送單不是「待確認」的狀態,沒有記下來;請到 POS 的叫貨單確認")
        self.assertEqual(VendorOrder.objects.get(pk=self.o["id"]).external_order_no, "SO20261013001")
        self.assertEqual(self.start(expect=400)["detail"], "這張叫貨單已經傳給廠商了")            # 成立了就不能再送

    def test_done_keeps_what_the_site_said(self):
        self.step(self.to_submitting(), "done", {"order_no": "SO20261013001", "note": "訂單已送出" * 100})
        self.assertEqual((self.last().state, self.last().problem), (State.DONE, ("訂單已送出" * 100)[:300]))

    def test_done_needs_a_real_looking_number_and_only_from_being_sent(self):
        code = self.start()
        self.step(code, "claim")
        self.assertIn("不是「待確認」的狀態", self.step(code, "done", {"order_no": "SO20261013001"}, expect=400)["detail"])    # 還沒說要送
        self.step(code, "submitting", {"account": "77", "bind": True})
        for odd in (None, "", "S1", "SO 2026", "x" * 41, "SO20261013001;drop"):
            self.assertEqual(self.step(code, "done", {"order_no": odd}, expect=400)["detail"], "訂單編號的樣子不對(只能是英文、數字、減號)", odd)
        for odd in ("abc", "-1", "1e400", "999999999"):
            self.assertEqual(self.step(code, "done", {"order_no": "SO20261013001", "total": odd}, expect=400)["detail"], "金額不對", odd)
        self.assertEqual((self.last().state, VendorOrder.objects.get(pk=self.o["id"]).sent_at), (State.SUBMITTING, None))

    def test_one_site_order_cannot_be_recorded_on_two_orders(self):
        self.step(self.to_submitting(), "done", {"order_no": "SO20261013001"})
        second = buy(self, "draft-h002")
        code = self.to_submitting(second, bind=False)
        self.assertEqual(self.step(code, "done", {"order_no": "SO20261013001"}, expect=400)["detail"],
                         f"訂單編號 SO20261013001 已經記在另一張叫貨單({self.o['vendor_order_no']})上了")
        self.assertEqual((self.last(second).state, VendorOrder.objects.get(pk=second["id"]).external_order_no), (State.SUBMITTING, ""))

    def test_an_order_placed_on_the_site_cannot_be_unmarked(self):
        """收回「已傳」= 這張單又可以送一次。網站上成立的那一張不會跟著不見,再送就是兩張。"""
        self.step(self.to_submitting(), "done", {"order_no": "SO20261013001"})
        r = self.clerk.post(f"{ORDERS}{self.o['id']}/sent/", {"sent": False}, format="json")
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "這張單已經在廠商那邊成立了(SO20261013001),不能收回"))
        self.assertEqual(self.start(expect=400)["detail"], "這張叫貨單已經傳給廠商了")
        self.assertEqual(self.order_now()["sent_how"], "site")
        # 手動標的照舊可以收回(那只是記號)
        second = buy(self, "draft-h002")
        for sent in (True, False):
            r = self.clerk.post(f"{ORDERS}{second['id']}/sent/", {"sent": sent}, format="json")
            self.assertEqual((r.status_code, r.json()["sent_at"] is not None), (200, sent))

    def test_failed_means_the_site_said_no_and_the_order_can_go_again(self):
        code = self.to_submitting()
        self.step(code, "failed", {"message": "庫存不足" * 100})
        self.step(code, "failed", {"message": "再報一次"})
        self.assertEqual((self.last().state, self.last().problem), (State.FAILED, ("庫存不足" * 100)[:300]))
        self.assertEqual((self.order_now()["sent_at"], self.order_now()["site"]["pending"]), (None, False))
        self.step(self.start(), "claim")                                 # 可以重新送


class PendingTests(_Site):
    """說了「要送了」之後沒有回報結果 = 待確認:這張單不能再送、同一家門市的別張單也先不能送,要人確認掉。"""

    def setUp(self):
        super().setUp()
        self.code = self.to_submitting()

    def resolve(self, body, order=None, client=None, expect=200):
        r = (client or self.clerk).post(f"{ORDERS}{(order or self.o)['id']}/handoff/resolve/", body, format="json")
        self.assertEqual(r.status_code, expect, r.content.decode())
        return r.json()

    def test_a_pending_order_cannot_be_sent_again(self):
        site = self.order_now()["site"]
        self.assertEqual((site["pending"], site["pending_since"] is not None), (True, True))
        self.assertEqual(self.start(expect=400)["detail"],
                         "這張單上一次送出還不知道有沒有成立(待確認):請先到廠商的訂單查詢確認,再選「訂單成立」或「沒有成立」")
        second = buy(self, "draft-h002")
        other = self.start(second)
        self.assertEqual(self.step(other, "claim", expect=400)["detail"],
                         f"另一張叫貨單({self.o['vendor_order_no']})上一次送出還沒確認有沒有成立,等它處理完再送這一張")
        self.assertEqual(VendorOrder.objects.filter(sent_at__isnull=False).count(), 0)

    def test_it_cannot_be_marked_sent_by_hand_while_pending(self):
        """待確認的單自己標成「已傳」= 跳過確認:網站上到底有沒有那一張就沒有人查了。"""
        r = self.clerk.post(f"{ORDERS}{self.o['id']}/sent/", {"sent": True}, format="json")
        self.assertEqual((r.status_code, r.json()["detail"]),
                         (400, "這張單上一次送出還不知道有沒有成立(待確認),請先選「訂單成立」或「沒有成立」"))
        self.assertEqual((self.order_now()["sent_at"], self.last().state), (None, State.SUBMITTING))

    def test_it_never_times_out_on_its_own(self):
        VendorHandoff.objects.update(submitting_at=timezone.now() - timedelta(days=3), claimed_at=timezone.now() - timedelta(days=3))
        second = buy(self, "draft-h002")
        self.assertIn("上一次送出還沒確認", self.step(self.start(second), "claim", expect=400)["detail"])
        self.assertEqual(self.last().state, State.SUBMITTING)

    def test_a_person_says_it_was_placed_and_gives_the_number(self):
        for body in ({"placed": True}, {"placed": True, "order_no": "SO 1"}):
            self.assertEqual(self.resolve(body, expect=400)["detail"], "訂單成立要填廠商的訂單編號(英文、數字、減號)")
        self.assertEqual(self.resolve({"placed": "yes"}, expect=400)["detail"], "只能是「訂單成立」或「沒有成立」")
        got = self.resolve({"placed": True, "order_no": " SO20261013009 "})
        self.assertEqual((got["site"]["pending"], got["site"]["external_order_no"], got["sent_how"], got["sent_by"]),
                         (False, "SO20261013009", "site", self.c.clerk_user.username))
        self.assertEqual((self.last().state, self.last().resolved_by), (State.DONE, self.c.clerk_user))
        self.assertEqual(self.resolve({"placed": False}, expect=400)["detail"], "這張叫貨單沒有待確認的送出")
        # 小幫手這時候才回報:同一個編號照樣成功,別的編號不收
        self.step(self.code, "done", {"order_no": "SO20261013009"})
        self.assertIn("不是「待確認」的狀態", self.step(self.code, "done", {"order_no": "SO20261013010"}, expect=400)["detail"])

    def test_not_placed_has_to_wait_while_the_helper_may_still_be_sending(self):
        """剛說「要送了」的那幾分鐘小幫手可能還在等網站回答:訂單查詢上還看不到不代表沒有成立。
        這時候就給按「沒有成立」、再送一次 → 第一次後來成立了,就是兩張訂單(複審第一輪 P0)。"""
        site = self.order_now()["site"]
        self.assertEqual(self.last().submitting_at + timedelta(minutes=handoff.DENY_WAIT_MINUTES),
                         timezone.datetime.fromisoformat(site["can_deny_at"].replace("Z", "+00:00")))
        self.assertEqual(self.resolve({"placed": False}, expect=400)["detail"],
                         "小幫手可能還在送,5 分鐘後還沒有結果再確認(到時候先到廠商的訂單查詢看過)")
        self.settle(timedelta(minutes=handoff.DENY_WAIT_MINUTES, seconds=-20))            # 還差 20 秒
        self.assertEqual(self.resolve({"placed": False}, expect=400)["detail"],
                         "小幫手可能還在送,1 分鐘後還沒有結果再確認(到時候先到廠商的訂單查詢看過)")
        self.assertEqual((self.last().state, self.start(expect=400)["detail"][:14]), (State.SUBMITTING, "這張單上一次送出還不知道有沒"))
        self.settle()
        self.resolve({"placed": False})
        self.assertEqual(self.last().state, State.DROPPED)

    def test_placed_can_be_said_at_once(self):
        """看到訂單了就是有:「訂單成立」不用等。"""
        got = self.resolve({"placed": True, "order_no": "SO20261013009"})
        self.assertEqual((got["site"]["pending"], got["site"]["can_deny_at"], got["site"]["external_order_no"]), (False, None, "SO20261013009"))

    def test_a_late_success_after_a_person_said_no_is_still_recorded(self):
        """人選了「沒有成立」之後,小幫手才收到網站說成立了:照網站的回答記(這張單還沒再送)。不記的話這張單可以再送一次。"""
        self.settle()
        self.resolve({"placed": False})
        self.step(self.code, "failed", {"message": "晚到的"})                                # 晚到的「被拒」:已經是沒有成立了,不當成錯
        self.assertEqual((self.last().state, self.last().problem), (State.DROPPED, handoff.DENIED))
        self.assertEqual(self.step(self.code, "done", {"order_no": "SO20261013001", "note": "訂單已送出"}),
                         {"ok": True, "order_no": "SO20261013001"})
        now = self.order_now()
        self.assertEqual((now["site"]["external_order_no"], now["site"]["pending"], now["sent_how"]), ("SO20261013001", False, "site"))
        self.assertEqual((self.last().state, self.last().resolved_by, self.last().problem), (State.DONE, self.c.clerk_user, "訂單已送出"))
        self.assertEqual(self.start(expect=400)["detail"], "這張叫貨單已經傳給廠商了")
        # 只有「人說沒有成立」的才這樣:自己取消、過期的那幾次不能事後回報成立
        second = buy(self, "draft-h002")
        code = self.start(second)
        self.step(code, "claim")
        self.step(code, "release")
        self.assertIn("不是「待確認」的狀態", self.step(code, "done", {"order_no": "SO20261013002"}, expect=400)["detail"])

    def test_a_late_success_after_the_order_went_out_again_is_called_out(self):
        """人選了「沒有成立」、又重新送了(或自己標了已傳),第一次才回報成立:兩張沒辦法都記在同一張單上 ——
        明講第一次那一張是多出來的,請人聯絡廠商取消;第二次的照常。"""
        self.settle()
        self.resolve({"placed": False})
        again = self.start()
        self.step(again, "claim")
        self.step(again, "submitting", {"account": "77", "bind": False})
        extra = "這張叫貨單已經重新送出了,廠商那邊的訂單 SO20261013001 是多出來的一張,請聯絡廠商取消"
        self.assertEqual(self.step(self.code, "done", {"order_no": "SO20261013001"}, expect=400)["detail"], extra)
        self.assertEqual((self.order_now()["site"]["pending"], self.order_now()["site"]["external_order_no"]), (True, ""))
        self.step(again, "done", {"order_no": "SO20261013002"})
        self.assertEqual(self.order_now()["site"]["external_order_no"], "SO20261013002")
        self.assertEqual(self.step(self.code, "done", {"order_no": "SO20261013001"}, expect=400)["detail"], extra)
        # 自己標了已傳的也一樣
        second = buy(self, "draft-h002")
        code = self.to_submitting(second, bind=False)
        self.settle()
        self.resolve({"placed": False}, order=second)
        self.clerk.post(f"{ORDERS}{second['id']}/sent/", {"sent": True}, format="json")
        self.assertIn("是多出來的一張", self.step(code, "done", {"order_no": "SO20261013003"}, expect=400)["detail"])
        self.assertEqual(self.order_now(second)["site"]["external_order_no"], "")

    def test_what_is_kept_across_a_restore_only_lands_on_the_same_order(self):
        """還原時放回去的「已成立 / 待確認」只放在同一張單上:單號與當初的鑰匙都要對得上
        (還原過的環境裡,同一個單號可能是另一條時間線上的另一張單)。整段還原在 `backup/tests` 有測。"""
        self.settle()
        self.resolve({"placed": False})                                   # 這張單現在沒有送過
        row = VendorOrder.objects.get(pk=self.o["id"])
        key = {"provider": row.provider, "vendor_order_no": row.vendor_order_no}
        placed = {**key, "request_key": "別的鑰匙", "external_order_no": "SO20261014009", "sent_at": timezone.now(), "vendor_ordered_at": None}
        waiting = {"order__provider": row.provider, "order__vendor_order_no": row.vendor_order_no, "order__request_key": "別的鑰匙",
                   "submitting_at": timezone.now(), "account": "77"}
        self.assertEqual(handoff.reapply_after_restore(self.t, {"placed": [placed], "waiting": [waiting]}), 0)
        self.assertEqual((self.order_now()["site"]["external_order_no"], self.order_now()["site"]["pending"]), ("", False))
        waiting["order__request_key"] = row.request_key
        self.assertEqual(handoff.reapply_after_restore(self.t, {"placed": [], "waiting": [waiting, waiting]}), 1)     # 不會放兩筆
        self.assertEqual(self.order_now()["site"]["pending"], True)
        placed["request_key"] = row.request_key
        self.assertEqual(handoff.reapply_after_restore(self.t, {"placed": [placed], "waiting": []}), 1)
        now = self.order_now()
        self.assertEqual((now["site"]["external_order_no"], now["site"]["pending"], now["sent_how"]), ("SO20261014009", False, "site"))
        self.assertEqual(handoff.reapply_after_restore(self.t, {"placed": [placed], "waiting": [waiting]}), 0)        # 已經有了:不動

    def test_a_pending_send_comes_back_even_onto_an_order_marked_sent_by_hand(self):
        """備份裡這張單是「手動標了已傳」(誤按的),之後收回、用小幫手送、停在待確認,然後還原到那份備份:
        待確認要放回去 —— 不放的話畫面只寫「已傳出」,收回標記之後就能再送一次(複審第二輪 P0)。"""
        facts = handoff.facts_before_restore(self.t)                       # 現況:這張單待確認
        self.assertEqual(len(facts["waiting"]), 1)
        # 當成還原回來的樣子:送單紀錄不在了,這張單是手動標的已傳
        VendorHandoff.objects.all().delete()
        VendorOrder.objects.filter(pk=self.o["id"]).update(sent_at=timezone.now(), sent_how="manual")
        self.assertEqual(handoff.reapply_after_restore(self.t, facts), 1)
        now = self.order_now()
        self.assertEqual((now["sent_how"], now["site"]["pending"]), ("manual", True))
        r = self.clerk.post(f"{ORDERS}{self.o['id']}/sent/", {"sent": False}, format="json")
        self.assertEqual((r.status_code, r.json()["detail"][:21]), (400, "這張單上一次送出還不知道有沒有成立(待確認"))
        self.assertEqual(self.start(expect=400)["detail"], "這張叫貨單已經傳給廠商了")
        # 同一組代碼還認得:小幫手這時候才回報成立,記得回去(誰送的也還在)
        self.step(self.code, "done", {"order_no": "SO20261014020"})
        now = self.order_now()
        self.assertEqual((now["site"]["external_order_no"], now["site"]["pending"]), ("SO20261014020", False))
        self.assertEqual(self.last().created_by, self.c.clerk_user)

    def test_a_send_caught_halfway_by_the_backup_is_carried_on_not_duplicated(self):
        """備份是在這一次送到一半(已經開始動購物車)時做的:還原回來的資料裡有這一筆、停在前面的進度。
        放回待確認時接著改那一筆 —— 再新增一筆同樣代碼的會撞唯一限制,整個還原就失敗了。"""
        facts = handoff.facts_before_restore(self.t)                       # 現況:待確認
        VendorHandoff.objects.update(state=State.CLAIMED, submitting_at=None, account="")      # 還原回來的樣子:還停在放進購物車
        self.assertEqual(handoff.reapply_after_restore(self.t, facts), 1)
        self.assertEqual(list(VendorHandoff.objects.values_list("state", "account", "problem")),
                         [(State.SUBMITTING, "77", "還原備份之前就待確認")])
        self.assertEqual(self.last().submitting_at, facts["waiting"][0]["submitting_at"])

    def test_a_person_says_it_was_not_placed_and_it_can_go_again(self):
        self.settle()
        got = self.resolve({"placed": False})
        self.assertEqual((got["site"]["pending"], got["sent_at"], got["site"]["external_order_no"]), (False, None, ""))
        self.assertEqual((self.last().state, self.last().problem, self.last().resolved_by), (State.DROPPED, "人確認沒有成立", self.c.clerk_user))
        self.step(self.start(), "claim")

    def test_who_may_resolve(self):
        other = Company("b", "乙通訊行", "乙")
        self.resolve({"placed": False}, client=other.admin, expect=404)
        self.turn_off("vendor_order")
        self.assertIn("沒有「廠商叫貨」的權限", self.resolve({"placed": False}, expect=403)["detail"])
        self.assertEqual(self.last().state, State.SUBMITTING)


class TwoAtOnceTests(TransactionTestCase):
    """兩個分頁差不多同時開始送同一家門市的兩張單:一個一個過(鎖門市 × 廠商那一列),後到的看得到先到的、被擋下來。
    不鎖的話兩邊都看到「沒有人在送」,兩張單的東西會疊進同一台購物車。"""

    def setUp(self):
        self.c = Company("a", "甲通訊行", "甲")
        self.t, self.wh1, self.wh2 = self.c.tenant, *self.c.warehouses
        self.admin, self.clerk = self.c.admin, self.c.clerk
        setup_kcimos(self)
        self.a, self.b = buy(self, "draft-h001"), buy(self, "draft-h002")

    def test_the_second_one_waits_and_is_refused(self):
        code_a = self.clerk.post(f"{ORDERS}{self.a['id']}/handoff/", {}, format="json").json()["url"].split("#mppos=")[1]
        self.clerk.post(f"{ORDERS}{self.b['id']}/handoff/", {}, format="json")
        link = VendorLink.objects.get(provider="kcimos", warehouse=self.wh1)
        other_b = VendorHandoff.objects.get(order_id=self.b["id"])
        holding = threading.Event()

        def another_tab_claims_b():
            other = connections.create_connection("default")
            try:
                other.ensure_connection()
                other.set_autocommit(False)
                with other.cursor() as cur:
                    cur.execute("SELECT 1 FROM vendor_orders_vendorlink WHERE id = %s FOR UPDATE", [link.pk])
                    cur.execute("UPDATE vendor_orders_vendorhandoff SET state = 'claimed', claimed_at = NOW() WHERE id = %s", [other_b.pk])
                holding.set()
                time.sleep(1.0)
                other.commit()
            finally:
                other.close()

        t = threading.Thread(target=another_tab_claims_b)
        t.start()
        self.addCleanup(t.join)
        self.assertTrue(holding.wait(5))
        began = time.monotonic()
        r = APIClient().post(f"/api/v1/site-handoff/{code_a}/claim/", "{}", content_type="text/plain", HTTP_ORIGIN=SITE)
        self.assertGreater(time.monotonic() - began, 0.5)                # 真的等了
        self.assertEqual((r.status_code, r.json()["detail"]),
                         (400, f"另一張叫貨單({self.b['vendor_order_no']})正在送,等它處理完再送這一張"))
        self.assertEqual(VendorHandoff.objects.get(order_id=self.a["id"]).state, State.OPEN)

    def _meanwhile(self, statements):
        """另一條連線:照順序做這幾句、握著 1 秒才提交。回來時它已經握著鎖了。"""
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
                time.sleep(1.0)
                other.commit()
            finally:
                other.close()

        t = threading.Thread(target=work)
        t.start()
        self.addCleanup(t.join)
        self.assertTrue(holding.wait(5))

    def _claimed(self):
        code = self.clerk.post(f"{ORDERS}{self.a['id']}/handoff/", {}, format="json").json()["url"].split("#mppos=")[1]
        r = APIClient().post(f"/api/v1/site-handoff/{code}/claim/", "{}", content_type="text/plain", HTTP_ORIGIN=SITE)
        self.assertEqual(r.status_code, 200, r.content.decode())
        return code

    def test_sending_waits_for_someone_marking_it_sent_by_hand(self):
        """有人剛手動標了已傳(他已經用 LINE 叫了)、還沒存完,另一個人在小幫手按送出:等他存完、看到已經傳了、不送。
        不先鎖叫貨單的話,這裡讀到的還是「還沒傳」,網站上就多一張訂單。"""
        code = self._claimed()
        self._meanwhile([
            ("SELECT 1 FROM vendor_orders_vendororder WHERE id = %s FOR UPDATE", [self.a["id"]]),
            ("UPDATE vendor_orders_vendororder SET sent_at = NOW(), sent_how = 'manual' WHERE id = %s", [self.a["id"]]),
        ])
        began = time.monotonic()
        r = APIClient().post(f"/api/v1/site-handoff/{code}/submitting/", json.dumps({"account": "77", "bind": True}),
                             content_type="text/plain", HTTP_ORIGIN=SITE)
        self.assertGreater(time.monotonic() - began, 0.5)
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "這張叫貨單已經傳給廠商了"))
        self.assertEqual(VendorHandoff.objects.get(order_id=self.a["id"]).state, State.CLAIMED)
        self.assertEqual(VendorLink.objects.get(provider="kcimos", warehouse=self.wh1).site_account, "")

    def test_marking_sent_by_hand_waits_for_one_being_sent(self):
        """反過來:小幫手正在說「要送了」(還沒存完),有人手動標已傳:等它存完、看到待確認、不給標。"""
        self._claimed()
        mine = VendorHandoff.objects.get(order_id=self.a["id"])
        self._meanwhile([
            ("SELECT 1 FROM vendor_orders_vendororder WHERE id = %s FOR UPDATE", [self.a["id"]]),
            ("UPDATE vendor_orders_vendorhandoff SET state = 'submitting', submitting_at = NOW() WHERE id = %s", [mine.pk]),
        ])
        began = time.monotonic()
        r = self.clerk.post(f"{ORDERS}{self.a['id']}/sent/", {"sent": True}, format="json")
        self.assertGreater(time.monotonic() - began, 0.5)
        self.assertEqual((r.status_code, r.json()["detail"]),
                         (400, "這張單上一次送出還不知道有沒有成立(待確認),請先選「訂單成立」或「沒有成立」"))
        self.assertIsNone(VendorOrder.objects.get(pk=self.a["id"]).sent_at)
