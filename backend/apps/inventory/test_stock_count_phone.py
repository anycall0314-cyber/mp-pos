"""手機走動盤點(owner 2026-10-15):QR Code 配對、不用登入;配件每刷一個 +1;沒對到的碼要處理好才能送出;
電腦存檔不能默默蓋掉手機加的。規則在 `stockcount_phone.py` 與 `stockcount.py`。全部是假資料。"""
import threading
import time
import uuid
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.backup.models import TenantMaintenance
from apps.backup.tests.factory import Company
from apps.catalog.models import Product
from apps.inventory import stockcount, stockcount_phone
from apps.inventory.models import StockBalance, StockCountLine, StockCountPhone, StockCountScan, StockCountTap, StockCountUnknown
from apps.inventory.test_locking import _Concurrent

URL = "/api/v1/stock-counts/"
PHONE = "/api/v1/count-phone/"
CASE_CODE = "T12SAMNOTE502"


class _Phone(TestCase):
    def setUp(self):
        c = self.c = Company("a", "甲通訊行", "甲")
        self.w1, self.w2 = c.warehouses
        c.purchase(phone_serials=["甲IMEI1", "甲IMEI2"], case_qty=10)
        Product.objects.filter(pk=c.case.pk).update(barcode=CASE_CODE)
        self.count = stockcount.open_count(c.tenant, self.w1, [], c.admin_user)

    def pair(self, label="小王", device="dev-1"):
        phone, token = stockcount_phone.start(self.count, self.c.clerk_user, label)
        stockcount_phone.session(token, device, claim=True)
        return phone, token, device

    def tap(self, phone, device, code, mode="accessory", op=None):
        return stockcount_phone.tap(StockCountPhone.objects.get(pk=phone.pk), device, code, mode, op or uuid.uuid4().hex)

    def pile(self, phone, device, n, op=None):
        return stockcount_phone.pile(StockCountPhone.objects.get(pk=phone.pk), device, n, op or uuid.uuid4().hex)

    def undo(self, phone, device, op=None):
        return stockcount_phone.undo(StockCountPhone.objects.get(pk=phone.pk), device, op or uuid.uuid4().hex)

    def line_qty(self, product=None):
        return StockCountLine.objects.filter(count=self.count, product=product or self.c.case).values_list("counted_qty", flat=True).first()


