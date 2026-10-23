"""銷退的手機直接回原門市在庫(全站檢視 A6;owner 2026-10-23「銷退過後，庫存自動轉回原倉」)。"""
from django.test import TestCase

from apps.backup.tests.factory import Company
from apps.inventory.models import ProductSerial
from apps.ledger.checks import check_serials

RETURNS = "/api/v1/sales-returns/"


class ReturnRestockTests(TestCase):
    def setUp(self):
        self.c = Company("a", "甲通訊行", "甲")
        self.w2 = self.c.warehouses[1]
        self.c.purchase(warehouse=self.w2, phone_serials=["甲R1"])
        self.phone = ProductSerial.objects.get(tenant=self.c.tenant, serial_no="甲R1")

    def back(self, so):
        return self.c._post(RETURNS, {"original_so": so["id"], "payment_method": "cash"})

    def void(self, sr):
        return self.c.admin.post(f"{RETURNS}{sr['id']}/void/", {}, format="json")

    def state(self):
        self.phone.refresh_from_db()
        return self.phone.status, self.phone.warehouse_id

    def books_agree(self):
        for result in check_serials(self.c.tenant):
            self.assertTrue(result["ok"], result)

    def test_a_returned_phone_is_back_in_stock_at_the_store_that_sold_it(self):
        so = self.c.sell(warehouse=self.w2, serial_no="甲R1")
        self.back(so)
        self.assertEqual(self.state(), ("in_stock", self.w2.id))
        self.assertIsNone(self.phone.sold_at)
        self.books_agree()
        # 可以直接再賣
        self.c.sell(warehouse=self.w2, serial_no="甲R1")
        self.assertEqual(self.state(), ("sold", None))
        self.books_agree()

    def test_voiding_a_return_nobody_touched_puts_it_back_to_sold(self):
        sr = self.back(self.c.sell(warehouse=self.w2, serial_no="甲R1"))
        r = self.void(sr)
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.assertEqual(self.state(), ("sold", None))
        self.books_agree()

    def test_a_return_cannot_be_voided_once_the_phone_was_sold_and_returned_again(self):
        first = self.back(self.c.sell(warehouse=self.w2, serial_no="甲R1"))
        self.back(self.c.sell(warehouse=self.w2, serial_no="甲R1"))
        self.assertEqual(self.state(), ("in_stock", self.w2.id))     # 看狀態跟沒動過一樣
        r = self.void(first)
        self.assertEqual(r.status_code, 400, r.content.decode())
        self.assertIn("甲R1", r.json()["detail"])
        self.assertEqual(self.state(), ("in_stock", self.w2.id))
        self.books_agree()

    def test_a_return_cannot_be_voided_once_the_phone_left_the_store(self):
        sr = self.back(self.c.sell(warehouse=self.w2, serial_no="甲R1"))
        self.c._post("/api/v1/transfer-orders/", {
            "from_warehouse": self.w2.id, "to_warehouse": self.c.wh.id,
            "items": [{"product": self.c.phone.id, "qty": 1, "serial_ids": [self.phone.id]}],
        })
        before = self.state()
        r = self.void(sr)
        self.assertEqual(r.status_code, 400, r.content.decode())
        self.assertEqual(self.state(), before)

    def test_an_older_return_still_sitting_as_returned_can_still_be_voided(self):
        sr = self.back(self.c.sell(warehouse=self.w2, serial_no="甲R1"))
        ProductSerial.objects.filter(pk=self.phone.pk).update(status="returned")   # 這一版之前的銷退
        r = self.void(sr)
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.assertEqual(self.state(), ("sold", None))
        self.books_agree()

    def test_a_return_cannot_be_voided_when_the_phone_is_recorded_at_another_store(self):
        # 帳上寫在別家門市(沒有異動紀錄的那種舊資料):照樣不能打回已售
        sr = self.back(self.c.sell(warehouse=self.w2, serial_no="甲R1"))
        ProductSerial.objects.filter(pk=self.phone.pk).update(warehouse=self.c.wh)
        r = self.void(sr)
        self.assertEqual(r.status_code, 400, r.content.decode())
        self.assertEqual(self.state(), ("in_stock", self.c.wh.id))
