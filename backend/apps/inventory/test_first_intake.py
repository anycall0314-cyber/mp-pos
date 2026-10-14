"""第一次盤點入庫(手機、中古機;2026-10-14):系統不認得的碼對舊系統的機器清單,管理員核准時指定品號與成本才入庫。
規則在 `inventory/stockcount.py`(`_first_intake`、`approve` 的 extras、`_add_units`)與 `legacy/units.py`。全部是假資料。"""
from decimal import Decimal

from django.test import TestCase

from apps.backup.tests.factory import Company
from apps.catalog.models import Category, Product
from apps.inventory import stockcount
from apps.inventory.models import ProductSerial, StockCountScan, StockMovement
from apps.inventory.test_locking import _Concurrent
from apps.ledger.checks import check_serials, check_stock_balance
from apps.legacy import units
from apps.legacy.archive import SOURCE_SYSTEM
from apps.legacy.models import LegacyProductMap, LegacyUnit, MapStatus

URL = "/api/v1/stock-counts/"
NEW_IMEI, NEW_IMEI2 = "356000000000011", "356000000000029"
USED_IMEI = "351135566270160"


def old_row(imei, code, name, store="湳雅店", day="20260926", supplier="W"):
    return {"IMEI": f"'{imei}", "S/N": "'", "品號": code, "品名": name, "店別": store,
            "進貨日期": day, "進貨廠商": supplier, "目前狀態": "庫存中"}


OLD = [
    old_row(NEW_IMEI, "0004A176001W3", "手機/三星-A17 6/128逆襲黑"),
    old_row(NEW_IMEI2, "0004A176001W3", "手機/三星-A17 6/128逆襲黑"),
    old_row(USED_IMEI, f"{USED_IMEI}I", "中古/IP13P/256G/78%/白/W"),
]
COSTS = {"0004A176001W3": Decimal("7050"), f"{USED_IMEI}I": Decimal("15500")}
PRICES = {"0004A176001W3": 8990, f"{USED_IMEI}I": 18900}


class _Intake(TestCase):
    def setUp(self):
        c = self.c = Company("a", "甲通訊行", "甲")
        self.w1, self.w2 = c.warehouses
        c.purchase(case_qty=10)
        self.used_cat = Category.objects.create(tenant=c.tenant, code="SC", name="中古", is_secondhand_default=True)
        self.used = Product.objects.create(tenant=c.tenant, category=self.used_cat, name="中古 iPhone 13 Pro 256GB")
        self.a17 = Product.objects.create(tenant=c.tenant, category=c.cat_phone, name="Galaxy A17 6/128 黑")
        units.load_units(c.tenant, OLD, COSTS, PRICES, write=True)

    def ok(self, r, code=200):
        self.assertEqual(r.status_code, code, r.content.decode())
        return r.json()

    def open(self):
        return self.ok(self.c.clerk.post(URL, {"warehouse": self.w1.id}, format="json"), 201)

    def scan(self, count, code):
        return self.c.clerk.post(f"{URL}{count['id']}/scans/", {"code": code}, format="json")

    def act(self, count, action, client=None, **body):
        return (client or self.c.admin).post(f"{URL}{count['id']}/{action}/", body, format="json")

    def detail(self, count, client=None):
        return self.ok((client or self.c.admin).get(f"{URL}{count['id']}/"))

    def submitted(self, *codes):
        count = self.open()
        for code in codes:
            self.ok(self.scan(count, code))
        self.ok(self.act(count, "submit", self.c.clerk, phones_done=True))
        return count, {r["code"]: r for r in self.detail(count)["new_rows"]}

    def books_agree(self):
        bad = [r for r in check_stock_balance(self.c.tenant) + check_serials(self.c.tenant) if not r["ok"]]
        self.assertEqual(bad, [])


