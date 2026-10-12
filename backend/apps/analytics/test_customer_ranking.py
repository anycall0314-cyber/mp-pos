"""客戶排行(固定報表)與自訂分析的「客戶」「會員」兩個角度(owner 2026-10-12;取舊歐睿 SA040 毛利彙總表照客戶 / 會員)。"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.analytics import presets
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

    def test_clerk_sees_own_store_without_the_actual_margin(self):
        self.sell(self.c.customer, None, 2, warehouse=self.w2)                 # 第二家門市的
        mine = self.report(client=self.c.clerk, warehouse=self.w2.id)           # 網址帶別家的編號沒有用
        self.assertEqual([m["key"] for m in mine["columns"]["measures"]], ["sales_orders", "net_sales", "staff_gross_profit"])
        # 不只是欄名沒列:每一列、合計、整份回應裡都沒有實際毛利(複審首輪:只驗欄名的話,數字偷偷帶出來也會過)
        allowed = {"sales_orders", "net_sales", "staff_gross_profit"}
        self.assertEqual(set(mine["totals"]), allowed)
        self.assertTrue(mine["rows"] and all(set(r["values"]) == allowed for r in mine["rows"]))
        self.assertNotIn("gross_profit\"", str(mine).replace("staff_gross_profit", "").replace("'", "\""))
        exported = self.report(client=self.c.clerk, export="1", by="member")
        self.assertEqual(set(exported["totals"]), allowed)
        self.assertTrue(all(set(r["values"]) == allowed for r in exported["rows"]))
        self.assertEqual(mine["totals"]["sales_orders"], 3)
        self.assertEqual(self.report()["totals"]["sales_orders"], 4)

    def test_needs_its_own_item_and_explore_follows(self):
        self.assertEqual(presets.REPORTS["customers"].ability, abilities.REPORT_CUSTOMERS)
        self.assertEqual(self.c.clerk.get(URL, self.range).status_code, 200)
        UserProfile.objects.filter(user=self.c.clerk_user).update(denied_abilities=["report_customers"])
        clerk = Company.client(get_user_model().objects.get(pk=self.c.clerk_user.pk))
        r = clerk.get(URL, self.range)
        self.assertEqual(r.status_code, 403)
        self.assertIn("客戶排行", r.json()["detail"])
        # 自訂分析挑「淨銷售額 × 會員」就組得出同一張表:這一張關掉,自訂分析也跟著不能用
        spec = {"measures": ["net_sales"], "dimensions": ["member"], "period": self.range}
        r = clerk.post("/api/v1/analytics/query/", spec, format="json")
        self.assertEqual(r.status_code, 403)
        self.assertIn("客戶排行", r.json()["detail"])
        self.assertEqual(self.c.admin.post("/api/v1/analytics/query/", spec, format="json").status_code, 200)

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
