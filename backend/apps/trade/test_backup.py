"""批發的資料跟著公司備份走;對外的金鑰不跟(還原之後舊的金鑰不能自己活過來)。跑法:manage.py test apps.trade.test_backup"""
import json

from rest_framework.test import APIClient

from apps.backup.tests.test_backup_restore import _Base as BackupBase
from apps.catalog.models import Product
from apps.inventory.models import ProductSerial

from . import api, partners, payments
from .models import TradeKey, TradeOrder, TradePartner, TradePayment, TradeSetting, TradeShipment, TradeShipmentSerial, TradeUnit

T = "/api/v1/trade/"


class TradeBackupTests(BackupBase):
    def test_a_restore_brings_wholesale_back_but_not_the_keys(self):
        a, b = self.a, self.b
        r = a.admin.post(T + "settings/", {"is_open": True, "unit_rule": "price_minus", "unit_value": 1000, "pay_note": "玉山 808"}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        used = Product.objects.create(tenant=a.tenant, category=a.cat_phone, name="甲 中古 iPhone 13", is_secondhand=True, list_price=15000)
        rows = [{"sn": sn, "grade": "A", "cost": "12000", "price": "16000"} for sn in ("BK-U1", "BK-U2")]
        a._post("/api/v1/purchase-orders/", {"supplier": a.supplier.id, "warehouse": a.wh.id, "tax_method": "untaxed",
                                              "items": [{"product": used.id, "qty": 2, "unit_price": "12000", "serial_numbers": rows}]})
        code = a.admin.post(T + "invites/", {"percent": 90, "terms": "月結"}, format="json").json()["code"]
        inside = partners.join(b.tenant, code)
        made = a.admin.post(T + "partners/external/", {"name": "外面的丁", "contact": "0911"}, format="json").json()
        key = made["key"]
        unit = TradeUnit.objects.get(serial__serial_no="BK-U1")
        status, placed = api.handle(a.tenant, inside, "POST", "/orders",
                                    {"idempotency_key": "bk-key-00001", "items": [{"sku": used.sku, "spec_id": unit.id, "qty": 1}]}, store="乙一店")
        self.assertEqual(status, 200, placed)
        order = TradeOrder.objects.get()
        line = order.lines.get()
        r = a.admin.post(f"{T}orders/{order.id}/ship/", {"request_key": "bk-ship-0001", "warehouse": a.wh.id, "shipping_fee": 100,
                                                        "lines": [{"line": line.id, "qty": 1, "serials": [line.unit_id]}]}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        a.admin.post(T + "payments/", {"partner": inside.id, "amount": 5000, "request_key": "bk-pay-000001"}, format="json")
        before = payments.ledger(TradePartner.objects.get(pk=inside.id))
        self.assertEqual((before["owed"], before["due"]), (15100, 10100))

        job = self.backup(a)
        # 備份之後:又多一張單、換了一把金鑰
        status, later = api.handle(a.tenant, inside, "POST", "/orders", {
            "idempotency_key": "bk-key-00002", "items": [{"sku": used.sku, "spec_id": TradeUnit.objects.get(serial__serial_no="BK-U2").id, "qty": 1}]})
        self.assertEqual((status, later["order_no"]), (200, "TO-000002"))
        done = self.rollback(a, self.path(job))
        self.assertEqual(done.status, "done", done.error)
        a.reload()

        # 金鑰全部清掉:舊的那一把什麼都拿不到(要重發)
        self.assertEqual(TradeKey.objects.count(), 0)
        r = APIClient().get("/api/trade/v2/products", HTTP_AUTHORIZATION=f"Bearer {key}")
        self.assertEqual(r.status_code, 401)
        # 其餘的照備份當時的樣子回來,而且彼此還連得起來
        setting = TradeSetting.objects.get(tenant=a.tenant)
        self.assertEqual((setting.is_open, setting.pay_note, setting.unit_value), (True, "玉山 808", 1000))
        got = {p.name: p for p in TradePartner.objects.filter(tenant=a.tenant)}
        self.assertEqual({(p.name, p.kind, p.status, p.percent, p.terms) for p in got.values()},
                         {("乙通訊行", "platform", "approved", 90, "月結"), ("外面的丁", "external", "approved", 100, "匯款")})
        self.assertEqual(got["乙通訊行"].buyer_uuid, b.tenant.backup_uuid)
        order = TradeOrder.objects.get(tenant=a.tenant)
        line = order.lines.get()
        shipment = TradeShipment.objects.get(order=order)
        self.assertEqual((order.no, order.status, order.partner.name, line.unit.serial_no, line.unit.status, line.shipped_qty, line.holding),
                         ("TO-000001", "shipped", "乙通訊行", "BK-U1", "sold", 1, False))
        self.assertEqual((shipment.no, shipment.sales_order.tenant_id, shipment.sales_order.is_void, int(shipment.sales_order.total),
                          TradeShipmentSerial.objects.get().serial.serial_no),
                         ("TO-000001-1", a.tenant.id, False, 15100, "BK-U1"))
        self.assertEqual(TradePayment.objects.filter(tenant=a.tenant).count(), 1)
        after = payments.ledger(got["乙通訊行"])
        self.assertEqual((after["owed"], after["due"]), (15100, 10100))
        # 備份之後那一張沒了,那一台回到還在賣;它用過的單號不會再發一次(買家那邊還記著 TO-000002)
        self.assertEqual(ProductSerial.objects.get(tenant=a.tenant, serial_no="BK-U2").status, "in_stock")
        again = TradeUnit.objects.get(serial__serial_no="BK-U2")
        status, fresh = api.handle(a.tenant, got["乙通訊行"], "POST", "/orders",
                                   {"idempotency_key": "bk-key-00003", "items": [{"sku": used.sku, "spec_id": again.id, "qty": 1}]})
        self.assertEqual((status, fresh["order_no"]), (200, "TO-000003"), json.dumps(fresh, ensure_ascii=False))
        # 重新發一把金鑰就能用
        a.admin = a.client(a.admin_user)
        new = a.admin.post(f"{T}partners/{got['外面的丁'].id}/key/", {}, format="json")
        self.assertEqual(new.status_code, 200, new.content.decode())
        r = APIClient().get("/api/trade/v2/capabilities", HTTP_AUTHORIZATION=f"Bearer {new.json()['key']}")
        self.assertEqual(r.status_code, 200, r.content.decode())
