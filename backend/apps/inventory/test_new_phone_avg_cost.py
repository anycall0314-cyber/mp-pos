"""新機賣掉記平均成本(owner 2026-10-31)。

「新機如果是這樣計算,門市就會特別去找便宜的貨來賣,導致貴的一直放著沒人賣」→ 選「連實際成本也改」:
帶序號的新機(不是中古機)賣掉記的是商品的平均成本(全公司),同一款每一台都一樣;中古機照舊記那一台自己的成本。
這一台真的進價照舊記在那一台上,只給管理員看。規則在 `inventory.models.book_cost`。
"""
import threading
import time
from decimal import Decimal
from importlib import import_module

from django.apps import apps as django_apps
from django.db import connections
from django.test import TestCase, TransactionTestCase

from apps.backup.tests.factory import Company
from apps.catalog.models import Product
from apps.inventory.locking import average_lock_key
from apps.inventory.models import ProductSerial, StockCountMissing
from apps.ledger.snapshot import current_stock
from apps.parties.models import Member
from apps.purchasing.models import PurchaseOrder
from apps.sales.models import SalesOrderItem
from apps.sales.services import acquire_secondhand_from_member
from apps.trade.models import TradeOrderLine
from apps.trade.tests import _Helpers as _TradeHelpers

D = Decimal


class _Shop:
    def setUp(self):
        self.c = Company("a", "甲通訊行", "甲")

    def buy(self, price, *codes, warehouse=None):
        return self.c._post("/api/v1/purchase-orders/", {
            "supplier": self.c.supplier.id, "warehouse": (warehouse or self.c.wh).id, "tax_method": "untaxed",
            "items": [{"product": self.c.phone.id, "qty": len(codes), "unit_price": str(price),
                       "serial_numbers": list(codes)}],
        })

    def unit(self, code):
        return ProductSerial.objects.get(tenant=self.c.tenant, serial_no=code)

    def sell(self, code):
        """賣掉那一台,回傳那一行記的(實際成本, 業務員成本)。"""
        so = self.c.sell(serial_no=code)
        line = SalesOrderItem.objects.get(so_id=so["id"])
        return line.cost_at_post, line.staff_cost

    def avg(self, product=None):
        product = product or self.c.phone
        product.refresh_from_db()
        return product.weighted_avg_cost

    def void(self, po, expect=200):
        r = self.c.admin.post(f"/api/v1/purchase-orders/{po['id']}/void/", {}, format="json")
        self.assertEqual(r.status_code, expect, r.content.decode())
        return r.json()


