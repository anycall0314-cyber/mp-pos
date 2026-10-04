"""整張調撥:一張進貨單的東西,現在還有哪些留在進貨門市、可以一次調到分店。"""
from django.test import TestCase

from apps.backup.tests.factory import Company
from apps.catalog.models import Product
from apps.inventory.models import ProductSerial, StockBalance, StockMovement
from apps.transfers.models import TransferOrder

IMEI_A = "490154203237518"
IMEI_B = "356938035643809"
SN_A = "F2LXK1ABCD"


class WholeOrderTransferTests(TestCase):
    def setUp(self):
        self.c = Company("a", "甲通訊行", "甲")
        self.hq, self.branch = self.c.warehouses
        self.po = self.c._post("/api/v1/purchase-orders/", {
            "supplier": self.c.supplier.id, "warehouse": self.hq.id, "tax_method": "untaxed",
            "items": [
                {"product": self.c.phone.id, "qty": 2, "unit_price": "20000",
                 "serial_numbers": [{"imei": IMEI_A, "sn": SN_A}, {"imei": IMEI_B, "sn": ""}]},
                {"product": self.c.case.id, "qty": 4, "unit_price": "100"},
                {"product": self.c.case.id, "qty": 6, "unit_price": "100"},
            ],
        })

    def transferable(self, client=None, po=None):
        return (client or self.c.admin).get(
            f"/api/v1/purchase-orders/{(po or self.po)['id']}/transferable/")

    def lines(self):
        r = self.transferable()
        self.assertEqual(r.status_code, 200, r.content.decode())
        return {l["product"]: l for l in r.json()["lines"]}

    def test_everything_still_at_the_receiving_store(self):
        body = self.transferable().json()
        self.assertEqual((body["no"], body["warehouse"], body["warehouse_name"]),
                         (self.po["no"], self.hq.id, "甲湳雅店"))
        lines = {l["product"]: l for l in body["lines"]}
        self.assertEqual(len(body["lines"]), 2)              # 同一個商品的兩行併成一行
        phone, case = lines[self.c.phone.id], lines[self.c.case.id]
        self.assertEqual((phone["requires_serial"], phone["purchased"], phone["qty"], phone["gone"]),
                         (True, 2, 2, []))
        self.assertEqual([(s["serial_no"], s["imei"], s["sn"]) for s in phone["serials"]],
                         [(IMEI_A, IMEI_A, SN_A), (IMEI_B, IMEI_B, "")])
        self.assertEqual((case["requires_serial"], case["purchased"], case["qty"], case["serials"]),
                         (False, 10, 10, []))

    def test_whole_order_goes_to_the_branch_in_one_transfer(self):
        before = (ProductSerial.objects.count(), StockMovement.objects.count(), TransferOrder.objects.count())
        lines = self.lines()
        self.assertEqual(                                    # 只是查,不改任何資料
            (ProductSerial.objects.count(), StockMovement.objects.count(), TransferOrder.objects.count()),
            before)
        r = self.c.admin.post("/api/v1/transfer-orders/", {
            "from_warehouse": self.hq.id, "to_warehouse": self.branch.id,
            "items": [{"product": l["product"], "qty": l["qty"],
                       "serial_ids": [s["id"] for s in l["serials"]]} for l in lines.values()],
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content.decode())
        self.assertEqual(set(ProductSerial.objects.filter(tenant=self.c.tenant)
                             .values_list("status", flat=True)), {"in_transit"})
        self.assertEqual(StockBalance.objects.get(product=self.c.case, warehouse=self.hq).qty, 0)
        # 調走之後,同一張進貨單沒有東西可以再調
        after = self.lines()
        self.assertEqual((after[self.c.phone.id]["qty"], after[self.c.case.id]["qty"]), (0, 0))
        self.assertEqual([g["status_label"] for g in after[self.c.phone.id]["gone"]], ["調撥中", "調撥中"])
        # 分店確認收貨後:東西在分店,也還是不能從這張進貨單再調一次
        r = self.c.admin.post(f"/api/v1/transfer-orders/{r.json()['id']}/confirm/")
        self.assertEqual(r.status_code, 200, r.content.decode())
        after = self.lines()
        self.assertEqual(after[self.c.phone.id]["qty"], 0)
        self.assertEqual({(g["status_label"], g["warehouse_name"]) for g in after[self.c.phone.id]["gone"]},
                         {("在庫", "甲民生店")})
        self.assertEqual(after[self.c.case.id]["qty"], 0)

    def test_sold_units_are_left_out_and_said(self):
        self.c.sell(serial_no=IMEI_A, case_qty=3)
        lines = self.lines()
        phone, case = lines[self.c.phone.id], lines[self.c.case.id]
        self.assertEqual((phone["qty"], [s["serial_no"] for s in phone["serials"]]), (1, [IMEI_B]))
        self.assertEqual([(g["serial_no"], g["status_label"]) for g in phone["gone"]], [(IMEI_A, "已售")])
        # 配件不分批:數量 = 這張單進的,但不超過進貨門市現在的庫存
        self.assertEqual((case["purchased"], case["qty"]), (10, 7))

    def test_only_what_this_order_brought_in(self):
        self.c.purchase(phone_serials=["352099001761481"], case_qty=50)   # 另一張單又進了 1 支、50 個
        lines = self.lines()
        self.assertEqual(lines[self.c.case.id]["qty"], 10)
        self.assertEqual([s["serial_no"] for s in lines[self.c.phone.id]["serials"]], [IMEI_A, IMEI_B])
        self.assertEqual(lines[self.c.phone.id]["gone"], [])

    def test_virtual_items_are_not_listed(self):
        fee = Product.objects.create(
            tenant=self.c.tenant, category=self.c.cat_case, name="甲 運費", requires_serial=False,
            is_virtual=True)
        po = self.c._post("/api/v1/purchase-orders/", {
            "supplier": self.c.supplier.id, "warehouse": self.hq.id, "tax_method": "untaxed",
            "items": [{"product": fee.id, "qty": 1, "unit_price": "100"},
                      {"product": self.c.case.id, "qty": 2, "unit_price": "100"}],
        })
        r = self.transferable(po=po)
        self.assertEqual([l["product"] for l in r.json()["lines"]], [self.c.case.id])

    def test_void_order_other_store_other_company(self):
        b = Company("b", "乙通訊行", "乙")
        self.assertEqual(self.transferable(client=b.admin).status_code, 404)
        # 鎖在湳雅店的店員看得到自己門市的進貨單,看不到民生店的
        self.assertEqual(self.transferable(client=self.c.clerk).status_code, 200)
        other = self.c.purchase(warehouse=self.branch, case_qty=1)
        self.assertEqual(self.transferable(client=self.c.clerk, po=other).status_code, 404)
        self.assertEqual(self.c.admin.post(f"/api/v1/purchase-orders/{self.po['id']}/void/").status_code, 200)
        r = self.transferable()
        self.assertEqual(r.status_code, 400)
        self.assertIn("已作廢", r.content.decode())
