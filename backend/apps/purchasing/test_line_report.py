"""進貨明細:進貨單的每一行一列。"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.backup.tests.factory import Company
from apps.catalog.models import Product
from apps.parties.models import Supplier
from apps.purchasing.models import PurchaseOrder

URL = "/api/v1/purchase-line-report/"


def today():
    return timezone.localdate()


class PurchaseLineTests(TestCase):
    def setUp(self):
        c = self.c = Company("a", "甲通訊行", "甲")
        self.w1, self.w2 = c.warehouses
        self.po = c.purchase(phone_serials=["甲IMEI1", "甲IMEI2", "甲IMEI3"], case_qty=10)
        self.second_supplier = Supplier.objects.create(tenant=c.tenant, name="甲二盤")
        self.glass = Product.objects.create(
            tenant=c.tenant, category=c.cat_case, name="9H 保護貼", requires_serial=False, list_price=300)
        # 含稅的單、有贈品:進 12 片只算 10 片的錢
        self.taxed = c._post("/api/v1/purchase-orders/", {
            "supplier": self.second_supplier.id, "warehouse": self.w2.id, "tax_method": "taxable_included",
            "note": "月結", "items": [{"product": self.glass.id, "qty": 12, "billed_qty": 10, "unit_price": "105"}],
        })

    def rows(self, client=None, **params):
        r = (client or self.c.admin).get(URL, {"from": today(), "to": today(), "export": "1", **params})
        self.assertEqual(r.status_code, 200, r.content.decode())
        return r.json()

    def test_one_row_per_line(self):
        data = self.rows()
        self.assertEqual((data["count"], data["truncated"]), (3, False))
        by_name = {r["name"]: r for r in data["results"]}
        phone = by_name[self.c.phone.name]
        self.assertEqual(
            {k: phone[k] for k in ("date", "doc", "store", "supplier", "sku", "qty", "free_qty", "unit_price", "amount", "cost")},
            {"date": today().isoformat(), "doc": {"kind": "purchase", "id": self.po["id"], "no": self.po["no"]},
             "store": self.w1.name, "supplier": self.c.supplier.name, "sku": self.c.phone.sku, "qty": 3, "free_qty": 0,
             "unit_price": "20000.00", "amount": "60000.00", "cost": "60000.00"},
        )
        glass = by_name["9H 保護貼"]
        # 單上:含稅 105 × 計價 10 片 = 1,050;記進庫存的成本是未稅 1,000(12 片分攤)
        self.assertEqual((glass["qty"], glass["free_qty"], glass["unit_price"], glass["amount"], glass["note"]),
                         (12, 2, "105.00", "1050.00", "月結"))
        self.assertEqual(Decimal(glass["cost"]).quantize(Decimal("1")), Decimal("1000"))
        self.assertEqual(data["totals"]["qty"], 3 + 10 + 12)
        self.assertEqual(Decimal(data["totals"]["amount"]), Decimal("60000") + Decimal("1000") + Decimal("1050"))

    def test_cost_total_is_the_purchase_amount_of_the_free_form_report(self):
        spec = {"measures": ["purchase_untaxed", "purchase_qty"], "dimensions": [],
                "period": {"from": today().isoformat(), "to": today().isoformat()}}
        got = self.c.admin.post("/api/v1/analytics/query/", spec, format="json").json()["totals"]
        mine = self.rows()["totals"]
        self.assertEqual(Decimal(mine["cost"]), Decimal(got["purchase_untaxed"]))
        self.assertEqual(mine["qty"], got["purchase_qty"])

    def test_voided_purchases_are_left_out(self):
        self.assertEqual(self.c.admin.post(f"/api/v1/purchase-orders/{self.taxed['id']}/void/").status_code, 200)
        data = self.rows()
        self.assertEqual({r["doc"]["no"] for r in data["results"]}, {self.po["no"]})
        self.assertEqual(data["totals"]["qty"], 13)

    def test_conditions(self):
        names = lambda **p: sorted(r["name"] for r in self.rows(**p)["results"])
        self.assertEqual(names(supplier=self.second_supplier.id), ["9H 保護貼"])
        self.assertEqual(names(warehouse=self.w2.id), ["9H 保護貼"])
        self.assertEqual(names(category=self.c.cat_phone.id), [self.c.phone.name])
        self.assertEqual(names(search="保護貼"), ["9H 保護貼"])
        self.assertEqual(names(search=self.c.case.sku), [self.c.case.name])
        self.assertEqual(names(search="iphone 保護貼"), [])
        self.assertEqual(self.rows(supplier=self.second_supplier.id)["totals"]["qty"], 12)       # 合計跟著條件走
        yesterday = today() - timedelta(days=1)
        self.assertEqual(self.rows(**{"from": yesterday, "to": yesterday})["count"], 0)
        PurchaseOrder.objects.filter(pk=self.taxed["id"]).update(doc_date=yesterday)             # 看的是單據日期
        self.assertEqual(self.rows(**{"from": yesterday, "to": yesterday})["count"], 1)
        self.assertEqual(self.rows()["count"], 2)                                                # 起日之前的不列

    def test_pages_and_newest_first(self):
        r = self.c.admin.get(URL, {"from": today(), "to": today(), "page_size": 2}).json()
        self.assertEqual((len(r["results"]), r["count"]), (2, 3))
        self.assertIsNotNone(r["next"])
        self.assertEqual(r["totals"]["qty"], 25)                          # 合計是全部的,不是這一頁
        self.assertEqual(r["results"][0]["doc"]["no"], self.taxed["no"])  # 後開的那一張在前面

    def test_locked_account_only_sees_its_own_store(self):
        mine = self.rows(client=self.c.clerk, warehouse=self.w2.id)        # 網址帶別家的編號沒有用
        self.assertEqual({r["store"] for r in mine["results"]}, {self.w1.name})
        self.assertEqual(mine["totals"]["qty"], 13)

    def test_other_companies_and_bad_conditions(self):
        from rest_framework.test import APIClient

        other = Company("b", "乙通訊行", "乙")
        other.purchase(case_qty=5)
        self.assertEqual(self.rows()["count"], 3)
        self.assertEqual(self.rows(supplier=other.supplier.id)["count"], 0)
        self.assertEqual(self.rows(warehouse=other.wh.id)["count"], 0)
        get = self.c.admin.get
        self.assertEqual(get(URL, {"from": today(), "to": today() - timedelta(days=1)}).status_code, 400)
        self.assertEqual(get(URL, {"supplier": "x"}).status_code, 400)
        self.assertIn(APIClient().get(URL).status_code, (401, 403))
