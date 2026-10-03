"""測試用:建一家有兩個門市、有進貨 / 銷貨 / 調撥 / 附件的公司。

盡量走真正的 API 建單,這樣帳本(序號、庫存餘額、異動、成本快照、付款)是系統
自己算出來的,不是測試手寫的。
"""
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from rest_framework.test import APIClient

from apps.catalog.models import Category, Product
from apps.identity.models import IntakeBatch, IntakeDocument, ProductAlias
from apps.inventory.models import Warehouse
from apps.parties.models import Customer, SalesPerson, Supplier
from apps.tenants.models import (
    InvoiceTrack,
    InvoiceType,
    PaymentMethod,
    Tenant,
    UserProfile,
)

STANDARD_NAME = "Reno16 側翻皮套／藍"


class Company:
    """一家測試公司。`tag` 會出現在每一筆資料裡,方便檢查有沒有混到別家。"""

    def __init__(self, code, name, tag, stores=("湳雅店", "民生店")):
        self.tag = tag
        self.tenant = Tenant.objects.create(name=name, code=code)
        self.warehouses = [
            Warehouse.objects.create(
                tenant=self.tenant, code=f"w{i + 1}", name=f"{tag}{store}"
            ) for i, store in enumerate(stores)
        ]
        self.wh = self.warehouses[0]
        self.cat_phone = Category.objects.create(tenant=self.tenant, code="PH", name="手機")
        self.cat_case = Category.objects.create(tenant=self.tenant, code="LC", name="皮套")
        self.supplier = Supplier.objects.create(tenant=self.tenant, name=f"{tag}大盤商")
        self.customer = Customer.objects.create(
            tenant=self.tenant, name=f"{tag}散客", phone="0912000111"
        )
        self.cash = PaymentMethod.objects.create(
            tenant=self.tenant, code="cash", name="現金", kind="cash"
        )
        self.invoice_type = InvoiceType.objects.create(
            tenant=self.tenant, code="none", name="免用", is_default=True
        )
        self.track = InvoiceTrack.objects.create(
            tenant=self.tenant, invoice_type=self.invoice_type, prefix="AB",
            range_start=10000000, range_end=10000049, next_number=10000007,
        )
        self.admin_user = self._user(f"{code}-boss", "tenant_admin")
        self.clerk_user = self._user(f"{code}-clerk", "tenant_user", self.wh)
        self.sales_person = SalesPerson.objects.create(
            tenant=self.tenant, code="S1", name=f"{tag}店員", user=self.clerk_user
        )
        self.admin = self.client(self.admin_user)
        self.clerk = self.client(self.clerk_user)
        self.phone = Product.objects.create(
            tenant=self.tenant, category=self.cat_phone, name=f"{tag} iPhone 15 128GB 黑",
            list_price=25000,
        )
        self.case = Product.objects.create(
            tenant=self.tenant, category=self.cat_case, name=STANDARD_NAME,
            requires_serial=False, list_price=390,
        )
        self.retired = Product.objects.create(
            tenant=self.tenant, category=self.cat_case, name=f"{tag} 停用的舊皮套",
            requires_serial=False, is_active=False,
        )

    def reload(self):
        """還原之後每一列都換了新的 id;照代碼 / 名稱把手上的物件重新抓一次。"""
        t = self.tenant
        self.warehouses = list(Warehouse.objects.filter(tenant=t).order_by("code"))
        self.wh = self.warehouses[0]
        self.cat_case = Category.objects.get(tenant=t, code="LC")
        self.cat_phone = Category.objects.get(tenant=t, code="PH")
        self.supplier = Supplier.objects.get(tenant=t)
        self.customer = Customer.objects.filter(tenant=t).order_by("id").first()
        self.sales_person = SalesPerson.objects.get(tenant=t, code="S1")
        self.phone = Product.objects.get(tenant=t, name=f"{self.tag} iPhone 15 128GB 黑")
        self.case = Product.objects.get(tenant=t, name=STANDARD_NAME)
        return self

    def _user(self, username, role, warehouse=None):
        user = get_user_model().objects.create_user(username=username, password="pw-12345")
        UserProfile.objects.create(
            user=user, role=role, tenant=self.tenant, default_warehouse=warehouse,
            is_warehouse_locked=(role == "tenant_user"),
        )
        return user

    @staticmethod
    def client(user):
        c = APIClient()
        c.force_authenticate(user)
        return c

    def _post(self, url, body):
        r = self.admin.post(url, body, format="json")
        assert r.status_code in (200, 201), (url, r.status_code, r.content.decode())
        return r.json()

    def purchase(self, warehouse=None, phone_serials=(), case_qty=0):
        items = []
        if phone_serials:
            items.append({
                "product": self.phone.id, "qty": len(phone_serials),
                "unit_price": "20000", "serial_numbers": list(phone_serials),
            })
        if case_qty:
            items.append({"product": self.case.id, "qty": case_qty, "unit_price": "100"})
        return self._post("/api/v1/purchase-orders/", {
            "supplier": self.supplier.id, "warehouse": (warehouse or self.wh).id,
            "tax_method": "untaxed", "items": items,
        })

    def sell(self, warehouse=None, serial_no=None, case_qty=0):
        from apps.inventory.models import ProductSerial

        items, total = [], 0
        if serial_no:
            serial = ProductSerial.objects.get(tenant=self.tenant, serial_no=serial_no)
            items.append({
                "product": self.phone.id, "qty": 1, "unit_price": "25000",
                "serial_ids": [serial.id],
            })
            total += 25000
        if case_qty:
            items.append({"product": self.case.id, "qty": case_qty, "unit_price": "390"})
            total += 390 * case_qty
        return self._post("/api/v1/sales-orders/", {
            "customer": self.customer.id, "warehouse": (warehouse or self.wh).id,
            "tax_method": "untaxed", "sales_person": self.sales_person.id,
            "items": items, "payments": [{"method": "cash", "amount": str(total)}],
        })

    def transfer(self, qty, source=None, target=None):
        source, target = source or self.warehouses[0], target or self.warehouses[1]
        order = self._post("/api/v1/transfer-orders/", {
            "from_warehouse": source.id, "to_warehouse": target.id,
            "items": [{"product": self.case.id, "qty": qty}],
        })
        return self._post(f"/api/v1/transfer-orders/{order['id']}/confirm/", {})

    def intake_document(self, content: bytes, name="單據.jpg"):
        import hashlib

        batch = IntakeBatch.objects.create(
            tenant=self.tenant, supplier=self.supplier, warehouse=self.wh,
            raw_text=f"{self.tag} 進貨單", created_by=self.admin_user,
        )
        doc = IntakeDocument(
            tenant=self.tenant, batch=batch, original_filename=name,
            content_hash=hashlib.sha256(content).hexdigest(), created_by=self.admin_user,
        )
        doc.image.save(name, ContentFile(content), save=True)
        return doc

    def remember(self, phrase):
        return ProductAlias.objects.create(
            tenant=self.tenant, product=self.case, kind=ProductAlias.Kind.LEGACY_NAME,
            value=phrase, created_by=self.admin_user,
        )


def standard_company(code="a", name="甲通訊行", tag="甲"):
    """兩家店、兩支手機、十個皮套;調撥四個到第二家店;賣掉一支手機與兩個皮套。"""
    c = Company(code, name, tag)
    c.purchase(phone_serials=[f"{tag}IMEI001", f"{tag}IMEI002"], case_qty=10)
    c.transfer(4)
    c.sell(serial_no=f"{tag}IMEI001", case_qty=2)
    c.intake_document(f"{tag} 的進貨單原圖".encode() * 50)
    c.remember("OPPO16代保護套-海洋")
    return c
