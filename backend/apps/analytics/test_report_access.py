"""員工帳號權限第三批:報表的勾、鎖在門市的只看自己門市、四張新報表。

期望值照單據手算。底下這幾張接在 `tests.build_shop()`(銷貨1~3 + 銷退)後面:

    銷貨4 2026-09-20  湳雅店  門號(皮套 1 × 0,成本 100;方案:業務員佣金 6000、公司佣金 10000),有業務員
    銷貨5 2026-09-21  民生店  門號(同上),沒有業務員
    銷貨6 2026-09-22  湳雅店  門號(同上),有業務員
    銷退  2026-09-25  整張退掉銷貨6
    銷貨7 2026-09-15  湳雅店  不計毛利的帳務項目 1 × 500,沒有業務員(個人收購那一類:不算業績)

9 月湳雅店(店員看得到的):
    甲店員  單數 4(銷貨1、3、4、6)  淨銷售 25780  業務員毛利 5580 − 100 = 5480
            門號佣金 6000 + 6000 − 6000 = 6000  毛利加佣金 11480
9 月全公司多一列(未指定):銷貨5 → 單數 1、淨銷售 0、毛利 −100、佣金 6000、毛利加佣金 5900
"""
from datetime import date
from decimal import Decimal
from unittest import mock

from django.test import SimpleTestCase, TestCase

from apps.backup.tests.factory import Company
from apps.catalog.models import Product
from apps.parties.models import Carrier, TelecomPlan
from apps.sales.models import SalesOrder, SalesReturn
from apps.tenants import abilities
from apps.tenants.models import UserProfile

from . import engine, presets
from .catalog import MEASURES, supported_dims
from .tests import AUG_SEP, SEP, build_shop

QUERY = "/api/v1/analytics/query/"
PRESET = "/api/v1/analytics/presets/"
LINES = "/api/v1/telecom-commissions/"
SEP_Q = "from=2026-09-01&to=2026-09-30"
REPORT_KEYS = ("report_sales_daily", "report_explore", "report_parts", "report_staff",
               "report_products", "report_commission", "report_daily")


def add_lines(c, tag="甲"):
    """接在 build_shop 後面開上面那四張單。"""
    c.carrier = Carrier.objects.create(tenant=c.tenant, code="CHT", name=f"{tag}中華電信")
    c.plan = TelecomPlan.objects.create(
        tenant=c.tenant, carrier=c.carrier, name=f"{tag}1399 30月", monthly_fee=1399, contract_months=30,
        kind="renewal", commission=Decimal("6000"), company_commission=Decimal("10000"),
    )
    Product.objects.filter(pk=c.case.pk).update(allows_telecom_line=True, allows_commission=True)
    c.fee = Product.objects.create(
        tenant=c.tenant, category=c.cat_case, name=f"{tag}收購項目", requires_serial=False,
        is_virtual=True, counts_margin=False,
    )

    def line(warehouse, person, msisdn):
        body = {
            "customer": c.customer.id, "warehouse": warehouse.id, "tax_method": "untaxed", "payments": [],
            "items": [{"product": c.case.id, "qty": 1, "unit_price": "0", "msisdn": msisdn,
                       "telecom_plan": c.plan.id, "activation_date": "2026-09-20"}],
        }
        if person:
            body["sales_person"] = c.sales_person.id
        return c._post("/api/v1/sales-orders/", body)

    c.s4 = line(c.wh, True, "0922333004")
    c.s5 = line(c.wh2, False, "0922333005")
    c.s6 = line(c.wh, True, "0922333006")
    c.sr6 = c._post("/api/v1/sales-returns/", {"original_so": c.s6["id"]})        # 總額 0:不用退款方式
    c.s7 = c._post("/api/v1/sales-orders/", {
        "customer": c.customer.id, "warehouse": c.wh.id, "tax_method": "untaxed",
        "items": [{"product": c.fee.id, "qty": 1, "unit_price": "500"}],
        "payments": [{"method": "cash", "amount": "500"}],
    })
    for so, day in ((c.s4, 20), (c.s5, 21), (c.s6, 22), (c.s7, 15)):
        SalesOrder.objects.filter(pk=so["id"]).update(doc_date=date(2026, 9, day))
    SalesReturn.objects.filter(pk=c.sr6["id"]).update(doc_date=date(2026, 9, 25))
    return c


