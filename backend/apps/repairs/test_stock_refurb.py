"""自家庫存的機器送去整理(owner 2026-10-29:收購的中古機機況太差,整理完再賣;自修或外包;工資先不算)。

整理花的錢(零件成本 / 委外實際費用)加進那一台的成本;整理中不能賣、不能調撥;重開扣回、作廢放回。規則在 repairs/stock.py。
"""
import threading
import time
from decimal import Decimal

from django.db import connections
from django.test import TestCase, TransactionTestCase

from apps.backup.tests.factory import Company
from apps.catalog.models import Product
from apps.inventory import stockcount
from apps.inventory.identifiers import create_serial
from apps.inventory.models import ProductSerial, StockBalance, StockMovement
from apps.ledger import checks
from apps.repairs import report
from apps.repairs.models import RepairOrder, RepairOrderPart
from apps.sales.models import SalesOrderItem

S = ProductSerial.Status
URL = "/api/v1/repair-orders/"
D = Decimal


class _Refurb:
    def make_company(self):
        self.c = Company("a", "甲通訊行", "甲")
        self.home, self.other = self.c.warehouses
        self.c.purchase(phone_serials=["R0001", "R0002"], case_qty=10)        # 手機一台 20,000、皮套一個 100
        self.c.purchase(warehouse=self.other, phone_serials=["R0003"])
        self.unit = ProductSerial.objects.get(tenant=self.c.tenant, serial_no="R0001")

    def open(self, serial=None, client=None, **body):
        payload = {
            "stock_serial": (serial or self.unit).id, "warehouse": self.home.id, "received_date": "2026-10-29",
            "mode": "in_house", "unlock_method": "none", "defect_description": "螢幕刮傷、電池老化",
            "sales_person": self.c.sales_person.id, **body,
        }
        return (client or self.c.admin).post(URL, payload, format="json")

    def opened(self, **body):
        r = self.open(**body)
        self.assertEqual(r.status_code, 201, r.content.decode())
        return r.json()

    def complete(self, pk, client=None):
        return (client or self.c.admin).post(f"{URL}{pk}/complete/", {}, format="json")

    def patch(self, pk, **body):
        r = self.c.admin.patch(f"{URL}{pk}/", body, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        return r.json()


class RefurbTests(_Refurb, TestCase):
    def setUp(self):
        self.make_company()

    def test_open_puts_it_aside_without_a_member(self):
        row = self.opened()
        self.unit.refresh_from_db()
        self.assertEqual((self.unit.status, self.unit.warehouse_id), (S.REFURB, self.home.id))   # 不搬
        self.assertEqual(row["device_serial"], "R0001")
        self.assertEqual(row["host_model_name"], self.c.phone.name)
        self.assertEqual(row["stock_serial_detail"]["status_label"], "整理中")
        move = StockMovement.objects.get(serial=self.unit, movement_type=StockMovement.MovementType.REFURB)
        self.assertEqual((move.from_warehouse_id, move.to_warehouse_id), (None, None))   # 只是紀錄,不動數量
        # 不能賣、不能調撥
        sale = self.c.admin.post("/api/v1/sales-orders/", {
            "customer": self.c.customer.id, "warehouse": self.home.id, "tax_method": "untaxed",
            "sales_person": self.c.sales_person.id,
            "items": [{"product": self.c.phone.id, "qty": 1, "unit_price": "25000", "serial_ids": [self.unit.id]}],
            "payments": [{"method": "cash", "amount": "25000"}],
        }, format="json")
        self.assertEqual(sale.status_code, 400, sale.content)
        move = self.c.admin.post("/api/v1/transfer-orders/", {
            "from_warehouse": self.home.id, "to_warehouse": self.other.id,
            "items": [{"product": self.c.phone.id, "qty": 1, "serial_ids": [self.unit.id]}],
        }, format="json")
        self.assertEqual(move.status_code, 400, move.content)
        self.unit.refresh_from_db()
        self.assertEqual((self.unit.status, self.unit.warehouse_id), (S.REFURB, self.home.id))
        # 同一台不能再開一張
        self.assertEqual(self.open().status_code, 400)

    def test_in_house_adds_the_parts_cost_not_the_labor(self):
        row = self.opened(parts_input=[{"part_product": self.c.case.id, "qty": 3}], labor_fee="800")
        self.assertEqual(self.complete(row["id"]).status_code, 200)
        self.unit.refresh_from_db()
        self.assertEqual(self.unit.status, S.IN_STOCK)
        self.assertEqual(self.unit.purchase_unit_cost, D("20300.00"))           # 20,000 + 零件 3 × 100;工資不算
        order = RepairOrder.objects.get(pk=row["id"])
        self.assertEqual(order.stock_cost_added, D("300.00"))
        self.assertEqual(StockBalance.objects.get(product=self.c.case, warehouse=self.home).qty, 7)   # 零件照扣
        # 商品的平均成本:三台 60,000 + 300 → 20,100
        self.c.phone.refresh_from_db()
        self.assertEqual(self.c.phone.weighted_avg_cost, D("20100.00"))
        # 賣掉:新機記平均成本(整理費已經攤進平均;2026-10-31)。中古機記那一台自己的(收購 + 整理),見 sales/test_buyback_cost.py
        so = self.c.sell(serial_no="R0001")
        self.assertEqual(SalesOrderItem.objects.get(so_id=so["id"], product=self.c.phone).cost_at_post, D("20100.00"))

    def test_external_adds_what_the_vendor_charged(self):
        row = self.opened(mode="external", external_vendor=self.c.supplier.id, external_quote_estimated="1200")
        self.patch(row["id"], external_quote_actual="1500")
        self.assertEqual(self.complete(row["id"]).status_code, 200)
        self.unit.refresh_from_db()
        self.assertEqual((self.unit.status, self.unit.purchase_unit_cost), (S.IN_STOCK, D("21500.00")))

    def test_twice_adds_up_and_history_shows_the_parts(self):
        first = self.opened(mode="external", external_vendor=self.c.supplier.id)
        self.patch(first["id"], external_quote_actual="1500")
        self.complete(first["id"])
        second = self.opened(parts_input=[{"part_product": self.c.case.id, "qty": 2}])
        self.complete(second["id"])
        self.unit.refresh_from_db()
        self.assertEqual(self.unit.purchase_unit_cost, D("21700.00"))
        data = self.c.admin.get(f"/api/v1/serials/{self.unit.id}/history/").json()
        self.assertEqual(D(data["acquisition"]["amount"]), D("20000"))          # 進貨的金額不含整理
        self.assertEqual([(r["no"], D(r["cost_added"])) for r in data["refurbs"]],
                         [(first["no"], D("1500")), (second["no"], D("200"))])
        self.assertEqual(D(data["serial"]["purchase_unit_cost"]), D("21700"))
        # 加進去的是零件的實際成本:只有管理員拆得出來;店員看到的進貨金額是這一台的業務員成本
        # (新機是平均成本:三台 60,000 + 整理 1,700;2026-10-31)
        data = self.c.clerk.get(f"/api/v1/serials/{self.unit.id}/history/").json()
        self.assertEqual([r["cost_added"] for r in data["refurbs"]], [None, None])
        self.assertEqual(D(data["acquisition"]["amount"]), D("20566.67"))

    def test_no_money_from_a_customer_and_not_in_the_monthly_report(self):
        self.assertEqual(self.open(customer_paid_amount="500").status_code, 400)
        self.assertEqual(self.open(customer=self.c.customer.id).status_code, 400)
        row = self.opened(parts_input=[{"part_product": self.c.case.id, "qty": 1}])
        r = self.c.admin.patch(f"{URL}{row['id']}/", {"customer_paid_amount": "300"}, format="json")
        self.assertEqual(r.status_code, 400, r.content)
        other = ProductSerial.objects.get(serial_no="R0002")
        r = self.c.admin.patch(f"{URL}{row['id']}/", {"stock_serial": other.id}, format="json")
        self.assertEqual(r.status_code, 400, r.content)                        # 建單之後不能換台
        self.complete(row["id"])
        from django.utils import timezone
        today = timezone.localdate()
        self.assertEqual(report.completed(self.c.tenant, start=today, end=today), [])

    def test_reopen_takes_it_back_and_void_releases(self):
        row = self.opened(parts_input=[{"part_product": self.c.case.id, "qty": 2}])
        self.complete(row["id"])
        r = self.c.admin.post(f"{URL}{row['id']}/reopen/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.unit.refresh_from_db()
        self.assertEqual((self.unit.status, self.unit.purchase_unit_cost), (S.REFURB, D("20000.00")))
        self.assertEqual(RepairOrder.objects.get(pk=row["id"]).stock_cost_added, D("0"))
        self.c.phone.refresh_from_db()
        self.assertEqual(self.c.phone.weighted_avg_cost, D("20000.00"))
        self.assertEqual(StockBalance.objects.get(product=self.c.case, warehouse=self.home).qty, 10)
        r = self.c.admin.post(f"{URL}{row['id']}/void/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.unit.refresh_from_db()
        self.assertEqual((self.unit.status, self.unit.purchase_unit_cost), (S.IN_STOCK, D("20000.00")))

    def test_reopen_refused_once_it_is_sold(self):
        row = self.opened(parts_input=[{"part_product": self.c.case.id, "qty": 1}])
        self.complete(row["id"])
        self.c.sell(serial_no="R0001")
        r = self.c.admin.post(f"{URL}{row['id']}/reopen/", {}, format="json")
        self.assertEqual(r.status_code, 400, r.content)
        self.unit.refresh_from_db()
        self.assertEqual((self.unit.status, self.unit.purchase_unit_cost), (S.SOLD, D("20100.00")))
        self.assertEqual(RepairOrder.objects.get(pk=row["id"]).status, RepairOrder.Status.COMPLETED)

    def test_only_in_stock_and_clerk_only_in_own_store(self):
        self.c.sell(serial_no="R0002")
        sold = ProductSerial.objects.get(serial_no="R0002")
        self.assertEqual(self.open(serial=sold).status_code, 400)
        far = ProductSerial.objects.get(serial_no="R0003")              # 在另一家門市
        r = self.open(serial=far, client=self.c.clerk)
        self.assertEqual(r.status_code, 400, r.content)
        far.refresh_from_db()
        self.assertEqual(far.status, S.IN_STOCK)
        [look] = self.c.clerk.get(f"{URL}stock-search/", {"q": "R0003"}).json()
        self.assertEqual((look["ok"], look["reason"]), (False, "這一台不在你的門市"))
        [look] = self.c.clerk.get(f"{URL}stock-search/", {"q": "R0001"}).json()
        self.assertEqual((look["ok"], look["product_name"]), (True, self.c.phone.name))
        self.assertEqual(self.open(client=self.c.clerk).status_code, 201)

    def test_stock_count_lists_it_and_does_not_lose_it(self):
        row = self.opened()
        count = stockcount.open_count(self.c.tenant, self.home, [], self.c.admin_user)
        self.assertNotIn(self.unit.id, set(stockcount.expected_serials(count).values_list("pk", flat=True)))
        rows = self.c.clerk.get(f"/api/v1/stock-counts/{count.id}/").json()["refurb_rows"]
        self.assertEqual([(x["serial_no"], x["repair_no"]) for x in rows], [("R0001", row["no"])])
        # 盤到一半整理完回到在庫:那一區已經盤過、沒刷到 → 不能變成盤虧
        self.complete(row["id"])
        self.assertNotIn(self.unit.id, set(stockcount.expected_serials(count).values_list("pk", flat=True)))
        self.assertIn(ProductSerial.objects.get(serial_no="R0002").pk,
                      set(stockcount.expected_serials(count).values_list("pk", flat=True)))

    def test_counted_everywhere_else_as_stock(self):
        self.opened()
        for result in checks.check_serials(self.c.tenant):
            self.assertEqual(result["samples"], [], result)
        from apps.ledger.snapshot import take_snapshot
        from apps.ledger.models import StockSnapshot

        take_snapshot(self.c.tenant)
        snap = StockSnapshot.objects.get(tenant=self.c.tenant, product=self.c.phone, warehouse=self.home,
                                         state=StockSnapshot.State.REFURB)
        self.assertEqual((snap.qty, snap.cost_value), (1, D("20000.00")))

    def test_daily_checks_stay_clean_after_finishing(self):
        row = self.opened(parts_input=[{"part_product": self.c.case.id, "qty": 1}])
        self.complete(row["id"])
        for result in checks.check_serials(self.c.tenant):
            self.assertEqual(result["samples"], [], result)
        for result in checks.check_stock_balance(self.c.tenant):
            self.assertEqual(result["samples"], [], result)


class RefurbAtOnceTests(_Refurb, TransactionTestCase):
    """另一條連線先鎖住、改掉、停一下才存檔:這邊要等它、看到它改過的(inventory/test_locking.py 同一套)。"""

    def setUp(self):
        self.make_company()

    def meanwhile(self, statements, hold=1.0):
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

    def test_open_waits_for_someone_selling_it(self):
        self.meanwhile([
            ("SELECT 1 FROM inventory_productserial WHERE id = %s FOR UPDATE", [self.unit.pk]),
            ("UPDATE inventory_productserial SET status = 'sold', warehouse_id = NULL WHERE id = %s", [self.unit.pk]),
        ])
        r = self.open()
        self.assertEqual(r.status_code, 400, r.content)
        self.unit.refresh_from_db()
        self.assertEqual(self.unit.status, S.SOLD)
        self.assertFalse(RepairOrder.objects.filter(stock_serial=self.unit).exists())

    def test_finish_waits_for_a_purchase_moving_the_average(self):
        row = self.opened(mode="external", external_vendor=self.c.supplier.id)
        RepairOrder.objects.filter(pk=row["id"]).update(external_quote_actual=D("900"))
        self.meanwhile([
            ("SELECT 1 FROM catalog_product WHERE id = %s FOR UPDATE", [self.c.phone.pk]),
            ("UPDATE catalog_product SET weighted_avg_cost = 30000 WHERE id = %s", [self.c.phone.pk]),
        ])
        self.assertEqual(self.complete(row["id"]).status_code, 200)
        self.c.phone.refresh_from_db()
        self.assertEqual(self.c.phone.weighted_avg_cost, D("30300.00"))        # 30,000 + 900 ÷ 3 台

    def test_reopen_locks_products_in_id_order(self):
        """重開:零件(編號小)與那一台的商品(編號大)照編號鎖(複審 2026-10-29 P1)。進貨先鎖零件、再鎖那一台的商品;
        重開如果先鎖那一台的商品、再從零件的庫存餘額連帶鎖零件,兩邊互卡。這裡:另一條連線鎖住零件、停一下,
        再試著不等待地鎖那一台的商品 —— 重開照編號的話,這時還在等零件、那一台的商品沒被它拿走。"""
        from apps.catalog.models import Product

        newer = Product.objects.create(tenant=self.c.tenant, category=self.c.cat_phone, name="甲 iPhone 16 128GB 黑",
                                       list_price=30000)
        self.assertGreater(newer.pk, self.c.case.pk)
        self.c._post("/api/v1/purchase-orders/", {
            "supplier": self.c.supplier.id, "warehouse": self.home.id, "tax_method": "untaxed",
            "items": [{"product": newer.id, "qty": 1, "unit_price": "25000", "serial_numbers": ["R0016"]}],
        })
        unit = ProductSerial.objects.get(tenant=self.c.tenant, serial_no="R0016")
        row = self.opened(serial=unit, parts_input=[{"part_product": self.c.case.id, "qty": 1}])
        self.assertEqual(self.complete(row["id"]).status_code, 200)

        holding, result = threading.Event(), {}

        def other_person():
            conn = connections.create_connection("default")
            try:
                conn.ensure_connection()
                conn.set_autocommit(False)
                with conn.cursor() as cur:
                    cur.execute("SELECT 1 FROM catalog_product WHERE id = %s FOR NO KEY UPDATE", [self.c.case.pk])
                    holding.set()
                    time.sleep(1.0)                         # 重開這時已經開始、正在等零件
                    try:
                        cur.execute("SELECT 1 FROM catalog_product WHERE id = %s FOR NO KEY UPDATE NOWAIT", [newer.pk])
                        result["got_it"] = True
                    except Exception:
                        result["got_it"] = False
                conn.rollback()
            finally:
                conn.close()

        t = threading.Thread(target=other_person)
        t.start()
        self.addCleanup(t.join)
        self.assertTrue(holding.wait(5))
        r = self.c.admin.post(f"{URL}{row['id']}/reopen/", {}, format="json")
        t.join()
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(result["got_it"])
        unit.refresh_from_db()
        self.assertEqual((unit.status, unit.purchase_unit_cost), (S.REFURB, D("25000.00")))

    def test_part_cost_is_read_after_the_lock(self):
        row = self.opened(parts_input=[{"part_product": self.c.case.id, "qty": 1}])
        RepairOrderPart.objects.filter(repair_order_id=row["id"]).update(unit_cost=D("0"), staff_unit_cost=None)
        self.meanwhile([
            ("SELECT 1 FROM catalog_product WHERE id = %s FOR UPDATE", [self.c.case.pk]),
            ("UPDATE catalog_product SET weighted_avg_cost = 150 WHERE id = %s", [self.c.case.pk]),
        ])
        self.assertEqual(self.complete(row["id"]).status_code, 200)
        self.unit.refresh_from_db()
        self.assertEqual(self.unit.purchase_unit_cost, D("20150.00"))


class StockSearchTests(_Refurb, TestCase):
    """owner 2026-10-29:「整理自家庫存,手動打序號,我希望可以打品名,或是打上序號前幾碼,會自動帶出最接近的手機」"""

    def setUp(self):
        self.make_company()
        self.c.purchase(phone_serials=["35612345", "11135612"])
        longer = Product.objects.create(tenant=self.c.tenant, category=self.c.cat_phone,
                                        name="甲 Apple iPhone 15 128GB 黑", list_price=20000)
        create_serial(tenant=self.c.tenant, product=longer, code="L0001", warehouse=self.home)

    def find(self, q, client=None):
        r = (client or self.c.admin).get(f"{URL}stock-search/", {"q": q})
        self.assertEqual(r.status_code, 200, r.content)
        return [(x["serial_no"], x["ok"], x["exact"]) for x in r.json()]

    def test_first_digits_put_the_ones_that_start_with_it_first(self):
        self.assertEqual(self.find("356"), [("35612345", True, False), ("11135612", True, False)])   # 開頭相同的先

    def test_name_ignores_case_and_spaces_and_the_shorter_name_comes_first(self):
        rows = self.find("iphone15")
        self.assertEqual(len(rows), 6)
        self.assertEqual(rows[-1], ("L0001", True, False))               # 品名比較長,排後面(照字排它會在前面)
        self.assertEqual({r[0] for r in rows[:5]}, {"R0001", "R0002", "R0003", "35612345", "11135612"})
        self.assertEqual(len(self.find("15 黑")), 6)
        self.assertEqual(self.find("15 白"), [])

    def test_a_scanned_code_is_marked_and_shown_even_when_it_cannot_go(self):
        self.assertEqual(self.find("R0002"), [("R0002", True, True)])
        self.c.sell(serial_no="R0002")
        r = self.c.admin.get(f"{URL}stock-search/", {"q": "R0002"}).json()
        self.assertEqual([(x["ok"], x["exact"], x["reason"]) for x in r], [(False, True, "這一台已售,不能送去整理")])
        self.assertEqual(self.find("R000"), [("R0001", True, False), ("R0003", True, False)])   # 已售的打一半不列

    def test_clerk_only_sees_own_store(self):
        self.assertEqual(self.find("R000", client=self.c.clerk), [("R0001", True, False), ("R0002", True, False)])
        r = self.c.clerk.get(f"{URL}stock-search/", {"q": "R0003"}).json()
        self.assertEqual([(x["serial_no"], x["ok"], x["reason"]) for x in r], [("R0003", False, "這一台不在你的門市")])

    def test_nothing_typed_lists_secondhand_and_refurbishing_ones_drop_out(self):
        self.assertEqual(self.find(""), [])
        Product.objects.filter(pk=self.c.phone.pk).update(is_secondhand=True)   # 用過的商品不能改旗標,這裡直接改資料
        self.assertEqual([r[0] for r in self.find("")], ["11135612", "35612345", "R0003", "R0002", "R0001"])
        self.opened()                                                    # R0001 送去整理
        self.assertNotIn("R0001", [r[0] for r in self.find("iphone")])
