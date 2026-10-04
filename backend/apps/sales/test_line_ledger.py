"""銷貨 / 銷退明細存死「未稅、稅額、沖回成本」(資料底層規劃 2.5)。

重點:每一行加總要正好等於單頭;分幾次退完,沖回成本加總正好等於當初記的成本;
既有資料的回填跟現在存檔算出來的一模一樣。
"""
import importlib
import random
from decimal import Decimal

from django.apps import apps as django_apps
from django.test import TestCase, TransactionTestCase

from apps.backup.tests.factory import Company
from apps.inventory.models import ProductSerial
from apps.sales.models import SalesOrder, SalesOrderItem, SalesReturnItem
from apps.sales.services import _calc_tax, split_tax_by_line

backfill = importlib.import_module(
    "apps.sales.migrations.0016_line_untaxed_tax_return_cost"
).backfill

D = Decimal


def build_return(tenant, so_id, lines, warehouse=None, void=False, customer="same"):
    """直接建一張銷退(不經過 API、不過帳):舊資料的部分退貨,或拿來測 service 自己的檢查。
    lines = [(原銷貨明細, 數量, [序號 id...]), ...]"""
    from apps.sales.models import SalesReturn, SalesReturnItemSerial

    so = SalesOrder.objects.get(pk=so_id)
    sr = SalesReturn.objects.create(
        tenant=tenant, original_so=so, warehouse=warehouse or so.warehouse,
        customer=so.customer if customer == "same" else customer, member=so.member,
        payment_method="cash", is_void=void,
    )
    for n, (oi, qty, serial_ids) in enumerate(lines, start=1):
        item = SalesReturnItem.objects.create(
            tenant=tenant, sr=sr, original_item=oi, product=oi.product, qty=qty,
            unit_price=oi.unit_price, amount=oi.unit_price * qty, line_no=n,
        )
        for pos, sid in enumerate(serial_ids, start=1):
            SalesReturnItemSerial.objects.create(tenant=tenant, item=item, serial_id=sid, line_pos=pos)
    return sr


class SplitTests(TestCase):
    def test_lines_always_add_up_to_the_header(self):
        rng = random.Random(20261004)
        for method in ("taxable_included", "taxable_excluded", "untaxed", "tax_free"):
            for _ in range(300):
                amounts = [
                    D(rng.randint(-50000, 300000)) / 100 for _ in range(rng.randint(1, 9))
                ]
                subtotal, tax, total = _calc_tax(sum(amounts, D("0")), method)
                split = split_tax_by_line(amounts, method, subtotal, tax)
                self.assertIsNotNone(split, (method, amounts))
                self.assertEqual(sum(u for u, _ in split), subtotal)
                self.assertEqual(sum(t for _, t in split), tax)
                if method == "taxable_included":
                    for a, (u, t) in zip(amounts, split):
                        self.assertEqual(u + t, a)

    def test_rounding_goes_to_the_biggest_line(self):
        amounts = [D("100.00"), D("250.00"), D("100.00")]
        subtotal, tax, _ = _calc_tax(sum(amounts), "taxable_included")
        split = split_tax_by_line(amounts, "taxable_included", subtotal, tax)
        self.assertEqual(split[0], (D("95.24"), D("4.76")))
        self.assertEqual(split[2], (D("95.24"), D("4.76")))
        self.assertEqual(sum(u for u, _ in split), subtotal)

    def test_header_that_does_not_match_is_not_forced(self):
        self.assertIsNone(
            split_tax_by_line([D("100")], "taxable_included", D("50.00"), D("50.00"))
        )


