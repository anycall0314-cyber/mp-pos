"""瑕疵設備送廠商換貨(owner 2026-10-21:「瑕疵部分照你的方法做，回來了名字改為已換貨」)。

不搬、在原門市標「廠商換貨中」;換回來一定要刷回來的那一台(紅隊);盤點不用刷但另外列出來。
"""
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.backup.tests.factory import Company
from apps.inventory import stockcount
from apps.inventory.identifiers import find_serial_ids
from apps.inventory.models import (
    ProductSerial,
    ProductSerialCodeChange,
    ProductSerialIdentifier,
    StockMovement,
    VendorExchange,
)
from apps.ledger import checks

S = ProductSerial.Status
URL = "/api/v1/vendor-exchanges/"


def imei(body: str) -> str:
    """14 碼 + 檢查碼 = 像真的 IMEI(系統用檢查碼猜這個碼是 IMEI 還是 SN)。"""
    total = 0
    for i, ch in enumerate(reversed(body)):
        d = int(ch)
        if i % 2 == 0:
            d *= 2
            d -= 9 if d > 9 else 0
        total += d
    return body + str((10 - total % 10) % 10)


A, B, C, NEW = (imei(f"3560000000{n:04d}") for n in (1, 2, 3, 4))


class VendorExchangeTests(TestCase):
    def setUp(self):
        self.c = Company("a", "甲通訊行", "甲")
        self.home, self.other = self.c.warehouses
        self.c.purchase(phone_serials=[A, B])
        self.c.purchase(warehouse=self.other, phone_serials=[C])
        self.a = ProductSerial.objects.get(tenant=self.c.tenant, serial_no=A)

    def send(self, client=None, **body):
        return (client or self.c.admin).post(URL, {"code": A, **body}, format="json")

    def done(self, pk, code, client=None):
        return (client or self.c.admin).post(f"{URL}{pk}/done/", {"code": code}, format="json")

    def test_send_keeps_it_in_the_store_but_not_sellable(self):
        r = self.send(note="螢幕閃爍")
        self.assertEqual(r.status_code, 201, r.content)
        row = r.json()
        self.a.refresh_from_db()
        self.assertEqual(self.a.status, S.RMA)
        self.assertEqual(self.a.warehouse_id, self.home.id)          # 不搬
        self.assertEqual(row["supplier"]["id"], self.c.supplier.id)  # 照進貨單帶廠商
        self.assertEqual((row["sent_imei"], row["note"], row["days"]), (A, "螢幕閃爍", 0))
        self.assertEqual(row["sent_at"][:10], str(timezone.localdate()))        # 台灣的日期
        self.assertTrue(row["sent_at"].endswith("+08:00"))
        move = StockMovement.objects.get(serial=self.a, movement_type=StockMovement.MovementType.VENDOR_EXCHANGE)
        self.assertEqual((move.from_warehouse_id, move.to_warehouse_id), (None, None))   # 只是紀錄,不動數量
        listed = self.c.admin.get(URL).json()
        self.assertEqual([x["id"] for x in listed["results"]], [row["id"]])

        # 不能賣、不能調撥、不能再送一次
        sale = self.c.admin.post("/api/v1/sales-orders/", {
            "warehouse": self.home.id, "customer": self.c.customer.id, "sales_person": self.c.sales_person.id,
            "tax_method": "taxable_included", "invoice_type": self.c.invoice_type.id,
            "items": [{"product": self.c.phone.id, "qty": 1, "unit_price": "25000", "serial_ids": [self.a.id]}],
            "payments": [{"method": self.c.cash.id, "amount": "25000"}],
        }, format="json")
        self.assertEqual(sale.status_code, 400, sale.content)
        move = self.c.admin.post("/api/v1/transfer-orders/", {
            "from_warehouse": self.home.id, "to_warehouse": self.other.id,
            "items": [{"product": self.c.phone.id, "qty": 1, "serial_ids": [self.a.id]}],
        }, format="json")
        self.assertEqual(move.status_code, 400, move.content)
        self.assertEqual(self.send().status_code, 400)
        self.a.refresh_from_db()
        self.assertEqual(self.a.status, S.RMA)

    def test_same_unit_back_needs_its_own_code(self):
        pk = self.send().json()["id"]
        self.assertEqual(self.done(pk, "").status_code, 400)         # 不刷不收(紅隊)
        r = self.done(pk, B)                                        # 別台的碼
        self.assertEqual(r.status_code, 400, r.content)
        self.assertIn("別台", r.json()["detail"])
        self.a.refresh_from_db()
        self.assertEqual(self.a.status, S.RMA)

        r = self.done(pk, A.lower() + " ")
        self.assertEqual(r.status_code, 200, r.content)
        row = r.json()
        self.assertEqual((row["status"], row["swapped"], row["back_imei"]), ("done", False, A))
        self.a.refresh_from_db()
        self.assertEqual((self.a.status, self.a.serial_no, self.a.warehouse_id), (S.IN_STOCK, A, self.home.id))
        self.assertFalse(ProductSerialCodeChange.objects.filter(serial=self.a).exists())
        self.assertEqual(self.done(pk, A).status_code, 400)          # 處理過了
        self.assertEqual(self.c.admin.get(URL).json()["results"], [])
        closed = self.c.admin.get(URL, {"status": "closed"}).json()["results"]
        self.assertEqual([x["id"] for x in closed], [pk])

    def test_vendor_swapped_unit_takes_over_the_record(self):
        # 舊機另外登記了 IMEI2(拍照入庫才會有):換成新機之後不能還留在這一台
        ProductSerialIdentifier.objects.create(
            tenant=self.c.tenant, serial=self.a, kind="imei2", value="356999999999999",
            normalized_value="356999999999999")
        cost = self.a.purchase_unit_cost
        pk = self.send().json()["id"]
        r = self.done(pk, NEW)
        self.assertEqual(r.status_code, 200, r.content)
        row = r.json()
        self.assertEqual((row["swapped"], row["sent_imei"], row["back_imei"]), (True, A, NEW))
        self.a.refresh_from_db()
        self.assertEqual((self.a.status, self.a.serial_no), (S.IN_STOCK, NEW))
        self.assertEqual((self.a.purchase_unit_cost, self.a.warehouse_id), (cost, self.home.id))
        self.assertEqual(find_serial_ids(self.c.tenant, NEW), [self.a.id])
        self.assertEqual(find_serial_ids(self.c.tenant, A), [])
        self.assertEqual(find_serial_ids(self.c.tenant, "356999999999999"), [])
        change = ProductSerialCodeChange.objects.get(serial=self.a)
        self.assertEqual((change.before_imei, change.after_imei, change.changed_by), (A, NEW, "a-boss"))
        note = StockMovement.objects.filter(serial=self.a).order_by("-id").first().note
        self.assertIn(NEW, note)
        self.assertIn(A, note)
        self.assertEqual(checks.check_serials(self.c.tenant)[-1]["samples"], [])   # 碼都有登記

    def test_cancel_puts_it_back(self):
        pk = self.send().json()["id"]
        r = self.c.admin.post(f"{URL}{pk}/cancel/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["status"], "cancelled")
        self.a.refresh_from_db()
        self.assertEqual(self.a.status, S.IN_STOCK)
        self.assertEqual(self.c.admin.post(f"{URL}{pk}/cancel/", {}, format="json").status_code, 400)

    def test_sold_or_unknown_cannot_be_sent(self):
        self.c.sell(serial_no=B)
        self.assertEqual(self.send(code=B).status_code, 400)
        self.assertEqual(self.send(code="NOPE-1234").status_code, 400)
        self.assertFalse(VendorExchange.objects.exists())

    def test_clerk_locked_to_store_only_touches_own_store(self):
        clerk = self.c.clerk
        r = self.send(clerk, code=C)                                   # 別家門市的
        self.assertEqual(r.status_code, 403, r.content)
        other = self.send(self.c.admin, code=C).json()["id"]
        mine = self.send(clerk).json()["id"]
        self.assertEqual([x["id"] for x in clerk.get(URL).json()["results"]], [mine])
        self.assertEqual(self.done(other, C, clerk).status_code, 403)
        self.assertEqual(self.c.clerk.post(f"{URL}{other}/cancel/", {}, format="json").status_code, 403)
        self.assertEqual(self.done(mine, A, clerk).status_code, 200)
        self.assertEqual(VendorExchange.objects.get(pk=mine).done_by, "a-clerk")

    def test_done_from_the_sales_screen_only_for_the_same_unit(self):
        self.send()
        url = f"{URL}done-serial/"
        r = self.c.admin.post(url, {"serial": self.a.id, "code": NEW}, format="json")
        self.assertEqual(r.status_code, 400, r.content)               # 換新機要到清單刷
        self.a.refresh_from_db()
        self.assertEqual(self.a.status, S.RMA)
        r = self.c.admin.post(url, {"serial": self.a.id, "code": A}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.a.refresh_from_db()
        self.assertEqual(self.a.status, S.IN_STOCK)

    def test_stock_count_lists_it_but_does_not_expect_it(self):
        self.send(note="背蓋裂")
        count = stockcount.open_count(self.c.tenant, self.home, [], self.c.admin_user)
        self.assertNotIn(self.a.id, set(stockcount.expected_serials(count).values_list("pk", flat=True)))
        for client in (self.c.admin, self.c.clerk):                   # 盤的人也看得到
            rows = client.get(f"/api/v1/stock-counts/{count.id}/").json()["vendor_rows"]
            self.assertEqual([(x["serial_no"], x["supplier"]) for x in rows], [(A, self.c.supplier.name)])
        other = stockcount.open_count(self.c.tenant, self.other, [], self.c.admin_user)
        self.assertEqual(self.c.admin.get(f"/api/v1/stock-counts/{other.id}/").json()["vendor_rows"], [])

    def test_average_cost_counts_the_one_at_the_vendor(self):
        # A(20,000)送廠商、另一家門市還有 C(20,000),再進一台 30,000:平均 = 三台的平均 23,333.33;
        # 只看在庫的話會漏掉 A、變成 25,000(複審 P0)
        self.c.sell(serial_no=B)
        self.send()
        self.c._post("/api/v1/purchase-orders/", {
            "supplier": self.c.supplier.id, "warehouse": self.home.id, "tax_method": "untaxed",
            "items": [{"product": self.c.phone.id, "qty": 1, "unit_price": "30000", "serial_numbers": [NEW]}],
        })
        self.c.phone.refresh_from_db()
        self.assertEqual(self.c.phone.weighted_avg_cost, Decimal("23333.33"))
        # 重算的那一支(作廢進貨等會用)也一樣
        from apps.purchasing.services import _recompute_weighted_avg_cost
        _recompute_weighted_avg_cost(self.c.tenant, self.c.phone)
        self.c.phone.refresh_from_db()
        self.assertEqual(self.c.phone.weighted_avg_cost, Decimal("23333.33"))

    def test_back_after_the_count_started_is_not_lost(self):
        # 開盤的時候在廠商那邊;盤到一半換回來、按已換貨,那一區已經盤過、沒刷到 → 不能變成盤虧(複審 P0)
        pk = self.send().json()["id"]
        count = stockcount.open_count(self.c.tenant, self.home, [], self.c.admin_user)
        self.assertEqual(self.done(pk, A).status_code, 200)
        expected = set(stockcount.expected_serials(count).values_list("pk", flat=True))
        self.assertNotIn(self.a.id, expected)
        self.assertIn(ProductSerial.objects.get(serial_no=B).pk, expected)     # 一直都在的照樣要刷
        # 開盤之前就換回來的:照樣要刷
        pk_c = self.send(code=C).json()["id"]
        self.assertEqual(self.done(pk_c, C).status_code, 200)
        later = stockcount.open_count(self.c.tenant, self.other, [], self.c.admin_user)
        c_serial = ProductSerial.objects.get(serial_no=C)
        self.assertIn(c_serial.pk, set(stockcount.expected_serials(later).values_list("pk", flat=True)))

    def test_daily_checks_stay_clean(self):
        self.send()
        for result in checks.check_serials(self.c.tenant):
            self.assertEqual(result["samples"], [], result)


class AccessoryExchangeTests(TestCase):
    """配件(按數量的;owner:「換貨的通常都是配件沒序號也可以嗎」)。"""

    def setUp(self):
        from apps.parties.models import Supplier

        self.c = Company("b", "乙通訊行", "乙")
        self.home, self.other = self.c.warehouses
        self.case = self.c.case
        self.case.sku = "LC-0001"
        self.case.save(update_fields=["sku"])
        self.c.purchase(case_qty=5)                                   # 甲大盤商 100 元
        self.s2 = Supplier.objects.create(tenant=self.c.tenant, name="第二家")
        self.buy(self.s2, 2, "200")

    def buy(self, supplier, qty, price):
        self.c._post("/api/v1/purchase-orders/", {
            "supplier": supplier.id, "warehouse": self.home.id, "tax_method": "untaxed",
            "items": [{"product": self.case.id, "qty": qty, "unit_price": price}],
        })

    def balance(self):
        from apps.inventory.models import StockBalance

        return StockBalance.objects.get(product=self.case, warehouse=self.home)

    def send(self, client=None, **body):
        payload = {"product": self.case.id, "warehouse": self.home.id, "qty": 2, "supplier": self.s2.id, **body}
        return (client or self.c.admin).post(URL, payload, format="json")

    def test_lookup_lists_the_suppliers_who_sold_it(self):
        r = self.c.admin.get(f"{URL}lookup/", {"code": "lc-0001"})
        self.assertEqual(r.status_code, 200, r.content)
        data = r.json()
        self.assertEqual(data["kind"], "product")
        self.assertEqual([s["id"] for s in data["suppliers"]], [self.s2.id, self.c.supplier.id])   # 最近的在前
        self.assertIsNone(data["default_supplier"])                    # 兩家:要人照標籤選
        self.assertEqual({s["id"]: s["qty"] for s in data["stores"]}, {self.home.id: 7, self.other.id: 0})
        clerk = self.c.clerk.get(f"{URL}lookup/", {"code": "LC-0001"}).json()
        self.assertEqual([s["id"] for s in clerk["stores"]], [self.home.id])   # 鎖在門市的只看自己那一家

    def test_send_takes_them_off_the_shelf_and_supplier_is_required(self):
        avg = self.balance().weighted_avg_cost
        r = self.send(supplier="")
        self.assertEqual(r.status_code, 400, r.content)               # 廠商一定要選(紅隊)
        self.assertEqual(self.send(qty=8).status_code, 400)           # 比門市有的多
        r = self.send(note="線斷了")
        self.assertEqual(r.status_code, 201, r.content)
        row = r.json()
        self.assertEqual((row["kind"], row["qty"], row["back_qty"]), ("product", 2, 0))
        self.assertEqual(row["amount"], str((avg * 2).quantize(Decimal("0.01"))))
        self.assertEqual(self.balance().qty, 5)
        move = StockMovement.objects.get(ref_doc_type="vendor_exchange", ref_doc_id=row["id"])
        self.assertEqual((move.from_warehouse_id, move.to_warehouse_id, move.qty), (self.home.id, None, 2))
        # 店員看不到成本
        self.assertNotIn("amount", self.c.clerk.get(URL).json()["results"][0])
        # 進銷存表:換貨那一欄 −2,等式成立;每日對帳的配件庫存對得上
        flow = self.c.admin.get("/api/v1/stock-flow-report/", {
            "from": str(timezone.localdate()), "to": str(timezone.localdate()), "warehouse": self.home.id}).json()
        case = next(x for x in flow["rows"] if x["product"] == self.case.id)
        self.assertEqual((case["vendor"], case["closing"]), (-2, 5))
        self.assertIn({"key": "vendor", "label": "換貨", "sign": 1}, flow["columns"])
        for result in checks.check_stock_balance(self.c.tenant):
            self.assertEqual(result["samples"], [], result)

    def test_back_in_batches_at_the_cost_it_left_with(self):
        pk = self.send(qty=3).json()["id"]
        sent_cost = VendorExchange.objects.get(pk=pk).unit_cost
        self.buy(self.s2, 3, "300")                                    # 送出去之後又進了一批,平均變了
        before = self.balance()
        r = self.c.admin.post(f"{URL}{pk}/done/", {"qty": 1}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual((r.json()["status"], r.json()["back_qty"]), ("pending", 1))
        self.assertEqual(self.c.admin.post(f"{URL}{pk}/done/", {"qty": 5}, format="json").status_code, 400)
        r = self.c.admin.post(f"{URL}{pk}/done/", {}, format="json")   # 剩下的全部
        self.assertEqual((r.json()["status"], r.json()["back_qty"]), ("done", 3))
        after = self.balance()
        self.assertEqual(after.qty, before.qty + 3)
        want = ((before.qty * before.weighted_avg_cost + 3 * sent_cost) / (before.qty + 3)).quantize(Decimal("0.01"))
        self.assertEqual(after.weighted_avg_cost, want)               # 照送出時的成本加回去
        self.assertEqual(self.c.admin.post(f"{URL}{pk}/done/", {}, format="json").status_code, 400)

    def test_vendor_short_ships_only_a_manager_can_close_it(self):
        pk = self.send(qty=3).json()["id"]
        self.c.admin.post(f"{URL}{pk}/done/", {"qty": 1}, format="json")
        self.assertEqual(self.c.admin.post(f"{URL}{pk}/cancel/", {}, format="json").status_code, 400)  # 回來過就不能取消
        r = self.c.clerk.post(f"{URL}{pk}/unreturned/", {}, format="json")
        self.assertEqual(r.status_code, 403, r.content)               # 店員不能(紅隊)
        r = self.c.admin.post(f"{URL}{pk}/unreturned/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        row = r.json()
        self.assertEqual((row["status"], row["back_qty"]), ("unreturned", 1))
        self.assertEqual(self.balance().qty, 5)                        # 7 − 3 + 1,沒回來的不加回
        unit = VendorExchange.objects.get(pk=pk).unit_cost
        self.assertEqual(row["amount"], str((unit * 2).quantize(Decimal("0.01"))))
        for result in checks.check_stock_balance(self.c.tenant):
            self.assertEqual(result["samples"], [], result)

    def test_cancel_puts_them_all_back(self):
        pk = self.send().json()["id"]
        r = self.c.admin.post(f"{URL}{pk}/cancel/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self.balance().qty, 7)

    def test_clerk_only_in_own_store(self):
        self.c.transfer(2)                                            # 民生店也有 2 個
        r = self.send(self.c.clerk, warehouse=self.other.id)          # 鎖在湳雅店:照自己門市送
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["warehouse"]["id"], self.home.id)
        other = self.send(warehouse=self.other.id).json()["id"]
        self.assertEqual(self.c.clerk.post(f"{URL}{other}/done/", {}, format="json").status_code, 403)
        self.assertEqual(self.c.clerk.post(f"{URL}{other}/cancel/", {}, format="json").status_code, 403)

    def test_purchase_cannot_be_voided_after_some_went_to_the_vendor(self):
        # 送出去之後作廢那張進貨單、再換回來 → 成本會少算(複審 P0):送出去算動用過
        from apps.purchasing.models import PurchaseOrder

        po = PurchaseOrder.objects.filter(tenant=self.c.tenant, supplier=self.s2).order_by("-id").first()
        self.send(qty=1)
        r = self.c.admin.post(f"/api/v1/purchase-orders/{po.id}/void/", {}, format="json")
        self.assertEqual(r.status_code, 400, r.content)
        po.refresh_from_db()
        self.assertFalse(po.is_void)

    def test_manager_locked_to_a_store_cannot_close_another_stores(self):
        # 管理員也可以被鎖在門市:不換了一樣只動得到自己門市的(複審 P1)
        self.c.transfer(2)
        pk = self.send(warehouse=self.other.id).json()["id"]
        profile = self.c.admin_user.profile                # 測試的連線拿的是同一個帳號物件:改它身上的
        profile.is_warehouse_locked, profile.default_warehouse = True, self.home
        profile.save()
        r = self.c.admin.post(f"{URL}{pk}/unreturned/", {}, format="json")
        self.assertEqual(r.status_code, 403, r.content)
        self.assertEqual(VendorExchange.objects.get(pk=pk).status, "pending")

    def test_serial_without_purchase_needs_a_supplier(self):
        # 盤點入庫的手機沒有進貨單:送廠商要選廠商
        from apps.inventory.identifiers import create_serial

        s = create_serial(tenant=self.c.tenant, product=self.c.phone, code=imei("35600000009999"),
                          warehouse=self.home)
        r = self.c.admin.post(URL, {"serial": s.id}, format="json")
        self.assertEqual(r.status_code, 400, r.content)
        r = self.c.admin.post(URL, {"serial": s.id, "supplier": self.s2.id}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        lookup = self.c.admin.get(f"{URL}lookup/", {"code": s.serial_no}).json()
        self.assertEqual((lookup["kind"], lookup["sendable"]), ("serial", False))   # 已經在換了
