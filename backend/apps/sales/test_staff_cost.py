"""業務員成本:算獎金看的毛利用的成本(實際成本加上公司定的加成)。

owner 2026-10-09:全公司一條 + 個別商品另設;沒設定 = 實際成本;一般商品用平均成本、中古機用那一台自己的成本;
實際成本不藏、也不受影響。業務員毛利 = 未稅金額 − 業務員成本。
"""
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

import threading
import time

from django.db import connections
from django.test import SimpleTestCase, TestCase, TransactionTestCase
from django.utils import timezone

from apps.backup.tests.factory import Company
from apps.catalog.models import Product
from apps.core import staff_cost
from apps.inventory.models import ProductSerial, StockBalance
from apps.tenants.models import Tenant

from .models import SalesOrderItem, SalesReturnItem

D = Decimal
SETTINGS = "/api/v1/tenant-settings/"
PRODUCTS = "/api/v1/products/"
SALES = "/api/v1/sales-orders/"
QUERY = "/api/v1/analytics/query/"


def thing(avg="0", mode="", value="0", virtual=False, secondhand=False, serial=False):
    """serial = 帶序號(手機…);中古機一定帶序號。"""
    return SimpleNamespace(weighted_avg_cost=D(avg), staff_cost_mode=mode, staff_cost_value=D(value),
                           is_virtual=virtual, is_secondhand=secondhand, requires_serial=serial or secondhand)


# 帶序號的商品「先不做」(owner 2026-10-10);規則還在、開關打開就會生效 —— 這幾個測試在開關打開的狀況下驗那兩段規則
serial_goods_switched_on = mock.patch.object(staff_cost, "SERIAL_GOODS_TOO", True)


def firm(mode="", value="0"):
    return SimpleNamespace(staff_cost_mode=mode, staff_cost_value=D(value))


