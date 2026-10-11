from datetime import date, timedelta
from decimal import Decimal as D

from apps.cash.views import _compute_cash_balance_before
from apps.purchasing.models import PurchaseOrder
from apps.tenants.models import PaymentMethod

from .test_manual import _Manual, C01
from .test_receiving import _Arrival
from .models import VendorReceipt
from .tests import ORDERS


class AccountingRegressions(_Manual):
    def setUp(self):
        super().setUp()
        self.assertEqual(self.open().status_code, 200)
        self.order = self.buy(payment_method="貨到付款").json()

    def receive(self, qty=20, price="45", freight=0, key="receive-accounting-1", was=None):
        response = self.clerk.post(f"{ORDERS}{self.order['id']}/receive/", {
            "request_key": key, "freight": freight,
            "lines": [{"key": C01, "qty": qty, "product": self.cable.id,
                       "unit_price": price, "was": was}],
        }, format="json")
        return response

    def cash_out(self):
        codes = list(PaymentMethod.objects.filter(tenant=self.t, kind="cash").values_list("code", flat=True))
        return -_compute_cash_balance_before(self.t, self.wh1.id, date.today() + timedelta(days=1), codes)

    def test_freight_outside_inventory_cost_is_still_paid(self):
        self.assertEqual(self.open(freight_into_cost=False).status_code, 200)
        self.assertEqual(self.receive(freight=80).status_code, 201)
        self.assertEqual(self.cash_out(), 980)

    def test_void_removes_the_batch_value_as_well_as_quantity(self):
        self.assertEqual(self.receive(qty=10, price="10").status_code, 201)
        self.assertEqual(self.receive(qty=10, price="30", key="receive-accounting-2", was=self.cable.id).status_code, 201)
        po = PurchaseOrder.objects.filter(tenant=self.t).latest("id")
        self.assertEqual(self.admin.post(f"/api/v1/purchase-orders/{po.id}/void/").status_code, 200)
        self.assertEqual(self.stock(self.cable), (10, D("10.00")))
        self.cable.refresh_from_db()
        self.assertEqual(self.cable.weighted_avg_cost, D("10.00"))

    def test_daily_report_and_next_opening_both_include_paid_freight(self):
        self.open(freight_into_cost=False)
        self.assertEqual(self.receive(freight=80).status_code, 201)
        response = self.admin.get("/api/v1/reports/business-daily/", {"warehouse": self.wh1.id, "date": date.today().isoformat()})
        self.assertEqual(response.status_code, 200, response.content.decode())
        self.assertEqual(response.json()["purchases"]["total"], 980)
        self.assertEqual(self.cash_out(), 980)
        po = PurchaseOrder.objects.get(tenant=self.t)
        self.assertEqual((po.total_cost, po.cash_paid), (900, 980))

    def test_invalid_or_missing_freight_rolls_back_and_can_retry(self):
        for fee in (None, "", True, -1, 1.5, "80", 10_000_000):
            response = self.receive(freight=fee)
            self.assertEqual(response.status_code, 400, (fee, response.content.decode()))
            self.assertEqual(PurchaseOrder.objects.filter(tenant=self.t).count(), 0)
            self.assertEqual(VendorReceipt.objects.filter(tenant=self.t).count(), 0)
            self.assertEqual(self.stock(self.cable)[0], 0)
        self.assertEqual(self.receive(freight=0).status_code, 201)

    def test_each_delivery_uses_its_own_paid_freight(self):
        self.open(freight_into_cost=False)
        self.assertEqual(self.receive(qty=10, freight=80).status_code, 201)
        self.assertEqual(self.receive(qty=10, freight=0, key="receive-accounting-2", was=self.cable.id).status_code, 201)
        self.assertEqual(self.cash_out(), 980)
        self.assertEqual(list(VendorReceipt.objects.filter(tenant=self.t).order_by("id").values_list("shipping_paid", flat=True)), [80, 0])

    def test_zero_price_goods_can_still_have_paid_freight(self):
        self.assertEqual(self.receive(price="0", freight=80).status_code, 201)
        self.assertEqual(self.cash_out(), 80)
        self.assertEqual(self.stock(self.cable)[0], 20)

    def test_sold_purchase_cannot_be_voided_even_after_stock_is_replenished(self):
        self.assertEqual(self.receive().status_code, 201)
        po = PurchaseOrder.objects.get(tenant=self.t)
        self.c.case = self.cable
        self.c.sell(case_qty=1)
        self.assertEqual(self.receive(qty=1, key="receive-accounting-2", was=self.cable.id).status_code, 201)
        before = self.stock(self.cable)
        response = self.admin.post(f"/api/v1/purchase-orders/{po.id}/void/")
        self.assertEqual(response.status_code, 400, response.content.decode())
        self.assertIn("逐筆", response.json()["detail"])
        po.refresh_from_db()
        self.assertFalse(po.is_void)
        self.assertEqual(self.stock(self.cable), before)

    def test_void_aggregates_duplicate_rows_and_recomputes_company_cost(self):
        self.assertEqual(self.receive(qty=10, price="10").status_code, 201)
        def buy(warehouse, items):
            response = self.admin.post("/api/v1/purchase-orders/", {
                "supplier": self.c.supplier.id, "warehouse": warehouse.id,
                "tax_method": "untaxed", "items": items,
            }, format="json")
            self.assertEqual(response.status_code, 201, response.content.decode())
            return response.json()
        def row(qty, price):
            return {"product": self.cable.id, "qty": qty, "unit_price": price}
        second = buy(self.wh1, [row(5, "30"), row(5, "30")])
        buy(self.wh2, [row(10, "50")])
        self.assertEqual(self.admin.post(f"/api/v1/purchase-orders/{second['id']}/void/").status_code, 200)
        self.assertEqual(self.stock(self.cable), (10, D("10.00")))
        self.cable.refresh_from_db()
        self.assertEqual(self.cable.weighted_avg_cost, D("30.00"))

    def test_sold_serial_cannot_be_voided_after_sale_is_reversed(self):
        purchase = self.c.purchase(phone_serials=["ACCOUNTING-IMEI001"])
        sale = self.c.sell(serial_no="ACCOUNTING-IMEI001")
        self.assertEqual(self.admin.post(f"/api/v1/sales-orders/{sale['id']}/void/").status_code, 200)
        response = self.admin.post(f"/api/v1/purchase-orders/{purchase['id']}/void/")
        self.assertEqual(response.status_code, 400, response.content.decode())
        self.assertFalse(PurchaseOrder.objects.get(id=purchase['id']).is_void)

    def test_cash_on_delivery_requires_an_active_cash_method(self):
        PaymentMethod.objects.filter(tenant=self.t, kind="cash").update(is_active=False)
        response = self.receive()
        self.assertEqual(response.status_code, 400, response.content.decode())
        self.assertEqual(PurchaseOrder.objects.filter(tenant=self.t).count(), 0)
        self.assertEqual(VendorReceipt.objects.filter(tenant=self.t).count(), 0)
        self.assertEqual(self.stock(self.cable)[0], 0)
        self.c.cash.is_active = True
        self.c.cash.save(update_fields=["is_active"])
        self.assertEqual(self.receive().status_code, 201)
        self.assertEqual(self.cash_out(), 900)
        self.assertEqual(self.receive().status_code, 200)
        self.assertEqual(self.cash_out(), 900)

    def test_cash_payment_does_not_come_from_rounded_unit_cost(self):
        self.assertEqual(self.receive(qty=300, price="10", freight=100).status_code, 201)
        self.assertEqual(self.cash_out(), 3100)


