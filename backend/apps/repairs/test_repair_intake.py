"""維修單快速收件(owner 2026-10-19:「門市只是負責收件…要檢測才會有細項…最好是可以讓我快速開單」)。

紅隊之後 owner 定的:序號 / IMEI 必填、開不了機勾「取不到」(擋在收件畫面,lib/repairIntake);
收件預估費用印在收件單上(註明以檢測後報價為準);隨機配件記在單上。檢測之後那一段(自修 / 委外、項目、零件、費用)不變。
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase

from apps.backup.tests.factory import Company
from apps.parties.models import Member

from .models import RepairOrder

ORDERS = "/api/v1/repair-orders/"


class IntakeTests(TestCase):
    def setUp(self):
        self.c = Company("a", "甲通訊行", "甲")
        self.member = Member(tenant=self.c.tenant, name="王小明", phone="0912345678")
        self.member.save()

    def intake(self, **body):
        base = {"member": self.member.id, "warehouse": self.c.wh.id, "received_date": str(date.today()),
                "mode": "in_house", "unlock_method": "none", "host_model_name": "iPhone 15",
                "defect_description": "螢幕破"}
        return self.c.clerk.post(ORDERS, {**base, **body}, format="json")

    def test_serial_unavailable_is_kept_apart_from_an_empty_serial(self):
        r = self.intake(serial_unavailable=True)
        self.assertEqual(r.status_code, 201, r.content.decode())
        self.assertTrue(r.json()["serial_unavailable"])
        r = self.intake(device_serial="356789012345671")
        self.assertEqual(r.status_code, 201, r.content.decode())
        self.assertFalse(r.json()["serial_unavailable"])

    def test_estimate_and_accessories_are_kept(self):
        r = self.intake(device_serial="356789012345671", intake_estimate="1499.6", accessories="保護殼、SIM 卡")
        self.assertEqual(r.status_code, 201, r.content.decode())
        o = RepairOrder.objects.get(pk=r.json()["id"])
        self.assertEqual((o.intake_estimate, o.accessories), (Decimal("1500"), "保護殼、SIM 卡"))   # 金額整數
        self.assertEqual(self.intake(device_serial="1", intake_estimate="-1").status_code, 400)

    def test_an_order_from_before_without_a_serial_can_still_be_saved(self):
        r = self.intake()
        r = self.c.clerk.patch(f"{ORDERS}{r.json()['id']}/", {"internal_note": "師傅看過了"}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())


class OpenRepairsFilterTests(TestCase):
    """維修單清單預設只看還沒完成的(全站檢視 E4):?open=1 不列完成的、作廢的。"""

    def test_open_lists_only_unfinished_and_not_void(self):
        from apps.backup.tests.factory import Company
        from apps.repairs.models import RepairOrder

        c = Company("o", "開通訊行", "開")
        ids = {}
        for key, fields in {"doing": {"status": "in_repair"}, "ready": {"status": "ready_pickup"},
                            "done": {"status": "completed"}, "void": {"status": "in_repair", "is_void": True}}.items():
            o = c._post("/api/v1/repair-orders/", {"warehouse": c.wh.id, "customer": c.customer.id, "received_date": "2026-10-20",
                                                   "mode": "in_house", "unlock_method": "none", "host_model_name": "iPhone 15"})
            RepairOrder.objects.filter(pk=o["id"]).update(**fields)
            ids[key] = o["id"]
        r = c.admin.get("/api/v1/repair-orders/", {"open": "1"})
        rows = r.json()["results"] if isinstance(r.json(), dict) else r.json()
        self.assertEqual(sorted(o["id"] for o in rows), sorted([ids["doing"], ids["ready"]]))
        r = c.admin.get("/api/v1/repair-orders/")
        rows = r.json()["results"] if isinstance(r.json(), dict) else r.json()
        self.assertEqual(len(rows), 4)
