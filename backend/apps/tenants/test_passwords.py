"""帳號自己改密碼、老闆管店員帳號(owner 2026-10-19:「登入後沒有修改密碼的選項」;
紅隊之後選「一起做」老闆重設;「離職員工也要有移除的權限」)。

用真的登入拿 token(不用 force_authenticate):要驗的就是「改了之後別台的 token 失效」。
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.backup.models import TenantMaintenance
from apps.backup.tests.factory import Company
from apps.parties.models import SalesPerson

from .models import UserProfile

PW = "pw-12345"   # factory 建帳號用的密碼
MINE = "/api/v1/account/password/"
ME = "/api/v1/auth/me/"


def access(pk):
    return f"/api/v1/staff-accounts/{pk}/access/"


def signed_in(username, password=PW):
    """真的登入一次;回 (client, token)。登不進去回 (None, 狀態碼)。"""
    c = APIClient()
    r = c.post("/api/v1/auth/login/", {"username": username, "password": password}, format="json")
    if r.status_code != 200:
        return None, r.status_code
    token = r.json()["token"]
    c.credentials(HTTP_AUTHORIZATION=f"Token {token}")
    return c, token


def with_token(token):
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Token {token}")
    return c


class ChangeMyPasswordTests(TestCase):
    def setUp(self):
        self.c = Company("a", "甲通訊行", "甲")
        self.clerk, self.old_token = signed_in("a-clerk")

    def test_changing_it_signs_out_everywhere_else_and_keeps_this_one_going(self):
        other_device = with_token(self.old_token)
        r = self.clerk.post(MINE, {"current_password": PW, "new_password": "9876"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        new_token = r.json()["token"]
        self.assertNotEqual(new_token, self.old_token)
        self.assertEqual(other_device.get(ME).status_code, 401)          # 別台要重新登入
        self.assertEqual(with_token(new_token).get(ME).status_code, 200)  # 這一台拿新的繼續用
        self.assertEqual(signed_in("a-clerk")[1], 401)                    # 舊密碼登不進去
        self.assertIsNotNone(signed_in("a-clerk", "9876")[0])

    def test_wrong_current_password_is_refused_without_signing_out(self):
        r = self.clerk.post(MINE, {"current_password": "nope", "new_password": "9876"}, format="json")
        self.assertEqual(r.status_code, 400)                  # 不是 401:401 會讓畫面直接登出
        self.assertEqual(r.json()["detail"], "目前的密碼不對")
        self.assertEqual(self.clerk.get(ME).status_code, 200)
        self.assertIsNotNone(signed_in("a-clerk")[0])

    def test_too_short_or_the_same_is_refused(self):
        for new, why in [("123", "新密碼至少 4 碼"), (PW, "新密碼跟目前的一樣"), (None, "新密碼至少 4 碼"),
                         (" 9876 ", "密碼前後不能有空白")]:   # 登入會去掉前後空白,存了就登不進去
            r = self.clerk.post(MINE, {"current_password": PW, "new_password": new}, format="json")
            self.assertEqual((r.status_code, r.json()["detail"]), (400, why))
        self.assertEqual(self.clerk.get(ME).status_code, 200)

    def test_not_signed_in_cannot(self):
        r = APIClient().post(MINE, {"current_password": PW, "new_password": "9876"}, format="json")
        self.assertEqual(r.status_code, 401)

    def test_not_while_the_company_is_being_restored(self):
        TenantMaintenance.objects.create(tenant=self.c.tenant, active=True, reason="資料還原中")
        r = self.clerk.post(MINE, {"current_password": PW, "new_password": "9876"}, format="json")
        self.assertEqual(r.status_code, 503)
        self.assertTrue(get_user_model().objects.get(username="a-clerk").check_password(PW))


class BossManagesClerkTests(TestCase):
    def setUp(self):
        self.a = Company("a", "甲通訊行", "甲")
        self.b = Company("b", "乙通訊行", "乙")
        self.boss, _ = signed_in("a-boss")
        self.clerk, self.clerk_token = signed_in("a-clerk")
        self.clerk_id = self.a.clerk_user.id

    def test_reset_password_signs_the_clerk_out(self):
        r = self.boss.post(access(self.clerk_id), {"password": "5555"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self.clerk.get(ME).status_code, 401)
        self.assertEqual(signed_in("a-clerk")[1], 401)
        self.assertIsNotNone(signed_in("a-clerk", "5555")[0])

    def test_deactivate_then_activate(self):
        r = self.boss.post(access(self.clerk_id), {"is_active": False}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertFalse(r.json()["is_active"])
        self.assertEqual(self.clerk.get(ME).status_code, 401)            # 開著的畫面立刻失效
        self.assertIsNone(signed_in("a-clerk")[0])                       # 登不進去
        self.assertFalse(SalesPerson.objects.get(pk=self.a.sales_person.pk).is_active)  # 開單選不到他
        r = self.boss.post(access(self.clerk_id), {"is_active": True}, format="json")
        self.assertTrue(r.json()["is_active"])
        self.assertTrue(SalesPerson.objects.get(pk=self.a.sales_person.pk).is_active)
        self.assertIsNotNone(signed_in("a-clerk")[0])

    def test_only_the_bosses_own_clerks(self):
        clerk_says = self.clerk.post(access(self.clerk_id), {"is_active": False}, format="json")
        self.assertEqual(clerk_says.status_code, 403)
        other_company = self.boss.post(access(self.b.clerk_user.id), {"is_active": False}, format="json")
        self.assertEqual(other_company.status_code, 404)
        admin_account = self.boss.post(access(self.a.admin_user.id), {"password": "5555"}, format="json")
        self.assertEqual((admin_account.status_code, admin_account.json()["detail"]), (400, "管理員帳號請找平台"))
        b_clerk = get_user_model().objects.get(username="b-clerk")
        self.assertTrue(b_clerk.is_active and b_clerk.check_password(PW))
        self.assertTrue(get_user_model().objects.get(username="a-boss").check_password(PW))
        self.assertEqual(self.clerk.get(ME).status_code, 200)

    def test_bad_requests_change_nothing(self):
        for body in [{}, {"password": "5555", "is_active": False}, {"password": "12"}, {"password": "5555 "},
                     {"is_active": "no"}]:
            r = self.boss.post(access(self.clerk_id), body, format="json")
            self.assertEqual(r.status_code, 400, body)
        self.assertEqual(self.clerk.get(ME).status_code, 200)
        self.assertIsNotNone(signed_in("a-clerk")[0])


class PlatformResetTests(TestCase):
    def test_platform_reset_signs_the_account_out(self):
        a = Company("a", "甲通訊行", "甲")
        root = get_user_model().objects.create_user(username="root", password=PW)
        UserProfile.objects.create(user=root, role=UserProfile.Role.PLATFORM_ADMIN, tenant=None)
        platform, _ = signed_in("root")
        clerk, _ = signed_in("a-clerk")
        r = platform.post(f"/api/v1/platform/users/{a.clerk_user.id}/reset-password/", {"password": "7777"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(clerk.get(ME).status_code, 401)
        self.assertIsNotNone(signed_in("a-clerk", "7777")[0])
