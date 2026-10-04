"""其他模組(進貨 / 調撥 / 雜支 / 現金調整 / 代收話費 / 維修)的跨公司與門市鎖防護。

每一種單先用自己公司的資料建一張(確認測試送的格式是對的),再換成別家公司的編號 → 要被欄位擋下;
鎖在自己門市的店員到別家門市建單 → 403。
"""
from datetime import date

from django.test import TestCase

from apps.backup.tests.factory import Company
from apps.parties.models import Carrier


class _Base(TestCase):
    def setUp(self):
        self.a = Company("a", "甲通訊行", "甲")
        self.b = Company("b", "乙通訊行", "乙")
        self.a.purchase(case_qty=5)
        self.b.purchase(case_qty=5)
        self.carrier_a = Carrier.objects.create(tenant=self.a.tenant, code="cht", name="中華")
        self.carrier_b = Carrier.objects.create(tenant=self.b.tenant, code="cht", name="中華")

    def bodies(self, c, carrier, warehouse=None):
        """六種單各一份最小的送出內容(全部用公司 c 自己的資料)。"""
        wh = warehouse or c.wh
        other = c.warehouses[1] if wh.pk == c.warehouses[0].pk else c.warehouses[0]
        return {
            "/api/v1/purchase-orders/": {
                "supplier": c.supplier.id, "warehouse": wh.id, "tax_method": "untaxed",
                "items": [{"product": c.case.id, "qty": 1, "unit_price": "100"}],
            },
            "/api/v1/transfer-orders/": {
                "from_warehouse": wh.id, "to_warehouse": other.id,
                "items": [{"product": c.case.id, "qty": 1}],
            },
            "/api/v1/petty-expenses/": {
                "warehouse": wh.id, "category": "other", "amount": "100",
                "payment_method": c.cash.id, "handled_by": c.sales_person.id,
            },
            "/api/v1/cash-adjustments/": {
                "warehouse": wh.id, "direction": "in", "reason": "refill", "amount": "100",
                "handled_by": c.sales_person.id,
            },
            "/api/v1/phone-bills/": {
                "warehouse": wh.id, "carrier": carrier.id, "phone_no": "0912345678",
                "amount": "500", "id_no": "A123456789", "handled_by": c.sales_person.id,
            },
            "/api/v1/repair-orders/": {
                "warehouse": wh.id, "customer": c.customer.id, "received_date": str(date.today()),
                "mode": "in_house", "unlock_method": "none", "host_model_name": "iPhone 15",
            },
        }


class OwnCompanyTests(_Base):
    def test_each_document_can_be_created_with_own_records(self):
        for url, body in self.bodies(self.a, self.carrier_a).items():
            r = self.a.admin.post(url, body, format="json")
            self.assertEqual(r.status_code, 201, (url, r.content.decode()))


class CrossCompanyTests(_Base):
    # 每種單:把哪些欄位換成別家公司的編號
    SWAPS = {
        "/api/v1/purchase-orders/": ["supplier", "warehouse"],
        "/api/v1/transfer-orders/": ["from_warehouse", "to_warehouse"],
        "/api/v1/petty-expenses/": ["warehouse", "payment_method", "handled_by"],
        "/api/v1/cash-adjustments/": ["warehouse", "handled_by"],
        "/api/v1/phone-bills/": ["warehouse", "carrier", "handled_by"],
        "/api/v1/repair-orders/": ["warehouse", "customer"],
    }

    def test_another_companys_ids_are_refused_field_by_field(self):
        mine = self.bodies(self.b, self.carrier_b)
        theirs = self.bodies(self.a, self.carrier_a)
        for url, fields in self.SWAPS.items():
            for field in fields:
                body = dict(mine[url], **{field: theirs[url][field]})
                r = self.b.admin.post(url, body, format="json")
                self.assertEqual(r.status_code, 400, (url, field, r.content.decode()))
                self.assertIn(field, r.json(), (url, field, r.content.decode()))

    def test_another_companys_product_in_the_lines_is_refused(self):
        for url in ("/api/v1/purchase-orders/", "/api/v1/transfer-orders/"):
            body = self.bodies(self.b, self.carrier_b)[url]
            body["items"][0]["product"] = self.a.case.id
            r = self.b.admin.post(url, body, format="json")
            self.assertEqual(r.status_code, 400, (url, r.content.decode()))
            self.assertIn("items", r.json(), (url, r.content.decode()))

    def test_repair_parts_must_be_own_products(self):
        r = self.b.admin.post("/api/v1/repair-items/", {
            "name": "換螢幕", "parts_input": [{"part_product": self.a.case.id, "default_qty": 1}],
        }, format="json")
        self.assertEqual(r.status_code, 400, r.content)
        self.assertIn("parts_input", r.json())
        body = dict(self.bodies(self.b, self.carrier_b)["/api/v1/repair-orders/"],
                    parts_input=[{"part_product": self.a.case.id, "qty": 1}])
        r = self.b.admin.post("/api/v1/repair-orders/", body, format="json")
        self.assertEqual(r.status_code, 400, r.content)
        self.assertIn("parts_input", r.json())


