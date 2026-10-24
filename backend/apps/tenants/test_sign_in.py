"""同一個帳號同一時間只能在一個位置登入(owner 2026-10-24:「同一時間只允許同一帳號登入一個位置,登入新位置,自動踢掉舊位置」)。

位置 = 一個瀏覽器(畫面送來的記號)。用真的登入拿 token(不用 force_authenticate):要驗的就是「換位置之後舊的 token 失效」。
"""
import threading
import time
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from apps.backup.tests.factory import Company

from .models import SignedOutElsewhere, SignInPlace
from .sign_in import ELSEWHERE_CODE, ELSEWHERE_TEXT, KEEP_DAYS, digest

PW = "pw-12345"   # factory 建帳號用的密碼
ME = "/api/v1/auth/me/"
SHOP = "shop-counter-0001-aaaa"
HOME = "home-desktop-0002-bbbb"
PHONE = "phone-0003-cccc-dddd"


def sign_in(username, device=None, password=PW):
    """真的登入一次;回 (client, token)。"""
    c = APIClient()
    body = {"username": username, "password": password}
    if device is not None:
        body["device"] = device
    r = c.post("/api/v1/auth/login/", body, format="json")
    assert r.status_code == 200, r.content
    token = r.json()["token"]
    c.credentials(HTTP_AUTHORIZATION=f"Token {token}")
    return c, token