class PairTests(_Phone):
    def test_a_qr_code_needs_a_name_binds_the_first_phone_and_expires(self):
        with self.assertRaisesMessage(stockcount_phone.PhoneError, "請寫這支手機是誰在用"):
            stockcount_phone.start(self.count, self.c.clerk_user, "  ")
        phone, token = stockcount_phone.start(self.count, self.c.clerk_user, "小王")
        with self.assertRaisesMessage(stockcount_phone.PhoneError, "請重新掃描 QR Code"):
            stockcount_phone.session(token, "dev-1")                      # 還沒掃(claim)的不認
        stockcount_phone.session(token, "dev-1", claim=True)
        stockcount_phone.session(token, "dev-1")
        with self.assertRaises(stockcount_phone.PhoneError) as e:
            stockcount_phone.session(token, "dev-2", claim=True)            # 第二支手機接不走
        self.assertEqual(e.exception.code, "taken")
        late, late_token = stockcount_phone.start(self.count, self.c.clerk_user, "小李")
        StockCountPhone.objects.filter(pk=late.pk).update(pair_expires_at=timezone.now() - timedelta(seconds=1))
        with self.assertRaisesMessage(stockcount_phone.PhoneError, "QR Code 過期了"):
            stockcount_phone.session(late_token, "dev-3", claim=True)

    def test_ending_submitting_or_idling_stops_the_phone(self):
        phone, token, device = self.pair()
        StockCountPhone.objects.filter(pk=phone.pk).update(device_active_at=timezone.now() - timedelta(minutes=31))
        with self.assertRaisesMessage(stockcount_phone.PhoneError, "太久沒有刷,已經結束"):
            stockcount_phone.session(token, device)
        phone, token, device = self.pair("小李", "dev-2")
        stockcount_phone.end(self.count, phone.pk)
        with self.assertRaises(stockcount_phone.PhoneError) as e:
            stockcount_phone.session(token, device)
        self.assertEqual(e.exception.code, "gone")
        phone, token, device = self.pair("小張", "dev-3")
        self.tap(phone, device, CASE_CODE)
        stockcount.submit(self.count, self.c.admin_user)
        with self.assertRaisesMessage(stockcount_phone.PhoneError, "這支手機的盤點已經結束"):     # 送出時手機一律結束(複審 P1)
            stockcount_phone.session(token, device)

    def test_a_phone_that_was_ended_between_its_check_and_its_tap_cannot_write(self):
        phone, token, device = self.pair()
        fresh = stockcount_phone.session(token, device)
        stockcount_phone.end(self.count, phone.pk)
        with self.assertRaisesMessage(stockcount_phone.PhoneError, "這支手機的盤點已經結束"):
            stockcount_phone.tap(fresh, device, CASE_CODE, "accessory", uuid.uuid4().hex)
        self.assertIsNone(self.line_qty())

    def test_at_most_ten_phones_at_once(self):
        for i in range(stockcount_phone.MAX_ACTIVE):
            stockcount_phone.start(self.count, self.c.clerk_user, f"人{i}")
        with self.assertRaisesMessage(stockcount_phone.PhoneError, "一張盤點單同時最多 10 支手機"):
            stockcount_phone.start(self.count, self.c.clerk_user, "多一個")

    def test_a_phone_that_stops_checking_in_shows_as_lost_and_comes_back_when_it_does(self):
        """全站檢視 V06b(紅隊):電腦上「已配對 N 台」只算現在真的還連著的。手機那一頁每 10 秒回報一次,
        30 秒沒回報 = 斷線(關掉了、沒網路);回報了就回來,照樣能刷。斷線的還佔一個名額(回來還能用)。"""
        phone, token, device = self.pair()
        status = lambda: stockcount_phone.status_of(StockCountPhone.objects.get(pk=phone.pk))
        self.assertEqual(status(), "connected")
        StockCountPhone.objects.filter(pk=phone.pk).update(seen_at=timezone.now() - timedelta(seconds=31))
        self.assertEqual(status(), "lost")
        r = self.c.clerk.get(f"{URL}{self.count.id}/")
        self.assertEqual([(p["label"], p["status"]) for p in r.json()["phones"]], [("小王", "lost")])
        stockcount_phone.session(token, device)                            # 那一頁回報(看狀態)
        self.assertEqual(status(), "connected")
        StockCountPhone.objects.filter(pk=phone.pk).update(seen_at=timezone.now() - timedelta(seconds=31))
        self.tap(phone, device, CASE_CODE)                                 # 斷線的手機回來直接刷:記得到,也算回來了
        self.assertEqual((self.line_qty(), status()), (1, "connected"))
        StockCountPhone.objects.filter(pk=phone.pk).update(seen_at=timezone.now() - timedelta(seconds=31))
        for i in range(stockcount_phone.MAX_ACTIVE - 1):
            stockcount_phone.start(self.count, self.c.clerk_user, f"人{i}")
        with self.assertRaisesMessage(stockcount_phone.PhoneError, "一張盤點單同時最多 10 支手機"):
            stockcount_phone.start(self.count, self.c.clerk_user, "多一個")


