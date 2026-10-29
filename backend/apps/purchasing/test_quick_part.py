"""維修單上當場進一個零件(owner 2026-10-29:整理自家庫存的料可能只進一次,要「快速進貨加領料」)。

規則在 quick_part.py:既有的零件或新建一個 + 一張只有這一行的進貨單;維修單存檔與完工照舊。
"""
from decimal import Decimal

from django.test import TestCase

from apps.backup.tests.factory import Company
from apps.catalog.models import Category, Product
from apps.core.models import IdempotencyKey
from apps.inventory.models import ProductSerial, StockBalance
from apps.purchasing.models import PurchaseOrder

URL = "/api/v1/purchase-orders/quick-part/"
D = Decimal


class QuickPartTests(TestCase):
    def setUp(self):
        self.c = Company("a", "甲通訊行", "甲")
        self.home, self.other = self.c.warehouses
        self.c.purchase(phone_serials=["Q0001"])                 # 手機一台 20,000
        self.unit = ProductSerial.objects.get(tenant=self.c.tenant, serial_no="Q0001")

    def buy(self, client=None, key=None, **body):
        payload = {"supplier": self.c.supplier.id, "warehouse": self.home.id, "qty": 1, "unit_price": "5250", **body}
        headers = {"HTTP_IDEMPOTENCY_KEY": key} if key else {}
        return (client or self.c.admin).post(URL, payload, format="json", **headers)

    def bought(self, **body):
        r = self.buy(**body)
        self.assertEqual(r.status_code, 201, r.content.decode())
        return r.json()

    def test_new_part_is_built_and_bought_in_one_go(self):
        data = self.bought(name="Fold5 內屏")
        part = Product.objects.get(pk=data["product"]["id"])
        self.assertEqual((part.name, part.warehouse_type, part.category.name), ("Fold5 內屏", "parts", "維修料"))
        self.assertEqual(part.weighted_avg_cost, D("5000.00"))               # 5,250 含稅 → 未稅 5,000
        self.assertEqual(D(data["product"]["weighted_avg_cost"]), D("5000"))  # 管理員看到的是實際成本
        po = PurchaseOrder.objects.get(pk=data["purchase_order"]["id"])
        self.assertEqual((po.no, po.supplier_id, po.warehouse_id, po.note), (data["purchase_order"]["no"],
                         self.c.supplier.id, self.home.id, "維修單當場進貨"))
        self.assertEqual([(i.product_id, i.qty) for i in po.items.all()], [(part.id, 1)])
        self.assertEqual(StockBalance.objects.get(product=part, warehouse=self.home).qty, 1)
        # 第二個新零件放進同一個類別(不再建一個「維修料」)
        again = self.bought(name="Fold5 後蓋", unit_price="1050")
        self.assertEqual(Product.objects.get(pk=again["product"]["id"]).category_id, part.category_id)
        self.assertEqual(Category.objects.filter(tenant=self.c.tenant, name="維修料").count(), 1)

    def test_refurb_order_uses_it_and_the_cost_lands_on_that_phone(self):
        part_id = self.bought(name="Fold5 內屏")["product"]["id"]
        r = self.c.admin.post("/api/v1/repair-orders/", {
            "stock_serial": self.unit.id, "warehouse": self.home.id, "received_date": "2026-10-29",
            "mode": "in_house", "unlock_method": "none", "defect_description": "內屏壞",
            "sales_person": self.c.sales_person.id, "parts_input": [{"part_product": part_id, "qty": 1}],
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content.decode())
        self.assertEqual(self.c.admin.post(f"/api/v1/repair-orders/{r.json()['id']}/complete/", {},
                                           format="json").status_code, 200)
        self.unit.refresh_from_db()
        self.assertEqual(self.unit.purchase_unit_cost, D("25000.00"))       # 20,000 + 內屏 5,000
        self.assertEqual(StockBalance.objects.get(product_id=part_id, warehouse=self.home).qty, 0)

    def test_existing_part_is_bought_into_not_duplicated(self):
        cat = Category.objects.create(tenant=self.c.tenant, code="PT", name="零件")
        screen = Product.objects.create(tenant=self.c.tenant, sku="PT-900001", name="Fold5 內屏",
                                        category=cat, warehouse_type="parts", requires_serial=False)
        data = self.bought(product=screen.id, qty=2)
        self.assertEqual((data["product"]["id"], data["qty"]), (screen.id, 2))
        self.assertEqual(StockBalance.objects.get(product=screen, warehouse=self.home).qty, 2)
        self.assertEqual(Product.objects.filter(tenant=self.c.tenant, name__contains="內屏").count(), 1)
        # 新零件跟著放進已經有零件的那個類別
        self.assertEqual(Product.objects.get(pk=self.bought(name="Fold5 後蓋")["product"]["id"]).category_id, cat.id)

    def test_only_parts(self):
        r = self.buy(product=self.c.case.id)                              # 皮套是商品倉的
        self.assertEqual(r.status_code, 400, r.content)
        tracked = Product.objects.create(tenant=self.c.tenant, sku="RP-900001", name="逐台追蹤的零件",
                                         category=self.c.cat_case, warehouse_type="parts")   # 預設要追蹤序號
        self.assertEqual(self.buy(product=tracked.id).status_code, 400)
        virtual = Product.objects.create(tenant=self.c.tenant, sku="RP-900002", name="虛擬的零件", category=self.c.cat_case,
                                         warehouse_type="parts", requires_serial=False, is_virtual=True)
        self.assertEqual(self.buy(product=virtual.id).status_code, 400)
        self.assertEqual(self.buy().status_code, 400)                     # 沒選也沒填
        self.assertEqual(self.buy(name="X", product=self.c.case.id).status_code, 400)
        self.assertFalse(PurchaseOrder.objects.filter(note="維修單當場進貨").exists())

    def test_same_name_is_sent_back_with_who_and_nothing_is_kept(self):
        r = self.buy(name=self.c.case.name, key="dup-key-0001")
        self.assertEqual(r.status_code, 409, r.content)
        self.assertEqual(r.json()["code"], "duplicate_product")
        self.assertEqual([x["id"] for x in r.json()["candidates"]], [self.c.case.id])
        self.assertFalse(PurchaseOrder.objects.filter(note="維修單當場進貨").exists())
        self.assertFalse(IdempotencyKey.objects.filter(key="dup-key-0001").exists())   # 改名再送是新的一次
        self.assertEqual(self.buy(name="Fold5 內屏", key="dup-key-0001").status_code, 201)

    def test_same_key_twice_buys_once(self):
        first = self.buy(name="Fold5 內屏", key="quick-key-0001")
        again = self.buy(name="Fold5 內屏", key="quick-key-0001")
        self.assertEqual((first.status_code, again.status_code), (201, 200), again.content)
        self.assertEqual(again["Idempotent-Replay"], "true")
        self.assertEqual(first.json()["purchase_order"]["no"], again.json()["purchase_order"]["no"])
        self.assertEqual(PurchaseOrder.objects.filter(note="維修單當場進貨").count(), 1)
        # 一般建進貨單用同一把鑰匙不會拿到這一張(各自的範圍)
        self.assertEqual(IdempotencyKey.objects.get(key="quick-key-0001").scope, "repair-quick-part")

    def test_staff_needs_purchase_own_store_and_product_rights_for_new(self):
        profile = self.c.clerk_user.profile
        profile.denied_abilities = ["edit_products"]
        profile.save()
        screen = Product.objects.create(tenant=self.c.tenant, sku="RP-000001", name="Fold5 內屏",
                                        category=self.c.cat_case, warehouse_type="parts", requires_serial=False)
        self.assertEqual(self.buy(client=self.c.clerk, name="Fold5 後蓋").status_code, 403)   # 建新的要「商品建檔」
        self.assertEqual(self.buy(client=self.c.clerk, product=screen.id).status_code, 201)   # 既有的照進
        self.assertEqual(self.buy(client=self.c.clerk, product=screen.id, warehouse=self.other.id).status_code, 403)
        profile.denied_abilities = ["purchase"]
        profile.save()
        self.assertEqual(self.buy(client=self.c.clerk, product=screen.id).status_code, 403)
        self.assertEqual(PurchaseOrder.objects.filter(note="維修單當場進貨").count(), 1)
        self.assertFalse(Product.objects.filter(name="Fold5 後蓋").exists())

    def test_other_company_ids_are_refused(self):
        b = Company("b", "乙通訊行", "乙")
        self.assertEqual(self.buy(product=b.case.id).status_code, 400)
        self.assertEqual(self.buy(name="Fold5 內屏", supplier=b.supplier.id).status_code, 400)
        self.assertEqual(self.buy(name="Fold5 內屏", warehouse=b.wh.id).status_code, 400)
        self.assertFalse(Product.objects.filter(tenant=self.c.tenant, name="Fold5 內屏").exists())


class StockModelTests(TestCase):
    """自家庫存的維修單:機型照那一台的商品帶(維修項目照機型列;owner「沒辦法先選擇機型」)。"""

    def test_lookup_and_open_carry_the_model(self):
        c = Company("a", "甲通訊行", "甲")
        c.purchase(phone_serials=["M0001"])
        unit = ProductSerial.objects.get(tenant=c.tenant, serial_no="M0001")
        [found] = c.admin.get("/api/v1/repair-orders/stock-search/", {"q": "M0001"}).json()
        self.assertTrue(found["model_key"])
        self.assertEqual((found["model_key"], found["model_name"]),
                         (c.phone.phone_model_key, c.phone.phone_model_name))
        r = c.admin.post("/api/v1/repair-orders/", {
            "stock_serial": unit.id, "warehouse": c.wh.id, "received_date": "2026-10-29", "mode": "in_house",
            "unlock_method": "none", "defect_description": "整理", "sales_person": c.sales_person.id,
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content.decode())
        self.assertEqual(r.json()["host_model_key"], c.phone.phone_model_key)


class PartsSearchTests(TestCase):
    """維修單的領用零件只搜零件倉(手機、配件挑了也不能用;列出來會把「新零件進貨」擠到最下面,owner「沒有相關品號就無法進貨」)。"""

    def test_search_can_ask_for_parts_only(self):
        c = Company("a", "甲通訊行", "甲")
        cat = Category.objects.create(tenant=c.tenant, code="RP", name="維修料")
        part = Product.objects.create(tenant=c.tenant, sku="RP-900001", name="Fold5 內屏", category=cat,
                                      warehouse_type="parts", requires_serial=False)
        c.phone.name = "Galaxy Z Fold5 256GB"
        c.phone.save()
        found = lambda **q: [p["id"] for p in c.admin.get("/api/v1/products/", {"search": "Fold5", **q}).json()["results"]]
        self.assertEqual(set(found()), {part.id, c.phone.id})                    # 不帶:照舊全部
        self.assertEqual(found(warehouse_type="parts"), [part.id])
        self.assertEqual(found(warehouse_type="product"), [c.phone.id])
