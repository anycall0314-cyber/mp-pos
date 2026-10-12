"""開通統計(固定報表)與自訂分析的門號角度(owner 2026-10-12;取舊歐睿 SIM031 開通數量統計)。

逐筆的是佣金明細(`sales/commission_views.py`)。這一張的規則全部沿用那一頁與業績彙總的門號佣金:
有方案的那一行 = 一門;作廢的單不算;退掉的扣在退的那一天。
"""
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase

from apps.backup.tests.factory import Company
from apps.parties.models import Carrier, SimCard, TelecomPlan
from apps.sales.models import SalesOrder, SalesReturn
from apps.tenants import abilities
from apps.tenants.models import UserProfile

from . import presets
from .catalog import NOT_A_LINE, PLAN_KINDS, supported_dims
from .test_report_access import LINES, PRESET, QUERY, SEP_Q, _Shop

URL = f"{PRESET}activations/"
SEP = {"from": "2026-09-01", "to": "2026-09-30"}
COUNTS = ("activations_new", "activations_renewal", "activations_portin", "return_activations", "net_activations")
MONEY = ("net_staff_commission", "net_company_commission")


def counts(values):
    """(新辦, 續約, 攜碼, 退掉, 淨開通)"""
    return tuple(values[k] for k in COUNTS)


class KindListTests(SimpleTestCase):
    def test_the_three_kinds_are_the_ones_on_the_plan(self):
        # 方案多一種、改了名字,報表的欄要跟著改(catalog.PLAN_KINDS 是另外列的一份)
        self.assertEqual(PLAN_KINDS, tuple(TelecomPlan.Kind.choices))


class _Lines(_Shop):
    """九月的門號(_Shop 已經有中華續約三門:第一家門市 9/20、9/22(9/25 整張退掉),第二家門市 9/21、沒有業務員),
    這裡再加:遠傳新辦一門(第一家門市 9/23)、中華攜碼一門(第二家門市 9/24)。另外有不是門號的銷貨(手機、皮套、收購)。"""

    def setUp(self):
        super().setUp()
        c = self.c
        self.fet = Carrier.objects.create(tenant=c.tenant, code="FET", name="甲遠傳")
        self.plan2 = TelecomPlan.objects.create(
            tenant=c.tenant, carrier=self.fet, name="甲599 24月", monthly_fee=599, contract_months=24,
            kind="new", commission=Decimal("2000"), company_commission=Decimal("3500"))
        self.plan3 = TelecomPlan.objects.create(
            tenant=c.tenant, carrier=c.carrier, name="甲999 攜碼", monthly_fee=999, contract_months=30,
            kind="portin", commission=Decimal("3000"), company_commission=Decimal("5000"))
        self.s8 = self.line(self.plan2, "0922333018", 23, self.wh1)
        self.s9 = self.line(self.plan3, "0922333019", 24, self.wh2)

    def line(self, plan, msisdn, day, warehouse):
        card = SimCard.objects.create(tenant=self.c.tenant, vendor=plan.carrier, card_no=f"89886000{msisdn[-4:]}")
        so = self.c._post("/api/v1/sales-orders/", {
            "customer": self.c.customer.id, "warehouse": warehouse.id, "tax_method": "untaxed",
            "payments": [], "sales_person": self.c.sales_person.id,
            "items": [{"product": self.c.case.id, "qty": 1, "unit_price": "0", "msisdn": msisdn,
                       "telecom_plan": plan.id, "sim_card": card.id, "activation_date": f"2026-09-{day:02d}"}]})
        SalesOrder.objects.filter(pk=so["id"]).update(doc_date=date(2026, 9, day))
        return so

    def report(self, client=None, **params):
        r = (client or self.admin).get(URL, {**SEP, **params})
        self.assertEqual(r.status_code, 200, r.content.decode())
        return r.json()

    def counted(self, data):
        return {label: counts(values) for label, values in self.table(data).items()}