class TapTests(_Phone):
    def test_each_scan_of_an_accessory_adds_one_and_phones_add_up(self):
        a, _, da = self.pair("小王", "dev-1")
        b, _, db = self.pair("小李", "dev-2")
        self.tap(a, da, CASE_CODE)
        self.tap(a, da, CASE_CODE.lower().upper())
        self.tap(b, db, self.c.case.sku.lower())                       # 品號也算(大小寫不算)
        self.assertEqual(self.line_qty(), 3)
        line = StockCountLine.objects.get(count=self.count, product=self.c.case)
        self.assertEqual((line.book_qty, line.counted_by, line.replaced_at), (10, self.c.clerk_user, None))
        taps = list(StockCountTap.objects.filter(count=self.count).values_list("label", "kind", "before", "after"))
        self.assertEqual(taps, [("小王", "line", None, 1), ("小王", "line", 1, 2), ("小李", "line", 2, 3)])

    def test_a_device_code_is_recorded_as_that_phone_whatever_the_mode(self):
        a, _, da = self.pair()
        t = self.tap(a, da, "甲IMEI1", mode="accessory")
        self.assertEqual((t.kind, t.scan.serial.serial_no), ("scan", "甲IMEI1"))
        with self.assertRaisesMessage(stockcount_phone.PhoneError, "這個碼刷過了"):
            self.tap(a, da, "甲IMEI1", mode="phone")

    def test_an_unknown_code_is_kept_as_unmatched_in_accessory_mode_and_as_a_phone_in_phone_mode(self):
        a, _, da = self.pair()
        self.tap(a, da, "ZZ-0001")
        self.tap(a, da, "zz0001")                                       # 同一個碼(寫法不同)算同一筆
        row = StockCountUnknown.objects.get(count=self.count)
        self.assertEqual((row.code, row.times, row.last_label), ("ZZ-0001", 2, "小王"))
        t = self.tap(a, da, "356000000000999", mode="phone")
        self.assertEqual((t.kind, t.scan.serial_id, t.scan.code), ("scan", None, "356000000000999"))

    def test_the_phone_sees_totals_but_never_the_book(self):
        a, token, da = self.pair()
        self.tap(a, da, CASE_CODE)
        view = stockcount_phone.phone_view(StockCountPhone.objects.get(pk=a.pk))
        self.assertEqual((view["label"], view["taps"][0]["name"], view["taps"][0]["total"]), ("小王", self.c.case.name, 1))
        self.assertNotIn("book", str(view))

    def test_a_restore_in_progress_stops_the_phone(self):
        a, token, da = self.pair()
        TenantMaintenance.objects.create(tenant=self.c.tenant, active=True, reason="restore")
        r = self.client.post(f"{PHONE}tap/", {"code": CASE_CODE, "mode": "accessory", "op": uuid.uuid4().hex}, content_type="application/json",
                             HTTP_X_PAIR_TOKEN=token, HTTP_X_PAIR_DEVICE=da)
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "公司資料還原中,暫時不能刷,請稍後再試"))
        self.assertIsNone(self.line_qty())


class PileAndUndoTests(_Phone):
    def test_a_pile_turns_the_last_plus_one_into_plus_n_even_while_others_add(self):
        a, _, da = self.pair("小王", "dev-1")
        b, _, db = self.pair("小李", "dev-2")
        self.tap(a, da, CASE_CODE)
        self.tap(b, db, CASE_CODE)                                      # 別支手機也在加:不擋
        self.pile(a, da, 12)
        self.assertEqual(self.line_qty(), 13)
        self.pile(a, da, 5)   # 再改:那一下從 +12 變 +5
        self.assertEqual(self.line_qty(), 6)
        with self.assertRaisesMessage(stockcount_phone.PhoneError, "要是 1 到 9999 的整數"):
            self.pile(a, da, 0)

    def test_undo_takes_back_only_that_one(self):
        a, _, da = self.pair("小王", "dev-1")
        b, _, db = self.pair("小李", "dev-2")
        self.tap(a, da, CASE_CODE)
        self.tap(b, db, CASE_CODE)
        self.undo(a, da)
        self.assertEqual(self.line_qty(), 1, "小李那一下還在")
        self.undo(b, db)
        self.assertIsNone(self.line_qty(), "手機建出來的那一列減到 0 = 回到沒盤,不是數到 0")
        with self.assertRaisesMessage(stockcount_phone.PhoneError, "沒有可以收回的"):
            self.undo(a, da)

    def test_undo_of_a_phone_and_of_an_unmatched_code(self):
        a, _, da = self.pair()
        self.tap(a, da, "甲IMEI1")
        self.tap(a, da, "ZZ-0001")
        self.tap(a, da, "ZZ-0001")
        self.undo(a, da)
        self.assertEqual(StockCountUnknown.objects.get(count=self.count).times, 1)
        self.undo(a, da)
        self.assertFalse(StockCountUnknown.objects.filter(count=self.count).exists())
        self.undo(a, da)
        self.assertFalse(StockCountScan.objects.filter(count=self.count).exists())

    def test_after_the_desktop_replaced_the_number_the_phone_cannot_take_back_or_pile(self):
        a, _, da = self.pair()
        self.tap(a, da, CASE_CODE)
        stockcount.set_line(self.count, self.c.case, 7, self.c.clerk_user, seen=1)
        with self.assertRaisesMessage(stockcount_phone.PhoneError, "電腦之後改過數字,請到電腦上改"):
            self.undo(a, da)
        with self.assertRaisesMessage(stockcount_phone.PhoneError, "電腦之後改過數字,請到電腦上改"):
            self.pile(a, da, 3)
        self.assertEqual(self.line_qty(), 7)
        self.tap(a, da, CASE_CODE)                                      # 換掉之後再刷的,照常 +1、也收得回來
        self.undo(a, da)
        self.assertEqual(self.line_qty(), 7)


