"""庫存三張:進銷存表、異動查詢、序號查詢。

情境盡量走真正的開單 API(進貨、銷貨、銷退、調撥、作廢、個人收購),這樣庫存與異動是系統自己記的;
報表只讀它們,驗的是「每一列等式成立、期末 = 帳上的數量、各門市加起來 = 全公司」。
"""
from datetime import timedelta
from itertools import product as combos

from django.db import connection
from django.test import TestCase, TransactionTestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.backup.tests.factory import Company
from apps.inventory import flows, reports
from apps.inventory.models import ProductSerial, StockBalance, StockMovement

T = StockMovement.MovementType
REFS = ["", "purchase_order", "sales_order", "sales_return", "transfer_order",
        "repair_order", "repair_order_shortage", "repair_order_reopen", "something_new"]
FLOW = "/api/v1/stock-flow-report/"
MOVES = "/api/v1/stock-movement-report/"
SERIALS = "/api/v1/serial-report/"


def today():
    return timezone.localdate()


def balanced(row):
    """期末 = 期初 + 每一欄 × 它的方向。"""
    return row["opening"] + sum(row[c] * flows.SIGN[c] for c in flows.COLUMNS) == row["closing"]


class FlowRuleTests(TestCase):
    """`flows.py`:每一種異動算哪一類、動到哪家門市、算在哪一欄 —— 資料庫的寫法與程式的寫法要是同一份規則。"""

    def setUp(self):
        self.c = Company("a", "甲通訊行", "甲")
        self.w1, self.w2 = self.c.warehouses
        rows = []
        for kind, ref, w_from, w_to in combos(
            [*T.values, "brand_new_type"], REFS, [None, self.w1, self.w2], [None, self.w1, self.w2],
        ):
            rows.append(StockMovement(
                tenant=self.c.tenant, product=self.c.case, qty=3, movement_type=kind,
                ref_doc_type=ref, from_warehouse=w_from, to_warehouse=w_to,
            ))
        StockMovement.objects.bulk_create(rows)
        self.rows = list(StockMovement.objects.filter(tenant=self.c.tenant))

    def test_every_movement_has_exactly_one_kind_and_the_filter_agrees(self):
        seen = {}
        for key in flows.KIND_LABELS:
            ids = set(StockMovement.objects.filter(flows.kind_q(key)).values_list("id", flat=True))
            want = {m.id for m in self.rows if flows.kind_of(m.movement_type, m.ref_doc_type) == key}
            self.assertEqual(ids, want, key)
            for pk in ids:
                self.assertNotIn(pk, seen, "同一筆異動被兩個類別篩到")
                seen[pk] = key
        self.assertEqual(len(seen), len(self.rows))       # 每一筆都有類別

    def test_kind_names_are_four_characters_and_columns_two(self):
        self.assertEqual({len(v) for v in flows.KIND_LABELS.values()}, {4})
        self.assertEqual({len(v) for v in flows.COLUMN_LABELS.values()}, {2})

    def test_store_filter_agrees_with_what_changes_the_stores_quantity(self):
        for w in (self.w1, self.w2):
            ids = set(StockMovement.objects.filter(flows.touches_q(w.id)).values_list("id", flat=True))
            want = {
                m.id for m in self.rows
                if any(wid == w.id for wid, _ in flows.deltas(
                    m.movement_type, m.from_warehouse_id, m.to_warehouse_id, m.qty))
            }
            self.assertEqual(ids, want)

    def test_columns_always_add_up_to_the_change_in_quantity(self):
        for m in self.rows:
            change = dict.fromkeys((self.w1.id, self.w2.id), 0)
            for wid, delta in flows.deltas(m.movement_type, m.from_warehouse_id, m.to_warehouse_id, m.qty):
                change[wid] += delta
            got = dict.fromkeys((self.w1.id, self.w2.id), 0)
            for wid, column, amount in flows.effects(
                m.movement_type, m.ref_doc_type, m.from_warehouse_id, m.to_warehouse_id, m.qty,
            ):
                self.assertIn(column, flows.COLUMNS)
                got[wid] += amount * flows.SIGN[column]
            self.assertEqual(got, change, (m.movement_type, m.ref_doc_type))

    def test_direction_matches_the_daily_check(self):
        # 調撥的兩筆都寫了來源與目的:派發只扣來源,確認才加到目的
        a, b = self.w1.id, self.w2.id
        self.assertEqual(flows.deltas(T.TRANSFER_OUT, a, b, 4), [(a, -4)])
        self.assertEqual(flows.deltas(T.TRANSFER_IN, a, b, 4), [(b, 4)])
        self.assertEqual(flows.deltas(T.PURCHASE_IN, None, a, 5), [(a, 5)])
        self.assertEqual(flows.deltas(T.VOID, None, None, 1), [])

    def test_voids_go_back_into_the_column_they_came_from(self):
        a, b = self.w1.id, self.w2.id
        e = flows.effects
        self.assertEqual(e(T.PURCHASE_IN, "purchase_order", None, a, 5), [(a, "purchase", 5)])
        self.assertEqual(e(T.TRADE_IN, "sales_order", None, a, 1), [(a, "purchase", 1)])
        self.assertEqual(e(T.VOID, "purchase_order", a, None, 5), [(a, "purchase", -5)])
        self.assertEqual(e(T.SALE_OUT, "sales_order", a, None, 2), [(a, "sale", 2)])
        self.assertEqual(e(T.PARTS_TRANSFER, "sales_order", a, None, 2), [(a, "sale", 2)])
        self.assertEqual(e(T.RETURN_IN, "sales_order", None, a, 2), [(a, "sale", -2)])        # 銷貨作廢
        self.assertEqual(e(T.RETURN_IN, "sales_return", None, a, 2), [(a, "sale_return", 2)])
        self.assertEqual(e(T.VOID, "sales_return", a, None, 2), [(a, "sale_return", -2)])
        self.assertEqual(e(T.TRANSFER_OUT, "transfer_order", a, b, 4), [(a, "transfer_out", 4)])
        self.assertEqual(e(T.TRANSFER_IN, "transfer_order", a, b, 4), [(b, "transfer_in", 4)])
        # 還在路上就作廢:只回到來源;確認過才作廢:目的門市的調入也不算了
        self.assertEqual(e(T.VOID, "transfer_order", None, a, 4), [(a, "transfer_out", -4)])
        self.assertEqual(
            e(T.VOID, "transfer_order", b, a, 4), [(a, "transfer_out", -4), (b, "transfer_in", -4)])
        self.assertEqual(e(T.REPAIR_USAGE, "repair_order", a, None, 1), [(a, "usage", 1)])
        self.assertEqual(e(T.ADJUST, "repair_order_reopen", None, a, 1), [(a, "usage", -1)])
        self.assertEqual(e(T.ADJUST, "repair_order_shortage", None, a, 1), [(a, "adjust", 1)])
        self.assertEqual(e("brand_new_type", "", a, b, 2), [(b, "adjust", 2), (a, "adjust", -2)])

    def test_what_is_on_the_way(self):
        a, b = self.w1.id, self.w2.id
        d = flows.transit_delta
        self.assertEqual(d(T.TRANSFER_OUT, "transfer_order", a, b, 4), 4)
        self.assertEqual(d(T.TRANSFER_IN, "transfer_order", a, b, 4), -4)
        self.assertEqual(d(T.VOID, "transfer_order", None, a, 4), -4)      # 還在路上就作廢
        self.assertEqual(d(T.VOID, "transfer_order", b, a, 4), 0)          # 確認過才作廢:不經過路上
        self.assertEqual(d(T.VOID, "transfer_order", None, None, 1), 0)    # 只是紀錄
        self.assertEqual(d(T.VOID, "purchase_order", None, a, 4), 0)
        self.assertEqual(d(T.SALE_OUT, "sales_order", a, None, 1), 0)


