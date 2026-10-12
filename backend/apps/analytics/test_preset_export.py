"""固定的報表匯出時給完整的:畫面只列前幾名的那一張(商品排行),檔不能只有前幾名、合計卻是全部的。"""
from dataclasses import replace
from decimal import Decimal
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from apps.analytics import presets
from apps.backup.tests.factory import Company


class PresetExportTests(TestCase):
    def setUp(self):
        self.c = Company("a", "甲通訊行", "甲")
        self.c.purchase(phone_serials=["甲IMEI1"], case_qty=10)
        self.c.sell(serial_no="甲IMEI1", case_qty=2)          # 兩個商品都有賣
        day = timezone.localdate().isoformat()
        self.range = {"from": day, "to": day}
        self.short = {**presets.REPORTS, "products": replace(presets.REPORTS["products"], keep=1)}

    def get(self, **params):
        r = self.c.admin.get("/api/v1/analytics/presets/products/", {**self.range, **params})
        self.assertEqual(r.status_code, 200, r.content.decode())
        return r.json()

    def test_screen_shows_the_top_rows_but_export_gives_all(self):
        with mock.patch.object(presets, "REPORTS", self.short):
            screen = self.get()
            everything = self.get(export="1")
        self.assertEqual((len(screen["rows"]), screen["row_count"], screen["truncated"]), (1, 2, True))
        self.assertEqual((len(everything["rows"]), everything["row_count"], everything["truncated"]), (2, 2, False))
        self.assertEqual(screen["totals"], everything["totals"])          # 合計本來就是全部的
        # 檔裡每一列加起來 = 合計(畫面那一份只有前一名,加起來對不上)
        total = Decimal(everything["totals"]["net_sales"])
        self.assertEqual(sum(Decimal(r["values"]["net_sales"]) for r in everything["rows"]), total)
        self.assertNotEqual(sum(Decimal(r["values"]["net_sales"]) for r in screen["rows"]), total)

    def test_without_the_cap_both_are_the_same(self):
        self.assertEqual(self.get()["rows"], self.get(export="1")["rows"])
        self.assertFalse(self.get(export="1")["truncated"])

    def test_over_the_engines_own_limit_still_says_so(self):
        from apps.analytics import engine

        with mock.patch.object(engine, "MAX_ROWS", 1):
            self.assertTrue(self.get(export="1")["truncated"])

    def test_export_follows_the_same_access_rules(self):
        from django.contrib.auth import get_user_model

        from apps.tenants.models import UserProfile

        mine = self.c.clerk.get("/api/v1/analytics/presets/products/", {**self.range, "export": "1"}).json()
        self.assertNotIn("gross_profit", {m["key"] for m in mine["columns"]["measures"]})     # 只給管理員的欄
        UserProfile.objects.filter(user=self.c.clerk_user).update(denied_abilities=["report_products"])
        clerk = Company.client(get_user_model().objects.get(pk=self.c.clerk_user.pk))
        r = clerk.get("/api/v1/analytics/presets/products/", {**self.range, "export": "1"})
        self.assertEqual(r.status_code, 403)
