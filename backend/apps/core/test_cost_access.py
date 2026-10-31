"""誰看得到實際成本與進價(owner 2026-10-28;規則在 core/cost_access.py)。

「除了管理者以外，其他所有人看的都是業務員成本（沒有設定則為實際成本），以及業務員毛利」;
進貨單、進貨明細、叫貨單、營業日報裡每一張進貨單的金額:有「進貨入庫」或「廠商叫貨」的人才看得到;維修也換成業務員成本。
這裡驗的是**伺服器回的資料裡根本沒有**,不是畫面藏起來。
"""
from decimal import Decimal as D

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.backup.tests.factory import Company
from apps.core import staff_cost
from apps.repairs.models import RepairOrderPart
from apps.tenants.models import Tenant, UserProfile


class _Shop(TestCase):
    def setUp(self):
        self.c = Company("a", "甲通訊行", "甲")
        self.t = self.c.tenant
        # 皮套 9 個、每個成本 100;手機一支成本 20000
        self.c.purchase(case_qty=9, phone_serials=["甲P1"])

    def again(self, user):
        """重新讀帳號(權限、公司的設定改過之後;測試的連線一直拿著同一個帳號物件)。"""
        return Company.client(get_user_model().objects.get(pk=user.pk))

    def clerk_without_prices(self):
        UserProfile.objects.filter(user=self.c.clerk_user).update(denied_abilities=["purchase", "vendor_order"])
        return self.again(self.c.clerk_user)

    def company_rule(self, mode, value):
        Tenant.objects.filter(pk=self.t.pk).update(staff_cost_mode=mode, staff_cost_value=D(value))
        return self.again(self.c.admin_user), self.again(self.c.clerk_user)


class ProductAndStockTests(_Shop):
    def test_average_cost_only_for_managers_everyone_has_the_staff_cost(self):
        admin, clerk = self.company_rule("percent", "20")
        url = f"/api/v1/products/{self.c.case.id}/"
        mine = clerk.get(url).json()
        self.assertNotIn("weighted_avg_cost", mine)
        self.assertEqual(D(mine["staff_cost"]), D("120"))
        self.assertEqual(D(admin.get(url).json()["weighted_avg_cost"]), D("100"))

        # 庫存查詢(每個商品一列)
        rows = {p["id"]: p for p in clerk.get("/api/v1/products/stock-matrix/").json()["products"]}
        self.assertNotIn("weighted_avg_cost", rows[self.c.case.id])
        self.assertEqual(D(rows[self.c.case.id]["staff_cost"]), D("120"))
        rows = {p["id"]: p for p in admin.get("/api/v1/products/stock-matrix/").json()["products"]}
        self.assertEqual(D(rows[self.c.case.id]["weighted_avg_cost"]), D("100"))

        # 各門市的平均成本
        balance = clerk.get("/api/v1/stock-balances/").json()["results"][0]
        self.assertNotIn("weighted_avg_cost", balance)
        self.assertIn("weighted_avg_cost", admin.get("/api/v1/stock-balances/").json()["results"][0])

    def test_last_purchase_price_follows_the_purchase_items(self):
        url = f"/api/v1/products/{self.c.case.id}/"
        self.assertIn("last_purchase_price", self.c.admin.get(url).json())
        self.assertIn("last_purchase_price", self.c.clerk.get(url).json())          # 預設開著「進貨入庫」
        UserProfile.objects.filter(user=self.c.clerk_user).update(denied_abilities=["purchase"])
        self.assertIn("last_purchase_price", self.again(self.c.clerk_user).get(url).json())    # 還有「廠商叫貨」
        self.assertNotIn("last_purchase_price", self.clerk_without_prices().get(url).json())

    def test_serial_goods_have_no_rule_yet(self):
        """帶序號的業務員成本 = 那一台帳上的成本(新機是平均成本),所以序號清單(inventory/reports.py、report_views.py)
        每一台的成本照舊給大家。要打開這個開關,先把那兩處改成照業務員成本給,再改這一條。
        這一台真的進價、帳上的成本只給管理員(2026-10-31:新機賣掉記平均成本,店員看得到進價就挑得出便宜的那批)。"""
        self.assertFalse(staff_cost.SERIAL_GOODS_TOO)
        admin, clerk = self.company_rule("percent", "20")
        unit = clerk.get("/api/v1/serials/", {"product": self.c.phone.id}).json()["results"][0]
        self.assertEqual(D(unit["staff_cost"]), D("20000"))
        self.assertNotIn("purchase_unit_cost", unit)
        self.assertNotIn("book_cost", unit)
        unit = admin.get("/api/v1/serials/", {"product": self.c.phone.id}).json()["results"][0]
        self.assertEqual((D(unit["purchase_unit_cost"]), D(unit["book_cost"])), (D("20000"), D("20000")))
        # 序號履歷也一樣(那一台的資料不帶進價,收購來源那一行是業務員成本)
        history = clerk.get(f"/api/v1/serials/{unit['id']}/history/").json()
        self.assertNotIn("purchase_unit_cost", history["serial"])
        self.assertEqual(D(history["acquisition"]["amount"]), D("20000"))


