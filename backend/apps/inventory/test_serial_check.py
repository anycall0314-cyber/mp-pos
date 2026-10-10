"""輸入序號的當下問一次「這些碼是不是已經在系統裡」(`POST /serials/check/`)。只讀;存檔時伺服器照舊自己再擋。

要守住的:**它說「已經有了」的,跟存檔時會被擋的是同一批**(不多不少);講得出是哪個商品、在哪家門市、什麼狀態;
只看自己公司;不會改任何資料。
"""
from django.test import TestCase
from rest_framework.test import APIClient

from apps.backup.tests.factory import Company

from .identifiers import IN_STORE, taken, taken_details
from .models import ProductSerial, ProductSerialIdentifier

CHECK = "/api/v1/serials/check/"
IMEI_A = "490154203237518"
IMEI_B = "356938035643809"
IMEI_C = "352099001761481"
SN_A = "F2LXK1ABCD"
SN_B = "G6TZN0QWER"


class SerialCheckTests(TestCase):
    def setUp(self):
        self.c = Company("a", "甲通訊行", "甲")
        self.t = self.c.tenant
        self.wh1, self.wh2 = self.c.warehouses

    def buy(self, entries, warehouse=None):
        r = self.c.admin.post("/api/v1/purchase-orders/", {
            "supplier": self.c.supplier.id, "warehouse": (warehouse or self.wh1).id, "tax_method": "untaxed",
            "items": [{"product": self.c.phone.id, "qty": len(entries), "unit_price": "20000", "serial_numbers": entries}],
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content.decode())
        return r.json()

    def check(self, codes, client=None):
        return (client or self.c.clerk).post(CHECK, {"codes": codes}, format="json")

    def taken_codes(self, codes, client=None):
        r = self.check(codes, client)
        self.assertEqual(r.status_code, 200, r.content.decode())
        return {row["code"]: row for row in r.json()["taken"]}

    def test_it_says_which_product_which_store_and_what_state(self):
        self.buy([{"imei": IMEI_A, "sn": SN_A}])
        self.buy([{"imei": IMEI_B}], warehouse=self.wh2)
        got = self.taken_codes([IMEI_A, IMEI_B, IMEI_C, SN_A, "沒有這個碼"])
        self.assertEqual(set(got), {IMEI_A, IMEI_B, SN_A})                 # 兩個碼(IMEI、SN)都認得是那一台
        self.assertEqual(got[IMEI_A], {
            "code": IMEI_A, "product_name": self.c.phone.name, "product_sku": self.c.phone.sku,
            "warehouse_name": "甲湳雅店", "status": "in_stock", "status_label": "在庫", "in_store": True})
        self.assertEqual((got[SN_A]["warehouse_name"], got[IMEI_B]["warehouse_name"]), ("甲湳雅店", "甲民生店"))
        # 不回成本、不回編號以外的東西
        self.assertEqual(set(got[IMEI_A]), {"code", "product_name", "product_sku", "warehouse_name", "status", "status_label", "in_store"})

    def test_the_way_it_is_written_does_not_matter(self):
        self.buy([{"sn": "AB-12-CD34"}])
        for written in ("AB12CD34", "ab-12-cd34", " AB 12 CD34 ", "ab.12_cd-34"):          # 空白、破折號、底線、點不算
            self.assertEqual(list(self.taken_codes([written])), [written.strip()], written)   # 回的是送進來的那個寫法(去掉前後空白)
        self.assertEqual(self.taken_codes(["AB12CD3", "AB12CD345", "B12CD34", "AB12/CD34"]), {})   # 只認完全相同,不是「包含」;斜線是另一個碼
        # 同一個碼送兩種寫法:算一個
        self.assertEqual(len(self.taken_codes(["AB12CD34", "ab-12-cd34"])), 1)

    def test_sold_units_still_hold_their_code_and_are_told_apart_from_units_in_the_store(self):
        self.buy([IMEI_A, IMEI_B, IMEI_C])
        self.c.sell(serial_no=IMEI_A)
        ProductSerial.objects.filter(tenant=self.t, serial_no=IMEI_B).update(status="in_transit", warehouse=None)
        got = self.taken_codes([IMEI_A, IMEI_B, IMEI_C])
        self.assertEqual({code: (row["status"], row["in_store"], row["warehouse_name"]) for code, row in got.items()},
                         {IMEI_A: ("sold", False, ""), IMEI_B: ("in_transit", True, ""), IMEI_C: ("in_stock", True, "甲湳雅店")})
        self.assertEqual(set(IN_STORE), {"in_stock", "in_transit", "rma"})

    def test_a_voided_purchase_frees_its_codes(self):
        po = self.buy([{"imei": IMEI_A, "sn": SN_A}])
        self.assertEqual(set(self.taken_codes([IMEI_A, SN_A])), {IMEI_A, SN_A})
        self.assertEqual(self.c.admin.post(f"/api/v1/purchase-orders/{po['id']}/void/").status_code, 200)
        self.assertEqual(self.taken_codes([IMEI_A, SN_A]), {})
        self.buy([{"imei": IMEI_A, "sn": SN_A}])                 # 作廢之後可以再進(畫面不會說它已經有了)

    def test_it_agrees_exactly_with_what_saving_would_refuse(self):
        """畫面提醒的,跟存檔時伺服器擋的,必須是同一批。"""
        self.buy([{"imei": IMEI_A, "sn": SN_A}, {"sn": "AB-12-CD34"}])
        self.buy([IMEI_B])
        self.c.sell(serial_no=IMEI_B)
        # 舊資料:識別碼表沒登記到、只有主碼的一台
        ProductSerial.objects.create(tenant=self.t, product=self.c.phone, serial_no="OLD-77", warehouse=self.wh1)
        voided = self.buy([IMEI_C])
        self.c.admin.post(f"/api/v1/purchase-orders/{voided['id']}/void/")
        asked = [IMEI_A, SN_A, "ab12cd34", IMEI_B, IMEI_C, "old77", "OLD-77", SN_B, "", "   ", "NEW-1"]
        refused = set(taken(self.t, asked))
        self.assertEqual(set(taken_details(self.t, asked)), refused)
        self.assertEqual(set(self.taken_codes(asked)), refused)
        self.assertEqual(refused, {IMEI_A, SN_A, "ab12cd34", IMEI_B, "old77"})

    def test_only_this_company(self):
        other = Company("b", "乙通訊行", "乙")
        self.buy([IMEI_A])
        self.assertEqual(self.taken_codes([IMEI_A], client=other.admin), {})
        self.assertEqual(set(self.taken_codes([IMEI_A])), {IMEI_A})

    def test_a_clerk_locked_to_one_store_still_hears_about_units_in_another_store(self):
        """鎖在自己門市的店員:別家門市已經有的碼一樣要講(不然他這邊就照進了,存檔才被擋)。"""
        self.buy([IMEI_A], warehouse=self.wh2)
        got = self.taken_codes([IMEI_A], client=self.c.clerk)
        self.assertEqual((got[IMEI_A]["warehouse_name"], got[IMEI_A]["in_store"]), ("甲民生店", True))

    def test_it_never_changes_anything_and_needs_a_login(self):
        self.buy([{"imei": IMEI_A, "sn": SN_A}])
        before = (ProductSerial.objects.count(), ProductSerialIdentifier.objects.count(),
                  list(ProductSerial.objects.values_list("status", "updated_at")))
        self.check([IMEI_A, SN_A, IMEI_B])
        self.assertEqual(before, (ProductSerial.objects.count(), ProductSerialIdentifier.objects.count(),
                                  list(ProductSerial.objects.values_list("status", "updated_at"))))
        self.assertIn(APIClient().post(CHECK, {"codes": [IMEI_A]}, format="json").status_code, (401, 403))

    def test_what_is_sent_has_to_be_a_short_list_of_codes(self):
        self.assertEqual(self.check([]).json(), {"taken": []})
        self.assertEqual(self.check(["x"] * 500).status_code, 200)
        for bad in (["x"] * 501, "490154203237518", None, {"a": 1}, [5], [None], [["x"]], ["x" * 81]):
            self.assertEqual(self.check(bad).status_code, 400, str(bad)[:40])
        self.assertEqual(self.c.clerk.post(CHECK, ["x"], format="json").status_code, 400)
        self.assertEqual(self.c.clerk.get(CHECK).status_code, 405)

    def test_the_unit_lookup_also_says_which_store(self):
        self.buy([IMEI_A], warehouse=self.wh2)
        row = self.c.clerk.get(f"/api/v1/serials/?code={IMEI_A}").json()["results"][0]
        self.assertEqual((row["warehouse_name"], row["status_label"]), ("甲民生店", "在庫"))
        self.c.sell(warehouse=self.wh2, serial_no=IMEI_A)
        row = self.c.clerk.get(f"/api/v1/serials/?code={IMEI_A}").json()["results"][0]
        self.assertEqual((row["warehouse_name"], row["status_label"]), ("", "已售"))
