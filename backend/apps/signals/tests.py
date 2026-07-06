"""需求感知最小切片測試。

證明:
1. Trends CSV 匯入 → MarketSignal(關鍵字經別名對應到 subject_key)。
2. 授權閘:熱度↑ 且內部↑ → 上升+已授權;熱度↑ 但內部平 → 觀望+未授權;退燒 → 下降。
不需外部 API、可離線重複跑。
"""
import csv
import tempfile
from datetime import date, timedelta
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from apps.catalog.models import Category, Product
from apps.tenants.models import Tenant

from .models import DemandAlert, MarketSignal, SubjectAlias, SubjectKind
from .services import compute_product_demand_alerts, record_signal

AS_OF = date(2026, 7, 1)


class SignalsTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="測試通訊行", code="demo")
        self.category = Category.objects.create(tenant=self.tenant, code="PH", name="手機")

    def _product(self, name, trend_ratio):
        return Product.objects.create(
            tenant=self.tenant, category=self.category, name=name,
            trend_ratio=Decimal(str(trend_ratio)),
        )

    def _alias(self, alias, key, product):
        return SubjectAlias.objects.create(
            tenant=self.tenant, alias=alias, subject_key=key,
            kind=SubjectKind.PRODUCT_SALES, product=product,
        )

    def _seed_heat(self, subject_key, recent_val, prev_val):
        """近 7 天每天 recent_val,前 7 天每天 prev_val。"""
        for i in range(7):
            record_signal(self.tenant, MarketSignal.Source.GOOGLE_TRENDS, subject_key,
                          AS_OF - timedelta(days=i), recent_val)
            record_signal(self.tenant, MarketSignal.Source.GOOGLE_TRENDS, subject_key,
                          AS_OF - timedelta(days=7 + i), prev_val)

    # ── CSV 匯入 ─────────────────────────────────────────────
    def test_import_trends_csv(self):
        p = self._product("iPhone 15 Pro 256GB 黑", 1.2)
        self._alias("iPhone 15 Pro", "apple-iphone-15-pro", p)

        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["date", "keyword", "value"])
            w.writerow(["2026-06-30", "iPhone 15 Pro", "80"])
            w.writerow(["2026-06-29", "iPhone 15 Pro", "75"])
            w.writerow(["2026-06-29", "無對應關鍵字", "50"])  # 應被列為 unmapped
            path = fh.name

        out = StringIO()
        call_command("import_trends_csv", "--tenant", "demo", "--file", path, stdout=out)
        text = out.getvalue()

        self.assertIn("匯入 2 筆訊號", text)
        self.assertIn("無對應關鍵字", text)  # 未對應提醒
        self.assertEqual(
            MarketSignal.objects.filter(subject_key="apple-iphone-15-pro").count(), 2
        )

    # ── 授權閘:熱度↑ + 內部↑ → 上升、已授權 ────────────────────
    def test_heat_up_internal_up_authorized(self):
        p = self._product("iPhone 15 Pro 256GB 黑", 1.30)  # 內部 +30%
        self._alias("i15p", "apple-iphone-15-pro", p)
        self._seed_heat("apple-iphone-15-pro", recent_val=20, prev_val=10)  # 熱度 +100%

        alerts = compute_product_demand_alerts(self.tenant, as_of=AS_OF)
        self.assertEqual(len(alerts), 1)
        a = alerts[0]
        self.assertEqual(a.direction, DemandAlert.Direction.UP)
        self.assertTrue(a.authorized)
        self.assertEqual(a.heat_growth, Decimal("1.0000"))
        self.assertEqual(a.internal_growth, Decimal("0.3000"))

    # ── 授權閘:熱度↑ 但內部平 → 觀望、未授權(防庫存山)──────────
    def test_heat_up_internal_flat_watch_unauthorized(self):
        p = self._product("Galaxy S25 256GB 黑", 1.00)  # 內部持平
        self._alias("s25", "samsung-galaxy-s25", p)
        self._seed_heat("samsung-galaxy-s25", recent_val=20, prev_val=10)  # 熱度 +100%

        alerts = compute_product_demand_alerts(self.tenant, as_of=AS_OF)
        self.assertEqual(len(alerts), 1)
        a = alerts[0]
        self.assertEqual(a.direction, DemandAlert.Direction.WATCH)
        self.assertFalse(a.authorized)

    # ── 退燒 → 下降 ──────────────────────────────────────────
    def test_heat_down_direction_down(self):
        p = self._product("iPhone 12 128GB 黑", 0.80)
        self._alias("i12", "apple-iphone-12", p)
        self._seed_heat("apple-iphone-12", recent_val=5, prev_val=10)  # 熱度 -50%

        alerts = compute_product_demand_alerts(self.tenant, as_of=AS_OF)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].direction, DemandAlert.Direction.DOWN)