class ReviewRoundOneTests(_Phone):
    def test_an_old_tap_cannot_take_back_a_line_that_was_removed_and_counted_again(self):
        # 複審 P0:甲 +1 → 電腦移除那一列 → 乙重新刷兩下 → 甲收回,不能把乙的 2 扣成 1
        a, _, da = self.pair("小王", "dev-1")
        b, _, db = self.pair("小李", "dev-2")
        self.tap(a, da, CASE_CODE)
        line = StockCountLine.objects.get(count=self.count, product=self.c.case)
        stockcount.remove_line(self.count, line.pk)
        self.tap(b, db, CASE_CODE)
        self.tap(b, db, CASE_CODE)
        with self.assertRaisesMessage(stockcount_phone.PhoneError, "電腦之後改過數字,請到電腦上改"):
            self.undo(a, da)
        self.assertEqual(self.line_qty(), 2)

    def test_the_same_action_sent_twice_is_done_once(self):
        # 複審 P0:刷了、伺服器記了、回應在路上斷線,手機用同一個編號重送 → 不能多 +1;「這一堆」「收回」也一樣
        a, _, da = self.pair()
        self.assertIsNotNone(self.tap(a, da, CASE_CODE, op="op-tap-0001"))
        self.assertIsNone(self.tap(a, da, CASE_CODE, op="op-tap-0001"))
        self.assertEqual(self.line_qty(), 1)
        self.pile(a, da, 10, op="op-pile-001")
        self.pile(a, da, 10, op="op-pile-001")
        self.assertEqual(self.line_qty(), 10)
        self.tap(a, da, CASE_CODE, op="op-tap-0002")
        self.undo(a, da, op="op-undo-001")
        self.undo(a, da, op="op-undo-001")                 # 重送:不能連前一下一起收掉
        self.assertEqual(self.line_qty(), 10)
        with self.assertRaisesMessage(stockcount_phone.PhoneError, "請重新整理這一頁再刷"):
            self.tap(a, da, CASE_CODE, op="x")
        other, _, do = self.pair("小李", "dev-2")
        self.assertIsNotNone(self.tap(other, do, CASE_CODE, op="op-tap-0001"), "別支手機用到一樣的編號不受影響")

    def test_undo_and_pile_only_act_on_the_tap_the_phone_was_looking_at(self):
        # 複審第二輪 P0:刷 A → 按收回(沒送到)→ 刷 B → 重送收回:不能收到 B
        a, _, da = self.pair()
        first = self.tap(a, da, CASE_CODE)
        self.tap(a, da, "甲IMEI1")
        phone = StockCountPhone.objects.get(pk=a.pk)
        with self.assertRaisesMessage(stockcount_phone.PhoneError, "最後一下已經不是那一下了,請看清單再按"):
            stockcount_phone.undo(phone, da, uuid.uuid4().hex, target=first.pk)
        with self.assertRaisesMessage(stockcount_phone.PhoneError, "最後一下已經不是那一下了,請看清單再按"):
            stockcount_phone.pile(phone, da, 5, uuid.uuid4().hex, target=first.pk)
        self.assertEqual((self.line_qty(), StockCountScan.objects.filter(count=self.count).count()), (1, 1), "兩下都還在")
        last = StockCountTap.objects.filter(count=self.count).order_by("-id").first()
        stockcount_phone.undo(phone, da, uuid.uuid4().hex, target=last.pk)
        self.assertFalse(StockCountScan.objects.filter(count=self.count).exists())

    def test_a_returned_count_does_not_bring_old_phones_back(self):
        # 複審 P1:送出 → 管理員退回重盤 → 舊的 QR Code 不能再寫
        a, token, da = self.pair()
        self.tap(a, da, CASE_CODE)
        stockcount.submit(self.count, self.c.admin_user)
        stockcount.give_back(self.count)
        with self.assertRaises(stockcount_phone.PhoneError) as e:
            stockcount_phone.session(token, da)
        self.assertEqual(e.exception.code, "gone")
        self.count.refresh_from_db()
        phone, token2 = stockcount_phone.start(self.count, self.c.clerk_user, "小王")
        stockcount_phone.session(token2, "dev-9", claim=True)          # 重新發的照常可以用
        stockcount.void(self.count, by_manager=True)
        self.assertTrue(all(p.ended_at for p in StockCountPhone.objects.filter(count=self.count)))