class OnePlaceTests(TestCase):
    def setUp(self):
        self.c = Company("a", "甲通訊行", "甲")

    def assertSignedOutElsewhere(self, client):
        r = client.get(ME)
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json(), {"detail": ELSEWHERE_TEXT, "code": ELSEWHERE_CODE})

    def test_same_browser_signing_in_again_keeps_the_same_key(self):
        first, token = sign_in("a-clerk", SHOP)
        second, again = sign_in("a-clerk", SHOP)          # 同一個瀏覽器另開分頁、關掉再開
        self.assertEqual(token, again)
        self.assertEqual(first.get(ME).status_code, 200)   # 不會把自己踢掉
        self.assertEqual(second.get(ME).status_code, 200)
        self.assertFalse(SignedOutElsewhere.objects.exists())

    def test_signing_in_somewhere_else_signs_the_old_place_out(self):
        shop, token = sign_in("a-clerk", SHOP)
        home, new = sign_in("a-clerk", HOME)
        self.assertNotEqual(token, new)
        self.assertSignedOutElsewhere(shop)
        self.assertEqual(home.get(ME).status_code, 200)
        self.assertEqual(Token.objects.filter(user__username="a-clerk").count(), 1)

    def test_the_refused_request_does_nothing(self):
        shop, _ = sign_in("a-clerk", SHOP)
        sign_in("a-clerk", HOME)
        r = shop.post("/api/v1/account/password/", {"current_password": PW, "new_password": "9876"}, format="json")
        self.assertEqual(r.status_code, 401)
        self.assertTrue(get_user_model().objects.get(username="a-clerk").check_password(PW))

    def test_going_back_signs_the_other_one_out(self):
        shop, _ = sign_in("a-clerk", SHOP)
        home, _ = sign_in("a-clerk", HOME)
        shop_again, _ = sign_in("a-clerk", SHOP)
        self.assertSignedOutElsewhere(home)
        self.assertSignedOutElsewhere(shop)                # 第一次被踢的那一把也還認得出來
        self.assertEqual(shop_again.get(ME).status_code, 200)

    def test_without_a_mark_every_sign_in_counts_as_a_new_place(self):
        for bad in (None, "", "short", "has space in it 123456", 12345678901234567):
            with self.subTest(bad=bad):
                first, _ = sign_in("a-clerk", bad)
                second, _ = sign_in("a-clerk", bad)
                self.assertSignedOutElsewhere(first)
                self.assertEqual(second.get(ME).status_code, 200)

    def test_signing_out_is_not_called_elsewhere(self):
        shop, token = sign_in("a-clerk", SHOP)
        other_tab = APIClient()
        other_tab.credentials(HTTP_AUTHORIZATION=f"Token {token}")
        self.assertEqual(shop.post("/api/v1/auth/logout/").status_code, 200)
        r = other_tab.get(ME)
        self.assertEqual(r.status_code, 401)
        self.assertNotEqual(r.json().get("code"), ELSEWHERE_CODE)
        again, _ = sign_in("a-clerk", SHOP)
        self.assertEqual(again.get(ME).status_code, 200)

    def test_each_account_is_separate(self):
        boss, _ = sign_in("a-boss", SHOP)
        clerk_shop, _ = sign_in("a-clerk", SHOP)
        sign_in("a-clerk", PHONE)
        self.assertEqual(boss.get(ME).status_code, 200)
        self.assertSignedOutElsewhere(clerk_shop)

    def test_boss_has_no_exception(self):
        shop, _ = sign_in("a-boss", SHOP)
        sign_in("a-boss", PHONE)
        self.assertSignedOutElsewhere(shop)

    def test_a_key_from_before_this_rule_is_replaced_on_the_next_sign_in(self):
        user = get_user_model().objects.get(username="a-clerk")
        old = Token.objects.create(user=user)              # 上線之前就開著的畫面
        sign_in("a-clerk", SHOP)
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f"Token {old.key}")
        self.assertSignedOutElsewhere(c)

    def test_changing_the_password_keeps_this_place(self):
        shop, _ = sign_in("a-clerk", SHOP)
        r = shop.post("/api/v1/account/password/", {"current_password": PW, "new_password": "9876"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        new = r.json()["token"]
        _, again = sign_in("a-clerk", SHOP, password="9876")   # 同一個瀏覽器另一個分頁重新登入
        self.assertEqual(again, new)

    def test_only_the_digest_is_kept_and_old_ones_are_cleared(self):
        _, token = sign_in("a-clerk", SHOP)
        sign_in("a-clerk", HOME)
        row = SignedOutElsewhere.objects.get()
        self.assertEqual(row.digest, digest(token))
        self.assertNotIn(token, row.digest)
        SignedOutElsewhere.objects.update(at=timezone.now() - timedelta(days=KEEP_DAYS + 1))
        sign_in("a-clerk", SHOP)
        self.assertEqual(SignedOutElsewhere.objects.count(), 1)  # 舊的清掉,只剩剛剛被踢的 HOME
        self.assertEqual(SignInPlace.objects.get(user__username="a-clerk").device, SHOP)


class SameMomentTests(TransactionTestCase):
    """同一個帳號兩個地方同時按登入:一個一個來(兩條連線)。"""

    def test_a_sign_in_waits_while_the_account_is_being_signed_in_elsewhere(self):
        Company("a", "甲通訊行", "甲")
        user = get_user_model().objects.get(username="a-clerk")
        locked, release = threading.Event(), threading.Event()
        done = []

        def hold():
            try:
                with transaction.atomic():
                    get_user_model().objects.select_for_update().get(pk=user.pk)
                    locked.set()
                    release.wait(timeout=10)
            finally:
                connection.close()

        def go():
            try:
                r = APIClient().post(
                    "/api/v1/auth/login/", {"username": "a-clerk", "password": PW, "device": HOME}, format="json",
                )
                done.append(r.status_code)
            finally:
                connection.close()

        holder = threading.Thread(target=hold)
        holder.start()
        self.assertTrue(locked.wait(timeout=10))
        login = threading.Thread(target=go)
        login.start()
        time.sleep(0.5)
        self.assertEqual(done, [])                          # 等前一個做完
        release.set()
        holder.join(timeout=10)
        login.join(timeout=10)
        self.assertEqual(done, [200])

    def test_two_places_at_once_end_with_one_key(self):
        Company("a", "甲通訊行", "甲")
        gate = threading.Barrier(2)
        results = []

        def go(device):
            try:
                gate.wait(timeout=10)
                r = APIClient().post(
                    "/api/v1/auth/login/", {"username": "a-clerk", "password": PW, "device": device}, format="json",
                )
                results.append((r.status_code, r.json().get("token")))
            finally:
                connection.close()

        threads = [threading.Thread(target=go, args=(d,)) for d in (SHOP, HOME)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        self.assertEqual(sorted(code for code, _ in results), [200, 200], results)
        keys = list(Token.objects.filter(user__username="a-clerk").values_list("key", flat=True))
        self.assertEqual(len(keys), 1)
        self.assertIn(keys[0], [t for _, t in results])
