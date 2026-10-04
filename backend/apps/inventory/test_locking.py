"""進貨 / 調撥 / 維修的「先鎖再檢查、再改」(規則見 apps/inventory/locking.py)。

「另一個人同時在做」用另一條資料庫連線模擬:它鎖住某一列、改掉、停一下才存檔。
這邊的動作必須等它存完、看到它改過的結果才做 —— 不能各自讀到舊值。
"""
import threading
import time
from datetime import date
from decimal import Decimal
from unittest import mock

from django.db import connection, connections
from django.test import TestCase, TransactionTestCase
from django.test.utils import CaptureQueriesContext

from apps.backup.tests.factory import Company
from apps.catalog.models import Product
from apps.inventory.locking import lock_stock_rows
from apps.inventory.models import ProductSerial, StockBalance, StockMovement
from apps.ledger.checks import check_stock_balance

D = Decimal


class _Concurrent(TransactionTestCase):
    def setUp(self):
        self.c = Company("a", "甲通訊行", "甲")
        self.c.purchase(phone_serials=["甲IMEI1"], case_qty=5)
        self.w1, self.w2 = self.c.warehouses

    def stock(self, warehouse=None, product=None):
        row = StockBalance.objects.filter(
            tenant=self.c.tenant, product=product or self.c.case, warehouse=warehouse or self.w1
        ).first()
        return row.qty if row else 0

    def meanwhile(self, statements, hold=1.0):
        """另一條連線執行這些 SQL(鎖住那幾列)、停一下再存檔。回傳時它已經握著鎖。"""
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

    def someone_adds_ten(self, warehouse=None):
        row = StockBalance.objects.get(tenant=self.c.tenant, product=self.c.case,
                                       warehouse=warehouse or self.w1)
        return self.meanwhile([
            ("SELECT 1 FROM inventory_stockbalance WHERE id = %s FOR UPDATE", [row.pk]),
            ("UPDATE inventory_stockbalance SET qty = qty + 10 WHERE id = %s", [row.pk]),
        ])


class PurchaseLockTests(_Concurrent):
    def test_purchase_does_not_lose_a_change_made_at_the_same_moment(self):
        t = self.someone_adds_ten()
        self.c.purchase(case_qty=1)
        t.join()
        self.assertEqual(self.stock(), 5 + 10 + 1)

    def test_purchase_voided_by_someone_else_a_moment_ago_is_not_voided_twice(self):
        po = self.c.purchase(case_qty=2)
        t = self.meanwhile([
            ("SELECT 1 FROM purchasing_purchaseorder WHERE id = %s FOR UPDATE", [po["id"]]),
            ("UPDATE purchasing_purchaseorder SET is_void = true WHERE id = %s", [po["id"]]),
        ])
        r = self.c.admin.post(f"/api/v1/purchase-orders/{po['id']}/void/", {}, format="json")
        t.join()
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(self.stock(), 7)          # 這一邊沒有再扣一次

    def test_void_does_not_lose_a_change_made_at_the_same_moment(self):
        po = self.c.purchase(case_qty=2)
        t = self.someone_adds_ten()
        r = self.c.admin.post(f"/api/v1/purchase-orders/{po['id']}/void/", {}, format="json")
        t.join()
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self.stock(), 7 + 10 - 2)


