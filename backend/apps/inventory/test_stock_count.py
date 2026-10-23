"""盤點(owner 2026-10-12):差異要管理員調整與核准、帶序號的逐台刷、盤點中可以繼續開單。規則在 `stockcount.py`。"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.backup.tests.factory import Company
from apps.catalog.models import Product
from apps.inventory import stockcount
from apps.inventory.identifiers import create_serial
from apps.inventory.models import (
    ProductSerial,
    StockBalance,
    StockCount,
    StockCountMissing,
    StockMovement,
)
from apps.inventory.test_locking import _Concurrent
from apps.ledger.checks import check_serials, check_stock_balance
from apps.tenants import abilities
from apps.tenants.models import UserProfile

URL = "/api/v1/stock-counts/"
ADJUST = StockMovement.MovementType.ADJUST


class _Count(TestCase):
    """第一家門市:皮套帳上 10 個、手機三台(甲IMEI1 ~ 3);第二家門市:皮套 5 個、手機一台(甲IMEI9)。店員鎖在第一家。"""

    def setUp(self):
        c = self.c = Company("a", "甲通訊行", "甲")
        self.w1, self.w2 = c.warehouses
        c.purchase(phone_serials=["甲IMEI1", "甲IMEI2", "甲IMEI3"], case_qty=10)
        c.purchase(warehouse=self.w2, phone_serials=["甲IMEI9"], case_qty=5)
        self.case, self.phone = c.case, c.phone

    # ── 小工具 ──
    def ok(self, r, code=200):
        self.assertEqual(r.status_code, code, r.content.decode())
        return r.json()

    def open(self, client=None, **body):
        return self.ok((client or self.c.clerk).post(URL, {"warehouse": self.w1.id, **body}, format="json"), 201)

    def line(self, count, qty, product=None, client=None):
        return (client or self.c.clerk).post(
            f"{URL}{count['id']}/lines/", {"product": (product or self.case).id, "counted_qty": qty}, format="json")

    def scan(self, count, code, client=None):
        return (client or self.c.clerk).post(f"{URL}{count['id']}/scans/", {"code": code}, format="json")

    def act(self, count, action, client=None, **body):
        return (client or self.c.admin).post(f"{URL}{count['id']}/{action}/", body, format="json")

    def detail(self, count, client=None):
        return self.ok((client or self.c.admin).get(f"{URL}{count['id']}/"))

    def stock(self, warehouse=None, product=None):
        row = StockBalance.objects.filter(
            tenant=self.c.tenant, product=product or self.case, warehouse=warehouse or self.w1).first()
        return row.qty if row else 0

    def status_of(self, serial_no):
        return ProductSerial.objects.get(tenant=self.c.tenant, serial_no=serial_no).status

    def moves(self, count):
        return list(StockMovement.objects.filter(
            tenant=self.c.tenant, ref_doc_type__startswith="stock_count", ref_doc_id=count["id"]).order_by("id"))

    def books_agree(self):
        """每日對帳的兩條:配件庫存 = 異動加總;序號的狀態、門市、銷貨紀錄彼此一致。"""
        bad = [r for r in check_stock_balance(self.c.tenant) + check_serials(self.c.tenant) if not r["ok"]]
        self.assertEqual(bad, [])


class FlowTests(_Count):
    def test_nothing_moves_until_a_manager_approves(self):
        count = self.open()
        self.assertEqual((count["no"], count["status"], count["warehouse"]["name"]), ("SC-000001", "counting", self.w1.name))
        self.ok(self.line(count, 8))                       # 帳上 10、數到 8
        self.ok(self.scan(count, "甲IMEI1"))
        self.ok(self.scan(count, "甲IMEI2"))                # 甲IMEI3 沒刷到
        self.ok(self.act(count, "submit", self.c.clerk, phones_done=True))
        # 送出了,庫存一個數字都沒動
        self.assertEqual((self.stock(), self.status_of("甲IMEI3"), self.moves(count)), (10, "in_stock", []))
        seen = self.detail(count)
        self.assertEqual((seen["status"], seen["phones_done"]), ("submitted", True))
        self.assertEqual([(r["book_qty"], r["counted_qty"], r["diff"], r["amount"]) for r in seen["line_rows"]],
                         [(10, 8, -2, "-200.00")])
        self.assertEqual([(m["serial_no"], m["cost"], m["still_here"]) for m in seen["missing_rows"]],
                         [("甲IMEI3", "20000.00", True)])
        self.assertEqual(seen["amounts"], {"lines": "-200.00", "phones": "-20000.00", "total": "-20200.00"})
        # 管理員核准:這時才動
        done = self.ok(self.act(count, "approve"))
        self.assertEqual(done["status"], "approved")
        self.assertEqual((self.stock(), self.status_of("甲IMEI3"), self.status_of("甲IMEI1")), (8, "lost", "in_stock"))
        moves = self.moves(count)
        self.assertEqual([(m.movement_type, m.product_id, m.serial_id is None, m.qty, m.from_warehouse_id, m.to_warehouse_id)
                          for m in moves],
                         [(ADJUST, self.case.id, True, 2, self.w1.id, None), (ADJUST, None, False, 1, self.w1.id, None)])
        self.assertIn("SC-000001", moves[0].note)
        saved = StockCount.objects.get(pk=count["id"])
        self.assertEqual((saved.approved_by, saved.submitted_by, saved.created_by),
                         (self.c.admin_user, self.c.clerk_user, self.c.clerk_user))
        self.assertEqual([(r["adjust_qty"], r["unit_cost"], r["amount"]) for r in done["line_rows"]], [(-2, "100.00", "-200.00")])
        # 金額用的是核准當下的平均成本:之後進貨把平均成本改掉,這張單上的數字不跟著變
        StockBalance.objects.filter(tenant=self.c.tenant, product=self.case, warehouse=self.w1).update(weighted_avg_cost=999)
        later = self.detail(count)
        self.assertEqual([(r["unit_cost"], r["amount"]) for r in later["line_rows"]], [("100.00", "-200.00")])
        StockBalance.objects.filter(tenant=self.c.tenant, product=self.case, warehouse=self.w1).update(weighted_avg_cost=100)
        self.assertEqual([(m["applied"], m["found"]) for m in done["missing_rows"]], [(True, False)])
        self.books_agree()
        # 異動查詢:歸在「庫存調整」,而且點得回這張盤點單
        listed = self.ok(self.c.admin.get("/api/v1/stock-movement-report/", {"kind": "adjust"}))["results"]
        self.assertEqual(len(listed), 2)
        self.assertEqual({(r["kind"], r["doc"]["kind"], r["doc"]["no"], r["doc"]["id"]) for r in listed},
                         {("adjust", "stock_count", "SC-000001", count["id"])})
        # 第二家門市完全沒動
        self.assertEqual((self.stock(self.w2), self.status_of("甲IMEI9")), (5, "in_stock"))

    def test_the_count_is_blind_for_whoever_counts(self):
        count = self.open()
        self.ok(self.line(count, 8))
        self.ok(self.scan(count, "甲IMEI1"))
        mine = self.detail(count, self.c.clerk)
        self.assertEqual((mine["manager"], mine["left"]), (False, 0))
        self.assertEqual(set(mine["line_rows"][0]), {"id", "product", "counted_qty", "counted_at", "moved_out", "moved_in"})
        self.assertEqual(set(mine["scan_rows"][0]), {"id", "code", "known", "name"})
        for hidden in ("missing_rows", "extra_rows", "amounts"):
            self.assertNotIn(hidden, mine)
        for word in ("book_qty", "diff", "unit_cost", "amount"):
            self.assertNotIn(word, str(mine))
        self.ok(self.act(count, "submit", self.c.clerk, phones_done=True))
        after = self.detail(count, self.c.clerk)
        self.assertNotIn("missing_rows", after)
        self.assertNotIn("book_qty", str(after))
        self.assertNotIn("甲IMEI3", str(after))               # 哪一台少了也不講
        boss = self.detail(count)
        self.assertTrue(boss["manager"] and boss["missing_rows"] and "book_qty" in boss["line_rows"][0])

    def test_how_many_are_left_is_a_number_only(self):
        other = Product.objects.create(tenant=self.c.tenant, category=self.c.cat_case, name="甲 另一款皮套",
                                       requires_serial=False, list_price=200)
        StockBalance.objects.create(tenant=self.c.tenant, product=other, warehouse=self.w1, qty=3, weighted_avg_cost=50)
        count = self.open()
        self.assertEqual(self.detail(count, self.c.clerk)["left"], 2)            # 皮套、另一款皮套
        self.ok(self.line(count, 10))
        self.assertEqual(self.detail(count, self.c.clerk)["left"], 1)
        self.ok(self.line(count, 0, other))                                       # 數到 0 個也是盤過了
        self.assertEqual(self.detail(count, self.c.clerk)["left"], 0)
        # 帶序號的商品不算在「還有幾樣」裡(它是逐台刷的;正常不會有它的數量餘額,這裡直接造一列釘住)
        StockBalance.objects.create(tenant=self.c.tenant, product=self.phone, warehouse=self.w1, qty=2, weighted_avg_cost=0)
        self.assertEqual(self.detail(count, self.c.clerk)["left"], 0)


class ReviewHelpTests(_Count):
    """全站檢視 B2 / B3:核准時看得到沒盤到的配件;刷到還沒建的配件可以先記下數量。"""

    def test_uncounted_accessories_are_listed_for_the_manager_only_after_submitting(self):
        other = Product.objects.create(tenant=self.c.tenant, category=self.c.cat_case, name="甲 另一款皮套",
                                       requires_serial=False, list_price=200)
        StockBalance.objects.create(tenant=self.c.tenant, product=other, warehouse=self.w1, qty=3, weighted_avg_cost=50)
        count = self.open()
        self.ok(self.line(count, 10))
        # 盤的時候誰都看不到這張清單(紅隊:看得到會照清單找、照帳打)
        self.assertNotIn("uncounted_rows", self.detail(count, self.c.clerk))
        self.assertNotIn("uncounted_rows", self.detail(count))
        self.ok(self.act(count, "submit", self.c.clerk, phones_done=True))
        self.assertNotIn("uncounted_rows", self.detail(count, self.c.clerk))
        rows = self.detail(count)["uncounted_rows"]
        self.assertEqual([(r["product"]["id"], r["book_qty"]) for r in rows], [(other.id, 3)])
        # 只列出來:核准不會把沒盤到的調成 0
        self.ok(self.act(count, "approve", lines=[], missing=[]))
        self.assertEqual(self.stock(product=other), 3)
        self.assertNotIn("uncounted_rows", self.detail(count))

    def test_a_code_not_in_the_system_can_be_noted_with_a_quantity(self):
        count = self.open()
        url = f"{URL}{count['id']}/unknowns/"
        out = self.ok(self.c.clerk.post(url, {"code": "OLD-0001", "qty": 5}, format="json"))
        self.assertEqual([(u["code"], u["times"], u["resolved"]) for u in out["unknown_rows"]], [("OLD-0001", 5, False)])
        out = self.ok(self.c.clerk.post(url, {"code": "old-0001", "qty": 2}, format="json"))     # 同一個碼累加
        self.assertEqual(out["unknown_rows"][0]["times"], 7)
        for bad in (0, -1, "3", 1.5, True, None, 100000):
            self.ok(self.c.clerk.post(url, {"code": "OLD-0002", "qty": bad}, format="json"), 400)
        # 系統裡有的不用先記
        self.assertIn("直接選它", self.ok(self.c.clerk.post(url, {"code": self.case.sku, "qty": 1}, format="json"), 400)["detail"])
        self.assertIn("手機", self.ok(self.c.clerk.post(url, {"code": "甲IMEI1", "qty": 1}, format="json"), 400)["detail"])
        # 還沒處理的照舊不能送出;有權限的人指定之後才行(先記的數量算進那個配件)
        self.assertIn("沒對到", self.ok(self.act(count, "submit", self.c.clerk), 400)["detail"])
        unknown = out["unknown_rows"][0]["id"]
        self.ok(self.c.admin.post(f"{URL}{count['id']}/unknowns/{unknown}/", {"product": self.case.id}, format="json"))
        boss = self.detail(count)
        self.assertEqual([(r["product"]["id"], r["counted_qty"]) for r in boss["line_rows"]], [(self.case.id, 7)])
        self.ok(self.act(count, "submit", self.c.clerk, phones_done=True))
        # 送出之後不能再記
        self.ok(self.c.clerk.post(url, {"code": "OLD-0003", "qty": 1}, format="json"), 400)


class SellingGoesOnTests(_Count):
    """盤點中可以繼續開單(owner 的第三條)。"""

    def test_the_difference_is_against_the_books_at_the_moment_of_entry(self):
        count = self.open()
        self.ok(self.line(count, 9))                        # 帳上 10、數到 9:少 1
        self.c.sell(case_qty=3)                             # 盤完之後賣掉 3 個:正常的異動
        self.ok(self.act(count, "submit", self.c.clerk))
        self.assertEqual(self.detail(count)["line_rows"][0]["diff"], -1)
        self.ok(self.act(count, "approve"))
        self.assertEqual(self.stock(), 6)                   # 7 − 1,不是「改成數到的 9」
        self.books_agree()

    def test_entering_again_takes_a_new_snapshot(self):
        count = self.open()
        self.ok(self.line(count, 9))
        self.c.sell(case_qty=2)
        self.ok(self.line(count, 7))                        # 重數:帳上這時是 8
        row = self.detail(count)["line_rows"][0]
        self.assertEqual((row["book_qty"], row["counted_qty"], row["diff"]), (8, 7, -1))
        self.assertEqual(len(self.detail(count)["line_rows"]), 1)

    def test_what_moved_between_the_start_and_the_entry_is_told(self):
        # 動手前紅隊第 3 條:先數、後輸入,中間賣掉的差異會少算 → 每一列講「開盤之後出了幾個、進了幾個」(不是帳上總數)
        self.c.sell(case_qty=1)                             # 開盤之前的不算
        count = self.open()
        self.c.sell(case_qty=2)
        self.c.purchase(case_qty=5)
        self.c.purchase(warehouse=self.w2, case_qty=4)      # 別家門市的不算
        self.ok(self.line(count, 9))
        self.c.sell(case_qty=1)                             # 輸入之後的不算(那是正常的異動)
        for client in (self.c.clerk, self.c.admin):
            row = self.detail(count, client)["line_rows"][0]
            self.assertEqual((row["moved_out"], row["moved_in"]), (2, 5))
        self.assertEqual(self.detail(count)["line_rows"][0]["book_qty"], 12)      # 9 − 2 + 5

    def test_a_phone_scanned_and_then_sold_is_neither_extra_nor_missing(self):
        # 紅隊第 2 條:刷的那一刻記下帳上的樣子
        count = self.open()
        self.ok(self.scan(count, "甲IMEI1"))
        self.c.sell(serial_no="甲IMEI1")                    # 刷過之後賣掉
        self.c.sell(serial_no="甲IMEI2")                    # 沒刷到、但已經賣掉:本來就不在庫
        self.ok(self.act(count, "submit", self.c.clerk, phones_done=True))
        seen = self.detail(count)
        self.assertEqual(([m["serial_no"] for m in seen["missing_rows"]], seen["extra_rows"]), (["甲IMEI3"], []))
        # 列成少的那一台,核准之前被賣掉了(它在):核准時不標盤虧
        self.c.sell(serial_no="甲IMEI3")
        self.assertEqual(self.detail(count)["missing_rows"][0]["still_here"], False)
        done = self.ok(self.act(count, "approve"))
        self.assertEqual((self.status_of("甲IMEI3"), done["missing_rows"][0]["applied"], self.moves(count)), ("sold", False, []))
        self.books_agree()

    def test_phones_that_came_in_after_the_count_started_are_not_missing(self):
        count = self.open()
        for code in ("甲IMEI1", "甲IMEI2", "甲IMEI3"):
            self.ok(self.scan(count, code))
        self.c.purchase(phone_serials=["甲IMEI4"])          # 刷完之後才進貨
        self.ok(self.act(count, "submit", self.c.clerk, phones_done=True))
        self.assertEqual(self.detail(count)["missing_rows"], [])


class PhoneTests(_Count):
    def test_unscanned_phones_are_only_missing_if_someone_says_all_were_scanned(self):
        # 紅隊第 1 條:只刷了櫃台的、保險櫃沒刷就送出,不能整櫃都變成盤虧
        count = self.open()
        self.ok(self.scan(count, "甲IMEI1"))
        self.ok(self.act(count, "submit", self.c.clerk))                # 沒有表明「全部刷完了」
        seen = self.detail(count)
        self.assertEqual((seen["phones_done"], seen["missing_rows"]), (False, []))
        self.ok(self.act(count, "approve"))
        self.assertEqual([self.status_of(s) for s in ("甲IMEI1", "甲IMEI2", "甲IMEI3")], ["in_stock"] * 3)
        # 表明了才算
        again = self.open()
        self.ok(self.scan(again, "甲IMEI1"))
        self.ok(self.act(again, "submit", self.c.clerk, phones_done=True))
        self.assertEqual([m["serial_no"] for m in self.detail(again)["missing_rows"]], ["甲IMEI2", "甲IMEI3"])
        # 只接受明確的「是」
        third_store = self.ok(self.c.admin.post(URL, {"warehouse": self.w2.id}, format="json"), 201)
        self.ok(self.act(third_store, "submit", phones_done="yes"), 400)

    def test_extras_are_listed_and_never_fixed_automatically(self):
        self.c.sell(serial_no="甲IMEI1")
        count = self.open()
        self.ok(self.scan(count, "甲IMEI1"))                # 帳上已售,現場卻刷到
        self.ok(self.scan(count, "甲IMEI9"))                # 帳上在第二家門市
        self.ok(self.scan(count, "不認得的碼123"))
        self.ok(self.scan(count, "甲IMEI2"))
        mine = self.detail(count, self.c.clerk)
        self.assertEqual([(s["code"], s["known"], s["name"]) for s in mine["scan_rows"]], [
            ("甲IMEI1", True, self.phone.name), ("甲IMEI9", True, self.phone.name), ("不認得的碼123", False, ""),
            ("甲IMEI2", True, self.phone.name)])
        self.ok(self.act(count, "submit", self.c.clerk, phones_done=True))
        seen = self.detail(count)
        self.assertEqual([(e["code"], e["state"]) for e in seen["extra_rows"]], [("甲IMEI1", "已售"), ("甲IMEI9", "在庫")])
        # 系統不認得的另外一份(第一次盤點入庫:要管理員指定品號才入;沒講就不入)
        self.assertEqual([(e["code"], e["product"]) for e in seen["new_rows"]], [("不認得的碼123", None)])
        self.ok(self.act(count, "approve"))
        self.assertFalse(ProductSerial.objects.filter(tenant=self.c.tenant, serial_no="不認得的碼123").exists())
        self.assertEqual((self.status_of("甲IMEI1"), self.status_of("甲IMEI9")), ("sold", "in_stock"))
        self.assertEqual(ProductSerial.objects.get(serial_no="甲IMEI9").warehouse, self.w2)
        self.books_agree()

    def test_found_only_works_for_a_phone_this_count_marked_lost(self):
        # 第一張盤點單把甲IMEI3 勾成先不調;第二張才把它標成盤虧。不能拿第一張的「找回」把它變回在庫
        first = self.open()
        self.ok(self.scan(first, "甲IMEI1"))
        self.ok(self.scan(first, "甲IMEI2"))
        self.ok(self.act(first, "submit", self.c.clerk, phones_done=True))
        skipped = self.detail(first)["missing_rows"][0]
        self.ok(self.act(first, "approve", missing={str(skipped["id"]): {"skipped": True}}))
        second = self.open()
        self.ok(self.scan(second, "甲IMEI1"))
        self.ok(self.scan(second, "甲IMEI2"))
        self.ok(self.act(second, "submit", self.c.clerk, phones_done=True))
        self.ok(self.act(second, "approve"))
        self.assertEqual(self.status_of("甲IMEI3"), "lost")
        r = self.c.admin.post(f"{URL}{first['id']}/missing/{skipped['id']}/found/", {}, format="json")
        self.assertEqual(r.status_code, 400, r.content.decode())
        self.assertEqual(self.status_of("甲IMEI3"), "lost")
        self.assertEqual(self.c.admin.post(f"{URL}{first['id']}/missing/999999/found/", {}, format="json").status_code, 400)

    def test_a_returned_phone_sitting_in_the_store_is_neither_extra_nor_missing(self):
        # 客人退回來、還放在店裡的(狀態「已退」):刷到不算多;沒刷到也不算少(要刷的只有「在庫」的)
        self.c.sell(serial_no="甲IMEI1")
        so = self.c.sell(serial_no="甲IMEI2")
        sold = __import__("apps.sales.models", fromlist=["SalesOrder"]).SalesOrder.objects.filter(tenant=self.c.tenant).order_by("id")
        for order in sold:
            self.c._post("/api/v1/sales-returns/", {"original_so": order.id, "payment_method": "cash"})
        # 2026-10-23 起銷退直接回在庫;「已退」只剩這一版之前退的
        ProductSerial.objects.filter(tenant=self.c.tenant, serial_no__in=["甲IMEI1", "甲IMEI2"]).update(status="returned")
        self.assertEqual((self.status_of("甲IMEI1"), self.status_of("甲IMEI2"), so["id"] > 0), ("returned", "returned", True))
        count = self.open()
        self.ok(self.scan(count, "甲IMEI1"))                # 已退、刷到了
        self.ok(self.scan(count, "甲IMEI3"))                # 甲IMEI2 已退、沒刷到
        self.ok(self.act(count, "submit", self.c.clerk, phones_done=True))
        seen = self.detail(count)
        self.assertEqual((seen["extra_rows"], seen["missing_rows"]), ([], []))
        self.ok(self.act(count, "approve"))
        self.assertEqual((self.status_of("甲IMEI1"), self.status_of("甲IMEI2")), ("returned", "returned"))

    def test_a_code_or_a_phone_is_scanned_once(self):
        both = create_serial(tenant=self.c.tenant, product=self.phone, imei="356789012345678", sn="SNAB12",
                             warehouse=self.w1, purchase_unit_cost=Decimal("20000"))
        count = self.open()
        self.ok(self.scan(count, "356789012345678"))
        self.assertIn("刷過", self.ok(self.scan(count, "3567 8901 2345 678"), 400)["detail"])     # 同一個碼(去掉空白)
        self.assertIn("這一台刷過", self.ok(self.scan(count, "SNAB12"), 400)["detail"])           # 同一台的另一個碼
        self.ok(self.scan(count, ""), 400)
        self.ok(self.scan(count, "---"), 400)
        self.ok(self.scan(count, "不認得的碼"))
        self.assertEqual(self.ok(self.scan(count, "不認得的碼"), 400)["detail"], "這個碼刷過了")       # 系統不認得的碼也只記一次
        self.assertEqual(len(self.detail(count)["scan_rows"]), 2)
        self.assertEqual(both.status, "in_stock")

    def test_found_brings_a_lost_phone_back(self):
        count = self.open()
        self.ok(self.scan(count, "甲IMEI1"))
        self.ok(self.scan(count, "甲IMEI2"))
        self.ok(self.act(count, "submit", self.c.clerk, phones_done=True))
        done = self.ok(self.act(count, "approve"))
        lost = done["missing_rows"][0]
        self.assertEqual(self.status_of("甲IMEI3"), "lost")
        # 盤虧的不能賣;碼還佔著(不能再進一次貨)
        serial = ProductSerial.objects.get(serial_no="甲IMEI3")
        r = self.c.admin.post("/api/v1/sales-orders/", {
            "customer": self.c.customer.id, "warehouse": self.w1.id, "tax_method": "untaxed",
            "items": [{"product": self.phone.id, "qty": 1, "unit_price": "25000", "serial_ids": [serial.id]}],
            "payments": [{"method": "cash", "amount": "25000"}]}, format="json")
        self.assertEqual(r.status_code, 400, r.content.decode())
        r = self.c.admin.post("/api/v1/purchase-orders/", {
            "supplier": self.c.supplier.id, "warehouse": self.w1.id, "tax_method": "untaxed",
            "items": [{"product": self.phone.id, "qty": 1, "unit_price": "20000", "serial_numbers": ["甲IMEI3"]}]}, format="json")
        self.assertEqual(r.status_code, 400, r.content.decode())
        # 找回:只有管理員
        url = f"{URL}{count['id']}/missing/{lost['id']}/found/"
        self.assertEqual(self.c.clerk.post(url, {}, format="json").status_code, 403)
        back = self.ok(self.c.admin.post(url, {}, format="json"))
        self.assertEqual((self.status_of("甲IMEI3"), back["missing_rows"][0]["found"], back["amounts"]["phones"]),
                         ("in_stock", True, "0.00"))
        last = self.moves(count)[-1]
        self.assertEqual((last.movement_type, last.serial_id, last.to_warehouse_id, last.from_warehouse_id, last.ref_doc_type),
                         (ADJUST, serial.id, self.w1.id, None, "stock_count_found"))
        self.assertEqual(StockCountMissing.objects.get(pk=lost["id"]).found_by, self.c.admin_user)
        self.assertEqual(self.c.admin.post(url, {}, format="json").status_code, 400)       # 找回過了
        self.books_agree()


class ApprovalTests(_Count):
    def ready(self):
        count = self.open()
        self.ok(self.line(count, 8))
        self.ok(self.scan(count, "甲IMEI1"))
        self.ok(self.scan(count, "甲IMEI2"))
        self.ok(self.act(count, "submit", self.c.clerk, phones_done=True))
        seen = self.detail(count)
        return count, seen["line_rows"][0]["id"], seen["missing_rows"][0]["id"]

    def test_the_manager_can_change_the_amount_or_leave_a_row_alone(self):
        count, line_id, missing_id = self.ready()
        done = self.ok(self.act(count, "approve",
                                lines={str(line_id): {"adjust_qty": -1, "reason": "倉庫找到一個"}},
                                missing={str(missing_id): {"skipped": True, "reason": "送修中忘了登記"}}))
        self.assertEqual((self.stock(), self.status_of("甲IMEI3")), (9, "in_stock"))
        self.assertEqual([(r["adjust_qty"], r["skipped"], r["reason"], r["diff"]) for r in done["line_rows"]],
                         [(-1, False, "倉庫找到一個", -2)])
        self.assertEqual([(m["applied"], m["skipped"], m["reason"]) for m in done["missing_rows"]],
                         [(False, True, "送修中忘了登記")])
        self.assertEqual([(m.qty, m.serial_id) for m in self.moves(count)], [(1, None)])
        self.assertEqual(done["amounts"], {"lines": "-100.00", "phones": "0.00", "total": "-100.00"})
        self.books_agree()

    def test_a_skipped_line_moves_nothing(self):
        count, line_id, missing_id = self.ready()
        self.ok(self.act(count, "approve", lines={str(line_id): {"skipped": True, "adjust_qty": -2}},
                         missing={str(missing_id): {"skipped": True}}))
        self.assertEqual((self.stock(), self.status_of("甲IMEI3"), self.moves(count)), (10, "in_stock", []))
        self.assertEqual(StockCount.objects.get(pk=count["id"]).status, "approved")

    def test_not_enough_to_take_off_stops_the_whole_approval(self):
        count = self.open()
        self.ok(self.line(count, 2))                        # 帳上 10、數到 2:差 8
        self.ok(self.scan(count, "甲IMEI1"))
        self.ok(self.act(count, "submit", self.c.clerk, phones_done=True))
        self.c.sell(case_qty=5)                             # 核准之前又賣掉 5 個:帳上剩 5,不夠扣 8
        r = self.act(count, "approve")
        self.assertEqual(r.status_code, 400)
        self.assertIn(self.case.name, r.json()["detail"])
        self.assertIn("5", r.json()["detail"])
        # 整張都沒動(手機也沒有先標成盤虧)
        self.assertEqual((self.stock(), self.status_of("甲IMEI2"), self.moves(count)), (5, "in_stock", []))
        self.assertEqual(StockCount.objects.get(pk=count["id"]).status, "submitted")
        line_id = self.detail(count)["line_rows"][0]["id"]
        self.ok(self.act(count, "approve", lines={str(line_id): {"adjust_qty": -5}}))
        self.assertEqual((self.stock(), self.status_of("甲IMEI2")), (0, "lost"))
        self.books_agree()

    def test_a_surplus_adds_stock(self):
        other = Product.objects.create(tenant=self.c.tenant, category=self.c.cat_case, name="甲 從來沒進過這家的皮套",
                                       requires_serial=False, list_price=200, weighted_avg_cost=Decimal("60"))
        count = self.open()
        self.ok(self.line(count, 12))                       # 帳上 10、數到 12
        self.ok(self.line(count, 3, other))                 # 這家門市從來沒有這個商品
        self.ok(self.act(count, "submit", self.c.clerk))
        done = self.ok(self.act(count, "approve"))
        self.assertEqual((self.stock(), self.stock(product=other)), (12, 3))
        self.assertEqual([(m.product_id, m.qty, m.to_warehouse_id, m.from_warehouse_id) for m in self.moves(count)],
                         [(self.case.id, 2, self.w1.id, None), (other.id, 3, self.w1.id, None)])
        # 平均成本不變;從來沒有過的用公司的平均成本(不是 0 元的貨)
        costs = dict(StockBalance.objects.filter(warehouse=self.w1).values_list("product_id", "weighted_avg_cost"))
        self.assertEqual((costs[self.case.id], costs[other.id]), (Decimal("100.00"), Decimal("60.00")))
        self.assertEqual(done["amounts"]["lines"], "380.00")            # 2 × 100 + 3 × 60
        self.books_agree()

    def test_a_product_turned_into_a_serial_or_virtual_one_after_submitting_cannot_be_adjusted(self):
        """複審 P0:盤完送出之後,商品被改成「帶序號」或「虛擬」。那種商品不能有數量庫存 —— 核准時要再看一次,
        不能照樣加出一筆數量(庫存查詢不算它、每日對帳會報錯)。"""
        fresh = Product.objects.create(tenant=self.c.tenant, category=self.c.cat_case, name="甲 之後改成帶序號的",
                                       requires_serial=False, list_price=200)
        ghost = Product.objects.create(tenant=self.c.tenant, category=self.c.cat_case, name="甲 之後改成虛擬的",
                                       requires_serial=False, list_price=200)
        count = self.open()
        self.ok(self.line(count, 3, fresh))
        self.ok(self.line(count, 2, ghost))
        self.ok(self.line(count, 8))
        self.ok(self.act(count, "submit", self.c.clerk))
        Product.objects.filter(pk=fresh.pk).update(requires_serial=True)
        Product.objects.filter(pk=ghost.pk).update(is_virtual=True)
        r = self.act(count, "approve")
        self.assertEqual(r.status_code, 400, r.content.decode())
        self.assertIn("甲 之後改成", r.json()["detail"])
        self.assertIn("先不調", r.json()["detail"])
        # 整張都沒動
        self.assertEqual((self.stock(), self.stock(product=fresh), self.stock(product=ghost), self.moves(count)), (10, 0, 0, []))
        rows = {r["product"]["id"]: r["id"] for r in self.detail(count)["line_rows"]}
        # 兩種都要擋:只把其中一個勾成先不調,另一個照樣擋下來
        for skipped, still_bad in ((fresh, ghost), (ghost, fresh)):
            r = self.act(count, "approve", lines={str(rows[skipped.id]): {"skipped": True}})
            self.assertEqual(r.status_code, 400, r.content.decode())
            self.assertIn(still_bad.name, r.json()["detail"])
        self.assertEqual((self.stock(), self.moves(count)), (10, []))
        self.ok(self.act(count, "approve", lines={str(rows[fresh.id]): {"skipped": True}, str(rows[ghost.id]): {"skipped": True}}))
        self.assertEqual((self.stock(), self.stock(product=fresh), self.stock(product=ghost)), (8, 0, 0))
        self.books_agree()

    def test_bad_decisions_are_refused(self):
        count, line_id, _ = self.ready()
        for body in ({"lines": {str(line_id): {"adjust_qty": "2"}}}, {"lines": {str(line_id): {"adjust_qty": 1.5}}},
                     {"lines": [1]}, {"lines": {str(line_id): "skip"}}, {"missing": "all"}):
            self.assertEqual(self.act(count, "approve", **body).status_code, 400, body)
        self.assertEqual((self.stock(), StockCount.objects.get(pk=count["id"]).status), (10, "submitted"))


class RulesTests(_Count):
    def test_states_and_who_may_do_what(self):
        count = self.open()
        self.ok(self.line(count, 8))
        # 盤的人不能核准、不能退回;還沒送出不能核准
        self.assertEqual(self.act(count, "approve", self.c.clerk).status_code, 403)
        self.assertEqual(self.act(count, "return", self.c.clerk).status_code, 403)
        self.assertEqual(self.act(count, "approve").status_code, 400)
        self.assertEqual(self.act(count, "nope").status_code, 404)
        self.ok(self.act(count, "submit", self.c.clerk))
        # 送出之後不能再改、不能再送;盤的人不能作廢已經送出的
        self.assertEqual(self.line(count, 9).status_code, 400)
        self.assertEqual(self.scan(count, "甲IMEI1").status_code, 400)
        self.assertEqual(self.c.clerk.delete(f"{URL}{count['id']}/lines/{self.detail(count)['line_rows'][0]['id']}/").status_code, 400)
        self.assertEqual(self.act(count, "submit", self.c.clerk).status_code, 400)
        self.assertEqual(self.act(count, "void", self.c.clerk).status_code, 403)
        # 管理員退回 → 可以再盤、送出時算的手機差異丟掉
        self.assertEqual(self.ok(self.act(count, "return"))["status"], "counting")
        self.ok(self.line(count, 9))
        self.ok(self.act(count, "submit", self.c.clerk))
        self.ok(self.act(count, "approve"))
        self.assertEqual(self.stock(), 9)
        # 核准之後什麼都不能再做
        for action in ("approve", "return", "void", "submit"):
            self.assertEqual(self.act(count, action).status_code, 400, action)
        self.assertEqual(self.stock(), 9)

    def test_return_throws_away_the_phone_differences(self):
        count = self.open()
        self.ok(self.scan(count, "甲IMEI1"))
        self.ok(self.act(count, "submit", self.c.clerk, phones_done=True))
        self.assertEqual(StockCountMissing.objects.filter(count_id=count["id"]).count(), 2)
        back = self.ok(self.act(count, "return"))
        self.assertEqual((StockCountMissing.objects.filter(count_id=count["id"]).count(), back["phones_done"]), (0, False))
        self.ok(self.scan(count, "甲IMEI2"))
        self.ok(self.c.clerk.delete(f"{URL}{count['id']}/scans/{back['scan_rows'][0]['id']}/"))        # 刷錯的可以拿掉
        self.ok(self.act(count, "submit", self.c.clerk, phones_done=True))
        self.assertEqual([m["serial_no"] for m in self.detail(count)["missing_rows"]], ["甲IMEI1", "甲IMEI3"])

    def test_one_unfinished_count_per_store(self):
        first = self.open()
        r = self.c.clerk.post(URL, {"warehouse": self.w1.id}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn(first["no"], r.json()["detail"])
        other = self.ok(self.c.admin.post(URL, {"warehouse": self.w2.id}, format="json"), 201)       # 別家門市可以
        self.assertEqual(other["no"], "SC-000002")
        self.ok(self.act(first, "void", self.c.clerk))                                              # 還在盤的自己可以作廢
        self.assertEqual(self.open()["no"], "SC-000003")
        self.assertEqual(self.ok(self.act(first, "submit", self.c.clerk), 400)["detail"][:6], "這張盤點單現")
        self.ok(self.c.clerk.post(URL, {"warehouse": self.w1.id, "categories": "x"}, format="json"), 400)

    def test_only_what_can_be_counted(self):
        count = self.open()
        self.assertIn("一台一台刷", self.ok(self.line(count, 3, self.phone), 400)["detail"])
        virtual = Product.objects.create(tenant=self.c.tenant, category=self.c.cat_case, name="甲 服務費",
                                         requires_serial=False, is_virtual=True)
        self.ok(self.line(count, 1, virtual), 400)
        for qty in (-1, "3", 1.5, None, True):
            self.assertEqual(self.line(count, qty).status_code, 400, qty)
        self.assertEqual(self.c.clerk.post(f"{URL}{count['id']}/lines/", {"product": 10**9, "counted_qty": 1},
                                           format="json").status_code, 400)
        self.assertEqual(self.detail(count)["line_rows"], [])

    def test_a_count_can_be_limited_to_some_categories(self):
        count = self.open(categories=[self.c.cat_case.id])
        self.assertEqual(count["categories"], [self.c.cat_case.name])
        self.ok(self.line(count, 8))
        self.assertIn("不在這張盤點單的類別裡", self.ok(self.scan(count, "甲IMEI1"), 400)["detail"])
        self.ok(self.act(count, "submit", self.c.clerk, phones_done=True))
        self.assertEqual(self.detail(count)["missing_rows"], [])            # 手機不在範圍裡:一台都不算少
        phones = self.ok(self.c.admin.post(URL, {"warehouse": self.w2.id, "categories": [self.c.cat_phone.id]}, format="json"), 201)
        self.assertIn("不在這張盤點單的類別裡", self.ok(self.line(phones, 5, client=self.c.admin), 400)["detail"])
        self.assertEqual(self.detail(phones)["left"], 0)                    # 配件不在範圍裡

    def test_a_locked_clerk_only_counts_the_own_store(self):
        mine = self.ok(self.c.clerk.post(URL, {"warehouse": self.w2.id}, format="json"), 201)     # 送別家的編號:開的還是自己門市
        self.assertEqual(mine["warehouse"]["id"], self.w1.id)
        theirs = self.ok(self.c.admin.post(URL, {"warehouse": self.w2.id}, format="json"), 201)
        self.assertEqual(self.c.clerk.get(f"{URL}{theirs['id']}/").status_code, 404)
        self.assertEqual(self.scan(theirs, "甲IMEI9").status_code, 404)
        self.assertEqual(self.act(theirs, "submit", self.c.clerk).status_code, 404)
        listed = self.ok(self.c.clerk.get(URL))["results"]
        self.assertEqual([c["no"] for c in listed], [mine["no"]])
        self.assertEqual(sorted(c["no"] for c in self.ok(self.c.admin.get(URL))["results"]), [mine["no"], theirs["no"]])

    def test_needs_the_item(self):
        self.assertEqual((abilities.LABELS[abilities.STOCK_COUNT], len(abilities.LABELS[abilities.STOCK_COUNT])), ("盤點作業", 4))
        count = self.open()
        UserProfile.objects.filter(user=self.c.clerk_user).update(denied_abilities=["stock_count"])
        clerk = Company.client(get_user_model().objects.get(pk=self.c.clerk_user.pk))
        for r in (clerk.get(URL), clerk.post(URL, {"warehouse": self.w1.id}, format="json"), clerk.get(f"{URL}{count['id']}/"),
                  self.line(count, 3, client=clerk), self.scan(count, "甲IMEI1", clerk), self.act(count, "submit", clerk)):
            self.assertEqual(r.status_code, 403, r.content.decode())
            self.assertIn("「盤點作業」", r.json()["detail"])
        self.assertEqual(self.c.admin.get(URL).status_code, 200)

    def test_another_company_is_never_touched(self):
        other = Company("b", "乙通訊行", "乙")
        other.purchase(phone_serials=["乙IMEI1"], case_qty=4)
        count = self.open()                                                 # 這家先開一張
        theirs = self.ok(other.admin.post(URL, {"warehouse": other.wh.id}, format="json"), 201)
        self.assertEqual((count["no"], theirs["no"]), ("SC-000001", "SC-000001"))        # 單號各家各自編
        self.assertEqual(self.c.admin.get(f"{URL}{theirs['id']}/").status_code, 404)
        self.assertEqual(self.c.admin.post(URL, {"warehouse": other.wh.id}, format="json").status_code, 400)
        self.assertEqual(self.line(count, 1, other.case).status_code, 400)
        # 規則那一層自己也擋(不靠端點先濾掉):別家公司的商品、別家公司的門市
        mine = StockCount.objects.get(pk=count["id"])
        with self.assertRaises(stockcount.CountError):
            stockcount.set_line(mine, other.case, 1, self.c.admin_user)
        with self.assertRaises(stockcount.CountError):
            stockcount.open_count(self.c.tenant, other.wh, [], self.c.admin_user)
        self.ok(self.scan(count, "乙IMEI1"))                                # 別家的碼 = 這家不認得
        self.assertEqual(self.detail(count)["scan_rows"][0]["known"], False)
        self.assertEqual(self.c.admin.post(URL, {"warehouse": self.w2.id, "categories": [other.cat_case.id]},
                                           format="json").status_code, 400)


class TwoPeopleTests(_Concurrent):
    """核准的當下別人正好在動同一個商品的庫存:要等他存完、照他改過的數量加減,不能各自讀到舊值。"""

    def test_approval_waits_for_a_change_made_at_the_same_moment(self):
        count = stockcount.open_count(self.c.tenant, self.w1, [], self.c.admin_user)
        stockcount.set_line(count, self.c.case, 4, self.c.admin_user)        # 帳上 5、數到 4:差 −1
        stockcount.submit(count, self.c.admin_user)
        t = self.someone_adds_ten()                                          # 另一條連線鎖著餘額、加了 10、還沒存
        stockcount.approve(count, self.c.admin_user)
        t.join()
        self.assertEqual(self.stock(), 5 + 10 - 1)

    def test_two_approvals_at_once_only_move_stock_once(self):
        """兩個管理員同時按核准(複審:原本那一條只用 SQL 改狀態,沒有真的核准兩次):
        另一條連線先握著這張單的鎖,這時兩邊都真的去核准 —— 鎖放開之後只有一邊成功,庫存只扣一次。"""
        import threading

        from django.db import connections

        count = stockcount.open_count(self.c.tenant, self.w1, [], self.c.admin_user)
        stockcount.set_line(count, self.c.case, 4, self.c.admin_user)        # 帳上 5、數到 4:差 −1
        stockcount.submit(count, self.c.admin_user)
        holder = self.meanwhile([("SELECT 1 FROM inventory_stockcount WHERE id = %s FOR UPDATE", [count.pk])])
        results = []

        def approve_once():
            try:
                stockcount.approve(StockCount.objects.get(pk=count.pk), self.c.admin_user)
                results.append("ok")
            except stockcount.CountError:
                results.append("refused")
            finally:
                connections.close_all()

        other = threading.Thread(target=approve_once)
        other.start()
        try:
            stockcount.approve(StockCount.objects.get(pk=count.pk), self.c.admin_user)
            results.append("ok")
        except stockcount.CountError:
            results.append("refused")
        other.join()
        holder.join()
        self.assertEqual(sorted(results), ["ok", "refused"])
        self.assertEqual(self.stock(), 4)
        self.assertEqual(StockMovement.objects.filter(ref_doc_type="stock_count", ref_doc_id=count.pk).count(), 1)

    def test_approval_takes_the_phone_before_the_stock_like_a_sale_does(self):
        """複審第二輪 P1:核准如果先鎖商品 / 餘額、再鎖手機,會跟銷貨(先鎖手機、再鎖餘額連帶商品)相反 ——
        一張銷貨單同時有那一台手機與那個配件、又剛好同時核准,兩邊互相等到死結。
        這裡讓「另一張單」握著那一台手機:核准在等手機的時候,手上不可以已經握著配件的餘額或商品。"""
        import threading
        import time

        from django.db import connection, connections, transaction
        from django.db.utils import OperationalError

        count = stockcount.open_count(self.c.tenant, self.w1, [], self.c.admin_user)
        stockcount.set_line(count, self.c.case, 4, self.c.admin_user)        # 帳上 5、數到 4
        stockcount.submit(count, self.c.admin_user, phones_done=True)        # 甲IMEI1 沒刷到 = 少的
        serial = ProductSerial.objects.get(serial_no="甲IMEI1")
        balance = StockBalance.objects.get(product=self.c.case, warehouse=self.w1)
        holder = self.meanwhile(
            [("SELECT 1 FROM inventory_productserial WHERE id = %s FOR NO KEY UPDATE", [serial.pk])], hold=2.0)
        done = []

        def approve():
            try:
                stockcount.approve(StockCount.objects.get(pk=count.pk), self.c.admin_user)
                done.append("ok")
            finally:
                connections.close_all()

        worker = threading.Thread(target=approve)
        worker.start()
        time.sleep(0.8)                                                      # 這時核准正在等那一台手機
        free = []
        for sql, pk in (("SELECT 1 FROM catalog_product WHERE id = %s FOR UPDATE NOWAIT", self.c.case.pk),
                        ("SELECT 1 FROM inventory_stockbalance WHERE id = %s FOR UPDATE NOWAIT", balance.pk)):
            try:
                with transaction.atomic(), connection.cursor() as cur:
                    cur.execute(sql, [pk])
                free.append(True)
            except OperationalError:
                free.append(False)
        worker.join()
        holder.join()
        self.assertEqual(free, [True, True])
        self.assertEqual((done, self.stock(), ProductSerial.objects.get(pk=serial.pk).status), (["ok"], 4, "lost"))

    def test_a_clerk_cannot_void_a_count_that_was_submitted_a_moment_ago(self):
        """複審 P0:一個人按送出、另一個人同時按作廢。作廢那邊手上看到的還是「盤點中」,但鎖到的時候單已經送出了 ——
        已經送出的只有管理員能作廢,這一下要在鎖到之後才看。"""
        count = stockcount.open_count(self.c.tenant, self.w1, [], self.c.clerk_user)
        stockcount.set_line(count, self.c.case, 4, self.c.clerk_user)
        stale = StockCount.objects.get(pk=count.pk)                          # 作廢的人手上這一份:盤點中
        t = self.meanwhile([
            ("SELECT 1 FROM inventory_stockcount WHERE id = %s FOR UPDATE", [count.pk]),
            ("UPDATE inventory_stockcount SET status = 'submitted' WHERE id = %s", [count.pk]),
        ])
        with self.assertRaises(stockcount.CountError):
            stockcount.void(stale, by_manager=False)
        t.join()
        self.assertEqual(StockCount.objects.get(pk=count.pk).status, "submitted")
        # 管理員可以
        stockcount.void(StockCount.objects.get(pk=count.pk), by_manager=True)
        self.assertEqual(StockCount.objects.get(pk=count.pk).status, "void")

    def test_the_void_request_of_a_clerk_is_refused_when_the_count_was_just_submitted(self):
        """同一件事從端點走一次:店員按作廢的請求進來時單還是「盤點中」,等到鎖的時候已經送出了 —— 要被擋下來。
        (端點如果把每個人都當成管理員傳進去,這裡就會作廢成功。)"""
        count = stockcount.open_count(self.c.tenant, self.w1, [], self.c.clerk_user)
        stockcount.set_line(count, self.c.case, 4, self.c.clerk_user)
        t = self.meanwhile([
            ("SELECT 1 FROM inventory_stockcount WHERE id = %s FOR UPDATE", [count.pk]),
            ("UPDATE inventory_stockcount SET status = 'submitted' WHERE id = %s", [count.pk]),
        ])
        r = self.c.clerk.post(f"/api/v1/stock-counts/{count.pk}/void/", {}, format="json")
        t.join()
        self.assertEqual(r.status_code, 400, r.content.decode())
        self.assertEqual(StockCount.objects.get(pk=count.pk).status, "submitted")
        # 管理員的作廢請求可以
        r = self.c.admin.post(f"/api/v1/stock-counts/{count.pk}/void/", {}, format="json")
        self.assertEqual((r.status_code, StockCount.objects.get(pk=count.pk).status), (200, "void"))

    def test_the_book_quantity_waits_for_a_first_purchase_that_is_being_saved(self):
        """複審 P0:這家門市還沒有這個商品的餘額列,有人正在存第一張進貨(那一列還沒存完、別人看不到)。
        這時輸入盤到的數量,要等他存完、讀到進貨之後的數量 —— 不能當成帳上 0(核准時會多加一次)。"""
        self.assertFalse(StockBalance.objects.filter(product=self.c.case, warehouse=self.w2).exists())
        count = stockcount.open_count(self.c.tenant, self.w2, [], self.c.admin_user)
        t = self.meanwhile([
            ("INSERT INTO inventory_stockbalance (tenant_id, product_id, warehouse_id, qty, weighted_avg_cost, created_at, updated_at) "
             "VALUES (%s, %s, %s, 10, 100, now(), now())", [self.c.tenant.pk, self.c.case.pk, self.w2.pk]),
        ])
        line = stockcount.set_line(count, self.c.case, 10, self.c.admin_user)
        t.join()
        self.assertEqual(line.book_qty, 10)
        stockcount.submit(count, self.c.admin_user)
        stockcount.approve(count, self.c.admin_user)
        self.assertEqual(self.stock(self.w2), 10)                            # 不是 20

    def test_the_book_quantity_is_read_after_a_sale_that_is_being_saved(self):
        count = stockcount.open_count(self.c.tenant, self.w1, [], self.c.admin_user)
        t = self.someone_adds_ten()
        line = stockcount.set_line(count, self.c.case, 15, self.c.admin_user)
        t.join()
        self.assertEqual(line.book_qty, 15)                                  # 等對方存完才讀:不是舊的 5

    def test_two_people_opening_a_count_for_the_same_store_get_one(self):
        t = self.meanwhile([
            ("SELECT 1 FROM tenants_tenant WHERE id = %s FOR UPDATE", [self.c.tenant.pk]),
            ("INSERT INTO inventory_stockcount (tenant_id, warehouse_id, no, status, note, phones_done, created_at, updated_at) "
             "VALUES (%s, %s, 'SC-000001', 'counting', '', false, now(), now())", [self.c.tenant.pk, self.w1.pk]),
        ])
        with self.assertRaises(stockcount.CountError):
            stockcount.open_count(self.c.tenant, self.w1, [], self.c.admin_user)
        t.join()
        self.assertEqual(StockCount.objects.filter(tenant=self.c.tenant).count(), 1)
