"""金額一律整數元、四捨五入(規則在 apps/core/money.py)。

這裡測規則本身,以及「看得到金額的地方」有沒有照規則走:進貨單頭、營業日報的加總、
舊系統金額的顯示、維修的建議報價、每日對帳認不認得以前算到分的單。
銷貨的部分在 apps/sales/test_line_ledger.py。
"""
from decimal import Decimal

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from apps.backup.tests.factory import Company
from apps.core.money import CENTS, money_int, round_money
from apps.ledger.checks import run_checks
from apps.legacy.views import _money_text
from apps.purchasing.models import PurchaseOrderItem
from apps.sales.models import SalesOrder, SalesOrderItem, SalesOrderPayment
from apps.sales.services import _calc_tax, split_tax_by_line

D = Decimal


class RuleTests(SimpleTestCase):
    def test_half_always_rounds_up(self):
        for raw, want in [("0.5", "1"), ("1.5", "2"), ("2.5", "3"), ("4.5", "5"),
                          ("115.50", "116"), ("0.49", "0"), ("952.38", "952"), ("47.62", "48")]:
            self.assertEqual(round_money(D(raw)), D(want), raw)

    def test_negative_rounds_to_the_same_number(self):
        self.assertEqual(round_money(D("-2.5")), D("-3"))
        self.assertEqual(round_money(D("-115.50")), D("-116"))
        self.assertEqual(round_money(D("-0.49")), D("0"))

    def test_report_sums_round_instead_of_cutting(self):
        # int() 是無條件捨去:115.50 會變 115
        self.assertEqual(money_int(D("115.50")), 116)
        self.assertEqual(money_int(D("115.49")), 115)
        self.assertEqual(money_int(D("-115.50")), -116)
        self.assertEqual(money_int(None), 0)

    def test_legacy_amounts_are_shown_in_whole_dollars(self):
        # 舊系統的金額存的是「分」,原文不改,只有顯示收成整數元
        self.assertEqual(_money_text(123450), "1,235")
        self.assertEqual(_money_text(123449), "1,234")
        self.assertEqual(_money_text(150000), "1,500")
        self.assertEqual(_money_text(-123450), "-1,235")
        self.assertEqual(_money_text(-49), "0")
        self.assertEqual(_money_text(0), "0")