class TransferLockTests(_Concurrent):
    def dispatch(self, qty=2):
        return self.c._post("/api/v1/transfer-orders/", {
            "from_warehouse": self.w1.id, "to_warehouse": self.w2.id,
            "items": [{"product": self.c.case.id, "qty": qty}],
        })

    def test_dispatch_does_not_lose_a_change_made_at_the_same_moment(self):
        t = self.someone_adds_ten()
        self.dispatch(1)
        t.join()
        self.assertEqual(self.stock(), 5 + 10 - 1)

    def test_transfer_confirmed_by_someone_else_a_moment_ago_is_not_received_twice(self):
        order = self.dispatch(2)
        t = self.meanwhile([
            ("SELECT 1 FROM transfers_transferorder WHERE id = %s FOR UPDATE", [order["id"]]),
            ("UPDATE transfers_transferorder SET status = 'confirmed' WHERE id = %s", [order["id"]]),
        ])
        r = self.c.admin.post(f"/api/v1/transfer-orders/{order['id']}/confirm/", {}, format="json")
        t.join()
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(self.stock(self.w2), 0)

    def test_void_sees_a_confirmation_that_happened_a_moment_ago(self):
        order = self.dispatch(2)
        # 另一個人剛把它標成已完成(這裡只模擬狀態,貨沒有真的進目的門市)
        t = self.meanwhile([
            ("SELECT 1 FROM transfers_transferorder WHERE id = %s FOR UPDATE", [order["id"]]),
            ("UPDATE transfers_transferorder SET status = 'confirmed' WHERE id = %s", [order["id"]]),
        ])
        r = self.c.admin.post(f"/api/v1/transfer-orders/{order['id']}/void/", {}, format="json")
        t.join()
        # 照「已完成」的規則作廢:目的門市沒有那麼多可以退 → 擋下,不能照「派發中」直接加回來源門市
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(self.stock(self.w1), 3)

    def test_confirm_does_not_lose_a_change_made_at_the_same_moment(self):
        self.dispatch(1)                         # 先讓目的門市有一列庫存餘額
        first = self.c._post("/api/v1/transfer-orders/", {
            "from_warehouse": self.w1.id, "to_warehouse": self.w2.id,
            "items": [{"product": self.c.case.id, "qty": 1}],
        })
        from apps.transfers.models import TransferOrder
        earlier = TransferOrder.objects.exclude(pk=first["id"]).get()
        self.c._post(f"/api/v1/transfer-orders/{earlier.pk}/confirm/", {})
        t = self.someone_adds_ten(self.w2)
        self.c._post(f"/api/v1/transfer-orders/{first['id']}/confirm/", {})
        t.join()
        self.assertEqual(self.stock(self.w2), 1 + 10 + 1)


class RepairLockTests(_Concurrent):
    def repair(self, qty):
        return self.c._post("/api/v1/repair-orders/", {
            "warehouse": self.w1.id, "customer": self.c.customer.id,
            "received_date": str(date.today()), "mode": "in_house", "unlock_method": "none",
            "host_model_name": "iPhone 15",
            "parts_input": [{"part_product": self.c.case.id, "qty": qty}],
        })

    def test_completion_does_not_lose_a_change_made_at_the_same_moment(self):
        order = self.repair(2)
        t = self.someone_adds_ten()
        self.c._post(f"/api/v1/repair-orders/{order['id']}/complete/", {})
        t.join()
        self.assertEqual(self.stock(), 5 + 10 - 2)

    def test_part_cost_is_read_after_a_purchase_that_is_changing_it(self):
        from apps.repairs.models import RepairOrderPart

        order = self.repair(1)
        RepairOrderPart.objects.filter(repair_order_id=order["id"]).update(unit_cost=0)
        # 同一瞬間有一張進貨正在改這個零件的加權平均成本
        t = self.meanwhile([
            ("SELECT 1 FROM catalog_product WHERE id = %s FOR NO KEY UPDATE", [self.c.case.pk]),
            ("UPDATE catalog_product SET weighted_avg_cost = 123 WHERE id = %s", [self.c.case.pk]),
        ])
        self.c._post(f"/api/v1/repair-orders/{order['id']}/complete/", {})
        t.join()
        self.assertEqual(RepairOrderPart.objects.get(repair_order_id=order["id"]).unit_cost, D("123.00"))

    def test_repair_completed_by_someone_else_a_moment_ago_is_not_deducted_twice(self):
        order = self.repair(2)
        t = self.meanwhile([
            ("SELECT 1 FROM repairs_repairorder WHERE id = %s FOR UPDATE", [order["id"]]),
            ("UPDATE repairs_repairorder SET status = 'completed' WHERE id = %s", [order["id"]]),
        ])
        self.c.admin.post(f"/api/v1/repair-orders/{order['id']}/complete/", {}, format="json")
        t.join()
        self.assertEqual(self.stock(), 5)