class RuleTests(SimpleTestCase):
    """只算數字的那一支(不碰資料庫)。"""

    def line(self, product, company, qty=1, actual="0", units=()):
        return staff_cost.line_cost(product, company, qty=qty, actual_cost=D(actual), unit_costs=[D(u) for u in units])

    def test_the_owners_examples(self):
        """成本 50 加 50 → 100;成本 50 加 20% → 60(不是只取 20%)。"""
        self.assertEqual(self.line(thing("50", "plus", "50"), firm(), actual="50"), (D("100.00"), "product:plus:50.00"))
        self.assertEqual(self.line(thing("50", "percent", "20"), firm(), actual="50"), (D("60.00"), "product:percent:20.00"))

    def test_nothing_set_means_the_actual_cost(self):
        self.assertEqual(self.line(thing("50"), firm(), qty=3, actual="141.33"), (D("141.33"), ""))

    def test_the_products_own_setting_wins_over_the_companys(self):
        self.assertEqual(self.line(thing("50"), firm("percent", "20"), qty=2, actual="100"),
                         (D("120.00"), "company:percent:20.00"))
        self.assertEqual(self.line(thing("50", "plus", "5"), firm("percent", "20"), qty=2, actual="100"),
                         (D("110.00"), "product:plus:5.00"))
        # 商品明講「加 0」= 這個商品不加成,不是「沒設定所以照全公司」
        self.assertEqual(self.line(thing("50", "percent", "0"), firm("percent", "20"), qty=2, actual="100"),
                         (D("100.00"), "product:percent:0.00"))

    def test_a_fixed_amount_ignores_the_cost(self):
        self.assertEqual(self.line(thing("50", "fixed", "80"), firm("percent", "20"), qty=3, actual="150"),
                         (D("240.00"), "product:fixed:80.00"))

    def test_serial_goods_are_left_out_for_now(self):
        """owner 2026-10-10:帶序號的先不做業務員成本。手機、中古機不管公司或商品自己設了什麼,都是實際成本。"""
        phone = thing("20000", "percent", "10", serial=True)
        self.assertEqual(self.line(phone, firm("plus", "500"), qty=1, actual="18000", units=["18000"]), (D("18000.00"), ""))
        used = thing("14000", "fixed", "1", secondhand=True)
        self.assertEqual(self.line(used, firm("percent", "20"), qty=2, actual="13000", units=["5000", "8000"]),
                         (D("13000.00"), ""))
        self.assertIsNone(staff_cost.rule_for(phone, firm("percent", "20")))
        # 「中古但沒標帶序號」(只有繞過存檔直接改資料庫才會有):一樣不加
        odd = SimpleNamespace(weighted_avg_cost=D("14000"), staff_cost_mode="percent", staff_cost_value=D("10"),
                              is_virtual=False, is_secondhand=True, requires_serial=False)
        self.assertEqual(self.line(odd, firm("plus", "5"), qty=1, actual="8000", units=["8000"]), (D("8000.00"), ""))
        # 畫面上的一件:手機是平均成本、中古機是那一台自己的成本,都不加成
        self.assertEqual(staff_cost.shown_unit_cost(phone, firm("percent", "20")), D("20000.00"))
        self.assertEqual(staff_cost.shown_unit_cost(used, firm("percent", "20"), own_cost=D("8000")), D("8000.00"))

    @serial_goods_switched_on
    def test_regular_goods_use_the_average_not_the_units_own_cost(self):
        """(開關打開時)一般的手機:就算這一台進得比較便宜,基準還是平均成本(不讓人挑便宜的那一台賣)。"""
        phone = thing("20000", "percent", "10", serial=True)
        self.assertEqual(self.line(phone, firm(), qty=1, actual="18000", units=["18000"])[0], D("22000.00"))

    @serial_goods_switched_on
    def test_secondhand_units_each_use_their_own_cost(self):
        used = thing("0", "percent", "10", secondhand=True)
        self.assertEqual(self.line(used, firm(), qty=2, actual="13000", units=["5000", "8000"])[0], D("14300.00"))
        used = thing("9999", "plus", "500", secondhand=True)
        self.assertEqual(self.line(used, firm(), qty=2, actual="13000", units=["5000", "8000"])[0], D("14000.00"))

    def test_a_missing_average_falls_back_to_this_sales_actual_cost(self):
        """平均成本是 0(沒有記到)而這一次有實際成本:拿實際成本當基準,不然業務員成本是 0、毛利虛高。"""
        self.assertEqual(self.line(thing("0", "percent", "20"), firm(), qty=2, actual="300")[0], D("360.00"))
        self.assertEqual(self.line(thing("0", "plus", "50"), firm(), qty=2, actual="300")[0], D("400.00"))
        self.assertEqual(self.line(thing("0", "plus", "50"), firm(), qty=2, actual="0")[0], D("100.00"))

    def test_virtual_goods_have_no_cost_whatever_the_rule(self):
        self.assertEqual(self.line(thing("0", "fixed", "80", virtual=True), firm("plus", "50"), qty=1), (D("0"), ""))
        self.assertEqual(staff_cost.shown_unit_cost(thing("0", virtual=True), firm("plus", "50")), D("0"))

    def test_cents_are_rounded_half_up_per_unit(self):
        # 95.24 × 1.2 = 114.288 → 一件 114.29;三件 342.87(畫面上一件的數字 × 數量 = 單上記的)
        self.assertEqual(self.line(thing("95.24", "percent", "20"), firm(), qty=3, actual="285.72")[0], D("342.87"))
        self.assertEqual(staff_cost.shown_unit_cost(thing("95.24", "percent", "20"), firm()), D("114.29"))
        self.assertEqual(staff_cost.shown_unit_cost(thing("0.125"), firm()), D("0.13"))

    def test_what_the_screen_shows_for_one_piece(self):
        self.assertEqual(staff_cost.shown_unit_cost(thing("50"), firm()), D("50.00"))                    # 沒有規則 = 平均成本
        self.assertEqual(staff_cost.shown_unit_cost(thing("50"), firm("plus", "30")), D("80.00"))
        self.assertEqual(staff_cost.shown_unit_cost(thing("50", "fixed", "70"), firm("plus", "30")), D("70.00"))
        with serial_goods_switched_on:                                     # 開關打開時:中古機拿那一台自己的成本加成
            used = thing("50", secondhand=True)
            self.assertEqual(staff_cost.shown_unit_cost(used, firm("percent", "10"), own_cost=D("8000")), D("8800.00"))
        # 中古機沒有任何規則:那一台的業務員成本 = 那一台自己的成本(= 存檔時記的實際成本),不是商品的平均。
        # 開單頁用這個數字估,所以中古機的預估跟存檔後清單上的數字一樣(改之前是拿商品的平均去估,兩邊對不起來)
        self.assertEqual(staff_cost.shown_unit_cost(thing("14000", secondhand=True), firm(), own_cost=D("8000")),
                         D("8000.00"))
        # 一般商品就算給了某一台的成本,還是用平均
        self.assertEqual(staff_cost.shown_unit_cost(thing("50"), firm("percent", "10"), own_cost=D("8000")), D("55.00"))

    def test_a_rule_type_nobody_knows_counts_as_not_set(self):
        """資料庫裡的算法是不認得的字(只有直接改資料庫才會):當成沒有設定,不拿去當百分比算。"""
        self.assertEqual(self.line(thing("50", "weird", "30"), firm(), qty=2, actual="100"), (D("100.00"), ""))
        self.assertEqual(self.line(thing("50", "weird", "30"), firm("plus", "5"), qty=2, actual="100"),
                         (D("110.00"), "company:plus:5.00"))                # 商品的不認得 → 看全公司的
        self.assertEqual(self.line(thing("50"), firm("weird", "30"), qty=2, actual="100"), (D("100.00"), ""))
        self.assertEqual(staff_cost.shown_unit_cost(thing("50", "weird", "30"), firm()), D("50.00"))

    def test_checking_a_setting(self):
        ok = staff_cost.check
        self.assertIsNone(ok("percent", D("20"), staff_cost.PRODUCT_MODES))
        self.assertIsNone(ok("", D("0"), staff_cost.COMPANY_MODES))
        self.assertIsNotNone(ok("fixed", D("5"), staff_cost.COMPANY_MODES))        # 全公司沒有「固定金額」
        self.assertIsNotNone(ok("percent", D("-1"), staff_cost.PRODUCT_MODES))
        self.assertIsNotNone(ok("whatever", D("1"), staff_cost.PRODUCT_MODES))
        self.assertIsNotNone(ok(["percent"], D("1"), staff_cost.PRODUCT_MODES))    # 不是字串也只是「不對」,不出錯
        # 有選算法就要有數字;沒選算法可以沒有數字
        self.assertEqual(ok("fixed", None, staff_cost.PRODUCT_MODES), "請填數字")
        self.assertIsNone(ok("", None, staff_cost.PRODUCT_MODES))


