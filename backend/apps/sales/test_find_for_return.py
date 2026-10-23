"""找原單來退(全站檢視 A5 / A7):打會員電話 / 姓名、刷手機的 IMEI 找得到那張單;退過的單帶著那張銷退單號。"""
from django.test import TestCase

from apps.backup.tests.factory import Company
from apps.parties.models import Member
from apps.sales.models import SalesOrder

URL = "/api/v1/sales-orders/"
RETURNS = "/api/v1/sales-returns/"


class FindOrderToReturnTests(TestCase):
    def setUp(self):
        self.c = Company("a", "甲通訊行", "甲")
        self.c.purchase(phone_serials=["356938035643809", "SNOTHER0001"], case_qty=5)
        self.member = Member.objects.create(tenant=self.c.tenant, name="王小明", phone="0912345678")
        self.sold = self.c.sell(serial_no="356938035643809")
        SalesOrder.objects.filter(pk=self.sold["id"]).update(member=self.member)
        self.other = self.c.sell(case_qty=1)

    def found(self, **params):
        r = self.c.clerk.get(URL, params)
        self.assertEqual(r.status_code, 200, r.content.decode())
        body = r.json()
        rows = body["results"] if isinstance(body, dict) else body
        return [o["id"] for o in rows]

    def test_member_phone_and_name_find_the_order(self):
        self.assertEqual(self.found(search="0912345678"), [self.sold["id"]])
        self.assertEqual(self.found(search="王小明"), [self.sold["id"]])

    def test_scanning_the_phone_finds_the_order_that_sold_it(self):
        self.assertEqual(self.found(code="356938035643809"), [self.sold["id"]])
        self.assertEqual(self.found(code="35693803564380"), [])          # 少一碼不算(完全相同才算)
        self.assertEqual(self.found(code="SNOTHER0001"), [])            # 還沒賣的那一台

    def test_a_returned_order_carries_the_return_number(self):
        rows = {o["id"]: o for o in self.c.clerk.get(URL).json()["results"]}
        self.assertEqual(rows[self.sold["id"]]["return_no"], "")
        sr = self.c._post(RETURNS, {"original_so": self.sold["id"], "payment_method": "cash"})
        rows = {o["id"]: o for o in self.c.clerk.get(URL).json()["results"]}
        self.assertEqual(rows[self.sold["id"]]["return_no"], sr["no"])
        self.assertEqual(rows[self.other["id"]]["return_no"], "")
        self.c.admin.post(f"{RETURNS}{sr['id']}/void/", {}, format="json")     # 作廢銷退:又是沒退過
        rows = {o["id"]: o for o in self.c.clerk.get(URL).json()["results"]}
        self.assertEqual(rows[self.sold["id"]]["return_no"], "")
