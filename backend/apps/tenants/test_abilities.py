"""員工帳號的權限:每個店員帳號一項一項勾(owner 2026-10-10)。第一批:作廢與銷退。

預設全開(跟以前一樣);管理員永遠全開;關掉的動作伺服器回 403、什麼都不會變。
"""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase, TestCase

from apps.backup.tests.factory import Company
from apps.cash.models import CashAdjustment, PettyExpense, PhoneBillCollection
from apps.inventory.models import StockBalance
from apps.parties.models import Carrier
from apps.purchasing.models import PurchaseOrder
from apps.repairs.models import RepairOrder
from apps.sales.models import SalesOrder, SalesReturn
from apps.transfers.models import TransferOrder

from . import abilities
from .models import UserProfile

ACCOUNTS = "/api/v1/staff-accounts/"
ALL = [a.key for a in abilities.ABILITIES]


def someone(role="tenant_user", off=()):
    return SimpleNamespace(is_authenticated=True, profile=SimpleNamespace(role=role, denied_abilities=list(off)))


class RuleTests(SimpleTestCase):
    def test_everything_is_allowed_until_something_is_turned_off(self):
        clerk = someone()
        self.assertEqual(abilities.for_user(clerk), {k: True for k in ALL})
        clerk = someone(off=["void_sales"])
        self.assertFalse(abilities.can(clerk, "void_sales"))
        self.assertTrue(abilities.can(clerk, "sales_return"))
        self.assertEqual(abilities.for_user(clerk), {**{k: True for k in ALL}, "void_sales": False})

    def test_managers_always_can(self):
        for role in ("tenant_admin", "platform_admin"):
            boss = someone(role, off=ALL)
            self.assertEqual(abilities.for_user(boss), {k: True for k in ALL})
            abilities.require(boss, "void_sales")          # 不會丟

    def test_require_says_which_and_where_to_turn_it_on(self):
        with self.assertRaises(abilities.PermissionDenied) as caught:
            abilities.require(someone(off=["void_purchase"]), "void_purchase")
        self.assertIn("作廢進貨單", str(caught.exception.detail))
        self.assertIn("員工帳號", str(caught.exception.detail))

    def test_a_misspelt_item_is_an_error_not_a_yes(self):
        with self.assertRaises(KeyError):
            abilities.can(someone(), "void_sale")
        with self.assertRaises(KeyError):
            abilities.require(someone(), "anything")

    def test_odd_things_in_the_stored_list_are_ignored(self):
        clerk = someone(off=["void_sales", "gone_item", 7, None, ["void_purchase"]])
        self.assertEqual(abilities.denied(clerk), {"void_sales"})
        self.assertEqual(abilities.denied(SimpleNamespace(is_authenticated=True)), set())      # 沒有帳號設定

    def test_changing_touches_only_what_was_sent(self):
        profile = SimpleNamespace(denied_abilities=["void_purchase", "old_item"])
        self.assertEqual(abilities.change(profile, {"void_sales": False}), ["void_sales", "void_purchase", "old_item"])
        self.assertEqual(abilities.change(profile, {"void_purchase": True}), ["old_item"])       # 清單裡沒有的舊項目留著
        self.assertEqual(abilities.change(profile, {"void_purchase": False}), ["void_purchase", "old_item"])   # 不會重複
        self.assertEqual(abilities.change(SimpleNamespace(denied_abilities=None), {"sales_return": True}), [])

    def test_names_in_one_group_are_the_same_length(self):
        for group in {a.group for a in abilities.ABILITIES}:
            self.assertEqual(len({len(a.label) for a in abilities.ABILITIES if a.group == group}), 1, group)
        self.assertEqual(len(abilities.KEYS), len(abilities.ABILITIES))


class _Shop(TestCase):
    def setUp(self):
        self.c = Company("a", "甲通訊行", "甲")
        self.t = self.c.tenant
        self.clerk = self.c.clerk_user

    def turn_off(self, *keys, user=None):
        UserProfile.objects.filter(user=user or self.clerk).update(denied_abilities=list(keys))
        (user or self.clerk).profile.refresh_from_db()      # 測試用的連線一直拿著同一個帳號物件;正式環境每個請求重新讀

    def off(self):
        return UserProfile.objects.get(user=self.clerk).denied_abilities


