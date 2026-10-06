"""門號合約到期的名單、聯絡紀錄、今日總覽的筆數、報表。

名單是拿來打電話的:該提醒的沒出現(漏掉客人)、不該提醒的一直出現(已經續約、已經講過不續、單已經作廢或退掉)都算錯。
"""
from datetime import date, timedelta

from django.test import TestCase

from apps.analytics import engine
from apps.backup.tests.factory import Company
from apps.catalog.models import Product
from apps.core.dates import add_months
from apps.parties.models import Carrier, TelecomPlan
from apps.sales import contracts as rules
from apps.sales.models import (
    ContractFollowUp, SalesOrder, SalesOrderItem, SalesReturn, SalesReturnItem,
)

TODAY = date.today()
URL = "/api/v1/telecom-contracts/"


class _Shop(TestCase):
    def setUp(self):
        self.c = Company("a", "甲通訊行", "甲")
        self.fet = Carrier.objects.create(tenant=self.c.tenant, code="FET", name="遠傳")
        self.cht = Carrier.objects.create(tenant=self.c.tenant, code="CHT", name="中華電信")
        self.plan = TelecomPlan.objects.create(
            tenant=self.c.tenant, carrier=self.fet, name="599 續約", monthly_fee=599,
            contract_months=24, kind="renewal",
        )
        self.plan_cht = TelecomPlan.objects.create(
            tenant=self.c.tenant, carrier=self.cht, name="799 續約", monthly_fee=799,
            contract_months=30, kind="renewal",
        )
        Product.objects.filter(pk=self.c.case.pk).update(
            allows_telecom_line=True, allows_commission=True)
        self.c.purchase(case_qty=30)
        self.c.purchase(warehouse=self.c.warehouses[1], case_qty=30)

    def sell(self, msisdn, ends_in_days, plan=None, client=None, warehouse=None):
        """賣一筆門號續約,合約在 ends_in_days 天後到期(負的 = 已經過期)。回那一行明細。"""
        return self.sell_lines([msisdn], ends_in_days, plan, client, warehouse)[0]

    def sell_lines(self, numbers, ends_in_days, plan=None, client=None, warehouse=None):
        """同一張單賣好幾個門號(每個門號一行)。回那幾行明細,順序 = 傳進來的順序。"""
        plan = plan or self.plan
        end = TODAY + timedelta(days=ends_in_days)
        start = add_months(end, -plan.contract_months)
        resp = (client or self.c.admin).post("/api/v1/sales-orders/", {
            "customer": self.c.customer.id, "warehouse": (warehouse or self.c.wh).id,
            "tax_method": "untaxed", "payments": [],
            "items": [{"product": self.c.case.id, "qty": 1, "unit_price": "0", "msisdn": msisdn,
                       "telecom_plan": plan.id, "activation_date": start.isoformat()}
                      for msisdn in numbers],
        }, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        items = list(SalesOrderItem.objects.filter(so_id=resp.json()["id"]).order_by("line_no", "id"))
        # 起算日 + 綁約月數有月底進位的誤差:直接把到期日釘在要測的那一天
        SalesOrderItem.objects.filter(pk__in=[it.pk for it in items]).update(contract_end=end)
        for it in items:
            it.refresh_from_db()
        return items

    def listing(self, client=None, **params):
        resp = (client or self.c.admin).get(URL, params)
        self.assertEqual(resp.status_code, 200, resp.content)
        return resp.json()

    def numbers(self, client=None, **params):
        return [r["msisdn"] for r in self.listing(client, **params)["results"]]

    def follow(self, item, status, note="", client=None, expect=200):
        resp = (client or self.c.admin).post(
            f"{URL}{item.id}/follow-up/", {"status": status, "note": note}, format="json")
        self.assertEqual(resp.status_code, expect, resp.content)
        return resp.json()


class WhoIsOnTheListTests(_Shop):
    def test_due_soon_and_overdue_are_listed_far_ones_are_not(self):
        self.sell("0911000001", 10)
        self.sell("0911000002", -5)                      # 過期 5 天還沒續
        self.sell("0911000003", 89)
        self.sell("0911000004", 200)                     # 還早
        data = self.listing()
        self.assertEqual([r["msisdn"] for r in data["results"]],
                         ["0911000002", "0911000001", "0911000003"])   # 最急的在最上面
        self.assertEqual([r["days_left"] for r in data["results"]], [-5, 10, 89])
        self.assertEqual(data["counts"]["pending"], 3)
        self.assertEqual(data["counts"]["overdue"], 1)
        self.assertEqual(data["remind_months"], 3)
        # 想看遠一點:不限期間就全部列出來
        self.assertEqual(len(self.numbers(until="all")), 4)
        self.assertEqual(self.numbers(until=(TODAY + timedelta(days=30)).isoformat()),
                         ["0911000002", "0911000001"])
        self.assertEqual(len(self.numbers(months=12)), 4)     # 今天起一年內
        self.assertEqual(self.c.admin.get(URL, {"months": "abc"}).status_code, 400)

    def test_a_newer_contract_on_the_same_number_means_renewed(self):
        old = self.sell("0912-345-678", 20)              # 當初打的有破折號
        self.assertEqual(self.numbers(), ["0912-345-678"])
        new = self.sell("0912345678", 700)               # 同一個門號續約了(寫法不一樣)
        self.assertEqual(self.numbers(), [])             # 舊的那一筆不用再提醒
        self.assertEqual(self.numbers(state="renewed"), ["0912-345-678"])
        self.assertEqual(self.listing()["counts"], {
            "pending": 0, "overdue": 0, "contacted": 0, "declined": 0, "renewed": 1})
        # 新約被作廢 → 舊的那一筆又回到名單上
        self.c.admin.post(f"/api/v1/sales-orders/{new.so_id}/void/", {}, format="json")
        self.assertEqual(self.numbers(), ["0912-345-678"])
        self.assertEqual(rules.contracts(self.c.tenant).get(pk=old.pk).state, rules.OPEN)

    def test_a_newer_contract_that_was_returned_does_not_count_as_a_renewal(self):
        # 續約那一張單後來整張退了:等於沒續,舊的那一筆要回到名單上(只有「沒作廢、沒被退」的新約才算續約)
        old = self.sell("0916000001", 20)
        new = self.sell("0916000001", 700)
        other = self.sell("0916000002", 30)              # 別的門號,自己那張單沒有被退
        self.assertEqual(self.numbers(), ["0916000002"])
        r = self.c.admin.post("/api/v1/sales-returns/", {"original_so": new.so_id}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(self.numbers(), ["0916000001", "0916000002"])
        self.assertEqual(self.listing()["counts"]["renewed"], 0)
        # 反過來:舊的那一張被退掉,新的那一筆照樣是一筆正常的合約(不會因為舊的被退而怎樣)
        self.c.admin.post(f"/api/v1/sales-returns/{r.json()['id']}/void/", {}, format="json")
        r2 = self.c.admin.post("/api/v1/sales-returns/", {"original_so": old.so_id}, format="json")
        self.assertEqual(r2.status_code, 201, r2.content)
        states = dict(rules.contracts(self.c.tenant).values_list("pk", "state"))
        self.assertEqual(states, {new.pk: rules.OPEN, other.pk: rules.OPEN})

    def test_another_sale_starting_the_same_day_is_not_a_renewal(self):
        # 同一個門號、同一天起算、兩張單(打重複沒作廢,或兩份不同月數的合約):
        # 不拿「誰比較後面建的」當續約 —— 先到期的那一筆要照樣提醒
        short = self.sell("0915550001", 20)                       # 24 個月的,20 天後到期
        start = short.activation_date
        resp = self.c.admin.post("/api/v1/sales-orders/", {
            "customer": self.c.customer.id, "warehouse": self.c.wh.id,
            "tax_method": "untaxed", "payments": [],
            "items": [{"product": self.c.case.id, "qty": 1, "unit_price": "0", "msisdn": "0915550001",
                       "telecom_plan": self.plan_cht.id, "activation_date": start.isoformat()}],
        }, format="json")                                         # 後面建的、同一天起算、30 個月
        self.assertEqual(resp.status_code, 201, resp.content)
        longer = SalesOrderItem.objects.get(so_id=resp.json()["id"])
        self.assertEqual(longer.activation_date, start)
        states = dict(rules.contracts(self.c.tenant).values_list("pk", "state"))
        self.assertEqual(states, {short.pk: rules.OPEN, longer.pk: rules.OPEN})
        self.assertEqual(self.numbers(), ["0915550001"])
        self.assertEqual(self.listing()["counts"]["renewed"], 0)

    def test_numbers_without_real_digits_do_not_renew_each_other(self):
        # 門號欄打「-」「無」的舊單:去掉符號後都是空的,不能因此互相當成「同一個門號續約了」
        self.sell("-", 10)
        self.sell("無", 20)
        self.sell("--", 700)
        self.sell("0912", 30)                             # 只打了前幾碼
        self.sell("09-12", 700)
        data = self.listing()
        self.assertEqual([r["msisdn"] for r in data["results"]], ["-", "無", "0912"])
        self.assertEqual(data["counts"]["renewed"], 0)

    def test_the_same_number_twice_on_one_sale_is_not_a_renewal(self):
        # 同一張單上同一個門號打了兩行(打重複、或一個門號加兩個方案):不算其中一行續了另一行
        first, second = self.sell_lines(["0918000001", "0918-000-001"], 10)
        self.assertEqual(self.listing()["counts"], {
            "pending": 2, "overdue": 0, "contacted": 0, "declined": 0, "renewed": 0})
        # 之後另一張單真的續約了 → 兩行都算已續約
        self.sell("0918000001", 700)
        states = dict(rules.contracts(self.c.tenant).filter(
            pk__in=[first.pk, second.pk]).values_list("pk", "state"))
        self.assertEqual(states, {first.pk: rules.RENEWED, second.pk: rules.RENEWED})
        self.assertEqual(self.numbers(), [])

    def test_an_old_partial_return_only_drops_the_line_that_was_returned(self):
        # 舊資料:一張單兩個門號,當時只退了其中一個。沒退的那一個還是合約,到期要提醒
        kept, returned = self.sell_lines(["0919000001", "0919000002"], 10)
        sr = SalesReturn.objects.create(
            tenant=self.c.tenant, original_so_id=kept.so_id, customer=self.c.customer,
            warehouse=self.c.wh, payment_method="cash")
        SalesReturnItem.objects.create(
            tenant=self.c.tenant, sr=sr, original_item=returned, product=returned.product,
            qty=1, unit_price=0, amount=0)
        self.assertEqual(self.numbers(), ["0919000001"])
        # 被退的那個門號之後在別張單續約,不會被「已經退掉的那一行」影響;沒退的那個不受牽連
        self.sell("0919000002", 700)
        self.assertEqual(self.numbers(), ["0919000001"])
        self.assertEqual(self.listing()["counts"]["renewed"], 0)
        # 那張舊銷退作廢(等於沒退)→ 被退的那一行回來,而且它已經有新約了
        SalesReturn.objects.filter(pk=sr.pk).update(is_void=True)
        self.assertEqual(self.numbers(), ["0919000001"])
        self.assertEqual(self.numbers(state="renewed"), ["0919000002"])

    def test_a_sale_without_a_customer_is_still_listed(self):
        # 散客的單可以沒有客戶(舊資料、別的入口):名單不能因為這一筆整頁打不開
        item = self.sell("0910000001", 10)
        SalesOrder.objects.filter(pk=item.so_id).update(customer=None)
        row = self.listing()["results"][0]
        self.assertEqual((row["msisdn"], row["customer_name"], row["customer_phone"]),
                         ("0910000001", "", ""))
        self.assertEqual(self.follow(item, "contacted")["customer_name"], "")

    def test_same_number_in_another_company_is_unrelated(self):
        mine = self.sell("0917000001", 20)
        b = Company("b", "乙通訊行", "乙")
        carrier = Carrier.objects.create(tenant=b.tenant, code="FET", name="遠傳")
        plan = TelecomPlan.objects.create(tenant=b.tenant, carrier=carrier, name="599 續約",
                                          monthly_fee=599, contract_months=24, kind="renewal")
        Product.objects.filter(pk=b.case.pk).update(allows_telecom_line=True)
        b.purchase(case_qty=5)
        resp = b.admin.post("/api/v1/sales-orders/", {
            "customer": b.customer.id, "warehouse": b.wh.id, "tax_method": "untaxed", "payments": [],
            "items": [{"product": b.case.id, "qty": 1, "unit_price": "0", "msisdn": "0917000001",
                       "telecom_plan": plan.id, "activation_date": TODAY.isoformat()}],
        }, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        # 別家公司剛好賣了同一個門號:我們這一筆不會因此變成「已續約」
        self.assertEqual(rules.contracts(self.c.tenant).get(pk=mine.pk).state, rules.OPEN)
        self.assertEqual(self.numbers(), ["0917000001"])

    def test_voided_and_fully_returned_sales_are_not_contracts(self):
        gone = self.sell("0913000001", 10)
        back = self.sell("0913000002", 10)
        self.sell("0913000003", 10)
        self.c.admin.post(f"/api/v1/sales-orders/{gone.so_id}/void/", {}, format="json")
        r = self.c.admin.post("/api/v1/sales-returns/", {"original_so": back.so_id}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(self.numbers(), ["0913000003"])
        # 銷退單作廢(等於沒退)→ 那一筆回來
        self.c.admin.post(f"/api/v1/sales-returns/{r.json()['id']}/void/", {}, format="json")
        self.assertEqual(sorted(self.numbers()), ["0913000002", "0913000003"])

    def test_filters(self):
        self.sell("0914000001", 10)
        self.sell("0914000002", 20, plan=self.plan_cht)
        self.assertEqual(self.numbers(carrier=self.cht.id), ["0914000002"])
        self.assertEqual(self.numbers(search="4000001"), ["0914000001"])
        self.assertEqual(sorted(self.numbers(search=self.c.customer.name)),
                         ["0914000001", "0914000002"])
        self.assertEqual(self.numbers(search="沒有這個人"), [])
        self.assertEqual(self.c.admin.get(URL, {"state": "nope"}).status_code, 400)
        self.assertEqual(self.c.admin.get(URL, {"until": "2026-13-40"}).status_code, 400)
        # 分頁上的數字跟著選的電信業者走,不跟著搜尋走
        self.assertEqual(self.listing(carrier=self.cht.id)["counts"]["pending"], 1)
        self.assertEqual(self.listing(search="4000001")["counts"]["pending"], 2)

    def test_paging_continues_after_the_last_row_shown_so_nobody_is_skipped(self):
        # 到期日故意有同一天的(第 2、3 筆;第 4、5 筆),而且一頁的最後一列跟下一頁的第一列同一天:
        # 「接在後面」同一天要靠編號分,不能把同一天的整批跳過
        items = [self.sell(f"09190000{n:02d}", 10 + (n + 1) // 2) for n in range(5)]
        cursor = lambda row: f"{row['contract_end']},{row['id']}"   # noqa: E731
        first = self.listing(page_size=2)
        self.assertEqual((first["total"], first["has_more"], first["has_prev"]), (5, True, False))
        self.assertEqual([r["msisdn"] for r in first["results"]], ["0919000000", "0919000001"])
        # 別的店員(或自己)把第一頁的第一筆標掉:後面的往前遞補一格。
        # 接在「畫面最後一列」後面拿下一頁 —— 遞補上來的那一筆不會被跳過、也不會重複
        self.follow(items[0], "contacted")
        second = self.listing(page_size=2, after=cursor(first["results"][-1]))
        self.assertEqual([r["msisdn"] for r in second["results"]], ["0919000002", "0919000003"])
        self.assertEqual((second["has_more"], second["has_prev"], second["total"]), (True, True, 4))
        third = self.listing(page_size=2, after=cursor(second["results"][-1]))
        self.assertEqual([r["msisdn"] for r in third["results"]], ["0919000004"])
        self.assertEqual((third["has_more"], third["has_prev"]), (False, True))
        # 往回:排在這一頁第一列前面的那幾筆(順序照舊)
        back = self.listing(page_size=2, before=cursor(third["results"][0]))
        self.assertEqual([r["msisdn"] for r in back["results"]], ["0919000002", "0919000003"])
        self.assertEqual((back["has_more"], back["has_prev"]), (True, True))
        top = self.listing(page_size=2, before=cursor(back["results"][0]))
        self.assertEqual([r["msisdn"] for r in top["results"]], ["0919000001"])
        self.assertEqual((top["has_more"], top["has_prev"]), (True, False))
        # 最後一列後面沒有人了:空的,但照實講「前面還有人」(畫面靠它回得去)
        beyond = self.listing(page_size=2, after=cursor(third["results"][-1]))
        self.assertEqual((beyond["results"], beyond["total"]), ([], 4))
        self.assertEqual((beyond["has_more"], beyond["has_prev"]), (False, True))
        # 第一列前面沒有人:空的,後面還有人
        ahead = self.listing(page_size=2, before=cursor(top["results"][0]))
        self.assertEqual((ahead["results"], ahead["has_more"], ahead["has_prev"]), ([], True, False))
        # 這一頁的人都被標掉(畫面上還留著他們):同一個游標重抓是空的,但前面那兩位還在 → 上一頁要回得去
        self.follow(items[4], "contacted")
        emptied = self.listing(page_size=2, after=cursor(second["results"][-1]))
        self.assertEqual((emptied["results"], emptied["total"]), ([], 3))
        self.assertEqual((emptied["has_more"], emptied["has_prev"]), (False, True))
        # 整個分頁都沒人了:兩邊都沒有
        nobody = self.listing(state="declined", after=cursor(first["results"][0]))
        self.assertEqual((nobody["results"], nobody["has_more"], nobody["has_prev"]), ([], False, False))
        for bad in ("abc", "2026-10-06", "2026-10-06,x"):
            self.assertEqual(self.c.admin.get(URL, {"after": bad}).status_code, 400, bad)
        self.assertEqual(self.c.admin.get(URL, {"before": "x,1"}).status_code, 400)

    def test_paging_on_a_newest_first_tab(self):
        # 不續約、已續約是「新的在上面」:接在後面 = 到期日更早的
        items = [self.sell(f"09170000{n:02d}", 10 + (n + 1) // 2) for n in range(3)]   # 後兩筆同一天到期
        for it in items:
            self.follow(it, "declined")
        cursor = lambda row: f"{row['contract_end']},{row['id']}"   # noqa: E731
        first = self.listing(state="declined", page_size=1)
        self.assertEqual([r["msisdn"] for r in first["results"]], ["0917000002"])
        self.assertEqual((first["has_more"], first["has_prev"]), (True, False))
        second = self.listing(state="declined", page_size=1, after=cursor(first["results"][-1]))
        self.assertEqual([r["msisdn"] for r in second["results"]], ["0917000001"])      # 同一天,編號小的在後面
        self.assertEqual((second["has_more"], second["has_prev"]), (True, True))
        third = self.listing(state="declined", page_size=1, after=cursor(second["results"][-1]))
        self.assertEqual([r["msisdn"] for r in third["results"]], ["0917000000"])
        self.assertEqual((third["has_more"], third["has_prev"]), (False, True))
        back = self.listing(state="declined", page_size=2, before=cursor(third["results"][0]))
        self.assertEqual([r["msisdn"] for r in back["results"]], ["0917000002", "0917000001"])

    def test_remind_window_follows_the_company_setting(self):
        self.sell("0915000001", 100)
        self.assertEqual(self.numbers(), [])
        r = self.c.admin.patch("/api/v1/tenant-settings/", {"contract_remind_months": 6}, format="json")
        self.assertEqual((r.status_code, r.json()["contract_remind_months"]), (200, 6))
        self.assertEqual(self.numbers(), ["0915000001"])
        for bad in (0, 25, "abc"):
            self.assertEqual(self.c.admin.patch(
                "/api/v1/tenant-settings/", {"contract_remind_months": bad}, format="json").status_code, 400)
        # 店員不能改設定
        self.assertEqual(self.c.clerk.patch(
            "/api/v1/tenant-settings/", {"contract_remind_months": 1}, format="json").status_code, 403)
        self.c.tenant.refresh_from_db()
        self.assertEqual(self.c.tenant.contract_remind_months, 6)


class FollowUpTests(_Shop):
    def test_mark_contacted_then_declined_then_clear(self):
        item = self.sell("0921000001", 10)
        row = self.follow(item, "contacted", "說下週來店裡")
        self.assertEqual((row["state"], row["follow"]["status"], row["follow"]["note"]),
                         ("contacted", "contacted", "說下週來店裡"))
        self.assertTrue(row["follow"]["by"] and row["follow"]["at"])
        self.assertEqual(self.numbers(), [])                       # 不在待聯絡了
        self.assertEqual(self.numbers(state="contacted"), ["0921000001"])
        row = self.follow(item, "declined", "已經攜碼到別家")       # 同一筆改成不續約(只有一筆紀錄)
        self.assertEqual(row["state"], "declined")
        self.assertEqual(ContractFollowUp.objects.filter(item=item).count(), 1)
        self.assertEqual(self.numbers(state="declined"), ["0921000001"])
        self.assertEqual(self.numbers(state="contacted"), [])
        row = self.follow(item, "")                                # 標錯了,取消(備註也清掉)
        self.assertEqual((row["state"], row["follow"]), ("open", None))
        self.assertEqual(self.numbers(), ["0921000001"])
        self.assertFalse(ContractFollowUp.objects.filter(item=item).exists())

    def test_a_note_alone_keeps_the_customer_on_the_to_contact_list(self):
        # 打了沒人接:先記一句,人還在待聯絡(沒有狀態的紀錄不算「處理過」)
        item = self.sell("0925000001", 10)
        row = self.follow(item, "", "無人接聽,明天再打")
        self.assertEqual((row["state"], row["follow"]["status"], row["follow"]["note"]),
                         ("open", "", "無人接聽,明天再打"))
        self.assertTrue(row["follow"]["by"])
        self.assertEqual(self.numbers(), ["0925000001"])
        self.assertEqual(self.listing()["results"][0]["follow"]["note"], "無人接聽,明天再打")
        self.assertEqual(self.listing()["counts"]["pending"], 1)
        self.assertEqual(self.c.admin.get("/api/v1/home-summary/").json()["contracts_pending"], 1)
        # 聯絡上了 → 已聯絡;標錯按「未聯絡」回到待聯絡,備註照送來的留著
        self.follow(item, "contacted", "會來續")
        self.assertEqual(self.numbers(), [])
        row = self.follow(item, "", "會來續")
        self.assertEqual((row["state"], row["follow"]["status"], row["follow"]["note"]),
                         ("open", "", "會來續"))
        self.assertEqual(self.numbers(), ["0925000001"])
        self.assertEqual(ContractFollowUp.objects.filter(item=item).count(), 1)
        # 備註也清空 = 整筆紀錄拿掉
        self.assertEqual(self.follow(item, "", "   ")["follow"], None)
        self.assertFalse(ContractFollowUp.objects.filter(item=item).exists())

    def test_settings_are_saved_all_or_nothing(self):
        r = self.c.admin.patch("/api/v1/tenant-settings/", {
            "repair_warranty_days": 120, "contract_remind_months": 25}, format="json")
        self.assertEqual(r.status_code, 400)
        self.c.tenant.refresh_from_db()
        self.assertEqual((self.c.tenant.repair_warranty_days, self.c.tenant.contract_remind_months), (90, 3))
        r = self.c.admin.patch("/api/v1/tenant-settings/", {
            "repair_warranty_days": 120, "contract_remind_months": 6}, format="json")
        self.assertEqual((r.status_code, r.json()["repair_warranty_days"], r.json()["contract_remind_months"]),
                         (200, 120, 6))

    def test_what_cannot_be_marked(self):
        item = self.sell("0922000001", 10)
        self.follow(item, "maybe", expect=400)
        self.follow(SalesOrderItem(id=999999), "contacted", expect=400)
        # 不是門號合約的明細(一般商品那一行)
        plain = self.c.sell(case_qty=1)
        self.follow(SalesOrderItem.objects.get(so_id=plain["id"]), "contacted", expect=400)
        # 已經續約的不用再標
        self.sell("0922000001", 700)
        self.follow(item, "contacted", expect=400)
        # 作廢的單
        other = self.sell("0922000002", 10)
        self.c.admin.post(f"/api/v1/sales-orders/{other.so_id}/void/", {}, format="json")
        self.follow(other, "contacted", expect=400)
        self.assertFalse(ContractFollowUp.objects.exists())

    def test_a_contacted_customer_who_renews_counts_as_renewed(self):
        item = self.sell("0923000001", 10)
        self.follow(item, "contacted", "會來續")
        self.sell("0923000001", 700)
        counts = self.listing()["counts"]
        self.assertEqual((counts["contacted"], counts["renewed"]), (0, 1))
        self.assertEqual(self.listing(state="renewed")["results"][0]["follow"], None)

    def test_note_is_trimmed_and_capped(self):
        item = self.sell("0924000001", 10)
        row = self.follow(item, "contacted", "  " + "很" * 300 + "  ")
        self.assertEqual(len(row["follow"]["note"]), 200)


class WhoCanSeeTests(_Shop):
    def test_clerk_locked_to_a_store_only_sees_and_marks_that_stores_contracts(self):
        mine = self.sell("0931000001", 10)                                   # 店員自己的門市
        theirs = self.sell("0931000002", 10, warehouse=self.c.warehouses[1])  # 另一家門市賣的
        self.assertEqual(sorted(self.numbers()), ["0931000001", "0931000002"])   # 管理員看全部
        self.assertEqual(self.numbers(client=self.c.clerk), ["0931000001"])
        self.assertEqual(self.listing(client=self.c.clerk)["counts"]["pending"], 1)
        # 帶別家門市的編號也沒用
        self.assertEqual(self.numbers(client=self.c.clerk, warehouse=self.c.warehouses[1].id),
                         ["0931000001"])
        self.follow(theirs, "declined", client=self.c.clerk, expect=400)
        self.assertFalse(ContractFollowUp.objects.filter(item=theirs).exists())
        self.follow(mine, "contacted", client=self.c.clerk)
        # 管理員可以用門市篩
        self.assertEqual(self.numbers(warehouse=self.c.warehouses[1].id), ["0931000002"])

    def test_other_company_sees_nothing_and_cannot_mark(self):
        item = self.sell("0932000001", 10)
        other = Company("b", "乙通訊行", "乙")
        self.assertEqual(self.numbers(client=other.admin), [])
        self.assertEqual(self.listing(client=other.admin)["counts"]["pending"], 0)
        self.follow(item, "declined", client=other.admin, expect=400)
        self.assertFalse(ContractFollowUp.objects.exists())

    def test_login_required(self):
        from rest_framework.test import APIClient
        self.assertIn(APIClient().get(URL).status_code, (401, 403))


class HomeAndReportTests(_Shop):
    def test_home_shows_how_many_to_contact(self):
        self.sell("0941000001", 10)
        self.sell("0941000002", -3)
        self.sell("0941000003", 300)
        declined = self.sell("0941000004", 10)
        self.follow(declined, "declined")
        self.sell("0941000005", 10, warehouse=self.c.warehouses[1])
        self.assertEqual(self.c.admin.get("/api/v1/home-summary/").json()["contracts_pending"], 3)
        self.assertEqual(self.c.clerk.get("/api/v1/home-summary/").json()["contracts_pending"], 2)

    def test_report_counts_contracts_by_the_month_they_end(self):
        self.sell("0951000001", 10)
        self.sell("0951000002", 20, plan=self.plan_cht)
        contacted = self.sell("0951000003", 30)
        self.follow(contacted, "contacted")
        old = self.sell("0951000004", 40)
        self.sell("0951000004", 700)                      # 0951000004 已續約
        voided = self.sell("0951000005", 10)
        self.c.admin.post(f"/api/v1/sales-orders/{voided.so_id}/void/", {}, format="json")
        period = {"from": TODAY.isoformat(), "to": (TODAY + timedelta(days=60)).isoformat()}

        def run(*dims):
            result = engine.run(self.c.tenant, {
                "measures": ["contracts_due"], "dimensions": list(dims), "period": period})
            return {" | ".join(d["label"] for d in row["dims"]): row["values"]["contracts_due"]
                    for row in result["rows"]}, result["totals"]["contracts_due"]

        rows, total = run("carrier")
        self.assertEqual((rows, total), ({"遠傳": 3, "中華電信": 1}, 4))       # 作廢的不算
        rows, _ = run("contract_state")
        self.assertEqual(rows, {"還沒處理": 2, "已聯絡": 1, "已續約": 1})
        rows, _ = run("plan_kind")
        self.assertEqual(rows, {"續約": 4})
        rows, _ = run("warehouse")
        self.assertEqual(sum(rows.values()), 4)
        # 現成的「未來 3 個月」「未來 12 個月」;分月看
        later = self.sell("0951000006", 200)
        for preset, expected in (("next_3_months", 4), ("next_12_months", 5)):
            result = engine.run(self.c.tenant, {
                "measures": ["contracts_due"], "dimensions": [], "period": {"preset": preset}})
            self.assertEqual(result["totals"]["contracts_due"], expected, preset)
        monthly = engine.run(self.c.tenant, {
            "measures": ["contracts_due"], "dimensions": ["date"],
            "period": {"preset": "next_12_months", "grain": "month"}})
        self.assertEqual(sum(r["values"]["contracts_due"] for r in monthly["rows"]), 5)
        self.assertEqual(later.contract_end, TODAY + timedelta(days=200))
        self.assertEqual(old.contract_end, TODAY + timedelta(days=40))
