"""發票字軌分門市、跳號(owner 2026-10-13)。

owner:「發票機我現在用WP-103，你的設計不但要可以設定發票字軌，設定完後，用若干時間發生突發狀況，
還要可以設定跳號指定幾號開始印製（有可能故障）」

三聯式收銀機發票是號碼已經印在紙上的整捲紙,每間門市的發票機各有一捲:系統開出去的號碼要跟紙上的一樣。
- 開單只取自己門市的字軌(與分門市之前建的、全公司共用的舊字軌);別間門市的不拿。
- 跳號 = 把「下一張」改成紙上的下一張,每一次留紀錄;新的下一張與它後面的號碼只要有一張開過就不准(會重複)。
- 「下一張」不能再直接改;開過發票的字軌不能刪、不能改字軌與起號;兩條字軌的號碼不能重疊。
- 新增 / 修改 / 刪除 / 跳號要有「發票字軌」那一項權限;鎖在門市的帳號只管得到自己門市的。

owner 同一天:「發票字軌設定不但有指定年月與字軌數字，跳月如未設定新的符合年月與字軌，則自動提示」
- 字軌登記是哪一期的(兩個月一期);開單只取發票日期那一期的。換期了沒設定:講是哪一期還沒設定;最後 7 天先提醒。
"""
import threading
import time
from datetime import date, timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.db import connections
from django.test import SimpleTestCase, TestCase, TransactionTestCase

from apps.backup.tests.factory import Company
from apps.sales.models import SalesOrder

from . import invoice_periods, services
from .models import InvoiceTrack, InvoiceTrackJump, InvoiceType, UserProfile

TRACKS = "/api/v1/invoice-tracks/"
# 銷貨單的發票日期一律是今天(伺服器定的):字軌的期別照今天排
THIS = invoice_periods.start_of(date.today())
LAST = invoice_periods.start_of(THIS - timedelta(days=1))
NEXT = invoice_periods.next_start(THIS)
THIS_NAME = invoice_periods.label(THIS)


def setup_shop(case):
    """兩間門市各一條這一期的「電子三聯式」字軌:湳雅店 AB 100 ~ 149、民生店 CD 200 ~ 249。工廠附的那一條共用字軌是「免用」的,不相干。"""
    c = case.c = Company("a", "甲通訊行", "甲")
    case.w1, case.w2 = c.warehouses
    c.purchase(case_qty=40)
    c.purchase(warehouse=case.w2, case_qty=40)
    case.tri = InvoiceType.objects.create(tenant=c.tenant, code="ev_tri", name="電子三聯式")
    case.t1 = new_track(case, case.w1, "AB", 100, 149)
    case.t2 = new_track(case, case.w2, "CD", 200, 249)


def new_track(case, warehouse, prefix, start, end, **more):
    return InvoiceTrack.objects.create(
        tenant=case.c.tenant, invoice_type=case.tri, warehouse=warehouse, prefix=prefix,
        range_start=start, range_end=end, **{"next_number": start, "period_start": THIS, **more})


class _Shop(TestCase):
    def setUp(self):
        setup_shop(self)

    def sell(self, warehouse=None, invoice_no="", invoice_form="ev_tri", client=None, expect=201):
        r = (client or self.c.admin).post("/api/v1/sales-orders/", {
            "customer": self.c.customer.id, "warehouse": (warehouse or self.w1).id, "tax_method": "untaxed",
            "sales_person": self.c.sales_person.id, "invoice_form": invoice_form, "invoice_no": invoice_no,
            "items": [{"product": self.c.case.id, "qty": 1, "unit_price": "390"}],
            "payments": [{"method": "cash", "amount": "390"}],
        }, format="json")
        self.assertEqual(r.status_code, expect, r.content.decode())
        return r.json()

    def jump(self, track, number, reason="", client=None, expect=200):
        r = (client or self.c.admin).post(
            f"{TRACKS}{track.id}/jump/", {"next_number": number, "reason": reason}, format="json")
        self.assertEqual(r.status_code, expect, r.content.decode())
        return r.json()

    def next_of(self, track):
        return InvoiceTrack.objects.get(pk=track.pk).next_number

    def peek(self, client=None, **params):
        r = (client or self.c.admin).get(f"{TRACKS}peek/", {"invoice_type_code": "ev_tri", **params})
        self.assertEqual(r.status_code, 200, r.content.decode())
        return r.json()