class AccountPageTests(_Shop):
    def test_only_managers_see_the_page(self):
        self.assertEqual(self.c.clerk.get(ACCOUNTS).status_code, 403)
        r = self.c.admin.get(ACCOUNTS)
        self.assertEqual(r.status_code, 200, r.content.decode())
        body = r.json()
        self.assertEqual([a["key"] for a in body["abilities"]], ALL)
        self.assertEqual({a["group"] for a in body["abilities"]}, {"作廢與銷退"})
        rows = {a["username"]: a for a in body["accounts"]}
        self.assertEqual(set(rows), {"a-boss", "a-clerk"})
        self.assertEqual((rows["a-clerk"]["editable"], rows["a-boss"]["editable"]), (True, False))
        self.assertEqual(rows["a-clerk"]["abilities"], {k: True for k in ALL})          # 預設全開
        self.assertEqual(rows["a-clerk"]["warehouse"], f"{self.c.wh.code} {self.c.wh.name}")
        self.assertEqual(rows["a-clerk"]["name"], "甲店員")

    def test_a_manager_turns_items_off_and_on(self):
        one = f"{ACCOUNTS}{self.clerk.id}/"
        r = self.c.admin.patch(one, {"abilities": {"void_sales": False}}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.assertEqual(r.json()["abilities"], {**{k: True for k in ALL}, "void_sales": False})
        self.assertEqual(self.off(), ["void_sales"])
        self.c.admin.patch(one, {"abilities": {"sales_return": False}}, format="json")        # 別的項目不動
        self.assertEqual(self.off(), ["void_sales", "sales_return"])
        self.c.admin.patch(one, {"abilities": {"void_sales": True, "void_others": False}}, format="json")
        self.assertEqual(self.off(), ["sales_return", "void_others"])
        rows = {a["username"]: a for a in self.c.admin.get(ACCOUNTS).json()["accounts"]}
        self.assertEqual(rows["a-clerk"]["abilities"]["sales_return"], False)

    def test_a_clerk_cannot_change_anything_not_even_their_own(self):
        self.turn_off("void_sales")
        r = self.c.clerk.patch(f"{ACCOUNTS}{self.clerk.id}/", {"abilities": {"void_sales": True}}, format="json")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.off(), ["void_sales"])

    def test_bad_requests_change_nothing(self):
        self.turn_off("void_sales")
        one = f"{ACCOUNTS}{self.clerk.id}/"
        for body in ({}, {"abilities": {}}, {"abilities": ["void_sales"]}, {"abilities": {"no_such": False}},
                     {"abilities": {"void_sales": "false"}}, {"abilities": {"void_sales": 0}},
                     {"abilities": {"void_sales": True, "no_such": False}}):
            r = self.c.admin.patch(one, body, format="json")
            self.assertEqual(r.status_code, 400, (body, r.content.decode()))
            self.assertEqual(self.off(), ["void_sales"], body)

    def test_managers_are_always_on_and_cannot_be_turned_off_here(self):
        r = self.c.admin.patch(f"{ACCOUNTS}{self.c.admin_user.id}/", {"abilities": {"void_sales": False}}, format="json")
        self.assertEqual(r.status_code, 400, r.content.decode())
        self.assertEqual(UserProfile.objects.get(user=self.c.admin_user).denied_abilities, [])

    def test_another_companys_accounts_are_out_of_reach(self):
        b = Company("b", "乙通訊行", "乙")
        r = self.c.admin.patch(f"{ACCOUNTS}{b.clerk_user.id}/", {"abilities": {"void_sales": False}}, format="json")
        self.assertEqual(r.status_code, 404, r.content.decode())
        self.assertEqual(UserProfile.objects.get(user=b.clerk_user).denied_abilities, [])
        self.assertEqual({a["username"] for a in self.c.admin.get(ACCOUNTS).json()["accounts"]}, {"a-boss", "a-clerk"})
        self.assertEqual(self.c.admin.patch(f"{ACCOUNTS}999999/", {"abilities": {"void_sales": False}},
                                            format="json").status_code, 404)

    def test_the_login_data_carries_what_this_account_can_do(self):
        self.turn_off("void_sales", "void_others")
        me = self.c.clerk.get("/api/v1/auth/me/").json()
        self.assertEqual(me["abilities"], {"void_sales": False, "sales_return": True, "void_purchase": True,
                                           "void_others": False})
        self.turn_off(*ALL, user=self.c.admin_user)                 # 管理員身上就算有,也不算
        self.assertEqual(self.c.admin.get("/api/v1/auth/me/").json()["abilities"], {k: True for k in ALL})