class StoreLockTests(_Base):
    def test_store_locked_clerk_creates_only_in_own_store(self):
        own = self.bodies(self.a, self.carrier_a, warehouse=self.a.warehouses[0])
        elsewhere = self.bodies(self.a, self.carrier_a, warehouse=self.a.warehouses[1])
        for url in own:
            r = self.a.clerk.post(url, elsewhere[url], format="json")
            self.assertEqual(r.status_code, 403, (url, r.content.decode()))
            r = self.a.clerk.post(url, own[url], format="json")
            self.assertEqual(r.status_code, 201, (url, r.content.decode()))


class ServiceTests(_Base):
    """不經過 API 直接呼叫存檔邏輯,也要擋(第二道防線)。"""

    def test_purchase(self):
        from apps.purchasing.models import PurchaseOrder, PurchaseOrderItem
        from apps.purchasing.services import PurchaseOrderError, commit_purchase_order

        po = PurchaseOrder.objects.create(tenant=self.b.tenant, supplier=self.b.supplier,
                                          warehouse=self.a.wh, tax_method="untaxed")
        PurchaseOrderItem.objects.create(tenant=self.b.tenant, po=po, product=self.b.case, qty=1,
                                         unit_price=100)
        with self.assertRaisesMessage(PurchaseOrderError, "供應商 / 門市"):
            commit_purchase_order(po)
        po = PurchaseOrder.objects.create(tenant=self.b.tenant, supplier=self.b.supplier,
                                          warehouse=self.b.wh, tax_method="untaxed")
        PurchaseOrderItem.objects.create(tenant=self.b.tenant, po=po, product=self.a.case, qty=1,
                                         unit_price=100)
        with self.assertRaisesMessage(PurchaseOrderError, "商品不屬於這家公司"):
            commit_purchase_order(po)

    def test_transfer(self):
        from apps.transfers.models import TransferOrder, TransferOrderItem
        from apps.transfers.services import TransferOrderError, dispatch_transfer_order

        to = TransferOrder.objects.create(tenant=self.b.tenant, from_warehouse=self.b.wh,
                                          to_warehouse=self.a.wh)
        TransferOrderItem.objects.create(tenant=self.b.tenant, to=to, product=self.b.case, qty=1)
        with self.assertRaisesMessage(TransferOrderError, "門市不屬於這家公司"):
            dispatch_transfer_order(to)
        to = TransferOrder.objects.create(tenant=self.b.tenant, from_warehouse=self.b.warehouses[0],
                                          to_warehouse=self.b.warehouses[1])
        TransferOrderItem.objects.create(tenant=self.b.tenant, to=to, product=self.a.case, qty=1)
        with self.assertRaisesMessage(TransferOrderError, "商品 / 序號不屬於這家公司"):
            dispatch_transfer_order(to)

    def test_repair_completion(self):
        from apps.repairs.models import RepairOrder, RepairOrderPart

        order = RepairOrder.objects.create(
            tenant=self.b.tenant, warehouse=self.b.wh, customer=self.b.customer,
            received_date=date.today(), mode="in_house", unlock_method="none",
        )
        RepairOrderPart.objects.create(tenant=self.b.tenant, repair_order=order,
                                       part_product=self.a.case, qty=1, unit_cost=0)
        r = self.b.admin.post(f"/api/v1/repair-orders/{order.id}/complete/", {}, format="json")
        self.assertEqual(r.status_code, 400, r.content)
        self.assertIn("不屬於這家公司", r.json()["detail"])