class Shop:
    """一家做過各種事的店(都是今天做的):

    手機:進 3 支 → 賣 IMEI1 → 賣 IMEI2 又整張退(當成這一版之前退的、還停在「已退」)→ 剩 IMEI3 在庫。
    皮套:進 10 → 賣 2 → 調 4 到第二家(確認)→ 再調 1(還在路上)→ 賣 1 又作廢 → 另外進 3 又整張作廢。
    """

    def __init__(self, code="a", tag="甲"):
        c = self.c = Company(code, f"{tag}通訊行", tag)
        self.w1, self.w2 = c.warehouses
        self.po = c.purchase(phone_serials=[f"{tag}IMEI1", f"{tag}IMEI2", f"{tag}IMEI3"], case_qty=10)
        self.so1 = c.sell(serial_no=f"{tag}IMEI1", case_qty=2)
        self.so2 = c.sell(serial_no=f"{tag}IMEI2")
        self.sr = c._post("/api/v1/sales-returns/", {"original_so": self.so2["id"], "payment_method": "cash"})
        # 2026-10-23 起銷退直接回在庫;報表的「已退」只剩以前退的,這裡放一台以前退的(報表照舊要分得出來)
        ProductSerial.objects.filter(tenant=c.tenant, serial_no=f"{tag}IMEI2").update(status="returned")
        c.transfer(4)
        self.pending = c._post("/api/v1/transfer-orders/", {
            "from_warehouse": self.w1.id, "to_warehouse": self.w2.id,
            "items": [{"product": c.case.id, "qty": 1}],
        })
        so3 = c.sell(case_qty=1)
        assert c.admin.post(f"/api/v1/sales-orders/{so3['id']}/void/").status_code == 200
        po2 = c.purchase(warehouse=self.w2, case_qty=3)
        assert c.admin.post(f"/api/v1/purchase-orders/{po2['id']}/void/").status_code == 200

    def flow(self, client=None, **params):
        r = (client or self.c.admin).get(FLOW, {"from": today(), "to": today(), **params})
        assert r.status_code == 200, r.content.decode()
        return r.json()

    @staticmethod
    def row(data, product):
        return next((r for r in data["rows"] if r["product"] == product.id), None)


