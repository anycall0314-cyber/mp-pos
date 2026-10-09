"""電信方案:看的人不限,改的只有管理員(2026-10-09)。

以前任何登入的店員都能新增 / 修改 / 刪除 / 批次建立方案;方案上的佣金會被帶到每一張銷貨單的明細。
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.backup.tests.factory import Company
from apps.tenants.models import UserProfile

from .models import Carrier, TelecomPlan

URL = "/api/v1/telecom-plans/"


class TelecomPlanPermissionTests(TestCase):
    def setUp(self):
        self.c = Company("a", "甲通訊行", "甲")
        self.t = self.c.tenant
        self.carrier = Carrier.objects.create(tenant=self.t, code="cht", name="中華電信")
        self.plan = TelecomPlan.objects.create(
            tenant=self.t, carrier=self.carrier, name="中華 1399 30月", monthly_fee=1399,
            contract_months=30, commission=12000,
        )

    def body(self, **over):
        return {"carrier": self.carrier.id, "name": "中華 999 24月", "monthly_fee": 999,
                "contract_months": 24, "kind": "new", "commission": "8000", **over}

    def snapshot(self):
        return sorted(TelecomPlan.objects.filter(tenant=self.t).values_list(
            "name", "monthly_fee", "contract_months", "commission", "is_active"))

    def test_a_clerk_can_still_read_plans(self):
        """開單要找得到方案:清單、明細、搜尋都照舊。"""
        r = self.c.clerk.get(URL)
        self.assertEqual(r.status_code, 200, r.content.decode())
        rows = r.json()["results"] if isinstance(r.json(), dict) else r.json()
        self.assertEqual([row["name"] for row in rows], ["中華 1399 30月"])
        self.assertEqual(self.c.clerk.get(f"{URL}{self.plan.id}/").status_code, 200)
        self.assertEqual(self.c.clerk.get(URL, {"search": "1399", "is_active": "true"}).status_code, 200)
        self.assertEqual(self.c.clerk.options(URL).status_code, 200)

    def test_a_clerk_cannot_change_anything(self):
        before = self.snapshot()
        one = f"{URL}{self.plan.id}/"
        attempts = [
            ("新增", lambda: self.c.clerk.post(URL, self.body(), format="json")),
            ("改佣金", lambda: self.c.clerk.patch(one, {"commission": "99999"}, format="json")),
            ("下架", lambda: self.c.clerk.patch(one, {"is_active": False}, format="json")),
            ("整筆改", lambda: self.c.clerk.put(one, self.body(name="改掉"), format="json")),
            ("刪除", lambda: self.c.clerk.delete(one)),
            ("批次新增", lambda: self.c.clerk.post(f"{URL}bulk/", {
                "common": {"carrier": self.carrier.id, "kind": "new"},
                "items": [{"name": "批次 A", "monthly_fee": "599", "contract_months": "24", "commission": "3000"}],
            }, format="json")),
        ]
        for what, attempt in attempts:
            with self.subTest(what=what):
                r = attempt()
                self.assertEqual(r.status_code, 403, r.content.decode())
                self.assertIn("只有管理員", r.json()["detail"])
                self.assertEqual(self.snapshot(), before)

    def test_a_manager_can_do_all_of_it(self):
        one = f"{URL}{self.plan.id}/"
        r = self.c.admin.patch(one, {"commission": "15000"}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.plan.refresh_from_db()
        self.assertEqual(self.plan.commission, 15000)
        self.assertEqual(self.c.admin.post(URL, self.body(), format="json").status_code, 201)
        r = self.c.admin.post(f"{URL}bulk/", {
            "common": {"carrier": self.carrier.id, "kind": "new"},
            "items": [{"name": "批次 A", "monthly_fee": "599", "contract_months": "24", "commission": "3000"}],
        }, format="json")
        self.assertIn(r.status_code, (200, 201), r.content.decode())
        self.assertEqual(TelecomPlan.objects.filter(tenant=self.t).count(), 3)
        self.assertEqual(self.c.admin.put(one, self.body(name="整筆改過"), format="json").status_code, 200)
        self.assertEqual(self.c.admin.delete(f"{URL}{TelecomPlan.objects.get(name='批次 A').id}/").status_code, 204)

    def test_the_platform_manager_can_change_them_too(self):
        root = get_user_model().objects.create_user("root", password="pw-12345")
        UserProfile.objects.create(user=root, role="platform_admin", tenant=None, is_warehouse_locked=False)
        client = APIClient()
        client.force_authenticate(root)
        r = client.patch(f"{URL}{self.plan.id}/?tenant={self.t.id}", {"commission": "13000"}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.plan.refresh_from_db()
        self.assertEqual(self.plan.commission, 13000)

    def test_someone_not_logged_in_gets_nothing(self):
        anon = APIClient()
        self.assertIn(anon.get(URL).status_code, (401, 403))
        self.assertIn(anon.patch(f"{URL}{self.plan.id}/", {"commission": "1"}, format="json").status_code, (401, 403))
        self.plan.refresh_from_db()
        self.assertEqual(self.plan.commission, 12000)

    def test_another_companys_manager_still_cannot_touch_it(self):
        b = Company("b", "乙通訊行", "乙")
        self.assertEqual(b.admin.get(f"{URL}{self.plan.id}/").status_code, 404)
        self.assertEqual(b.admin.patch(f"{URL}{self.plan.id}/", {"commission": "1"}, format="json").status_code, 404)
        self.assertEqual(b.admin.delete(f"{URL}{self.plan.id}/").status_code, 404)
        self.plan.refresh_from_db()
        self.assertEqual(self.plan.commission, 12000)
