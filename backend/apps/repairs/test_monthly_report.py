"""維修毛利只有一份算法(owner 2026-10-12:「工資是分業績的」)與維修月報。"""
from datetime import date, datetime, timezone as dt_timezone
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.backup.tests.factory import Company
from apps.parties.models import SalesPerson
from apps.repairs import report
from apps.repairs.models import RepairOrder, RepairOrderPart
from apps.repairs.services import compute_margin, compute_personal_margin, money_of, way_of
from apps.tenants import abilities
from apps.tenants.models import UserProfile

URL = "/api/v1/repair-monthly-report/"
SEP = {"from": "2026-09-01", "to": "2026-09-30"}
OCT = {"from": "2026-10-01", "to": "2026-10-31"}


def at(month, day, hour=4):
    """世界時間的那一刻(台灣 = 加 8 小時)。"""
    return datetime(2026, month, day, hour, 0, tzinfo=dt_timezone.utc)


class _Repairs(TestCase):
    """九月完工的維修單(零件一個成本 400):
    a 自修、收件人自己修   第一家門市  零件 2 個、工資 500、實付 3,000        → 毛利 2,200
    b 自修、另有技師       第一家門市  零件 1 個、工資 600、實付 2,000        → 毛利 1,600(收件人 1,000、技師 600)
    c 委外給外面的維修廠   第二家門市  委外實際 3,500、實付 5,000(也領了 1 個零件,不算)→ 毛利 1,500
    d 內轉(修的是自己公司的技師)第一家門市 零件 1 個、內部結算價 2,500、實付 4,000 → 毛利 3,600(收件人 1,500、技師 2,100)
    h 沒有填收件人的自修   第一家門市  沒有零件、實付 1,000                    → 毛利 1,000
    另外:e 完工後作廢、f 還在維修中、g 台灣 10/01 凌晨 00:30 完工(世界時間還在 9/30)。
    """

    def setUp(self):
        c = self.c = Company("a", "甲通訊行", "甲")
        self.w1, self.w2 = c.warehouses
        c.purchase(case_qty=30)
        c.purchase(warehouse=self.w2, case_qty=5)
        self.tech = SalesPerson.objects.create(tenant=c.tenant, code="T1", name="甲技師")
        s1, t1 = c.sales_person, self.tech
        self.a = self.make(at(9, 5), parts=2, labor_fee=500, customer_paid_amount=3000, sales_person=s1)
        self.b = self.make(at(9, 6), parts=1, labor_fee=600, customer_paid_amount=2000, sales_person=s1, technician=t1)
        self.c_out = self.make(at(9, 7), warehouse=self.w2, parts=1, mode="external", external_quote_actual=3500,
                               customer_paid_amount=5000, sales_person=s1)
        self.d = self.make(at(9, 8), parts=1, mode="external", technician=t1, internal_settle_amount=2500,
                           external_quote_actual=999, customer_paid_amount=4000, sales_person=s1)
        self.h = self.make(at(9, 9), parts=0, customer_paid_amount=1000)
        self.e = self.make(at(9, 10), parts=1, customer_paid_amount=9999, sales_person=s1, is_void=True)
        self.f = self.make(None, parts=1, customer_paid_amount=8888, sales_person=s1)
        self.g = self.make(at(9, 30, 16), parts=0, customer_paid_amount=700, sales_person=s1)       # 台灣 10/01 00:00

    def make(self, completed_at, *, warehouse=None, parts=1, **fields):
        order = self.c._post("/api/v1/repair-orders/", {
            "warehouse": (warehouse or self.w1).id, "customer": self.c.customer.id,
            "received_date": "2026-09-01", "mode": "in_house", "unlock_method": "none", "host_model_name": "iPhone 15",
            "parts_input": [{"part_product": self.c.case.id, "qty": parts}] if parts else [],
        })
        RepairOrderPart.objects.filter(repair_order_id=order["id"]).update(unit_cost=Decimal("400"))
        if completed_at is not None:
            fields.update(status="completed", completed_at=completed_at)
        RepairOrder.objects.filter(pk=order["id"]).update(**fields)
        return RepairOrder.objects.get(pk=order["id"])

    def report(self, client=None, period=SEP, **params):
        r = (client or self.c.admin).get(URL, {**period, **params})
        self.assertEqual(r.status_code, 200, r.content.decode())
        return r.json()

    @staticmethod
    def numbers(data):
        return [r["doc"]["no"] for r in data["results"]]


