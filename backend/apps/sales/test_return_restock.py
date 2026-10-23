"""銷退的手機先標「已退」(不能賣),確認可賣才回在庫(owner 2026-10-23「先標不能賣，確認可賣再點回倉」)。"""
from django.test import TestCase

from apps.backup.tests.factory import Company
from apps.inventory.models import ProductSerial, StockMovement
from apps.ledger.checks import check_serials

RETURNS = "/api/v1/sales-returns/"


class ReturnedThenReleasedTests(TestCase):
    def setUp(self):
        self.c = Company("a", "甲通訊行", "甲")
        self.w2 = self.c.warehouses[1]
        self.c.purchase(warehouse=self.w2, phone_serials=["甲R1"])
        self.phone = ProductSerial.objects.get(tenant=self.c.tenant, serial_no="甲R1")

    def back(self, so):
        return self.c._post(RETURNS, {"original_so": so["id"], "payment_method": "cash"})

    def void(self, sr):
        return self.c.admin.post(f"{RETURNS}{sr['id']}/void/", {}, format="json")

    def release(self, client=None):
        return (client or self.c.admin).post(f"/api/v1/serials/{self.phone.pk}/release/", {}, format="json")

    def state(self):
        self.phone.refresh_from_db()
        return self.phone.status, self.phone.warehouse_id

    def books_agree(self):
        for result in check_serials(self.c.tenant):
            self.assertTrue(result["ok"], result)

    def test_a_returned_phone_waits_as_returned_and_cannot_be_sold(self):
        self.back(self.c.sell(warehouse=self.w2, serial_no="甲R1"))
        self.assertEqual(self.state(), ("returned", self.w2.id))
        self.assertIsNone(self.phone.sold_at)
        r = self.c.admin.post("/api/v1/sales-orders/", {
            "customer": self.c.customer.id, "warehouse": self.w2.id, "tax_method": "untaxed",
            "items": [{"product": self.c.phone.id, "qty": 1, "unit_price": "25000", "serial_ids": [self.phone.id]}],
            "payments": [{"method": "cash", "amount": "25000"}],
        }, format="json")
        self.assertEqual(r.status_code, 400, r.content.decode())
        self.books_agree()

    def test_confirming_puts_it_back_in_stock_and_leaves_a_record(self):
        sr = self.back(self.c.sell(warehouse=self.w2, serial_no="甲R1"))
        r = self.release()
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.assertEqual(self.state(), ("in_stock", self.w2.id))
        mv = StockMovement.objects.get(serial=self.phone, movement_type="return_release")
        self.assertEqual((mv.ref_doc_type, mv.ref_doc_id, mv.from_warehouse_id, mv.to_warehouse_id),
                         ("sales_return", sr["id"], None, None))          # 只是紀錄,不動數量
        self.assertIn(sr["no"], mv.note)
        self.assertEqual(self.release().status_code, 400)                 # 已經在庫了
        self.c.sell(warehouse=self.w2, serial_no="甲R1")                   # 可以再賣
        self.assertEqual(self.state(), ("sold", None))
        self.books_agree()

    def test_who_may_confirm(self):
        self.back(self.c.sell(warehouse=self.w2, serial_no="甲R1"))
        # 店員鎖在第一家門市:這一台在第二家,按不了
        self.assertEqual(self.release(self.c.clerk).status_code, 403)
        self.assertEqual(self.state(), ("returned", self.w2.id))
        # 員工帳號關掉「確認可賣」也按不了
        profile = self.c.clerk_user.profile
        profile.default_warehouse = self.w2
        profile.denied_abilities = ["release_returned"]
        profile.save()
        self.assertEqual(self.release(self.c.clerk).status_code, 403)
        profile.denied_abilities = []
        profile.save()
        self.assertEqual(self.release(self.c.clerk).status_code, 200)
        self.assertEqual(self.state(), ("in_stock", self.w2.id))

    def test_voiding_a_return_nobody_touched_puts_it_back_to_sold(self):
        sr = self.back(self.c.sell(warehouse=self.w2, serial_no="甲R1"))
        r = self.void(sr)
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.assertEqual(self.state(), ("sold", None))
        self.books_agree()

    def test_a_return_cannot_be_voided_once_the_phone_was_confirmed(self):
        sr = self.back(self.c.sell(warehouse=self.w2, serial_no="甲R1"))
        self.release()
        r = self.void(sr)
        self.assertEqual(r.status_code, 400, r.content.decode())
        self.assertIn("甲R1", r.json()["detail"])
        self.assertEqual(self.state(), ("in_stock", self.w2.id))

    def test_a_return_cannot_be_voided_once_the_phone_was_sold_and_returned_again(self):
        first = self.back(self.c.sell(warehouse=self.w2, serial_no="甲R1"))
        self.release()
        self.back(self.c.sell(warehouse=self.w2, serial_no="甲R1"))
        self.assertEqual(self.state(), ("returned", self.w2.id))      # 看狀態跟沒動過一樣
        self.assertEqual(self.void(first).status_code, 400)
        self.books_agree()

    def test_a_return_cannot_be_voided_when_the_phone_is_recorded_at_another_store(self):
        sr = self.back(self.c.sell(warehouse=self.w2, serial_no="甲R1"))
        ProductSerial.objects.filter(pk=self.phone.pk).update(warehouse=self.c.wh)
        self.assertEqual(self.void(sr).status_code, 400)
        self.assertEqual(self.state(), ("returned", self.c.wh.id))

    def test_the_home_page_counts_returned_phones_waiting(self):
        self.back(self.c.sell(warehouse=self.w2, serial_no="甲R1"))
        r = self.c.admin.get("/api/v1/home-summary/")
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.assertEqual(r.json()["returns_pending"], 1)
        self.release()
        self.assertEqual(self.c.admin.get("/api/v1/home-summary/").json()["returns_pending"], 0)

    def test_a_returned_phone_stays_in_the_average_cost(self):
        # 複審 P0:已退的不算進平均成本的話,退回來之後再進一批,平均會被新的那一批拉走
        self.back(self.c.sell(warehouse=self.w2, serial_no="甲R1"))          # 甲R1 成本 20000,已退
        self.c._post("/api/v1/purchase-orders/", {
            "supplier": self.c.supplier.id, "warehouse": self.w2.id, "tax_method": "untaxed",
            "items": [{"product": self.c.phone.id, "qty": 1, "unit_price": "30000", "serial_numbers": ["甲R2"]}],
        })
        self.c.phone.refresh_from_db()
        self.assertEqual(int(self.c.phone.weighted_avg_cost), 25000)

    def test_cancelling_a_vendor_exchange_of_a_returned_phone_puts_it_back_as_returned(self):
        # 複審 P1:送換貨再按「標錯了」不能變成可以賣(繞過「確認可賣」)
        self.back(self.c.sell(warehouse=self.w2, serial_no="甲R1"))
        sent = self.c._post("/api/v1/vendor-exchanges/", {"code": "甲R1", "supplier": self.c.supplier.id})
        self.assertEqual(self.state()[0], "rma")
        self.c._post(f"/api/v1/vendor-exchanges/{sent['id']}/cancel/", {})
        self.assertEqual(self.state(), ("returned", self.w2.id))