class DesktopTests(_Phone):
    def test_the_desktop_cannot_silently_overwrite_what_phones_added(self):
        a, _, da = self.pair()
        self.tap(a, da, CASE_CODE)
        self.tap(a, da, CASE_CODE)
        with self.assertRaisesMessage(stockcount.CountError, f"「{self.c.case.name}」剛剛有人改過,現在是 2 個,再確認一次"):
            stockcount.set_line(self.count, self.c.case, 5, self.c.clerk_user, seen=None)
        with self.assertRaisesMessage(stockcount.CountError, "現在是 2 個"):
            stockcount.set_line(self.count, self.c.case, 5, self.c.clerk_user, seen=1)
        stockcount.set_line(self.count, self.c.case, 5, self.c.clerk_user, seen=2)
        self.assertEqual(self.line_qty(), 5)
        r = self.c.clerk.post(f"{URL}{self.count.id}/lines/", {"product": self.c.case.id, "counted_qty": 6, "seen": 4}, format="json")
        self.assertEqual((r.status_code, r.json()["detail"]), (400, f"「{self.c.case.name}」剛剛有人改過,現在是 5 個,再確認一次"))

    def test_unmatched_codes_block_submitting_until_each_is_matched_or_left_out(self):
        a, _, da = self.pair()
        for _ in range(3):
            self.tap(a, da, "ZZ-0001")
        self.tap(a, da, "ZZ-0002")
        with self.assertRaisesMessage(stockcount.CountError, "還有 2 個沒對到的碼,先指定配件或寫原因不入,才能送出"):
            stockcount.submit(self.count, self.c.admin_user)
        one, two = StockCountUnknown.objects.filter(count=self.count).order_by("id")
        stockcount.resolve_unknown(self.count, one.pk, self.c.clerk_user, product=self.c.case)
        self.assertEqual(self.line_qty(), 3, "刷了幾次就加幾個")
        with self.assertRaisesMessage(stockcount.CountError, "不入要寫原因"):
            stockcount.resolve_unknown(self.count, two.pk, self.c.clerk_user, reason=" ")
        stockcount.resolve_unknown(self.count, two.pk, self.c.clerk_user, reason="樣品")
        with self.assertRaisesMessage(stockcount_phone.PhoneError, "ZZ-0001 已經在電腦上處理過了"):
            self.tap(a, da, "ZZ-0001")
        stockcount.submit(self.count, self.c.admin_user)

    def test_the_api_gives_a_qr_once_lists_phones_and_ends_them(self):
        r = self.c.clerk.post(f"{URL}{self.count.id}/phones/", {"label": "小王"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        body = r.json()
        token = body["pair"]["token"]
        self.assertEqual([(p["label"], p["status"]) for p in body["phones"]], [("小王", "waiting")])
        self.assertNotIn("token", str(self.c.clerk.get(f"{URL}{self.count.id}/").json()))
        r = self.client.generic("POST", f"{PHONE}claim/", HTTP_X_PAIR_TOKEN=token, HTTP_X_PAIR_DEVICE="d1")   # 沒有內容、沒有內容類型
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIn("no-cache", r["Cache-Control"])
        r = self.client.post(f"{PHONE}tap/", {"code": CASE_CODE, "mode": "accessory", "op": uuid.uuid4().hex}, content_type="application/json",
                             HTTP_X_PAIR_TOKEN=token, HTTP_X_PAIR_DEVICE="d1")
        self.assertEqual((r.status_code, r.json()["taps"][0]["total"]), (200, 1))
        detail = self.c.clerk.get(f"{URL}{self.count.id}/").json()
        self.assertEqual([(x["product"]["id"], x["counted_qty"]) for x in detail["line_rows"]], [(self.c.case.id, 1)])
        self.c.clerk.delete(f"{URL}{self.count.id}/phones/{body['pair']['id']}/")
        r = self.client.get(f"{PHONE}state/", HTTP_X_PAIR_TOKEN=token, HTTP_X_PAIR_DEVICE="d1")
        self.assertEqual((r.status_code, r.json()["code"]), (410, "gone"))
        other = Company("b", "乙通訊行", "乙")
        r = other.clerk.post(f"{URL}{self.count.id}/phones/", {"label": "外人"}, format="json")
        self.assertEqual(r.status_code, 404)

    def test_resolving_through_the_api(self):
        a, _, da = self.pair()
        self.tap(a, da, "ZZ-0001")
        row = StockCountUnknown.objects.get(count=self.count)
        r = self.c.clerk.post(f"{URL}{self.count.id}/unknowns/{row.pk}/", {"product": self.c.case.id}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual([(u["code"], u["resolved"], u["product"]["id"]) for u in r.json()["unknown_rows"]], [("ZZ-0001", True, self.c.case.id)])


class TwoPhonesTests(_Concurrent):
    def test_checking_a_phone_does_not_wait_for_the_count(self):
        """複審 P1:手機看狀態時只能鎖配對那一列。連帶鎖到盤點單的話,刷碼那邊是「先盤點單、後配對」,兩邊會互等卡死。
        這裡另一條連線握著盤點單那一列,看狀態不能被它卡住。"""
        c = self.c
        count = stockcount.open_count(c.tenant, self.w1, [], c.admin_user)
        phone, token = stockcount_phone.start(count, c.clerk_user, "小王")
        stockcount_phone.session(token, "dev-1", claim=True)
        t = self.meanwhile([("SELECT 1 FROM inventory_stockcount WHERE id = %s FOR UPDATE", [count.pk])], hold=2.0)
        started = time.monotonic()
        stockcount_phone.session(token, "dev-1")
        self.assertLess(time.monotonic() - started, 1.0)
        t.join()

    def test_two_phones_adding_at_the_same_moment_are_both_counted(self):
        """別支手機正好在加同一個配件(握著那個商品在這家門市的餘額列):要等它加完、在它加好的數字上再加一。
        不先鎖餘額列就讀那一列的話,兩邊都從 1 加到 2,少算一個。"""
        c = self.c
        Product.objects.filter(pk=c.case.pk).update(barcode=CASE_CODE)
        count = stockcount.open_count(c.tenant, self.w1, [], c.admin_user)
        phone, token = stockcount_phone.start(count, c.clerk_user, "小王")
        stockcount_phone.session(token, "dev-1", claim=True)
        stockcount_phone.tap(StockCountPhone.objects.get(pk=phone.pk), "dev-1", CASE_CODE, "accessory", uuid.uuid4().hex)
        line = StockCountLine.objects.get(count=count, product=c.case)
        balance = StockBalance.objects.get(tenant=c.tenant, product=c.case, warehouse=self.w1)
        t = self.meanwhile([
            ("SELECT 1 FROM inventory_stockbalance WHERE id = %s FOR NO KEY UPDATE", [balance.pk]),
            ("UPDATE inventory_stockcountline SET counted_qty = counted_qty + 1 WHERE id = %s", [line.pk]),
        ])
        stockcount_phone.tap(StockCountPhone.objects.get(pk=phone.pk), "dev-1", CASE_CODE, "accessory", uuid.uuid4().hex)
        t.join()
        line.refresh_from_db()
        self.assertEqual(line.counted_qty, 3)