class _Shop(TestCase):
    def setUp(self):
        self.c = add_lines(build_shop())
        self.t = self.c.tenant
        self.wh1, self.wh2 = self.c.wh, self.c.wh2
        self.admin, self.clerk = self.c.admin, self.c.clerk

    def turn_off(self, *keys):
        UserProfile.objects.filter(user=self.c.clerk_user).update(denied_abilities=list(keys))
        self.c.clerk_user.profile.refresh_from_db()

    def preset(self, key, client=None, extra=""):
        r = (client or self.clerk).get(f"{PRESET}{key}/?{SEP_Q}{extra}")
        self.assertEqual(r.status_code, 200, r.content.decode())
        return r.json()

    @staticmethod
    def table(result):
        """{第一欄的名稱: {指標: 值}}"""
        return {row["dims"][0]["label"]: row["values"] for row in result["rows"]}

    def assertDenied(self, r, label):
        self.assertEqual(r.status_code, 403, r.content.decode())
        self.assertIn(f"「{label}」", r.json()["detail"])


class ListTests(SimpleTestCase):
    def test_the_seven_report_items(self):
        items = {a["key"]: a for a in abilities.catalog() if a["group"] == "報表"}
        self.assertEqual(tuple(items), REPORT_KEYS)
        self.assertEqual(
            [items[k]["label"] for k in REPORT_KEYS],
            ["銷貨日報", "自訂分析", "零件耗用", "業績彙總", "商品排行", "佣金明細", "每日彙總"])

    def test_every_measure_can_be_limited_to_one_store(self):
        """鎖在門市的帳號靠「只算那一家」:哪個指標分不出門市,店員就整個不能用 —— 新增指標時這裡會提醒。"""
        self.assertEqual([m for m in MEASURES if "warehouse" not in supported_dims(m)], [])

    def test_each_fixed_report_has_its_own_item(self):
        self.assertEqual({k: r.ability for k, r in presets.REPORTS.items()},
                         {"staff": "report_staff", "products": "report_products", "daily": "report_daily"})

    def test_explore_needs_every_report_it_can_rebuild(self):
        """自訂分析挑同樣的指標與分組就組得出固定的報表:固定的報表每一張都要列在「自訂分析要另外開著的」裡面。"""
        needs = set(abilities.ALSO_NEEDS["report_explore"])
        self.assertEqual({r.ability for r in presets.REPORTS.values()} - needs, set())
        self.assertIn("view_business_daily", needs)             # 自訂分析有「收款」:每天收了多少錢