class RepairRaceTests(_Concurrent):
    """維修單的其他入口(改狀態、作廢)跟完工同時發生:照先後順序,不能各做各的。"""

    def repair(self, qty=2):
        return self.c._post("/api/v1/repair-orders/", {
            "warehouse": self.w1.id, "customer": self.c.customer.id,
            "received_date": str(date.today()), "mode": "in_house", "unlock_method": "none",
            "host_model_name": "iPhone 15",
            "parts_input": [{"part_product": self.c.case.id, "qty": qty}],
        })

    def someone_sets(self, order, column, value):
        return self.meanwhile([
            ("SELECT 1 FROM repairs_repairorder WHERE id = %s FOR UPDATE", [order["id"]]),
            (f"UPDATE repairs_repairorder SET {column} = %s WHERE id = %s", [value, order["id"]]),
        ])

    def test_status_change_cannot_undo_a_completion_that_just_happened(self):
        order = self.repair()
        t = self.someone_sets(order, "status", "completed")
        r = self.c.admin.post(f"/api/v1/repair-orders/{order['id']}/set-status/",
                              {"status": "ready_pickup"}, format="json")
        t.join()
        self.assertEqual(r.status_code, 400, r.content)
        from apps.repairs.models import RepairOrder
        self.assertEqual(RepairOrder.objects.get(pk=order["id"]).status, "completed")

    def test_repair_voided_a_moment_ago_is_not_completed(self):
        order = self.repair()
        t = self.someone_sets(order, "is_void", True)
        r = self.c.admin.post(f"/api/v1/repair-orders/{order['id']}/complete/", {}, format="json")
        t.join()
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(self.stock(), 5)

    def test_edit_cannot_overwrite_a_completion_that_just_happened(self):
        order = self.repair()
        t = self.someone_sets(order, "status", "completed")
        r = self.c.admin.patch(f"/api/v1/repair-orders/{order['id']}/",
                               {"warehouse": self.w2.id}, format="json")
        t.join()
        self.assertEqual(r.status_code, 400, r.content)


