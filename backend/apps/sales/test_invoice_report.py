"""發票明細(owner 2026-10-12;取舊歐睿 FI012 開立發票表):有發票號碼的銷貨單一張一列。"""
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.backup.tests.factory import Company
from apps.sales.models import SalesOrder, SalesReturn
from apps.tenants.models import InvoiceTrack, InvoiceType, UserProfile

URL = "/api/v1/sales-invoice-report/"
SEP = {"from": "2026-09-01", "to": "2026-09-30"}
OCT = {"from": "2026-10-01", "to": "2026-10-31"}


class _Invoices(TestCase):
    """九月開的發票(皮套一個 390,不另外加稅的單):
    a QA…01 第一家門市 780(有統編)        正常
    b QA…02 第二家門市 390                正常
    c 免用發票                            不列
    d ZZ12345678 手開三聯、應稅內含 1,170、沒有填發票日期(看單據日期 9/08)   正常
    e QA…03 390,銷貨單作廢                作廢
    f QA…04 780,10/02 整張退、勾了作廢原發票   作廢
    g QA…05 390,9/20 退(勾了作廢原發票),那張銷退後來又作廢   待查
    h QA…06 1,560,10/03 整張退、沒有作廢原發票  正常(銷退 1,560)
    另外 i QA…07 是八月(8/20)開的 390,9/15 才退、沒有作廢原發票。
    """

    def setUp(self):
        c = self.c = Company("a", "甲通訊行", "甲")
        self.w1, self.w2 = c.warehouses
        c.purchase(case_qty=30)
        c.purchase(warehouse=self.w2, case_qty=10)
        self.e_type = InvoiceType.objects.create(tenant=c.tenant, code="e_invoice", name="電子發票")
        InvoiceType.objects.create(tenant=c.tenant, code="hand_tri", name="手開三聯")
        InvoiceTrack.objects.create(tenant=c.tenant, invoice_type=self.e_type, prefix="QA",
                                    range_start=10000001, range_end=10000050, next_number=10000001)
        self.a = self.sell(2, date(2026, 9, 5), buyer_tax_id="87654321")
        self.b = self.sell(1, date(2026, 9, 6), warehouse=self.w2)
        self.c_none = self.sell(1, date(2026, 9, 7), invoice_form="none")
        self.e = self.sell(1, date(2026, 9, 9))
        self.f = self.sell(2, date(2026, 9, 10))
        self.g = self.sell(1, date(2026, 9, 11))
        self.h = self.sell(4, date(2026, 9, 12))
        self.i = self.sell(1, date(2026, 8, 20))
        self.d = self.sell(3, date(2026, 9, 8), invoice_form="hand_tri", invoice_no="ZZ12345678",
                           tax_method="taxable_included")
        SalesOrder.objects.filter(pk=self.d["id"]).update(invoice_date=None)
        self.post(f"/api/v1/sales-orders/{self.e['id']}/void/", {"reason": "打錯"})
        self.rf = self.give_back(self.f, date(2026, 10, 2), void_invoice=True)
        self.rg = self.give_back(self.g, date(2026, 9, 20), void_invoice=True)
        self.post(f"/api/v1/sales-returns/{self.rg['id']}/void/", {"reason": "退錯"})
        self.rh = self.give_back(self.h, date(2026, 10, 3))
        self.ri = self.give_back(self.i, date(2026, 9, 15))

    def post(self, url, body):
        r = self.c.admin.post(url, body, format="json")
        self.assertIn(r.status_code, (200, 201), r.content.decode())
        return r.json()

    def sell(self, cases, day, warehouse=None, invoice_form="e_invoice", invoice_no="", tax_method="untaxed",
             buyer_tax_id=""):
        so = self.post("/api/v1/sales-orders/", {
            "customer": self.c.customer.id, "warehouse": (warehouse or self.w1).id, "tax_method": tax_method,
            "sales_person": self.c.sales_person.id, "invoice_form": invoice_form, "invoice_no": invoice_no,
            "buyer_tax_id": buyer_tax_id,
            "items": [{"product": self.c.case.id, "qty": cases, "unit_price": "390"}],
            "payments": [{"method": "cash", "amount": str(390 * cases)}],
        })
        SalesOrder.objects.filter(pk=so["id"]).update(doc_date=day)
        SalesOrder.objects.filter(pk=so["id"]).exclude(invoice_no="").update(invoice_date=day)
        return so

    def give_back(self, so, day, void_invoice=False):
        sr = self.post("/api/v1/sales-returns/", {
            "original_so": so["id"], "payment_method": "cash", "void_original_invoice": void_invoice})
        SalesReturn.objects.filter(pk=sr["id"]).update(doc_date=day)
        return sr

    def report(self, client=None, period=SEP, **params):
        r = (client or self.c.admin).get(URL, {**period, **params})
        self.assertEqual(r.status_code, 200, r.content.decode())
        return r.json()

    @staticmethod
    def numbers(data):
        return [r["invoice_no"] for r in data["results"]]


