"""客戶排行(固定報表)與自訂分析的「客戶」「會員」兩個角度(owner 2026-10-12;取舊歐睿 SA040 毛利彙總表照客戶 / 會員)。"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from rest_framework.exceptions import PermissionDenied

from apps.analytics import engine, presets
from apps.analytics.catalog import NO_MEMBER, supported_dims
from apps.backup.tests.factory import Company
from apps.parties.models import Customer, Member
from apps.tenants import abilities
from apps.tenants.models import UserProfile

URL = "/api/v1/analytics/presets/customers/"


class CustomerRankingTests(TestCase):
    """散客買手機 + 2 個皮套(沒有會員);同行帶會員王小明買 1 個皮套(之後整張退);散客 + 會員王小明買 3 個皮套。"""

    def setUp(self):
        c = self.c = Company("a", "甲通訊行", "甲")
        self.w1, self.w2 = c.warehouses
        c.purchase(phone_serials=["甲IMEI1"], case_qty=20)
        c.purchase(warehouse=self.w2, case_qty=5)
        self.peer = Customer.objects.create(tenant=c.tenant, name="甲同行", phone="0922000111")
        self.wang = Member.objects.create(tenant=c.tenant, name="王小明", phone="0911222333")
        self.so1 = c.sell(serial_no="甲IMEI1", case_qty=2)
        self.so2 = self.sell(self.peer, self.wang, 1)
        self.so3 = self.sell(c.customer, self.wang, 3)
        c._post("/api/v1/sales-returns/", {"original_so": self.so2["id"], "payment_method": "cash"})
        day = timezone.localdate().isoformat()
        self.range = {"from": day, "to": day}

    def sell(self, customer, member, cases, warehouse=None):
        return self.c._post("/api/v1/sales-orders/", {
            "customer": customer.id, "member": member.id if member else None,
            "warehouse": (warehouse or self.w1).id, "tax_method": "untaxed",
            "sales_person": self.c.sales_person.id,
            "items": [{"product": self.c.case.id, "qty": cases, "unit_price": "390"}],
            "payments": [{"method": "cash", "amount": str(390 * cases)}],
        })

    @staticmethod
    def root():
        user = get_user_model().objects.create_user(username="root-x", password="pw-12345")
        UserProfile.objects.create(user=user, role="platform_admin", tenant=None, is_warehouse_locked=False)
        return user

    def report(self, client=None, **params):
        r = (client or self.c.admin).get(URL, {**self.range, **params})
        self.assertEqual(r.status_code, 200, r.content.decode())
        return r.json()

    @staticmethod
    def rows(data):
        return {r["dims"][0]["label"]: r["values"] for r in data["rows"]}

    def test_by_customer(self):
        data = self.report()
        self.assertEqual((data["title"], [b["label"] for b in data["by"]]), ("客戶排行", ["客戶", "會員"]))
        self.assertEqual([m["label"] for m in data["columns"]["measures"]], ["銷貨單數", "淨銷售額", "業務員毛利", "實際毛利"])
        rows = self.rows(data)
        # 散客:手機 25,000 + 皮套 780 + 皮套 1,170;同行:賣 390 又整張退 = 0(那張單還是算一張)
        self.assertEqual(rows[self.c.customer.name], {
            "sales_orders": 2, "net_sales": "26950.00", "staff_gross_profit": "6450.00", "gross_profit": "6450.00"})
        self.assertEqual((rows["甲同行"]["sales_orders"], Decimal(rows["甲同行"]["net_sales"])), (1, 0))
        self.assertEqual([r["dims"][0]["label"] for r in data["rows"]], [self.c.customer.name, "甲同行"])     # 買得多的在前面

    def test_by_member(self):
        data = self.report(by="member")
        rows = self.rows(data)
        # 王小明:兩張單(同行那一張退掉了)併成一列;沒有會員的那一張歸「(非會員)」
        self.assertEqual((rows["王小明"]["sales_orders"], rows["王小明"]["net_sales"]), (2, "1170.00"))
        self.assertEqual((rows[NO_MEMBER]["sales_orders"], rows[NO_MEMBER]["net_sales"]), (1, "25780.00"))
        self.assertEqual(set(rows), {"王小明", NO_MEMBER})
        self.assertEqual([r["dims"][0]["label"] for r in data["rows"]], [NO_MEMBER, "王小明"])    # 買得多的在前面
        self.assertNotIn("0911222333", str(data))                    # 只有姓名,沒有電話

    def test_a_return_counts_against_whoever_is_on_the_return(self):
        # 銷退單自己記的客戶 / 會員(建立時照抄原單、唯讀):退的金額算在那一位。這裡直接改資料庫讓兩邊不一樣,釘住看的是哪一邊
        from apps.sales.models import SalesReturn

        other = Member.objects.create(tenant=self.c.tenant, name="李大同", phone="0966000111")
        SalesReturn.objects.filter(tenant=self.c.tenant).update(member=other)
        rows = self.rows(self.report(by="member"))
        self.assertEqual(rows["王小明"]["net_sales"], "1560.00")      # 兩張單 390 + 1,170,退的那一筆不算在他頭上
        self.assertEqual(rows["李大同"]["net_sales"], "-390.00")

    def test_rows_add_up_to_the_totals_of_the_other_reports(self):
        staff = self.c.admin.get("/api/v1/analytics/presets/staff/", self.range).json()["totals"]
        for by in ("customer", "member"):
            data = self.report(by=by)
            for key in ("net_sales", "staff_gross_profit", "gross_profit"):
                self.assertEqual(sum(Decimal(r["values"][key]) for r in data["rows"]), Decimal(data["totals"][key]), (by, key))
                self.assertEqual(Decimal(data["totals"][key]), Decimal(staff[key]), (by, key))
            self.assertEqual(data["totals"]["sales_orders"], 3)

    def test_two_people_with_the_same_name_are_two_rows(self):
        twin = Member.objects.create(tenant=self.c.tenant, name="王小明", phone="0933444555")
        self.sell(self.c.customer, twin, 1)
        data = self.report(by="member")
        named = [r for r in data["rows"] if r["dims"][0]["label"] == "王小明"]
        self.assertEqual(sorted(r["values"]["net_sales"] for r in named), ["1170.00", "390.00"])
        self.assertEqual(len({r["dims"][0]["value"] for r in named}), 2)

    def test_only_managers_see_it(self):
        # owner 2026-10-12:「客戶排行不用給店員看」—— 沒有勾可以開,店員一律 403;管理員與平台管理員照舊
        self.assertEqual(presets.REPORTS["customers"].ability, presets.MANAGERS_ONLY)
        self.assertNotIn("report_customers", abilities.KEYS)
        for params in (self.range, {**self.range, "by": "member"}, {**self.range, "export": "1"}):
            r = self.c.clerk.get(URL, params)
            self.assertEqual(r.status_code, 403, r.content.decode())
            self.assertEqual(r.json()["detail"], "「客戶排行」只有管理員可以看")
            self.assertNotIn("王小明", r.content.decode())
        self.assertEqual(self.c.admin.get(URL, self.range).status_code, 200)
        root_user = self.root()
        presets.check(presets.REPORTS["customers"], root_user)                # 平台管理員也可以(不丟錯)
        with self.assertRaises(PermissionDenied):
            presets.check(presets.REPORTS["customers"], self.c.clerk_user)
        # 平台管理員實際走一次(複審:只呼叫 check 沒有驗到整條路):選了這家公司之後查得到、匯出得到、自訂分析也能照會員分
        from rest_framework.authtoken.models import Token
        from rest_framework.test import APIClient

        root = APIClient()
        root.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=root_user).key}",
                         HTTP_X_TENANT_ID=str(self.c.tenant.pk))
        for params in (self.range, {**self.range, "by": "member", "export": "1"}):
            r = root.get(URL, params)
            self.assertEqual(r.status_code, 200, r.content.decode())
            self.assertTrue(r.json()["rows"])
        r = root.post("/api/v1/analytics/query/", {
            "measures": ["net_sales"], "dimensions": ["member"], "period": self.range}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.assertIn("王小明", [row["dims"][0]["label"] for row in r.json()["rows"]])
        # 店員別的報表照舊(不是整組一起關)
        self.assertEqual(self.c.clerk.get("/api/v1/analytics/presets/staff/", self.range).status_code, 200)

    def test_a_clerk_who_was_an_admin_loses_it(self):
        UserProfile.objects.filter(user=self.c.admin_user).update(role="tenant_user")
        former = Company.client(get_user_model().objects.get(pk=self.c.admin_user.pk))
        self.assertEqual(former.get(URL, self.range).status_code, 403)

    def test_export_gives_everything(self):
        from dataclasses import replace
        from unittest import mock

        short = {**presets.REPORTS, "customers": replace(presets.REPORTS["customers"], keep=1)}
        with mock.patch.object(presets, "REPORTS", short):
            self.assertEqual((len(self.report()["rows"]), self.report()["truncated"]), (1, True))
            everything = self.report(export="1")
        self.assertEqual((len(everything["rows"]), everything["truncated"]), (2, False))


class PeopleDimensionTests(TestCase):
    """自訂分析的「客戶」「會員」:哪些指標可以用、條件、下拉只給自己公司的。"""

    def setUp(self):
        c = self.c = Company("a", "甲通訊行", "甲")
        c.purchase(case_qty=20)
        self.wang = Member.objects.create(tenant=c.tenant, name="王小明", phone="0911222333")
        self.so = c._post("/api/v1/sales-orders/", {
            "customer": c.customer.id, "member": self.wang.id, "warehouse": c.wh.id, "tax_method": "untaxed",
            "sales_person": c.sales_person.id,
            "items": [{"product": c.case.id, "qty": 2, "unit_price": "390"}],
            "payments": [{"method": "cash", "amount": "780"}],
        })
        c.sell(case_qty=1)
        day = timezone.localdate().isoformat()
        self.range = {"from": day, "to": day}

    def query(self, client=None, **spec):
        return (client or self.c.admin).post(
            "/api/v1/analytics/query/", {"period": self.range, **spec}, format="json")

    def test_which_measures_can_be_split_by_people(self):
        for measure in ("net_sales", "gross_profit", "sales_orders", "received", "net_received", "contracts_due",
                        "staff_commission", "avg_ticket"):
            self.assertTrue({"customer", "member"} <= supported_dims(measure), measure)
        for measure in ("purchase_untaxed", "stock_qty", "legacy_net", "all_sales"):
            self.assertFalse({"customer", "member"} & supported_dims(measure), measure)

    def test_split_and_filter_by_member(self):
        r = self.query(measures=["net_sales", "received"], dimensions=["member"])
        self.assertEqual(r.status_code, 200, r.content.decode())
        rows = {row["dims"][0]["label"]: row["values"] for row in r.json()["rows"]}
        self.assertEqual(rows, {"王小明": {"net_sales": "780.00", "received": "780.00"},
                                NO_MEMBER: {"net_sales": "390.00", "received": "390.00"}})
        only = self.query(measures=["net_sales"], dimensions=["customer"], filters={"member": [self.wang.id]}).json()
        self.assertEqual(only["totals"], {"net_sales": "780.00"})
        self.assertEqual([row["dims"][0]["label"] for row in only["rows"]], [self.c.customer.name])
        # 退掉之後跟著扣(銷退單上的會員跟原單一樣)
        self.c._post("/api/v1/sales-returns/", {"original_so": self.so["id"], "payment_method": "cash"})
        after = self.query(measures=["net_sales", "net_received"], dimensions=["member"]).json()
        rows = {row["dims"][0]["label"]: row["values"] for row in after["rows"]}
        self.assertEqual(rows["王小明"], {"net_sales": "0.00", "net_received": "0.00"})

    def test_measures_that_have_no_customer_say_so(self):
        r = self.query(measures=["purchase_untaxed"], dimensions=["member"])
        self.assertEqual(r.status_code, 400)
        self.assertIn("會員", r.json()["detail"])

    def test_clerks_cannot_split_filter_or_list_by_people(self):
        """照客戶 / 會員分就是客戶排行:分組、條件、下拉的名單、選單都一起收(owner 2026-10-12)。店員的自訂分析其餘照舊。"""
        for dim, label, one in (("customer", "客戶", self.c.customer.id), ("member", "會員", self.wang.id)):
            for spec in ({"dimensions": [dim]}, {"dimensions": ["warehouse"], "filters": {dim: [one]}},
                         {"dimensions": [], "filters": {dim: [one]}}):
                r = self.query(self.c.clerk, measures=["net_sales"], **spec)
                self.assertEqual(r.status_code, 400, (dim, spec, r.content.decode()))
                self.assertEqual(r.json()["detail"], f"沒有權限照「{label}」看")
                self.assertEqual(self.query(measures=["net_sales"], **spec).status_code, 200, (dim, spec))   # 管理員可以
            r = self.c.clerk.get(f"/api/v1/analytics/options/?dimension={dim}")
            self.assertEqual(r.status_code, 400)
            self.assertNotIn("王小明", r.content.decode())
            self.assertEqual(self.c.admin.get(f"/api/v1/analytics/options/?dimension={dim}").status_code, 200)
        seen = self.c.clerk.get("/api/v1/analytics/catalog/").json()
        self.assertFalse({"customer", "member"} & {d["key"] for d in seen["dimensions"]})
        self.assertFalse(any({"customer", "member"} & set(m["dimensions"]) for m in seen["measures"]))
        self.assertTrue({"warehouse", "product", "sales_person"} <= {d["key"] for d in seen["dimensions"]})
        full = self.c.admin.get("/api/v1/analytics/catalog/").json()
        self.assertTrue({"customer", "member"} <= {d["key"] for d in full["dimensions"]})
        self.assertTrue({"customer", "member"} <= set(
            next(m for m in full["measures"] if m["key"] == "net_sales")["dimensions"]))
        root = CustomerRankingTests.root()
        self.assertTrue({"customer", "member"} <= {d["key"] for d in engine.describe(root)["dimensions"]})
        self.assertFalse({"customer", "member"} & {d["key"] for d in engine.describe(None)["dimensions"]})
        # 店員其餘的自訂分析照舊
        self.assertEqual(self.query(self.c.clerk, measures=["net_sales"], dimensions=["sales_person"]).status_code, 200)

    def test_a_shared_report_by_people_does_not_open_for_clerks(self):
        """管理員存成全公司共用的「照會員」報表:店員的清單上看得到這一份,但打不開、也拿不到裡面的名單。"""
        for name, spec in (("照會員", {"dimensions": ["member"]}),
                           ("只看王小明", {"dimensions": ["warehouse"], "filters": {"member": [self.wang.id]}})):
            r = self.c.admin.post("/api/v1/analytics/reports/", {
                "name": name, "shared": True, "spec": {"measures": ["net_sales"], "period": self.range, **spec},
            }, format="json")
            self.assertEqual(r.status_code, 201, r.content.decode())
        mine = {x["name"]: x for x in self.c.admin.get("/api/v1/analytics/reports/").json()["results"]}
        self.assertEqual((mine["照會員"]["error"], mine["只看王小明"]["error"]), ("", ""))
        self.assertEqual(mine["只看王小明"]["filters"][0]["values"][0]["label"], "王小明")
        r = self.c.clerk.get("/api/v1/analytics/reports/")
        self.assertEqual(r.status_code, 200)
        theirs = {x["name"]: x for x in r.json()["results"]}
        self.assertEqual((theirs["照會員"]["error"], theirs["只看王小明"]["error"]),
                         ("沒有權限照「會員」看", "沒有權限照「會員」看"))
        self.assertEqual(theirs["只看王小明"]["filters"], [])
        self.assertNotIn("王小明", str(theirs["只看王小明"]["filters"]))
        # 店員自己也存不了這種報表
        r = self.c.clerk.post("/api/v1/analytics/reports/", {
            "name": "偷存", "spec": {"measures": ["net_sales"], "dimensions": ["customer"], "period": self.range},
        }, format="json")
        self.assertEqual(r.status_code, 400)

    def test_options_and_filters_stay_inside_the_company(self):
        other = Company("b", "乙通訊行", "乙")
        theirs = Member.objects.create(tenant=other.tenant, name="乙會員", phone="0955000111")
        names = [o["label"] for o in self.c.admin.get("/api/v1/analytics/options/?dimension=member").json()["results"]]
        self.assertEqual(names, ["王小明"])
        self.assertNotIn("0911222333", str(self.c.admin.get("/api/v1/analytics/options/?dimension=member").json()))
        customers = [o["label"] for o in self.c.admin.get("/api/v1/analytics/options/?dimension=customer").json()["results"]]
        self.assertIn(self.c.customer.name, customers)
        self.assertNotIn(other.customer.name, customers)
        r = self.query(measures=["net_sales"], dimensions=["member"], filters={"member": [theirs.id]})
        self.assertEqual(r.status_code, 400)                      # 別家公司的會員編號 = 不認得
