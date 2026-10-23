"""同一支電話好幾位會員(家人共用;全站檢視 E2):`?many=1` 每一位都回,最早建的在前;沒帶照舊回最早那一位。"""
from django.test import TestCase

from apps.backup.tests.factory import Company
from apps.parties.models import Member

URL = "/api/v1/members/lookup/"


class SharedPhoneLookupTests(TestCase):
    def setUp(self):
        self.c = Company("a", "甲通訊行", "甲")
        self.dad = Member.objects.create(tenant=self.c.tenant, name="王爸爸", phone="0911000111")
        self.kid = Member.objects.create(tenant=self.c.tenant, name="王小明", phone="0911000111")
        Member.objects.create(tenant=self.c.tenant, name="別人", phone="0922000222")
        other = Company("b", "乙通訊行", "乙")
        Member.objects.create(tenant=other.tenant, name="乙的客人", phone="0911000111")

    def test_many_returns_everyone_on_that_phone_of_this_company(self):
        r = self.c.clerk.get(URL, {"phone": "0911000111", "many": "1"})
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.assertEqual(r.json()["count"], 2)
        self.assertEqual([m["name"] for m in r.json()["results"]], ["王爸爸", "王小明"])

    def test_without_many_it_is_still_the_oldest_one(self):
        r = self.c.clerk.get(URL, {"phone": "0911000111"})
        self.assertEqual(r.json()["name"], "王爸爸")

    def test_nobody_is_an_empty_list_not_404(self):
        r = self.c.clerk.get(URL, {"phone": "0999999999", "many": "1"})
        self.assertEqual((r.status_code, r.json()["count"], r.json()["results"]), (200, 0, []))
        self.assertEqual(self.c.clerk.get(URL, {"phone": "0999999999"}).status_code, 404)