class ScanTests(_Intake):
    def test_a_code_on_the_old_list_brings_its_old_name_cost_and_price(self):
        count = self.open()
        self.ok(self.scan(count, NEW_IMEI))
        mine = self.detail(count, self.c.clerk)
        self.assertEqual([(s["code"], s["known"], s["name"]) for s in mine["scan_rows"]],
                         [(NEW_IMEI, False, "手機/三星-A17 6/128逆襲黑")])
        self.assertNotIn("new_rows", mine)                                  # 成本只給管理員
        [row] = self.detail(count)["new_rows"]
        self.assertEqual((row["old_code"], row["group"], row["old_cost"], row["old_price"], row["product"]),
                         ("0004A176001W3", "手機/三星-A17 6/128逆襲黑", "7050.00", "8990.00", None))

    def test_the_old_sticker_of_a_used_phone_is_that_phone(self):
        count = self.open()
        self.ok(self.scan(count, f"{USED_IMEI}I"))                         # 中古機的舊貼紙:IMEI + I
        scan = StockCountScan.objects.get(count_id=count["id"])
        self.assertEqual((scan.code, scan.old_name), (USED_IMEI, "中古/IP13P/256G/78%/白/W"))
        r = self.scan(count, USED_IMEI)                                    # 再刷機身的 IMEI = 同一台
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "這個碼刷過了"))

    def test_the_old_sticker_of_a_model_asks_for_the_imei(self):
        count = self.open()
        r = self.scan(count, "0004A176001W3")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["detail"], "這是「手機/三星-A17 6/128逆襲黑」型號的貼紙,請刷這一台的 IMEI")
        self.assertFalse(StockCountScan.objects.exists())

    def test_an_accessory_barcode_in_the_phone_box_says_where_it_goes(self):
        self.c.case.barcode = "T12SAMNOTE502"
        self.c.case.save(update_fields=["barcode"])
        count = self.open()
        r = self.scan(count, "T12SAMNOTE502")
        self.assertEqual((r.status_code, r.json()["detail"]), (400, f"「{self.c.case.name}」是配件,請在配件那一格打數量"))

    def test_a_code_nobody_knows_is_still_recorded(self):
        count = self.open()
        self.ok(self.scan(count, "F2LXK1ABCDEF"))
        scan = StockCountScan.objects.get(count_id=count["id"])
        self.assertEqual((scan.serial_id, scan.old_code, scan.old_cost), (None, "", None))

    def test_a_phone_registered_twice_in_the_old_system_takes_the_newest(self):
        units.load_units(self.c.tenant, OLD + [
            old_row(f"{NEW_IMEI}A", "0004A176011W3", "手機/三星-A17 8/128逆襲黑", day="20250101"),
            old_row(f"{NEW_IMEI}I", "0004A176014W3", "手機/三星-A17 8/128追浪藍", day="20261001"),
        ], COSTS, PRICES, write=True)
        count = self.open()
        self.ok(self.scan(count, NEW_IMEI))
        self.assertEqual(StockCountScan.objects.get(count_id=count["id"]).old_code, "0004A176014W3")

    def test_the_old_list_of_another_company_is_never_used(self):
        other = Company("b", "乙通訊行", "乙")
        count = self.ok(other.clerk.post(URL, {"warehouse": other.wh.id}, format="json"), 201)
        self.ok(other.clerk.post(f"{URL}{count['id']}/scans/", {"code": NEW_IMEI}, format="json"))
        self.assertEqual(StockCountScan.objects.get(count_id=count["id"]).old_name, "")