class LedgerTests(TestCase):
    def setUp(self):
        self.c = Company("a", "甲通訊行", "甲")
        # 皮套成本做成除不盡:3 個 100 + 3 個 101 → 加權平均 100.5;再進 1 個 100 → 100.43
        self.c.purchase(phone_serials=["IMEI-1", "IMEI-2"], case_qty=3)
        self.c._post("/api/v1/purchase-orders/", {
            "supplier": self.c.supplier.id, "warehouse": self.c.wh.id, "tax_method": "untaxed",
            "items": [{"product": self.c.case.id, "qty": 3, "unit_price": "101"}],
        })
        self.c.purchase(case_qty=1)

    def sell(self, method, lines, pay):
        return self.c._post("/api/v1/sales-orders/", {
            "customer": self.c.customer.id, "warehouse": self.c.wh.id, "tax_method": method,
            "items": lines, "payments": [{"method": "cash", "amount": pay}],
        })

    def assert_lines_match_header(self, header, items):
        self.assertEqual(sum(D(i["untaxed_amount"]) for i in items), D(header["subtotal"]))
        self.assertEqual(sum(D(i["tax_amount"]) for i in items), D(header["tax_amount"]))

    def test_sale_taxable_included_stores_each_line(self):
        serial = ProductSerial.objects.get(serial_no="IMEI-1")
        so = self.sell("taxable_included", [
            {"product": self.c.phone.id, "qty": 1, "unit_price": "25000", "serial_ids": [serial.id]},
            {"product": self.c.case.id, "qty": 1, "unit_price": "390"},
            {"product": self.c.case.id, "qty": 1, "unit_price": "390"},
        ], "25780")
        self.assertEqual(D(so["total"]), D("25780"))
        self.assert_lines_match_header(so, so["items"])
        phone = so["items"][0]
        self.assertEqual(D(phone["untaxed_amount"]) + D(phone["tax_amount"]), D("25000"))

    def test_sale_taxable_excluded(self):
        so = self.sell("taxable_excluded", [
            {"product": self.c.case.id, "qty": 1, "unit_price": "33.30"},
            {"product": self.c.case.id, "qty": 1, "unit_price": "33.30"},
            {"product": self.c.case.id, "qty": 1, "unit_price": "33.30"},
        ], "104.90")
        self.assert_lines_match_header(so, so["items"])
        self.assertEqual([D(i["untaxed_amount"]) for i in so["items"]], [D("33.30")] * 3)

    def test_untaxed_sale_has_no_tax(self):
        so = self.sell("untaxed", [
            {"product": self.c.case.id, "qty": 1, "unit_price": "390"},
        ], "390")
        item = SalesOrderItem.objects.get(so_id=so["id"])
        self.assertEqual((item.untaxed_amount, item.tax_amount), (D("390.00"), D("0.00")))

    def returnable(self, so):
        r = self.c.admin.get(f"/api/v1/sales-returns/returnable/?sales_order={so['id']}")
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()

    def give_back(self, so):
        """整張退(銷退只能整張退,不送明細)。"""
        return self.c._post("/api/v1/sales-returns/", {
            "original_so": so["id"], "payment_method": "cash",
        })

    def test_whole_return_refunds_what_was_collected(self):
        # 第一行打折:2 個 × 390 只收 700
        so = self.sell("untaxed", [
            {"product": self.c.case.id, "qty": 2, "unit_price": "390", "amount": "700"},
            {"product": self.c.case.id, "qty": 1, "unit_price": "390"},
        ], "1090")
        back = self.give_back(so)
        self.assertEqual(D(back["total"]), D("1090"))
        self.assertEqual([D(i["amount"]) for i in back["items"]], [D("700"), D("390")])
        self.assertEqual([i["qty"] for i in back["items"]], [2, 1])
        lines = SalesOrderItem.objects.filter(so_id=so["id"]).order_by("line_no")
        self.assertEqual([D(i["cost_at_post"]) for i in back["items"]],
                         [line.cost_at_post for line in lines])
        self.assert_lines_match_header(back, back["items"])

    def test_a_sale_is_returned_only_once_unless_the_return_is_voided(self):
        so = self.sell("untaxed", [{"product": self.c.case.id, "qty": 1, "unit_price": "390"}], "390")
        first = self.give_back(so)
        r = self.c.admin.post("/api/v1/sales-returns/", {
            "original_so": so["id"], "payment_method": "cash"}, format="json")
        self.assertEqual(r.status_code, 400, r.content)
        self.assertIn("已經退過", str(r.json()))
        self.assertEqual(self.returnable(so)["returned_by"], first["no"])   # 畫面據此擋下
        r = self.c.admin.post(f"/api/v1/sales-returns/{first['id']}/void/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self.returnable(so)["returned_by"], "")
        self.give_back(so)

    def historic_return(self, so, line, qty, void=False, serial_ids=()):
        """舊資料裡的部分退貨(現在畫面已經不能這樣退,只有舊資料會有)。"""
        return build_return(self.c.tenant, so["id"], [(line, qty, list(serial_ids))], void=void)

    def test_serial_return_reverses_that_phone_cost(self):
        serial = ProductSerial.objects.get(serial_no="IMEI-2")
        so = self.sell("untaxed", [
            {"product": self.c.phone.id, "qty": 1, "unit_price": "25000", "serial_ids": [serial.id]},
        ], "25000")
        line = SalesOrderItem.objects.get(so_id=so["id"])
        back = self.give_back(so)
        self.assertEqual(D(back["items"][0]["cost_at_post"]), serial.purchase_unit_cost)
        self.assertEqual(D(back["items"][0]["cost_at_post"]), line.cost_at_post)

    def test_backfill_reproduces_what_saving_computes(self):
        self.c.purchase(case_qty=5)
        serial = ProductSerial.objects.get(serial_no="IMEI-1")
        orders = [
            self.sell("taxable_included", [
                {"product": self.c.phone.id, "qty": 1, "unit_price": "25000",
                 "serial_ids": [serial.id]},
                {"product": self.c.case.id, "qty": 2, "unit_price": "390"},
                {"product": self.c.case.id, "qty": 1, "unit_price": "390"},
            ], "26170"),
            self.sell("taxable_excluded", [
                {"product": self.c.case.id, "qty": 1, "unit_price": "33.30"},
                {"product": self.c.case.id, "qty": 2, "unit_price": "33.30"},
            ], "104.90"),
            # 三行各自四捨五入會多 1 分,零頭要補在最大那一行
            self.sell("taxable_included", [
                {"product": self.c.case.id, "qty": 1, "unit_price": "100"},
                {"product": self.c.case.id, "qty": 1, "unit_price": "100"},
                {"product": self.c.case.id, "qty": 1, "unit_price": "100"},
            ], "300"),
        ]
        case_line = SalesOrderItem.objects.get(so_id=orders[0]["id"], line_no=2)
        # 除不盡的成本(舊資料可能這樣):整張退時沖回整行成本
        SalesOrderItem.objects.filter(pk=case_line.pk).update(cost_at_post=D("100.01"))
        self.give_back(orders[0])
        self.give_back(orders[2])

        def snapshot():
            return (
                list(SalesOrderItem.objects.order_by("id").values_list(
                    "id", "untaxed_amount", "tax_amount")),
                list(SalesReturnItem.objects.order_by("id").values_list(
                    "id", "untaxed_amount", "tax_amount", "cost_at_post")),
            )
        saved = snapshot()
        SalesOrderItem.objects.update(untaxed_amount=0, tax_amount=0)
        SalesReturnItem.objects.update(untaxed_amount=0, tax_amount=0, cost_at_post=0)
        backfill(django_apps, None)
        self.assertEqual(snapshot(), saved)

    def test_backfill_leaves_a_mismatched_order_unforced(self):
        so = self.sell("taxable_included", [
            {"product": self.c.case.id, "qty": 1, "unit_price": "390"},
        ], "390")
        SalesOrder.objects.filter(pk=so["id"]).update(subtotal=D("100.00"), tax_amount=D("5.00"))
        backfill(django_apps, None)
        item = SalesOrderItem.objects.get(so_id=so["id"])
        self.assertEqual((item.untaxed_amount, item.tax_amount), (D("371.43"), D("18.57")))


class ReturnSafetyTests(TestCase):
    def setUp(self):
        self.c = Company("a", "甲通訊行", "甲")
        self.c.purchase(case_qty=3)
        self.so = self.c._post("/api/v1/sales-orders/", {
            "customer": self.c.customer.id, "warehouse": self.c.wh.id, "tax_method": "untaxed",
            "items": [{"product": self.c.case.id, "qty": 1, "unit_price": "390"}],
            "payments": [{"method": "cash", "amount": "390"}],
        })
        self.line = SalesOrderItem.objects.get(so_id=self.so["id"])

    def refused(self, sr, message):
        from apps.sales.services import SalesReturnError, commit_sales_return

        with self.assertRaisesMessage(SalesReturnError, message):
            commit_sales_return(sr)

    def test_same_line_twice_in_one_return_is_refused(self):
        sr = build_return(self.c.tenant, self.so["id"], [(self.line, 1, []), (self.line, 1, [])])
        self.refused(sr, "同一行")

    def test_only_whole_returns_are_accepted(self):
        so = self.c._post("/api/v1/sales-orders/", {
            "customer": self.c.customer.id, "warehouse": self.c.wh.id, "tax_method": "untaxed",
            "items": [{"product": self.c.case.id, "qty": 2, "unit_price": "390"}],
            "payments": [{"method": "cash", "amount": "780"}],
        })
        line = SalesOrderItem.objects.get(so_id=so["id"])
        partial = build_return(self.c.tenant, so["id"], [(line, 1, [])])
        self.refused(partial, "要整行退")
        partial.delete()
        self.refused(build_return(self.c.tenant, so["id"], []), "還有 1 行沒有退")

    def test_every_phone_of_the_line_must_come_back(self):
        self.c.purchase(phone_serials=["甲A1", "甲A2"])
        phones = list(ProductSerial.objects.filter(serial_no__in=["甲A1", "甲A2"]).order_by("serial_no"))
        so = self.c._post("/api/v1/sales-orders/", {
            "customer": self.c.customer.id, "warehouse": self.c.wh.id, "tax_method": "untaxed",
            "items": [{"product": self.c.phone.id, "qty": 2, "unit_price": "25000",
                       "serial_ids": [p.id for p in phones]}],
            "payments": [{"method": "cash", "amount": "50000"}],
        })
        line = SalesOrderItem.objects.get(so_id=so["id"])
        # 數量照整行,但只帶了其中一台
        self.refused(build_return(self.c.tenant, so["id"], [(line, 2, [phones[0].id])]), "每一台")

    def test_second_return_is_refused_inside_the_save(self):
        # 兩個人同時按:API 檢查時都還沒有銷退,存檔(已鎖原單)時第二張要被擋下
        build_return(self.c.tenant, self.so["id"], [(self.line, 1, [])])
        self.refused(build_return(self.c.tenant, self.so["id"], [(self.line, 1, [])]), "已經退過")

    def test_return_store_must_be_the_original_store(self):
        other = self.c.warehouses[1]
        self.refused(build_return(self.c.tenant, self.so["id"], [(self.line, 1, [])], warehouse=other),
                     "退回門市要跟原銷貨單的門市一樣")

    def test_return_must_keep_the_original_customer(self):
        someone_else = type(self.c.customer).objects.create(
            tenant=self.c.tenant, name="甲另一位", phone="0912000777")
        self.refused(build_return(self.c.tenant, self.so["id"], [(self.line, 1, [])],
                                  customer=someone_else), "客戶 / 會員要跟原銷貨單一樣")

    def test_line_rows_must_belong_to_the_company_too(self):
        other = Company("b", "乙通訊行", "乙")
        sr = build_return(self.c.tenant, self.so["id"], [(self.line, 1, [])])
        SalesReturnItem.objects.filter(sr=sr).update(tenant=other.tenant)
        self.refused(sr, "不屬於這家公司")

    def test_original_sale_is_locked_before_the_return_is_written(self):
        # 兩張同時送出時,如果先寫銷退再鎖原單會互相等到死結;所以鎖一定要在寫入之前
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as ctx:
            self.c._post("/api/v1/sales-returns/", {"original_so": self.so["id"],
                                                    "payment_method": "cash"})
        sql = [q["sql"] for q in ctx.captured_queries]
        lock = next(i for i, q in enumerate(sql)
                    if 'FROM "sales_salesorder"' in q and "FOR UPDATE" in q)
        insert = next(i for i, q in enumerate(sql) if q.startswith('INSERT INTO "sales_salesreturn"'))
        self.assertLess(lock, insert)

    def test_sale_with_a_live_return_cannot_be_voided(self):
        back = self.c._post("/api/v1/sales-returns/", {"original_so": self.so["id"],
                                                       "payment_method": "cash"})
        from apps.inventory.models import StockBalance
        stock = StockBalance.objects.get(tenant=self.c.tenant, product=self.c.case, warehouse=self.c.wh)
        r = self.c.admin.post(f"/api/v1/sales-orders/{self.so['id']}/void/", {}, format="json")
        self.assertEqual(r.status_code, 400, r.content)
        self.assertIn(back["no"], str(r.json()))
        stock.refresh_from_db()
        self.assertEqual(stock.qty, 3)          # 沒有被加回第二次
        # 先作廢銷退,再作廢銷貨就可以
        r = self.c.admin.post(f"/api/v1/sales-returns/{back['id']}/void/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        r = self.c.admin.post(f"/api/v1/sales-orders/{self.so['id']}/void/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        stock.refresh_from_db()
        self.assertEqual(stock.qty, 3)

    def test_return_copies_the_original_figures_exactly(self):
        # 舊單:單頭跟明細有零頭差(現在的算法算不出這組數字)
        SalesOrder.objects.filter(pk=self.so["id"]).update(
            tax_method="taxable_included", subtotal=D("371.40"), tax_amount=D("18.60"))
        SalesOrderItem.objects.filter(pk=self.line.pk).update(
            untaxed_amount=D("371.41"), tax_amount=D("18.59"))
        back = self.c._post("/api/v1/sales-returns/", {"original_so": self.so["id"],
                                                       "payment_method": "cash"})
        self.assertEqual((D(back["subtotal"]), D(back["tax_amount"]), D(back["total"])),
                         (D("371.40"), D("18.60"), D("390.00")))
        item = back["items"][0]
        self.assertEqual((D(item["untaxed_amount"]), D(item["tax_amount"])),
                         (D("371.41"), D("18.59")))

    def test_buyback_cannot_be_returned(self):
        SalesOrder.objects.filter(pk=self.so["id"]).update(total=D("-390"))
        self.refused(build_return(self.c.tenant, self.so["id"], [(self.line, 1, [])]), "收購單")


class ReturnLockTests(TransactionTestCase):
    def test_return_waits_for_the_original_sale(self):
        from django.db import OperationalError, connection, connections

        c = Company("a", "甲通訊行", "甲")
        c.purchase(case_qty=2)
        so = c._post("/api/v1/sales-orders/", {
            "customer": c.customer.id, "warehouse": c.wh.id, "tax_method": "untaxed",
            "items": [{"product": c.case.id, "qty": 1, "unit_price": "390"}],
            "payments": [{"method": "cash", "amount": "390"}],
        })
        line = SalesOrderItem.objects.get(so_id=so["id"])
        # 另一個連線(另一張同時送出的銷退)握著原銷貨單
        other = connections.create_connection("default")
        other.ensure_connection()
        self.addCleanup(other.close)
        other.set_autocommit(False)
        with other.cursor() as cur:
            cur.execute("SELECT 1 FROM sales_salesorder WHERE id = %s FOR NO KEY UPDATE", [so["id"]])
        with connection.cursor() as cur:
            cur.execute("SET lock_timeout = '300ms'")
        self.addCleanup(lambda: connection.cursor().execute("SET lock_timeout = 0"))
        with self.assertRaises(OperationalError):
            # 不作廢原發票:否則改原銷貨單那一步本來就會等,測不出「先鎖再檢查」
            c.admin.post("/api/v1/sales-returns/", {
                "original_so": so["id"], "warehouse": c.wh.id, "payment_method": "cash",
                "void_original_invoice": False,
                "items": [{"original_item": line.id, "qty": 1, "unit_price": "390"}],
            }, format="json")
        self.assertFalse(SalesReturnItem.objects.exists())


class VoidLockTests(TransactionTestCase):
    def test_voiding_a_return_waits_for_its_turn(self):
        from django.db import OperationalError, connection, connections

        c = Company("a", "甲通訊行", "甲")
        c.purchase(case_qty=2)
        so = c._post("/api/v1/sales-orders/", {
            "customer": c.customer.id, "warehouse": c.wh.id, "tax_method": "untaxed",
            "items": [{"product": c.case.id, "qty": 1, "unit_price": "390"}],
            "payments": [{"method": "cash", "amount": "390"}],
        })
        back = c._post("/api/v1/sales-returns/", {"original_so": so["id"], "payment_method": "cash"})
        # 另一個連線握著這張銷退(弱鎖:只會擋住「一開始就上的排他鎖」,
        # 擋不住最後改 is_void 那一步 —— 這樣才測得出是不是「先鎖再檢查」)
        other = connections.create_connection("default")
        other.ensure_connection()
        self.addCleanup(other.close)
        other.set_autocommit(False)
        with other.cursor() as cur:
            cur.execute("SELECT 1 FROM sales_salesreturn WHERE id = %s FOR KEY SHARE", [back["id"]])
        with connection.cursor() as cur:
            cur.execute("SET lock_timeout = '300ms'")
        self.addCleanup(lambda: connection.cursor().execute("SET lock_timeout = 0"))
        with self.assertRaises(OperationalError):
            c.admin.post(f"/api/v1/sales-returns/{back['id']}/void/", {}, format="json")
        from apps.inventory.models import StockBalance
        self.assertEqual(StockBalance.objects.get(product=c.case, warehouse=c.wh).qty, 2)


class StockLockTests(TransactionTestCase):
    """庫存數量是「讀 → 加減 → 存」,一定要先鎖;不同的單同時動同一個商品才不會少算一次。"""

    def setUp(self):
        self.c = Company("a", "甲通訊行", "甲")
        self.c.purchase(case_qty=5)

    def hold_stock(self):
        from django.db import connection, connections

        from apps.inventory.models import StockBalance

        bal = StockBalance.objects.get(product=self.c.case, warehouse=self.c.wh)
        other = connections.create_connection("default")
        other.ensure_connection()
        self.addCleanup(other.close)
        other.set_autocommit(False)
        with other.cursor() as cur:
            cur.execute("SELECT 1 FROM inventory_stockbalance WHERE id = %s FOR KEY SHARE", [bal.pk])
        with connection.cursor() as cur:
            cur.execute("SET lock_timeout = '300ms'")
        self.addCleanup(lambda: connection.cursor().execute("SET lock_timeout = 0"))
        return bal

    def sale_body(self):
        return {
            "customer": self.c.customer.id, "warehouse": self.c.wh.id, "tax_method": "untaxed",
            "items": [{"product": self.c.case.id, "qty": 1, "unit_price": "390"}],
            "payments": [{"method": "cash", "amount": "390"}],
        }

    def test_sale_return_and_void_lock_the_stock_first(self):
        from django.db import OperationalError

        so = self.c._post("/api/v1/sales-orders/", self.sale_body())
        other_so = self.c._post("/api/v1/sales-orders/", self.sale_body())
        bal = self.hold_stock()
        for call in (
            lambda: self.c.admin.post("/api/v1/sales-orders/", self.sale_body(), format="json"),
            lambda: self.c.admin.post("/api/v1/sales-returns/",
                                      {"original_so": so["id"], "payment_method": "cash"}, format="json"),
            lambda: self.c.admin.post(f"/api/v1/sales-orders/{other_so['id']}/void/", {}, format="json"),
        ):
            with self.assertRaises(OperationalError):
                call()
        bal.refresh_from_db()
        self.assertEqual(bal.qty, 3)

    def test_same_phone_cannot_be_sold_twice_at_the_same_moment(self):
        """另一張單正在賣同一支手機(還沒存完):這張要等它,等到之後看到「已售」就拒絕。
        不能兩張都看到「在庫」而各賣一次。"""
        import threading
        import time

        from django.db import connections

        self.c.purchase(phone_serials=["甲P1"])
        phone = ProductSerial.objects.get(serial_no="甲P1")
        holding = threading.Event()

        def other_sale():
            other = connections.create_connection("default")
            try:
                other.ensure_connection()
                other.set_autocommit(False)
                with other.cursor() as cur:
                    cur.execute("SELECT 1 FROM inventory_productserial WHERE id = %s FOR UPDATE",
                                [phone.pk])
                    cur.execute("UPDATE inventory_productserial SET status = 'sold', "
                                "warehouse_id = NULL WHERE id = %s", [phone.pk])
                holding.set()
                time.sleep(1.0)
                other.commit()
            finally:
                other.close()

        t = threading.Thread(target=other_sale)
        t.start()
        self.assertTrue(holding.wait(5))
        r = self.c.admin.post("/api/v1/sales-orders/", {
            "customer": self.c.customer.id, "warehouse": self.c.wh.id, "tax_method": "untaxed",
            "items": [{"product": self.c.phone.id, "qty": 1, "unit_price": "25000",
                       "serial_ids": [phone.pk]}],
            "payments": [{"method": "cash", "amount": "25000"}],
        }, format="json")
        t.join()
        self.assertEqual(r.status_code, 400, r.content)
        self.assertIn("不可銷貨", str(r.json()))
        self.assertEqual(SalesOrder.objects.count(), 0)

    def in_another_session(self, statements, hold=1.0):
        """另一個人同時在做:開另一條連線、執行這些 SQL(會鎖住那幾列),停一下再存檔。
        回傳後那條連線已經握著鎖;存檔在背景發生。"""
        import threading
        import time

        from django.db import connections

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
        return t

    def test_phone_being_sold_cannot_be_transferred_at_the_same_moment(self):
        self.c.purchase(phone_serials=["甲P2"])
        phone = ProductSerial.objects.get(serial_no="甲P2")
        t = self.in_another_session([
            ("SELECT 1 FROM inventory_productserial WHERE id = %s FOR NO KEY UPDATE", [phone.pk]),
            ("UPDATE inventory_productserial SET status = 'sold', warehouse_id = NULL WHERE id = %s",
             [phone.pk]),
        ])
        r = self.c.admin.post("/api/v1/transfer-orders/", {
            "from_warehouse": self.c.warehouses[0].id, "to_warehouse": self.c.warehouses[1].id,
            "items": [{"product": self.c.phone.id, "qty": 1, "serial_ids": [phone.pk]}],
        }, format="json")
        t.join()
        self.assertEqual(r.status_code, 400, r.content)
        self.assertIn("不可調撥", str(r.json()))
        phone.refresh_from_db()
        self.assertEqual(phone.status, "sold")

    def test_stock_rows_are_locked_in_a_fixed_order(self):
        """兩張單的商品順序相反時不能互相等到死結:不管明細順序,一律照商品編號上鎖。"""
        import re

        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        from apps.catalog.models import Product

        second = Product.objects.create(tenant=self.c.tenant, category=self.c.cat_case,
                                        name="甲 另一款皮套", requires_serial=False, list_price=200)
        self.c._post("/api/v1/purchase-orders/", {
            "supplier": self.c.supplier.id, "warehouse": self.c.wh.id, "tax_method": "untaxed",
            "items": [{"product": second.id, "qty": 2, "unit_price": "50"}],
        })
        self.assertLess(self.c.case.id, second.id)
        with CaptureQueriesContext(connection) as ctx:
            self.c._post("/api/v1/sales-orders/", {
                "customer": self.c.customer.id, "warehouse": self.c.wh.id, "tax_method": "untaxed",
                "items": [{"product": second.id, "qty": 1, "unit_price": "200"},
                          {"product": self.c.case.id, "qty": 1, "unit_price": "390"}],
                "payments": [{"method": "cash", "amount": "590"}],
            })
        locked = [
            int(re.search(r'"product_id" = (\d+)', q["sql"]).group(1))
            for q in ctx.captured_queries
            if 'FROM "inventory_stockbalance"' in q["sql"] and "FOR UPDATE" in q["sql"]
        ]
        self.assertEqual(locked[:2], [self.c.case.id, second.id])

    def test_stock_is_rechecked_after_the_lock(self):
        from unittest import mock

        from apps.sales import services

        so = SalesOrder.objects.create(tenant=self.c.tenant, warehouse=self.c.wh,
                                       customer=self.c.customer, tax_method="untaxed")
        SalesOrderItem.objects.create(tenant=self.c.tenant, so=so, product=self.c.case, qty=9,
                                      unit_price=D("390"))
        # 鎖之前的檢查通過之後,庫存被另一張單賣掉了
        with mock.patch.object(services, "_validate_items"):
            with self.assertRaisesMessage(services.SalesOrderError, "不足銷售"):
                services.commit_sales_order(so)


class CrossCompanyTests(TestCase):
    """別家公司的單據 / 門市 / 商品 / 序號,猜到編號也不能拿來用。"""

    def setUp(self):
        self.a = Company("a", "甲通訊行", "甲")
        self.a.purchase(phone_serials=["甲IMEI1"], case_qty=3)
        self.b = Company("b", "乙通訊行", "乙")
        serial = ProductSerial.objects.get(serial_no="甲IMEI1")
        self.so = self.a._post("/api/v1/sales-orders/", {
            "customer": self.a.customer.id, "warehouse": self.a.wh.id, "tax_method": "untaxed",
            "items": [
                {"product": self.a.phone.id, "qty": 1, "unit_price": "25000", "serial_ids": [serial.id]},
                {"product": self.a.case.id, "qty": 1, "unit_price": "390"},
            ],
            "payments": [{"method": "cash", "amount": "25390"}],
        })
        self.serial = serial

    def test_return_against_another_companys_sale_is_refused(self):
        phone_line = SalesOrderItem.objects.get(so_id=self.so["id"], product=self.a.phone)
        r = self.b.admin.post("/api/v1/sales-returns/", {
            "original_so": self.so["id"], "warehouse": self.b.wh.id, "payment_method": "cash",
            "items": [{"original_item": phone_line.id, "qty": 1, "unit_price": "25000",
                       "serial_ids": [self.serial.id]}],
        }, format="json")
        self.assertEqual(r.status_code, 400, r.content)
        self.assertIn("original_so", r.json())          # 欄位本身就不接受別家的編號
        self.serial.refresh_from_db()
        self.assertEqual(self.serial.status, "sold")
        self.assertFalse(SalesReturnItem.objects.exists())

    def test_service_refuses_even_without_the_api(self):
        from apps.sales.models import SalesReturn
        from apps.sales.services import SalesReturnError, commit_sales_return

        case_line = SalesOrderItem.objects.get(so_id=self.so["id"], product=self.a.case)
        sr = SalesReturn.objects.create(
            tenant=self.b.tenant, original_so_id=self.so["id"], warehouse=self.b.wh,
            payment_method="cash",
        )
        SalesReturnItem.objects.create(
            tenant=self.b.tenant, sr=sr, original_item=case_line, product=self.a.case, qty=1,
            unit_price=case_line.unit_price, amount=0,
        )
        with self.assertRaisesMessage(SalesReturnError, "不屬於這家公司"):
            commit_sales_return(sr)

    def test_return_service_refuses_another_companys_store(self):
        from apps.sales.models import SalesReturn
        from apps.sales.services import SalesReturnError, commit_sales_return

        # 原單是自己公司的,只有退回的門市是別家的
        case_line = SalesOrderItem.objects.get(so_id=self.so["id"], product=self.a.case)
        sr = SalesReturn.objects.create(
            tenant=self.a.tenant, original_so_id=self.so["id"], warehouse=self.b.wh,
            payment_method="cash",
        )
        SalesReturnItem.objects.create(
            tenant=self.a.tenant, sr=sr, original_item=case_line, product=self.a.case, qty=1,
            unit_price=case_line.unit_price, amount=0,
        )
        with self.assertRaisesMessage(SalesReturnError, "原銷貨單 / 門市"):
            commit_sales_return(sr)

    def test_line_from_another_sale_is_refused(self):
        other = self.a._post("/api/v1/sales-orders/", {
            "customer": self.a.customer.id, "warehouse": self.a.wh.id, "tax_method": "untaxed",
            "items": [{"product": self.a.case.id, "qty": 1, "unit_price": "390"}],
            "payments": [{"method": "cash", "amount": "390"}],
        })
        from apps.sales.services import SalesReturnError, commit_sales_return

        other_line = SalesOrderItem.objects.get(so_id=other["id"])
        sr = build_return(self.a.tenant, self.so["id"], [(other_line, 1, [])])
        with self.assertRaisesMessage(SalesReturnError, "不是原銷貨單"):
            commit_sales_return(sr)

    def test_sale_using_another_companys_store_or_product_is_refused(self):
        r = self.b.admin.post("/api/v1/sales-orders/", {
            "customer": self.b.customer.id, "warehouse": self.a.wh.id, "tax_method": "untaxed",
            "items": [{"product": self.a.case.id, "qty": 1, "unit_price": "390"}],
            "payments": [{"method": "cash", "amount": "390"}],
        }, format="json")
        self.assertEqual(r.status_code, 400, r.content)
        self.assertIn("warehouse", r.json())
        self.assertEqual(SalesOrder.objects.filter(tenant=self.b.tenant).count(), 0)

    def test_sale_service_refuses_another_companys_store(self):
        from apps.sales.services import SalesOrderError, commit_sales_order

        # 商品是自己公司的,只有門市是別家的
        so = SalesOrder.objects.create(tenant=self.b.tenant, warehouse=self.a.wh, tax_method="untaxed")
        SalesOrderItem.objects.create(tenant=self.b.tenant, so=so, product=self.b.case, qty=1,
                                      unit_price=D("390"))
        with self.assertRaisesMessage(SalesOrderError, "門市 / 客戶"):
            commit_sales_order(so)

    def test_sale_service_refuses_another_companys_product(self):
        from apps.sales.services import SalesOrderError, commit_sales_order

        so = SalesOrder.objects.create(tenant=self.b.tenant, warehouse=self.b.wh, tax_method="untaxed")
        SalesOrderItem.objects.create(tenant=self.b.tenant, so=so, product=self.a.case, qty=1,
                                      unit_price=D("390"))
        with self.assertRaisesMessage(SalesOrderError, "不屬於這家公司"):
            commit_sales_order(so)

    def _sale_of_a(self, product, serial=None):
        """不經 API 建一張甲公司的銷貨單(用來放進不該出現的別家商品 / 序號)。"""
        from apps.sales.models import SalesOrderItemSerial, SalesOrderPayment

        so = SalesOrder.objects.create(tenant=self.a.tenant, warehouse=self.a.wh,
                                       customer=self.a.customer, tax_method="untaxed",
                                       subtotal=D("390"), total=D("390"))
        line = SalesOrderItem.objects.create(tenant=self.a.tenant, so=so, product=product, qty=1,
                                             unit_price=D("390"), amount=D("390"))
        SalesOrderPayment.objects.create(tenant=self.a.tenant, so=so, method="cash", amount=D("390"))
        if serial is not None:
            SalesOrderItemSerial.objects.create(tenant=self.a.tenant, item=line, serial=serial)
        return so, line

    def test_return_refuses_another_companys_product_or_phone_behind_the_lines(self):
        from apps.sales.services import SalesReturnError, commit_sales_return

        so, line = self._sale_of_a(self.b.case)
        with self.assertRaisesMessage(SalesReturnError, "不屬於這家公司"):
            commit_sales_return(build_return(self.a.tenant, so.id, [(line, 1, [])]))

        self.b.purchase(phone_serials=["乙IMEI9"])
        theirs = ProductSerial.objects.get(serial_no="乙IMEI9")
        so, line = self._sale_of_a(self.a.phone, serial=theirs)
        with self.assertRaisesMessage(SalesReturnError, "不屬於這家公司"):
            commit_sales_return(build_return(self.a.tenant, so.id, [(line, 1, [theirs.id])]))
        theirs.refresh_from_db()
        self.assertEqual(theirs.status, "in_stock")

    def test_buyback_service_refuses_another_companys_product(self):
        from apps.catalog.models import Product
        from apps.parties.models import Member
        from apps.sales.services import SecondhandIntakeError, acquire_secondhand_from_member

        member = Member.objects.create(tenant=self.a.tenant, name="甲會員", phone="0911000333")
        theirs = Product.objects.create(tenant=self.b.tenant, category=self.b.cat_phone,
                                        name="乙 中古 iPhone 13", is_secondhand=True)
        with self.assertRaisesMessage(SecondhandIntakeError, "不屬於這家公司"):
            acquire_secondhand_from_member(
                tenant=self.a.tenant, member=member, warehouse=self.a.wh,
                secondhand_product=theirs, serial_no="甲USED9", condition_grade="A",
                custom_unit_price=None, acquisition_price=D("8000"), payment_method_code="cash",
            )
        self.assertFalse(ProductSerial.objects.filter(serial_no="甲USED9").exists())

    def test_sale_line_rows_must_belong_to_the_company_too(self):
        from apps.sales.services import SalesOrderError, commit_sales_order

        so = SalesOrder.objects.create(tenant=self.b.tenant, warehouse=self.b.wh, tax_method="untaxed")
        SalesOrderItem.objects.create(tenant=self.a.tenant, so=so, product=self.b.case, qty=1,
                                      unit_price=D("390"))
        with self.assertRaisesMessage(SalesOrderError, "不屬於這家公司"):
            commit_sales_order(so)

    def test_store_locked_clerk_cannot_sell_for_another_store(self):
        other_store = self.a.warehouses[1]
        r = self.a.clerk.post("/api/v1/sales-orders/", {
            "customer": self.a.customer.id, "warehouse": other_store.id, "tax_method": "untaxed",
            "items": [{"product": self.a.case.id, "qty": 1, "unit_price": "390"}],
            "payments": [{"method": "cash", "amount": "390"}],
        }, format="json")
        self.assertEqual(r.status_code, 403, r.content)


class BackfillRuleTests(TestCase):
    # 借用 LedgerTests 的準備與小工具,不繼承它的測試(否則會整組再跑一次)
    setUp = LedgerTests.setUp
    sell = LedgerTests.sell
    historic_return = LedgerTests.historic_return

    def test_header_off_by_a_cent_is_not_forced(self):
        # 兩行含稅各 100,但單頭加起來 199.99:不補零頭,每行 未稅 + 稅額 仍 = 金額
        self.assertIsNone(split_tax_by_line(
            [D("100.00"), D("100.00")], "taxable_included", D("190.47"), D("9.52")))
        so = self.sell("taxable_included", [
            {"product": self.c.case.id, "qty": 1, "unit_price": "100"},
            {"product": self.c.case.id, "qty": 1, "unit_price": "100"},
        ], "200")
        SalesOrder.objects.filter(pk=so["id"]).update(subtotal=D("190.47"), tax_amount=D("9.52"))
        backfill(django_apps, None)
        for item in SalesOrderItem.objects.filter(so_id=so["id"]):
            self.assertEqual(item.untaxed_amount + item.tax_amount, item.amount)

    def test_backfill_valid_returns_add_up_after_an_early_one_was_voided(self):
        so = self.sell("untaxed", [{"product": self.c.case.id, "qty": 3, "unit_price": "390"}], "1170")
        SalesOrderItem.objects.filter(so_id=so["id"]).update(cost_at_post=D("100.00"))
        line = SalesOrderItem.objects.get(so_id=so["id"])
        # 舊資料:三張各退一個,第一張後來作廢,再退一個
        first = self.historic_return(so, line, 1, void=True)
        for _ in range(3):
            self.historic_return(so, line, 1)
        backfill(django_apps, None)
        live = SalesReturnItem.objects.filter(original_item=line, sr__is_void=False)
        self.assertEqual(live.count(), 3)
        self.assertEqual(sum(i.cost_at_post for i in live), line.cost_at_post)
        voided = SalesReturnItem.objects.get(sr=first)
        self.assertEqual(voided.cost_at_post, D("33.33"))

    def test_backfill_voided_return_never_takes_the_remainder(self):
        so = self.sell("untaxed", [{"product": self.c.case.id, "qty": 3, "unit_price": "390"}], "1170")
        SalesOrderItem.objects.filter(so_id=so["id"]).update(cost_at_post=D("100.00"))
        line = SalesOrderItem.objects.get(so_id=so["id"])
        self.historic_return(so, line, 1)
        self.historic_return(so, line, 1)
        last = self.historic_return(so, line, 1, void=True)
        backfill(django_apps, None)
        self.assertEqual(SalesReturnItem.objects.get(sr=last).cost_at_post, D("33.33"))


class ReturnScreenPayloadTests(TestCase):
    """銷退畫面實際送的格式:只有原單、退款方式、明細(不送門市、單價、客戶)。"""

    def setUp(self):
        self.c = Company("a", "甲通訊行", "甲")
        self.c.purchase(case_qty=3)
        self.c.purchase(case_qty=3, warehouse=self.c.warehouses[1])
        self.other_customer = type(self.c.customer).objects.create(
            tenant=self.c.tenant, name="甲另一位客人", phone="0912000999")

    def sale(self, store):
        so = self.c._post("/api/v1/sales-orders/", {
            "customer": self.c.customer.id, "warehouse": store.id, "tax_method": "untaxed",
            "items": [{"product": self.c.case.id, "qty": 2, "unit_price": "390"}],
            "payments": [{"method": "cash", "amount": "780"}],
        })
        return so, SalesOrderItem.objects.get(so_id=so["id"])

    def test_store_clerk_can_return_from_the_screen(self):
        so, line = self.sale(self.c.wh)
        r = self.c.clerk.post("/api/v1/sales-returns/", {
            "original_so": so["id"], "payment_method": "cash", "void_original_invoice": True,
            "note": "", "items": [{"original_item": line.id, "qty": 1}],
            "customer": self.other_customer.id,
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        body = r.json()
        self.assertEqual(body["warehouse"], self.c.wh.id)
        self.assertEqual(body["customer"], self.c.customer.id)       # 跟原單一樣,不採用送來的
        self.assertEqual(D(body["items"][0]["unit_price"]), D("390"))

    def test_store_clerk_cannot_return_another_stores_sale(self):
        so, line = self.sale(self.c.warehouses[1])
        r = self.c.clerk.post("/api/v1/sales-returns/", {
            "original_so": so["id"], "payment_method": "cash",
        }, format="json")
        self.assertEqual(r.status_code, 403, r.content)
        # 自己指定「退回自己門市」也一樣不行:退回門市一律是原單門市
        r = self.c.clerk.post("/api/v1/sales-returns/", {
            "original_so": so["id"], "payment_method": "cash", "warehouse": self.c.wh.id,
        }, format="json")
        self.assertEqual(r.status_code, 403, r.content)
        self.assertFalse(SalesReturnItem.objects.exists())

    def test_return_always_goes_back_to_the_store_that_sold_it(self):
        so, line = self.sale(self.c.warehouses[1])
        r = self.c.admin.post("/api/v1/sales-returns/", {
            "original_so": so["id"], "payment_method": "cash", "warehouse": self.c.wh.id,
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["warehouse"], self.c.warehouses[1].id)

    def test_free_sale_can_be_returned_without_a_refund_method(self):
        so = self.c._post("/api/v1/sales-orders/", {
            "customer": self.c.customer.id, "warehouse": self.c.wh.id, "tax_method": "untaxed",
            "items": [{"product": self.c.case.id, "qty": 1, "unit_price": "0"}],
            "payments": [],
        })
        self.assertEqual(D(so["total"]), D("0"))
        r = self.c.admin.post("/api/v1/sales-returns/", {"original_so": so["id"]}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        # 有收錢的單還是要選退款方式
        paid, _ = self.sale(self.c.wh)
        r = self.c.admin.post("/api/v1/sales-returns/", {"original_so": paid["id"]}, format="json")
        self.assertEqual(r.status_code, 400, r.content)
        self.assertIn("payment_method", r.json())

    def test_return_cannot_be_voided_after_the_phone_moved_on(self):
        self.c.purchase(phone_serials=["甲V1"])
        phone = ProductSerial.objects.get(serial_no="甲V1")
        so = self.c._post("/api/v1/sales-orders/", {
            "customer": self.c.customer.id, "warehouse": self.c.wh.id, "tax_method": "untaxed",
            "items": [{"product": self.c.phone.id, "qty": 1, "unit_price": "25000",
                       "serial_ids": [phone.id]}],
            "payments": [{"method": "cash", "amount": "25000"}],
        })
        back = self.c._post("/api/v1/sales-returns/", {"original_so": so["id"],
                                                       "payment_method": "cash"})
        # 退回來的機器已經被轉回在庫
        ProductSerial.objects.filter(pk=phone.pk).update(status="in_stock")
        r = self.c.admin.post(f"/api/v1/sales-returns/{back['id']}/void/", {}, format="json")
        self.assertEqual(r.status_code, 400, r.content)
        phone.refresh_from_db()
        self.assertEqual(phone.status, "in_stock")