class OneMarginTests(_Repairs):
    """同一張維修單,到哪裡看都是同一個毛利。"""

    def test_labor_is_not_a_cost(self):
        # 自修:實付 − 零件成本。工資、內部結算價怎麼改都不影響公司的毛利(只影響兩個人怎麼分)
        self.assertEqual(compute_margin(self.a), Decimal("2200"))
        self.assertEqual(compute_margin(self.b), Decimal("1600"))                 # 以前這裡還多扣了工資 600
        self.assertEqual(compute_margin(self.c_out), Decimal("1500"))             # 委外:實付 − 委外實際費用(領的零件不算)
        self.assertEqual(compute_margin(self.d), Decimal("3600"))                 # 內轉:實付 − 零件成本(不是扣委外實際費用 999)
        RepairOrder.objects.filter(pk__in=[self.b.pk, self.d.pk]).update(labor_fee=99999, internal_settle_amount=1)
        for order in RepairOrder.objects.filter(pk__in=[self.b.pk, self.d.pk]):
            self.assertEqual(compute_margin(order), {self.b.pk: Decimal("1600"), self.d.pk: Decimal("3600")}[order.pk])

    def test_the_two_people_always_add_up_to_it(self):
        for order in (self.a, self.b, self.c_out, self.d, self.h, self.e, self.f, self.g):
            split, money = compute_personal_margin(order), money_of(order)
            self.assertEqual(split["sales_person_amount"] + split["technician_amount"], money["margin"], order.no)
            self.assertEqual(money["paid"] - money["parts"] - money["outside"], money["margin"], order.no)
        self.assertEqual([way_of(o) for o in (self.a, self.b, self.c_out, self.d)],
                         ["in_house", "in_house", "vendor", "transfer"])
        # 委外模式、維修人員填的是收件人自己:不算內轉
        RepairOrder.objects.filter(pk=self.c_out.pk).update(technician=self.c.sales_person)
        self.assertEqual(way_of(RepairOrder.objects.get(pk=self.c_out.pk)), "vendor")

    def test_the_api_gives_the_same_number_everywhere(self):
        got = self.c.admin.get(f"/api/v1/repair-orders/{self.b.pk}/").json()
        self.assertEqual(Decimal(got["margin"]), Decimal("1600"))
        self.assertEqual(Decimal(got["margin_breakdown"]["sales_person_amount"])
                         + Decimal(got["margin_breakdown"]["technician_amount"]), Decimal("1600"))
        listed = self.c.admin.get("/api/v1/repair-orders/").json()
        rows = listed["results"] if isinstance(listed, dict) else listed
        self.assertEqual({r["no"]: Decimal(r["margin"]) for r in rows if r["no"] in (self.a.no, self.d.no)},
                         {self.a.no: Decimal("2200"), self.d.no: Decimal("3600")})
        preview = self.c.admin.get(f"/api/v1/repair-orders/{self.b.pk}/quote-preview/").json()
        self.assertEqual(Decimal(preview["margin"]), Decimal("1600"))
        row = next(r for r in self.report()["results"] if r["doc"]["no"] == self.b.no)
        self.assertEqual(row["margin"], "1600.00")
        # 送來的 margin 不算數
        r = self.c.admin.patch(f"/api/v1/repair-orders/{self.f.pk}/", {"margin": "1"}, format="json")
        self.assertIn(r.status_code, (200, 400))
        self.assertEqual(compute_margin(RepairOrder.objects.get(pk=self.f.pk)), Decimal("8488"))

    def test_the_part_cost_is_the_one_written_on_the_line(self):
        """複審 P0:成本是 0 的零件完工之後,零件後來進貨把平均成本拉高 —— 這張單的毛利不能跟著變,
        而且要跟開單頁算的(每一行記的成本 × 數量)是同一個數字。"""
        RepairOrderPart.objects.filter(repair_order=self.a).update(unit_cost=0)          # 完工時成本就是 0
        type(self.c.case).objects.filter(pk=self.c.case.pk).update(weighted_avg_cost=Decimal("150"))   # 之後才進貨
        order = RepairOrder.objects.get(pk=self.a.pk)
        self.assertEqual((money_of(order)["parts"], compute_margin(order)), (Decimal("0"), Decimal("3000")))
        split = compute_personal_margin(order)
        self.assertEqual(split["sales_person_amount"] + split["technician_amount"], Decimal("3000"))
        # 開單頁拿到的每一行成本 × 數量加起來,實付減掉它 = 伺服器給的毛利(每一張都是;委外給外廠的看委外實際費用)
        for o in (self.a, self.b, self.d, self.h, self.f):
            got = self.c.admin.get(f"/api/v1/repair-orders/{o.pk}/").json()
            on_page = sum(Decimal(p["unit_cost"]) * p["qty"] for p in got["parts"])
            self.assertEqual(Decimal(got["customer_paid_amount"]) - on_page, Decimal(got["margin"]), o.no)
            self.assertEqual(Decimal(got["margin_breakdown"]["sales_person_amount"])
                             + Decimal(got["margin_breakdown"]["technician_amount"]), Decimal(got["margin"]), o.no)
        row = next(r for r in self.report()["results"] if r["doc"]["no"] == self.a.no)
        self.assertEqual((row["parts"], row["margin"]), ("0.00", "3000.00"))