class PickTests(_Shop):
    def test_each_store_takes_numbers_from_its_own_track(self):
        self.assertEqual(self.sell(self.w1)["invoice_no"], "AB00000100")
        self.assertEqual(self.sell(self.w2)["invoice_no"], "CD00000200")
        self.assertEqual(self.sell(self.w1)["invoice_no"], "AB00000101")
        self.assertEqual((self.next_of(self.t1), self.next_of(self.t2)), (102, 201))

    def test_a_store_never_takes_another_stores_numbers(self):
        """民生店自己的字軌停用了:結帳被擋、講得出原因,湳雅店那一捲的號碼一張都不會動。"""
        InvoiceTrack.objects.filter(pk=self.t2.pk).update(is_active=False)
        body = self.sell(self.w2, expect=400)
        self.assertIn(f"電子三聯式:{THIS_NAME} 的字軌還沒設定,請到系統設定新增字軌", str(body))
        self.assertEqual(self.next_of(self.t1), 100)
        self.assertEqual(self.peek(warehouse=self.w2.id), {
            "next_invoice_no": None, "track": None, "upcoming": "", "detail": f"{THIS_NAME} 的字軌還沒設定"})

    def test_own_track_first_then_the_shared_one(self):
        """共用的舊字軌(沒有門市)比較早建,自己門市的還是先用;自己的用完才輪到共用的。"""
        shared = new_track(self, None, "EF", 300, 349)
        mine = new_track(self, self.w2, "GH", 400, 400)
        InvoiceTrack.objects.filter(pk=self.t2.pk).update(is_active=False)
        self.assertLess(shared.id, mine.id)
        self.assertEqual(self.peek(warehouse=self.w2.id)["next_invoice_no"], "GH00000400")
        self.assertEqual(self.sell(self.w2)["invoice_no"], "GH00000400")
        self.assertEqual(self.peek(warehouse=self.w2.id)["track"]["id"], shared.id)       # 自己的用完了
        self.assertEqual(self.sell(self.w2)["invoice_no"], "EF00000300")
        self.assertEqual(self.sell(self.w1)["invoice_no"], "AB00000100")                  # 湳雅店自己的還有,不碰共用的
        self.assertEqual(self.next_of(shared), 301)

    def test_peek_tells_the_number_and_which_track_for_that_store(self):
        got = self.peek(warehouse=self.w2.id)
        self.assertEqual((got["next_invoice_no"], got["track"]["id"], got["track"]["warehouse_name"]),
                         ("CD00000200", self.t2.id, self.w2.name))
        self.assertIsNone(self.peek()["next_invoice_no"])            # 沒講門市:只有共用的可以看,這裡沒有
        # 鎖在湳雅店的店員:不管網址帶哪一間,看到的都是自己門市的
        self.assertEqual(self.peek(self.c.clerk, warehouse=self.w2.id)["next_invoice_no"], "AB00000100")
        self.assertEqual(self.next_of(self.t1), 100)                 # 預覽不取號


