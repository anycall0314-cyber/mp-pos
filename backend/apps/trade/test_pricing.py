"""中古機的價目表、獨立定價、改價紀錄。跑法:manage.py test apps.trade.test_pricing

要守住的(owner 2026-10-14:「型號成色電池都可能會決定價格」「批次全選,再取消部分勾選獨立定價」「改價紀錄也要」):
1. 一格價目 = 型號 + 成色 + 電池區間 + 有沒有備註。**全公司符合那一格、沒有獨立定價的在庫機器都用那個價**(不只送來的那幾台、不只一間門市);
   那一格改了它們跟著變;新進貨的自動用那個價。
2. 兩格都符合 → 比較細的那一格算數;一樣細的電池區間不能重疊。
3. 獨立定價要人明講(自己那一列打價、或取消勾選);獨立的那一台價目怎麼改都不動;可以改回來跟價目。
4. 每一次價錢變了都記一筆:誰、哪一格或哪幾台、每一台從多少變多少。下架也記。
5. 價目是全公司的:鎖門市的店員不能改;別家公司碰不到。
"""
import threading
import time
from decimal import Decimal as D

from django.db import connection, connections
from django.test import TestCase, TransactionTestCase
from django.test.utils import CaptureQueriesContext

from apps.backup.tests.test_backup_restore import _Base as BackupBase
from apps.catalog.models import Product
from apps.inventory.models import ProductSerial

from . import pricing
from .models import TradePriceChange, TradePriceChangeUnit, TradePriceRule, TradeUnit
from .tests import T, _Helpers


class _Table(_Helpers):
    def units(self, *rows, warehouse=None):
        """進幾台:每一台 (序號, 成色, 電池, 備註)。門市價 16000 → 通則算出來 15000。"""
        made = []
        for sn, grade, battery, note in rows:
            made += self.stock_units(sn, warehouse=warehouse, grade=grade, battery=battery, note=note)
        return made

    def put(self, rows=None, expect=200, client=None, **body):
        r = (client or self.a.admin).post(T + "units/list/", {"rows": rows or [], "product": self.used.id, **body}, format="json")
        self.assertEqual(r.status_code, expect, r.content.decode())
        return r.json()

    def cell(self, price, expect=200, rows=None, client=None, **cell):
        return self.put(rows, expect=expect, client=client, cell=cell, cell_price=price)

    def price(self, serial):
        return int(TradeUnit.objects.get(serial=serial).price)

    def log(self):
        return [(c.what, c.scope, c.count, c.old_low and int(c.old_low), c.old_high and int(c.old_high), c.new_low and int(c.new_low),
                 c.new_high and int(c.new_high)) for c in TradePriceChange.objects.order_by("id")]