class SalesTests(_Shop):
    def test_lines_reports_and_returns_carry_only_the_staff_cost_for_clerks(self):
        admin, clerk = self.company_rule("percent", "20")
        doc = self.c.sell(case_qty=2)
        line = clerk.get(f"/api/v1/sales-orders/{doc['id']}/").json()["items"][0]
        self.assertNotIn("cost_at_post", line)
        self.assertNotIn("staff_cost_rule", line)
        self.assertEqual(D(line["staff_cost"]), D("240"))
        line = admin.get(f"/api/v1/sales-orders/{doc['id']}/").json()["items"][0]
        self.assertEqual((D(line["cost_at_post"]), D(line["staff_cost"])), (D("200"), D("240")))

        back = admin.post("/api/v1/sales-returns/", {"original_so": doc["id"], "payment_method": "cash"},
                          format="json").json()
        line = clerk.get(f"/api/v1/sales-returns/{back['id']}/").json()["items"][0]
        self.assertNotIn("cost_at_post", line)
        self.assertEqual(D(line["staff_cost"]), D("240"))
        self.assertIn("cost_at_post", admin.get(f"/api/v1/sales-returns/{back['id']}/").json()["items"][0])

        report = clerk.get("/api/v1/sales-daily-report/").json()
        for item in [it for o in (*report["orders"], *report["returns"]) for it in o["items"]]:
            self.assertNotIn("cost_at_post", item)
            self.assertEqual(abs(D(item["staff_cost"])), D("240"))
        report = admin.get("/api/v1/sales-daily-report/").json()
        self.assertEqual(D(report["orders"][0]["items"][0]["cost_at_post"]), D("200"))


class PurchasePriceTests(_Shop):
    def test_purchase_documents_need_purchase_or_vendor_ordering(self):
        po = self.c.purchase(case_qty=1)
        urls = ("/api/v1/purchase-orders/", f"/api/v1/purchase-orders/{po['id']}/",
                "/api/v1/purchase-line-report/", "/api/v1/identity/intakes/", "/api/v1/vendor-orders/",
                "/api/v1/assistant/commands/")
        nobody = self.clerk_without_prices()
        for url in urls:
            r = nobody.get(url)
            self.assertEqual(r.status_code, 403, url)
            self.assertNotIn("100", r.content.decode().replace("403", ""), url)
        UserProfile.objects.filter(user=self.c.clerk_user).update(denied_abilities=["purchase"])
        orderer = self.again(self.c.clerk_user)
        for url in urls:
            self.assertEqual(orderer.get(url).status_code, 200, url)
        for url in urls:
            self.assertEqual(self.c.admin.get(url).status_code, 200, url)

    def test_business_daily_lists_purchases_without_amounts_but_keeps_the_cash_total(self):
        self.c._post("/api/v1/purchase-orders/", {
            "supplier": self.c.supplier.id, "warehouse": self.c.wh.id, "tax_method": "untaxed",
            "payment_method": self.c.cash.id, "items": [{"product": self.c.case.id, "qty": 2, "unit_price": "100"}],
        })
        from django.utils import timezone
        url = f"/api/v1/reports/business-daily/?warehouse={self.c.wh.id}&date={timezone.localdate().isoformat()}"
        r = self.clerk_without_prices().get(url)
        self.assertEqual(r.status_code, 200, r.content.decode())
        mine = r.json()
        self.assertEqual(len(mine["purchases"]["rows"]), 1)
        self.assertNotIn("total_cost", mine["purchases"]["rows"][0])
        self.assertEqual(mine["purchases"]["total"], 200)        # 現金櫃流水要加得起來
        boss = self.c.admin.get(url).json()
        self.assertEqual(D(boss["purchases"]["rows"][0]["total_cost"]), D("200"))
        self.assertEqual(boss["net_change"], mine["net_change"])


