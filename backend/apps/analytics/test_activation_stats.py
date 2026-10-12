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


OCT = {"from": "2026-10-01", "to": "2026-10-31"}
START = ("started_new", "started_renewal", "started_portin", "return_started", "started_net")
START_MONEY = ("started_net_staff_commission", "started_net_company_commission")


def started(values):
    """(新辦, 續約, 攜碼, 退掉, 淨開通)—— 照上線日"""
    return tuple(values[k] for k in START)


class StartDateTests(_Lines):
    """開通統計照上線日看(owner 2026-10-12)。上線日 = 合約從哪一天起算;電信商照它算佣金與達標。

    把 _Lines 的五門排成:
      s4 中華續約 第一家門市 開單 9/20 上線 9/20
      s5 中華續約 第二家門市 開單 9/21 上線 **10/02**(手機到貨才續約,跨月)、沒有業務員
      s6 中華續約 第一家門市 開單 9/22 上線 9/20,9/25 整張退掉
      s8 遠傳新辦 第一家門市 開單 9/23 上線 9/23
      s9 中華攜碼 第二家門市 開單 9/24 **還沒填上線日**
    """

    def setUp(self):
        super().setUp()
        self.set_start(self.c.s5, date(2026, 10, 2))
        self.set_start(self.s8, date(2026, 9, 23))        # 新辦存檔時上線日 = 當下的單據日期(今天),這裡跟著測試的開單日
        self.set_start(self.s9, None)

    @staticmethod
    def set_start(so, day):
        from apps.sales.models import SalesOrderItem

        SalesOrderItem.objects.filter(so_id=so["id"]).update(activation_date=day)

    def by_start(self, client=None, **params):
        return self.report(client, date="start", **params)

    def test_the_period_is_the_start_date(self):
        data = self.by_start()
        self.assertEqual((data["date"], data["dates"]), ("start", [
            {"key": "doc", "label": "開單日"}, {"key": "start", "label": "上線日"}]))
        self.assertEqual(len({len(d["label"]) for d in data["dates"]}), 1)              # 下拉的字一樣長
        self.assertEqual([m["label"] for m in data["columns"]["measures"]],
                         ["新辦", "續約", "攜碼", "退掉", "淨開通", "業務員佣金", "公司佣金"])     # 欄名跟照開單日一樣
        self.assertEqual(data["note"], "佣金已扣銷退")
        # 九月上線的:中華續約兩門(s4、s6;s5 十月才上線、s9 還沒填)、退掉一門(s6);遠傳新辦一門
        self.assertEqual(self.table(data), {
            "甲中華電信": {"started_new": 0, "started_renewal": 2, "started_portin": 0, "return_started": 1,
                       "started_net": 1, "started_net_staff_commission": "6000.00",
                       "started_net_company_commission": "10000.00"},
            "甲遠傳": {"started_new": 1, "started_renewal": 0, "started_portin": 0, "return_started": 0,
                     "started_net": 1, "started_net_staff_commission": "2000.00",
                     "started_net_company_commission": "3500.00"},
        })
        self.assertEqual((started(data["totals"]), data["totals"]["started_net_staff_commission"],
                          data["totals"]["started_net_company_commission"]), ((1, 2, 0, 1, 2), "8000.00", "13500.00"))
        # 十月上線的:九月開單、十月才續約的那一門
        octo = self.by_start(**OCT)
        self.assertEqual(self.table(octo), {"甲中華電信": {
            "started_new": 0, "started_renewal": 1, "started_portin": 0, "return_started": 0, "started_net": 1,
            "started_net_staff_commission": "6000.00", "started_net_company_commission": "10000.00"}})

    def test_the_default_is_still_the_document_date(self):
        # 不帶、或帶 doc:跟以前一模一樣(照開單日五門都在九月),只是多了「可以看哪幾種日期」
        plain, doc = self.report(), self.report(date="doc")
        self.assertEqual(plain, doc)
        self.assertEqual((plain["date"], [d["key"] for d in plain["dates"]], plain["pending"]), ("doc", ["doc", "start"], ""))
        self.assertEqual(counts(plain["totals"]), (1, 3, 1, 1, 4))
        self.assertEqual(self.report(**OCT)["rows"], [])                                # 照開單日十月沒有東西

    def test_lines_without_a_start_date_are_called_out_wherever_the_period_is(self):
        # 動手前紅隊第 2 條:還沒填的要在正在看的那一段就看得到(不管哪一天開的單)。哪一段期間都一樣
        for period in (SEP, OCT, {"from": "2026-01-01", "to": "2026-01-31"}):
            self.assertEqual(self.by_start(**period)["pending"], "未填上線日 1 門", period)
        self.assertEqual(self.by_start(warehouse=self.wh2.id)["pending"], "未填上線日 1 門")
        self.assertEqual(self.by_start(warehouse=self.wh1.id)["pending"], "")           # 那一門在第二家門市
        # 補填之後不見了、算進那一天
        r = self.admin.post(f"/api/v1/sales-orders/{self.s9['id']}/contract-dates/", {
            "item": self.item_of(self.s9), "activation_date": "2026-09-30"}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        after = self.by_start()
        self.assertEqual((after["pending"], started(after["totals"])), ("", (1, 2, 1, 1, 3)))

    @staticmethod
    def item_of(so):
        from apps.sales.models import SalesOrderItem

        return SalesOrderItem.objects.get(so_id=so["id"]).id

    def test_void_and_returned_lines_are_not_pending(self):
        self.set_start(self.c.s4, None)
        self.set_start(self.c.s6, None)                                                 # 已經整張退掉的
        self.assertEqual(self.by_start()["pending"], "未填上線日 2 門")                   # s4、s9;退掉的 s6 不算
        r = self.admin.post(f"/api/v1/sales-orders/{self.c.s4['id']}/void/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.assertEqual(self.by_start()["pending"], "未填上線日 1 門")                   # 作廢的不算
        # 銷退作廢之後那一門又是有效的:又要填了
        r = self.admin.post(f"/api/v1/sales-returns/{self.c.sr6['id']}/void/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.assertEqual(self.by_start()["pending"], "未填上線日 2 門")

    def test_a_return_comes_off_on_the_day_it_came_back_not_the_start_month(self):
        # 動手前紅隊第 1 條:電信商追回佣金出在後來那一期,不會回頭改上線那個月。九月上線、十月才退 → 九月不變、十月扣
        SalesReturn.objects.filter(pk=self.c.sr6["id"]).update(doc_date=date(2026, 10, 5))
        sep, octo = self.by_start(), self.by_start(**OCT)
        self.assertEqual((started(sep["totals"]), sep["totals"]["started_net_staff_commission"]), ((1, 2, 0, 0, 3), "14000.00"))
        # 十月:上線一門(s5)、退掉一門(九月上線的 s6)→ 淨開通 0、佣金 6,000 − 6,000
        self.assertEqual((started(octo["totals"]), octo["totals"]["started_net_staff_commission"],
                          octo["totals"]["started_net_company_commission"]), ((0, 1, 0, 1, 0), "0.00", "0.00"))

    def test_returning_a_line_that_never_had_a_start_date_takes_nothing_off(self):
        # 沒填上線日的那一門當初沒有算進任何一期,退掉時也不能扣(不然憑空少一門、佣金多扣一次)
        sr = self.c._post("/api/v1/sales-returns/", {"original_so": self.s9["id"]})
        SalesReturn.objects.filter(pk=sr["id"]).update(doc_date=date(2026, 9, 26))
        data = self.by_start()
        self.assertEqual((started(data["totals"]), data["totals"]["started_net_staff_commission"],
                          data["totals"]["started_net_company_commission"], data["pending"]),
                         ((1, 2, 0, 1, 2), "8000.00", "13500.00", ""))                    # 兩種佣金都沒有多扣
        # 對照:照開單日那一門有算(成交一門、退一門)
        self.assertEqual(counts(self.report()["totals"]), (1, 3, 1, 2, 3))

    def test_a_returned_line_that_is_not_a_phone_line_is_never_a_returned_start(self):
        # 退掉的門數只算門號那一行。不是門號的明細不會有上線日(存檔時會擋);這裡直接改資料庫造一筆,釘住「退掉」數的是門號
        from apps.sales.models import SalesOrderItem

        so = self.c.sell(case_qty=1)
        SalesOrder.objects.filter(pk=so["id"]).update(doc_date=date(2026, 9, 18))
        SalesOrderItem.objects.filter(so_id=so["id"]).update(activation_date=date(2026, 9, 18))
        sr = self.c._post("/api/v1/sales-returns/", {"original_so": so["id"], "payment_method": "cash"})
        SalesReturn.objects.filter(pk=sr["id"]).update(doc_date=date(2026, 9, 19))
        self.assertEqual(started(self.by_start()["totals"]), (1, 2, 0, 1, 2))            # 退掉還是只有 s6 那一門

    def test_the_columns_add_up_and_every_grouping_agrees(self):
        expected = {
            "plan": {"甲1399 30月": (0, 2, 0, 1, 1), "甲599 24月": (1, 0, 0, 0, 1)},
            "sales_person": {self.c.sales_person.name: (1, 2, 0, 1, 2)},
            "warehouse": {self.wh1.name: (1, 2, 0, 1, 2)},
        }
        first = self.by_start()["totals"]
        for by, rows in expected.items():
            data = self.by_start(by=by)
            self.assertEqual({label: started(v) for label, v in self.table(data).items()}, rows, by)
            self.assertEqual(data["totals"], first, by)
            for values in [r["values"] for r in data["rows"]] + [data["totals"]]:
                new, renewal, portin, back, net = started(values)
                self.assertEqual(new + renewal + portin - back, net, by)
            for key in START_MONEY:
                self.assertEqual(sum(Decimal(r["values"][key]) for r in data["rows"]), Decimal(first[key]), (by, key))

    def test_both_ends_of_the_period_count_and_void_orders_do_not(self):
        def net(first, last):
            return self.by_start(**{"from": first, "to": last})["totals"]["started_net"]

        self.assertEqual((net("2026-09-20", "2026-09-20"), net("2026-09-21", "2026-09-22"),
                          net("2026-09-23", "2026-09-23"), net("2026-09-25", "2026-09-25"),
                          net("2026-10-02", "2026-10-02"), net("2026-10-01", "2026-10-01")), (2, 0, 1, -1, 1, 0))
        r = self.admin.post(f"/api/v1/sales-orders/{self.c.s4['id']}/void/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.assertEqual(net("2026-09-20", "2026-09-20"), 1)

    def test_moving_the_start_date_moves_the_line(self):
        # 上線日事後改到別的月份(中華等手機到貨才續約):報表跟著變
        r = self.admin.post(f"/api/v1/sales-orders/{self.c.s4['id']}/contract-dates/", {
            "item": self.item_of(self.c.s4), "activation_date": "2026-10-10"}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.assertEqual((started(self.by_start()["totals"]), started(self.by_start(**OCT)["totals"])),
                         ((1, 1, 0, 1, 1), (0, 2, 0, 0, 2)))
        self.assertEqual(counts(self.report()["totals"]), (1, 3, 1, 1, 4))               # 照開單日的不受影響

    def test_most_lines_first(self):
        self.line(self.plan2, "0922333028", 23, self.wh1)                                # 遠傳再一門(新辦:上線日要另外設)
        from apps.sales.models import SalesOrderItem
        SalesOrderItem.objects.filter(msisdn="0922333028").update(activation_date=date(2026, 9, 23))
        data = self.by_start()
        self.assertEqual([(r["dims"][0]["label"], r["values"]["started_net"]) for r in data["rows"]],
                         [("甲遠傳", 2), ("甲中華電信", 1)])                               # 照門數(遠傳佣金 4,000 < 中華 6,000)

    def test_clerk_sees_own_store_without_the_company_commission(self):
        self.set_start(self.c.s5, None)                                                 # 第二家門市兩門都還沒填
        mine = self.by_start(client=self.clerk, warehouse=self.wh2.id, by="warehouse")   # 網址帶別家的編號沒有用
        allowed = {*START, "started_net_staff_commission"}
        self.assertEqual([m["key"] for m in mine["columns"]["measures"]], [*START, "started_net_staff_commission"])
        self.assertEqual(set(mine["totals"]), allowed)
        self.assertTrue(mine["rows"] and all(set(r["values"]) == allowed for r in mine["rows"]))
        self.assertNotIn("company", str(mine))
        self.assertEqual({label: started(v) for label, v in self.table(mine).items()}, {self.wh1.name: (1, 2, 0, 1, 2)})
        # 還沒填的只算自己門市的(第二家的兩門不關這個店員的事)
        self.assertEqual(mine["pending"], "")
        self.assertEqual(self.by_start()["pending"], "未填上線日 2 門")
        self.set_start(self.c.s4, None)
        self.assertEqual(self.by_start(client=self.clerk, warehouse=self.wh2.id)["pending"], "未填上線日 1 門")
        exported = self.by_start(client=self.clerk, export="1")
        self.assertEqual(set(exported["totals"]), allowed)
        self.assertNotIn("company", str(exported))

    def test_same_item_and_export_and_bad_dates(self):
        shown, exported = self.by_start(by="plan"), self.by_start(by="plan", export="1")
        self.assertEqual((exported["rows"], exported["totals"], exported["date"], exported["pending"]),
                         (shown["rows"], shown["totals"], "start", shown["pending"]))
        r = self.admin.get(URL, {**SEP, "date": "nope"})
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "這張報表不能照這個日期看"))
        # 別張報表沒有第二種日期:送 start 是打錯,不默默當成預設
        r = self.admin.get(f"{PRESET}staff/", {**SEP, "date": "start"})
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "這張報表不能照這個日期看"))
        staff = self.admin.get(f"{PRESET}staff/", {**SEP, "date": "doc"})
        self.assertEqual((staff.status_code, staff.json()["dates"], staff.json()["pending"]), (200, [], ""))
        # 同一個勾:關掉之後照上線日也看不到
        UserProfile.objects.filter(user=self.c.clerk_user).update(denied_abilities=["report_activations"])
        clerk = Company.client(get_user_model().objects.get(pk=self.c.clerk_user.pk))
        self.assertDenied(clerk.get(URL, {**SEP, "date": "start"}), "開通統計")

    def test_another_company_is_never_mixed_in(self):
        from apps.sales.models import SalesOrderItem

        from .test_report_access import add_lines
        from .tests import build_shop

        other = add_lines(build_shop("b", "乙通訊行", "乙"), "乙")
        SalesOrderItem.objects.filter(tenant=other.tenant, telecom_plan__isnull=False, so_id=other.s4["id"]).update(
            activation_date=None)
        data = self.by_start()
        self.assertEqual(set(self.table(data)), {"甲中華電信", "甲遠傳"})
        self.assertEqual((data["totals"]["started_net"], data["pending"]), (2, "未填上線日 1 門"))
        theirs = other.admin.get(URL, {**SEP, "date": "start"}).json()
        self.assertEqual((theirs["totals"]["started_net"], theirs["pending"]), (1, "未填上線日 1 門"))

    def test_the_new_measures_in_explore(self):
        q = lambda client, *measures, **spec: client.post(                              # noqa: E731
            QUERY, {"measures": list(measures), "period": SEP, **spec}, format="json")
        r = q(self.admin, "started_net", "started_net_company_commission", dimensions=["carrier"])
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.assertEqual(self.table(r.json())["甲中華電信"], {"started_net": 1, "started_net_company_commission": "10000.00"})
        # 公司佣金那三個只有管理員看得到(直接的、沖回的、扣掉之後的)
        for key in ("started_company_commission", "return_started_company_commission", "started_net_company_commission"):
            self.assertEqual(q(self.clerk, key).status_code, 400, key)
            self.assertEqual(q(self.admin, key).status_code, 200, key)
        seen = {m["key"] for m in self.clerk.get("/api/v1/analytics/catalog/").json()["measures"]}
        self.assertFalse({k for k in seen if "company" in k})
        self.assertTrue({"started_net", "started_new", "started_net_staff_commission", "return_started"} <= seen)
        # 歸在既有的類別(選單的類別是固定的那幾個)
        groups = {m["key"]: m["group"] for m in self.admin.get("/api/v1/analytics/catalog/").json()["measures"]}
        self.assertEqual({groups[k] for k in ("started_new", "started_net", "return_started")}, {"門號合約"})
        self.assertEqual({groups[k] for k in ("started_staff_commission", "started_net_company_commission")}, {"佣金"})
        # 跟銷貨一樣可以照門市、業務、電信、方案分;鎖門市的店員只算自己門市
        for measure in ("started_net", "started_net_staff_commission"):
            self.assertTrue({"warehouse", "sales_person", "carrier", "plan", "plan_kind", "date"} <= supported_dims(measure))
        mine = q(self.clerk, "started_net", dimensions=["warehouse"]).json()
        self.assertEqual(self.table(mine), {self.wh1.name: {"started_net": 2}})


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