class _Shop(TestCase):
    def setUp(self):
        self.c = Company("a", "甲通訊行", "甲")
        self.t = self.c.tenant
        # 皮套 9 個、每個成本 100;手機兩支、每支成本 20000
        self.c.purchase(case_qty=9, phone_serials=["甲P1", "甲P2"])

    def company_rule(self, mode, value):
        Tenant.objects.filter(pk=self.t.pk).update(staff_cost_mode=mode, staff_cost_value=D(value))
        self.fresh()

    def fresh(self):
        """測試用的連線一直拿著同一個帳號物件(連同它第一次讀到的公司資料);正式環境每個請求都重新讀。"""
        for user in (self.c.admin_user, self.c.clerk_user):
            user.profile.tenant.refresh_from_db()

    def product_rule(self, product, mode, value):
        Product.objects.filter(pk=product.pk).update(staff_cost_mode=mode, staff_cost_value=D(value))

    def sell(self, *lines, client=None):
        total = sum(D(l.get("amount") or D(l["unit_price"]) * l["qty"]) for l in lines)
        r = (client or self.c.clerk).post(SALES, {
            "customer": self.c.customer.id, "warehouse": self.c.wh.id, "tax_method": "untaxed",
            "items": list(lines), "payments": [{"method": "cash", "amount": str(total)}] if total else [],
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content.decode())
        return r.json()

    def cases(self, qty, price="390"):
        return {"product": self.c.case.id, "qty": qty, "unit_price": price}

    def phone(self, serial_no, price="25000", product=None):
        serial = ProductSerial.objects.get(tenant=self.t, serial_no=serial_no)
        return {"product": (product or self.c.phone).id, "qty": 1, "unit_price": price, "serial_ids": [serial.id]}

    def stored(self, doc, n=0):
        line = SalesOrderItem.objects.filter(so_id=doc["id"]).order_by("line_no", "id")[n]
        return line.cost_at_post, line.staff_cost, line.staff_cost_rule


class CompanySettingTests(_Shop):
    def test_only_managers_get_and_change_it(self):
        self.company_rule("percent", "20")
        seen = self.c.clerk.get(SETTINGS).json()
        self.assertNotIn("staff_cost_mode", seen)
        self.assertNotIn("staff_cost_value", seen)
        self.assertIn("repair_warranty_days", seen)                       # 其他設定照舊
        seen = self.c.admin.get(SETTINGS).json()
        self.assertEqual((seen["staff_cost_mode"], D(seen["staff_cost_value"])), ("percent", D("20")))
        r = self.c.clerk.patch(SETTINGS, {"staff_cost_mode": "plus", "staff_cost_value": "1"}, format="json")
        self.assertEqual(r.status_code, 403)
        self.t.refresh_from_db()
        self.assertEqual((self.t.staff_cost_mode, self.t.staff_cost_value), ("percent", D("20")))

    def test_a_manager_sets_changes_and_clears_it(self):
        r = self.c.admin.patch(SETTINGS, {"staff_cost_mode": "plus", "staff_cost_value": "30"}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.assertEqual((r.json()["staff_cost_mode"], D(r.json()["staff_cost_value"])), ("plus", D("30")))
        self.t.refresh_from_db()
        self.assertEqual((self.t.staff_cost_mode, self.t.staff_cost_value), ("plus", D("30")))
        # 只改數字:算法留著
        self.c.admin.patch(SETTINGS, {"staff_cost_value": "45.5"}, format="json")
        self.t.refresh_from_db()
        self.assertEqual((self.t.staff_cost_mode, self.t.staff_cost_value), ("plus", D("45.50")))
        # 改回尚未設定:數字不留
        r = self.c.admin.patch(SETTINGS, {"staff_cost_mode": ""}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.t.refresh_from_db()
        self.assertEqual((self.t.staff_cost_mode, self.t.staff_cost_value), ("", D("0")))

    def test_bad_values_change_nothing(self):
        self.company_rule("percent", "20")
        for body in ({"staff_cost_mode": "fixed", "staff_cost_value": "5"},          # 全公司沒有「固定金額」
                     {"staff_cost_mode": "percent", "staff_cost_value": "-1"},
                     {"staff_cost_mode": "percent", "staff_cost_value": "abc"},
                     {"staff_cost_mode": "percent", "staff_cost_value": "NaN"},
                     {"staff_cost_mode": "percent", "staff_cost_value": "1e15"},
                     {"staff_cost_mode": ["percent"], "staff_cost_value": "5"},
                     {"staff_cost_mode": "plus", "staff_cost_value": "5", "repair_warranty_days": 0}):
            r = self.c.admin.patch(SETTINGS, body, format="json")
            self.assertEqual(r.status_code, 400, (body, r.content.decode()))
            self.t.refresh_from_db()
            self.assertEqual((self.t.staff_cost_mode, self.t.staff_cost_value, self.t.repair_warranty_days),
                             ("percent", D("20"), 90), body)

    def test_a_rule_must_come_with_its_number(self):
        """只送算法、沒送數字:不沿用原本的數字(原本是 0 的話等於白設),整筆退回。"""
        r = self.c.admin.patch(SETTINGS, {"staff_cost_mode": "plus"}, format="json")
        self.assertEqual(r.status_code, 400, r.content.decode())
        self.assertEqual(r.json()["detail"], "業務員成本請填數字")
        self.company_rule("plus", "30")
        r = self.c.admin.patch(SETTINGS, {"staff_cost_mode": "percent"}, format="json")     # 換算法也要重新給數字
        self.assertEqual(r.status_code, 400, r.content.decode())
        self.t.refresh_from_db()
        self.assertEqual((self.t.staff_cost_mode, self.t.staff_cost_value), ("plus", D("30")))

    def test_the_number_is_rounded_half_up_before_checking_it_fits(self):
        r = self.c.admin.patch(SETTINGS, {"staff_cost_mode": "percent", "staff_cost_value": "1.005"}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.t.refresh_from_db()
        self.assertEqual(self.t.staff_cost_value, D("1.01"))               # 跟成交時同一種四捨五入
        r = self.c.admin.patch(SETTINGS, {"staff_cost_mode": "percent", "staff_cost_value": "999999999999.999"},
                               format="json")                              # 進位之後放不下
        self.assertEqual(r.status_code, 400, r.content.decode())
        self.t.refresh_from_db()
        self.assertEqual(self.t.staff_cost_value, D("1.01"))

    def test_the_other_settings_still_save_on_their_own(self):
        self.company_rule("percent", "20")
        r = self.c.admin.patch(SETTINGS, {"repair_warranty_days": 30}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.t.refresh_from_db()
        self.assertEqual((self.t.repair_warranty_days, self.t.staff_cost_mode, self.t.staff_cost_value),
                         (30, "percent", D("20")))

    def test_another_company_is_not_touched(self):
        b = Company("b", "乙通訊行", "乙")
        self.c.admin.patch(SETTINGS, {"staff_cost_mode": "plus", "staff_cost_value": "30"}, format="json")
        b.tenant.refresh_from_db()
        self.assertEqual(b.tenant.staff_cost_mode, "")
        self.assertEqual(b.admin.get(SETTINGS).json()["staff_cost_mode"], "")


class ProductSettingTests(_Shop):
    def one(self, client, product=None):
        return client.get(f"{PRODUCTS}{(product or self.c.case).id}/").json()

    def test_everyone_sees_the_number_only_managers_see_how_it_is_set(self):
        self.product_rule(self.c.case, "plus", "30")
        seen = self.one(self.c.clerk)
        self.assertEqual(D(seen["staff_cost"]), D("130"))                  # 平均成本 100 + 30
        self.assertEqual(D(seen["weighted_avg_cost"]), D("100"))           # 實際成本照舊看得到
        self.assertNotIn("staff_cost_mode", seen)
        self.assertNotIn("staff_cost_value", seen)
        seen = self.one(self.c.admin)
        self.assertEqual((seen["staff_cost_mode"], D(seen["staff_cost_value"]), D(seen["staff_cost"])),
                         ("plus", D("30"), D("130")))
        row = next(x for x in self.c.clerk.get(PRODUCTS, {"search": self.c.case.name}).json()["results"]
                   if x["id"] == self.c.case.id)
        self.assertEqual(D(row["staff_cost"]), D("130"))
        self.assertNotIn("staff_cost_mode", row)

    def test_without_any_rule_it_is_the_average_cost(self):
        self.assertEqual(D(self.one(self.c.clerk)["staff_cost"]), D("100"))
        self.company_rule("percent", "20")
        self.assertEqual(D(self.one(self.c.clerk)["staff_cost"]), D("120"))
        self.assertEqual(D(self.one(self.c.clerk, self.c.phone)["staff_cost"]), D("20000"))     # 帶序號的先不加
        self.product_rule(self.c.case, "fixed", "77")
        self.assertEqual(D(self.one(self.c.clerk)["staff_cost"]), D("77"))

    def test_a_clerks_change_is_not_taken(self):
        self.product_rule(self.c.case, "plus", "30")
        r = self.c.clerk.patch(f"{PRODUCTS}{self.c.case.id}/",
                               {"staff_cost_mode": "fixed", "staff_cost_value": "1", "spec": "新規格"}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.c.case.refresh_from_db()
        self.assertEqual((self.c.case.staff_cost_mode, self.c.case.staff_cost_value, self.c.case.spec),
                         ("plus", D("30"), "新規格"))

    def test_a_manager_sets_and_clears_it(self):
        one = f"{PRODUCTS}{self.c.case.id}/"
        r = self.c.admin.patch(one, {"staff_cost_mode": "percent", "staff_cost_value": "15"}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.assertEqual(D(r.json()["staff_cost"]), D("115"))
        r = self.c.admin.patch(one, {"staff_cost_mode": ""}, format="json")      # 回到照全公司:自己的數字不留
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.c.case.refresh_from_db()
        self.assertEqual((self.c.case.staff_cost_mode, self.c.case.staff_cost_value), ("", D("0")))

    def test_bad_values_are_refused(self):
        one = f"{PRODUCTS}{self.c.case.id}/"
        r = self.c.admin.patch(one, {"staff_cost_mode": "plus", "staff_cost_value": "-5"}, format="json")
        self.assertEqual(r.status_code, 400, r.content.decode())
        self.assertEqual(r.json()["detail"], ["業務員成本不能是負的"])            # 畫面只認 detail 這一格
        self.product_rule(self.c.case, "plus", "30")
        r = self.c.admin.patch(one, {"staff_cost_value": "-5"}, format="json")    # 只送數字也一樣擋
        self.assertEqual(r.status_code, 400, r.content.decode())
        r = self.c.admin.patch(one, {"staff_cost_mode": "whatever"}, format="json")
        self.assertEqual(r.status_code, 400, r.content.decode())
        self.c.case.refresh_from_db()
        self.assertEqual((self.c.case.staff_cost_mode, self.c.case.staff_cost_value), ("plus", D("30")))

    def test_a_rule_must_come_with_its_number(self):
        """複審抓到的:只送「固定金額」、沒送數字 → 數字是原本的 0 → 業務員成本 0、毛利等於整筆金額。現在整筆退回。"""
        one = f"{PRODUCTS}{self.c.case.id}/"
        for body in ({"staff_cost_mode": "fixed"}, {"staff_cost_mode": "plus"}, {"staff_cost_mode": "percent"}):
            r = self.c.admin.patch(one, body, format="json")
            self.assertEqual(r.status_code, 400, (body, r.content.decode()))
            self.assertEqual(r.json()["detail"], ["業務員成本請填數字"])
        r = self.c.admin.post(f"{PRODUCTS}bulk-edit/", {"ids": [self.c.case.id], "patch": {"staff_cost_mode": "fixed"}},
                              format="json")
        self.assertEqual(r.status_code, 400, r.content.decode())
        self.product_rule(self.c.case, "plus", "30")
        r = self.c.admin.patch(one, {"staff_cost_mode": "fixed"}, format="json")      # 換算法不沿用原本的 30
        self.assertEqual(r.status_code, 400, r.content.decode())
        self.c.case.refresh_from_db()
        self.assertEqual((self.c.case.staff_cost_mode, self.c.case.staff_cost_value), ("plus", D("30")))
        # 只改數字(算法不動)照舊可以
        self.assertEqual(self.c.admin.patch(one, {"staff_cost_value": "45"}, format="json").status_code, 200)
        self.c.case.refresh_from_db()
        self.assertEqual((self.c.case.staff_cost_mode, self.c.case.staff_cost_value), ("plus", D("45")))

    def test_setting_a_batch_at_once(self):
        r = self.c.admin.post(f"{PRODUCTS}bulk-edit/", {
            "ids": [self.c.case.id, self.c.phone.id],
            "patch": {"staff_cost_mode": "percent", "staff_cost_value": "12"}}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.c.case.refresh_from_db()
        self.c.phone.refresh_from_db()
        self.assertEqual((self.c.case.staff_cost_mode, self.c.case.staff_cost_value), ("percent", D("12")))
        # 一起勾到的手機(帶序號):不擋,也不存設定
        self.assertEqual((self.c.phone.staff_cost_mode, self.c.phone.staff_cost_value), ("", D("0")))
        # 店員送同一個請求:什麼都不會變
        r = self.c.clerk.post(f"{PRODUCTS}bulk-edit/", {
            "ids": [self.c.case.id], "patch": {"staff_cost_mode": "fixed", "staff_cost_value": "1"}}, format="json")
        self.c.case.refresh_from_db()
        self.assertEqual((self.c.case.staff_cost_mode, self.c.case.staff_cost_value), ("percent", D("12")))

    def units(self):
        rows = self.c.clerk.get("/api/v1/serials/", {"product": self.c.phone.id}).json()["results"]
        return {x["serial_no"]: D(x["staff_cost"]) for x in rows}

    def test_each_unit_shows_a_number_without_any_markup_for_now(self):
        """開單頁挑到某一台時用的數字。帶序號的先不加成:一般的手機每一台都是商品的平均成本,中古機是那一台自己的成本。"""
        ProductSerial.objects.filter(tenant=self.t, serial_no="甲P2").update(purchase_unit_cost=D("8000"))
        self.company_rule("percent", "10")
        self.assertEqual(self.units(), {"甲P1": D("20000"), "甲P2": D("20000")})
        Product.objects.filter(pk=self.c.phone.pk).update(is_secondhand=True)
        self.assertEqual(self.units(), {"甲P1": D("20000"), "甲P2": D("8000")})

    @serial_goods_switched_on
    def test_each_unit_shows_its_own_number_only_for_secondhand(self):
        """(開關打開時)中古機是那一台自己的成本加成,一般的手機每一台都跟商品的一樣。"""
        ProductSerial.objects.filter(tenant=self.t, serial_no="甲P2").update(purchase_unit_cost=D("8000"))
        self.company_rule("percent", "10")
        self.assertEqual(self.units(), {"甲P1": D("22000"), "甲P2": D("22000")})          # 平均成本 20000 × 1.1
        Product.objects.filter(pk=self.c.phone.pk).update(is_secondhand=True)
        self.assertEqual(self.units(), {"甲P1": D("22000"), "甲P2": D("8800")})

    def test_a_serial_product_does_not_keep_a_setting(self):
        """帶序號的商品先不做:管理員送設定過來不擋、也不存(之後開關打開時不會冒出一條沒人記得的規則)。"""
        one = f"{PRODUCTS}{self.c.phone.id}/"
        r = self.c.admin.patch(one, {"staff_cost_mode": "fixed", "staff_cost_value": "1"}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.c.phone.refresh_from_db()
        self.assertEqual((self.c.phone.staff_cost_mode, self.c.phone.staff_cost_value), ("", D("0")))
        self.assertEqual(D(r.json()["staff_cost"]), D("20000"))
        r = self.c.admin.patch(one, {"staff_cost_mode": "fixed"}, format="json")     # 沒送數字也一樣不擋(本來就不存)
        self.assertEqual(r.status_code, 200, r.content.decode())
        # 配件改成帶序號的同一次請求:設定也不留
        r = self.c.admin.post(PRODUCTS, {"name": "新的序號商品 X1", "category": self.c.cat_phone.id, "requires_serial": True,
                                         "staff_cost_mode": "plus", "staff_cost_value": "50"}, format="json")
        self.assertEqual(r.status_code, 201, r.content.decode())
        self.assertEqual(Product.objects.get(tenant=self.t, name="新的序號商品 X1").staff_cost_mode, "")
        r = self.c.admin.post(PRODUCTS, {"name": "新的配件 X2", "category": self.c.cat_case.id, "requires_serial": False,
                                         "staff_cost_mode": "plus", "staff_cost_value": "50"}, format="json")
        self.assertEqual(r.status_code, 201, r.content.decode())
        made = Product.objects.get(tenant=self.t, name="新的配件 X2")
        self.assertEqual((made.staff_cost_mode, made.staff_cost_value), ("plus", D("50")))
        # 放進「中古機類別」的商品,存檔時會被連帶改成中古機、帶序號(就算送來的是不帶序號):設定一樣不留
        from apps.catalog.models import Category

        used = Category.objects.create(tenant=self.t, code="UH", name="中古手機", is_secondhand_default=True)
        r = self.c.admin.post(PRODUCTS, {"name": "中古類別裡的東西 X3", "category": used.id, "requires_serial": False,
                                         "is_secondhand": False, "staff_cost_mode": "plus", "staff_cost_value": "50"},
                              format="json")
        self.assertEqual(r.status_code, 201, r.content.decode())
        made = Product.objects.get(tenant=self.t, name="中古類別裡的東西 X3")
        self.assertEqual((made.requires_serial, made.staff_cost_mode, made.staff_cost_value), (True, "", D("0")))
        # 直接勾「中古機」(送來的 requires_serial 是 False,存檔會被改成帶序號):也不留
        r = self.c.admin.post(PRODUCTS, {"name": "勾了中古機的東西 X4", "category": self.c.cat_case.id,
                                         "requires_serial": False, "is_secondhand": True,
                                         "staff_cost_mode": "plus", "staff_cost_value": "50"}, format="json")
        self.assertEqual(r.status_code, 201, r.content.decode())
        made = Product.objects.get(tenant=self.t, name="勾了中古機的東西 X4")
        self.assertEqual((made.requires_serial, made.staff_cost_mode, made.staff_cost_value), (True, "", D("0")))
        # 既有的配件搬進中古機類別、同一次送設定:也不留
        r = self.c.admin.patch(f"{PRODUCTS}{Product.objects.get(tenant=self.t, name='新的配件 X2').id}/",
                               {"category": used.id, "staff_cost_mode": "fixed", "staff_cost_value": "9"}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        moved = Product.objects.get(tenant=self.t, name="新的配件 X2")
        self.assertEqual((moved.requires_serial, moved.staff_cost_mode, moved.staff_cost_value), (True, "", D("0")))

    def test_setting_it_never_touches_the_actual_cost(self):
        self.c.admin.patch(f"{PRODUCTS}{self.c.case.id}/", {"staff_cost_mode": "fixed", "staff_cost_value": "999"},
                           format="json")
        self.c.case.refresh_from_db()
        self.assertEqual(self.c.case.weighted_avg_cost, D("100"))


class SaleTests(_Shop):
    def test_nothing_set_records_the_actual_cost(self):
        doc = self.sell(self.cases(2), self.phone("甲P1"))
        self.assertEqual(self.stored(doc, 0), (D("200"), D("200"), ""))
        self.assertEqual(self.stored(doc, 1), (D("20000"), D("20000"), ""))

    def test_the_company_rule_is_recorded_on_the_line(self):
        self.company_rule("percent", "20")
        doc = self.sell(self.cases(2), self.phone("甲P1"))
        self.assertEqual(self.stored(doc, 0), (D("200"), D("240"), "company:percent:20.00"))
        self.assertEqual(self.stored(doc, 1), (D("20000"), D("20000"), ""))          # 手機帶序號:先不加,記實際成本
        # 回應裡兩個都有:實際成本不藏
        line = doc["items"][0]
        self.assertEqual((D(line["cost_at_post"]), D(line["staff_cost"]), line["staff_cost_rule"]),
                         (D("200"), D("240"), "company:percent:20.00"))

    def test_the_rule_is_read_at_the_moment_of_sale(self):
        """管理員剛改完全公司的那一條,店員的下一張單就用新的(不用這個請求一開始帶進來的那一份公司資料)。"""
        self.sell(self.cases(1))                                   # 先讓這條連線讀過一次公司資料
        Tenant.objects.filter(pk=self.t.pk).update(staff_cost_mode="plus", staff_cost_value=D("11"))
        doc = self.sell(self.cases(2))
        self.assertEqual(self.stored(doc), (D("200"), D("222"), "company:plus:11.00"))

    def test_one_wrong_setting_saves_neither(self):
        """保固天數對、業務員成本不對:兩個都不存。"""
        r = self.c.admin.patch(SETTINGS, {"repair_warranty_days": 30, "staff_cost_mode": "percent",
                                          "staff_cost_value": "-1"}, format="json")
        self.assertEqual(r.status_code, 400, r.content.decode())
        self.t.refresh_from_db()
        self.assertEqual((self.t.repair_warranty_days, self.t.staff_cost_mode), (90, ""))

    def test_the_product_is_read_again_after_the_locks(self):
        """等鎖的時候商品的平均成本與它自己的設定被別人改掉(已提交):用鎖到之後讀到的,不用進交易之前那一份。"""
        from unittest import mock

        from apps.sales import services

        real = services._lock_rows

        def lock_then_someone_else_commits(*args, **kwargs):
            real(*args, **kwargs)
            Product.objects.filter(pk=self.c.case.pk).update(
                weighted_avg_cost=D("250"), staff_cost_mode="plus", staff_cost_value=D("40"))

        with mock.patch.object(services, "_lock_rows", side_effect=lock_then_someone_else_commits):
            doc = self.sell(self.cases(2))
        self.assertEqual(self.stored(doc), (D("200"), D("580"), "product:plus:40.00"))      # (250 + 40) × 2

    def test_the_products_own_rule_wins(self):
        self.company_rule("percent", "20")
        self.product_rule(self.c.case, "fixed", "150")
        doc = self.sell(self.cases(3))
        self.assertEqual(self.stored(doc), (D("300"), D("450"), "product:fixed:150.00"))
        self.product_rule(self.c.case, "plus", "50")
        doc = self.sell(self.cases(2))
        self.assertEqual(self.stored(doc), (D("200"), D("300"), "product:plus:50.00"))

    def test_changing_the_rule_or_the_cost_later_does_not_touch_the_sale(self):
        self.company_rule("percent", "20")
        doc = self.sell(self.cases(2))
        self.company_rule("percent", "90")
        self.product_rule(self.c.case, "fixed", "1")
        Product.objects.filter(pk=self.c.case.pk).update(weighted_avg_cost=D("5"))
        self.assertEqual(self.stored(doc), (D("200"), D("240"), "company:percent:20.00"))
        seen = self.c.admin.get(f"{SALES}{doc['id']}/").json()["items"][0]
        self.assertEqual(D(seen["staff_cost"]), D("240"))

    def test_what_the_client_sends_does_not_count(self):
        self.company_rule("percent", "20")
        doc = self.sell({**self.cases(2), "staff_cost": "1", "staff_cost_rule": "x", "cost_at_post": "1"},
                        client=self.c.admin)
        self.assertEqual(self.stored(doc), (D("200"), D("240"), "company:percent:20.00"))

    def test_serial_goods_record_the_actual_cost_whatever_the_rules(self):
        """owner 2026-10-10:帶序號的先不做。公司有規則、商品自己也被寫了規則(直接改資料庫),手機與中古機照樣記實際成本。"""
        ProductSerial.objects.filter(tenant=self.t, serial_no="甲P2").update(purchase_unit_cost=D("8000"))
        self.company_rule("percent", "20")
        self.product_rule(self.c.phone, "fixed", "1")
        doc = self.sell(self.phone("甲P1"), self.cases(1))
        self.assertEqual(self.stored(doc, 0), (D("20000"), D("20000"), ""))
        self.assertEqual(self.stored(doc, 1), (D("100"), D("120"), "company:percent:20.00"))      # 同一張單的配件照加
        Product.objects.filter(pk=self.c.phone.pk).update(is_secondhand=True)
        doc = self.sell(self.phone("甲P2"))
        self.assertEqual(self.stored(doc, 0), (D("8000"), D("8000"), ""))

    @serial_goods_switched_on
    def test_a_regular_phone_uses_the_average_not_its_own_cost(self):
        """(開關打開時)兩支手機進價不同(20000 與 18000),平均 19000:賣哪一支業務員成本都一樣。"""
        ProductSerial.objects.filter(tenant=self.t, serial_no="甲P2").update(purchase_unit_cost=D("18000"))
        Product.objects.filter(pk=self.c.phone.pk).update(weighted_avg_cost=D("19000"))
        self.company_rule("percent", "10")
        cheap, dear = self.sell(self.phone("甲P2")), self.sell(self.phone("甲P1"))
        self.assertEqual(self.stored(cheap), (D("18000"), D("20900"), "company:percent:10.00"))
        self.assertEqual(self.stored(dear), (D("20000"), D("20900"), "company:percent:10.00"))

    @serial_goods_switched_on
    def test_a_secondhand_unit_uses_its_own_cost(self):
        ProductSerial.objects.filter(tenant=self.t, serial_no="甲P2").update(purchase_unit_cost=D("8000"))
        Product.objects.filter(pk=self.c.phone.pk).update(is_secondhand=True, weighted_avg_cost=D("14000"))
        self.company_rule("percent", "10")
        doc = self.sell(self.phone("甲P2"), self.phone("甲P1"))
        self.assertEqual(self.stored(doc, 0), (D("8000"), D("8800"), "company:percent:10.00"))
        self.assertEqual(self.stored(doc, 1), (D("20000"), D("22000"), "company:percent:10.00"))

    def test_a_missing_average_uses_this_sales_actual_cost(self):
        Product.objects.filter(pk=self.c.case.pk).update(weighted_avg_cost=D("0"))     # 例:匯入的庫存沒有帶到平均成本
        self.company_rule("percent", "20")
        doc = self.sell(self.cases(2))
        self.assertEqual(self.stored(doc), (D("200"), D("240"), "company:percent:20.00"))

    def test_reading_the_product_again_does_not_cost_a_query_per_line(self):
        """鎖到之後重新讀商品是一次查完的(要看的欄位都在那一次裡,不會每一行再回去補查)。"""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        self.company_rule("percent", "20")
        other = Product.objects.create(tenant=self.t, category=self.c.cat_case, name="另一個配件 Q9", requires_serial=False)
        self.c.admin.post("/api/v1/purchase-orders/", {
            "supplier": self.c.supplier.id, "warehouse": self.c.wh.id, "tax_method": "untaxed",
            "items": [{"product": other.id, "qty": 3, "unit_price": "50"}]}, format="json")
        with CaptureQueriesContext(connection) as ctx:
            self.sell(self.cases(1), {"product": other.id, "qty": 1, "unit_price": "390"}, self.phone("甲P1"))
        refetch = [q["sql"] for q in ctx.captured_queries
                   if 'FROM "catalog_product"' in q["sql"] and '"requires_serial"' in q["sql"]
                   and '"catalog_product"."name"' not in q["sql"]]
        self.assertEqual(len(refetch), 1, refetch)

    def test_a_rule_type_nobody_knows_does_not_break_the_sale(self):
        Product.objects.filter(pk=self.c.case.pk).update(staff_cost_mode="weird", staff_cost_value=D("30"))
        doc = self.sell(self.cases(2))
        self.assertEqual(self.stored(doc), (D("200"), D("200"), ""))

    def test_virtual_goods_record_zero(self):
        self.company_rule("plus", "50")
        fee = Product.objects.create(tenant=self.t, category=self.c.cat_case, name="手續費", requires_serial=False,
                                     is_virtual=True, list_price=100)
        doc = self.sell({"product": fee.id, "qty": 1, "unit_price": "100"})
        self.assertEqual(self.stored(doc), (D("0"), D("0"), ""))

    def test_a_line_from_before_this_existed_reads_as_the_actual_cost(self):
        doc = self.sell(self.cases(2))
        SalesOrderItem.objects.filter(so_id=doc["id"]).update(staff_cost=None)          # 2026-10-09 之前開的單
        seen = self.c.clerk.get(f"{SALES}{doc['id']}/").json()["items"][0]
        self.assertEqual((D(seen["staff_cost"]), seen["staff_cost_rule"]), (D("200"), ""))
        rows = self.c.clerk.get(SALES).json()["results"]
        self.assertEqual(D(next(x for x in rows if x["id"] == doc["id"])["items"][0]["staff_cost"]), D("200"))

    def test_the_actual_cost_and_stock_are_exactly_as_before(self):
        """加了規則,實際成本、庫存、平均成本一個都不變。"""
        plain = self.sell(self.cases(2))
        self.company_rule("percent", "50")
        marked = self.sell(self.cases(2))
        self.assertEqual(self.stored(plain)[0], self.stored(marked)[0])
        self.c.case.refresh_from_db()
        self.assertEqual(self.c.case.weighted_avg_cost, D("100"))


class ReturnTests(_Shop):
    def give_back(self, doc):
        r = self.c.admin.post("/api/v1/sales-returns/", {"original_so": doc["id"], "payment_method": "cash"},
                              format="json")
        self.assertEqual(r.status_code, 201, r.content.decode())
        return r.json()

    def test_a_return_copies_the_line_not_todays_rule(self):
        self.company_rule("percent", "20")
        doc = self.sell(self.cases(2))
        self.company_rule("percent", "90")
        back = self.give_back(doc)
        line = SalesReturnItem.objects.get(sr_id=back["id"])
        self.assertEqual((line.cost_at_post, line.staff_cost), (D("200"), D("240")))
        self.assertEqual(D(back["items"][0]["staff_cost"]), D("240"))

    def test_returning_an_old_line_leaves_it_empty_and_reads_as_the_actual_cost(self):
        doc = self.sell(self.cases(2))
        SalesOrderItem.objects.filter(so_id=doc["id"]).update(staff_cost=None)
        self.company_rule("percent", "90")
        back = self.give_back(doc)
        self.assertIsNone(SalesReturnItem.objects.get(sr_id=back["id"]).staff_cost)
        self.assertEqual(D(back["items"][0]["staff_cost"]), D("200"))


class ReportTests(_Shop):
    def ask(self, client, *measures):
        today = timezone.localdate().isoformat()
        r = client.post(QUERY, {"measures": list(measures), "dimensions": [],
                                "period": {"from": today, "to": today}}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        return {k: D(str(v)) for k, v in r.json()["totals"].items()}

    def test_staff_profit_is_sales_minus_the_recorded_staff_cost(self):
        self.company_rule("percent", "20")
        self.sell(self.cases(2))                                    # 780 − 240
        old = self.sell(self.cases(1))                              # 390 − 100(當成舊單:沒有記)
        SalesOrderItem.objects.filter(so_id=old["id"]).update(staff_cost=None)
        got = self.ask(self.c.clerk, "sales_untaxed", "sales_cost", "sales_staff_cost", "sales_profit", "staff_profit")
        self.assertEqual(got["sales_untaxed"], D("1170"))
        self.assertEqual((got["sales_cost"], got["sales_profit"]), (D("300"), D("870")))            # 實際的照舊
        self.assertEqual((got["sales_staff_cost"], got["staff_profit"]), (D("340"), D("830")))

    def test_without_any_rule_staff_profit_equals_the_profit(self):
        self.sell(self.cases(2), self.phone("甲P1"))
        got = self.ask(self.c.clerk, "sales_profit", "staff_profit", "gross_profit", "staff_gross_profit")
        self.assertEqual(got["staff_profit"], got["sales_profit"])
        self.assertEqual(got["staff_gross_profit"], got["gross_profit"])

    def test_returns_are_taken_off_with_what_was_recorded(self):
        self.company_rule("percent", "20")
        kept, gone = self.sell(self.cases(2)), self.sell(self.cases(1))
        r = self.c.admin.post("/api/v1/sales-returns/", {"original_so": gone["id"], "payment_method": "cash"},
                              format="json")
        self.assertEqual(r.status_code, 201, r.content.decode())
        got = self.ask(self.c.admin, "staff_profit", "staff_gross_profit", "return_staff_cost", "gross_profit")
        self.assertEqual(got["staff_profit"], D("1170") - D("360"))
        self.assertEqual(got["return_staff_cost"], D("120"))
        self.assertEqual(got["staff_gross_profit"], D("780") - D("240"))
        self.assertEqual(got["gross_profit"], D("780") - D("200"))

    def test_goods_that_do_not_count_toward_profit_are_left_out(self):
        self.company_rule("plus", "50")
        Product.objects.filter(pk=self.c.case.pk).update(counts_margin=False)
        self.sell(self.cases(2))
        got = self.ask(self.c.clerk, "sales_staff_cost", "staff_profit")
        self.assertEqual((got["sales_staff_cost"], got["staff_profit"]), (D("0"), D("0")))

    def test_the_menu_offers_them_to_everyone(self):
        keys = {m["key"] for m in self.c.clerk.get("/api/v1/analytics/catalog/").json()["measures"]}
        self.assertLessEqual({"sales_staff_cost", "staff_profit", "staff_gross_profit", "return_staff_cost"}, keys)


class TwoPeopleAtOnceTests(TransactionTestCase):
    """真的兩條連線:店員開單的同時,另一個人的進貨單正要提交(握著這家店這個商品的庫存鎖)。
    開單要等他提交,而且**鎖到之後才讀**平均成本 —— 複審抓到的:明細連同商品是等鎖之前讀的,
    拿那個舊平均去算業務員成本,會跟同一行的實際成本(鎖到之後才讀)對不起來、毛利多算。"""

    def meanwhile(self, statements, hold=0.8):
        """另一條連線執行這些 SQL、停一下再提交。回傳時它已經握著鎖。"""
        holding = threading.Event()

        def work():
            other = connections.create_connection("default")
            try:
                other.ensure_connection()
                other.set_autocommit(False)
                with other.cursor() as cur:
                    for sql, params in statements:
                        cur.execute(sql, params)
                holding.set()
                time.sleep(hold)
                other.commit()
            finally:
                other.close()

        t = threading.Thread(target=work)
        t.start()
        self.addCleanup(t.join)
        self.assertTrue(holding.wait(5))
        return t

    def test_a_purchase_that_lands_while_the_sale_waits_is_what_gets_marked_up(self):
        c = Company("a", "甲通訊行", "甲")
        c.purchase(case_qty=1)                                            # 1 個、平均成本 100
        Tenant.objects.filter(pk=c.tenant.pk).update(staff_cost_mode="percent", staff_cost_value=D("20"))
        balance = StockBalance.objects.get(tenant=c.tenant, product=c.case, warehouse=c.wh)
        # 另一個人:再進 1 個、成本 300 → 這家店與全公司的平均都變成 200(還沒提交)
        t = self.meanwhile([
            (f"SELECT 1 FROM {StockBalance._meta.db_table} WHERE id = %s FOR UPDATE", [balance.pk]),
            (f"UPDATE {StockBalance._meta.db_table} SET qty = 2, weighted_avg_cost = 200 WHERE id = %s", [balance.pk]),
            (f"UPDATE {Product._meta.db_table} SET weighted_avg_cost = 200 WHERE id = %s", [c.case.pk]),
        ])
        doc = c.sell(case_qty=1)                                          # 等他提交才做得下去
        t.join()
        line = SalesOrderItem.objects.get(so_id=doc["id"])
        self.assertEqual((line.cost_at_post, line.staff_cost, line.staff_cost_rule),
                         (D("200"), D("240"), "company:percent:20.00"))