class RepairTests(_Shop):
    def order(self, client, paid="1000"):
        r = client.post("/api/v1/repair-orders/", {
            "warehouse": self.c.wh.id, "customer": self.c.customer.id, "received_date": "2026-10-28",
            "mode": "in_house", "unlock_method": "none", "host_model_name": "iPhone 15",
            "customer_paid_amount": paid, "parts_input": [{"part_product": self.c.case.id, "qty": 2}],
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content.decode())
        return r.json()

    def test_parts_record_the_staff_cost_and_clerks_see_the_staff_margin(self):
        admin, clerk = self.company_rule("percent", "50")
        doc = self.order(admin)
        line = RepairOrderPart.objects.get(repair_order_id=doc["id"])
        self.assertEqual((line.unit_cost, line.staff_unit_cost), (D("100"), D("150")))      # 同一刻記
        url = f"/api/v1/repair-orders/{doc['id']}/"
        mine = clerk.get(url).json()
        self.assertNotIn("unit_cost", mine["parts"][0])
        self.assertNotIn("suggested_quote", mine)
        self.assertEqual(D(mine["parts"][0]["staff_unit_cost"]), D("150"))
        self.assertEqual(D(mine["margin"]), D("700"))                       # 1000 − 150 × 2
        self.assertEqual(D(mine["margin_breakdown"]["sales_person_amount"]), D("700"))
        boss = admin.get(url).json()
        self.assertEqual((D(boss["parts"][0]["unit_cost"]), D(boss["margin"])), (D("100"), D("800")))
        preview = clerk.get(f"{url}quote-preview/").json()
        self.assertEqual((D(preview["margin"]), D(preview["suggested_quote"])), (D("700"), D("300")))
        preview = admin.get(f"{url}quote-preview/").json()
        self.assertEqual((D(preview["margin"]), D(preview["suggested_quote"])), (D("800"), D("200")))

        # 之後改規則不影響這一張(跟銷貨單一樣)
        admin, clerk = self.company_rule("percent", "90")
        self.assertEqual(D(clerk.get(url).json()["margin"]), D("700"))

    def test_parts_from_before_are_the_actual_cost_until_completed(self):
        admin, clerk = self.company_rule("percent", "50")
        doc = self.order(admin, paid="0")
        RepairOrderPart.objects.filter(repair_order_id=doc["id"]).update(staff_unit_cost=None)   # 10-28 之前加的
        url = f"/api/v1/repair-orders/{doc['id']}/"
        self.assertEqual(D(clerk.get(url).json()["parts"][0]["staff_unit_cost"]), D("100"))
        r = admin.post(f"{url}complete/")
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.assertEqual(RepairOrderPart.objects.get(repair_order_id=doc["id"]).staff_unit_cost, D("150"))

    def test_a_real_zero_cost_is_not_recosted_at_completion(self):
        """零件實際成本真的是 0:加的時候記了業務員成本,之後改規則再完工,不能被新規則蓋掉(複審 2026-10-28 抓到的)。"""
        from apps.catalog.models import Product
        Product.objects.filter(pk=self.c.case.pk).update(weighted_avg_cost=D("0"))
        admin, clerk = self.company_rule("plus", "100")
        doc = self.order(admin, paid="0")
        line = RepairOrderPart.objects.get(repair_order_id=doc["id"])
        self.assertEqual((line.unit_cost, line.staff_unit_cost), (D("0"), D("100")))
        admin, clerk = self.company_rule("plus", "200")
        self.assertEqual(admin.post(f"/api/v1/repair-orders/{doc['id']}/complete/").status_code, 200)
        line.refresh_from_db()
        self.assertEqual((line.unit_cost, line.staff_unit_cost), (D("0"), D("100")))

    def test_monthly_report_and_parts_usage_use_the_staff_cost_for_clerks(self):
        admin, clerk = self.company_rule("percent", "50")
        doc = self.order(admin, paid="0")
        self.assertEqual(admin.post(f"/api/v1/repair-orders/{doc['id']}/complete/").status_code, 200)
        RepairOrderPart.objects.filter(repair_order_id=doc["id"]).update(staff_unit_cost=D("150"))
        from apps.repairs.models import RepairOrder
        RepairOrder.objects.filter(pk=doc["id"]).update(customer_paid_amount=D("1000"))
        mine = clerk.get("/api/v1/repair-monthly-report/").json()["totals"]
        boss = admin.get("/api/v1/repair-monthly-report/").json()["totals"]
        self.assertEqual((D(mine["parts"]), D(mine["margin"])), (D("300"), D("700")))
        self.assertEqual((D(boss["parts"]), D(boss["margin"])), (D("200"), D("800")))

        row = clerk.get("/api/v1/parts-usage-report/").json()["rows"][0]
        self.assertNotIn("unit_cost", row)
        self.assertEqual(D(row["staff_cost"]), D("150"))
        self.assertEqual(D(admin.get("/api/v1/parts-usage-report/").json()["rows"][0]["unit_cost"]), D("100"))
