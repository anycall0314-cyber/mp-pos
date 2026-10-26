"""身份別與員工帳號(owner 2026-10-27:「我要做身份別，比如管理者，店長，門市，行政（可自行添加刪除），或是針對特定帳號做權限調整」)。

帳號跟著身份別走:改身份別的勾選,那個身份的人一起變;帳號自己多開 / 多關的是例外。「管理者」= 公司管理員,固定全開。
管理員可以在這裡新增店員帳號、改名字 / 門市 / 鎖門市 / 身份別。
"""
import threading
from types import SimpleNamespace

from django.contrib.auth import authenticate, get_user_model
from django.db import connection
from django.test import SimpleTestCase, TestCase, TransactionTestCase

from apps.backup.tests.factory import Company
from apps.parties.models import SalesPerson

from . import abilities
from .models import StaffRole, UserProfile

ACCOUNTS = "/api/v1/staff-accounts/"
ROLES = "/api/v1/staff-roles/"
ALL = [a.key for a in abilities.ABILITIES]
DEFAULT = {k: k not in abilities.OPT_IN for k in ALL}


def clerk(role_off=None, extra=()):
    role = SimpleNamespace(denied_abilities=list(role_off)) if role_off is not None else None
    return SimpleNamespace(is_authenticated=True, profile=SimpleNamespace(
        role="tenant_user", staff_role=role, denied_abilities=list(extra)))


def old_switched_off(stored):
    """2026-10-27 以前的算法(沒有身份別):沒有身份別的帳號要算出一樣的結果。"""
    stored = [k for k in stored if isinstance(k, str)]
    granted = {k[1:] for k in stored if k.startswith("+")}
    return (set(stored) & abilities.KEYS) | (abilities.OPT_IN - granted)


class RuleTests(SimpleTestCase):
    def test_an_account_follows_its_role_plus_its_own_exceptions(self):
        someone = clerk(role_off=["void_sales", "void_purchase"])
        self.assertEqual(abilities.for_user(someone), {**DEFAULT, "void_sales": False, "void_purchase": False})
        someone = clerk(role_off=["void_sales", "void_purchase"], extra=["+void_sales", "sales_return"])
        self.assertEqual(abilities.for_user(someone), {**DEFAULT, "void_purchase": False, "sales_return": False})
        self.assertEqual(abilities.exceptions(someone.profile), ["void_sales", "sales_return"])
        # 預設不開的項目:身份別打開,帳號跟著開;帳號自己也可以多開
        self.assertTrue(abilities.can(clerk(role_off=["+remember_barcode"]), "remember_barcode"))
        self.assertTrue(abilities.can(clerk(role_off=[], extra=["+remember_barcode"]), "remember_barcode"))

    def test_both_marks_on_one_item_mean_off(self):
        self.assertFalse(abilities.can(clerk(role_off=[], extra=["void_sales", "+void_sales"]), "void_sales"))

    def test_without_a_role_it_is_exactly_the_old_rule(self):
        for stored in ([], ["void_sales"], ["+remember_barcode"], ["void_sales", "+remember_barcode", "gone"],
                       ["remember_barcode"], ["report_staff", "x", 7]):
            with self.subTest(stored=stored):
                self.assertEqual(abilities.switched_off(clerk(extra=stored).profile), old_switched_off(stored))

    def test_setting_an_item_back_to_the_role_value_drops_the_exception(self):
        profile = clerk(role_off=["void_sales"], extra=["+void_sales", "sales_return"]).profile
        self.assertEqual(abilities.change(profile, {"void_sales": False, "sales_return": True}), [])
        self.assertEqual(abilities.change(profile, {"void_purchase": False}), ["sales_return", "void_purchase", "+void_sales"])

    def test_changing_the_role_clears_exceptions_but_keeps_unknown_old_items(self):
        self.assertEqual(abilities.leftovers(["void_sales", "+remember_barcode", "gone", "+gone2", 7]), ["+gone2", "gone"])

    def test_role_settings_only_record_what_differs_from_the_default(self):
        role = SimpleNamespace(denied_abilities=["void_sales"])
        self.assertEqual(abilities.change_role(role, {"void_sales": True, "remember_barcode": True, "sales_return": False}),
                         ["sales_return", "+remember_barcode"])
        self.assertEqual(abilities.change_role(role, {"remember_barcode": False}), ["void_sales"])