class ApproveTests(_Intake):
    def test_approved_units_are_in_stock_at_the_cost_given(self):
        count, rows = self.submitted(NEW_IMEI, NEW_IMEI2, USED_IMEI)
        self.ok(self.act(count, "approve", extras={
            rows[NEW_IMEI]["id"]: {"product": self.a17.id, "unit_cost": "7050"},
            rows[NEW_IMEI2]["id"]: {"product": self.a17.id, "unit_cost": "7150"},
            rows[USED_IMEI]["id"]: {"product": self.used.id, "unit_cost": "15500", "unit_price": "18900"},
        }))
        new = ProductSerial.objects.get(tenant=self.c.tenant, serial_no=NEW_IMEI)
        self.assertEqual((new.product, new.warehouse, new.status, new.purchase_unit_cost),
                         (self.a17, self.w1, "in_stock", Decimal("7050")))
        self.a17.refresh_from_db()
        self.assertEqual(self.a17.weighted_avg_cost, Decimal("7100"))       # 兩台平均
        used = ProductSerial.objects.get(tenant=self.c.tenant, serial_no=USED_IMEI)
        self.assertEqual((used.purchase_unit_cost, used.custom_unit_price, used.battery_health, used.condition_note),
                         (Decimal("15500"), Decimal("18900"), 78, "舊系統:中古/IP13P/256G/78%/白/W"))
        moves = StockMovement.objects.filter(tenant=self.c.tenant, ref_doc_type="stock_count", ref_doc_id=count["id"])
        self.assertEqual(sorted((m.serial.serial_no, m.movement_type, m.to_warehouse_id) for m in moves), sorted(
            (code, StockMovement.MovementType.ADJUST, self.w1.id) for code in (NEW_IMEI, NEW_IMEI2, USED_IMEI)))
        self.assertTrue(all(r["added"] for r in self.detail(count)["new_rows"]))
        self.books_agree()

    def test_the_average_cost_is_worked_out_the_same_way_as_a_purchase(self):
        """複審 P0:先盤入兩台(10000、20000,平均 15000)→ 賣掉 10000 那一台 → 另一家門市再盤入一台 30000。
        進貨的算法是(在庫 1 台 × 15000 + 30000)÷ 2 = 22500;拿「現在在庫那幾台的成本平均」會算成 25000。"""
        phone = self.c.phone
        count, rows = self.submitted(NEW_IMEI, NEW_IMEI2)
        self.ok(self.act(count, "approve", extras={
            rows[NEW_IMEI]["id"]: {"product": phone.id, "unit_cost": "10000"},
            rows[NEW_IMEI2]["id"]: {"product": phone.id, "unit_cost": "20000"},
        }))
        phone.refresh_from_db()
        self.assertEqual(phone.weighted_avg_cost, Decimal("15000"))
        self.c.sell(serial_no=NEW_IMEI)
        other = self.ok(self.c.admin.post(URL, {"warehouse": self.w2.id}, format="json"), 201)
        self.ok(self.c.admin.post(f"{URL}{other['id']}/scans/", {"code": "356000000000037"}, format="json"))
        self.ok(self.act(other, "submit", phones_done=True))
        [row] = self.detail(other)["new_rows"]
        self.ok(self.act(other, "approve", extras={row["id"]: {"product": phone.id, "unit_cost": "30000"}}))
        phone.refresh_from_db()
        self.assertEqual(phone.weighted_avg_cost, Decimal("22500"))
        self.books_agree()

    def test_the_amounts_count_the_new_phones(self):
        count, rows = self.submitted(NEW_IMEI)
        self.assertEqual(self.detail(count)["amounts"]["phones"], "0.00")          # 還沒指定品號
        self.ok(self.act(count, "approve", extras={rows[NEW_IMEI]["id"]: {"product": self.a17.id, "unit_cost": "7050"}}))
        self.assertEqual(self.detail(count)["amounts"]["phones"], "7050.00")

    def test_what_was_chosen_is_remembered_for_the_next_phone_of_the_same_old_code(self):
        count, rows = self.submitted(NEW_IMEI)
        self.ok(self.act(count, "approve", extras={rows[NEW_IMEI]["id"]: {"product": self.a17.id, "unit_cost": "7050"}}))
        m = LegacyProductMap.objects.get(tenant=self.c.tenant, source_system=SOURCE_SYSTEM, product_code_raw="0004A176001W3")
        self.assertEqual((m.status, m.product_id), (MapStatus.CONFIRMED, self.a17.id))
        count2, rows2 = self.submitted(NEW_IMEI, NEW_IMEI2)                  # 上一次入的那一台也刷到(不然算少一台)
        self.assertEqual(list(rows2), [NEW_IMEI2])
        self.assertEqual(rows2[NEW_IMEI2]["product"]["id"], self.a17.id)    # 先帶出來,管理員確認
        self.assertEqual(self.detail(count2)["amounts"]["phones"], "7050.00")      # 照現在的樣子核准會入的

    def test_nothing_sent_means_not_brought_in(self):
        count, rows = self.submitted(NEW_IMEI, NEW_IMEI2)
        self.ok(self.act(count, "approve", extras={rows[NEW_IMEI2]["id"]: {"skipped": True, "reason": "樣品機"}}))
        self.assertFalse(ProductSerial.objects.filter(tenant=self.c.tenant, serial_no__in=[NEW_IMEI, NEW_IMEI2]).exists())
        got = {r["code"]: (r["skipped"], r["reason"], r["added"]) for r in self.detail(count)["new_rows"]}
        self.assertEqual(got, {NEW_IMEI: (True, "", False), NEW_IMEI2: (True, "樣品機", False)})

    def test_bad_decisions_stop_the_whole_approval(self):
        count, rows = self.submitted(NEW_IMEI, NEW_IMEI2)
        a, b = rows[NEW_IMEI]["id"], rows[NEW_IMEI2]["id"]
        good = {"product": self.a17.id, "unit_cost": "7050"}
        other = Company("b", "乙通訊行", "乙")
        cases = [
            ({"product": self.c.case.id, "unit_cost": "1"}, "不是一台一個碼的商品"),
            ({"product": other.phone.id, "unit_cost": "1"}, "品號不屬於這家公司"),
            ({"product": self.a17.id}, "的成本要填(沒有就填 0)"),
            ({"product": self.a17.id, "unit_cost": "-1"}, "的成本要是 0 以上的數字"),
            ({"product": self.a17.id, "unit_cost": "abc"}, "的成本要是數字"),
            ({"product": "7", "unit_cost": "1"}, "品號不對"),
        ]
        for bad, says in cases:
            r = self.act(count, "approve", extras={a: good, b: bad})
            self.assertEqual(r.status_code, 400, bad)
            self.assertIn(says, r.json()["detail"])
        self.assertFalse(ProductSerial.objects.filter(tenant=self.c.tenant, serial_no=NEW_IMEI).exists())
        self.assertEqual(self.detail(count)["status"], "submitted")
        self.a17.is_active = False
        self.a17.save(update_fields=["is_active"])
        r = self.act(count, "approve", extras={a: good})
        self.assertEqual((r.status_code, r.json()["detail"]), (400, f"{NEW_IMEI}:「Galaxy A17 6/128 黑」已停用"))

    def test_a_code_that_came_into_the_system_after_the_scan_is_refused(self):
        count, rows = self.submitted(NEW_IMEI)
        self.c.purchase(phone_serials=[NEW_IMEI])                            # 盤完之後有人照一般進貨入了同一台
        r = self.act(count, "approve", extras={rows[NEW_IMEI]["id"]: {"product": self.a17.id, "unit_cost": "7050"}})
        self.assertEqual(r.status_code, 400)
        self.assertIn(NEW_IMEI, r.json()["detail"])
        self.assertEqual(ProductSerial.objects.filter(tenant=self.c.tenant, serial_no=NEW_IMEI).count(), 1)

    def test_a_count_limited_to_some_categories_only_brings_those_in(self):
        count = self.ok(self.c.clerk.post(URL, {"warehouse": self.w1.id, "categories": [self.c.cat_phone.id]},
                                          format="json"), 201)
        self.ok(self.scan(count, USED_IMEI))
        self.ok(self.act(count, "submit", self.c.clerk, phones_done=True))
        [row] = self.detail(count)["new_rows"]
        r = self.act(count, "approve", extras={row["id"]: {"product": self.used.id, "unit_cost": "1"}})
        self.assertEqual((r.status_code, r.json()["detail"]), (400, f"{USED_IMEI}:「中古 iPhone 13 Pro 256GB」不在這張盤點單的類別裡"))

    def test_only_a_manager_approves(self):
        count, rows = self.submitted(NEW_IMEI)
        r = self.act(count, "approve", self.c.clerk, extras={rows[NEW_IMEI]["id"]: {"product": self.a17.id, "unit_cost": "1"}})
        self.assertEqual(r.status_code, 403)
        self.assertFalse(ProductSerial.objects.filter(tenant=self.c.tenant, serial_no=NEW_IMEI).exists())