class AutomaticCashMethodRegression(_Arrival):
    def test_no_cash_method_blocks_the_whole_receipt_and_same_key_can_retry(self):
        self.vendor.find(self.no)["payment_method"] = "貨到付款"
        PaymentMethod.objects.filter(tenant=self.t, kind="cash").update(is_active=False)
        response = self.take([self.line()], freight=0)
        self.assertEqual(response.status_code, 400, response.content.decode())
        self.assertNothingReceived()
        self.c.cash.is_active = True
        self.c.cash.save(update_fields=["is_active"])
        self.assertEqual(self.take([self.line()], freight=0).status_code, 201)
        self.assertEqual(self.take([self.line()], freight=0).status_code, 200)
        self.assertEqual(PurchaseOrder.objects.filter(tenant=self.t).count(), 1)

    def test_full_automatic_receipt_uses_original_subtotal_for_cash(self):
        self.vendor.find(self.no)["payment_method"] = "貨到付款"
        self.vendor.find(self.no)["items"][0].update(qty=300, shipped_qty=300, subtotal=10000)
        self.assertEqual(self.take([self.line(qty=300)], freight=100).status_code, 201)
        po = PurchaseOrder.objects.get(tenant=self.t)
        self.assertEqual(po.cash_paid, 10100)
        self.assertEqual(po.total_cost, 10098)

    def test_automatic_partial_receipts_do_not_spread_actual_paid_freight(self):
        self.vendor.find(self.no)["payment_method"] = "貨到付款"
        self.assertEqual(self.take([self.line(qty=20)], freight=80).status_code, 201)
        self.assertEqual(self.take([self.line(qty=30)], key="recv-0002", freight=0).status_code, 201)
        self.assertEqual(sum(PurchaseOrder.objects.filter(tenant=self.t).values_list("cash_paid", flat=True)), 7580)
        self.assertEqual(list(VendorReceipt.objects.filter(tenant=self.t).order_by("id").values_list("shipping_paid", flat=True)), [80, 0])