class MonthlyReportTests(_Repairs):
    def test_totals_rows_and_people(self):
        data = self.report()
        self.assertEqual(self.numbers(data), [self.a.no, self.b.no, self.c_out.no, self.d.no, self.h.no])   # 照完工的先後
        self.assertEqual(data["totals"], {
            "count": 5, "paid": "15000.00", "parts": "1600.00", "outside": "3500.00", "margin": "9900.00"})
        self.assertEqual(data["results"][1], {
            "id": self.b.pk, "date": "2026-09-06", "doc": {"kind": "repair", "id": self.b.pk, "no": self.b.no},
            "store": self.w1.name, "model": "iPhone 15", "way": "in_house",
            "receiver": self.c.sales_person.name, "technician": "甲技師",
            "paid": "2000.00", "parts": "400.00", "outside": "0.00", "margin": "1600.00"})
        ways = {r["doc"]["no"]: (r["way"], r["parts"], r["outside"], r["margin"]) for r in data["results"]}
        self.assertEqual(ways, {
            self.a.no: ("in_house", "800.00", "0.00", "2200.00"),
            self.b.no: ("in_house", "400.00", "0.00", "1600.00"),
            self.c_out.no: ("vendor", "0.00", "3500.00", "1500.00"),          # 委外領的零件不算
            self.d.no: ("transfer", "400.00", "0.00", "3600.00"),
            self.h.no: ("in_house", "0.00", "0.00", "1000.00"),
        })
        # 每一列:實付 − 零件成本 − 委外費用 = 毛利;加起來 = 合計
        for row in data["results"]:
            self.assertEqual(Decimal(row["paid"]) - Decimal(row["parts"]) - Decimal(row["outside"]), Decimal(row["margin"]))
        for key in ("paid", "parts", "outside", "margin"):
            self.assertEqual(sum(Decimal(r[key]) for r in data["results"]), Decimal(data["totals"][key]), key)
        # 人員:收件人 a 自己修(收件、維修各一件)+ b、c、d 的收件;技師修 b、d;沒填收件人的歸「(未指定)」
        self.assertEqual(data["people"], [
            {"id": self.c.sales_person.id, "name": self.c.sales_person.name, "received": 4, "repaired": 1, "amount": "6200.00"},
            {"id": self.tech.id, "name": "甲技師", "received": 0, "repaired": 2, "amount": "2700.00"},
            {"id": None, "name": "(未指定)", "received": 1, "repaired": 1, "amount": "1000.00"},
        ])
        self.assertEqual(sum(Decimal(p["amount"]) for p in data["people"]), Decimal(data["totals"]["margin"]))
        self.assertEqual((data["from"], data["to"]), ("2026-09-01", "2026-09-30"))
        self.assertEqual(data["choices"], {"way": [
            {"key": "in_house", "label": "自修"}, {"key": "vendor", "label": "委外"}, {"key": "transfer", "label": "內轉"}]})

    def test_only_completed_ones_that_are_not_void(self):
        nos = self.numbers(self.report())
        self.assertNotIn(self.e.no, nos)          # 完工後作廢
        self.assertNotIn(self.f.no, nos)          # 還在維修中
        RepairOrder.objects.filter(pk=self.a.pk).update(is_void=True)
        self.assertEqual(self.report()["totals"]["count"], 4)
        # 有完工時間、但狀態不是完成的不算(正常流程重開時會把完工時間清掉;這裡直接改資料庫造一筆,釘住看的是狀態)
        RepairOrder.objects.filter(pk=self.f.pk).update(status="ready_pickup", completed_at=at(9, 20))
        self.assertNotIn(self.f.no, self.numbers(self.report()))
        RepairOrder.objects.filter(pk=self.f.pk).update(status="completed", completed_at=at(9, 20))
        self.assertIn(self.f.no, self.numbers(self.report()))

    def test_the_period_is_the_local_day_of_completion(self):
        # 台灣 10/01 00:00 完工的(世界時間 9/30 16:00)算十月;收件日(9/01)不看
        self.assertNotIn(self.g.no, self.numbers(self.report()))
        octo = self.report(period=OCT)
        self.assertEqual([(r["doc"]["no"], r["date"]) for r in octo["results"]], [(self.g.no, "2026-10-01")])

        def got(first, last):
            return self.numbers(self.report(period={"from": first, "to": last}))

        self.assertEqual(got("2026-09-05", "2026-09-05"), [self.a.no])
        self.assertEqual(got("2026-09-06", "2026-09-08"), [self.b.no, self.c_out.no, self.d.no])
        self.assertEqual(got("2026-09-10", "2026-09-30"), [])
        # 23:59 完工的算當天
        RepairOrder.objects.filter(pk=self.a.pk).update(completed_at=datetime(2026, 9, 5, 15, 59, tzinfo=dt_timezone.utc))
        self.assertEqual(got("2026-09-05", "2026-09-05"), [self.a.no])
        self.assertEqual(got("2026-09-06", "2026-09-06"), [self.b.no])

    def test_filters(self):
        self.assertEqual(self.numbers(self.report(way="in_house")), [self.a.no, self.b.no, self.h.no])
        self.assertEqual(self.numbers(self.report(way="vendor")), [self.c_out.no])
        only = self.report(way="transfer")
        self.assertEqual(self.numbers(only), [self.d.no])
        # 條件之後的合計與人員是照條件的
        self.assertEqual(only["totals"], {"count": 1, "paid": "4000.00", "parts": "400.00", "outside": "0.00", "margin": "3600.00"})
        self.assertEqual([(p["name"], p["received"], p["repaired"], p["amount"]) for p in only["people"]],
                         [("甲技師", 0, 1, "2100.00"), (self.c.sales_person.name, 1, 0, "1500.00")])
        second = self.report(warehouse=self.w2.id)
        self.assertEqual((self.numbers(second), second["totals"]["margin"]), ([self.c_out.no], "1500.00"))
        for params, text in (({"way": "gone"}, "方式"), ({"from": "2026-09-30", "to": "2026-09-01"}, "起日"),
                             ({"from": "2025-01-01", "to": "2026-09-30"}, "一年")):
            r = self.c.admin.get(URL, {**SEP, **params})
            self.assertEqual(r.status_code, 400, params)
            self.assertIn(text, r.json()["detail"])

    def test_pages_and_export(self):
        page = self.report(page_size=2)
        self.assertEqual((page["count"], self.numbers(page)), (5, [self.a.no, self.b.no]))
        second = self.report(page_size=2, page=2)
        self.assertEqual(self.numbers(second), [self.c_out.no, self.d.no])
        self.assertEqual((second["totals"], second["people"]), (page["totals"], page["people"]))       # 合計與人員是全部的
        everything = self.report(export="1")
        self.assertEqual((len(everything["results"]), everything["truncated"], everything["totals"], everything["people"]),
                         (5, False, page["totals"], page["people"]))

    def test_a_locked_clerk_only_gets_the_own_store(self):
        mine = self.report(client=self.c.clerk, warehouse=self.w2.id)                # 網址帶別家的編號沒有用
        self.assertEqual(self.numbers(mine), [self.a.no, self.b.no, self.d.no, self.h.no])
        self.assertEqual(mine["totals"], {"count": 4, "paid": "10000.00", "parts": "1600.00", "outside": "0.00", "margin": "8400.00"})
        # 人員也只算自己門市的(第二家那一張委外不算在收件人頭上)
        self.assertEqual([(p["name"], p["received"], p["amount"]) for p in mine["people"]],
                         [(self.c.sales_person.name, 3, "4700.00"), ("甲技師", 0, "2700.00"), ("(未指定)", 1, "1000.00")])

    def test_needs_its_own_item(self):
        self.assertEqual(abilities.LABELS[abilities.REPORT_REPAIRS], "維修月報")
        self.assertNotIn(abilities.REPORT_REPAIRS, abilities.ALSO_NEEDS[abilities.REPORT_EXPLORE])
        self.assertEqual(self.c.clerk.get(URL, SEP).status_code, 200)
        UserProfile.objects.filter(user=self.c.clerk_user).update(denied_abilities=["report_repairs"])
        clerk = Company.client(get_user_model().objects.get(pk=self.c.clerk_user.pk))
        for params in (SEP, {**SEP, "export": "1"}):
            r = clerk.get(URL, params)
            self.assertEqual(r.status_code, 403)
            self.assertIn("「維修月報」", r.json()["detail"])
        self.assertEqual(clerk.get("/api/v1/repair-orders/").status_code, 200)        # 維修單清單不受影響
        self.assertEqual(self.c.admin.post(URL, {}, format="json").status_code, 405)  # 只能讀

    def test_another_company_is_never_mixed_in(self):
        other = Company("b", "乙通訊行", "乙")
        other.purchase(case_qty=5)
        theirs = other._post("/api/v1/repair-orders/", {
            "warehouse": other.wh.id, "customer": other.customer.id, "received_date": "2026-09-01",
            "mode": "in_house", "unlock_method": "none", "host_model_name": "乙的手機", "parts_input": []})
        RepairOrder.objects.filter(pk=theirs["id"]).update(
            status="completed", completed_at=at(9, 5), customer_paid_amount=7777, sales_person=other.sales_person)
        mine = self.report()
        self.assertEqual((mine["totals"]["count"], mine["totals"]["paid"]), (5, "15000.00"))
        self.assertNotIn(other.sales_person.name, [p["name"] for p in mine["people"]])
        got = other.admin.get(URL, SEP).json()
        self.assertEqual((got["totals"]["count"], got["totals"]["paid"]), (1, "7777.00"))

    def test_people_helper_orders_by_amount(self):
        found = report.completed(self.c.tenant, start=date(2026, 9, 1), end=date(2026, 9, 30))
        self.assertEqual([p["name"] for p in report.people(found)], [self.c.sales_person.name, "甲技師", "(未指定)"])
        self.assertEqual(report.people([]), [])
        self.assertEqual(report.totals([]), {"count": 0, "paid": "0.00", "parts": "0.00", "outside": "0.00", "margin": "0.00"})