class InvoiceListTests(_Invoices):
    def test_one_row_per_invoice_in_number_order(self):
        data = self.report()
        self.assertEqual(self.numbers(data), [
            "QA10000001", "QA10000002", "QA10000003", "QA10000004", "QA10000005", "QA10000006", "ZZ12345678"])
        self.assertEqual(data["count"], 7)
        first = data["results"][0]
        self.assertEqual(first, {
            "id": self.a["id"], "date": "2026-09-05", "invoice_no": "QA10000001", "form": "電子發票",
            "buyer_tax_id": "87654321", "doc": {"kind": "sale", "id": self.a["id"], "no": self.a["no"]},
            "store": self.w1.name, "customer": self.c.customer.name, "tax_method": "未稅",
            "subtotal": "780.00", "tax": "0.00", "total": "780.00", "state": "ok",
            "returned": "0.00", "return_date": None,
        })
        # 免用發票的那一張不在;八月開的那一張也不在(照發票日看九月)
        self.assertNotIn(self.c_none["no"], [r["doc"]["no"] for r in data["results"]])
        self.assertNotIn("QA10000007", self.numbers(data))

    def test_hand_written_number_uses_the_document_date_and_keeps_its_tax(self):
        row = self.report()["results"][-1]
        so = SalesOrder.objects.get(pk=self.d["id"])
        self.assertIsNone(so.invoice_date)
        self.assertEqual((row["date"], row["form"], row["tax_method"]), ("2026-09-08", "手開三聯", "應稅內含"))
        # 1,170 內含 5%:系統的稅額算到整數元 → 未稅 1,114 + 稅 56(跟那張銷貨單上記的一樣)
        self.assertEqual((row["subtotal"], row["tax"], row["total"]), ("1114.00", "56.00", "1170.00"))
        self.assertEqual((Decimal(row["subtotal"]), Decimal(row["tax"])), (so.subtotal, so.tax_amount))

    def test_states(self):
        states = {r["invoice_no"]: (r["state"], r["returned"], r["return_date"]) for r in self.report()["results"]}
        self.assertEqual(states, {
            "QA10000001": ("ok", "0.00", None),
            "QA10000002": ("ok", "0.00", None),
            "QA10000003": ("void", "0.00", None),                 # 銷貨單作廢
            "QA10000004": ("void", "780.00", "2026-10-02"),       # 整張退 + 作廢原發票
            "QA10000005": ("check", "0.00", None),                # 記成作廢,但那張銷退後來作廢了
            "QA10000006": ("ok", "1560.00", "2026-10-03"),        # 退了但發票沒有作廢
            "ZZ12345678": ("ok", "0.00", None),
        })

    def test_totals_are_the_face_value_of_the_normal_ones(self):
        data = self.report()
        # 正常四張:780 + 390 + 1,560 + 1,170;作廢兩張、待查一張(390)不算進金額;銷退合計是正常那幾張被退的
        self.assertEqual(data["totals"], {
            "ok_count": 4, "void_count": 2, "check_count": 1,
            "subtotal": "3844.00", "tax": "56.00", "total": "3900.00",
            "check_total": "390.00", "returned": "1560.00",
        })
        ok = [r for r in data["results"] if r["state"] == "ok"]
        for key in ("subtotal", "tax", "total", "returned"):
            self.assertEqual(sum(Decimal(r[key]) for r in ok), Decimal(data["totals"][key]), key)

    def test_filters(self):
        self.assertEqual(self.numbers(self.report(state="void")), ["QA10000003", "QA10000004"])
        self.assertEqual(self.numbers(self.report(state="check")), ["QA10000005"])
        self.assertEqual(self.numbers(self.report(state="ok")), ["QA10000001", "QA10000002", "QA10000006", "ZZ12345678"])
        self.assertEqual(self.numbers(self.report(form="hand_tri")), ["ZZ12345678"])
        self.assertEqual(self.numbers(self.report(warehouse=self.w2.id)), ["QA10000002"])
        self.assertEqual(self.numbers(self.report(search="zz1234")), ["ZZ12345678"])           # 發票號碼(不分大小寫)
        self.assertEqual(self.numbers(self.report(search="8765")), ["QA10000001"])             # 統編
        self.assertEqual(self.numbers(self.report(search=self.b["no"])), ["QA10000002"])       # 銷貨單號
        self.assertEqual(self.numbers(self.report(search="QA1000 4321")), ["QA10000001"])      # 每一段都要有
        # 條件之後的合計是照條件的
        only = self.report(state="void")
        self.assertEqual((only["totals"]["void_count"], only["totals"]["ok_count"], only["totals"]["total"]), (2, 0, "0.00"))

    def test_both_ends_of_the_period_count(self):
        def got(first, last):
            return self.numbers(self.report(period={"from": f"2026-09-{first}", "to": f"2026-09-{last}"}))

        self.assertEqual(got("05", "05"), ["QA10000001"])
        self.assertEqual(got("06", "08"), ["QA10000002", "ZZ12345678"])
        self.assertEqual(got("13", "30"), [])

    def test_by_return_date_finds_invoices_from_an_earlier_period(self):
        # 八月開的發票九月才退:照發票日看九月沒有它,照銷退日看九月才看得到(動手前紅隊第 1 條)
        sep = self.report(by="return")
        self.assertEqual([(r["invoice_no"], r["date"], r["state"], r["returned"], r["return_date"]) for r in sep["results"]],
                         [("QA10000007", "2026-08-20", "ok", "390.00", "2026-09-15")])
        self.assertEqual((sep["by"], sep["totals"]["ok_count"], sep["totals"]["returned"]), ("return", 1, "390.00"))
        # 作廢的那張銷退(9/20)不算有退
        self.assertNotIn("QA10000005", self.numbers(sep))
        octo = self.report(period=OCT, by="return")
        self.assertEqual([(r["invoice_no"], r["state"], r["returned"]) for r in octo["results"]],
                         [("QA10000004", "void", "780.00"), ("QA10000006", "ok", "1560.00")])
        self.assertEqual((octo["totals"]["ok_count"], octo["totals"]["void_count"], octo["totals"]["total"],
                          octo["totals"]["returned"]), (1, 1, "1560.00", "1560.00"))
        # 照發票日看十月:一張都沒有
        self.assertEqual(self.report(period=OCT)["results"], [])

    def test_the_period_is_the_invoice_date_not_the_document_date(self):
        # 9/30 開的單、發票日期是 10/01(隔天才開發票):算十月的,不算九月的
        SalesOrder.objects.filter(pk=self.b["id"]).update(doc_date=date(2026, 9, 30), invoice_date=date(2026, 10, 1))
        self.assertNotIn("QA10000002", self.numbers(self.report()))
        octo = self.report(period=OCT)
        self.assertEqual([(r["invoice_no"], r["date"]) for r in octo["results"]], [("QA10000002", "2026-10-01")])

    def test_what_the_return_columns_mean_if_one_invoice_ever_has_two_returns(self):
        # 現在的規則不會有兩張有效的銷退(只能整張退、一次一張)。這裡直接改資料庫造一張,釘住欄位的意思:
        # 之後如果開放部分退,「照銷退日」的銷退是**那段期間**退的、銷退日是**最近**的那一張,不會默默變掉
        extra = SalesReturn.objects.get(pk=self.rh["id"])
        extra.pk, extra.no = None, ""
        extra.doc_date, extra.total = date(2026, 9, 28), Decimal("100")
        extra.save()
        h = {"QA10000006"}
        by_invoice = next(r for r in self.report()["results"] if r["invoice_no"] in h)
        self.assertEqual((by_invoice["returned"], by_invoice["return_date"]), ("1660.00", "2026-10-03"))     # 全部的、最近的
        in_sep = [r for r in self.report(by="return")["results"] if r["invoice_no"] in h]
        self.assertEqual([(r["returned"], r["return_date"]) for r in in_sep], [("100.00", "2026-10-03")])    # 九月退的
        in_oct = next(r for r in self.report(period=OCT, by="return")["results"] if r["invoice_no"] in h)
        self.assertEqual(in_oct["returned"], "1560.00")                                                    # 十月退的

    def test_a_return_made_again_after_the_first_was_voided_settles_it(self):
        # 待查的那一張再退一次(貨真的退回來了):退的金額對上了 → 作廢
        self.give_back(self.g, date(2026, 9, 25))
        row = next(r for r in self.report()["results"] if r["invoice_no"] == "QA10000005")
        self.assertEqual((row["state"], row["returned"], row["return_date"]), ("void", "390.00", "2026-09-25"))

    def test_choices_come_from_the_server(self):
        data = self.report()
        self.assertEqual(data["choices"], {
            "by": [{"key": "invoice", "label": "發票日"}, {"key": "return", "label": "銷退日"}],
            "state": [{"key": "ok", "label": "正常"}, {"key": "void", "label": "作廢"}, {"key": "check", "label": "待查"}],
        })
        self.assertEqual((data["from"], data["to"], data["by"]), ("2026-09-01", "2026-09-30", "invoice"))

    def test_pages_and_export(self):
        page = self.report(page_size=3)
        self.assertEqual((page["count"], len(page["results"])), (7, 3))
        second = self.report(page_size=3, page=2)
        self.assertEqual(self.numbers(second), ["QA10000004", "QA10000005", "QA10000006"])
        self.assertEqual(second["totals"], page["totals"])               # 合計是全部的,不是這一頁的
        everything = self.report(export="1")
        self.assertEqual((len(everything["results"]), everything["truncated"], everything["totals"]),
                         (7, False, page["totals"]))


