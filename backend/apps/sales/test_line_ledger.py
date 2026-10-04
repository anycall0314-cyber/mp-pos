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

    def give_back(self, so, item_id, qty, serial_ids=()):
        price = str(SalesOrderItem.objects.get(pk=item_id).unit_price)
        return self.c._post("/api/v1/sales-returns/", {
            "original_so": so["id"], "warehouse": self.c.wh.id, "payment_method": "cash",
            "items": [{"original_item": item_id, "qty": qty, "unit_price": price,
                       "serial_ids": list(serial_ids)}],
        })

    def test_returns_reverse_exactly_the_cost_that_was_booked(self):
        so = self.sell("taxable_included", [
            {"product": self.c.case.id, "qty": 3, "unit_price": "390"},
        ], "1170")
        # 成本存到分,正常賣出時一定除得盡;舊資料可能除不盡,直接設一個除不盡的成本來測零頭
        SalesOrderItem.objects.filter(so_id=so["id"]).update(cost_at_post=D("100.00"))
        line = SalesOrderItem.objects.get(so_id=so["id"])
        first = self.give_back(so, line.id, 1)
        self.assertEqual(D(first["items"][0]["cost_at_post"]), D("33.33"))
        self.assert_lines_match_header(first, first["items"])
        # 作廢一張再退:作廢的不算進「先前已沖回」
        voided = self.give_back(so, line.id, 1)
        r = self.c.admin.post(f"/api/v1/sales-returns/{voided['id']}/void/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        second = self.give_back(so, line.id, 1)
        self.assertEqual(D(second["items"][0]["cost_at_post"]), D("33.33"))
        last = self.give_back(so, line.id, 1)
        self.assertEqual(D(last["items"][0]["cost_at_post"]), D("33.34"))
        live = SalesReturnItem.objects.filter(original_item=line, sr__is_void=False)
        self.assertEqual(sum(i.cost_at_post for i in live), line.cost_at_post)

    def test_serial_return_reverses_that_phone_cost(self):
        serial = ProductSerial.objects.get(serial_no="IMEI-2")
        so = self.sell("untaxed", [
            {"product": self.c.phone.id, "qty": 1, "unit_price": "25000", "serial_ids": [serial.id]},
        ], "25000")
        line = SalesOrderItem.objects.get(so_id=so["id"])
        back = self.give_back(so, line.id, 1, [serial.id])
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
        # 除不盡的成本(舊資料可能這樣):分兩次退,第二次要拿餘數
        SalesOrderItem.objects.filter(pk=case_line.pk).update(cost_at_post=D("100.01"))
        self.give_back(orders[0], case_line.id, 1)
        self.give_back(orders[0], case_line.id, 1)
        phone_line = SalesOrderItem.objects.get(so_id=orders[0]["id"], line_no=1)
        self.give_back(orders[0], phone_line.id, 1, [serial.id])

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

    def test_same_line_twice_in_one_return_is_refused(self):
        r = self.c.admin.post("/api/v1/sales-returns/", {
            "original_so": self.so["id"], "warehouse": self.c.wh.id, "payment_method": "cash",
            "items": [
                {"original_item": self.line.id, "qty": 1, "unit_price": "390"},
                {"original_item": self.line.id, "qty": 1, "unit_price": "390"},
            ],
        }, format="json")
        self.assertEqual(r.status_code, 400, r.content)
        self.assertIn("同一行", r.json()["detail"])
        self.assertFalse(SalesReturnItem.objects.exists())


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
        other_line = SalesOrderItem.objects.get(so_id=other["id"])
        r = self.a.admin.post("/api/v1/sales-returns/", {
            "original_so": self.so["id"], "warehouse": self.a.wh.id, "payment_method": "cash",
            "items": [{"original_item": other_line.id, "qty": 1, "unit_price": "390"}],
        }, format="json")
        self.assertEqual(r.status_code, 400, r.content)
        self.assertIn("不是原銷貨單", r.json()["detail"])

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

    def test_store_locked_clerk_cannot_sell_or_take_returns_for_another_store(self):
        other_store = self.a.warehouses[1]
        r = self.a.clerk.post("/api/v1/sales-orders/", {
            "customer": self.a.customer.id, "warehouse": other_store.id, "tax_method": "untaxed",
            "items": [{"product": self.a.case.id, "qty": 1, "unit_price": "390"}],
            "payments": [{"method": "cash", "amount": "390"}],
        }, format="json")
        self.assertEqual(r.status_code, 403, r.content)
        case_line = SalesOrderItem.objects.get(so_id=self.so["id"], product=self.a.case)
        r = self.a.clerk.post("/api/v1/sales-returns/", {
            "original_so": self.so["id"], "warehouse": other_store.id, "payment_method": "cash",
            "items": [{"original_item": case_line.id, "qty": 1, "unit_price": "390"}],
        }, format="json")
        self.assertEqual(r.status_code, 403, r.content)


class BackfillRuleTests(TestCase):
    # 借用 LedgerTests 的準備與小工具,不繼承它的測試(否則會整組再跑一次)
    setUp = LedgerTests.setUp
    sell = LedgerTests.sell
    give_back = LedgerTests.give_back

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
        first = self.give_back(so, line.id, 1)
        self.give_back(so, line.id, 1)
        self.give_back(so, line.id, 1)
        r = self.c.admin.post(f"/api/v1/sales-returns/{first['id']}/void/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.give_back(so, line.id, 1)
        SalesReturnItem.objects.update(cost_at_post=0)
        backfill(django_apps, None)
        live = SalesReturnItem.objects.filter(original_item=line, sr__is_void=False)
        self.assertEqual(live.count(), 3)
        self.assertEqual(sum(i.cost_at_post for i in live), line.cost_at_post)
        voided = SalesReturnItem.objects.get(sr_id=first["id"])
        self.assertEqual(voided.cost_at_post, D("33.33"))

    def test_backfill_voided_return_never_takes_the_remainder(self):
        so = self.sell("untaxed", [{"product": self.c.case.id, "qty": 3, "unit_price": "390"}], "1170")
        SalesOrderItem.objects.filter(so_id=so["id"]).update(cost_at_post=D("100.00"))
        line = SalesOrderItem.objects.get(so_id=so["id"])
        self.give_back(so, line.id, 1)
        self.give_back(so, line.id, 1)
        last = self.give_back(so, line.id, 1)
        r = self.c.admin.post(f"/api/v1/sales-returns/{last['id']}/void/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        backfill(django_apps, None)
        self.assertEqual(SalesReturnItem.objects.get(sr_id=last["id"]).cost_at_post, D("33.33"))


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
            "items": [{"original_item": line.id, "qty": 1}],
        }, format="json")
        self.assertEqual(r.status_code, 403, r.content)