class DocumentTests(TestCase):
    def setUp(self):
        self.c = Company("a", "甲通訊行", "甲")

    def buy(self, method, unit_price, qty=1):
        return self.c._post("/api/v1/purchase-orders/", {
            "supplier": self.c.supplier.id, "warehouse": self.c.wh.id, "tax_method": method,
            "items": [{"product": self.c.case.id, "qty": qty, "unit_price": unit_price}],
        })

    def header(self, doc):
        return D(doc["subtotal"]), D(doc["tax_amount"]), D(doc["total_cost"])

    def test_purchase_header_is_whole_dollars(self):
        self.assertEqual(self.header(self.buy("taxable_included", "1000")),
                         (D("952"), D("48"), D("1000")))
        # 外加:110 的稅是 5.5 → 6;90 的稅是 4.5 → 5
        self.assertEqual(self.header(self.buy("taxable_excluded", "110")),
                         (D("110"), D("6"), D("116")))
        self.assertEqual(self.header(self.buy("taxable_excluded", "90")),
                         (D("90"), D("5"), D("95")))

    def test_purchase_cost_keeps_its_cents(self):
        # 成本是平均值:收成整數會越算越偏,照舊算到分(只在畫面上顯示成整數)
        po = self.buy("taxable_included", "100", qty=10)
        item = PurchaseOrderItem.objects.get(po_id=po["id"])
        self.assertEqual(item.amount, D("1000"))
        self.assertEqual(item.unit_landed_cost, D("95.24"))

    def test_daily_report_rounds_amounts_saved_in_cents(self):
        self.c.purchase(case_qty=5)
        so = self.c._post("/api/v1/sales-orders/", {
            "customer": self.c.customer.id, "warehouse": self.c.wh.id,
            "tax_method": "taxable_excluded",
            "items": [{"product": self.c.case.id, "qty": 1, "unit_price": "110"}],
            "payments": [{"method": "cash", "amount": "116"}],
        })
        # 以前存的單:總額 115.50、付款 115.50
        SalesOrder.objects.filter(pk=so["id"]).update(tax_amount=D("5.50"), total=D("115.50"))
        SalesOrderPayment.objects.filter(so_id=so["id"]).update(amount=D("115.50"))
        today = timezone.localdate().isoformat()
        r = self.c.admin.get(
            f"/api/v1/reports/business-daily/?warehouse={self.c.wh.id}&date={today}")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["sales"]["total"], 116)

    def test_yesterdays_closing_is_todays_opening(self):
        # 兩筆以前存的 115.50 現金:逐筆進位是 232,先加再進位是 231。期初要跟前一天的明細用同一種算法
        from datetime import timedelta

        self.c.purchase(case_qty=5)
        yesterday = timezone.localdate() - timedelta(days=1)
        for _ in range(2):
            so = self.c._post("/api/v1/sales-orders/", {
                "customer": self.c.customer.id, "warehouse": self.c.wh.id,
                "tax_method": "taxable_excluded",
                "items": [{"product": self.c.case.id, "qty": 1, "unit_price": "110"}],
                "payments": [{"method": "cash", "amount": "116"}],
            })
            SalesOrder.objects.filter(pk=so["id"]).update(
                tax_amount=D("5.50"), total=D("115.50"), doc_date=yesterday)
            SalesOrderPayment.objects.filter(so_id=so["id"]).update(amount=D("115.50"))

        def report(day):
            r = self.c.admin.get(
                f"/api/v1/reports/business-daily/?warehouse={self.c.wh.id}&date={day.isoformat()}")
            self.assertEqual(r.status_code, 200, r.content)
            return r.json()
        before = report(yesterday)
        self.assertEqual(before["sales"]["total"], 232)
        self.assertEqual(before["net_change"], 232)
        self.assertEqual(
            report(timezone.localdate())["opening_cash"],
            before["opening_cash"] + before["net_change"],
        )

    def test_cash_paid_for_a_buyback_is_listed_the_day_it_happens(self):
        # 個人收購 = 現金付款是負的銷貨單。期初現金本來就把它算成支出;當天的日報也要列,
        # 否則收購那天的結餘會比隔天的期初多出付出去的錢
        from datetime import timedelta

        from apps.catalog.models import Product
        from apps.parties.models import Member
        from apps.sales.services import acquire_secondhand_from_member

        yesterday = timezone.localdate() - timedelta(days=1)
        used = Product.objects.create(
            tenant=self.c.tenant, category=self.c.cat_phone, name="甲 中古 iPhone 13",
            is_secondhand=True, list_price=12000,
        )
        member = Member.objects.create(tenant=self.c.tenant, name="王小明", phone="0911222333")
        acquire_secondhand_from_member(
            tenant=self.c.tenant, member=member, warehouse=self.c.wh, secondhand_product=used,
            serial_no="", imei="356938035643809", sn="", condition_grade="A",
            custom_unit_price=None, acquisition_price="1000", payment_method_code="cash",
            battery_health=None, condition_note="", doc_date=yesterday, note="",
        )

        def report(day):
            r = self.c.admin.get(
                f"/api/v1/reports/business-daily/?warehouse={self.c.wh.id}&date={day.isoformat()}")
            self.assertEqual(r.status_code, 200, r.content)
            return r.json()
        before = report(yesterday)
        self.assertEqual(before["buybacks"]["total"], 1000)
        self.assertEqual(len(before["buybacks"]["rows"]), 1)
        self.assertEqual(before["sales"]["total"], 0)
        self.assertEqual(before["net_change"], -1000)
        self.assertEqual(
            report(timezone.localdate())["opening_cash"],
            before["opening_cash"] + before["net_change"],
        )

    def test_amount_rounded_to_zero_stays_zero(self):
        # 明細金額四捨五入成 0 之後,存檔不能又把 0 當成「沒填」改回去
        self.c.purchase(case_qty=5)
        so = self.c._post("/api/v1/sales-orders/", {
            "customer": self.c.customer.id, "warehouse": self.c.wh.id,
            "tax_method": "taxable_included",
            "items": [{"product": self.c.case.id, "qty": 1, "unit_price": "0.40"}],
            "payments": [],
        })
        item = SalesOrderItem.objects.get(so_id=so["id"])
        self.assertEqual(item.amount, D("0"))
        self.assertEqual(item.untaxed_amount + item.tax_amount, item.amount)
        self.assertEqual(D(so["total"]), D("0"))

    def test_saving_a_purchase_line_again_keeps_whole_dollars(self):
        po = self.buy("untaxed", "10.40")
        item = PurchaseOrderItem.objects.get(po_id=po["id"])
        self.assertEqual(item.amount, D("10"))
        item.save()  # 例如在管理後台打開再存
        item.refresh_from_db()
        self.assertEqual(item.amount, D("10"))

    def test_commission_copied_onto_a_new_line_is_whole_dollars(self):
        # 方案主檔以前存的佣金 100.50 不回頭改;存進新銷貨明細的那一份是金額,整數元
        from apps.parties.models import Carrier, TelecomPlan

        carrier = Carrier.objects.create(tenant=self.c.tenant, code="CHT", name="中華電信")
        plan = TelecomPlan.objects.create(
            tenant=self.c.tenant, carrier=carrier, name="舊方案", monthly_fee=599,
            contract_months=24, commission=D("100.50"), kind="renewal",  # 續約不用配 SIM 卡
        )
        from apps.catalog.models import Product
        Product.objects.filter(pk=self.c.case.pk).update(
            allows_telecom_line=True, allows_commission=True)
        self.c.purchase(case_qty=2)
        so = self.c._post("/api/v1/sales-orders/", {
            "customer": self.c.customer.id, "warehouse": self.c.wh.id, "tax_method": "untaxed",
            "items": [{"product": self.c.case.id, "qty": 1, "unit_price": "390",
                       "telecom_plan": plan.id, "msisdn": "0912345678"}],
            "payments": [{"method": "cash", "amount": "390"}],
        })
        item = SalesOrderItem.objects.get(so_id=so["id"])
        self.assertEqual(item.commission, D("101"))
        plan.refresh_from_db()
        self.assertEqual(plan.commission, D("100.50"))

    def test_orders_saved_in_cents_still_pass_the_daily_check(self):
        self.c.purchase(case_qty=5)
        so = self.c._post("/api/v1/sales-orders/", {
            "customer": self.c.customer.id, "warehouse": self.c.wh.id,
            "tax_method": "taxable_included",
            "items": [{"product": self.c.case.id, "qty": 1, "unit_price": "1000"}],
            "payments": [{"method": "cash", "amount": "1000"}],
        })
        self.assertEqual((D(so["subtotal"]), D(so["tax_amount"])), (D("952"), D("48")))

        def problems():
            return sorted(r["key"] for r in run_checks(self.c.tenant).results
                          if not r["ok"] and r["key"].startswith("sales_"))
        self.assertEqual(problems(), [])
        # 改成 2026-10-06 以前存檔的樣子(算到分):一樣算一致,不回頭改寫舊單
        subtotal, tax, total = _calc_tax(D("1000"), "taxable_included", CENTS)
        self.assertEqual((subtotal, tax), (D("952.38"), D("47.62")))
        SalesOrder.objects.filter(pk=so["id"]).update(subtotal=subtotal, tax_amount=tax)
        (u, t), = split_tax_by_line([D("1000")], "taxable_included", subtotal, tax)
        SalesOrderItem.objects.filter(so_id=so["id"]).update(untaxed_amount=u, tax_amount=t)
        self.assertEqual(problems(), [])
        # 兩種算法都不是的數字照樣抓得到
        SalesOrder.objects.filter(pk=so["id"]).update(subtotal=D("952.40"), tax_amount=D("47.60"))
        self.assertEqual(problems(), ["sales_header", "sales_line_tax"])


class MessageTests(SimpleTestCase):
    def test_amounts_in_messages_have_no_decimal_point(self):
        from apps.core.money import money_text

        self.assertEqual(money_text(D("116.00")), "116")
        self.assertEqual(money_text(D("25780")), "25,780")
        self.assertEqual(money_text(D("-300.00")), "-300")
        # 真的帶小數的照原樣印(看得出跟 116 差在哪)
        self.assertEqual(money_text(D("115.50")), "115.50")