class OldListTests(TestCase):
    def setUp(self):
        self.c = Company("a", "甲通訊行", "甲")

    def test_the_list_is_replaced_and_the_trial_writes_nothing(self):
        r = units.load_units(self.c.tenant, OLD, COSTS, PRICES)
        self.assertEqual((r.units, r.with_cost, r.with_price, LegacyUnit.objects.count()), (3, 3, 3, 0))
        units.load_units(self.c.tenant, OLD, COSTS, PRICES, write=True)
        units.load_units(self.c.tenant, OLD[:1] + [{**OLD[1], "目前狀態": "已售出"}], write=True)
        self.assertEqual(list(LegacyUnit.objects.values_list("code_raw", flat=True)), [NEW_IMEI])

    def test_keys_battery_and_groups(self):
        self.assertEqual([units.unit_key(x) for x in ("'354679848372002I", "I354679848372002", "f2lxk-1abc")],
                         ["354679848372002", "354679848372002", "F2LXK1ABC"])
        self.assertEqual([units.battery_of(x) for x in ("中古/IP16/128G/80%/黑/R", "中古/SE2/64G/白/100%/R", "9H/120%", "皮套/A")],
                         [80, 100, None, None])
        self.assertEqual(units.group_of("中古/IP13P/256G/銀/保內"), "中古/IP13P/256G")


