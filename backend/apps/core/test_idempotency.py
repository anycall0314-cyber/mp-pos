"""同一份建單請求只成立一次(apps/core/idempotency.py)。

工作台版型按「確認」之後連線斷掉,畫面會拿同一把鑰匙再送一次:不能因此開出兩張單、收兩次錢。
"""
import threading
from decimal import Decimal

from django.db import connection
from django.test import TestCase, TransactionTestCase

from apps.backup.tests.factory import Company
from apps.core.models import IdempotencyKey
from apps.purchasing.models import PurchaseOrder
from apps.sales.models import SalesOrder

KEY = "0f8fad5b-d9cb-469f-a165-70867728950e"


def buy_body(c, unit_price="100", qty=2):
    return {
        "supplier": c.supplier.id, "warehouse": c.wh.id, "tax_method": "untaxed",
        "items": [{"product": c.case.id, "qty": qty, "unit_price": unit_price}],
    }


def sell_body(c):
    return {
        "customer": c.customer.id, "warehouse": c.wh.id, "tax_method": "untaxed",
        "items": [{"product": c.case.id, "qty": 1, "unit_price": "390"}],
        "payments": [{"method": "cash", "amount": "390"}],
    }


class IdempotencyTests(TestCase):
    def setUp(self):
        self.c = Company("a", "甲通訊行", "甲")

    def post(self, url, body, key=None, client=None):
        headers = {"HTTP_IDEMPOTENCY_KEY": key} if key else {}
        return (client or self.c.admin).post(url, body, format="json", **headers)

    def test_same_key_makes_one_purchase(self):
        first = self.post("/api/v1/purchase-orders/", buy_body(self.c), KEY)
        again = self.post("/api/v1/purchase-orders/", buy_body(self.c), KEY)
        self.assertEqual(first.status_code, 201, first.content)
        self.assertEqual(again.status_code, 200, again.content)
        self.assertEqual(again["Idempotent-Replay"], "true")
        self.assertEqual(again.json()["id"], first.json()["id"])
        self.assertEqual(again.json()["no"], first.json()["no"])
        self.assertEqual(PurchaseOrder.objects.filter(tenant=self.c.tenant).count(), 1)
        # 庫存只進一次
        from apps.inventory.models import StockBalance
        bal = StockBalance.objects.get(tenant=self.c.tenant, product=self.c.case, warehouse=self.c.wh)
        self.assertEqual(bal.qty, 2)

    def test_same_key_makes_one_sale_and_one_payment(self):
        self.c.purchase(case_qty=3)
        first = self.post("/api/v1/sales-orders/", sell_body(self.c), KEY)
        again = self.post("/api/v1/sales-orders/", sell_body(self.c), KEY)
        self.assertEqual(first.status_code, 201, first.content)
        self.assertEqual(again.status_code, 200, again.content)
        self.assertEqual(again.json()["no"], first.json()["no"])
        self.assertEqual(SalesOrder.objects.filter(tenant=self.c.tenant).count(), 1)
        from apps.sales.models import SalesOrderPayment
        self.assertEqual(SalesOrderPayment.objects.filter(so__tenant=self.c.tenant).count(), 1)
        from apps.inventory.models import StockBalance
        bal = StockBalance.objects.get(tenant=self.c.tenant, product=self.c.case, warehouse=self.c.wh)
        self.assertEqual(bal.qty, 2)  # 進 3、只賣出 1

    def test_without_a_key_nothing_changes(self):
        for _ in range(2):
            r = self.post("/api/v1/purchase-orders/", buy_body(self.c))
            self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(PurchaseOrder.objects.filter(tenant=self.c.tenant).count(), 2)
        self.assertEqual(IdempotencyKey.objects.count(), 0)

    def test_a_refused_request_does_not_use_up_the_key(self):
        # 第一次資料不對被擋(沒有庫存):單沒成立,鑰匙也沒留下;補貨後拿同一把再送是一次新的建單
        bad = self.post("/api/v1/sales-orders/", sell_body(self.c), KEY)
        self.assertEqual(bad.status_code, 400, bad.content)
        self.assertEqual(IdempotencyKey.objects.count(), 0)
        self.c.purchase(case_qty=1)
        good = self.post("/api/v1/sales-orders/", sell_body(self.c), KEY)
        self.assertEqual(good.status_code, 201, good.content)
        self.assertEqual(SalesOrder.objects.filter(tenant=self.c.tenant).count(), 1)

    def test_different_keys_are_different_documents(self):
        a = self.post("/api/v1/purchase-orders/", buy_body(self.c), KEY)
        b = self.post("/api/v1/purchase-orders/", buy_body(self.c), KEY[:-1] + "f")
        self.assertEqual((a.status_code, b.status_code), (201, 201))
        self.assertNotEqual(a.json()["id"], b.json()["id"])

    def test_the_same_key_in_another_company_is_unrelated(self):
        other = Company("b", "乙通訊行", "乙")
        a = self.post("/api/v1/purchase-orders/", buy_body(self.c), KEY)
        b = self.post("/api/v1/purchase-orders/", buy_body(other), KEY, client=other.admin)
        self.assertEqual((a.status_code, b.status_code), (201, 201))
        self.assertEqual(PurchaseOrder.objects.filter(tenant=other.tenant).count(), 1)

    def test_purchase_and_sale_keys_do_not_collide(self):
        self.c.purchase(case_qty=3)
        a = self.post("/api/v1/purchase-orders/", buy_body(self.c), KEY)
        b = self.post("/api/v1/sales-orders/", sell_body(self.c), KEY)
        self.assertEqual((a.status_code, b.status_code), (201, 201))

    def test_bad_key_is_refused(self):
        r = self.post("/api/v1/purchase-orders/", buy_body(self.c), "短")
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(PurchaseOrder.objects.filter(tenant=self.c.tenant).count(), 0)

    def test_replay_still_finds_the_document_after_ids_change(self):
        # 還原備份之後資料庫編號會換、單號不會:鑰匙記的是單號
        first = self.post("/api/v1/purchase-orders/", buy_body(self.c), KEY)
        record = IdempotencyKey.objects.get()
        self.assertEqual(record.doc_no, first.json()["no"])
        self.assertEqual(record.scope, "purchase-order")

    def test_old_keys_are_cleared(self):
        from datetime import timedelta

        from django.utils import timezone

        self.post("/api/v1/purchase-orders/", buy_body(self.c), KEY)
        IdempotencyKey.objects.update(created_at=timezone.now() - timedelta(days=30))
        self.post("/api/v1/purchase-orders/", buy_body(self.c), KEY[:-1] + "f")
        self.assertEqual(IdempotencyKey.objects.count(), 1)


class RaceTests(TransactionTestCase):
    def test_two_requests_at_once_with_one_key_make_one_sale(self):
        c = Company("a", "甲通訊行", "甲")
        c.purchase(case_qty=5)
        results = []
        gate = threading.Barrier(2)

        def go():
            try:
                gate.wait(timeout=10)
                r = Company.client(c.admin_user).post(
                    "/api/v1/sales-orders/", sell_body(c), format="json",
                    HTTP_IDEMPOTENCY_KEY=KEY,
                )
                results.append((r.status_code, r.json().get("no")))
            finally:
                connection.close()

        threads = [threading.Thread(target=go) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        self.assertEqual(sorted(code for code, _ in results), [200, 201], results)
        self.assertEqual(len({no for _, no in results}), 1, results)
        self.assertEqual(SalesOrder.objects.filter(tenant=c.tenant).count(), 1)