class ActivationStatsTests(_Lines):
    def test_by_carrier(self):
        data = self.report()
        # 畫面上的「業務」送出去的是照業務員分(不是只有字對):代碼與字一起釘住
        self.assertEqual((data["title"], [(b["key"], b["label"]) for b in data["by"]]), ("開通統計", [
            ("carrier", "電信"), ("plan", "方案"), ("sales_person", "業務"), ("warehouse", "門市")]))
        # 期間旁邊那幾個字:這一張的新辦 / 續約 / 攜碼是成交的數(退掉的另外一欄),不能跟別張一樣寫「已扣銷退」
        self.assertEqual((data["note"], self.preset("staff", self.admin)["note"]), ("佣金已扣銷退", "已扣銷退"))
        self.assertEqual([m["label"] for m in data["columns"]["measures"]],
                         ["新辦", "續約", "攜碼", "退掉", "淨開通", "業務員佣金", "公司佣金"])
        # 中華:續約三門、攜碼一門、退一門 = 3;佣金 6,000 × 3 + 3,000 − 6,000。不是門號的銷貨不列
        self.assertEqual(self.table(data), {
            "甲中華電信": {"activations_new": 0, "activations_renewal": 3, "activations_portin": 1,
                       "return_activations": 1, "net_activations": 3,
                       "net_staff_commission": "15000.00", "net_company_commission": "25000.00"},
            "甲遠傳": {"activations_new": 1, "activations_renewal": 0, "activations_portin": 0,
                     "return_activations": 0, "net_activations": 1,
                     "net_staff_commission": "2000.00", "net_company_commission": "3500.00"},
        })
        self.assertEqual([r["dims"][0]["label"] for r in data["rows"]], ["甲中華電信", "甲遠傳"])     # 開得多的在前面
        self.assertEqual((counts(data["totals"]), data["totals"]["net_staff_commission"], data["totals"]["net_company_commission"]),
                         ((1, 3, 1, 1, 4), "17000.00", "28500.00"))

    def test_the_most_activations_come_first(self):
        # 9/23 ~ 9/25:遠傳新辦一門;中華攜碼一門、退掉一門(淨開通 0)。照淨開通排,不是照建立的先後或名稱
        def order(first, last):
            data = self.report(**{"from": f"2026-09-{first}", "to": f"2026-09-{last}"})
            return [(r["dims"][0]["label"], r["values"]["net_activations"]) for r in data["rows"]]

        self.assertEqual(order(23, 25), [("甲遠傳", 1), ("甲中華電信", 0)])
        # 照門數,不是照佣金:9/22 ~ 9/23 遠傳兩門(佣金 4,000)排在中華一門(佣金 6,000)前面
        self.line(self.plan2, "0922333028", 23, self.wh1)
        self.assertEqual(order(22, 23), [("甲遠傳", 2), ("甲中華電信", 1)])

    def test_every_grouping_adds_up_to_the_same_totals(self):
        expected = {
            "plan": {"甲1399 30月": (0, 3, 0, 1, 2), "甲599 24月": (1, 0, 0, 0, 1), "甲999 攜碼": (0, 0, 1, 0, 1)},
            # 第二家門市 9/21 那一門沒有填業務員
            "sales_person": {self.c.sales_person.name: (1, 2, 1, 1, 3), "(未指定)": (0, 1, 0, 0, 1)},
            "warehouse": {self.wh1.name: (1, 2, 0, 1, 2), self.wh2.name: (0, 1, 1, 0, 2)},
        }
        first = self.report()["totals"]
        for by, rows in expected.items():
            data = self.report(by=by)
            self.assertEqual(self.counted(data), rows, by)
            self.assertEqual(data["totals"], first, by)
            for key in COUNTS:
                self.assertEqual(sum(r["values"][key] for r in data["rows"]), first[key], (by, key))
            for key in MONEY:
                self.assertEqual(sum(Decimal(r["values"][key]) for r in data["rows"]), Decimal(first[key]), (by, key))

    def test_the_columns_add_up(self):
        # 新辦 + 續約 + 攜碼 − 退掉 = 淨開通:每一列、合計都是
        data = self.report(by="sales_person")
        for values in [r["values"] for r in data["rows"]] + [data["totals"]]:
            new, renewal, portin, back, net = counts(values)
            self.assertEqual(new + renewal + portin - back, net)

    def test_same_numbers_as_the_commission_lines_and_the_staff_report(self):
        lines = self.admin.get(f"{LINES}?{SEP_Q}").json()
        kinds = [r["kind"] for r in lines["rows"]]
        totals = self.report()["totals"]
        self.assertEqual((totals["net_activations"], totals["return_activations"]),
                         (kinds.count("sale") - kinds.count("return"), kinds.count("return")))
        self.assertEqual((totals["net_staff_commission"], totals["net_company_commission"]),
                         (lines["totals"]["commission"], lines["totals"]["company_commission"]))
        self.assertEqual(self.preset("staff", self.admin)["totals"]["net_staff_commission"], totals["net_staff_commission"])

    def test_a_return_comes_off_on_the_day_it_came_back(self):
        # 9/22 開的那一門 9/25 退:9/24 以前還算四門(沒有退掉的),退的那一段是負的一門(不回頭改成交那幾天的數字)
        before = self.report(to="2026-09-24")
        self.assertEqual((self.counted(before)["甲中華電信"], self.table(before)["甲中華電信"]["net_staff_commission"]),
                         ((0, 3, 1, 0, 4), "21000.00"))
        after = self.report(**{"from": "2026-09-25"})
        self.assertEqual(self.table(after), {"甲中華電信": {
            "activations_new": 0, "activations_renewal": 0, "activations_portin": 0,
            "return_activations": 1, "net_activations": -1,
            "net_staff_commission": "-6000.00", "net_company_commission": "-10000.00"}})
        # 那張銷退作廢之後,那一門又算回來
        r = self.admin.post(f"/api/v1/sales-returns/{self.c.sr6['id']}/void/", {"reason": "退錯"}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.assertEqual(counts(self.report()["totals"]), (1, 3, 1, 0, 5))
        self.assertEqual(self.report(**{"from": "2026-09-25"})["rows"], [])

    def test_sold_and_returned_in_the_same_period_still_shows(self):
        # 只看 9/25 那一天:只有退掉的一門。把那一門的成交也挪到同一天 → 開一門、退一門,淨開通是 0,但這一列要在
        data = self.report(**{"from": "2026-09-25", "to": "2026-09-25"})
        self.assertEqual(self.counted(data), {"甲中華電信": (0, 0, 0, 1, -1)})
        SalesOrder.objects.filter(pk=self.c.s6["id"]).update(doc_date=date(2026, 9, 25))
        data = self.report(**{"from": "2026-09-25", "to": "2026-09-25"})
        self.assertEqual(self.counted(data), {"甲中華電信": (0, 1, 0, 1, 0)})

    def test_a_return_follows_its_own_line(self):
        # 同一張單有一個皮套 + 一門續約,整張退:退掉的門號是一門(看的是被退的那一行,不是那張單上的每一行),
        # 皮套那一行的退貨不算在任何一家電信
        so = self.c._post("/api/v1/sales-orders/", {
            "customer": self.c.customer.id, "warehouse": self.wh1.id, "tax_method": "untaxed",
            "sales_person": self.c.sales_person.id,
            "items": [{"product": self.c.case.id, "qty": 1, "unit_price": "390"},
                      {"product": self.c.case.id, "qty": 1, "unit_price": "0", "msisdn": "0922333020",
                       "telecom_plan": self.c.plan.id, "activation_date": "2026-09-26"}],
            "payments": [{"method": "cash", "amount": "390"}]})
        SalesOrder.objects.filter(pk=so["id"]).update(doc_date=date(2026, 9, 26))
        back = self.c._post("/api/v1/sales-returns/", {"original_so": so["id"], "payment_method": "cash"})
        SalesReturn.objects.filter(pk=back["id"]).update(doc_date=date(2026, 9, 27))
        data = self.report()
        self.assertEqual(self.counted(data), {"甲中華電信": (0, 4, 1, 2, 3), "甲遠傳": (1, 0, 0, 0, 1)})
        self.assertEqual(counts(data["totals"]), (1, 4, 1, 2, 4))
        for by in ("plan", "sales_person", "warehouse"):
            rows = self.report(by=by)["rows"]
            self.assertEqual(sum(r["values"]["return_activations"] for r in rows), 2, by)
        # 自訂分析:皮套那一行的銷退在「(不是門號)」那一列,不會跑到中華那一列
        r = self.admin.post(QUERY, {"measures": ["return_qty", "return_activations"], "dimensions": ["carrier"],
                                    "period": SEP}, format="json").json()
        rows = {row["dims"][0]["label"]: row["values"] for row in r["rows"]}
        self.assertEqual(rows["甲中華電信"], {"return_qty": 2, "return_activations": 2})
        self.assertEqual(rows[NOT_A_LINE]["return_activations"], 0)
        self.assertEqual(sum(v["return_qty"] for v in rows.values()), r["totals"]["return_qty"])

    def test_void_orders_do_not_count(self):
        r = self.admin.post(f"/api/v1/sales-orders/{self.s8['id']}/void/", {"reason": "打錯"}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        data = self.report()
        self.assertEqual(set(self.table(data)), {"甲中華電信"})
        self.assertEqual(counts(data["totals"]), (0, 3, 1, 1, 3))

    def test_both_ends_of_the_period_count(self):
        # 9/20、9/21、9/22(9/25 退)、9/23、9/24 各一門
        def net(first, last):
            return self.report(**{"from": f"2026-09-{first}", "to": f"2026-09-{last}"})["totals"]["net_activations"]

        self.assertEqual((net(20, 20), net(21, 23), net(24, 24), net(25, 25), net(20, 25)), (1, 3, 1, -1, 4))

    def test_clerk_sees_own_store_without_the_company_commission(self):
        mine = self.report(client=self.clerk, warehouse=self.wh2.id, by="warehouse")     # 網址帶別家的編號沒有用
        allowed = {*COUNTS, "net_staff_commission"}
        self.assertEqual([m["key"] for m in mine["columns"]["measures"]], [*COUNTS, "net_staff_commission"])
        # 每一列、合計、匯出的回應裡都沒有公司佣金(不只是欄名沒列)
        self.assertEqual(set(mine["totals"]), allowed)
        self.assertTrue(mine["rows"] and all(set(r["values"]) == allowed for r in mine["rows"]))
        self.assertNotIn("company", str(mine))
        self.assertEqual(self.counted(mine), {self.wh1.name: (1, 2, 0, 1, 2)})
        self.assertEqual(mine["totals"]["net_staff_commission"], "8000.00")
        exported = self.report(client=self.clerk, export="1")
        self.assertEqual(set(exported["totals"]), allowed)
        self.assertTrue(exported["rows"] and all(set(r["values"]) == allowed for r in exported["rows"]))
        self.assertNotIn("company", str(exported))

    def test_needs_its_own_item_and_explore_follows(self):
        self.assertEqual(presets.REPORTS["activations"].ability, abilities.REPORT_ACTIVATIONS)
        self.assertEqual(self.clerk.get(URL, SEP).status_code, 200)
        UserProfile.objects.filter(user=self.c.clerk_user).update(denied_abilities=["report_activations"])
        clerk = Company.client(get_user_model().objects.get(pk=self.c.clerk_user.pk))
        self.assertDenied(clerk.get(URL, SEP), "開通統計")
        # 自訂分析挑「開通數 × 電信業者」就組得出同一張表:這一張關掉,自訂分析也跟著不能用
        spec = {"measures": ["net_activations"], "dimensions": ["carrier"], "period": SEP}
        self.assertDenied(clerk.post(QUERY, spec, format="json"), "開通統計")
        self.assertEqual(self.admin.post(QUERY, spec, format="json").status_code, 200)
        # 佣金明細是另外一個勾:關掉它不影響這一張
        UserProfile.objects.filter(user=self.c.clerk_user).update(denied_abilities=["report_commission"])
        other = Company.client(get_user_model().objects.get(pk=self.c.clerk_user.pk))
        self.assertEqual(other.get(URL, SEP).status_code, 200)

    def test_export_is_the_same_table(self):
        shown, exported = self.report(by="plan"), self.report(by="plan", export="1")
        self.assertEqual((exported["rows"], exported["totals"], exported["truncated"]),
                         (shown["rows"], shown["totals"], False))

    def test_another_company_is_never_mixed_in(self):
        from .test_report_access import add_lines
        from .tests import build_shop

        add_lines(build_shop("b", "乙通訊行", "乙"), "乙")
        data = self.report()
        self.assertEqual(set(self.table(data)), {"甲中華電信", "甲遠傳"})
        self.assertEqual(data["totals"]["net_activations"], 4)


class PlanDimensionTests(_Lines):
    """自訂分析的「電信業者」「方案種類」「方案」:銷貨、銷退那幾組指標也能用了。"""

    def query(self, client=None, **spec):
        return (client or self.admin).post(QUERY, {"period": SEP, **spec}, format="json")

    def test_which_measures_can_be_split_by_plan(self):
        dims = {"carrier", "plan_kind", "plan"}
        for measure in ("net_activations", "activations", "activations_new", "return_activations", "net_sales",
                        "sales_orders", "net_staff_commission", "net_company_commission", "contracts_due"):
            self.assertTrue(dims <= supported_dims(measure), measure)
        for measure in ("purchase_untaxed", "stock_qty", "received", "net_received", "legacy_net"):
            self.assertFalse(dims & supported_dims(measure), measure)

    def test_lines_without_a_plan_are_one_row(self):
        r = self.query(measures=["net_sales", "net_activations"], dimensions=["carrier"])
        self.assertEqual(r.status_code, 200, r.content.decode())
        rows = {row["dims"][0]["label"]: row["values"] for row in r.json()["rows"]}
        self.assertEqual(set(rows), {"甲中華電信", "甲遠傳", NOT_A_LINE})
        # 門號那幾行單價是 0;九月其他的銷貨(手機、皮套)都在「(不是門號)」那一列、開通數是 0
        self.assertEqual((rows[NOT_A_LINE]["net_activations"], rows["甲中華電信"]["net_sales"]), (0, "0.00"))
        whole = self.query(measures=["net_sales"]).json()["totals"]["net_sales"]
        self.assertEqual(rows[NOT_A_LINE]["net_sales"], whole)
        self.assertNotEqual(Decimal(whole), 0)

    def test_the_kind_as_a_grouping_matches_the_kind_columns(self):
        by_kind = self.query(measures=["activations", "return_activations", "net_activations"], dimensions=["plan_kind"]).json()
        rows = {row["dims"][0]["label"]: row["values"] for row in by_kind["rows"]}
        self.assertEqual({k: (v["activations"], v["return_activations"], v["net_activations"]) for k, v in rows.items() if k != NOT_A_LINE},
                         {"新辦": (1, 0, 1), "續約": (3, 1, 2), "攜碼": (1, 0, 1)})
        columns = self.query(measures=["activations_new", "activations_renewal", "activations_portin", "activations"]).json()["totals"]
        self.assertEqual(columns, {"activations_new": 1, "activations_renewal": 3, "activations_portin": 1, "activations": 5})

    def test_filter_by_plan_and_kind(self):
        only = self.query(measures=["net_activations", "net_staff_commission"], dimensions=["warehouse"],
                          filters={"plan": [self.plan2.id]}).json()
        self.assertEqual(only["totals"], {"net_activations": 1, "net_staff_commission": "2000.00"})
        kind = self.query(measures=["net_activations"], filters={"plan_kind": ["renewal"]}).json()
        self.assertEqual(kind["totals"], {"net_activations": 2})
        # 兩個角度一起分:每一門只落在一格
        both = self.query(measures=["net_activations"], dimensions=["carrier", "plan_kind"]).json()
        cells = {tuple(d["label"] for d in row["dims"]): row["values"]["net_activations"] for row in both["rows"]}
        self.assertEqual({k: v for k, v in cells.items() if v},
                         {("甲中華電信", "續約"): 2, ("甲中華電信", "攜碼"): 1, ("甲遠傳", "新辦"): 1})

    def test_measures_without_a_plan_say_so(self):
        r = self.query(measures=["purchase_untaxed"], dimensions=["plan"])
        self.assertEqual(r.status_code, 400)
        self.assertIn("方案", r.json()["detail"])

    def test_options_and_filters_stay_inside_the_company(self):
        other = Company("b", "乙通訊行", "乙")
        carrier = Carrier.objects.create(tenant=other.tenant, code="CHT", name="乙中華電信")
        theirs = TelecomPlan.objects.create(
            tenant=other.tenant, carrier=carrier, name="乙999 24月", monthly_fee=999, contract_months=24,
            kind="new", commission=Decimal("1"))
        names = [o["label"] for o in self.admin.get("/api/v1/analytics/options/?dimension=plan").json()["results"]]
        self.assertEqual(names, ["甲1399 30月", "甲599 24月", "甲999 攜碼"])
        r = self.query(measures=["net_activations"], filters={"plan": [theirs.id]})
        self.assertEqual(r.status_code, 400)                      # 別家公司的方案編號 = 不認得