class PriceTableTests(_Table, TestCase):
    def setUp(self):
        super().setUp()
        self.open_shop()

    def test_a_cell_prices_everything_that_fits_in_the_whole_company(self):
        a1, a2, b1 = self.units(("A1", "A", 90, ""), ("A2", "A", 80, "小刮"), ("B1", "B", 90, ""))
        far, = self.units(("A3", "A", 95, ""), warehouse=self.wh2)
        TradeUnit.objects.filter(serial=a2).update(is_listed=False)                      # 下架中的也算(再上架的時候價要是對的)
        self.cell(12000, grade="A")                                                      # 一台都沒送:只改這一格
        self.assertEqual([self.price(s) for s in (a1, a2, far, b1)], [12000, 12000, 12000, 15000])
        rule = TradePriceRule.objects.get()
        self.assertEqual((rule.product_id, rule.grade, rule.battery_min, rule.battery_max, rule.noted, int(rule.price), rule.updated_by_id),
                         (self.used.id, "A", 0, 100, "", 12000, self.a.admin_user.id))
        # 紀錄上的台數 = 全公司用這一格的(下架中的那一台也算)
        self.assertEqual(self.log(), [("rule", "A 級", 3, 15000, 15000, 12000, 12000)])
        self.assertEqual(set(TradePriceChangeUnit.objects.values_list("serial__serial_no", "old_price", "new_price")),
                         {("A1", D("15000"), D("12000")), ("A2", D("15000"), D("12000")), ("A3", D("15000"), D("12000"))})
        # 買家看到的就是新的價
        self.assertEqual(sorted(s["unit_price"] for s in self.products(self.b)[self.used.sku]["specs"]), [12000, 12000, 15000])
        # 同一格再存一次同樣的價:什麼都沒變、不多記一筆
        self.cell(12000, grade="A")
        self.assertEqual((TradePriceRule.objects.count(), TradePriceChange.objects.count()), (1, 1))

    def test_the_finer_cell_wins(self):
        high, low, unknown, noted = self.units(("A1", "A", 90, ""), ("A2", "A", 80, ""), ("A3", "A", None, ""), ("A4", "A", 90, "無盒"))
        self.cell(10000)                                                                 # 不分成色的那一格
        self.cell(12000, grade="A")
        self.cell(11000, grade="A", battery_max=84)
        self.cell(12500, grade="A", noted="no")
        # 有限電池的贏過指定備註的;沒記電池的不算在有限電池的格子裡
        self.assertEqual([self.price(s) for s in (high, low, unknown, noted)], [12500, 11000, 12500, 12000])
        self.cell(9000, grade="A", noted="yes")
        self.assertEqual(self.price(noted), 9000)
        other, = self.units(("C1", "C", 70, ""))                                         # 新進貨:只有不分成色的那一格符合
        self.assertEqual(self.price(other), 10000)
        self.assertEqual([pricing.text_of(r) for r in sorted(TradePriceRule.objects.all(), key=lambda r: r.id)],
                         ["全部", "A 級", "A 級 電池 84 以下", "A 級 沒備註", "A 級 有備註"])

    def test_two_cells_just_as_fine_cannot_overlap_and_bad_cells_are_refused(self):
        one, = self.units(("A1", "A", 90, ""))
        self.cell(11000, grade="A", battery_max=84)
        got = self.cell(11500, grade="A", battery_min=80, battery_max=90, expect=400)
        self.assertEqual(got["detail"], "跟「A 級 電池 84 以下」的電池區間重疊")
        self.cell(11500, grade="A", battery_min=85, battery_max=90)                      # 接在後面的可以
        self.cell(10000, grade="B", battery_min=80, battery_max=90)                      # 別的成色、別的備註各算各的
        self.cell(10500, grade="A", battery_min=80, battery_max=90, noted="yes")
        for bad in ({"grade": "Z"}, {"battery_min": 90, "battery_max": 80}, {"battery_max": 101}, {"battery_min": -1}, {"battery_min": "80"},
                    {"noted": "maybe"}, {"grade": ["A"]}):
            self.cell(9000, expect=400, **bad)
        for bad in (0, -5, 1.5, "abc", None, True):
            self.cell(bad, grade="S", expect=400)
        self.put(expect=400, cell="A", cell_price=9000)
        self.assertEqual((TradePriceRule.objects.count(), self.price(one)), (4, 11500))
        # 沒講是哪個型號、不是中古機的型號:不能有價目
        r = self.a.admin.post(T + "units/list/", {"rows": [], "cell": {"grade": "A"}, "cell_price": 9000}, format="json")
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "要先選型號"))
        r = self.a.admin.post(T + "units/list/", {"rows": [], "product": self.a.case.id, "cell": {"grade": "A"}, "cell_price": 9000}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_an_independent_unit_does_not_move_until_it_is_told_to_follow_again(self):
        plain, special, other = self.units(("A1", "A", 90, ""), ("A2", "A", 90, "螢幕有刮痕"), ("A3", "A", 88, ""))
        self.cell(12000, grade="A", rows=[{"serial": special.id, "price": 9500}])        # 存這一格的同時,特殊的那一台自己的價
        self.assertEqual([self.price(s) for s in (plain, special, other)], [12000, 9500, 12000])
        self.assertEqual(list(TradeUnit.objects.filter(own_price=True).values_list("serial__serial_no", flat=True)), ["A2"])
        self.cell(11500, grade="A")
        self.assertEqual([self.price(s) for s in (plain, special, other)], [11500, 9500, 11500])
        # 取消勾選(獨立、價維持現在的)
        self.put([{"serial": other.id, "own": True}])
        self.cell(11000, grade="A")
        self.assertEqual([self.price(s) for s in (plain, special, other)], [11000, 9500, 11500])
        # 勾回來:兩台都回到這一格的價
        self.put([{"serial": special.id}, {"serial": other.id}])
        self.assertEqual([self.price(s) for s in (plain, special, other)], [11000, 11000, 11000])
        self.assertFalse(TradeUnit.objects.filter(own_price=True).exists())
        self.assertEqual(self.log(), [
            ("rule", "A 級", 3, 15000, 15000, 9500, 12000), ("rule", "A 級", 2, 12000, 12000, 11500, 11500),
            ("rule", "A 級", 1, 11500, 11500, 11000, 11000), ("price", "", 2, 9500, 11500, 11000, 11000)])

    def test_a_unit_no_cell_fits_keeps_its_price_and_never_listed_ones_need_one(self):
        one, = self.units(("B1", "B", 90, ""))
        self.put([{"serial": one.id, "price": 14000}])
        self.put([{"serial": one.id}])                                                   # 不獨立了,但沒有符合的格子:價不動
        unit = TradeUnit.objects.get(serial=one)
        self.assertEqual((int(unit.price), unit.own_price), (14000, False))
        self.cell(13000, grade="B")                                                      # 之後有了符合的格子:跟上
        self.assertEqual(self.price(one), 13000)
        TradeUnit.objects.all().delete()
        got = self.put([{"serial": one.id, "own": True}], expect=400)
        self.assertEqual(got["detail"], "B1 要獨立定價,請填價")
        self.put([{"serial": one.id, "own": "yes"}], expect=400)
        self.assertEqual(TradeUnit.objects.count(), 0)

    def test_new_stock_takes_the_table_price_and_the_form_can_still_set_its_own(self):
        self.cell(12000, grade="A")
        new, = self.units(("A1", "A", 90, ""))
        mine, = self.stock_units("A2", wholesale_price=13333)
        self.assertEqual([(int(u.price), u.own_price) for u in TradeUnit.objects.order_by("serial__serial_no")], [(12000, False), (13333, True)])
        self.cell(11000, grade="A")
        self.assertEqual([self.price(new), self.price(mine)], [11000, 13333])
        # 收進來的不記成一次改價(那是進貨,不是改價)
        self.assertEqual([c[0] for c in self.log()], ["rule"])

    def test_the_whole_batch_or_nothing_and_no_query_per_unit(self):
        made = self.units(*[(f"Q{i:03d}", "A", 90, "") for i in range(60)])
        with CaptureQueriesContext(connection) as seen:
            self.cell(12000, grade="A")
        self.assertLess(len(seen), 40, len(seen))
        self.assertEqual(set(TradeUnit.objects.values_list("price", flat=True)), {D("12000")})
        ProductSerial.objects.filter(pk=made[-1].id).update(status="sold", warehouse=None)
        got = self.cell(11000, grade="A", rows=[{"serial": made[0].id, "price": 9000}, {"serial": made[-1].id, "price": 9000}], expect=400)
        self.assertIn("Q059", got["detail"])
        # 這一格的價、每一台的價、紀錄都沒有動
        self.assertEqual((int(TradePriceRule.objects.get().price), set(TradeUnit.objects.values_list("price", flat=True)), TradePriceChange.objects.count()),
                         (12000, {D("12000")}, 1))

    def test_many_cells_at_once(self):
        a1, b1 = self.units(("A1", "A", 90, ""), ("B1", "B", 90, ""))
        self.cell(12000, grade="A")
        self.cell(10000, grade="B")
        ra, rb = TradePriceRule.objects.order_by("id")
        r = self.a.admin.post(T + "units/rules/", {"cells": [{"id": ra.id, "price": 11800}, {"id": rb.id, "price": 10000}]}, format="json")
        self.assertEqual((r.status_code, r.json()), (200, {"changed": 1}))                # B 那一格沒變
        r = self.a.admin.post(T + "units/rules/", {"cells": [{"id": ra.id, "price": 11500}, {"id": rb.id, "price": 9800}]}, format="json")
        self.assertEqual(r.json(), {"changed": 2})
        self.assertEqual([self.price(a1), self.price(b1)], [11500, 9800])
        self.assertEqual(self.log()[-2:], [("rule", "A 級", 1, 11800, 11800, 11500, 11500), ("rule", "B 級", 1, 10000, 10000, 9800, 9800)])
        for bad in ([], [{"id": ra.id}], [{"id": ra.id, "price": 0}], [{"id": ra.id, "price": 9000}, {"id": ra.id, "price": 9100}],
                    [{"id": ra.id, "price": 9000}, {"id": 999999, "price": 9000}], "x", [{"id": "1", "price": 9000}]):
            r = self.a.admin.post(T + "units/rules/", {"cells": bad}, format="json")
            self.assertEqual(r.status_code, 400, bad)
        self.assertEqual([self.price(a1), self.price(b1)], [11500, 9800])                 # 有一格不對整批不動

    def test_dropping_a_cell_falls_back_to_the_next_one(self):
        low, high = self.units(("A1", "A", 80, ""), ("A2", "A", 90, ""))
        self.cell(12000, grade="A")
        self.cell(11000, grade="A", battery_max=84)
        fine = TradePriceRule.objects.get(battery_max=84)
        r = self.a.admin.post(f"{T}units/rules/{fine.id}/drop/", {}, format="json")
        self.assertEqual((r.status_code, r.json()), (200, {"changed": 1}))
        self.assertEqual([self.price(low), self.price(high)], [12000, 12000])
        self.assertEqual(self.log()[-1], ("drop", "A 級 電池 84 以下", 1, 11000, 11000, 12000, 12000))
        r = self.a.admin.post(f"{T}units/rules/{TradePriceRule.objects.get().id}/drop/", {}, format="json")
        self.assertEqual(r.json(), {"changed": 0})                                        # 沒有下一格:價維持
        self.assertEqual(([self.price(low), self.price(high)], TradePriceRule.objects.count()), ([12000, 12000], 0))
        self.assertEqual(self.a.admin.post(f"{T}units/rules/{fine.id}/drop/", {}, format="json").status_code, 404)

    def test_the_screens_are_told_who_follows_which_cell(self):
        a1, a2, b1 = self.units(("A1", "A", 90, ""), ("A2", "A", 90, "無盒"), ("B1", "B", 90, ""))
        self.cell(12000, grade="A", rows=[{"serial": a2.id, "price": 9500}])
        rule = TradePriceRule.objects.get()
        got = self.a.admin.get(f"{T}units/?state=all&product={self.used.id}").json()
        rows = {u["serial_no"]: u for u in got["results"]}
        self.assertEqual([(rows[k]["own"], rows[k]["rule"], rows[k]["price"], rows[k]["auto_price"]) for k in ("A1", "A2", "B1")],
                         [(False, rule.id, 12000, 12000), (True, rule.id, 9500, 12000), (False, None, 15000, 15000)])
        self.assertEqual(got["rules"], [{"id": rule.id, "product": self.used.id, "grade": "A", "battery_min": 0, "battery_max": 100, "noted": "",
                                         "price": 12000, "text": "A 級", "followers": 1}])
        # 全部型號那個入口也帶(每一台才算得出勾回來是什麼價);台數不算
        self.assertEqual(self.a.admin.get(f"{T}units/?state=all").json()["rules"], [{**got["rules"][0], "followers": None}])
        model, = self.a.admin.get(T + "units/models/").json()["results"]
        self.assertEqual((model["price_low"], model["price_high"], model["own"], model["rules"]), (9500, 15000, 1, got["rules"]))

    def test_every_change_can_be_looked_up(self):
        a1, a2 = self.units(("A1", "A", 90, ""), ("A2", "A", 90, ""))
        self.cell(12000, grade="A")
        self.put([{"serial": a2.id, "price": 9500}])
        r = self.a.admin.post(T + "units/unlist/", {"serials": [a2.id], "product": self.used.id}, format="json")
        self.assertEqual(r.json(), {"unlisted": 1})
        self.put([{"serial": a2.id, "own": True}])                                        # 再上架(獨立、原本的價)
        got = self.a.admin.get(f"{T}units/changes/?product={self.used.id}").json()
        self.assertEqual(got["total"], 4)
        self.assertEqual([(c["what_label"], c["scope"], c["count"], c["old_low"], c["old_high"], c["new_low"], c["new_high"], c["by"]) for c in got["results"]], [
            ("上架", "", 1, None, None, 9500, 9500, "a-boss"), ("下架", "", 1, 9500, 9500, None, None, "a-boss"),
            ("改價", "", 1, 12000, 12000, 9500, 9500, "a-boss"), ("改價目", "A 級", 2, 15000, 15000, 12000, 12000, "a-boss")])
        self.assertTrue(all(c["at"] and c["name"] == self.used.name for c in got["results"]))
        only = self.a.admin.get(f"{T}units/changes/?product={self.used.id}&q=A1").json()
        self.assertEqual((only["total"], only["results"][0]["units"]), (1, [{"serial_no": "A1", "old_price": 15000, "new_price": 12000}]))
        self.assertEqual(self.a.admin.get(f"{T}units/changes/?q=A2").json()["total"], 4)
        self.assertEqual(self.b.admin.get(f"{T}units/changes/").json()["total"], 0)       # 別家公司看不到

    def test_the_price_table_is_not_for_a_clerk_tied_to_one_store_or_for_another_company(self):
        one, = self.units(("A1", "A", 90, ""))
        self.cell(12000, grade="A")
        rule = TradePriceRule.objects.get()
        got = self.cell(9000, grade="A", client=self.a.clerk, expect=400)
        self.assertEqual(got["detail"], "沒有改價目的權限")
        self.assertEqual(self.a.clerk.post(T + "units/rules/", {"cells": [{"id": rule.id, "price": 9000}]}, format="json").status_code, 400)
        self.assertEqual(self.a.clerk.post(f"{T}units/rules/{rule.id}/drop/", {}, format="json").status_code, 400)
        self.assertEqual(self.b.admin.post(T + "units/rules/", {"cells": [{"id": rule.id, "price": 9000}]}, format="json").status_code, 400)
        self.assertEqual(self.b.admin.post(f"{T}units/rules/{rule.id}/drop/", {}, format="json").status_code, 404)
        self.assertEqual((self.price(one), int(TradePriceRule.objects.get().price)), (12000, 12000))
        # 店員還是可以替自己門市的那一台定自己的價
        self.put([{"serial": one.id, "price": 9900}], client=self.a.clerk)
        self.assertEqual(self.price(one), 9900)
        from apps.tenants.models import UserProfile
        UserProfile.objects.filter(user=self.a.clerk_user).update(denied_abilities=["trade_sell"])
        self.a.clerk_user.profile.refresh_from_db()
        for method, url in (("get", f"{T}units/changes/"), ("post", f"{T}units/rules/"), ("post", f"{T}units/rules/{rule.id}/drop/")):
            self.assertEqual(getattr(self.a.clerk, method)(url, {} if method == "post" else None, format="json").status_code, 403, url)


class PriceTableLockTests(_Table, TransactionTestCase):
    """改價目先鎖型號(鎖的順序:商品 → 序號);會讀價目來定價的另外兩條路(替一台定價、進貨 / 收購就上架)也先鎖型號 —— 一次一個。"""

    def setUp(self):
        super().setUp()
        self.open_shop()
        self.one, = self.units(("A1", "A", 90, ""))
        self.cell(12000, grade="A")
        self.rule = TradePriceRule.objects.get()

    def meanwhile(self, statements, hold=1.0):
        """另一條連線照順序做這幾句、握著 `hold` 秒才提交。回來時它已經握著鎖了。"""
        holding = threading.Event()

        def work():
            other = connections.create_connection("default")
            try:
                other.ensure_connection()
                other.set_autocommit(False)
                with other.cursor() as cur:
                    for sql, args in statements:
                        cur.execute(sql, args)
                holding.set()
                time.sleep(hold)
                other.commit()
            finally:
                other.close()

        t = threading.Thread(target=work)
        t.start()
        self.addCleanup(t.join)
        self.assertTrue(holding.wait(5))
        return time.monotonic()

    LOCK_PRODUCT = "SELECT 1 FROM catalog_product WHERE id = %s FOR NO KEY UPDATE"

    def test_changing_a_cell_waits_for_whoever_holds_the_product(self):
        began = self.meanwhile([(self.LOCK_PRODUCT, [self.used.id])])
        self.cell(11000, grade="A")
        self.assertGreater(time.monotonic() - began, 0.5)
        self.assertEqual(self.price(self.one), 11000)

    def test_an_own_price_waits_for_the_cell_being_changed_and_is_not_overwritten(self):
        """複審 P0:另一邊正在改價目、整批重算(握著型號);這邊替其中一台定獨立價 —— 要等它做完,獨立價不會被它蓋掉。"""
        # 另一邊只握著型號(還沒寫到那一台):這邊也要等 —— 不然它接著把整批寫回去的時候會蓋掉這邊的獨立價
        began = self.meanwhile([(self.LOCK_PRODUCT, [self.used.id]),
                                ("UPDATE trade_tradepricerule SET price = 11000 WHERE id = %s", [self.rule.id])])
        self.put([{"serial": self.one.id, "price": 9500}])
        self.assertGreater(time.monotonic() - began, 0.5)
        unit = TradeUnit.objects.get(serial=self.one)
        self.assertEqual((int(unit.price), unit.own_price), (9500, True))
        # 之後價目再改,獨立的那一台照樣不動
        self.cell(10500, grade="A")
        self.assertEqual(self.price(self.one), 9500)

    def test_taking_a_number_does_not_hold_up_a_cell_being_changed(self):
        """複審第二輪 P1:跟會員收購第一次替他建客戶的時候會拿公司的流水號(鎖公司那一列),接著要等型號;
        改價目的人握著型號、要寫改價紀錄(指到公司那一列)—— 公司那一列用擋外鍵的鎖的話,兩邊會互等到其中一個失敗。
        拿流水號只改流水號:不可以擋到別人新增指到這家公司的資料。"""
        from django.db import connection as main, transaction

        holding, release = threading.Event(), threading.Event()

        def take_a_number():
            try:
                with transaction.atomic():
                    self.seller.issue_next_customer_code()
                    holding.set()
                    release.wait(3)
            finally:
                connections["default"].close()

        t = threading.Thread(target=take_a_number)
        t.start()
        self.addCleanup(t.join)
        self.addCleanup(release.set)
        self.assertTrue(holding.wait(5))
        began = time.monotonic()
        self.cell(11000, grade="A")                                          # 寫改價紀錄:指到公司那一列
        took = time.monotonic() - began
        release.set()
        self.assertLess(took, 1.5, took)
        self.assertEqual((self.price(self.one), TradePriceChange.objects.count()), (11000, 2))
        self.assertTrue(main.is_usable())

    def test_buying_from_a_walk_in_customer_waits_for_the_cell_being_changed_and_takes_the_new_price(self):
        """複審 P0:另一邊正在把價目改成 11,000(握著型號);這邊跟客人收購一台 A 級 —— 等它做完、用新的價上架,不是舊的 12,000。"""
        from apps.parties.models import Member

        member = Member.objects.create(tenant=self.seller, name="王小明", phone="0911222333")
        began = self.meanwhile([(self.LOCK_PRODUCT, [self.used.id]),
                                ("UPDATE trade_tradepricerule SET price = 11000 WHERE id = %s", [self.rule.id])])
        r = self.a.admin.post("/api/v1/sales-orders/secondhand-acquisition/", {
            "member": member.id, "warehouse": self.wh1.id, "product": self.used.id, "sn": "W001", "condition_grade": "A", "battery_health": 92,
            "custom_unit_price": "16000", "acquisition_price": "9000", "payment_method_code": "cash"}, format="json")
        self.assertEqual(r.status_code, 201, r.content.decode())
        self.assertGreater(time.monotonic() - began, 0.5)
        unit = TradeUnit.objects.get(serial__serial_no="W001")
        self.assertEqual((int(unit.price), unit.own_price), (11000, False))


class PriceTableBackupTests(BackupBase):
    def test_the_price_table_and_its_history_come_back_with_the_company(self):
        a = self.a
        self.assertEqual(a.admin.post(T + "settings/", {"is_open": True, "unit_rule": "price_minus", "unit_value": 1000}, format="json").status_code, 200)
        used = Product.objects.create(tenant=a.tenant, category=a.cat_phone, name="甲 中古 iPhone 13", is_secondhand=True, list_price=15000)
        rows = [{"sn": sn, "grade": "A", "cost": "12000", "price": "16000", "battery": 90} for sn in ("PT-1", "PT-2")]
        a._post("/api/v1/purchase-orders/", {"supplier": a.supplier.id, "warehouse": a.wh.id, "tax_method": "untaxed",
                                              "items": [{"product": used.id, "qty": 2, "unit_price": "12000", "serial_numbers": rows}]})
        special = ProductSerial.objects.get(serial_no="PT-2")
        r = a.admin.post(T + "units/list/", {"rows": [{"serial": special.id, "price": 9500}], "product": used.id, "cell": {"grade": "A"}, "cell_price": 12000},
                         format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        job = self.backup(a)
        r = a.admin.post(T + "units/list/", {"rows": [{"serial": special.id}], "product": used.id, "cell": {"grade": "A"}, "cell_price": 11000}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        done = self.rollback(a, self.path(job))
        self.assertEqual(done.status, "done", done.error)
        a.reload()
        rule = TradePriceRule.objects.get(tenant=a.tenant)
        self.assertEqual((rule.product.name, rule.grade, int(rule.price)), ("甲 中古 iPhone 13", "A", 12000))
        self.assertEqual([(u.serial.serial_no, int(u.price), u.own_price) for u in TradeUnit.objects.filter(tenant=a.tenant).order_by("serial__serial_no")],
                         [("PT-1", 12000, False), ("PT-2", 9500, True)])
        change = TradePriceChange.objects.get(tenant=a.tenant)
        self.assertEqual((change.what, change.scope, change.count, change.product.name, set(change.units.values_list("serial__serial_no", flat=True))),
                         ("rule", "A 級", 2, "甲 中古 iPhone 13", {"PT-1", "PT-2"}))
        # 還原之後價目照樣管得到那幾台
        a.admin = a.client(a.admin_user)
        r = a.admin.post(T + "units/rules/", {"cells": [{"id": rule.id, "price": 11800}]}, format="json")
        self.assertEqual((r.status_code, r.json()), (200, {"changed": 1}))