class _Shop(TestCase):
    def setUp(self):
        self.c = Company("A", "甲公司", "甲")
        self.other = Company("B", "乙公司", "乙")
        self.store_role = StaffRole.objects.create(tenant=self.c.tenant, name="門市", denied_abilities=[])
        self.head_role = StaffRole.objects.create(tenant=self.c.tenant, name="店長", denied_abilities=[])
        UserProfile.objects.filter(user=self.c.clerk_user).update(staff_role=self.store_role)
        self.one = f"{ACCOUNTS}{self.c.clerk_user.id}/"

    def fresh(self, user=None):
        """每次重新讀帳號(真的請求每次都從資料庫讀;測試裡同一個物件會留著舊的身份別)。"""
        return Company.client(get_user_model().objects.get(pk=(user or self.c.clerk_user).pk))

    def me(self, user=None):
        return self.fresh(user).get("/api/v1/auth/me/").json()["abilities"]

    def profile(self, user=None):
        return UserProfile.objects.get(user=user or self.c.clerk_user)


class RoleTests(_Shop):
    def test_changing_a_role_changes_everyone_in_it(self):
        r = self.c.admin.patch(f"{ROLES}{self.store_role.id}/", {"abilities": {"void_sales": False}}, format="json")
        self.assertEqual((r.status_code, r.json()["abilities"]["void_sales"], r.json()["accounts"]), (200, False, 1))
        self.assertFalse(self.me()["void_sales"])
        so_void = self.fresh().post("/api/v1/sales-orders/999999/void/", {}, format="json")
        self.assertEqual(so_void.status_code, 403, so_void.content)
        self.c.admin.patch(f"{ROLES}{self.store_role.id}/", {"abilities": {"void_sales": True}}, format="json")
        self.assertTrue(self.me()["void_sales"])

    def test_an_account_exception_beats_its_role(self):
        self.c.admin.patch(f"{ROLES}{self.store_role.id}/", {"abilities": {"void_sales": False}}, format="json")
        r = self.c.admin.patch(self.one, {"abilities": {"void_sales": True}}, format="json")
        self.assertEqual((r.status_code, r.json()["exceptions"], r.json()["abilities"]["void_sales"]), (200, ["void_sales"], True))
        self.assertTrue(self.me()["void_sales"])
        # 回到身份別:送跟身份別一樣的值,例外就沒了
        r = self.c.admin.patch(self.one, {"abilities": {"void_sales": False}}, format="json")
        self.assertEqual((r.json()["exceptions"], self.profile().denied_abilities), ([], []))

    def test_create_copy_rename_and_delete(self):
        self.c.admin.patch(f"{ROLES}{self.store_role.id}/", {"abilities": {"void_sales": False}}, format="json")
        r = self.c.admin.post(ROLES, {"name": " 行政 ", "copy_from": self.store_role.id,
                                      "abilities": {"purchase": False}}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        made = StaffRole.objects.get(pk=r.json()["id"])
        self.assertEqual((made.name, made.denied_abilities, made.tenant_id), ("行政", ["void_sales", "purchase"], self.c.tenant.id))
        for bad, why in ((" ", "身份別名稱要填"), ("門市", "已經有「門市」了"), ("管理者", "「管理者」是固定的,換一個名稱"),
                         ("名" * 21, "身份別名稱最多 20 個字")):
            r = self.c.admin.post(ROLES, {"name": bad}, format="json")
            self.assertEqual((r.status_code, r.json()), (400, {"detail": why}))
        r = self.c.admin.patch(f"{ROLES}{made.id}/", {"name": "店長"}, format="json")
        self.assertEqual((r.status_code, r.json()), (400, {"detail": "已經有「店長」了"}))
        r = self.c.admin.patch(f"{ROLES}{made.id}/", {"name": "會計"}, format="json")
        self.assertEqual((r.status_code, r.json()["name"]), (200, "會計"))
        self.assertEqual(self.c.admin.delete(f"{ROLES}{made.id}/").status_code, 204)
        self.assertFalse(StaffRole.objects.filter(pk=made.id).exists())

    def test_a_role_in_use_cannot_be_deleted(self):
        r = self.c.admin.delete(f"{ROLES}{self.store_role.id}/")
        self.assertEqual((r.status_code, r.json()), (400, {"detail": "還有 1 個帳號是「門市」,先把他們換成別的身份別"}))
        self.assertTrue(StaffRole.objects.filter(pk=self.store_role.id).exists())

    def test_only_managers_of_that_company(self):
        self.assertEqual(self.c.clerk.post(ROLES, {"name": "x"}, format="json").status_code, 403)
        self.assertEqual(self.c.clerk.patch(f"{ROLES}{self.head_role.id}/", {"name": "x"}, format="json").status_code, 403)
        self.assertEqual(self.c.clerk.delete(f"{ROLES}{self.head_role.id}/").status_code, 403)
        self.assertEqual(self.other.admin.patch(f"{ROLES}{self.head_role.id}/", {"name": "x"}, format="json").status_code, 404)
        self.assertEqual(self.other.admin.delete(f"{ROLES}{self.head_role.id}/").status_code, 404)
        r = self.other.admin.post(ROLES, {"name": "y", "copy_from": self.head_role.id}, format="json")
        self.assertEqual((r.status_code, r.json()), (400, {"detail": "找不到要照的身份別"}))
        self.assertEqual(StaffRole.objects.get(pk=self.head_role.id).name, "店長")
        self.assertEqual(StaffRole.objects.filter(tenant=self.c.tenant).count(), 2)

    def test_explore_still_needs_its_reports(self):
        r = self.c.admin.patch(f"{ROLES}{self.store_role.id}/", {"abilities": {"report_staff": False}}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(self.me()["report_explore"])
        r = self.c.admin.patch(f"{ROLES}{self.store_role.id}/", {"abilities": {"report_explore": True}}, format="json")
        self.assertEqual((r.status_code, r.json()), (400, {"detail": "「自訂分析」要先開:業績彙總"}))


class AccountTests(_Shop):
    def test_the_page_lists_roles_accounts_and_the_next_account_name(self):
        r = self.c.admin.get(ACCOUNTS)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual([(x["name"], x["accounts"]) for x in body["roles"]], [("門市", 1), ("店長", 0)])
        mine = next(a for a in body["accounts"] if a["id"] == self.c.clerk_user.id)
        self.assertEqual((mine["staff_role"], mine["exceptions"], mine["own"]),
                         ({"id": self.store_role.id, "name": "門市"}, [], DEFAULT))
        boss = next(a for a in body["accounts"] if a["id"] == self.c.admin_user.id)
        self.assertEqual((boss["staff_role"], boss["editable"]), (None, False))
        self.assertEqual(body["next_username"], "A001")
        self.assertEqual(next(i for i in body["abilities"] if i["key"] == "report_explore")["needs"],
                         list(abilities.ALSO_NEEDS["report_explore"]))

    def test_a_manager_adds_a_clerk_with_a_role_and_a_sales_person(self):
        r = self.c.admin.post(ACCOUNTS, {
            "username": "A002", "name": " 王小明 ", "password": "pw-12345",
            "warehouse": self.c.wh.id, "warehouse_locked": True, "staff_role": self.head_role.id,
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual((r.json()["name"], r.json()["staff_role"]["name"], r.json()["warehouse_locked"]), ("王小明", "店長", True))
        p = UserProfile.objects.get(user__username="A002")
        self.assertEqual((p.tenant_id, p.role, p.default_warehouse_id, p.staff_role_id, p.denied_abilities),
                         (self.c.tenant.id, "tenant_user", self.c.wh.id, self.head_role.id, []))
        sp = SalesPerson.objects.get(user=p.user)
        self.assertEqual((sp.tenant_id, sp.code, sp.name), (self.c.tenant.id, "A002", "王小明"))
        self.assertIsNotNone(authenticate(username="A002", password="pw-12345"))
        self.assertEqual(self.c.admin.get(ACCOUNTS).json()["next_username"], "A003")

    def test_a_new_account_can_start_with_exceptions(self):
        self.c.admin.patch(f"{ROLES}{self.store_role.id}/", {"abilities": {"void_sales": False}}, format="json")
        r = self.c.admin.post(ACCOUNTS, {"username": "A003", "name": "小美", "password": "pw-12345",
                                         "staff_role": self.store_role.id,
                                         "abilities": {"void_sales": True, "purchase": False, "sales_return": True}},
                              format="json")
        self.assertEqual((r.status_code, r.json()["exceptions"]), (201, ["void_sales", "purchase"]), r.content)
        self.assertEqual(UserProfile.objects.get(user__username="A003").denied_abilities, ["purchase", "+void_sales"])
        r = self.c.admin.post(ACCOUNTS, {"username": "A004", "name": "小莉", "password": "pw-12345",
                                         "staff_role": self.store_role.id,
                                         "abilities": {"report_staff": False, "report_explore": True}}, format="json")
        self.assertEqual((r.status_code, r.json()), (400, {"detail": "「自訂分析」要先開:業績彙總"}))
        self.assertFalse(get_user_model().objects.filter(username="A004").exists())

    def test_bad_new_accounts_are_refused(self):
        good = {"username": "A009", "name": "小華", "password": "pw-12345", "staff_role": self.store_role.id}
        cases = [
            ({"username": ""}, "帳號要填"),
            ({"username": "a b"}, "帳號只能用英文、數字和 @ . + - _"),
            ({"username": self.c.clerk_user.username.upper()}, f"帳號 {self.c.clerk_user.username.upper()} 已經有人用了"),
            ({"username": "s1"}, "業務員代號 s1 已經有人用了,換一個帳號"),
            ({"name": "  "}, "名字要填"),
            ({"password": "1"}, None),
            ({"warehouse": self.other.wh.id}, "找不到這間門市"),
            ({"warehouse_locked": True}, "鎖在門市要先選門市"),
            ({"staff_role": None}, "要選身份別"),
            ({"staff_role": StaffRole.objects.create(tenant=self.other.tenant, name="門市").id}, "找不到這個身份別"),
        ]
        for change, why in cases:
            with self.subTest(change=change):
                r = self.c.admin.post(ACCOUNTS, {**good, **change}, format="json")
                self.assertEqual(r.status_code, 400, r.content)
                if why:
                    self.assertEqual(r.json(), {"detail": why})
        self.assertFalse(UserProfile.objects.filter(user__username="A009").exists())
        self.assertEqual(self.c.clerk.post(ACCOUNTS, good, format="json").status_code, 403)
        self.assertFalse(UserProfile.objects.filter(user__username="A009").exists())

    def test_rename_move_and_lock(self):
        r = self.c.admin.patch(self.one, {"name": "陳大文", "warehouse": self.c.warehouses[1].id,
                                          "warehouse_locked": False}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        p = self.profile()
        self.assertEqual((p.default_warehouse_id, p.is_warehouse_locked), (self.c.warehouses[1].id, False))
        self.assertEqual(SalesPerson.objects.get(user=self.c.clerk_user).name, "陳大文")
        self.assertEqual(r.json()["name"], "陳大文")
        r = self.c.admin.patch(self.one, {"warehouse": None, "warehouse_locked": True}, format="json")
        self.assertEqual((r.status_code, r.json()), (400, {"detail": "鎖在門市要先選門市"}))
        self.assertEqual(self.profile().default_warehouse_id, self.c.warehouses[1].id)     # 被退回的那次什麼都沒存
        r = self.c.admin.patch(self.one, {"warehouse": self.other.wh.id}, format="json")
        self.assertEqual((r.status_code, r.json()), (400, {"detail": "找不到這間門市"}))

    def test_switching_role_follows_the_new_role_and_takes_new_exceptions(self):
        self.c.admin.patch(f"{ROLES}{self.head_role.id}/", {"abilities": {"purchase": False}}, format="json")
        self.c.admin.patch(self.one, {"abilities": {"void_sales": False}}, format="json")
        self.assertEqual(self.profile().denied_abilities, ["void_sales"])
        # 只換身份別:例外清掉,完全照店長(進貨入庫關、作廢銷貨單開)
        r = self.c.admin.patch(self.one, {"staff_role": self.head_role.id}, format="json")
        self.assertEqual((r.status_code, r.json()["staff_role"]["name"], r.json()["exceptions"]), (200, "店長", []))
        self.assertEqual((self.me()["void_sales"], self.me()["purchase"]), (True, False))
        # 換身份別同一次送例外:跟新身份別比,不一樣的才記
        r = self.c.admin.patch(self.one, {"staff_role": self.store_role.id,
                                          "abilities": {"void_sales": False, "purchase": True}}, format="json")
        self.assertEqual((r.json()["exceptions"], self.profile().denied_abilities), (["void_sales"], ["void_sales"]))
        self.assertEqual((self.me()["void_sales"], self.me()["purchase"]), (False, True))
        # 換成同一個身份別不算換:例外不動
        r = self.c.admin.patch(self.one, {"staff_role": self.store_role.id}, format="json")
        self.assertEqual(r.json()["exceptions"], ["void_sales"])

    def test_manager_accounts_and_other_companies_are_off_limits(self):
        boss = f"{ACCOUNTS}{self.c.admin_user.id}/"
        r = self.c.admin.patch(boss, {"name": "x"}, format="json")
        self.assertEqual((r.status_code, r.json()), (400, {"detail": "管理員帳號永遠全開,不能在這裡改"}))
        self.assertEqual(self.other.admin.patch(self.one, {"name": "x"}, format="json").status_code, 404)
        r = self.c.admin.patch(self.one, {"staff_role": StaffRole.objects.create(tenant=self.other.tenant, name="店長").id},
                               format="json")
        self.assertEqual((r.status_code, r.json()), (400, {"detail": "找不到這個身份別"}))
        self.assertEqual(self.c.clerk.patch(self.one, {"name": "x"}, format="json").status_code, 403)
        self.assertEqual(self.profile().staff_role_id, self.store_role.id)


class RoleDeleteRaceTests(TransactionTestCase):
    """刪身份別與把帳號換成那個身份別同時發生:不能 500,也不能留下指到不存在身份別的帳號。"""

    def test_delete_and_assign_at_the_same_time(self):
        c = Company("A", "甲公司", "甲")
        keep = StaffRole.objects.create(tenant=c.tenant, name="門市")
        doomed = StaffRole.objects.create(tenant=c.tenant, name="行政")
        UserProfile.objects.filter(user=c.clerk_user).update(staff_role=keep)
        gate = threading.Barrier(2)
        results = {}

        def run(name, call):
            try:
                gate.wait()
                results[name] = call().status_code
            finally:
                connection.close()

        threads = [
            threading.Thread(target=run, args=("assign", lambda: Company.client(c.admin_user).patch(
                f"{ACCOUNTS}{c.clerk_user.id}/", {"staff_role": doomed.id}, format="json"))),
            threading.Thread(target=run, args=("delete", lambda: Company.client(c.admin_user).delete(
                f"{ROLES}{doomed.id}/"))),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertIn((results["assign"], results["delete"]), {(200, 400), (400, 204)}, results)
        profile = UserProfile.objects.get(user=c.clerk_user)
        if results["delete"] == 204:
            self.assertEqual(profile.staff_role_id, keep.id)
        else:
            self.assertEqual(profile.staff_role_id, doomed.id)


class PlatformCreatedTests(TestCase):
    def test_a_clerk_made_in_the_platform_gets_the_most_used_role(self):
        from apps.tenants.services import first_staff_role

        c = Company("A", "甲公司", "甲")
        head = StaffRole.objects.create(tenant=c.tenant, name="店長")
        store = StaffRole.objects.create(tenant=c.tenant, name="門市")
        self.assertEqual(first_staff_role(c.tenant), head)            # 都沒人用:先建的
        UserProfile.objects.filter(user=c.clerk_user).update(staff_role=store)
        UserProfile.objects.filter(user=c.admin_user).update(staff_role=head)   # 管理員不算
        self.assertEqual(first_staff_role(c.tenant), store)
        self.assertIsNone(first_staff_role(None))

    def test_moving_a_clerk_to_another_company_drops_the_old_exceptions(self):
        """複審 2026-10-27:平台把帳號換到別家公司,舊公司給的「多開」不能帶過去。"""
        a, b = Company("A", "甲公司", "甲"), Company("B", "乙公司", "乙")
        a_role = StaffRole.objects.create(tenant=a.tenant, name="門市", denied_abilities=["void_sales"])
        b_role = StaffRole.objects.create(tenant=b.tenant, name="門市", denied_abilities=["void_sales"])
        UserProfile.objects.filter(user=a.clerk_user).update(staff_role=a_role, denied_abilities=["+void_sales"])
        platform = get_user_model().objects.create_user(username="plat", password="pw-12345")
        UserProfile.objects.create(user=platform, role="platform_admin", tenant=None, is_warehouse_locked=False)
        r = Company.client(platform).patch(f"/api/v1/platform/users/{a.clerk_user.id}/",
                                           {"tenant": b.tenant.id, "default_warehouse": b.wh.id}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        p = UserProfile.objects.get(user=a.clerk_user)
        self.assertEqual((p.tenant_id, p.staff_role_id, p.denied_abilities), (b.tenant.id, b_role.id, []))
        self.assertFalse(abilities.can(get_user_model().objects.get(pk=a.clerk_user.pk), "void_sales"))