class IntakeRawIdTests(_Base):
    def test_unknown_or_foreign_supplier_and_store_are_refused_not_blanked(self):
        from apps.identity.models import IntakeBatch

        for field, bad in (("supplier", self.a.supplier.id), ("supplier", 99999999),
                           ("warehouse", self.a.wh.id), ("warehouse", 99999999)):
            r = self.b.admin.post("/api/v1/identity/intakes/",
                                  {"raw_text": "皮套 x1", field: bad}, format="json")
            self.assertEqual(r.status_code, 400, (field, bad, r.content))
            self.assertIn(field, r.json())
        self.assertFalse(IntakeBatch.objects.filter(tenant=self.b.tenant).exists())
        r = self.b.admin.post("/api/v1/identity/intakes/", {
            "raw_text": "皮套 x1", "supplier": self.b.supplier.id, "warehouse": self.b.wh.id,
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content)


class LineRowTests(_Base):
    """明細列本身掛的公司也要對(不經 API 建出「單是甲的、明細列是乙的」要擋)。"""

    def test_purchase_transfer_and_repair_lines(self):
        from apps.purchasing.models import PurchaseOrder, PurchaseOrderItem
        from apps.purchasing.services import PurchaseOrderError, commit_purchase_order
        from apps.repairs.models import RepairOrder, RepairOrderPart
        from apps.transfers.models import TransferOrder, TransferOrderItem
        from apps.transfers.services import TransferOrderError, dispatch_transfer_order

        po = PurchaseOrder.objects.create(tenant=self.b.tenant, supplier=self.b.supplier,
                                          warehouse=self.b.wh, tax_method="untaxed")
        PurchaseOrderItem.objects.create(tenant=self.a.tenant, po=po, product=self.b.case, qty=1,
                                         unit_price=100)
        with self.assertRaisesMessage(PurchaseOrderError, "不屬於這家公司"):
            commit_purchase_order(po)

        to = TransferOrder.objects.create(tenant=self.b.tenant, from_warehouse=self.b.warehouses[0],
                                          to_warehouse=self.b.warehouses[1])
        TransferOrderItem.objects.create(tenant=self.a.tenant, to=to, product=self.b.case, qty=1)
        with self.assertRaisesMessage(TransferOrderError, "不屬於這家公司"):
            dispatch_transfer_order(to)

        order = RepairOrder.objects.create(
            tenant=self.b.tenant, warehouse=self.b.wh, customer=self.b.customer,
            received_date=date.today(), mode="in_house", unlock_method="none",
        )
        RepairOrderPart.objects.create(tenant=self.a.tenant, repair_order=order,
                                       part_product=self.b.case, qty=1, unit_cost=0)
        r = self.b.admin.post(f"/api/v1/repair-orders/{order.id}/complete/", {}, format="json")
        self.assertEqual(r.status_code, 400, r.content)


class LockedWithoutStoreTests(_Base):
    def test_store_locked_account_with_no_store_sees_no_company_wide_reports(self):
        from apps.tenants.models import UserProfile

        UserProfile.objects.filter(user=self.a.clerk_user).update(default_warehouse=None)
        self.a.clerk_user.refresh_from_db()
        for url in ("/api/v1/home-summary/", "/api/v1/inventory-alerts/",
                    "/api/v1/clearance-pressure/", "/api/v1/parts-usage-report/"):
            r = self.a.clerk.get(url)
            self.assertEqual(r.status_code, 403, (url, r.content[:200]))
            self.assertEqual(self.a.admin.get(url).status_code, 200, url)


class ReadLeakTests(_Base):
    """不靠送編號也能看到別家資料的路:API 瀏覽頁、篩選條件。"""

    def test_api_browser_page_is_off(self):
        r = self.a.admin.get("/api/v1/sales-orders/?format=api")
        self.assertNotIn("text/html", r.get("Content-Type", ""))
        self.assertNotIn(self.b.customer.name, r.content.decode("utf-8", "replace"))
        r = self.a.admin.get("/api/v1/sales-orders/", HTTP_ACCEPT="text/html")
        self.assertNotIn("text/html", r.get("Content-Type", ""))

    def test_filters_treat_another_companys_id_like_a_missing_one(self):
        self.assertEqual(
            self.a.admin.get(f"/api/v1/sales-orders/?customer={self.a.customer.id}").status_code, 200)
        other = self.a.admin.get(f"/api/v1/sales-orders/?customer={self.b.customer.id}")
        missing = self.a.admin.get("/api/v1/sales-orders/?customer=99999999")
        self.assertEqual((other.status_code, missing.status_code), (400, 400))
        other = self.a.admin.get(f"/api/v1/stock-balances/?warehouse={self.b.wh.id}")
        self.assertEqual(other.status_code, 400, other.content)


class BuybackStoreLockTests(_Base):
    def test_store_locked_clerk_buys_back_only_in_own_store(self):
        from apps.catalog.models import Product
        from apps.parties.models import Member

        member = Member.objects.create(tenant=self.a.tenant, name="甲會員", phone="0911000222")
        used = Product.objects.create(
            tenant=self.a.tenant, category=self.a.cat_phone, name="甲 中古 iPhone 13",
            is_secondhand=True, list_price=12000,
        )
        body = {
            "member": member.id, "product": used.id, "serial_no": "甲USED1",
            "condition_grade": "A", "acquisition_price": "8000", "payment_method_code": "cash",
        }
        r = self.a.clerk.post("/api/v1/sales-orders/secondhand-acquisition/",
                              dict(body, warehouse=self.a.warehouses[1].id), format="json")
        self.assertEqual(r.status_code, 403, r.content)
        r = self.a.clerk.post("/api/v1/sales-orders/secondhand-acquisition/",
                              dict(body, warehouse=self.a.warehouses[0].id), format="json")
        self.assertIn(r.status_code, (200, 201), r.content)
        # 別家公司的會員 / 門市 / 商品:欄位本身就不接受
        r = self.b.admin.post("/api/v1/sales-orders/secondhand-acquisition/",
                              dict(body, warehouse=self.b.wh.id, serial_no="乙USED1"), format="json")
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(sorted(r.json()), ["member", "product"])


class UnboundAccountTests(_Base):
    """沒綁公司的帳號:只有平台管理員(與 superuser)能指定要看哪一家公司。"""

    def client_with_token(self, username, role=None, superuser=False):
        from django.contrib.auth import get_user_model
        from rest_framework.authtoken.models import Token
        from rest_framework.test import APIClient

        from apps.tenants.models import UserProfile

        User = get_user_model()
        user = (User.objects.create_superuser if superuser else User.objects.create_user)(
            username=username, password="pw-12345")
        if role:
            UserProfile.objects.create(user=user, role=role, tenant=None, is_warehouse_locked=False)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=user).key}")
        return client

    def setUp(self):
        super().setUp()
        self.a.sell(case_qty=1)

    def test_account_without_a_company_cannot_use_company_data(self):
        nobody = self.client_with_token("nobody")
        for url in ("/api/v1/sales-orders/", f"/api/v1/sales-orders/?tenant={self.a.tenant.pk}"):
            r = nobody.get(url)
            self.assertEqual(r.status_code, 403, (url, r.content))
        r = nobody.get("/api/v1/sales-orders/", HTTP_X_TENANT_ID=str(self.a.tenant.pk))
        self.assertEqual(r.status_code, 403, r.content)
        self.assertEqual(nobody.get("/api/v1/auth/me/").status_code, 200)

    def test_platform_admin_and_superuser_can_still_pick_a_company(self):
        for client in (self.client_with_token("root", role="platform_admin"),
                       self.client_with_token("super", superuser=True)):
            r = client.get(f"/api/v1/sales-orders/?tenant={self.a.tenant.pk}")
            self.assertEqual(r.status_code, 200, r.content)
            self.assertEqual(r.json()["count"], 1)
            r = client.get(f"/api/v1/sales-orders/?tenant={self.b.tenant.pk}")
            self.assertEqual(r.json()["count"], 0)

    def test_company_user_cannot_switch_company(self):
        from rest_framework.authtoken.models import Token
        from rest_framework.test import APIClient

        client = APIClient()
        client.credentials(
            HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=self.b.admin_user).key}")
        r = client.get(f"/api/v1/sales-orders/?tenant={self.a.tenant.pk}")
        self.assertEqual((r.status_code, r.json()["count"]), (200, 0))


class CompanySwitchRuleTests(_Base):
    def test_only_platform_roles_may_name_a_company(self):
        from django.conf import settings
        from django.contrib.auth import get_user_model
        from django.test import RequestFactory

        from apps.tenants.middleware import _resolve_tenant_from_request, effective_tenant_id
        from apps.tenants.models import UserProfile

        User = get_user_model()
        nobody = User.objects.create_user("nobody2", password="pw-12345")
        root = User.objects.create_user("root2", password="pw-12345")
        UserProfile.objects.create(user=root, role="platform_admin", tenant=None,
                                   is_warehouse_locked=False)
        for user, expected in ((nobody, settings.DEFAULT_TENANT_ID), (root, self.a.tenant.pk),
                               (self.b.admin_user, self.b.tenant.pk)):
            request = RequestFactory().get(f"/api/v1/sales-orders/?tenant={self.a.tenant.pk}")
            request.user = user
            self.assertEqual(_resolve_tenant_from_request(request).pk, expected, user.username)
            self.assertEqual(effective_tenant_id(request, user), expected, user.username)
