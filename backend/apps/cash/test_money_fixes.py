"""全站檢視 E6 / E7:維修取機收的現金進營業日報;現金調整的事由決定方向。"""
from datetime import date, timedelta

from django.test import TestCase
from django.utils import timezone

from apps.backup.tests.factory import Company
from apps.parties.models import Member
from apps.tenants.models import PaymentMethod

ORDERS = "/api/v1/repair-orders/"
DAILY = "/api/v1/reports/business-daily/"
ADJ = "/api/v1/cash-adjustments/"


class RepairCashTests(TestCase):
    def setUp(self):
        self.c = Company("a", "甲通訊行", "甲")
        self.member = Member.objects.create(tenant=self.c.tenant, name="王小明", phone="0912345678")
        self.card = PaymentMethod.objects.create(tenant=self.c.tenant, code="card", name="刷卡", kind="non_cash")

    def order(self, paid, method=None):
        r = self.c.admin.post(ORDERS, {
            "member": self.member.id, "warehouse": self.c.wh.id, "received_date": str(date.today()),
            "mode": "in_house", "unlock_method": "none", "host_model_name": "iPhone 15", "defect_description": "螢幕破",
            "customer_paid_amount": str(paid), "payment_method": method.id if method else None,
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content.decode())
        return r.json()

    def complete(self, o):
        return self.c.admin.post(f"{ORDERS}{o['id']}/complete/", {}, format="json")

    def daily(self, day):
        r = self.c.admin.get(DAILY, {"warehouse": self.c.wh.id, "date": day.isoformat()})
        self.assertEqual(r.status_code, 200, r.content.decode())
        return r.json()

    def test_cash_repairs_count_on_the_day_they_are_completed_and_carry_into_tomorrow(self):
        cash = self.order(1500, self.c.cash)
        self.assertEqual(self.complete(cash).status_code, 200)
        card = self.order(800, self.card)
        self.assertEqual(self.complete(card).status_code, 200)
        self.order(600, self.c.cash)                      # 還沒完成的不算
        today = timezone.localdate()
        d = self.daily(today)
        self.assertEqual(d["repairs"]["total"], 1500)      # 刷卡的不進現金
        self.assertEqual([r["no"] for r in d["repairs"]["rows"]], [cash["no"]])
        self.assertEqual(d["net_change"], 1500)
        nxt = self.daily(today + timedelta(days=1))
        self.assertEqual((nxt["opening_cash"], nxt["repairs"]["total"]), (1500, 0))   # 當天結餘 = 隔天期初

    def test_a_paid_repair_needs_a_payment_method_before_it_can_be_completed(self):
        o = self.order(1500)
        r = self.complete(o)
        self.assertEqual(r.status_code, 400, r.content.decode())
        self.assertIn("收款方式", r.json()["detail"])
        self.assertEqual(self.c.admin.get(f"{ORDERS}{o['id']}/").json()["status"], "pending")
        self.assertEqual(self.complete(self.order(0)).status_code, 200)   # 沒收錢的照常完成


class CashAdjustmentReasonTests(TestCase):
    def setUp(self):
        self.c = Company("a", "甲通訊行", "甲")

    def post(self, reason, direction):
        return self.c.admin.post(ADJ, {
            "warehouse": self.c.wh.id, "doc_date": str(date.today()), "reason": reason, "direction": direction,
            "amount": "1000", "handled_by": self.c.sales_person.id,
        }, format="json")

    def test_the_reason_decides_the_direction_for_refill_deposit_and_owner_take(self):
        for reason, wrong in (("refill", "out"), ("deposit", "in"), ("owner_take", "in")):
            r = self.post(reason, wrong)
            self.assertEqual(r.status_code, 400, (reason, r.content.decode()))
            self.assertIn("direction", r.json())
        for reason, right in (("refill", "in"), ("deposit", "out"), ("owner_take", "out")):
            self.assertEqual(self.post(reason, right).status_code, 201, reason)
        # 盤點校正、其他兩個方向都可以
        for direction in ("in", "out"):
            self.assertEqual(self.post("adjustment", direction).status_code, 201)
            self.assertEqual(self.post("other", direction).status_code, 201)
        # 改既有的一筆:2026-10-24 起根本不能修改(owner:記錯只能作廢再重記),方向照舊
        made = self.post("deposit", "out").json()
        r = self.c.admin.patch(f"{ADJ}{made['id']}/", {"direction": "in"}, format="json")
        self.assertEqual(r.status_code, 405, r.content.decode())