class InvoiceAccessTests(_Invoices):
    def test_a_locked_clerk_only_gets_the_own_store(self):
        mine = self.report(client=self.c.clerk, warehouse=self.w2.id)          # 網址帶別家的編號沒有用
        self.assertNotIn("QA10000002", self.numbers(mine))
        self.assertEqual(len(mine["results"]), 6)
        self.assertEqual(mine["totals"]["ok_count"], 3)
        self.assertEqual(self.report()["totals"]["ok_count"], 4)                 # 管理員看得到第二家的

    def test_needs_its_own_item(self):
        self.assertEqual(self.c.clerk.get(URL, SEP).status_code, 200)
        UserProfile.objects.filter(user=self.c.clerk_user).update(denied_abilities=["report_invoices"])
        clerk = Company.client(get_user_model().objects.get(pk=self.c.clerk_user.pk))
        r = clerk.get(URL, SEP)
        self.assertEqual(r.status_code, 403)
        self.assertIn("「發票明細」", r.json()["detail"])
        self.assertEqual(clerk.get(f"{URL}?export=1", SEP).status_code, 403)

    def test_another_company_is_never_mixed_in(self):
        other = Company("b", "乙通訊行", "乙")
        other.purchase(case_qty=5)
        so = other._post("/api/v1/sales-orders/", {
            "customer": other.customer.id, "warehouse": other.wh.id, "tax_method": "untaxed",
            "invoice_form": "hand_tri", "invoice_no": "QA10000001",
            "items": [{"product": other.case.id, "qty": 1, "unit_price": "390"}],
            "payments": [{"method": "cash", "amount": "390"}]})
        SalesOrder.objects.filter(pk=so["id"]).update(doc_date=date(2026, 9, 5), invoice_date=date(2026, 9, 5))
        mine = self.report()
        self.assertEqual((mine["count"], mine["totals"]["total"]), (7, "3900.00"))
        theirs = other.admin.get(URL, SEP).json()
        self.assertEqual([r["doc"]["no"] for r in theirs["results"]], [so["no"]])

    def test_bad_requests_get_a_plain_message(self):
        for params, text in (({"by": "void"}, "發票日"), ({"state": "gone"}, "狀態"),
                             ({"from": "2026-09-30", "to": "2026-09-01"}, "起日"),
                             ({"from": "2025-01-01", "to": "2026-09-01"}, "一年"), ({"from": "9/1"}, "日期")):
            r = self.c.admin.get(URL, {**SEP, **params})
            self.assertEqual(r.status_code, 400, params)
            self.assertIn(text, r.json()["detail"], params)

    def test_only_reads(self):
        for method in ("post", "put", "patch", "delete"):
            self.assertEqual(getattr(self.c.admin, method)(URL, {}, format="json").status_code, 405, method)
        self.assertEqual(self.c.admin.__class__().get(URL, SEP).status_code, 401)
