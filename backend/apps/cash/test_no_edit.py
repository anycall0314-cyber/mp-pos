"""雜支、現金調整存好就不能改(owner 2026-10-24:「雜支、現金調整改成不能修改、記錯只能作廢再重記」)。

改了不留修改紀錄、改日期或金額會改到過去的營業日報;記錯了用作廢(要「作廢其他單」)再記一筆新的。
"""
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase

from apps.backup.tests.factory import Company
from apps.cash.models import CashAdjustment, PettyExpense
from apps.cash.views import NO_EDIT_ADJUST, NO_EDIT_PETTY

PETTY = "/api/v1/petty-expenses/"
ADJ = "/api/v1/cash-adjustments/"


class NoEditTests(TestCase):
    def setUp(self):
        self.c = Company("a", "甲通訊行", "甲")
        today = str(date.today())
        r = self.c.admin.post(PETTY, {
            "warehouse": self.c.wh.id, "doc_date": today, "category": "meal", "amount": "120",
            "payment_method": self.c.cash.id, "handled_by": self.c.sales_person.id, "note": "便當",
        }, format="json")
        assert r.status_code == 201, r.content
        self.petty = r.json()
        r = self.c.admin.post(ADJ, {
            "warehouse": self.c.wh.id, "doc_date": today, "direction": "in", "reason": "refill", "amount": "1000",
            "handled_by": self.c.sales_person.id, "note": "補零錢",
        }, format="json")
        assert r.status_code == 201, r.content
        self.adjust = r.json()
        self.yesterday = str(date.today() - timedelta(days=1))

    def snapshot(self):
        p = PettyExpense.objects.get(pk=self.petty["id"])
        a = CashAdjustment.objects.get(pk=self.adjust["id"])
        return (p.amount, p.doc_date, p.note, p.warehouse_id, p.is_void, a.amount, a.doc_date, a.direction, a.note, a.is_void)

    def test_patch_and_put_are_refused_and_nothing_changes(self):
        before = self.snapshot()
        for client in (self.c.admin, self.c.clerk):           # 老闆也一樣
            for method in ("patch", "put"):
                r = getattr(client, method)(f"{PETTY}{self.petty['id']}/", {
                    "warehouse": self.c.wh.id, "doc_date": self.yesterday, "category": "meal", "amount": "999",
                    "payment_method": self.c.cash.id, "note": "改過",
                }, format="json")
                self.assertEqual(r.status_code, 405, (method, r.content.decode()))
                self.assertEqual(r.json(), {"detail": NO_EDIT_PETTY})
                r = getattr(client, method)(f"{ADJ}{self.adjust['id']}/", {
                    "warehouse": self.c.wh.id, "doc_date": self.yesterday, "direction": "in", "reason": "refill",
                    "amount": "1", "note": "改過",
                }, format="json")
                self.assertEqual(r.status_code, 405, (method, r.content.decode()))
                self.assertEqual(r.json(), {"detail": NO_EDIT_ADJUST})
        self.assertEqual(self.snapshot(), before)

    def test_void_then_record_again_still_works(self):
        self.assertEqual(self.c.admin.post(f"{PETTY}{self.petty['id']}/void/", {}, format="json").status_code, 200)
        self.assertEqual(self.c.admin.post(f"{ADJ}{self.adjust['id']}/void/", {}, format="json").status_code, 200)
        # 作廢的也不能改
        r = self.c.admin.patch(f"{PETTY}{self.petty['id']}/", {"note": "作廢後改"}, format="json")
        self.assertEqual(r.status_code, 405)
        self.assertEqual(PettyExpense.objects.get(pk=self.petty["id"]).note, "便當")
        # 重記一筆
        r = self.c.admin.post(PETTY, {
            "warehouse": self.c.wh.id, "doc_date": str(date.today()), "category": "meal", "amount": "150",
            "payment_method": self.c.cash.id, "handled_by": self.c.sales_person.id,
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content.decode())
        self.assertEqual(
            list(PettyExpense.objects.filter(tenant=self.c.tenant).order_by("id").values_list("amount", "is_void")),
            [(Decimal("120.00"), True), (Decimal("150.00"), False)],
        )