class StockFlowTests(TestCase):
    def setUp(self):
        self.s = Shop()
        self.c = self.s.c

    def test_company_numbers(self):
        data = self.s.flow()
        self.assertTrue(data["with_transit"])
        phone, case = Shop.row(data, self.c.phone), Shop.row(data, self.c.case)
        self.assertEqual(
            {k: phone[k] for k in ("opening", "purchase", "sale", "sale_return", "closing", "returned")},
            {"opening": 0, "purchase": 3, "sale": 2, "sale_return": 1, "closing": 2, "returned": 1},
        )
        # 皮套:進 10(另外 3 個進了又作廢 = 0)、賣 2(另外 1 個賣了又作廢 = 0)、調出 5、調入 4、還有 1 個在路上
        self.assertEqual(
            {k: case[k] for k in ("opening", "purchase", "sale", "transfer_out", "transfer_in", "closing", "transit")},
            {"opening": 0, "purchase": 10, "sale": 2, "transfer_out": 5, "transfer_in": 4, "closing": 7, "transit": 1},
        )
        self.assertEqual([c["label"] for c in data["columns"]], ["進貨", "銷貨", "銷退", "調入", "調出", "領用", "換貨", "調整"])
        self.assertEqual(data["totals"]["closing"], 9)
        self.assertEqual(data["totals"]["transit"], 1)

    def test_every_row_adds_up_and_closing_is_what_is_on_the_books(self):
        for wid in (None, self.s.w1.id, self.s.w2.id):
            data = self.s.flow(**({"warehouse": wid} if wid else {}))
            for row in data["rows"]:
                self.assertTrue(balanced(row), row)
                serials = ProductSerial.objects.filter(
                    tenant=self.c.tenant, product_id=row["product"], warehouse__isnull=False,
                    status__in=["in_stock", "returned"])
                balances = StockBalance.objects.filter(tenant=self.c.tenant, product_id=row["product"])
                if wid:
                    serials, balances = serials.filter(warehouse_id=wid), balances.filter(warehouse_id=wid)
                self.assertEqual(row["closing"], serials.count() + sum(b.qty for b in balances), row)

    def test_stores_add_up_to_the_company(self):
        whole = self.s.flow()
        one, two = self.s.flow(warehouse=self.s.w1.id), self.s.flow(warehouse=self.s.w2.id)
        self.assertFalse(one["with_transit"])
        for key in ("opening", *flows.COLUMNS, "closing", "returned"):
            self.assertEqual(whole["totals"][key], one["totals"][key] + two["totals"][key], key)
        case = Shop.row(two, self.c.case)
        # 第二家:調入 4(路上的那 1 個還沒算)、進了 3 又作廢 = 0
        self.assertEqual((case["transfer_in"], case["purchase"], case["closing"]), (4, 0, 4))
        self.assertEqual(Shop.row(one, self.c.case)["transit"], 0)     # 在途只有全公司那一張算

    def test_goods_on_the_way_come_back_when_confirmed_or_voided(self):
        r = self.c.admin.post(f"/api/v1/transfer-orders/{self.s.pending['id']}/confirm/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        case = Shop.row(self.s.flow(), self.c.case)
        self.assertEqual((case["transfer_in"], case["transfer_out"], case["closing"], case["transit"]), (5, 5, 8, 0))
        # 確認過才作廢:兩邊都沖回去
        r = self.c.admin.post(f"/api/v1/transfer-orders/{self.s.pending['id']}/void/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        case = Shop.row(self.s.flow(), self.c.case)
        self.assertEqual((case["transfer_in"], case["transfer_out"], case["closing"], case["transit"]), (4, 4, 8, 0))
        self.assertTrue(balanced(case))

    def test_each_store_only_gets_its_own_side_of_a_voided_transfer(self):
        # 確認過才作廢的那一筆異動同時動到兩家門市(目的門市拿走、來源門市加回):各家只算自己那一邊
        self.c.admin.post(f"/api/v1/transfer-orders/{self.s.pending['id']}/confirm/", {}, format="json")
        r = self.c.admin.post(f"/api/v1/transfer-orders/{self.s.pending['id']}/void/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        one = Shop.row(self.s.flow(warehouse=self.s.w1.id), self.c.case)
        two = Shop.row(self.s.flow(warehouse=self.s.w2.id), self.c.case)
        self.assertEqual((one["transfer_out"], one["transfer_in"], one["closing"]), (4, 0, 4))
        self.assertEqual((two["transfer_out"], two["transfer_in"], two["closing"]), (0, 4, 4))
        self.assertTrue(balanced(one) and balanced(two))
        for wid in (self.s.w1.id, self.s.w2.id):
            rows = self.c.admin.get(MOVES, {
                "from": today(), "to": today(), "warehouse": wid, "kind": "transfer_void", "export": "1",
            }).json()["results"]
            self.assertEqual(len(rows), 1)
            self.assertEqual([e["warehouse"] for e in rows[0]["effects"]], [wid])      # 只留這一家的那一邊
        both = self.c.admin.get(MOVES, {
            "from": today(), "to": today(), "kind": "transfer_void", "export": "1"}).json()["results"]
        self.assertEqual(sorted(e["delta"] for e in both[0]["effects"]), [-1, 1])       # 全公司:兩邊都看得到

    def test_a_phone_on_the_way_is_counted_too(self):
        unit = ProductSerial.objects.get(tenant=self.c.tenant, serial_no="甲IMEI3")
        self.c._post("/api/v1/transfer-orders/", {
            "from_warehouse": self.s.w1.id, "to_warehouse": self.s.w2.id,
            "items": [{"product": self.c.phone.id, "qty": 1, "serial_ids": [unit.id]}],
        })
        phone = Shop.row(self.s.flow(), self.c.phone)
        # 原本在店 2 台(1 在庫 + 1 已退):在庫的那一台上路了
        self.assertEqual((phone["transfer_out"], phone["closing"], phone["returned"], phone["transit"]), (1, 1, 1, 1))
        self.assertTrue(balanced(phone))
        self.assertEqual(self.s.flow()["totals"]["transit"], 2)          # 連同路上的那 1 個皮套

    def test_voiding_on_the_road_puts_it_back_at_the_source(self):
        r = self.c.admin.post(f"/api/v1/transfer-orders/{self.s.pending['id']}/void/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        case = Shop.row(self.s.flow(), self.c.case)
        self.assertEqual((case["transfer_out"], case["closing"], case["transit"]), (4, 8, 0))

    def test_voided_return_is_no_longer_counted(self):
        r = self.c.admin.post(f"/api/v1/sales-returns/{self.s.sr['id']}/void/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        phone = Shop.row(self.s.flow(), self.c.phone)
        self.assertEqual((phone["sale"], phone["sale_return"], phone["closing"], phone["returned"]), (2, 0, 1, 0))
        self.assertTrue(balanced(phone))


class PastPeriodTests(TestCase):
    """異動發生在不同的日子:期末是從現在的庫存倒推回去的,前一段的期末要 = 後一段的期初。"""

    def setUp(self):
        self.s = Shop()
        self.c = self.s.c
        now = timezone.now()
        t = self.c.tenant
        moves = StockMovement.objects.filter(tenant=t)
        # 進貨 = 三天前;第一張銷貨 = 兩天前;其餘(第二張銷貨、銷退、調撥、作廢)= 今天
        moves.filter(ref_doc_type="purchase_order", ref_doc_id=self.s.po["id"]).update(
            created_at=now - timedelta(days=3))
        moves.filter(ref_doc_type="sales_order", ref_doc_id=self.s.so1["id"]).update(
            created_at=now - timedelta(days=2))
        # 今天另外賣 1 個皮套又整張退:數量不變,但配件的銷退不能被算成「已退」(那是序號商品才有的狀態)
        so = self.c.sell(case_qty=1)
        self.c._post("/api/v1/sales-returns/", {"original_so": so["id"], "payment_method": "cash"})

    def flow(self, start, end, **params):
        r = self.c.admin.get(FLOW, {
            "from": today() - timedelta(days=start), "to": today() - timedelta(days=end), **params})
        self.assertEqual(r.status_code, 200, r.content.decode())
        return r.json()

    def test_a_period_in_the_past(self):
        data = self.flow(2, 1)
        phone, case = Shop.row(data, self.c.phone), Shop.row(data, self.c.case)
        self.assertEqual((phone["opening"], phone["sale"], phone["closing"], phone["returned"]), (3, 1, 2, 0))
        self.assertEqual((case["opening"], case["sale"], case["closing"], case["transit"]), (10, 2, 8, 0))
        self.assertEqual(case["returned"], 0)
        self.assertEqual(case["purchase"], 0)             # 進貨在這段期間之前
        self.assertTrue(balanced(phone) and balanced(case))

    def test_closing_carries_into_the_next_opening(self):
        for wid in (None, self.s.w1.id, self.s.w2.id):
            extra = {"warehouse": wid} if wid else {}
            before, after = self.flow(5, 1, **extra), self.flow(0, 0, **extra)
            for product in (self.c.phone, self.c.case):
                a, b = Shop.row(before, product), Shop.row(after, product)
                self.assertEqual(a["closing"] if a else 0, b["opening"] if b else 0, (wid, product.name))

    def test_before_anything_happened(self):
        data = self.flow(9, 6)
        self.assertEqual(data["rows"], [])
        self.assertEqual(data["totals"]["closing"], 0)

    def test_quiet_products_are_listed_unless_asked_not_to(self):
        # 昨天一整天沒有任何進出:東西還在店裡,月底盤點要看得到(紅隊第 3 條)
        data = self.flow(1, 1)
        case = Shop.row(data, self.c.case)
        self.assertEqual((case["opening"], case["closing"]), (8, 8))
        self.assertFalse(any(case[c] for c in flows.COLUMNS))
        self.assertEqual(self.flow(1, 1, moved="1")["rows"], [])
        self.assertEqual(len(self.flow(2, 2, moved="1")["rows"]), 2)     # 兩天前賣了手機與皮套

    def test_sold_then_voided_still_counts_as_having_moved(self):
        # 複審首輪:期間內只有「賣了又作廢」,銷貨那一欄沖成 0,但它有進出 ——「只看有進出」不能把它藏起來
        from apps.catalog.models import Product

        quiet = Product.objects.create(
            tenant=self.c.tenant, category=self.c.cat_case, name="很少動的皮套", requires_serial=False,
            list_price=200)
        po = self.c._post("/api/v1/purchase-orders/", {
            "supplier": self.c.supplier.id, "warehouse": self.s.w1.id, "tax_method": "untaxed",
            "items": [{"product": quiet.id, "qty": 5, "unit_price": "80"}],
        })
        StockMovement.objects.filter(
            tenant=self.c.tenant, ref_doc_type="purchase_order", ref_doc_id=po["id"],
        ).update(created_at=timezone.now() - timedelta(days=3))
        so = self.c._post("/api/v1/sales-orders/", {
            "customer": self.c.customer.id, "warehouse": self.s.w1.id, "tax_method": "untaxed",
            "sales_person": self.c.sales_person.id,
            "items": [{"product": quiet.id, "qty": 1, "unit_price": "200"}],
            "payments": [{"method": "cash", "amount": "200"}],
        })
        self.assertEqual(self.c.admin.post(f"/api/v1/sales-orders/{so['id']}/void/").status_code, 200)
        row = Shop.row(self.flow(0, 0, moved="1"), quiet)
        self.assertIsNotNone(row)
        self.assertEqual((row["opening"], row["sale"], row["closing"]), (5, 0, 5))
        self.assertTrue(balanced(row))
        self.assertIsNone(Shop.row(self.flow(1, 1, moved="1"), quiet))          # 昨天真的沒有進出
        self.assertIsNotNone(Shop.row(self.flow(1, 1), quiet))                  # 沒勾的時候有庫存就列


class OneMomentTests(TransactionTestCase):
    """不包在測試的交易裡跑一次:進銷存表整張讀的是同一個時間點(異動與現在的庫存之間有人開單也不會差一筆)。"""

    def test_the_whole_report_reads_one_moment(self):
        s = Shop()
        with CaptureQueriesContext(connection) as seen:
            data = s.flow()
        sql = [q["sql"] for q in seen.captured_queries]
        first = next(i for i, q in enumerate(sql) if "REPEATABLE READ" in q)
        counted = [i for i, q in enumerate(sql) if "inventory_stockmovement" in q or "inventory_stockbalance" in q]
        self.assertTrue(counted and all(i > first for i in counted), sql)
        self.assertTrue(all(balanced(r) for r in data["rows"]))
        self.assertEqual(Shop.row(data, s.c.case)["closing"], 7)
        self.assertFalse(connection.in_atomic_block)          # 讀完就放掉,不留著交易
        self.assertEqual(s.c.admin.get(MOVES).status_code, 200)


class FlowAccessTests(TestCase):
    def setUp(self):
        self.s = Shop()
        self.c = self.s.c
        self.other = Shop("b", "乙")

    def test_locked_account_only_gets_its_own_store(self):
        mine = self.s.flow(client=self.c.clerk)
        self.assertEqual(mine["warehouse"], self.s.w1.id)
        self.assertFalse(mine["with_transit"])
        asked = self.s.flow(client=self.c.clerk, warehouse=self.s.w2.id)       # 網址帶別家的編號沒有用
        self.assertEqual(asked["warehouse"], self.s.w1.id)
        self.assertEqual(asked["rows"], mine["rows"])
        self.assertEqual(Shop.row(mine, self.c.case)["closing"], 3)

    def test_other_companies_are_invisible(self):
        data = self.s.flow()
        self.assertEqual({r["product"] for r in data["rows"]}, {self.c.phone.id, self.c.case.id})
        self.assertEqual(self.s.flow(warehouse=self.other.w1.id)["rows"], [])   # 別家公司的門市 = 什麼都沒有
        self.assertEqual(self.s.flow(category=self.other.c.cat_case.id)["rows"], [])

    def test_filters(self):
        self.assertEqual(
            [r["product"] for r in self.s.flow(category=self.c.cat_case.id)["rows"]], [self.c.case.id])
        self.assertEqual([r["product"] for r in self.s.flow(search="iphone 128")["rows"]], [self.c.phone.id])
        self.assertEqual([r["product"] for r in self.s.flow(search=self.c.case.sku)["rows"]], [self.c.case.id])
        self.assertEqual(self.s.flow(search="iphone 皮套")["rows"], [])          # 每一段都要有
        only = self.s.flow(search="iphone")
        self.assertEqual(only["totals"]["closing"], 2)                           # 合計跟著條件走

    def test_bad_conditions_are_refused(self):
        get = self.c.admin.get
        day = today()
        self.assertEqual(get(FLOW, {"from": day, "to": day - timedelta(days=1)}).status_code, 400)
        self.assertEqual(get(FLOW, {"from": day - timedelta(days=366), "to": day}).status_code, 400)
        self.assertEqual(get(FLOW, {"from": day - timedelta(days=365), "to": day}).status_code, 200)
        self.assertEqual(get(FLOW, {"from": "10/12"}).status_code, 400)
        self.assertEqual(get(FLOW, {"category": "abc"}).status_code, 400)
        self.assertEqual(get(MOVES, {"kind": "nope"}).status_code, 400)
        self.assertEqual(get(SERIALS, {"status": "nope"}).status_code, 400)
        self.assertEqual(get(SERIALS, {"sold_from": day, "sold_to": day - timedelta(days=1)}).status_code, 400)

    def test_needs_login(self):
        from rest_framework.test import APIClient

        for url in (FLOW, MOVES, SERIALS):
            self.assertIn(APIClient().get(url).status_code, (401, 403))


class MovementReportTests(TestCase):
    def setUp(self):
        self.s = Shop()
        self.c = self.s.c

    def rows(self, client=None, **params):
        r = (client or self.c.admin).get(MOVES, {"from": today(), "to": today(), "export": "1", **params})
        self.assertEqual(r.status_code, 200, r.content.decode())
        return r.json()

    def test_every_movement_is_listed_with_its_document(self):
        data = self.rows()
        self.assertEqual(data["count"], StockMovement.objects.filter(tenant=self.c.tenant).count())
        self.assertFalse(data["truncated"])
        self.assertEqual([k["label"] for k in data["kinds"]][:3], ["進貨入庫", "收購入庫", "銷貨出庫"])
        kinds = {r["kind_label"] for r in data["results"]}
        self.assertEqual(kinds, {"進貨入庫", "銷貨出庫", "銷退入庫", "調撥出庫", "調撥入庫", "銷貨作廢", "進貨作廢"})
        bought = [r for r in data["results"] if r["kind"] == "purchase" and r["serial_no"] == "甲IMEI1"][0]
        self.assertEqual(bought["doc"], {"kind": "purchase", "id": self.s.po["id"], "no": self.s.po["no"]})
        self.assertEqual(bought["effects"], [{"warehouse": self.s.w1.id, "name": self.s.w1.name, "delta": 1}])
        self.assertEqual((bought["sku"], bought["name"]), (self.c.phone.sku, self.c.phone.name))
        back = [r for r in data["results"] if r["kind"] == "sale_return"][0]
        self.assertEqual(back["doc"], {"kind": "sale_return", "id": self.s.sr["id"], "no": self.s.sr["no"]})
        out = [r for r in data["results"] if r["kind"] == "transfer_out"][0]
        self.assertEqual((out["from_name"], out["to_name"]), (self.s.w1.name, self.s.w2.name))
        self.assertEqual([e["delta"] for e in out["effects"]], [-out["qty"]])
        self.assertTrue(all(r["note"] == "" for r in data["results"]))       # 一般的備註只是把單號再講一次

    def test_document_is_found_by_its_number_not_by_the_stored_id(self):
        # 還原備份之後每張單的編號都換了,異動上記的那個數字不會跟著換:連結要照備註裡的單號找
        sale = StockMovement.objects.filter(
            tenant=self.c.tenant, movement_type=T.SALE_OUT, ref_doc_id=self.s.so1["id"])
        self.assertEqual(sale.count(), 2)
        sale.update(ref_doc_id=self.s.so2["id"])                    # 指到另一張銷貨單
        StockMovement.objects.filter(
            tenant=self.c.tenant, ref_doc_type="purchase_order", ref_doc_id=self.s.po["id"],
        ).update(ref_doc_id=987654)                                  # 指到不存在的單
        rows = self.rows()["results"]
        sold = [r for r in rows if r["kind"] == "sale" and r["serial_no"] == "甲IMEI1"][0]
        self.assertEqual(sold["doc"], {"kind": "sale", "id": self.s.so1["id"], "no": self.s.so1["no"]})
        bought = [r for r in rows if r["kind"] == "purchase" and r["serial_no"] == "甲IMEI1"][0]
        self.assertEqual(bought["doc"], {"kind": "purchase", "id": self.s.po["id"], "no": self.s.po["no"]})
        # 備註裡沒有單號、也不是個人收購:不猜
        StockMovement.objects.filter(pk=sold["id"]).update(note="")
        again = [r for r in self.rows()["results"] if r["id"] == sold["id"]][0]
        self.assertIsNone(again["doc"])

    def test_one_product_means_exactly_that_product(self):
        # 複審首輪:從進銷存表點品名過來要是「那一個商品」。用品號找是包含,LC-000001 會連 XLC-000001 一起列
        from apps.catalog.models import Category, Product

        longer = Category.objects.create(tenant=self.c.tenant, code="XLC", name="另一種皮套")
        twin = Product.objects.create(
            tenant=self.c.tenant, category=longer, name="別的皮套", requires_serial=False, list_price=100)
        self.assertIn(self.c.case.sku, twin.sku)                     # 品號互相包含
        self.c._post("/api/v1/purchase-orders/", {
            "supplier": self.c.supplier.id, "warehouse": self.s.w1.id, "tax_method": "untaxed",
            "items": [{"product": twin.id, "qty": 3, "unit_price": "50"}],
        })
        by_words = {r["product"] for r in self.rows(search=self.c.case.sku)["results"]}
        self.assertEqual(by_words, {self.c.case.id, twin.id})          # 用找的:兩個都在
        exact = self.rows(product=self.c.case.id)["results"]
        self.assertEqual({r["product"] for r in exact}, {self.c.case.id})
        flow = Shop.row(self.s.flow(), self.c.case)
        moved = sum(e["delta"] for r in exact for e in r["effects"])
        self.assertEqual(moved, flow["closing"] - flow["opening"])    # 跟進銷存表那一列是同一批
        phone = self.rows(product=self.c.phone.id)["results"]         # 序號商品:照那一台的商品
        self.assertEqual({r["product"] for r in phone}, {self.c.phone.id})
        self.assertTrue(all(r["serial_no"] for r in phone))
        other = Shop("b", "乙")
        self.assertEqual(self.rows(product=other.c.case.id)["count"], 0)       # 別家公司的商品 = 什麼都沒有
        self.assertEqual(self.c.admin.get(MOVES, {"product": "abc"}).status_code, 400)

    def test_changes_listed_equal_the_flow_report(self):
        # 兩張表是同一份紀錄:異動查詢逐筆加起來 = 進銷存表的 期末 − 期初
        for wid in (self.s.w1.id, self.s.w2.id):
            flow = self.s.flow(warehouse=wid)
            moved = {}
            for r in self.rows(warehouse=wid)["results"]:
                self.assertEqual({e["warehouse"] for e in r["effects"]}, {wid})
                moved[r["product"]] = moved.get(r["product"], 0) + sum(e["delta"] for e in r["effects"])
            for row in flow["rows"]:
                self.assertEqual(moved.get(row["product"], 0), row["closing"] - row["opening"], row)

    def test_filters(self):
        self.assertEqual({r["kind"] for r in self.rows(kind="sale_void")["results"]}, {"sale_void"})
        self.assertEqual({r["name"] for r in self.rows(category=self.c.cat_case.id)["results"]}, {self.c.case.name})
        self.assertEqual({r["serial_no"] for r in self.rows(search="IMEI2")["results"]}, {"甲IMEI2"})
        self.assertEqual(self.rows(search="甲-imei 皮套")["results"], [])        # 每一段都要有
        self.assertEqual({r["serial_no"] for r in self.rows(search="甲-imei2")["results"]}, {"甲IMEI2"})
        self.assertEqual({r["name"] for r in self.rows(search="皮套")["results"]}, {self.c.case.name})
        second = self.rows(warehouse=self.s.w2.id)["results"]
        # 第二家:調入 4、進 3、進貨作廢 3;派發的那兩筆不動它的數量,不列
        self.assertEqual(sorted(r["kind"] for r in second), ["purchase", "purchase_void", "transfer_in"])
        yesterday = today() - timedelta(days=1)
        self.assertEqual(self.c.admin.get(MOVES, {"from": yesterday, "to": yesterday}).json()["count"], 0)

    def test_pages(self):
        r = self.c.admin.get(MOVES, {"from": today(), "to": today(), "page_size": 5})
        body = r.json()
        self.assertEqual(len(body["results"]), 5)
        self.assertIsNotNone(body["next"])
        self.assertEqual(body["count"], StockMovement.objects.filter(tenant=self.c.tenant).count())
        newest = StockMovement.objects.filter(tenant=self.c.tenant).order_by("-created_at", "-id").first()
        self.assertEqual(body["results"][0]["id"], newest.id)                 # 新的在前面

    def test_locked_account_only_sees_its_own_store(self):
        mine = self.rows(client=self.c.clerk)
        self.assertEqual(mine["warehouse"], self.s.w1.id)
        asked = self.rows(client=self.c.clerk, warehouse=self.s.w2.id)
        self.assertEqual([r["id"] for r in asked["results"]], [r["id"] for r in mine["results"]])
        self.assertNotIn("purchase_void", {r["kind"] for r in mine["results"]})   # 那是第二家的事
        self.assertEqual({e["warehouse"] for r in mine["results"] for e in r["effects"]}, {self.s.w1.id})
        # 原本就有的那一支異動端點也一樣(不能是繞過去的門)
        old = self.c.clerk.get("/api/v1/stock-movements/", {"page_size": 200}).json()["results"]
        for m in old:
            self.assertIn(self.s.w1.id, (m["from_warehouse"], m["to_warehouse"]))
        everything = self.c.admin.get("/api/v1/stock-movements/").json()["count"]
        self.assertGreater(everything, len(old))

    def test_other_companies_are_invisible(self):
        other = Shop("b", "乙")
        self.assertEqual({r["serial_no"] for r in self.rows(search="IMEI")["results"]}, {"甲IMEI1", "甲IMEI2", "甲IMEI3"})
        self.assertEqual(self.rows(warehouse=other.w1.id)["count"], 0)
        # 兩家公司的單號一樣(各自從 000001 編起):連結要是自己公司的那一張
        self.assertEqual(other.po["no"], self.s.po["no"])
        self.assertNotEqual(other.po["id"], self.s.po["id"])
        mine = {r["doc"]["id"] for r in self.rows(kind="purchase")["results"] if r["doc"]["no"] == self.s.po["no"]}
        self.assertEqual(mine, {self.s.po["id"]})
        from apps.sales.models import SalesOrder

        sold = {r["doc"]["id"] for r in self.rows(kind="sale")["results"]}
        self.assertTrue({self.s.so1["id"], self.s.so2["id"]} <= sold)
        self.assertEqual(SalesOrder.objects.filter(tenant=self.c.tenant, pk__in=sold).count(), len(sold))

    def test_personal_details_and_odd_rows(self):
        t = self.c.tenant
        StockMovement.objects.create(
            tenant=t, product=self.c.case, qty=1, movement_type=T.TRADE_IN, to_warehouse=self.s.w1,
            ref_doc_type="sales_order", ref_doc_id=self.s.so1["id"], note="個人收購入庫 from 0911222333 王小明")
        StockMovement.objects.create(
            tenant=t, product=self.c.case, qty=2, movement_type=T.ADJUST, to_warehouse=self.s.w1,
            ref_doc_type="repair_order_shortage", ref_doc_id=999999, note="R-1 維修領用時帳上不足,補差 2")
        StockMovement.objects.create(
            tenant=t, product=self.c.case, qty=1, movement_type=T.VOID, ref_doc_type="transfer_order",
            ref_doc_id=self.s.pending["id"],
            note=f"調撥單 {self.s.pending['no']} 作廢(派發中);序號 X 當下為「已售」已脫離本單,跳過回滾")
        rows = {r["kind"]: r for r in self.rows()["results"] if r["kind"] in ("trade_in", "adjust", "transfer_void")}
        self.assertEqual(rows["trade_in"]["note"], "")                 # 賣家的電話姓名不進清單
        self.assertNotIn("0911222333", str(self.rows()))
        self.assertEqual(rows["adjust"]["note"], "R-1 維修領用時帳上不足,補差 2")
        self.assertIsNone(rows["adjust"]["doc"])                        # 那張單找不到:不給連結
        self.assertEqual(rows["transfer_void"]["effects"], [])          # 只是紀錄,不動數量
        self.assertEqual(
            rows["transfer_void"]["doc"],
            {"kind": "transfer", "id": self.s.pending["id"], "no": self.s.pending["no"]})
        self.assertIn("已脫離本單", rows["transfer_void"]["note"])


class SerialReportTests(TestCase):
    def setUp(self):
        self.s = Shop()
        self.c = self.s.c

    def rows(self, client=None, **params):
        r = (client or self.c.admin).get(SERIALS, {"export": "1", **params})
        self.assertEqual(r.status_code, 200, r.content.decode())
        return r.json()

    def test_what_is_in_the_store(self):
        data = self.rows(status="in_stock,returned")
        by_no = {r["serial_no"]: r for r in data["results"]}
        self.assertEqual(set(by_no), {"甲IMEI2", "甲IMEI3"})            # 已退的那一台也在(盤點點得到)
        self.assertEqual((by_no["甲IMEI2"]["status_label"], by_no["甲IMEI2"]["store"]), ("已退", self.s.w1.name))
        self.assertIsNone(by_no["甲IMEI2"]["sale"])
        unit = by_no["甲IMEI3"]
        self.assertEqual(unit["source"], {
            "kind": "purchase", "label": self.c.supplier.name,
            "doc": {"kind": "purchase", "id": self.s.po["id"], "no": self.s.po["no"]},
        })
        self.assertEqual((unit["sku"], unit["name"], unit["cost"]), (self.c.phone.sku, self.c.phone.name, "20000.00"))
        self.assertEqual(data["cost_total"], "40000.00")
        # 2026-10-12 多「盤虧」(盤點核准之後少的那幾台)
        self.assertEqual([s["label"] for s in data["statuses"]], ["在庫", "調撥中", "已售", "已退", "廠商換貨中", "作廢", "盤虧"])

    def test_sold_units_show_who_sold_them_and_when(self):
        data = self.rows(status="sold")
        self.assertEqual([r["serial_no"] for r in data["results"]], ["甲IMEI1"])
        unit = data["results"][0]
        self.assertEqual(unit["sale"]["doc"], {"kind": "sale", "id": self.s.so1["id"], "no": self.s.so1["no"]})
        self.assertEqual(unit["sale"]["date"], today().isoformat())
        self.assertEqual(unit["store"], self.s.w1.name)                 # 已售的看是哪一家賣的
        self.assertEqual(len(self.rows(status="sold", warehouse=self.s.w1.id)["results"]), 1)
        self.assertEqual(len(self.rows(status="sold", warehouse=self.s.w2.id)["results"]), 0)
        yesterday = today() - timedelta(days=1)
        self.assertEqual(len(self.rows(sold_from=today(), sold_to=today())["results"]), 1)
        self.assertEqual(len(self.rows(sold_to=yesterday)["results"]), 0)
        self.assertEqual(len(self.rows(sold_from=yesterday)["results"]), 1)

    def test_filters(self):
        self.assertEqual(len(self.rows()["results"]), 3)                # 沒給狀態 = 全部
        self.assertEqual({r["serial_no"] for r in self.rows(search="imei3")["results"]}, {"甲IMEI3"})
        self.assertEqual(len(self.rows(search="iphone 128")["results"]), 3)
        self.assertEqual(len(self.rows(search="iphone 皮套")["results"]), 0)
        self.assertEqual(len(self.rows(supplier=self.c.supplier.id)["results"]), 3)
        self.assertEqual(len(self.rows(supplier=self.c.supplier.id + 999)["results"]), 0)
        yesterday = today() - timedelta(days=1)
        self.assertEqual(len(self.rows(received_from=today())["results"]), 3)
        self.assertEqual(len(self.rows(received_to=today())["results"]), 3)       # 迄日那一天整天都算
        self.assertEqual(len(self.rows(received_to=yesterday)["results"]), 0)
        self.assertEqual(len(self.rows(warehouse=self.s.w2.id)["results"]), 0)
        page = self.c.admin.get(SERIALS, {"page_size": 2}).json()
        self.assertEqual((len(page["results"]), page["count"]), (2, 3))
        self.assertEqual(page["cost_total"], "60000.00")                # 合計是全部的,不是這一頁

    def test_bought_from_a_customer_shows_no_personal_details(self):
        from apps.catalog.models import Product
        from apps.parties.models import Member

        used = Product.objects.create(
            tenant=self.c.tenant, category=self.c.cat_phone, name="甲 中古 iPhone 13", is_secondhand=True)
        member = Member.objects.create(tenant=self.c.tenant, name="王小明", phone="0911222333")
        r = self.c.admin.post("/api/v1/sales-orders/secondhand-acquisition/", {
            "member": member.id, "warehouse": self.s.w1.id, "product": used.id, "condition_grade": "A",
            "acquisition_price": "8000", "payment_method_code": "cash", "serial_no": "USED-1",
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content.decode())
        data = self.rows(search="USED-1")
        unit = data["results"][0]
        self.assertEqual((unit["source"]["kind"], unit["source"]["label"]), ("trade_in", "個人收購"))
        self.assertEqual(unit["source"]["doc"]["kind"], "sale")
        self.assertNotIn("王小明", str(data))
        self.assertNotIn("0911222333", str(data))
        # 同一台在另外兩張表上:進銷存表算在進貨,異動查詢叫收購入庫
        flow = Shop.row(self.s.flow(), used)
        self.assertEqual((flow["purchase"], flow["closing"]), (1, 1))
        moves = self.c.admin.get(MOVES, {"from": today(), "to": today(), "kind": "trade_in"}).json()
        self.assertEqual([m["serial_no"] for m in moves["results"]], ["USED-1"])
        self.assertEqual(moves["results"][0]["doc"], unit["source"]["doc"])      # 連到收購的那一張單
        self.assertNotIn("0911222333", str(moves))

    def test_everyone_sees_every_store_like_the_stock_page(self):
        self.c.purchase(warehouse=self.s.w2, phone_serials=["甲IMEI9"])
        mine = self.rows(client=self.c.clerk, status="in_stock")
        self.assertEqual({r["serial_no"] for r in mine["results"]}, {"甲IMEI3", "甲IMEI9"})

    def test_other_companies_are_invisible(self):
        other = Shop("b", "乙")
        self.assertEqual({r["serial_no"][0] for r in self.rows()["results"]}, {"甲"})
        self.assertEqual(self.rows(warehouse=other.w1.id)["results"], [])
        self.assertEqual(self.rows(supplier=other.c.supplier.id)["results"], [])

    def test_code_search_matches_the_registered_codes(self):
        unit = ProductSerial.objects.get(tenant=self.c.tenant, serial_no="甲IMEI3")
        from apps.inventory.identifiers import set_codes

        set_codes(unit, imei="", sn="SN-ABC-778", user=self.c.admin_user, may_change=True)
        self.assertEqual([r["id"] for r in self.rows(search="abc778")["results"]], [unit.id])
        self.assertEqual(self.rows(search="abc778")["results"][0]["sn"], "SN-ABC-778")
        # 去掉破折號才對得上的:打三個字以上才比(跟序號搜尋同一個門檻)
        self.assertEqual([r["id"] for r in self.rows(search="c77")["results"]], [unit.id])
        self.assertEqual(self.rows(search="c7")["results"], [])
        self.assertEqual(reports.CODE_SEARCH_MIN, 3)


class ReturnsAreBackInStockTests(TestCase):
    """2026-10-23 起銷退直接回在庫:過去那一段的「已退」不能因為之後的銷退 / 作廢銷退變出來(Codex 複審 P1)。"""

    def setUp(self):
        self.c = Company("a", "甲通訊行", "甲")
        self.c.purchase(phone_serials=["甲N1"])
        self.so = self.c.sell(serial_no="甲N1")
        StockMovement.objects.filter(tenant=self.c.tenant).update(created_at=timezone.now() - timedelta(days=2))

    def phone_on(self, days_ago):
        day = today() - timedelta(days=days_ago)
        r = self.c.admin.get(FLOW, {"from": day, "to": day})
        self.assertEqual(r.status_code, 200, r.content.decode())
        row = Shop.row(r.json(), self.c.phone)
        self.assertTrue(balanced(row), row)
        return row

    def test_a_return_after_the_period_is_not_counted_as_returned_back_then(self):
        self.c._post("/api/v1/sales-returns/", {"original_so": self.so["id"], "payment_method": "cash"})
        old = self.phone_on(2)
        self.assertEqual((old["closing"], old["returned"]), (0, 0))
        now = self.phone_on(0)
        self.assertEqual((now["sale_return"], now["closing"], now["returned"]), (1, 1, 0))

    def test_a_return_voided_later_was_in_stock_not_returned_that_day(self):
        sr = self.c._post("/api/v1/sales-returns/", {"original_so": self.so["id"], "payment_method": "cash"})
        StockMovement.objects.filter(tenant=self.c.tenant, ref_doc_type="sales_return").update(
            created_at=timezone.now() - timedelta(days=1))
        self.assertEqual(self.c.admin.post(f"/api/v1/sales-returns/{sr['id']}/void/", {}, format="json").status_code, 200)
        that_day = self.phone_on(1)
        self.assertEqual((that_day["closing"], that_day["returned"]), (1, 0))
