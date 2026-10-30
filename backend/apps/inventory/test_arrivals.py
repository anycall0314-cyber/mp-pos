"""今日總覽的「到貨」(owner 2026-10-30:「新品是一個,還有原本零庫存進貨的也要」)。規則在 `inventory/arrivals.py`。"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.backup.tests.factory import Company
from apps.catalog.models import Product
from apps.inventory.models import StockMovement

URL = "/api/v1/home-summary/"


class ArrivalsTests(TestCase):
    def setUp(self):
        c = self.c = Company("a", "甲通訊行", "甲")
        self.w1, self.w2 = c.warehouses
        # 昨天:湳雅店皮套進 2 賣 2(賣完了),民生店皮套有 3;湳雅店手機兩台
        c.purchase(warehouse=self.w1, case_qty=2, phone_serials=["A0001", "A0002"])
        c.sell(warehouse=self.w1, case_qty=2)
        c.purchase(warehouse=self.w2, case_qty=3)
        StockMovement.objects.filter(tenant=c.tenant).update(created_at=timezone.now() - timedelta(days=1))

    def buy(self, product, qty, warehouse=None):
        return self.c._post("/api/v1/purchase-orders/", {
            "supplier": self.c.supplier.id, "warehouse": (warehouse or self.w1).id, "tax_method": "untaxed",
            "items": [{"product": product.id, "qty": qty, "unit_price": "100"}],
        })

    def product(self, name, **fields):
        return Product.objects.create(tenant=self.c.tenant, category=self.c.cat_case, name=name,
                                      requires_serial=False, **fields)

    def arrivals(self, client, **params):
        r = client.get(URL, params)
        self.assertEqual(r.status_code, 200, r.content.decode())
        got = r.json()["arrivals"]
        return {k: [(i["name"], i["qty"]) for i in got[k]["items"]] for k in ("new", "restock")}, got

    def test_new_and_sold_out_restock_follow_the_store(self):
        fresh = self.product("甲 新款皮套")
        self.buy(fresh, 4)
        self.buy(self.c.case, 3)                                    # 湳雅店原本 0 個
        self.c.sell(warehouse=self.w2, case_qty=1)                 # 之後民生店賣掉一個:不影響湳雅店原本有幾個
        self.c.purchase(warehouse=self.w1, phone_serials=["A0003"])   # 原本就有兩台:一般補貨,不列
        part = self.product("甲 螢幕總成", warehouse_type=Product.WarehouseType.PARTS)
        self.buy(part, 2)                                           # 零件不列

        clerk, got = self.arrivals(self.c.clerk)                    # 鎖在湳雅店
        self.assertEqual(clerk, {"new": [("甲 新款皮套", 4)], "restock": [(self.c.case.name, 3)]})
        self.assertEqual(got["new"]["items"][0]["warehouses"], [self.w1.name])
        # 全公司:民生店本來就有皮套 → 不是缺貨補進;新品照樣是新品
        self.assertEqual(self.arrivals(self.c.admin)[0], {"new": [("甲 新款皮套", 4)], "restock": []})
        # 老闆切到民生店:今天沒有東西進民生店
        self.assertEqual(self.arrivals(self.c.admin, warehouse=self.w2.id)[0], {"new": [], "restock": []})

    def test_stock_before_is_counted_at_the_moment_it_arrived(self):
        self.c.purchase(warehouse=self.w1, case_qty=1)             # 今天:0 → 1(缺貨補進)
        self.c.sell(warehouse=self.w1, case_qty=1)
        self.assertEqual(self.arrivals(self.c.clerk)[0]["restock"], [(self.c.case.name, 1)])

        # 原本有兩台手機,今天進一台、再賣三台 → 現在 0,但進來的時候不是 0:不列
        self.c.purchase(warehouse=self.w1, phone_serials=["A0003"])
        for no in ("A0001", "A0002", "A0003"):
            self.c.sell(warehouse=self.w1, serial_no=no)
        self.assertNotIn(self.c.phone.name, [n for n, _ in self.arrivals(self.c.clerk)[0]["restock"]])

        # 今天先有貨、賣完之後又進一張:那一張進來時是 0 → 列
        self.c.purchase(warehouse=self.w1, phone_serials=["A0004"])
        self.assertIn((self.c.phone.name, 2), self.arrivals(self.c.clerk)[0]["restock"])

    def test_voided_purchase_is_not_an_arrival(self):
        fresh = self.product("甲 作廢的新款")
        po = self.buy(fresh, 1)
        self.c._post(f"/api/v1/purchase-orders/{po['id']}/void/", {})
        self.assertEqual(self.arrivals(self.c.clerk)[0], {"new": [], "restock": []})

    def test_latest_first(self):
        first, second = self.product("甲 早上到的"), self.product("甲 下午到的")
        self.buy(first, 1)
        self.buy(second, 1)
        StockMovement.objects.filter(tenant=self.c.tenant, product=first).update(
            created_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual([n for n, _ in self.arrivals(self.c.clerk)[0]["new"]], ["甲 下午到的", "甲 早上到的"])