class BlockingTests(_Shop):
    """每一種作廢 / 銷退:關掉的店員被擋(403、什麼都沒變);沒關的照舊;管理員不受影響。"""

    def setUp(self):
        super().setUp()
        self.c.purchase(case_qty=9)
        self.w2 = self.c.warehouses[1]

    def blocked(self, r, label):
        self.assertEqual(r.status_code, 403, r.content.decode())
        self.assertIn(label, r.json()["detail"])

    def stock(self, wh=None):
        return StockBalance.objects.get(tenant=self.t, product=self.c.case, warehouse=wh or self.c.wh).qty

    def test_voiding_a_sale(self):
        so = self.c.sell(case_qty=2)
        url = f"/api/v1/sales-orders/{so['id']}/void/"
        self.turn_off("void_sales")
        self.blocked(self.c.clerk.post(url, {}, format="json"), "作廢銷貨單")
        self.assertFalse(SalesOrder.objects.get(pk=so["id"]).is_void)
        self.assertEqual(self.stock(), 7)
        self.turn_off("sales_return", "void_purchase", "void_others")       # 關的是別項:照舊可以
        self.assertEqual(self.c.clerk.post(url, {}, format="json").status_code, 200)
        self.assertTrue(SalesOrder.objects.get(pk=so["id"]).is_void)
        self.assertEqual(self.stock(), 9)

    def test_a_manager_is_never_blocked(self):
        so = self.c.sell(case_qty=1)
        self.turn_off(*ALL, user=self.c.admin_user)
        self.assertEqual(self.c.admin.post(f"/api/v1/sales-orders/{so['id']}/void/", {}, format="json").status_code, 200)

    def test_returning_a_sale_and_voiding_the_return(self):
        so = self.c.sell(case_qty=2)
        body = {"original_so": so["id"], "payment_method": "cash"}
        self.turn_off("sales_return")
        self.blocked(self.c.clerk.post("/api/v1/sales-returns/", body, format="json"), "開立銷退單")
        # 沒有權限的先擋,連送來的內容都不看(不讓人靠錯誤訊息探別的單)
        self.blocked(self.c.clerk.post("/api/v1/sales-returns/", {"original_so": 999999}, format="json"), "開立銷退單")
        self.assertFalse(SalesReturn.objects.filter(tenant=self.t).exists())
        self.assertEqual(self.stock(), 7)
        self.turn_off("void_sales")
        r = self.c.clerk.post("/api/v1/sales-returns/", body, format="json")
        self.assertEqual(r.status_code, 201, r.content.decode())
        self.assertEqual(self.stock(), 9)
        void = f"/api/v1/sales-returns/{r.json()['id']}/void/"
        self.turn_off("sales_return")
        self.blocked(self.c.clerk.post(void, {}, format="json"), "開立銷退單")
        self.assertFalse(SalesReturn.objects.get(pk=r.json()["id"]).is_void)
        self.turn_off()
        self.assertEqual(self.c.clerk.post(void, {}, format="json").status_code, 200)
        self.assertEqual(self.stock(), 7)

    def test_voiding_a_purchase(self):
        po = self.c.purchase(case_qty=3)
        url = f"/api/v1/purchase-orders/{po['id']}/void/"
        self.turn_off("void_purchase")
        self.blocked(self.c.clerk.post(url, {}, format="json"), "作廢進貨單")
        self.assertFalse(PurchaseOrder.objects.get(pk=po["id"]).is_void)
        self.assertEqual(self.stock(), 12)
        self.turn_off("void_sales", "sales_return", "void_others")
        self.assertEqual(self.c.clerk.post(url, {}, format="json").status_code, 200)
        self.assertEqual(self.stock(), 9)

    def test_voiding_the_other_documents(self):
        """調撥、維修、雜支、現金調整、代收話費:同一個勾。"""
        transfer = self.c._post("/api/v1/transfer-orders/", {
            "from_warehouse": self.c.wh.id, "to_warehouse": self.w2.id, "items": [{"product": self.c.case.id, "qty": 2}]})
        repair = self.c._post("/api/v1/repair-orders/", {
            "warehouse": self.c.wh.id, "customer": self.c.customer.id, "received_date": str(date.today()),
            "mode": "in_house", "unlock_method": "none", "host_model_name": "iPhone 15"})
        expense = PettyExpense.objects.create(tenant=self.t, warehouse=self.c.wh, amount=Decimal("100"),
                                              payment_method=self.c.cash)
        adjust = CashAdjustment.objects.create(tenant=self.t, warehouse=self.c.wh, amount=Decimal("50"))
        carrier = Carrier.objects.create(tenant=self.t, code="CHT", name="中華電信")
        bill = PhoneBillCollection.objects.create(tenant=self.t, warehouse=self.c.wh, carrier=carrier, phone_no="0912345678",
                                                  amount=Decimal("999"), id_no="A123456789", handled_by=self.c.sales_person)
        docs = [
            (f"/api/v1/transfer-orders/{transfer['id']}/void/", TransferOrder, transfer["id"]),
            (f"/api/v1/repair-orders/{repair['id']}/void/", RepairOrder, repair["id"]),
            (f"/api/v1/petty-expenses/{expense.id}/void/", PettyExpense, expense.id),
            (f"/api/v1/cash-adjustments/{adjust.id}/void/", CashAdjustment, adjust.id),
            (f"/api/v1/phone-bills/{bill.id}/void/", PhoneBillCollection, bill.id),
        ]

        def voided(model, pk):
            row = model.objects.get(pk=pk)
            return row.is_void if hasattr(row, "is_void") else row.status == "void"

        self.turn_off("void_others")
        for url, model, pk in docs:
            self.blocked(self.c.clerk.post(url, {}, format="json"), "作廢其他單")
            self.assertFalse(voided(model, pk), url)
        # 複審抓到的:雜支、現金調整、代收話費原本還能直接刪掉(比作廢更徹底、不留紀錄)—— 不能拿刪除繞過去。
        # 這三種單現在誰都不能刪(包括管理員、包括沒被關掉的店員),只能作廢
        for url, model, pk in docs[2:]:
            one = url.replace("void/", "")
            for client in (self.c.clerk, self.c.admin):
                r = client.delete(one)
                self.assertEqual(r.status_code, 405, (one, r.content.decode()))
                self.assertIn("請用作廢", r.json()["detail"])
            self.assertTrue(model.objects.filter(pk=pk).exists(), one)
            self.assertFalse(voided(model, pk), one)
        for url, model, pk in docs[:2]:                             # 調撥、維修本來就不能刪
            self.assertIn(self.c.clerk.delete(url.replace("void/", "")).status_code, (400, 405))
            self.assertTrue(model.objects.filter(pk=pk).exists())
        self.assertEqual(self.stock(), 7)                          # 調撥派出去的 2 個沒有被退回來
        self.turn_off("void_sales", "sales_return", "void_purchase")
        for url, model, pk in docs:
            r = self.c.clerk.post(url, {}, format="json")
            self.assertEqual(r.status_code, 200, (url, r.content.decode()))
            self.assertTrue(voided(model, pk), url)
        self.assertEqual(self.stock(), 9)

    def test_the_void_flag_cannot_be_set_by_editing(self):
        """被關掉的人不能靠「編輯」把單改成作廢(那一格只有作廢的動作能動)。"""
        expense = PettyExpense.objects.create(tenant=self.t, warehouse=self.c.wh, amount=Decimal("100"),
                                              payment_method=self.c.cash)
        self.turn_off("void_others")
        r = self.c.clerk.patch(f"/api/v1/petty-expenses/{expense.id}/", {"is_void": True, "note": "改備註"}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        expense.refresh_from_db()
        self.assertEqual((expense.is_void, expense.note), (False, "改備註"))

    def test_everything_else_is_untouched(self):
        """關掉全部四項的店員:開單、看單照舊。"""
        self.turn_off(*ALL)
        r = self.c.clerk.post("/api/v1/sales-orders/", {
            "customer": self.c.customer.id, "warehouse": self.c.wh.id, "tax_method": "untaxed",
            "items": [{"product": self.c.case.id, "qty": 1, "unit_price": "390"}],
            "payments": [{"method": "cash", "amount": "390"}]}, format="json")
        self.assertEqual(r.status_code, 201, r.content.decode())
        self.assertEqual(self.c.clerk.get("/api/v1/sales-orders/").status_code, 200)
        self.assertEqual(self.c.clerk.get("/api/v1/sales-returns/").status_code, 200)
        self.assertEqual(self.c.clerk.get(f"/api/v1/sales-returns/returnable/?sales_order={r.json()['id']}").status_code, 200)
