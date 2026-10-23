"""今日總覽的待辦(2026-10-23,UI 改善計劃 6.1;紅隊:每一區跟著同一個門市範圍)。

鎖在門市的店員 = 自己那一家;沒鎖的管理員 = 全公司,或帶 ?warehouse= 看某一家。
"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.backup.tests.factory import Company
from apps.identity.models import IntakeBatch
from apps.inventory.models import StockCount
from apps.repairs.models import RepairOrder

URL = "/api/v1/home-summary/"


class HomeTodoTests(TestCase):
    def setUp(self):
        self.c = Company("a", "甲通訊行", "甲")
        self.w1, self.w2 = self.c.warehouses
        self.c.purchase(warehouse=self.w1, case_qty=10)
        self.c.purchase(warehouse=self.w2, case_qty=10)

    def dispatch(self, source, target, qty=1):
        return self.c._post("/api/v1/transfer-orders/", {
            "from_warehouse": source.id, "to_warehouse": target.id,
            "items": [{"product": self.c.case.id, "qty": qty}],
        })

    def repair(self, warehouse, **fields):
        order = self.c._post("/api/v1/repair-orders/", {
            "warehouse": warehouse.id, "customer": self.c.customer.id, "received_date": "2026-09-01",
            "mode": "in_house", "unlock_method": "none", "host_model_name": "iPhone 15",
        })
        RepairOrder.objects.filter(pk=order["id"]).update(**fields)
        return order

    def get(self, client, **params):
        r = client.get(URL, params)
        self.assertEqual(r.status_code, 200, r.content.decode())
        return r.json()

    def test_each_store_sees_its_own_queue_and_the_boss_can_pick(self):
        to_w2 = self.dispatch(self.w1, self.w2)                     # 寄到民生店
        self.dispatch(self.w2, self.w1)                             # 寄到湳雅店
        self.dispatch(self.w2, self.w1)
        done = self.dispatch(self.w2, self.w1)
        self.c._post(f"/api/v1/transfer-orders/{done['id']}/confirm/", {})   # 已入庫的不算
        now = timezone.now()
        self.repair(self.w1, status="ready_pickup", completed_at=now - timedelta(days=5))
        self.repair(self.w1, status="ready_pickup", completed_at=now)
        self.repair(self.w2, status="ready_pickup", completed_at=now)
        self.repair(self.w1, status="in_repair")
        IntakeBatch.objects.create(tenant=self.c.tenant, warehouse=self.w1, raw_text="甲 一")
        IntakeBatch.objects.create(tenant=self.c.tenant, warehouse=None, raw_text="甲 還沒選門市")
        IntakeBatch.objects.create(tenant=self.c.tenant, warehouse=self.w2, raw_text="甲 二")
        IntakeBatch.objects.create(tenant=self.c.tenant, warehouse=self.w1, raw_text="甲 過帳了",
                                   status=IntakeBatch.Status.COMMITTED)
        StockCount.objects.create(tenant=self.c.tenant, no="SC-1", warehouse=self.w1, status=StockCount.Status.SUBMITTED)
        StockCount.objects.create(tenant=self.c.tenant, no="SC-2", warehouse=self.w2, status=StockCount.Status.COUNTING)

        clerk = self.get(self.c.clerk)                              # 鎖在湳雅店
        self.assertEqual(clerk["warehouse_id"], self.w1.id)
        self.assertEqual(clerk["transfers_pending"]["count"], 2)
        self.assertEqual({t["from_name"] for t in clerk["transfers_pending"]["items"]}, {self.w2.name})
        self.assertEqual(clerk["repair_alerts"]["pickup"]["count"], 2)
        self.assertEqual(clerk["repair_alerts"]["pickup"]["items"][0]["ready_days"], 5)   # 放最久的在前
        self.assertEqual(clerk["repair_alerts"]["awaiting_pickup"]["count"], 1)           # 超過 3 天的照舊
        self.assertEqual(clerk["intake_open"], 2)
        self.assertEqual(clerk["counts_pending"], 1)
        # 店員帶別家的門市也一樣只看自己那一家
        self.assertEqual(self.get(self.c.clerk, warehouse=self.w2.id)["transfers_pending"]["count"], 2)

        boss = self.get(self.c.admin)                               # 全公司
        self.assertIsNone(boss["warehouse_id"])
        self.assertEqual(boss["transfers_pending"]["count"], 3)
        self.assertEqual(boss["repair_alerts"]["pickup"]["count"], 3)
        self.assertEqual(boss["intake_open"], 3)
        self.assertEqual(boss["counts_pending"], 1)

        w2 = self.get(self.c.admin, warehouse=self.w2.id)           # 老闆切到民生店
        self.assertEqual(w2["warehouse_name"], f"{self.w2.code} {self.w2.name}")
        self.assertEqual([t["id"] for t in w2["transfers_pending"]["items"]], [to_w2["id"]])
        self.assertEqual(w2["repair_alerts"]["pickup"]["count"], 1)
        self.assertEqual(w2["intake_open"], 2)                      # 民生店的 + 還沒選門市的
        self.assertEqual(w2["counts_pending"], 0)

    def test_overdue_counts_are_the_real_totals_not_the_first_ten(self):
        yesterday = timezone.localdate() - timedelta(days=1)
        for _ in range(12):
            self.repair(self.w1, status="in_repair", expected_complete_date=yesterday)
        alerts = self.get(self.c.admin)["repair_alerts"]
        self.assertEqual(alerts["overdue_repairs"]["count"], 12)
        self.assertEqual(len(alerts["overdue_repairs"]["items"]), 10)