class TwoPeopleTests(_Concurrent):
    def test_the_average_waits_for_a_change_to_the_same_phone_made_at_the_same_moment(self):
        """核准要重算那個品號的平均成本:別人正好在動同一個品號(進貨存到一半),要等他存完、照他存好的算。
        不先鎖那個品號的話,這裡讀到的是他還沒存的那一份(20000 → 算成 10500)。"""
        c = self.c
        count = stockcount.open_count(c.tenant, self.w1, [], c.admin_user)
        stockcount.scan(count, NEW_IMEI, c.admin_user)
        stockcount.submit(count, c.admin_user)
        scan = StockCountScan.objects.get(count=count)
        t = self.meanwhile([                                                       # 甲IMEI1 進貨 20000、在庫 1 台
            ("SELECT 1 FROM catalog_product WHERE id = %s FOR NO KEY UPDATE", [c.phone.pk]),
            ("UPDATE catalog_product SET weighted_avg_cost = 9000 WHERE id = %s", [c.phone.pk]),
        ])
        stockcount.approve(count, c.admin_user, extras={scan.pk: {"product": c.phone.pk, "unit_cost": "1000"}})
        t.join()
        c.phone.refresh_from_db()
        self.assertEqual(c.phone.weighted_avg_cost, Decimal("5000"))           # (1 台 × 9000 + 1000) ÷ 2


class NotInYetTests(_Intake):
    def test_the_manager_sees_what_the_old_list_has_that_is_not_in_yet(self):
        units.load_units(self.c.tenant, OLD + [
            old_row(f"{NEW_IMEI}A", "0004A176001W3", "手機/三星-A17 6/128逆襲黑", day="20240101"),   # 同一台登記兩筆
            old_row("356000000000037", "X1", "手機/X", store="民生店"),
        ], COSTS, PRICES, write=True)
        r = self.ok(self.c.admin.get(f"{URL}old-units/"))
        self.assertEqual(r["total"], 4)
        self.assertEqual(sorted((s["store"], s["count"]) for s in r["stores"]), [("民生店", 1), ("湳雅店", 3)])
        self.assertNotIn("cost", r["rows"][0])
        count, rows = self.submitted(NEW_IMEI, USED_IMEI)
        self.ok(self.act(count, "approve", extras={
            rows[NEW_IMEI]["id"]: {"product": self.a17.id, "unit_cost": "7050"},
            rows[USED_IMEI]["id"]: {"product": self.used.id, "unit_cost": "1"},
        }))
        r = self.ok(self.c.admin.get(f"{URL}old-units/"))
        self.assertEqual(sorted(x["code"] for x in r["rows"]), sorted(["356000000000037", NEW_IMEI2]))

    def test_only_a_manager_sees_it(self):
        self.assertEqual(self.c.clerk.get(f"{URL}old-units/").status_code, 403)