class JumpTests(_Shop):
    def test_jump_forward_leaves_a_record_and_the_next_sale_starts_there(self):
        self.assertEqual(self.sell()["invoice_no"], "AB00000100")
        body = self.jump(self.t1, 105, "卡紙", client=self.c.clerk)
        self.assertEqual((body["next_number"], body["next_invoice_no"]), (105, "AB00000105"))
        log = self.c.admin.get(f"{TRACKS}{self.t1.id}/jumps/").json()
        self.assertEqual(len(log), 1)
        self.assertEqual(
            {k: log[0][k] for k in ("from_number", "to_number", "from_no", "to_no", "reason", "by")},
            {"from_number": 101, "to_number": 105, "from_no": "AB00000101", "to_no": "AB00000105",
             "reason": "卡紙", "by": self.c.clerk_user.username})
        self.assertEqual(self.sell()["invoice_no"], "AB00000105")
        self.assertEqual(self.next_of(self.t2), 200)                 # 別條字軌不動

    def test_number_may_come_as_text_from_the_form(self):
        self.assertEqual(self.jump(self.t1, "00000107")["next_number"], 107)

    def test_jump_back_is_allowed_only_while_nothing_was_issued_from_there_on(self):
        self.jump(self.t1, 110)
        self.jump(self.t1, 103, "打錯")                               # 跳太多、還沒開過:改回來
        self.assertEqual(self.sell()["invoice_no"], "AB00000103")
        so = SalesOrder.objects.get(invoice_no="AB00000103")
        for target in (103, 101, 100):                               # 103 開過了:它與它前面都不能當下一張
            body = self.jump(self.t1, target, expect=400)
            self.assertEqual(body["detail"], f"AB00000103 已經開給銷貨單 {so.no},下一張不能排在它前面")
        self.assertEqual(self.next_of(self.t1), 104)
        self.assertEqual(InvoiceTrackJump.objects.filter(track=self.t1).count(), 2)

    def test_a_voided_sale_still_holds_its_number(self):
        so = self.sell()
        r = self.c.admin.post(f"/api/v1/sales-orders/{so['id']}/void/", {"reason": "打錯"}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.jump(self.t1, 110)
        self.assertIn("AB00000100 已經開給銷貨單", self.jump(self.t1, 100, expect=400)["detail"])
        self.assertEqual(self.next_of(self.t1), 110)

    def test_a_number_typed_by_hand_on_a_sale_counts_too(self):
        """自己打號碼的銷貨單(大小寫不同也認)也算開過:往後跳也不能跳到它前面。"""
        so = self.sell(invoice_no="ab00000120")
        # 這條字軌系統沒開過號、也沒跳過號,但單上有它的號碼:算用過,不能刪
        self.assertEqual(self.c.admin.delete(f"{TRACKS}{self.t1.id}/").status_code, 400)
        body = self.jump(self.t1, 115, expect=400)
        self.assertEqual(body["detail"], f"AB00000120 已經開給銷貨單 {so['no']},下一張不能排在它前面")
        self.assertEqual(self.jump(self.t1, 121)["next_number"], 121)
        # 別家公司剛好有同一個號碼:不相干
        other = Company("b", "乙通訊行", "乙")
        other.purchase(case_qty=5)
        r = other.admin.post("/api/v1/sales-orders/", {
            "customer": other.customer.id, "warehouse": other.wh.id, "tax_method": "untaxed",
            "sales_person": other.sales_person.id, "invoice_form": "none", "invoice_no": "AB00000140",
            "items": [{"product": other.case.id, "qty": 1, "unit_price": "390"}],
            "payments": [{"method": "cash", "amount": "390"}]}, format="json")
        self.assertEqual(r.status_code, 201, r.content.decode())
        # 長得不像這條字軌號碼的不算(位數不對、不是數字、別的字軌)
        for odd in ("AB0000013", "AB0000013X", "AC00000130", "AB000000130"):
            self.sell(invoice_no=odd)
        self.assertEqual(self.jump(self.t1, 125)["next_number"], 125)

    def test_outside_the_roll_the_same_number_or_not_a_number_changes_nothing(self):
        cases = [
            (99, "下一張要在 AB00000100 ~ AB00000149 之間"),
            (151, "下一張要在 AB00000100 ~ AB00000149 之間"),
            (100, "下一張本來就是 AB00000100"),
            ("十", "下一張要填數字"), (None, "下一張要填數字"), (1.5, "下一張要填數字"), (True, "下一張要填數字"),
            (-3, "下一張要在 AB00000100 ~ AB00000149 之間"),
        ]
        for number, message in cases:
            self.assertEqual(self.jump(self.t1, number, expect=400)["detail"], message, number)
        self.assertEqual(self.next_of(self.t1), 100)
        self.assertFalse(InvoiceTrackJump.objects.exists())

    def test_jumping_past_the_last_number_retires_the_rest_of_the_roll(self):
        body = self.jump(self.t1, 150, "這一捲不用了")
        self.assertEqual((body["is_depleted"], body["next_invoice_no"]), (True, None))
        self.assertIn(f"{THIS_NAME} 的字軌用完了", str(self.sell(expect=400)))
        self.assertEqual(self.peek(warehouse=self.w1.id)["detail"], f"{THIS_NAME} 的字軌用完了")
        self.assertEqual(self.jump(self.t1, 149)["next_invoice_no"], "AB00000149")      # 還沒開過,改得回來

    def test_a_jump_by_someone_outside_the_company_does_not_show_their_account_name(self):
        """平台管理員代為操作:紀錄上只寫「平台管理員」,不把平台的帳號名稱給店家看(跟銷貨單「誰作廢的」同一個原則)。"""
        outsider = get_user_model().objects.create_user(username="platform-root", password="pw-12345")
        UserProfile.objects.create(user=outsider, role="platform_admin", tenant=None, is_warehouse_locked=False)
        services.jump_invoice_track(self.c.tenant, self.t1.pk, 104, user=outsider, reason="代為處理")
        services.jump_invoice_track(self.c.tenant, self.t1.pk, 106)                  # 沒有人(排程、指令):空的
        log = self.c.admin.get(f"{TRACKS}{self.t1.id}/jumps/").json()
        self.assertEqual([(j["to_no"], j["by"]) for j in log], [("AB00000106", ""), ("AB00000104", "平台管理員")])

    def test_a_number_the_system_issued_stays_used_even_if_its_sale_is_gone(self):
        """系統開出去過的號碼,那張銷貨單後來不在了(回到較早的備份:單沒了、紙已經用掉)也不能再跳回來開。
        往後跳錯、沒開過的那幾號照樣改得回來。"""
        self.sell()                                                   # AB00000100
        self.sell()                                                   # AB00000101
        SalesOrder.objects.filter(tenant=self.c.tenant).update(invoice_no="")       # 單上查不到這兩個號碼了
        for target in (101, 100):
            self.assertEqual(self.jump(self.t1, target, expect=400)["detail"], "AB00000101 已經開過,下一張不能排在它前面")
        self.assertEqual(self.next_of(self.t1), 102)
        # 沒有單、沒有跳過號,但開過:照樣算用過,不能刪
        self.assertEqual(self.c.admin.delete(f"{TRACKS}{self.t1.id}/").status_code, 400)
        self.jump(self.t1, 120)                                       # 往後跳錯了
        self.assertEqual(self.jump(self.t1, 102)["next_number"], 102)  # 那幾號沒開過:改得回來
        self.assertEqual(self.sell()["invoice_no"], "AB00000102")
        self.assertIn("AB00000102 已經開給銷貨單", self.jump(self.t1, 102, expect=400)["detail"])

    def test_reason_is_trimmed_and_cut_to_fit(self):
        self.jump(self.t1, 101, "  " + "卡" * 150 + "  ")
        self.assertEqual(InvoiceTrackJump.objects.get().reason, "卡" * 100)

    def test_other_company_and_other_store_cannot_reach_the_track(self):
        other = Company("b", "乙通訊行", "乙")
        self.jump(self.t1, 105, client=other.admin, expect=404)
        self.jump(self.t2, 205, client=self.c.clerk, expect=404)     # 湳雅店的店員碰不到民生店那一捲
        self.assertEqual(other.admin.get(f"{TRACKS}{self.t1.id}/jumps/").status_code, 404)
        self.assertEqual((self.next_of(self.t1), self.next_of(self.t2)), (100, 200))
        # 全公司共用的舊字軌:鎖在門市的店員也跳得了(他的發票機卡紙時要對得回來)
        shared = new_track(self, None, "EF", 300, 349)
        self.assertEqual(self.jump(shared, 303, client=self.c.clerk)["next_number"], 303)


class EditTests(_Shop):
    def patch(self, track, body, client=None, expect=200):
        r = (client or self.c.admin).patch(f"{TRACKS}{track.id}/", body, format="json")
        self.assertEqual(r.status_code, expect, r.content.decode())
        return r.json()

    def create(self, client=None, expect=201, **body):
        body = {"invoice_type": self.tri.id, "prefix": "KK", "range_start": 500, "range_end": 549,
                "period_start": THIS.isoformat(), **body}
        r = (client or self.c.admin).post(TRACKS, body, format="json")
        self.assertEqual(r.status_code, expect, r.content.decode())
        return r.json()

    def test_next_number_can_only_be_changed_by_jumping(self):
        self.assertEqual(self.patch(self.t1, {"next_number": 120}, expect=400),
                         {"next_number": ["下一張不能直接改,請用「跳號」"]})
        self.assertEqual(self.next_of(self.t1), 100)
        # 畫面把整筆送回來(下一張沒變):照收,下一張不動
        self.assertEqual(self.patch(self.t1, {"next_number": 100, "note": "櫃檯"})["note"], "櫃檯")
        self.assertEqual(self.next_of(self.t1), 100)

    def test_a_new_track_needs_a_store_and_a_period_and_starts_at_its_first_number(self):
        self.assertEqual(self.create(expect=400), {"warehouse": ["請選門市"]})
        self.assertEqual(self.create(warehouse=None, expect=400), {"warehouse": ["請選門市"]})
        self.assertEqual(self.create(warehouse=self.w2.id, period_start=None, expect=400), {"period_start": ["請選期別"]})
        for odd in ("2026-10-01", "2026-11-02"):             # 一期從奇數月 1 日開始
            self.assertEqual(self.create(warehouse=self.w2.id, period_start=odd, expect=400),
                             {"period_start": ["期別是兩個月一期,從奇數月 1 日開始"]})
        made = self.create(warehouse=self.w2.id, prefix=" kk ", period_label="亂打的")
        self.assertEqual((made["prefix"], made["next_number"], made["warehouse_name"]), ("KK", 500, self.w2.name))
        # 期別的字由系統照期別填(不收人打的);跟今天比是這一期
        self.assertEqual((made["period_start"], made["period_label"], made["period_state"]),
                         (THIS.isoformat(), THIS_NAME, "now"))
        # 那一捲已經用掉幾張:新增時可以直接填下一張
        half = self.create(warehouse=self.w1.id, prefix="LL", next_number=520)
        self.assertEqual(half["next_invoice_no"], "LL00000520")
        self.assertIn("next_number", self.create(warehouse=self.w1.id, prefix="MM", next_number=551, expect=400))
        self.assertIn("range_end", self.create(warehouse=self.w1.id, prefix="MM", range_end=499, expect=400))
        self.assertIn("range_end", self.create(warehouse=self.w1.id, prefix="MM", range_end=100000000, expect=400))

    def test_two_tracks_may_not_share_numbers(self):
        """同一捲紙登記兩次(兩間門市各登一條),兩邊會開出同一個號碼。"""
        for start, end in ((140, 180), (90, 100), (110, 120), (50, 300)):
            body = self.create(warehouse=self.w2.id, prefix="ab", range_start=start, range_end=end, expect=400)
            self.assertEqual(body, {"range_start": ["號碼跟另一條字軌重疊:AB00000100 ~ AB00000149"]}, (start, end))
        self.create(warehouse=self.w2.id, prefix="AB", range_start=150, range_end=199)     # 接在後面的不算
        self.create(warehouse=self.w2.id, prefix="ZZ", range_start=100, range_end=149)     # 字軌不同的不算
        # 改迄號改到撞上別條也不行;改自己原本的範圍不會跟自己撞
        self.assertIn("重疊", str(self.patch(self.t1, {"range_end": 150}, expect=400)))
        self.assertEqual(self.patch(self.t1, {"range_end": 149, "period_label": "115年9-10月"})["range_end"], 149)

    def test_a_track_that_issued_or_jumped_cannot_be_deleted_or_renamed(self):
        self.sell()                      # AB00000100
        self.jump(self.t2, 203)          # 民生店那一條只跳過號、沒開過
        for track in (self.t1, self.t2):
            r = self.c.admin.delete(f"{TRACKS}{track.id}/")
            self.assertEqual((r.status_code, r.json()["detail"]),
                             (400, "這條字軌已經開過發票或跳過號,不能刪;不用了請改成停用"))
            for change in ({"prefix": "XY"}, {"range_start": track.range_start - 10}, {"invoice_type": self.c.invoice_type.id}):
                self.assertEqual(self.patch(track, change, expect=400),
                                 {next(iter(change)): ["這條字軌已經開過發票或跳過號,字軌、起號、類型不能改"]}, change)
        self.assertEqual(InvoiceTrack.objects.filter(pk__in=[self.t1.pk, self.t2.pk]).count(), 2)
        # 迄號可以加長;不能縮到已經用到的號碼前面
        self.assertEqual(self.patch(self.t1, {"range_end": 199})["range_end"], 199)
        self.assertEqual(self.patch(self.t1, {"range_end": 100})["range_end"], 100)     # 下一張 101 = 迄號 + 1,剛好用完
        self.assertIn("range_end", self.patch(self.t2, {"range_end": 201}, expect=400))  # 下一張 203,201 之後還跳過 202
        self.assertEqual(self.patch(self.t1, {"is_active": False, "note": "收起來"})["is_active"], False)

    def test_an_unused_track_can_still_be_fixed_or_deleted(self):
        fixed = self.patch(self.t1, {"prefix": "AC", "range_start": 110})
        self.assertEqual((fixed["prefix"], fixed["next_number"], fixed["next_invoice_no"]), ("AC", 110, "AC00000110"))
        # 新增時填了下一張的:改起號不會把它蓋掉,但新的範圍要包得住它
        half = new_track(self, self.w1, "LL", 500, 549, next_number=520)
        self.assertEqual(self.patch(half, {"range_start": 510})["next_number"], 520)
        self.assertIn("range_end", self.patch(half, {"range_start": 530}, expect=400))
        self.assertEqual(self.c.admin.delete(f"{TRACKS}{self.t2.id}/").status_code, 204)
        self.assertFalse(InvoiceTrack.objects.filter(pk=self.t2.pk).exists())

    def test_the_store_cannot_be_taken_off_but_a_shared_one_can_get_a_store(self):
        self.assertEqual(self.patch(self.t1, {"warehouse": None}, expect=400), {"warehouse": ["請選門市"]})
        shared = new_track(self, None, "EF", 300, 349)
        self.assertEqual(self.patch(shared, {"note": "舊的"})["warehouse"], None)       # 舊的共用字軌照舊改得了別的欄位
        self.assertEqual(self.patch(shared, {"warehouse": self.w2.id})["warehouse_name"], self.w2.name)
        other = Company("b", "乙通訊行", "乙")                                           # 別家公司的門市選不到
        self.assertIn("warehouse", self.patch(shared, {"warehouse": other.wh.id}, expect=400))


class PeriodRuleTests(SimpleTestCase):
    def test_two_months_make_a_period(self):
        p = invoice_periods
        for day, start in ((date(2026, 1, 1), date(2026, 1, 1)), (date(2026, 2, 28), date(2026, 1, 1)),
                           (date(2026, 10, 13), date(2026, 9, 1)), (date(2026, 11, 1), date(2026, 11, 1)),
                           (date(2026, 12, 31), date(2026, 11, 1))):
            self.assertEqual(p.start_of(day), start, day)
        self.assertEqual((p.next_start(date(2026, 9, 1)), p.next_start(date(2026, 11, 1))), (date(2026, 11, 1), date(2027, 1, 1)))
        self.assertEqual((p.last_day(date(2026, 9, 1)), p.last_day(date(2028, 1, 1))), (date(2026, 10, 31), date(2028, 2, 29)))
        self.assertEqual((p.label(date(2026, 9, 1)), p.label(date(2027, 1, 1))), ("115年9-10月", "116年1-2月"))
        self.assertEqual((p.days_left(date(2026, 10, 31)), p.days_left(date(2026, 10, 24)), p.days_left(date(2026, 9, 1))), (0, 7, 60))
        self.assertEqual([p.is_start(d) for d in (date(2026, 9, 1), date(2026, 10, 1), date(2026, 9, 2))], [True, False, False])


class PeriodTests(_Shop):
    def today_is(self, day):
        """預覽看的「今天」(銷貨單的發票日期是另外一條路,一律真的今天)。"""
        patcher = mock.patch("django.utils.timezone.localdate", return_value=day)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_only_the_track_of_the_invoice_dates_period_is_used(self):
        """換期了:上一期的字軌還有號碼也不能再開;還沒到的那一期也不會先拿來用。講得出是哪一期還沒設定。"""
        InvoiceTrack.objects.filter(pk=self.t1.pk).update(period_start=LAST)
        coming = new_track(self, self.w1, "NX", 700, 749, period_start=NEXT)
        body = self.sell(expect=400)
        self.assertIn(f"電子三聯式:{THIS_NAME} 的字軌還沒設定,請到系統設定新增字軌", str(body))
        self.assertEqual((self.next_of(self.t1), self.next_of(coming)), (100, 700))
        self.assertEqual(self.peek(warehouse=self.w1.id)["detail"], f"{THIS_NAME} 的字軌還沒設定")
        current = new_track(self, self.w1, "TH", 800, 849)
        self.assertEqual(self.sell()["invoice_no"], "TH00000800")
        self.assertEqual((self.next_of(self.t1), self.next_of(coming), self.next_of(current)), (100, 700, 801))
        # 列表上各自寫得出是過期、這一期、還沒到
        states = {t["id"]: t["period_state"] for t in self.listed()}
        self.assertEqual((states[self.t1.id], states[current.id], states[coming.id], states[self.c.track.id]),
                         ("past", "now", "future", ""))

    def listed(self):
        body = self.c.admin.get(TRACKS).json()
        return body["results"] if isinstance(body, dict) else body

    def test_the_invoice_date_decides_the_period_not_the_day_it_is_asked(self):
        take = lambda day: services.assign_invoice_no(self.c.tenant, "ev_tri", self.w1.id, day)
        last = new_track(self, self.w1, "LS", 600, 649, period_start=LAST)
        self.assertEqual(take(LAST + timedelta(days=40)), "LS00000600")
        self.assertEqual(take(THIS), "AB00000100")
        with self.assertRaises(services.InvoiceTrackError) as caught:
            take(NEXT)
        self.assertEqual(str(caught.exception), f"電子三聯式:{invoice_periods.label(NEXT)} 的字軌還沒設定,請到系統設定新增字軌")
        self.assertEqual((self.next_of(last), self.next_of(self.t1)), (601, 101))

    def test_an_old_track_without_a_period_still_works_after_the_one_with_a_period(self):
        """沒登記期別的舊字軌不分期、什麼時候都能用;同一間門市有登記這一期的先用。"""
        old = new_track(self, self.w1, "OL", 900, 949, period_start=None)
        InvoiceTrack.objects.filter(pk=self.t1.pk).update(is_active=False)
        fresh = new_track(self, self.w1, "FR", 950, 950)             # 這一期的,比舊字軌晚建:還是它先
        self.assertLess(old.id, fresh.id)
        self.assertEqual(self.sell()["invoice_no"], "FR00000950")
        self.assertEqual(self.sell()["invoice_no"], "OL00000900")     # 這一期的用完了才輪到舊字軌
        InvoiceTrack.objects.filter(pk=self.t1.pk).update(is_active=True, period_start=LAST, next_number=120)
        self.assertEqual(self.sell()["invoice_no"], "OL00000901")     # 上一期的還有號碼也不拿
        self.assertEqual(self.next_of(self.t1), 120)

    def test_the_last_week_reminds_when_the_next_period_is_not_set(self):
        InvoiceTrack.objects.filter(pk__in=[self.t1.pk, self.t2.pk]).update(period_start=date(2026, 9, 1))
        upcoming = lambda: self.peek(warehouse=self.w1.id)["upcoming"]
        self.today_is(date(2026, 10, 24))
        self.assertEqual(upcoming(), "")                              # 還有 7 天以上:不吵
        self.today_is(date(2026, 10, 25))
        self.assertEqual(upcoming(), "115年11-12月")
        self.assertEqual(self.peek(warehouse=self.w1.id)["next_invoice_no"], "AB00000100")     # 這一期照常開
        new_track(self, self.w2, "N2", 700, 749, period_start=date(2026, 11, 1))               # 別間門市設了不算
        off = new_track(self, self.w1, "N1", 750, 799, period_start=date(2026, 11, 1), is_active=False)   # 停用的不算
        self.assertEqual(upcoming(), "115年11-12月")
        self.assertEqual(self.peek(warehouse=self.w2.id)["upcoming"], "")
        InvoiceTrack.objects.filter(pk=off.pk).update(is_active=True)
        self.assertEqual(upcoming(), "")
        InvoiceTrack.objects.filter(pk=off.pk).delete()
        new_track(self, None, "NS", 850, 899, period_start=date(2026, 11, 1))                  # 全公司共用的設了也算
        self.assertEqual(upcoming(), "")

    def test_after_the_month_turns_it_says_which_period_is_missing(self):
        InvoiceTrack.objects.filter(pk=self.t1.pk).update(period_start=date(2026, 9, 1))
        self.today_is(date(2026, 11, 1))
        self.assertEqual(self.peek(warehouse=self.w1.id), {
            "next_invoice_no": None, "track": None, "upcoming": "", "detail": "115年11-12月 的字軌還沒設定"})
        new_track(self, self.w1, "ND", 700, 700, period_start=date(2026, 11, 1), next_number=701)
        self.assertEqual(self.peek(warehouse=self.w1.id)["detail"], "115年11-12月 的字軌用完了")
        self.today_is(date(2026, 12, 28))                             # 跨年:下一期是明年的 1-2 月
        new_track(self, self.w1, "NE", 710, 719, period_start=date(2026, 11, 1))
        self.assertEqual(self.peek(warehouse=self.w1.id)["upcoming"], "116年1-2月")

    def test_an_old_track_without_a_period_never_reminds(self):
        InvoiceTrack.objects.filter(pk=self.t1.pk).update(period_start=None, period_label="自己寫的")
        self.today_is(date(2026, 10, 31))
        got = self.peek(warehouse=self.w1.id)
        self.assertEqual((got["next_invoice_no"], got["upcoming"]), ("AB00000100", ""))

    def test_period_can_be_fixed_but_not_taken_off(self):
        patch = lambda track, body, expect=200: self._patch(track, body, expect)
        self.sell()                                                   # 開過發票的字軌:期別填錯還是要能改(不然結帳被擋)
        fixed = patch(self.t1, {"period_start": NEXT.isoformat()})
        self.assertEqual((fixed["period_label"], fixed["period_state"]), (invoice_periods.label(NEXT), "future"))
        self.assertEqual(patch(self.t1, {"period_start": None}, 400), {"period_start": ["請選期別"]})
        self.assertIn("period_start", patch(self.t1, {"period_start": "2026-12-01"}, 400))
        # 沒登記期別的舊字軌:照舊可以不填(字是原本人打的);補上期別之後字跟著換
        old = new_track(self, self.w1, "OL", 900, 949, period_start=None, period_label="115年5-6月")
        self.assertEqual(patch(old, {"note": "舊的"})["period_label"], "115年5-6月")
        self.assertEqual(patch(old, {"period_start": THIS.isoformat(), "period_label": "亂打"})["period_label"], THIS_NAME)

    def _patch(self, track, body, expect):
        r = self.c.admin.patch(f"{TRACKS}{track.id}/", body, format="json")
        self.assertEqual(r.status_code, expect, r.content.decode())
        return r.json()


class PermissionTests(_Shop):
    def test_switching_the_item_off_stops_every_change_but_not_selling(self):
        UserProfile.objects.filter(user=self.c.clerk_user).update(denied_abilities=["invoice_tracks"])
        # 重新抓帳號:工廠手上那一個的帳號設定是建立當下的(還沒關)
        clerk = Company.client(get_user_model().objects.get(pk=self.c.clerk_user.pk))
        calls = [
            clerk.post(TRACKS, {"invoice_type": self.tri.id, "warehouse": self.w1.id, "prefix": "KK",
                                "range_start": 500, "range_end": 549, "period_start": THIS.isoformat()}, format="json"),
            clerk.patch(f"{TRACKS}{self.t1.id}/", {"note": "x"}, format="json"),
            clerk.delete(f"{TRACKS}{self.t1.id}/"),
            clerk.post(f"{TRACKS}{self.t1.id}/jump/", {"next_number": 105}, format="json"),
        ]
        for r in calls:
            self.assertEqual(r.status_code, 403, r.content.decode())
            self.assertEqual(r.json()["detail"], "這個帳號沒有「發票字軌」的權限,請管理員到「系統設定 → 員工帳號」開啟")
        self.assertEqual((InvoiceTrack.objects.count(), self.next_of(self.t1)), (3, 100))
        self.assertFalse(InvoiceTrackJump.objects.exists())
        # 看、預覽、開單取號照舊
        self.assertEqual(clerk.get(TRACKS).status_code, 200)
        self.assertEqual(self.peek(clerk)["next_invoice_no"], "AB00000100")
        self.assertEqual(clerk.get(f"{TRACKS}{self.t1.id}/jumps/").status_code, 200)
        self.assertEqual(self.sell(client=clerk)["invoice_no"], "AB00000100")

    def test_a_clerk_locked_to_a_store_manages_only_that_stores_tracks(self):
        clerk = self.c.clerk
        shared = new_track(self, None, "EF", 300, 349)
        listed = clerk.get(TRACKS).json()
        listed = listed["results"] if isinstance(listed, dict) else listed
        self.assertEqual({t["id"] for t in listed}, {self.t1.id, shared.id, self.c.track.id})
        make = {"invoice_type": self.tri.id, "prefix": "KK", "range_start": 500, "range_end": 549,
                "period_start": THIS.isoformat()}
        r = clerk.post(TRACKS, {**make, "warehouse": self.w2.id}, format="json")
        self.assertEqual((r.status_code, r.json()["detail"]), (403, "這個帳號只能設定自己門市的字軌"))
        self.assertEqual(clerk.patch(f"{TRACKS}{self.t2.id}/", {"note": "x"}, format="json").status_code, 404)
        self.assertEqual(clerk.delete(f"{TRACKS}{self.t2.id}/").status_code, 404)
        # 共用的:改、刪、搬到自己門市都要管理員
        self.assertEqual(clerk.patch(f"{TRACKS}{shared.id}/", {"note": "x"}, format="json").status_code, 403)
        self.assertEqual(clerk.patch(f"{TRACKS}{shared.id}/", {"warehouse": self.w1.id}, format="json").status_code, 403)
        self.assertEqual(clerk.delete(f"{TRACKS}{shared.id}/").status_code, 403)
        # 自己門市的:搬去別間門市不行,其他照做
        self.assertEqual(clerk.patch(f"{TRACKS}{self.t1.id}/", {"warehouse": self.w2.id}, format="json").status_code, 403)
        self.assertEqual(clerk.patch(f"{TRACKS}{self.t1.id}/", {"note": "櫃檯"}, format="json").status_code, 200)
        self.assertEqual(clerk.post(TRACKS, {**make, "warehouse": self.w1.id}, format="json").status_code, 201)
        self.assertEqual(InvoiceTrack.objects.get(pk=self.t2.pk).note, "")
        self.assertEqual(InvoiceTrack.objects.get(pk=shared.pk).warehouse_id, None)
        self.assertEqual(InvoiceTrack.objects.get(pk=self.t1.pk).warehouse_id, self.w1.id)


class _TwoConnections(TransactionTestCase):
    """「另一個人同時在做」用另一條資料庫連線模擬:它先拿到鎖、做完它的事、停一下才存檔。"""

    def setUp(self):
        setup_shop(self)

    def meanwhile(self, statements, hold=1.0):
        """另一條連線執行這些 SQL、停一下再存檔。回傳時它已經握著鎖。"""
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

    def someone_takes_the_next_number(self, so=None):
        """有人正在結帳:鎖著字軌那一列、下一張已經加一(單還沒存完)。"""
        statements = [
            ("SELECT 1 FROM tenants_invoicetrack WHERE id = %s FOR UPDATE", [self.t1.pk]),
            ("UPDATE tenants_invoicetrack SET next_number = next_number + 1, floor_number = next_number + 1 WHERE id = %s",
             [self.t1.pk]),
        ]
        if so is not None:
            statements.append(("UPDATE sales_salesorder SET invoice_no = 'AB00000105' WHERE id = %s", [so["id"]]))
        return self.meanwhile(statements)

    def someone_adds_a_track(self, start, end):
        """別人正在新增一條字軌(AB start ~ end,民生店):拿著「這家公司在動字軌設定」那一把、資料已經寫了、還沒存完。"""
        return self.meanwhile([
            ("SELECT pg_advisory_xact_lock(%s, %s)", [services.TRACK_SETUP_LOCK, self.c.tenant.pk]),
            ("INSERT INTO tenants_invoicetrack (created_at, updated_at, tenant_id, invoice_type_id, warehouse_id,"
             " period_label, period_start, prefix, range_start, range_end, next_number, is_active, note)"
             " VALUES (NOW(), NOW(), %s, %s, %s, '', %s, 'AB', %s, %s, %s, TRUE, '')",
             [self.c.tenant.pk, self.tri.pk, self.w2.pk, THIS, start, end, start]),
        ])


class JumpWaitsForSaleTests(_TwoConnections):
    """有人正在結帳、號碼取到一半(字軌那一列被他鎖著、單還沒存完):跳號要等他存完才查「開過沒有」。
    不等的話查不到他剛取的那一號,往回跳就准了,之後會再開出同一個號碼。"""

    def test_jump_back_sees_the_number_a_sale_was_just_taking(self):
        InvoiceTrack.objects.filter(pk=self.t1.pk).update(next_number=105)
        so = self.c.sell(case_qty=1)                 # 一張還沒有發票號碼的單,拿來當「正在結帳的那一張」
        began = self.someone_takes_the_next_number(so)
        r = self.c.admin.post(f"{TRACKS}{self.t1.id}/jump/", {"next_number": 103}, format="json")
        self.assertGreater(time.monotonic() - began, 0.5)             # 真的等了
        self.assertEqual(r.status_code, 400, r.content.decode())
        self.assertEqual(r.json()["detail"], f"AB00000105 已經開給銷貨單 {so['no']},下一張不能排在它前面")
        self.assertEqual(InvoiceTrack.objects.get(pk=self.t1.pk).next_number, 106)
        self.assertFalse(InvoiceTrackJump.objects.exists())


class EditWaitsForSaleTests(_TwoConnections):
    """存字軌的編輯(改備註、改迄號…)要先鎖住那一列、重新讀:不然它手上的「下一張」是進來時讀到的舊值,
    存檔會把剛剛結帳取走的那一號蓋回去,下一張銷貨單就開出重複的號碼(複審 2026-10-13 第 1 條)。"""

    def test_an_edit_does_not_put_back_the_number_a_sale_just_took(self):
        began = self.someone_takes_the_next_number()                  # 100 被取走,下一張變 101
        r = self.c.admin.patch(f"{TRACKS}{self.t1.id}/", {"note": "櫃檯"}, format="json")
        self.assertGreater(time.monotonic() - began, 0.5)
        self.assertEqual(r.status_code, 200, r.content.decode())
        track = InvoiceTrack.objects.get(pk=self.t1.pk)
        self.assertEqual((track.next_number, track.floor_number, track.note), (101, 101, "櫃檯"))

    def test_a_delete_sees_the_number_a_sale_was_just_taking(self):
        began = self.someone_takes_the_next_number()
        r = self.c.admin.delete(f"{TRACKS}{self.t1.id}/")
        self.assertGreater(time.monotonic() - began, 0.5)
        self.assertEqual(r.status_code, 400, r.content.decode())      # 等他存完:這條字軌開過號了,不能刪
        self.assertTrue(InvoiceTrack.objects.filter(pk=self.t1.pk).exists())


class OverlapWaitsTests(_TwoConnections):
    """「號碼跟別條字軌重不重疊」是先查再寫:兩個人同時新增(或一個新增、一個改迄號)重疊的兩條,各自都查不到對方、兩條都成立,
    兩間門市就會開出同一個號碼(複審 2026-10-13 第 3 條)。同一家公司動字軌的設定要排隊。"""

    def test_adding_a_track_waits_for_the_other_one_and_then_sees_the_overlap(self):
        began = self.someone_adds_a_track(500, 599)
        r = self.c.admin.post(TRACKS, {
            "invoice_type": self.tri.id, "warehouse": self.w1.id, "period_start": THIS.isoformat(),
            "prefix": "AB", "range_start": 550, "range_end": 649}, format="json")
        self.assertGreater(time.monotonic() - began, 0.5)
        self.assertEqual((r.status_code, r.json()), (400, {"range_start": ["號碼跟另一條字軌重疊:AB00000500 ~ AB00000599"]}))
        self.assertEqual(   # 只有先來的那一條(500 ~ 599);工廠附的那一條共用字軌在一千萬號,不相干
            list(InvoiceTrack.objects.filter(tenant=self.c.tenant, prefix="AB", range_start__range=(500, 700))
                 .values_list("range_start", "range_end")), [(500, 599)])

    def test_stretching_a_track_waits_too(self):
        began = self.someone_adds_a_track(150, 199)
        r = self.c.admin.patch(f"{TRACKS}{self.t1.id}/", {"range_end": 160}, format="json")
        self.assertGreater(time.monotonic() - began, 0.5)
        self.assertEqual(r.status_code, 400, r.content.decode())
        self.assertIn("重疊", str(r.json()))
        self.assertEqual(InvoiceTrack.objects.get(pk=self.t1.pk).range_end, 149)

    def test_another_company_does_not_wait(self):
        other = Company("b", "乙通訊行", "乙")
        tri = InvoiceType.objects.create(tenant=other.tenant, code="ev_tri", name="電子三聯式")
        began = self.someone_adds_a_track(500, 599)
        r = other.admin.post(TRACKS, {
            "invoice_type": tri.id, "warehouse": other.wh.id, "period_start": THIS.isoformat(),
            "prefix": "AB", "range_start": 550, "range_end": 649}, format="json")
        self.assertLess(time.monotonic() - began, 0.5)                # 別家公司的事,不用等
        self.assertEqual(r.status_code, 201, r.content.decode())


class InvoiceTaxMethodTests(_Shop):
    """全站檢視 A1:開單選了哪種發票課稅別帶什麼,每種發票自己設(以前「免用」寫死切成未稅)。"""

    def test_new_companies_keep_the_old_meaning_of_no_invoice(self):
        from apps.tenants.models import Tenant
        t = Tenant.objects.create(name="新公司", code="nn")
        services.seed_tenant_defaults(t)
        self.assertEqual(InvoiceType.objects.get(tenant=t, code="none").tax_method, "untaxed")
        self.assertEqual(InvoiceType.objects.get(tenant=t, code="e_invoice").tax_method, "")

    def test_the_shop_can_choose_what_no_invoice_brings(self):
        it = InvoiceType.objects.get(tenant=self.c.tenant, code="none")
        r = self.c.admin.patch(f"/api/v1/invoice-types/{it.id}/", {"tax_method": "taxable_included"}, format="json")
        self.assertEqual((r.status_code, r.json().get("tax_method")), (200, "taxable_included"), r.content)
        r = self.c.admin.patch(f"/api/v1/invoice-types/{it.id}/", {"tax_method": "nonsense"}, format="json")
        self.assertEqual(r.status_code, 400, r.content)