class SaleCostTests(_Shop, TestCase):

    def test_the_cheap_unit_and_the_dear_unit_cost_the_same(self):
        self.buy(20000, "N1")
        self.buy(22000, "N2")
        self.assertEqual(self.avg(), D("21000.00"))
        self.assertEqual(self.sell("N1"), (D("21000.00"), D("21000.00")))     # 便宜那台:記平均,不是 20,000
        self.assertEqual(self.avg(), D("21000.00"))                             # 賣掉不動平均
        self.assertEqual(self.sell("N2"), (D("21000.00"), D("21000.00")))     # 貴那台也是 21,000
        # 這一台真的進價照舊記在那一台上
        self.assertEqual((self.unit("N1").purchase_unit_cost, self.unit("N2").purchase_unit_cost),
                         (D("20000.00"), D("22000.00")))

    def test_clerks_cannot_tell_the_cheap_unit_apart(self):
        self.buy(20000, "N1")
        self.buy(22000, "N2")
        units = self.c.clerk.get("/api/v1/serials/", {"product": self.c.phone.id}).json()["results"]
        self.assertEqual(sorted(D(u["staff_cost"]) for u in units), [D("21000"), D("21000")])
        self.assertTrue(all("purchase_unit_cost" not in u and "book_cost" not in u for u in units))
        report = self.c.clerk.get("/api/v1/serial-report/", {"status": "in_stock"}).json()
        self.assertEqual(sorted(D(r["cost"]) for r in report["results"]), [D("21000"), D("21000")])
        self.assertEqual(D(report["cost_total"]), D("42000"))
        # 履歷:收購來源那一行也是業務員成本
        history = self.c.clerk.get(f"/api/v1/serials/{self.unit('N1').id}/history/").json()
        self.assertEqual(D(history["acquisition"]["amount"]), D("21000"))
        # 管理員:帳上的成本是平均,真的進價在那一台上、履歷的收購來源那一行
        units = {u["serial_no"]: u for u in
                 self.c.admin.get("/api/v1/serials/", {"product": self.c.phone.id}).json()["results"]}
        self.assertEqual((D(units["N1"]["book_cost"]), D(units["N1"]["purchase_unit_cost"])), (D("21000"), D("20000")))
        history = self.c.admin.get(f"/api/v1/serials/{self.unit('N1').id}/history/").json()
        self.assertEqual(D(history["acquisition"]["amount"]), D("20000"))

    def test_sold_units_show_what_the_sale_recorded(self):
        self.buy(20000, "N1")
        self.buy(22000, "N2")
        self.sell("N1")
        self.buy(30000, "N3")                                                   # (21,000 + 30,000)÷ 2
        self.assertEqual(self.avg(), D("25500.00"))
        rows = {r["serial_no"]: D(r["cost"]) for r in
                self.c.admin.get("/api/v1/serial-report/").json()["results"]}
        self.assertEqual(rows, {"N1": D("21000"), "N2": D("25500"), "N3": D("25500")})
        # 在庫的合計照帳上的成本(兩台進價加起來是 52,000)
        report = self.c.admin.get("/api/v1/serial-report/", {"status": "in_stock"}).json()
        self.assertEqual(D(report["cost_total"]), D("51000"))

    def test_stock_value_is_the_average(self):
        self.buy(20000, "N1")
        self.buy(22000, "N2")
        self.sell("N1")
        # 剩下 N2(進價 22,000),帳上是平均 21,000:賣掉的那台記了 21,000,加起來剛好是兩台的進價
        key = (self.c.wh.id, self.c.phone.id, "in_stock")
        self.assertEqual(current_stock(self.c.tenant)[key], (1, D("21000.00")))

    def test_shortfall_and_units_at_the_vendor_are_valued_at_the_average(self):
        self.buy(20000, "N1")
        self.buy(22000, "N2")
        count = self.c.clerk.post("/api/v1/stock-counts/", {"warehouse": self.c.wh.id}, format="json").json()
        self.assertEqual(self.c.clerk.post(f"/api/v1/stock-counts/{count['id']}/scans/", {"code": "N1"},
                                           format="json").status_code, 200)
        r = self.c.clerk.post(f"/api/v1/stock-counts/{count['id']}/submit/", {"phones_done": True}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        seen = self.c.admin.get(f"/api/v1/stock-counts/{count['id']}/").json()
        self.assertEqual([(m["serial_no"], m["cost"]) for m in seen["missing_rows"]], [("N2", "21000.00")])
        self.assertEqual(seen["amounts"]["phones"], "-21000.00")                # 盤虧照平均,不是那台的 22,000
        self.c._post("/api/v1/vendor-exchanges/", {"code": "N1", "supplier": self.c.supplier.id})
        row = self.c.admin.get("/api/v1/vendor-exchanges/").json()["results"][0]
        self.assertEqual(row["amount"], "21000.00")                              # 在廠商那邊的成本也是平均

    def test_an_approved_shortfall_keeps_its_amount(self):
        self.buy(20000, "N1")
        self.buy(22000, "N2")
        count = self.c.clerk.post("/api/v1/stock-counts/", {"warehouse": self.c.wh.id}, format="json").json()
        self.c.clerk.post(f"/api/v1/stock-counts/{count['id']}/scans/", {"code": "N1"}, format="json")
        self.c.clerk.post(f"/api/v1/stock-counts/{count['id']}/submit/", {"phones_done": True}, format="json")
        r = self.c.admin.post(f"/api/v1/stock-counts/{count['id']}/approve/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.assertEqual(self.unit("N2").status, ProductSerial.Status.LOST)
        self.buy(30000, "N3")                                                   # 平均變成 25,500
        seen = self.c.admin.get(f"/api/v1/stock-counts/{count['id']}/").json()
        self.assertEqual(([m["cost"] for m in seen["missing_rows"]], seen["amounts"]["phones"]),
                         (["21000.00"], "-21000.00"))                           # 核准那一刻的,不跟著變
        # 以前就核准的:補上當時畫面上的數字(那一台的成本)
        StockCountMissing.objects.filter(count_id=count["id"]).update(unit_cost=None)
        import_module("apps.inventory.migrations.0026_stockcount_missing_unit_cost").backfill(django_apps, None)
        self.assertEqual(StockCountMissing.objects.get(count_id=count["id"]).unit_cost, D("22000.00"))

    def test_secondhand_still_records_its_own_cost(self):
        used = Product.objects.create(tenant=self.c.tenant, category=self.c.cat_phone, name="甲 中古 iPhone 13",
                                      is_secondhand=True, list_price=12000)
        member = Member.objects.create(tenant=self.c.tenant, name="王小明", phone="0911222333")
        units = [acquire_secondhand_from_member(
            tenant=self.c.tenant, member=member, warehouse=self.c.wh, secondhand_product=used, imei=imei,
            condition_grade="C", custom_unit_price=None, acquisition_price=price, payment_method_code="cash",
        )[0] for imei, price in (("356938035643809", "3000"), ("356938035643817", "5000"))]
        so = self.c._post("/api/v1/sales-orders/", {
            "customer": self.c.customer.id, "warehouse": self.c.wh.id, "tax_method": "untaxed",
            "sales_person": self.c.sales_person.id,
            "items": [{"product": used.id, "qty": 1, "unit_price": "9000", "serial_ids": [units[0].id]}],
            "payments": [{"method": "cash", "amount": "9000"}],
        })
        self.assertEqual(SalesOrderItem.objects.get(so_id=so["id"]).cost_at_post, D("3000.00"))
        clerk = {u["id"]: D(u["staff_cost"]) for u in
                 self.c.clerk.get("/api/v1/serials/", {"product": used.id}).json()["results"]}
        self.assertEqual(clerk[units[1].id], D("5000"))


class AverageKeepingTests(_Shop, TestCase):

    def test_units_in_transit_count(self):
        self.buy(20000, "N1")
        r = self.c.admin.post("/api/v1/transfer-orders/", {
            "from_warehouse": self.c.wh.id, "to_warehouse": self.c.warehouses[1].id,
            "items": [{"product": self.c.phone.id, "qty": 1, "serial_ids": [self.unit("N1").id]}],
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content.decode())
        self.assertEqual(self.unit("N1").status, ProductSerial.Status.IN_TRANSIT)
        self.buy(30000, "N2")
        self.assertEqual(self.avg(), D("25000.00"))                 # 不是 30,000:調撥途中那一台也算

    def test_voiding_a_purchase_takes_its_batch_back_out(self):
        self.buy(20000, "N1", "N2")
        wrong = self.buy(26000, "N3")
        self.assertEqual(self.avg(), D("22000.00"))
        self.void(wrong)
        self.assertEqual(self.avg(), D("20000.00"))                 # 打錯整張作廢:回到原本的平均

    def test_voiding_after_a_sale_keeps_the_books_whole(self):
        self.buy(20000, "N1", "N2")
        wrong = self.buy(26000, "N3")
        self.assertEqual(self.sell("N1")[0], D("22000.00"))
        self.void(wrong)
        # 進貨淨額 40,000 = 賣掉記的 22,000 + 剩下那一台 18,000(用剩下那台的進價重算會是 20,000,多出 2,000)
        self.assertEqual(self.avg(), D("18000.00"))

    def test_a_void_that_would_turn_the_average_negative_is_refused(self):
        self.buy(1000, "N1", "N2")
        wrong = self.buy(100000, "N3")                              # 平均 34,000
        self.sell("N1")
        self.assertIn("庫存成本已變動", self.void(wrong, expect=400)["detail"])
        self.assertFalse(PurchaseOrder.objects.get(pk=wrong["id"]).is_void)
        self.assertEqual(self.avg(), D("34000.00"))

    def test_existing_new_phones_line_up_with_what_is_left(self):
        self.buy(20000, "N1")
        self.buy(22000, "N2")
        self.buy(24000, "N3")
        r = self.c.admin.post("/api/v1/transfer-orders/", {
            "from_warehouse": self.c.wh.id, "to_warehouse": self.c.warehouses[1].id,
            "items": [{"product": self.c.phone.id, "qty": 1, "serial_ids": [self.unit("N3").id]}],
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content.decode())
        # 以前賣掉記那一台的進價:N1 賣掉之後剩下 N2、N3(調撥途中)= 46,000,平均卻停在 22,000
        ProductSerial.objects.filter(pk=self.unit("N1").pk).update(status=ProductSerial.Status.SOLD, warehouse=None)
        Product.objects.filter(pk=self.c.phone.pk).update(weighted_avg_cost=D("22000.00"))
        empty = Product.objects.create(tenant=self.c.tenant, category=self.c.cat_phone, name="甲 iPhone 16 黑",
                                       list_price=30000, weighted_avg_cost=D("123.00"))
        used = Product.objects.create(tenant=self.c.tenant, category=self.c.cat_phone, name="甲 中古 iPhone 13",
                                      is_secondhand=True, list_price=12000, weighted_avg_cost=D("456.00"))
        member = Member.objects.create(tenant=self.c.tenant, name="王小明", phone="0911222333")
        acquire_secondhand_from_member(
            tenant=self.c.tenant, member=member, warehouse=self.c.wh, secondhand_product=used,
            imei="356938035643809", condition_grade="C", custom_unit_price=None, acquisition_price="3000",
            payment_method_code="cash",
        )
        Product.objects.filter(pk=used.pk).update(weighted_avg_cost=D("456.00"))

        import_module("apps.inventory.migrations.0025_new_phone_avg_cost").recompute(django_apps, None)
        self.assertEqual(self.avg(), D("23000.00"))                 # (22,000 + 24,000)÷ 2
        self.assertEqual(self.avg(empty), D("123.00"))             # 一台都沒有的不動
        self.assertEqual(self.avg(used), D("456.00"))              # 中古機不動


class TwoAtOnceTests(_TradeHelpers, TransactionTestCase):
    """真的兩條連線(複審 2026-10-31 兩輪的 P1):新機賣掉讀平均成本、進貨 / 作廢 / 盤點 / 整理改平均成本,
    都在鎖任何一列之前先拿那個品號的平均成本鎖(`locking.lock_averages`)。另一條連線拿同一把鎖,假裝是另一張單。"""

    def other(self, first, then=(), wait=0.0, hold=1.0):
        """另一條連線:先做 first(拿到鎖)、過 wait 秒再做 then、握到 hold 秒才提交。回傳(thread, 它出的錯)。"""
        holding, errors = threading.Event(), []

        def work():
            conn = connections.create_connection("default")
            try:
                conn.ensure_connection()
                conn.set_autocommit(False)
                with conn.cursor() as cur:
                    for sql, args in first:
                        cur.execute(sql, args)
                    holding.set()
                    time.sleep(wait)
                    for sql, args in then:
                        cur.execute(sql, args)
                time.sleep(max(hold - wait, 0))
                conn.commit()
            except Exception as exc:          # 死結被資料庫中止也記下來
                errors.append(exc)
                holding.set()
            finally:
                conn.close()

        t = threading.Thread(target=work)
        t.start()
        self.addCleanup(t.join)
        self.assertTrue(holding.wait(5))
        return t, errors

    @staticmethod
    def average_lock(product):
        return "SELECT pg_advisory_xact_lock(%s, %s)", list(average_lock_key(product.id))

    @staticmethod
    def lock_row(table, pk):
        return f"SELECT 1 FROM {table} WHERE id = %s FOR NO KEY UPDATE", [pk]

    def set_avg(self, product, value):
        return "UPDATE catalog_product SET weighted_avg_cost = %s WHERE id = %s", [value, product.id]

    def waited(self, began):
        self.assertGreater(time.monotonic() - began, 0.5)

    def test_a_sale_waits_for_a_purchase_of_the_same_model(self):
        self.a.purchase(phone_serials=["N1"])                                   # 平均 20,000
        # 另一張進貨單:拿著這一款的平均成本鎖、把平均改成 25,000,還沒提交
        t, errors = self.other([self.average_lock(self.a.phone), self.lock_row("catalog_product", self.a.phone.id),
                                self.set_avg(self.a.phone, 25000)], hold=0.8)
        doc = self.a.sell(serial_no="N1")                                       # 等他提交才做得下去
        t.join()
        self.assertEqual(errors, [])
        self.assertEqual(SalesOrderItem.objects.get(so_id=doc["id"]).cost_at_post, D("25000.00"))

    def test_a_phone_and_a_case_sold_while_both_are_bought_do_not_deadlock(self):
        # 第二輪 P1:配件編號比新機小。進貨照編號先鎖配件、再鎖新機;銷貨的庫存餘額鎖會連帶鎖配件那一列
        phone = Product.objects.create(tenant=self.seller, category=self.a.cat_phone, name="甲 iPhone 16 黑", list_price=30000)
        self.assertLess(self.a.case.id, phone.id)
        self.a._post("/api/v1/purchase-orders/", {
            "supplier": self.a.supplier.id, "warehouse": self.wh1.id, "tax_method": "untaxed",
            "items": [{"product": phone.id, "qty": 1, "unit_price": "28000", "serial_numbers": ["P1"]},
                      {"product": self.a.case.id, "qty": 5, "unit_price": "100"}]})
        unit = ProductSerial.objects.get(tenant=self.seller, serial_no="P1")
        t, errors = self.other([self.average_lock(phone), self.lock_row("catalog_product", self.a.case.id)],
                               then=[self.lock_row("catalog_product", phone.id)], wait=0.4, hold=1.0)
        self.a._post("/api/v1/sales-orders/", {
            "customer": self.a.customer.id, "warehouse": self.wh1.id, "tax_method": "untaxed",
            "sales_person": self.a.sales_person.id,
            "items": [{"product": phone.id, "qty": 1, "unit_price": "32000", "serial_ids": [unit.id]},
                      {"product": self.a.case.id, "qty": 1, "unit_price": "390"}],
            "payments": [{"method": "cash", "amount": "32390"}]})
        t.join()
        self.assertEqual(errors, [])

    def test_buying_and_voiding_a_purchase_wait_for_a_sale_of_the_same_model(self):
        self.a.purchase(phone_serials=["N1"])
        t, errors = self.other([self.average_lock(self.a.phone)], hold=0.8)     # 一張正在賣這一款的銷貨單
        began = time.monotonic()
        po = self.a.purchase(phone_serials=["N2"])
        self.waited(began)
        t.join()
        t, errors = self.other([self.average_lock(self.a.phone)], hold=0.8)
        began = time.monotonic()
        r = self.a.admin.post(f"/api/v1/purchase-orders/{po['id']}/void/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.waited(began)
        t.join()
        self.assertEqual(errors, [])

    def test_shipping_to_a_dealer_and_a_counter_sale_do_not_deadlock(self):
        self.open_shop()
        self.a.purchase(phone_serials=["N700"])
        self.offer(self.a.phone, price=23000)
        self.approve(self.b)
        got = self.buy(self.b, [{"sku": self.a.phone.sku, "spec_id": None, "qty": 1}])
        unit = ProductSerial.objects.get(tenant=self.seller, serial_no="N700")
        line = TradeOrderLine.objects.get(order__no=got["order_no"])
        # 門市的銷貨:先拿平均成本鎖、過一下才鎖那一台;出貨要是先鎖那一台才拿平均成本鎖,兩邊會互等
        t, errors = self.other([self.average_lock(self.a.phone)], then=[self.lock_row("inventory_productserial", unit.id)],
                               wait=0.4, hold=1.0)
        self.ship(got["order_no"], lines=[{"line": line.id, "qty": 1, "serials": [unit.id]}])
        t.join()
        self.assertEqual(errors, [])

    def test_approving_a_shortfall_waits_for_a_purchase_of_the_same_model(self):
        self.a.purchase(phone_serials=["N1", "N2"])                             # 平均 20,000
        count = self.a.clerk.post("/api/v1/stock-counts/", {"warehouse": self.a.wh.id}, format="json").json()
        self.a.clerk.post(f"/api/v1/stock-counts/{count['id']}/scans/", {"code": "N1"}, format="json")
        self.a.clerk.post(f"/api/v1/stock-counts/{count['id']}/submit/", {"phones_done": True}, format="json")
        t, errors = self.other([self.average_lock(self.a.phone), self.lock_row("catalog_product", self.a.phone.id),
                                self.set_avg(self.a.phone, 25000)], hold=0.8)
        r = self.a.admin.post(f"/api/v1/stock-counts/{count['id']}/approve/", {}, format="json")
        t.join()
        self.assertEqual((r.status_code, errors), (200, []), r.content.decode())
        self.assertEqual(StockCountMissing.objects.get(count_id=count["id"]).unit_cost, D("25000.00"))

    def test_finishing_and_reopening_a_refurb_wait_for_a_sale_of_the_same_model(self):
        self.a.purchase(phone_serials=["N1"])
        unit = ProductSerial.objects.get(tenant=self.seller, serial_no="N1")
        r = self.a.admin.post("/api/v1/repair-orders/", {
            "stock_serial": unit.id, "warehouse": self.wh1.id, "received_date": "2026-10-31",
            "mode": "external", "external_vendor": self.a.supplier.id, "unlock_method": "none",
            "defect_description": "外盒壓傷、換電池", "sales_person": self.a.sales_person.id,
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content.decode())
        url = f"/api/v1/repair-orders/{r.json()['id']}/"
        self.assertEqual(self.a.admin.patch(url, {"external_quote_actual": 1000}, format="json").status_code, 200)
        for action in ("complete", "reopen"):
            t, errors = self.other([self.average_lock(self.a.phone)], hold=0.8)
            began = time.monotonic()
            r = self.a.admin.post(f"{url}{action}/", {}, format="json")
            self.assertEqual(r.status_code, 200, r.content.decode())
            self.waited(began)
            t.join()
            self.assertEqual(errors, [])
