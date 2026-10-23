"""打烊實點(owner 2026-10-23「實點加上去」):記下點到多少與當下應有,不改帳;一天可以點好幾次、都列出來。"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.backup.tests.factory import Company
from apps.cash.models import CashCount

DAILY = "/api/v1/reports/business-daily/"
COUNT = "/api/v1/reports/business-daily/count/"


class CashCountTests(TestCase):
    def setUp(self):
        self.c = Company("a", "甲通訊行", "甲")
        self.c.purchase(case_qty=5)
        self.c.sell(case_qty=1)                      # 現金收 390

    def daily(self, day, client=None):
        r = (client or self.c.admin).get(DAILY, {"warehouse": self.c.wh.id, "date": day.isoformat()})
        self.assertEqual(r.status_code, 200, r.content.decode())
        return r.json()

    def count(self, amount, client=None, warehouse=None):
        return (client or self.c.admin).post(
            COUNT, {"warehouse": (warehouse or self.c.wh).id, "counted": amount}, format="json")

    def test_a_count_records_the_difference_and_does_not_touch_the_books(self):
        today = timezone.localdate()
        r = self.count("300")
        self.assertEqual(r.status_code, 201, r.content.decode())
        self.assertEqual([(x["counted"], x["expected"], x["diff"]) for x in r.json()["counts"]], [(300, 390, -90)])
        d = self.daily(today)
        self.assertEqual((d["net_change"], d["can_count"]), (390, True))
        self.assertEqual(d["counts"][0]["by"], "a-boss")
        self.assertEqual(self.daily(today + timedelta(days=1))["opening_cash"], 390)      # 隔天期初照舊

    def test_every_count_of_the_day_is_listed_and_none_can_be_changed(self):
        self.count("300")
        self.count("390", client=self.c.clerk)       # 交班再點一次
        d = self.daily(timezone.localdate())
        self.assertEqual([(x["counted"], x["diff"], x["by"]) for x in d["counts"]],
                         [(300, -90, "a-boss"), (390, 0, "甲店員")])
        self.assertEqual(CashCount.objects.count(), 2)
        self.assertFalse(self.daily(timezone.localdate() - timedelta(days=1))["can_count"])

    def test_who_may_count_and_what_is_accepted(self):
        other = self.c.warehouses[1]
        self.assertEqual(self.count("100", client=self.c.clerk, warehouse=other).status_code, 403)   # 鎖在第一家
        for bad in ("12.5", "-3", "abc", ""):
            self.assertEqual(self.count(bad).status_code, 400, bad)
        profile = self.c.clerk_user.profile
        profile.denied_abilities = ["view_business_daily"]
        profile.save()
        self.assertEqual(self.count("100", client=self.c.clerk).status_code, 403)
        self.assertEqual(CashCount.objects.count(), 0)