class RepairEntryPointTests(TestCase):
    """維修單只有 complete / reopen 會動庫存;其他入口不能繞過它們。"""

    def setUp(self):
        self.c = Company("a", "甲通訊行", "甲")
        self.w1, self.w2 = self.c.warehouses
        self.c.purchase(case_qty=5)
        self.c.purchase(warehouse=self.w2, case_qty=5)
        self.order = self.c._post("/api/v1/repair-orders/", {
            "warehouse": self.w1.id, "customer": self.c.customer.id,
            "received_date": str(date.today()), "mode": "in_house", "unlock_method": "none",
            "host_model_name": "iPhone 15",
            "parts_input": [{"part_product": self.c.case.id, "qty": 2}],
        })
        self.url = f"/api/v1/repair-orders/{self.order['id']}/"

    def stock(self, warehouse):
        return StockBalance.objects.get(product=self.c.case, warehouse=warehouse).qty

    def post(self, action, body=None):
        return self.c.admin.post(f"{self.url}{action}/", body or {}, format="json")

    def test_status_cannot_be_set_by_a_plain_edit(self):
        r = self.c.admin.patch(self.url, {"status": "completed"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["status"], "pending")
        self.assertEqual(self.stock(self.w1), 5)

    def test_completed_repair_is_locked_until_reopened(self):
        self.assertEqual(self.post("complete").status_code, 200)
        self.assertEqual(self.stock(self.w1), 3)
        for r in (
            self.c.admin.patch(self.url, {"warehouse": self.w2.id}, format="json"),
            self.c.admin.patch(self.url, {"parts_input": []}, format="json"),
            self.post("set-status", {"status": "ready_pickup"}),
            self.post("void"),
        ):
            self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(self.post("complete").status_code, 200)     # 再按一次完工不會再扣
        self.assertEqual(self.stock(self.w1), 3)
        self.assertEqual(self.post("reopen").status_code, 200)
        self.assertEqual(self.stock(self.w1), 5)
        self.assertEqual(self.post("void").status_code, 200)

    def test_voided_repair_cannot_be_completed_or_changed(self):
        self.assertEqual(self.post("void").status_code, 200)
        for r in (self.post("complete"), self.post("void"),
                  self.post("set-status", {"status": "in_repair"}),
                  self.c.admin.patch(self.url, {"internal_note": "x"}, format="json")):
            self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(self.stock(self.w1), 5)

    def test_repair_orders_are_voided_not_deleted(self):
        from apps.repairs.models import RepairOrder

        self.assertEqual(self.c.admin.delete(self.url).status_code, 405)
        self.assertTrue(RepairOrder.objects.filter(pk=self.order["id"]).exists())

    def test_reopen_returns_what_was_actually_taken_from_where_it_was_taken(self):
        from apps.repairs.models import RepairOrder, RepairOrderPart

        self.post("complete")
        # 舊資料 / 其他途徑:完工之後單上的門市與零件數量被改掉了
        RepairOrder.objects.filter(pk=self.order["id"]).update(warehouse=self.w2)
        RepairOrderPart.objects.filter(repair_order_id=self.order["id"]).update(qty=4)
        self.assertEqual(self.post("reopen").status_code, 200)
        self.assertEqual((self.stock(self.w1), self.stock(self.w2)), (5, 5))
        self.assertTrue(check_stock_balance(self.c.tenant)[0]["ok"])
        # 再重開一次(狀態已不是完工)不會再歸還
        RepairOrder.objects.filter(pk=self.order["id"]).update(status="completed")
        self.post("reopen")
        self.assertEqual((self.stock(self.w1), self.stock(self.w2)), (5, 5))


class LedgerStaysConsistentTests(TestCase):
    """不靠並行也要對的事:一張單裡同一個商品出現兩行、維修缺料、做到一半出錯。"""

    def setUp(self):
        self.c = Company("a", "甲通訊行", "甲")
        self.w1, self.w2 = self.c.warehouses

    def consistent(self):
        result = check_stock_balance(self.c.tenant)[0]
        self.assertTrue(result["ok"], result["samples"])

    def test_two_lines_of_the_same_phone_average_correctly(self):
        self.c._post("/api/v1/purchase-orders/", {
            "supplier": self.c.supplier.id, "warehouse": self.w1.id, "tax_method": "untaxed",
            "items": [
                {"product": self.c.phone.id, "qty": 1, "unit_price": "20000", "serial_numbers": ["甲A"]},
                {"product": self.c.phone.id, "qty": 1, "unit_price": "30000", "serial_numbers": ["甲B"]},
            ],
        })
        self.assertEqual(Product.objects.get(pk=self.c.phone.pk).weighted_avg_cost, D("25000.00"))

    def test_purchase_cannot_be_voided_after_a_phone_moved_to_another_store(self):
        po = self.c.purchase(phone_serials=["甲M1", "甲M2"])
        moved = ProductSerial.objects.get(serial_no="甲M1")
        order = self.c._post("/api/v1/transfer-orders/", {
            "from_warehouse": self.w1.id, "to_warehouse": self.w2.id,
            "items": [{"product": self.c.phone.id, "qty": 1, "serial_ids": [moved.pk]}],
        })
        self.c._post(f"/api/v1/transfer-orders/{order['id']}/confirm/", {})
        moved.refresh_from_db()
        self.assertEqual((moved.status, moved.warehouse_id), ("in_stock", self.w2.pk))
        r = self.c.admin.post(f"/api/v1/purchase-orders/{po['id']}/void/", {}, format="json")
        self.assertEqual(r.status_code, 400, r.content)
        self.assertIn("甲M1", str(r.json()))
        moved.refresh_from_db()
        self.assertEqual((moved.status, moved.warehouse_id), ("in_stock", self.w2.pk))
        self.assertEqual(ProductSerial.objects.get(serial_no="甲M2").status, "in_stock")

    def test_purchase_with_the_same_item_on_two_lines_cannot_be_voided_past_zero(self):
        po = self.c._post("/api/v1/purchase-orders/", {
            "supplier": self.c.supplier.id, "warehouse": self.w1.id, "tax_method": "untaxed",
            "items": [{"product": self.c.case.id, "qty": 2, "unit_price": "100"},
                      {"product": self.c.case.id, "qty": 2, "unit_price": "100"}],
        })
        self.c.sell(case_qty=1)                  # 剩 3 個,不夠退整張單的 4 個
        r = self.c.admin.post(f"/api/v1/purchase-orders/{po['id']}/void/", {}, format="json")
        self.assertEqual(r.status_code, 400, r.content)
        self.assertIn("無法回退本單的 4 件", str(r.json()))
        self.assertEqual(StockBalance.objects.get(product=self.c.case, warehouse=self.w1).qty, 3)
        self.consistent()

    def test_transfer_with_the_same_item_on_two_lines_cannot_overdraw(self):
        self.c.purchase(case_qty=5)
        r = self.c.admin.post("/api/v1/transfer-orders/", {
            "from_warehouse": self.w1.id, "to_warehouse": self.w2.id,
            "items": [{"product": self.c.case.id, "qty": 3}, {"product": self.c.case.id, "qty": 3}],
        }, format="json")
        self.assertEqual(r.status_code, 400, r.content)
        self.assertIn("不足調撥", str(r.json()))
        self.assertEqual(StockBalance.objects.get(product=self.c.case, warehouse=self.w1).qty, 5)
        self.consistent()

    def repair(self, qty):
        return self.c._post("/api/v1/repair-orders/", {
            "warehouse": self.w1.id, "customer": self.c.customer.id,
            "received_date": str(date.today()), "mode": "in_house", "unlock_method": "none",
            "host_model_name": "iPhone 15",
            "parts_input": [{"part_product": self.c.case.id, "qty": qty}],
        })

    def test_repair_short_of_parts_keeps_the_books_adding_up(self):
        self.c.purchase(case_qty=1)
        order = self.repair(2)                   # 帳上只有 1 個,要用 2 個
        self.c._post(f"/api/v1/repair-orders/{order['id']}/complete/", {})
        self.assertEqual(StockBalance.objects.get(product=self.c.case, warehouse=self.w1).qty, 0)
        moves = list(
            StockMovement.objects.filter(tenant=self.c.tenant, ref_doc_id=order["id"],
                                         ref_doc_type__startswith="repair_order")
            .order_by("id").values_list("movement_type", "qty", "ref_doc_type")
        )
        self.assertEqual(moves, [("adjust", 1, "repair_order_shortage"),
                                 ("repair_usage", 2, "repair_order")])
        self.consistent()
        # 重開:歸還全部,帳仍然對得起來
        self.c._post(f"/api/v1/repair-orders/{order['id']}/reopen/", {})
        self.assertEqual(StockBalance.objects.get(product=self.c.case, warehouse=self.w1).qty, 2)
        self.consistent()

    def test_repair_completion_is_all_or_nothing(self):
        from apps.repairs import services
        from apps.repairs.models import RepairOrder

        self.c.purchase(case_qty=5)
        order = RepairOrder.objects.get(pk=self.repair(2)["id"])
        with mock.patch.object(services, "compute_in_house_quote", side_effect=RuntimeError("壞掉")):
            with self.assertRaises(RuntimeError):
                services.complete_repair_order(order)
        self.assertEqual(StockBalance.objects.get(product=self.c.case, warehouse=self.w1).qty, 5)
        self.assertFalse(StockMovement.objects.filter(movement_type="repair_usage").exists())
        order.refresh_from_db()
        self.assertNotEqual(order.status, "completed")

    def test_rows_are_locked_in_one_fixed_order(self):
        import re

        self.c.purchase(phone_serials=["甲P1", "甲P2"], case_qty=2)
        self.c.purchase(warehouse=self.w2, case_qty=2)
        serials = list(ProductSerial.objects.filter(serial_no__in=["甲P1", "甲P2"])
                       .order_by("-pk").values_list("pk", flat=True))
        with CaptureQueriesContext(connection) as ctx:
            from django.db import transaction
            with transaction.atomic():
                lock_stock_rows(
                    self.c.tenant, products=[self.c.phone, self.c.case], serial_ids=serials,
                    balances=[(self.c.case, self.w2), (self.c.case, self.w1)],
                )
        locks = [q["sql"] for q in ctx.captured_queries if "FOR " in q["sql"]]
        tables = [re.search(r'FROM "(\w+)"', q).group(1) for q in locks]
        self.assertEqual(tables, ["catalog_product", "inventory_productserial",
                                  "inventory_stockbalance", "inventory_stockbalance"])
        self.assertIn("NO KEY UPDATE", locks[0])
        self.assertIn("NO KEY UPDATE", locks[1])
        for q in locks:                          # 只鎖這家公司自己的列
            self.assertIn(f'"tenant_id" = {self.c.tenant.pk}', q)
        self.assertIn('ORDER BY "inventory_productserial"."id" ASC', locks[1])
        stores = [int(re.search(r'"warehouse_id" = (\d+)', q).group(1)) for q in locks[2:]]
        self.assertEqual(stores, sorted([self.w1.pk, self.w2.pk]))