class OwnStoreTests(_Shop):
    """鎖在門市的帳號:自訂分析只算自己門市(owner 2026-10-10;以前看得到全公司)。"""
    SPEC = {"measures": ["net_sales", "gross_profit"], "dimensions": ["warehouse"], "period": AUG_SEP}

    def test_a_locked_clerk_only_gets_the_own_store(self):
        r = self.clerk.post(QUERY, self.SPEC, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.assertEqual(self.table(r.json()), {"甲湳雅店": {"net_sales": "25780.00", "gross_profit": "5480.00"}})
        self.assertEqual(r.json()["totals"], {"net_sales": "25780.00", "gross_profit": "5480.00"})
        # 畫面上看得到是哪一家(不是默默少算)
        self.assertEqual(r.json()["applied"]["filters"], [{
            "dimension": "warehouse", "label": "門市",
            "values": [{"value": self.wh1.id, "label": "甲湳雅店"}]}])

    def test_asking_for_another_store_changes_nothing(self):
        for filters in ({"warehouse": [self.wh2.id]}, {"warehouse": [self.wh1.id, self.wh2.id]},
                        {"warehouse": [None]}):
            r = self.clerk.post(QUERY, {**self.SPEC, "filters": filters}, format="json")
            self.assertEqual(r.status_code, 200, r.content.decode())
            self.assertEqual(set(self.table(r.json())), {"甲湳雅店"}, filters)
            self.assertEqual(r.json()["totals"]["net_sales"], "25780.00", filters)

    def test_without_a_store_column_and_with_compare_it_is_still_the_own_store(self):
        r = self.clerk.post(QUERY, {"measures": ["net_sales", "staff_commission"], "period": SEP,
                                    "compare": "previous"}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.assertEqual(r.json()["totals"], {"net_sales": "25780.00", "staff_commission": "12000.00"})
        self.assertEqual(r.json()["totals_previous"]["net_sales"], "0.00")      # 8 月那一張是民生店的
        r = self.admin.post(QUERY, {"measures": ["net_sales"], "period": SEP, "compare": "previous"},
                            format="json")
        self.assertEqual(r.json()["totals_previous"]["net_sales"], "371.00")

    def test_managers_and_unlocked_accounts_see_the_whole_company(self):
        r = self.admin.post(QUERY, self.SPEC, format="json")
        self.assertEqual(set(self.table(r.json())), {"甲湳雅店", "甲民生店"})
        UserProfile.objects.filter(user=self.c.clerk_user).update(is_warehouse_locked=False)
        self.c.clerk_user.profile.refresh_from_db()
        r = self.clerk.post(QUERY, self.SPEC, format="json")
        self.assertEqual(set(self.table(r.json())), {"甲湳雅店", "甲民生店"})

    def test_locked_without_a_store_sees_nothing(self):
        UserProfile.objects.filter(user=self.c.clerk_user).update(default_warehouse=None)
        self.c.clerk_user.profile.refresh_from_db()
        for r in (self.clerk.post(QUERY, self.SPEC, format="json"),
                  self.clerk.get(f"{PRESET}staff/?{SEP_Q}"), self.clerk.get(f"{LINES}?{SEP_Q}")):
            self.assertEqual(r.status_code, 403, r.content.decode())
            self.assertNotIn("25780", r.content.decode())

    def test_a_measure_that_cannot_be_split_by_store_is_refused(self):
        spec = {"measures": ["net_sales"], "period": SEP}
        with mock.patch.object(engine, "supported_dims", return_value={"date"}):
            with self.assertRaises(engine.QueryError) as ctx:
                engine.run(self.t, spec, self.c.clerk_user, only_warehouse=self.wh1.id)
            self.assertIn("分不出門市", str(ctx.exception))
            engine.run(self.t, spec, self.c.admin_user)          # 沒鎖門市的不受影響

    def test_company_commission_stays_with_managers_in_the_new_measures(self):
        listed = {m["key"] for m in self.clerk.get("/api/v1/analytics/catalog/").json()["measures"]}
        self.assertTrue({"staff_total", "net_staff_commission", "return_staff_commission"} <= listed)
        self.assertFalse({"net_company_commission", "return_company_commission"} & listed)
        for key in ("net_company_commission", "return_company_commission"):
            r = self.clerk.post(QUERY, {"measures": [key], "period": SEP}, format="json")
            self.assertEqual((r.status_code, "沒有權限看" in r.json()["detail"]), (400, True), key)
        r = self.admin.post(QUERY, {"measures": ["net_company_commission", "return_company_commission",
                                                 "net_staff_commission", "staff_total"], "period": SEP},
                            format="json")
        self.assertEqual(r.json()["totals"], {
            "net_company_commission": "20000.00", "return_company_commission": "10000.00",
            "net_staff_commission": "12000.00", "staff_total": "17380.00"})


class ItemTests(_Shop):
    """一張一個勾:關掉的那一張伺服器回 403 與原因,別張照舊。"""

    def test_explore_off_blocks_the_whole_group(self):
        report = self.clerk.post("/api/v1/analytics/reports/", {
            "name": "我的", "spec": OwnStoreTests.SPEC}, format="json").json()
        self.turn_off("report_explore")
        one = f"/api/v1/analytics/reports/{report['id']}/"
        for r in (self.clerk.get("/api/v1/analytics/catalog/"),
                  self.clerk.get("/api/v1/analytics/options/?dimension=warehouse"),
                  self.clerk.post(QUERY, OwnStoreTests.SPEC, format="json"),
                  self.clerk.get("/api/v1/analytics/reports/"),
                  self.clerk.post("/api/v1/analytics/reports/", {"name": "二", "spec": OwnStoreTests.SPEC},
                                  format="json"),
                  self.clerk.patch(one, {"name": "改"}, format="json"),
                  self.clerk.delete(one)):
            self.assertDenied(r, "自訂分析")
        self.assertEqual(self.clerk.get(f"{PRESET}staff/?{SEP_Q}").status_code, 200)    # 別張不受影響
        self.assertEqual(self.admin.post(QUERY, OwnStoreTests.SPEC, format="json").status_code, 200)

    def test_each_fixed_report_follows_its_own_item(self):
        urls = {"report_staff": (f"{PRESET}staff/?{SEP_Q}", "業績彙總"),
                "report_products": (f"{PRESET}products/?{SEP_Q}", "商品排行"),
                "report_daily": (f"{PRESET}daily/?{SEP_Q}", "每日彙總"),
                "report_commission": (f"{LINES}?{SEP_Q}", "佣金明細"),
                "report_parts": ("/api/v1/parts-usage-report/", "零件耗用")}
        for key, (url, label) in urls.items():
            self.turn_off(key)
            self.assertDenied(self.clerk.get(url), label)
            for other, (other_url, _label) in urls.items():
                if other != key:
                    self.assertEqual(self.clerk.get(other_url).status_code, 200, (key, other))
            self.assertEqual(self.admin.get(url).status_code, 200, key)
        self.turn_off()
        self.assertEqual(self.clerk.post(QUERY, OwnStoreTests.SPEC, format="json").status_code, 200)

    def test_the_sales_daily_item_only_hides_the_page(self):
        """銷貨日報的內容就是銷貨單清單:關掉只收那一頁,清單照舊查得到(伺服器沒有另外一支可以擋)。"""
        self.turn_off("report_sales_daily")
        self.assertEqual(self.clerk.get("/api/v1/sales-orders/").status_code, 200)
        self.assertFalse(self.clerk.get("/api/v1/auth/me/").json()["abilities"]["report_sales_daily"])


class ExploreFollowsTheOthersTests(_Shop):
    """複審抓到的:關掉「業績彙總」、留著「自訂分析」的人,到自訂分析挑同樣的指標與分組就看到了。
    所以那幾張有一張被關掉,自訂分析也跟著不能用。"""
    ACCOUNTS = "/api/v1/staff-accounts/"
    SAME_AS = {
        "report_staff": {"measures": ["sales_orders", "net_sales", "staff_gross_profit", "net_staff_commission",
                                      "staff_total"], "dimensions": ["sales_person"], "period": SEP,
                         "sort": "-staff_total", "limit": 2000},
        "report_products": {"measures": ["net_qty", "net_sales", "staff_gross_profit"], "dimensions": ["product"],
                            "period": SEP},
        "report_daily": {"measures": ["sales_orders", "net_sales", "staff_total"], "dimensions": ["date"],
                         "period": {**SEP, "grain": "day"}},
        "view_business_daily": {"measures": ["received", "net_received"], "dimensions": ["date", "payment_method"],
                                "period": {**SEP, "grain": "day"}},
    }
    LABEL = {"report_staff": "業績彙總", "report_products": "商品排行", "report_daily": "每日彙總",
             "view_business_daily": "營業日報"}

    def mine(self):
        return {a["username"]: a for a in self.admin.get(self.ACCOUNTS).json()["accounts"]}["a-clerk"]["abilities"]

    def test_the_same_table_cannot_be_rebuilt_in_explore(self):
        for key, spec in self.SAME_AS.items():
            self.turn_off()
            self.assertEqual(self.clerk.post(QUERY, spec, format="json").status_code, 200, key)   # 沒關的時候可以
            self.turn_off(key)
            r = self.clerk.post(QUERY, spec, format="json")
            self.assertEqual(r.status_code, 403, (key, r.content.decode()))
            # 講的是被關掉的那一張,不是叫人去開一個本來就開著的「自訂分析」
            self.assertEqual(r.json()["detail"], f"這個帳號的「{self.LABEL[key]}」被關掉了,「自訂分析」也不能用,"
                                                 "請管理員到「系統設定 → 員工帳號」開啟")
            self.assertNotIn("rows", r.json())
            for url in ("catalog/", "options/?dimension=warehouse", "reports/"):
                self.assertEqual(self.clerk.get(f"/api/v1/analytics/{url}").status_code, 403, (key, url))
            self.assertEqual(self.admin.post(QUERY, spec, format="json").status_code, 200, key)
        self.turn_off("report_staff", "report_daily")
        r = self.clerk.post(QUERY, self.SAME_AS["report_products"], format="json")
        self.assertIn("「業績彙總、每日彙總」被關掉了", r.json()["detail"])
        # 自訂分析自己也被關掉的:講的是它自己(開了之後管理員會再被告知要先開哪一張)
        self.turn_off("report_staff", "report_explore")
        r = self.clerk.post(QUERY, self.SAME_AS["report_products"], format="json")
        self.assertEqual((r.status_code, "沒有「自訂分析」的權限" in r.json()["detail"]), (403, True))

    def test_the_login_data_and_the_account_page_show_it_as_off(self):
        self.turn_off("report_products")
        me = self.clerk.get("/api/v1/auth/me/").json()["abilities"]
        self.assertEqual((me["report_products"], me["report_explore"], me["report_staff"]), (False, False, True))
        self.assertEqual((self.mine()["report_explore"], self.mine()["report_daily"]), (False, True))
        # 沒有被記成「關掉」:那一張開回來,自訂分析自己回來
        self.assertEqual(UserProfile.objects.get(user=self.c.clerk_user).denied_abilities, ["report_products"])
        self.turn_off()
        self.assertTrue(self.clerk.get("/api/v1/auth/me/").json()["abilities"]["report_explore"])
        self.assertEqual(self.clerk.post(QUERY, self.SAME_AS["report_products"], format="json").status_code, 200)

    def test_other_items_do_not_take_explore_away(self):
        others = [k for k in abilities.KEYS if k not in abilities.ALSO_NEEDS["report_explore"] and k != "report_explore"]
        self.turn_off(*others)
        self.assertTrue(self.clerk.get("/api/v1/auth/me/").json()["abilities"]["report_explore"])
        self.assertEqual(self.clerk.post(QUERY, OwnStoreTests.SPEC, format="json").status_code, 200)

    def test_a_manager_cannot_switch_explore_on_while_one_of_them_is_off(self):
        one = f"{self.ACCOUNTS}{self.c.clerk_user.id}/"
        r = self.admin.patch(one, {"abilities": {"report_staff": False, "view_business_daily": False}}, format="json")
        self.assertEqual((r.status_code, r.json()["abilities"]["report_explore"]), (200, False))
        r = self.admin.patch(one, {"abilities": {"report_explore": True}}, format="json")
        self.assertEqual((r.status_code, r.json()), (400, {"detail": "「自訂分析」要先開:業績彙總、營業日報"}))
        r = self.admin.patch(one, {"abilities": {"report_explore": True, "report_staff": True}}, format="json")
        self.assertEqual((r.status_code, r.json()), (400, {"detail": "「自訂分析」要先開:營業日報"}))
        self.assertEqual(UserProfile.objects.get(user=self.c.clerk_user).denied_abilities,
                         ["view_business_daily", "report_staff"])                  # 被退回的那兩次什麼都沒存
        # 關掉自訂分析本身、開別的項目都不受這一條影響
        r = self.admin.patch(one, {"abilities": {"report_explore": False, "void_sales": True}}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        r = self.admin.patch(one, {"abilities": {"report_staff": True, "view_business_daily": True,
                                                 "report_explore": True}}, format="json")
        self.assertEqual((r.status_code, r.json()["abilities"]["report_explore"]), (200, True))
        self.assertEqual(UserProfile.objects.get(user=self.c.clerk_user).denied_abilities, [])


class FixedReportTests(_Shop):
    def test_staff_report_for_a_clerk_is_the_own_store_without_manager_columns(self):
        got = self.preset("staff")
        self.assertEqual((got["title"], got["columns"]["dimensions"]), ("業績彙總", [{"key": "sales_person", "label": "業務員"}]))
        self.assertEqual([(m["key"], m["label"]) for m in got["columns"]["measures"]], [
            ("sales_orders", "銷貨單數"), ("net_sales", "淨銷售額"), ("staff_gross_profit", "業務員毛利"),
            ("net_staff_commission", "門號佣金"), ("staff_total", "毛利加佣金")])
        mine = {"sales_orders": 4, "net_sales": "25780.00", "staff_gross_profit": "5480.00",
                "net_staff_commission": "6000.00", "staff_total": "11480.00"}
        # 沒有業務員的那一張(銷貨7:不計毛利)整列是 0,不列出來
        self.assertEqual(self.table(got), {"甲店員": mine})
        self.assertEqual((got["totals"], got["row_count"], got["truncated"]), (mine, 1, False))
        self.assertEqual(self.preset("staff", extra=f"&warehouse={self.wh2.id}")["totals"], mine)
        for text in ("gross_profit\"", "company", "10000", "20000"):
            self.assertNotIn(text, self.clerk.get(f"{PRESET}staff/?{SEP_Q}").content.decode().replace(
                "staff_gross_profit\"", ""))

    def test_staff_report_for_a_manager(self):
        got = self.preset("staff", self.admin)
        self.assertEqual([m["label"] for m in got["columns"]["measures"]], [
            "銷貨單數", "淨銷售額", "業務員毛利", "門號佣金", "毛利加佣金", "實際毛利", "公司佣金"])
        self.assertEqual(self.table(got), {
            "甲店員": {"sales_orders": 4, "net_sales": "25780.00", "staff_gross_profit": "5480.00",
                    "net_staff_commission": "6000.00", "staff_total": "11480.00",
                    "gross_profit": "5480.00", "net_company_commission": "10000.00"},
            "(未指定)": {"sales_orders": 1, "net_sales": "0.00", "staff_gross_profit": "-100.00",
                      "net_staff_commission": "6000.00", "staff_total": "5900.00",
                      "gross_profit": "-100.00", "net_company_commission": "10000.00"},
        })
        self.assertEqual([r["dims"][0]["label"] for r in got["rows"]], ["甲店員", "(未指定)"])   # 毛利加佣金高的在前
        self.assertEqual(got["totals"], {
            "sales_orders": 5, "net_sales": "25780.00", "staff_gross_profit": "5380.00",
            "net_staff_commission": "12000.00", "staff_total": "17380.00",
            "gross_profit": "5380.00", "net_company_commission": "20000.00"})
        only = self.preset("staff", self.admin, f"&warehouse={self.wh2.id}")
        self.assertEqual((set(self.table(only)), only["totals"]["staff_total"]), ({"(未指定)"}, "5900.00"))

    def test_staff_cost_rule_moves_the_staff_profit_but_not_the_actual_one(self):
        """業務員毛利用的是單上記的業務員成本;沒有記的舊單 = 實際成本。"""
        from apps.sales.models import SalesOrderItem

        SalesOrderItem.objects.filter(so_id=self.c.s1["id"], product=self.c.phone).update(staff_cost=Decimal("21000"))
        got = self.preset("staff", self.admin)
        row = self.table(got)["甲店員"]
        self.assertEqual((row["staff_gross_profit"], row["staff_total"], row["gross_profit"]),
                         ("4480.00", "10480.00", "5480.00"))

    def test_daily_report_counts_a_return_on_the_day_it_came_back(self):
        got = self.preset("daily")
        self.assertEqual(got["applied"]["grain"], "day")
        rows = {r["dims"][0]["value"]: r["values"] for r in got["rows"]}
        self.assertEqual(rows, {
            "2026-09-10": {"sales_orders": 2, "net_sales": "26170.00", "staff_gross_profit": "5870.00",
                           "net_staff_commission": "0.00", "staff_total": "5870.00"},
            "2026-09-12": {"sales_orders": 0, "net_sales": "-390.00", "staff_gross_profit": "-290.00",
                           "net_staff_commission": "0.00", "staff_total": "-290.00"},
            "2026-09-20": {"sales_orders": 1, "net_sales": "0.00", "staff_gross_profit": "-100.00",
                           "net_staff_commission": "6000.00", "staff_total": "5900.00"},
            "2026-09-22": {"sales_orders": 1, "net_sales": "0.00", "staff_gross_profit": "-100.00",
                           "net_staff_commission": "6000.00", "staff_total": "5900.00"},
            "2026-09-25": {"sales_orders": 0, "net_sales": "0.00", "staff_gross_profit": "100.00",
                           "net_staff_commission": "-6000.00", "staff_total": "-5900.00"},
        })
        self.assertEqual(list(rows), sorted(rows))                              # 照日期排
        self.assertEqual(got["totals"]["staff_total"], self.preset("staff")["totals"]["staff_total"])

    def test_product_ranking_and_its_other_groupings(self):
        got = self.preset("products", self.admin)
        self.assertEqual([b["key"] for b in got["by"]], ["product", "category", "brand"])
        self.assertEqual([(r["dims"][0]["label"], r["values"]) for r in got["rows"]], [
            ("Reno16 側翻皮套／藍", {"net_qty": 4, "net_sales": "780.00", "staff_gross_profit": "380.00",
                              "gross_profit": "380.00"}),
            ("甲 iPhone 15 128GB 黑", {"net_qty": 1, "net_sales": "25000.00", "staff_gross_profit": "5000.00",
                                   "gross_profit": "5000.00"}),
        ])
        by_cat = self.preset("products", self.admin, "&by=category")
        self.assertEqual(by_cat["columns"]["dimensions"], [{"key": "category", "label": "品類"}])
        self.assertEqual({k: v["net_qty"] for k, v in self.table(by_cat).items()}, {"皮套": 4, "手機": 1})
        mine = self.preset("products")
        self.assertEqual({k: v for k, v in self.table(mine).items()}, {
            "Reno16 側翻皮套／藍": {"net_qty": 3, "net_sales": "780.00", "staff_gross_profit": "480.00"},
            "甲 iPhone 15 128GB 黑": {"net_qty": 1, "net_sales": "25000.00", "staff_gross_profit": "5000.00"},
        })

    def test_the_ranking_is_cut_but_the_totals_are_not(self):
        with mock.patch.dict(presets.REPORTS, {"products": presets.Report(
                "products", "商品排行", abilities.REPORT_PRODUCTS, {"product": "商品"},
                presets.REPORTS["products"].cols, sort="-net_qty", keep=1)}):
            got = self.preset("products", self.admin)
        self.assertEqual(([r["dims"][0]["label"] for r in got["rows"]], got["row_count"], got["truncated"]),
                         (["Reno16 側翻皮套／藍"], 2, True))
        self.assertEqual(got["totals"]["net_sales"], "25780.00")

    def test_bad_requests_get_a_plain_message(self):
        for url, text in ((f"{PRESET}staff/", "開始日期的格式"),
                          (f"{PRESET}staff/?from=2026-09-01", "結束日期的格式"),
                          (f"{PRESET}staff/?from=2026-09-30&to=2026-09-01", "結束日期不能早於"),
                          (f"{PRESET}products/?{SEP_Q}&by=warehouse", "不能這樣分"),
                          (f"{PRESET}products/?{SEP_Q}&by=so__customer", "不能這樣分"),
                          (f"{PRESET}daily/?from=2025-09-01&to=2026-09-02", "一次最多看一年"),
                          (f"{PRESET}staff/?{SEP_Q}&warehouse=999999", "找不到的資料")):
            r = self.admin.get(url)
            self.assertEqual((r.status_code, text in r.json()["detail"]), (400, True), (url, r.content.decode()))
        self.assertEqual(self.admin.get(f"{PRESET}daily/?from=2025-09-01&to=2026-09-01").status_code, 200)
        # 一年的上限只管每日彙總(一天一列);別張照引擎的上限
        self.assertEqual(self.admin.get(f"{PRESET}staff/?from=2020-01-01&to=2026-09-30").status_code, 200)
        self.assertEqual(self.admin.get(f"{PRESET}nope/?{SEP_Q}").status_code, 404)
        from rest_framework.test import APIClient

        self.assertEqual(APIClient().get(f"{PRESET}staff/?{SEP_Q}").status_code, 401)
        self.assertEqual(APIClient().get(f"{LINES}?{SEP_Q}").status_code, 401)

    def test_another_company_is_never_mixed_in(self):
        other = add_lines(build_shop("b", "乙通訊行", "乙"), "乙")
        got = self.preset("staff", self.admin)
        self.assertEqual(set(self.table(got)), {"甲店員", "(未指定)"})
        self.assertEqual(got["totals"]["staff_total"], "17380.00")
        r = self.admin.get(f"{PRESET}staff/?{SEP_Q}&warehouse={other.wh.id}")
        self.assertEqual(r.status_code, 400, r.content.decode())
        lines = self.admin.get(f"{LINES}?{SEP_Q}").json()
        self.assertEqual((lines["row_count"], lines["totals"]["commission"]), (4, "12000.00"))
        self.assertNotIn("乙", self.admin.get(f"{LINES}?{SEP_Q}").content.decode())


class CommissionLinesTests(_Shop):
    def lines(self, client=None, extra=""):
        r = (client or self.clerk).get(f"{LINES}?{SEP_Q}{extra}")
        self.assertEqual(r.status_code, 200, r.content.decode())
        return r.json()

    def test_a_manager_sees_every_line_and_both_commissions(self):
        got = self.lines(self.admin)
        self.assertEqual([(r["date"], r["kind"], r["doc_no"], r["warehouse"], r["msisdn"], r["sales_person"],
                           r["commission"], r["company_commission"]) for r in got["rows"]], [
            ("2026-09-20", "sale", self.c.s4["no"], "甲湳雅店", "0922333004", "甲店員", "6000.00", "10000.00"),
            ("2026-09-21", "sale", self.c.s5["no"], "甲民生店", "0922333005", "", "6000.00", "10000.00"),
            ("2026-09-22", "sale", self.c.s6["no"], "甲湳雅店", "0922333006", "甲店員", "6000.00", "10000.00"),
            ("2026-09-25", "return", self.c.sr6["no"], "甲湳雅店", "0922333006", "甲店員", "-6000.00", "-10000.00"),
        ])
        self.assertEqual((got["rows"][0]["plan"], got["rows"][0]["carrier"], got["rows"][0]["doc_id"]),
                         ("甲1399 30月", "甲中華電信", self.c.s4["id"]))
        self.assertEqual(got["rows"][3]["doc_id"], self.c.sr6["id"])
        self.assertEqual((got["totals"], got["manager"], got["truncated"]),
                         ({"commission": "12000.00", "company_commission": "20000.00"}, True, False))
        only = self.lines(self.admin, f"&warehouse={self.wh2.id}")
        self.assertEqual(([r["doc_no"] for r in only["rows"]], only["totals"]["commission"]),
                         ([self.c.s5["no"]], "6000.00"))

    def test_a_clerk_sees_the_own_store_and_never_the_company_commission(self):
        got = self.lines()
        self.assertEqual([(r["date"], r["kind"], r["commission"]) for r in got["rows"]], [
            ("2026-09-20", "sale", "6000.00"), ("2026-09-22", "sale", "6000.00"),
            ("2026-09-25", "return", "-6000.00")])
        self.assertEqual((got["totals"], got["manager"]), ({"commission": "6000.00"}, False))
        for extra in ("", f"&warehouse={self.wh2.id}"):
            text = self.clerk.get(f"{LINES}?{SEP_Q}{extra}").content.decode()
            self.assertNotIn("company_commission", text)
            self.assertNotIn("10000", text)
            self.assertNotIn("民生", text)

    def test_the_total_is_the_same_number_as_the_staff_report(self):
        for client in (self.admin, self.clerk):
            self.assertEqual(self.lines(client)["totals"]["commission"],
                             self.preset("staff", client)["totals"]["net_staff_commission"])
        # 只看到退的那一天之前:原本那一列還在、佣金還算;退的那一天才扣
        r = self.admin.get(f"{LINES}?from=2026-09-01&to=2026-09-24").json()
        self.assertEqual((r["row_count"], r["totals"]["commission"]), (3, "18000.00"))
        r = self.admin.get(f"{PRESET}staff/?from=2026-09-01&to=2026-09-24").json()
        self.assertEqual(r["totals"]["net_staff_commission"], "18000.00")

    def test_void_orders_and_plan_without_company_commission(self):
        TelecomPlan.objects.filter(pk=self.c.plan.pk).update(company_commission=None)
        extra = self.c._post("/api/v1/sales-orders/", {
            "customer": self.c.customer.id, "warehouse": self.wh1.id, "tax_method": "untaxed", "payments": [],
            "items": [{"product": self.c.case.id, "qty": 1, "unit_price": "0", "msisdn": "0922333008",
                       "telecom_plan": self.c.plan.id, "activation_date": "2026-09-20"}]})
        SalesOrder.objects.filter(pk=extra["id"]).update(doc_date=date(2026, 9, 28))
        got = self.lines(self.admin)
        last = got["rows"][-1]
        # 方案當時沒設定公司佣金:那一列是空的(不是 0),合計不把它當 0 以外的數字
        self.assertEqual((last["doc_no"], last["commission"], last["company_commission"]),
                         (extra["no"], "6000.00", None))
        self.assertEqual(got["totals"], {"commission": "18000.00", "company_commission": "20000.00"})
        r = self.admin.post(f"/api/v1/sales-orders/{extra['id']}/void/", {"reason": "打錯"}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        got = self.lines(self.admin)
        self.assertEqual((got["row_count"], got["totals"]["commission"]), (4, "12000.00"))

    def test_both_ends_of_the_period_count(self):
        def between(first, last):
            return self.admin.get(f"{LINES}?from=2026-09-{first}&to=2026-09-{last}").json()

        got = between(20, 22)                                   # 銷貨4(20 日)與銷貨6(22 日)都在邊上
        self.assertEqual((got["row_count"], got["totals"]["commission"]), (3, "18000.00"))
        got = between(22, 25)                                   # 銷貨6 與它的銷退(25 日)
        self.assertEqual([(r["kind"], r["commission"]) for r in got["rows"]],
                         [("sale", "6000.00"), ("return", "-6000.00")])
        self.assertEqual(got["totals"]["commission"], "0.00")
        got = between(25, 25)
        self.assertEqual((got["row_count"], got["totals"]["commission"]), (1, "-6000.00"))
        got = between(23, 24)
        self.assertEqual((got["row_count"], got["totals"]["commission"]), (0, "0.00"))

    def test_a_void_return_no_longer_takes_the_commission_back(self):
        r = self.admin.post(f"/api/v1/sales-returns/{self.c.sr6['id']}/void/", {"reason": "退錯"}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        got = self.lines(self.admin)
        self.assertEqual([r["kind"] for r in got["rows"]], ["sale", "sale", "sale"])
        self.assertEqual(got["totals"], {"commission": "18000.00", "company_commission": "30000.00"})
        self.assertEqual(self.preset("staff", self.admin)["totals"]["net_staff_commission"], "18000.00")

    def test_bad_dates(self):
        for query, text in (("", "開始日期的格式"), ("from=2026-09-01&to=x", "結束日期的格式"),
                            ("from=2026-09-30&to=2026-09-01", "結束日期不能早於"),
                            ("from=2025-09-01&to=2026-09-02", "一次最多看一年")):
            r = self.admin.get(f"{LINES}?{query}")
            self.assertEqual((r.status_code, text in r.json()["detail"]), (400, True), query)
        self.assertEqual(self.admin.get(f"{LINES}?from=2025-09-01&to=2026-09-01").status_code, 200)

    def test_only_reads(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as ctx:
            self.lines(self.admin)
            self.preset("staff", self.admin)
        writes = [q["sql"] for q in ctx.captured_queries
                  if q["sql"].lstrip().split(" ", 1)[0].upper() in ("INSERT", "UPDATE", "DELETE")]
        self.assertEqual(writes, [])
