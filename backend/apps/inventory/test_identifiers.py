"""一台設備兩個碼(IMEI / SN):可以都有、可以只有一個;刷哪一個都找得到同一台;一個碼只屬於一台。"""
import importlib
import pathlib
import re

from django.apps import apps as django_apps
from django.test import TestCase

from apps.backup.tests.factory import Company
from apps.ledger.checks import check_serials

from .identifiers import (
    IdentifierError,
    codes_of,
    create_serial,
    find_serial_ids,
    looks_like_imei,
    split_codes,
)
from .models import ProductSerial, ProductSerialCodeChange, ProductSerialIdentifier

IMEI_A = "490154203237518"
IMEI_B = "356938035643809"
IMEI_C = "352099001761481"
SN_A = "F2LXK1ABCD"
SN_B = "G6TZN0QWER"


class _Shop(TestCase):
    def setUp(self):
        self.c = Company("a", "甲通訊行", "甲")
        self.t = self.c.tenant

    def buy(self, entries, client=None, ok=True):
        r = (client or self.c.admin).post("/api/v1/purchase-orders/", {
            "supplier": self.c.supplier.id, "warehouse": self.c.wh.id, "tax_method": "untaxed",
            "items": [{"product": self.c.phone.id, "qty": len(entries), "unit_price": "20000",
                       "serial_numbers": entries}],
        }, format="json")
        if ok:
            self.assertEqual(r.status_code, 201, r.content.decode())
        return r

    def unit(self, code):
        ids = find_serial_ids(self.t, code)
        self.assertEqual(len(ids), 1, code)
        return ProductSerial.objects.get(pk=ids[0])

    def api_unit(self, pk, client=None):
        return (client or self.c.admin).get(f"/api/v1/serials/{pk}/").json()


class GuessTests(TestCase):
    def test_imei_is_15_digits_with_a_valid_check_digit(self):
        for code in (IMEI_A, IMEI_B, IMEI_C, "49 015420 323751 8", "490154-203237-518"):
            self.assertTrue(looks_like_imei(code), code)
        for code in ("490154203237519", "49015420323751", "4901542032375180", SN_A, "", "４９０１５４２０３２３７５１８"):
            self.assertFalse(looks_like_imei(code), code)

    def test_a_single_code_goes_to_the_box_it_looks_like(self):
        self.assertEqual(split_codes(code=IMEI_A), (IMEI_A, ""))
        self.assertEqual(split_codes(code=SN_A), ("", SN_A))
        self.assertEqual(split_codes(code="490154203237519"), ("", "490154203237519"))  # 檢查碼不對
        # 有明講放哪一格就照放,不改判(檢查碼不對只提醒不擋)
        self.assertEqual(split_codes(imei="490154203237519"), ("490154203237519", ""))
        self.assertEqual(split_codes(sn=IMEI_A), ("", IMEI_A))
        self.assertEqual(split_codes(imei=f" {IMEI_A} ", sn=f" {SN_A} "), (IMEI_A, SN_A))

    def test_nonsense_is_refused(self):
        for kwargs, text in (({}, "至少要填一個"), ({"imei": "  ", "sn": ""}, "至少要填一個"),
                             ({"sn": "---"}, "不是有效的碼"), ({"imei": "x" * 81}, "太長"),
                             ({"imei": IMEI_A, "sn": "490154-203237-518"}, "不能是同一個碼")):
            with self.assertRaises(IdentifierError) as ctx:
                split_codes(**kwargs)
            self.assertIn(text, str(ctx.exception))


class StockInTests(_Shop):
    def test_both_codes_only_imei_only_sn(self):
        self.buy([{"imei": IMEI_A, "sn": SN_A}, {"imei": IMEI_B, "sn": ""}, {"imei": "", "sn": SN_B}])
        both, only_imei, only_sn = self.unit(IMEI_A), self.unit(IMEI_B), self.unit(SN_B)
        # 主碼:有 IMEI 用 IMEI,沒有才用 SN
        self.assertEqual((both.serial_no, only_imei.serial_no, only_sn.serial_no), (IMEI_A, IMEI_B, SN_B))
        self.assertEqual(codes_of(both), {"imei": IMEI_A, "sn": SN_A})
        self.assertEqual(codes_of(only_imei), {"imei": IMEI_B, "sn": ""})
        self.assertEqual(codes_of(only_sn), {"imei": "", "sn": SN_B})
        self.assertEqual(self.unit(SN_A).pk, both.pk)           # 兩個碼是同一台
        shown = self.api_unit(both.pk)
        self.assertEqual((shown["serial_no"], shown["imei"], shown["sn"]), (IMEI_A, IMEI_A, SN_A))
        self.assertEqual(
            sorted(ProductSerialIdentifier.objects.filter(serial=both).values_list("kind", "value", "is_primary")),
            [("imei", IMEI_A, True), ("sn", SN_A, False)])

    def test_old_single_code_format_still_works(self):
        self.buy([IMEI_A, SN_A, {"sn": IMEI_B, "grade": ""}])
        self.assertEqual(codes_of(self.unit(IMEI_A)), {"imei": IMEI_A, "sn": ""})
        self.assertEqual(codes_of(self.unit(SN_A)), {"imei": "", "sn": SN_A})
        self.assertEqual(codes_of(self.unit(IMEI_B)), {"imei": IMEI_B, "sn": ""})

    def test_one_code_belongs_to_one_unit(self):
        self.buy([{"imei": IMEI_A, "sn": SN_A}])
        for entries, text in (
            ([{"imei": IMEI_A, "sn": ""}], "已存在"),                       # 同一個 IMEI
            ([{"imei": IMEI_B, "sn": SN_A}], "已存在"),                     # 別台的 SN
            ([{"imei": "", "sn": "f2l-xk1 abcd"}], "已存在"),               # 寫法不同還是同一個碼
            ([{"imei": "", "sn": IMEI_A}], "已存在"),                       # 別台的 IMEI 填到 SN 那一格
            ([{"imei": IMEI_B, "sn": SN_B}, {"imei": IMEI_C, "sn": SN_B}], "重複"),   # 同一張單兩台同一個 SN
            ([{"imei": IMEI_B, "sn": ""}, {"imei": "", "sn": IMEI_B}], "重複"),       # 一台的 IMEI = 另一台的 SN
            ([{"imei": IMEI_B, "sn": IMEI_B}], "不能是同一個碼"),
            ([{"imei": "", "sn": ""}], "至少要填一個"),
        ):
            r = self.buy(entries, ok=False)
            self.assertEqual(r.status_code, 400, entries)
            self.assertIn(text, r.content.decode(), entries)
        self.assertEqual(ProductSerial.objects.filter(tenant=self.t).count(), 1)
        # 存檔前一次把撞到的碼都講出來(不是存到一半才一個一個報)
        r = self.buy([{"imei": IMEI_A, "sn": ""}, {"imei": IMEI_B, "sn": SN_A}], ok=False)
        self.assertIn(f"序號已存在於系統:{IMEI_A}, {SN_A}", r.content.decode())
        # 同一張單不同行也一樣:第二行的 SN 跟第一行那一台相同
        r = self.c.admin.post("/api/v1/purchase-orders/", {
            "supplier": self.c.supplier.id, "warehouse": self.c.wh.id, "tax_method": "untaxed",
            "items": [{"product": self.c.phone.id, "qty": 1, "unit_price": "20000",
                       "serial_numbers": [{"imei": IMEI_B, "sn": SN_B}]},
                      {"product": self.c.phone.id, "qty": 1, "unit_price": "20000",
                       "serial_numbers": [{"imei": IMEI_C, "sn": "g6tzn0qwer"}]}],
        }, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("整單序號內出現重複", r.content.decode())

    def test_another_company_can_have_the_same_code(self):
        b = Company("b", "乙通訊行", "乙")
        self.buy([{"imei": IMEI_A, "sn": SN_A}])
        r = b.admin.post("/api/v1/purchase-orders/", {
            "supplier": b.supplier.id, "warehouse": b.wh.id, "tax_method": "untaxed",
            "items": [{"product": b.phone.id, "qty": 1, "unit_price": "20000",
                       "serial_numbers": [{"imei": IMEI_A, "sn": SN_A}]}],
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content.decode())
        mine, theirs = find_serial_ids(self.t, SN_A), find_serial_ids(b.tenant, SN_A)
        self.assertEqual((len(mine), len(theirs)), (1, 1))
        self.assertNotEqual(mine, theirs)
        # 搜尋也只看得到自己公司那一台
        found = self.c.admin.get(f"/api/v1/serials/?search={SN_A}").json()["results"]
        self.assertEqual([s["id"] for s in found], mine)

    def test_personal_buy_back_takes_both_codes(self):
        from apps.catalog.models import Product
        from apps.parties.models import Member

        used = Product.objects.create(
            tenant=self.t, category=self.c.cat_phone, name="甲 中古 iPhone 13", is_secondhand=True)
        member = Member.objects.create(tenant=self.t, name="賣家", phone="0911222333")
        body = {"member": member.id, "warehouse": self.c.wh.id, "product": used.id,
                "condition_grade": "A", "acquisition_price": "8000", "payment_method_code": "cash"}
        r = self.c.admin.post("/api/v1/sales-orders/secondhand-acquisition/",
                              {**body, "imei": IMEI_A, "sn": SN_A}, format="json")
        self.assertEqual(r.status_code, 201, r.content.decode())
        self.assertEqual((r.json()["serial"]["imei"], r.json()["serial"]["sn"]), (IMEI_A, SN_A))
        # 舊寫法(只給 serial_no)照舊;碼已經被用掉就擋
        r = self.c.admin.post("/api/v1/sales-orders/secondhand-acquisition/",
                              {**body, "serial_no": SN_B}, format="json")
        self.assertEqual(r.status_code, 201, r.content.decode())
        self.assertEqual(codes_of(self.unit(SN_B)), {"imei": "", "sn": SN_B})
        r = self.c.admin.post("/api/v1/sales-orders/secondhand-acquisition/",
                              {**body, "imei": IMEI_B, "sn": SN_A}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn(f"序號 {SN_A} 已存在", r.content.decode())     # 講的是撞到的那個碼,不是主碼
        # 擋下來的時候什麼都沒建(連收購用的虛擬商品都不該多出來)
        self.assertEqual(ProductSerial.objects.filter(tenant=self.t).count(), 2)


class LookupTests(_Shop):
    def setUp(self):
        super().setUp()
        self.buy([{"imei": IMEI_A, "sn": SN_A}, {"imei": "", "sn": SN_B}])
        self.both, self.only_sn = self.unit(IMEI_A), self.unit(SN_B)

    def serials(self, **params):
        r = self.c.admin.get("/api/v1/serials/", params)
        self.assertEqual(r.status_code, 200, r.content.decode())
        return [s["id"] for s in r.json()["results"]]

    def products(self, **params):
        r = self.c.admin.get("/api/v1/products/", params)
        self.assertEqual(r.status_code, 200, r.content.decode())
        return [p["id"] for p in r.json()["results"]]

    def test_either_code_finds_the_same_unit(self):
        for code in (IMEI_A, SN_A, SN_A.lower(), "f2l-xk1 abcd", "49 015420 323751 8"):
            self.assertEqual(self.serials(search=code), [self.both.pk], code)
        self.assertEqual(self.serials(search=SN_B), [self.only_sn.pk])
        # 打末幾碼也可以(挑序號的下拉會這樣用),而且一台只出現一次
        self.assertEqual(self.serials(search=SN_A[-5:]), [self.both.pk])
        self.assertEqual(self.serials(search=IMEI_A[-6:]), [self.both.pk])
        # 挑序號的下拉會帶門市 / 商品 / 在庫:其他條件照常生效
        self.assertEqual(self.serials(search=SN_A, status="in_stock", product=self.c.phone.id,
                                      warehouse=self.c.wh.id), [self.both.pk])
        self.assertEqual(self.serials(search=SN_A, warehouse=self.c.warehouses[1].id), [])
        self.assertEqual(self.serials(search=SN_A, status="sold"), [])

    def test_a_scan_means_exactly_that_unit(self):
        """刷條碼自動掛序號用 ?code=:只認完全相同。同商品另一台的碼剛好「包含」這串字時不能掛到它。"""
        self.buy([{"imei": "", "sn": "ABC123"}, {"imei": "", "sn": "XABC123Y"}])
        short, long_ = self.unit("ABC123"), self.unit("XABC123Y")
        self.assertEqual(sorted(self.serials(search="ABC123")), sorted([short.pk, long_.pk]))   # 下拉:包含
        self.assertEqual(self.serials(code="ABC123"), [short.pk])                               # 刷條碼:就這一台
        self.assertEqual(self.serials(code="abc-123"), [short.pk])
        self.assertEqual(self.serials(code="xabc123y"), [long_.pk])
        self.assertEqual(self.serials(code="BC12"), [])
        # IMEI、SN 都算;其他條件照常
        self.assertEqual(self.serials(code=SN_A), [self.both.pk])
        self.assertEqual(self.serials(code=IMEI_A, status="in_stock", warehouse=self.c.wh.id), [self.both.pk])
        self.assertEqual(self.serials(code=IMEI_A, warehouse=self.c.warehouses[1].id), [])
        b = Company("b", "乙通訊行", "乙")
        self.assertEqual(b.admin.get("/api/v1/serials/", {"code": SN_A}).json()["results"], [])

    def test_a_scanned_code_brings_up_its_product(self):
        for code in (IMEI_A, SN_A, SN_B, SN_A.lower()):
            self.assertEqual(self.products(search=code), [self.c.phone.id], code)
        # 銷貨的挑商品清單也是(有庫存才列)
        self.assertEqual(self.products(search=SN_A, sales_pickable="true", is_active="true",
                                       warehouse=self.c.wh.id), [self.c.phone.id])
        # 商品搜尋只認「完全相同」的碼:SN 的一部分不會把商品帶出來
        self.assertEqual(self.products(search=SN_A[:6]), [])

    def test_stock_query_page_finds_the_product_by_either_code(self):
        def matrix(search):
            r = self.c.admin.get("/api/v1/products/stock-matrix/", {"search": search})
            self.assertEqual(r.status_code, 200, r.content.decode())
            return [row["id"] for row in r.json()["products"]]

        for code in (IMEI_A, SN_A, SN_B, SN_A.lower(), "f2l-xk1 abcd", IMEI_A[-6:]):
            self.assertEqual(matrix(code), [self.c.phone.id], code)
        # SN 的一部分、太短的數字不比對碼
        self.assertEqual(matrix(SN_A[:6]), [])
        self.assertEqual(matrix(IMEI_A[-5:]), [])
        # 別家公司有同一個碼,不會把別家的商品帶進來
        b = Company("b", "乙通訊行", "乙")
        self.assertEqual(
            b.admin.get("/api/v1/products/stock-matrix/", {"search": SN_A}).json()["products"], [])

    def test_sell_and_transfer_the_unit_found_by_its_sn(self):
        pk = self.serials(search=SN_A, status="in_stock")[0]
        r = self.c.admin.post("/api/v1/sales-orders/", {
            "customer": self.c.customer.id, "warehouse": self.c.wh.id, "tax_method": "untaxed",
            "items": [{"product": self.c.phone.id, "qty": 1, "unit_price": "25000", "serial_ids": [pk]}],
            "payments": [{"method": "cash", "amount": "25000"}],
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content.decode())
        self.both.refresh_from_db()
        self.assertEqual(self.both.status, "sold")
        self.assertEqual(self.serials(search=IMEI_A, status="in_stock"), [])
        pk = self.serials(search=SN_B, status="in_stock")[0]
        r = self.c.admin.post("/api/v1/transfer-orders/", {
            "from_warehouse": self.c.wh.id, "to_warehouse": self.c.warehouses[1].id,
            "items": [{"product": self.c.phone.id, "qty": 1, "serial_ids": [pk]}],
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content.decode())
        self.only_sn.refresh_from_db()
        self.assertEqual(self.only_sn.status, "in_transit")


class EditCodesTests(_Shop):
    def setUp(self):
        super().setUp()
        self.buy([{"imei": IMEI_A, "sn": ""}, {"imei": "", "sn": SN_B}])
        self.phone, self.watch = self.unit(IMEI_A), self.unit(SN_B)

    def edit(self, unit, client, **codes):
        return client.post(f"/api/v1/serials/{unit.pk}/codes/", codes, format="json")

    def test_clerk_fills_the_empty_box(self):
        r = self.edit(self.phone, self.c.clerk, imei=IMEI_A, sn=SN_A)
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.assertEqual((r.json()["imei"], r.json()["sn"], r.json()["serial_no"]), (IMEI_A, SN_A, IMEI_A))
        self.assertEqual(self.unit(SN_A).pk, self.phone.pk)
        # 只有 SN 的那一台補上 IMEI:主碼換成 IMEI,原本的 SN 還是找得到
        r = self.edit(self.watch, self.c.clerk, imei=IMEI_B, sn=SN_B)
        self.assertEqual((r.status_code, r.json()["serial_no"]), (200, IMEI_B))
        self.assertEqual((self.unit(SN_B).pk, self.unit(IMEI_B).pk), (self.watch.pk, self.watch.pk))
        log = list(ProductSerialCodeChange.objects.filter(tenant=self.t).order_by("id").values_list(
            "serial_id", "before_imei", "before_sn", "after_imei", "after_sn", "changed_by"))
        self.assertEqual(log, [(self.phone.pk, IMEI_A, "", IMEI_A, SN_A, "a-clerk"),
                               (self.watch.pk, "", SN_B, IMEI_B, SN_B, "a-clerk")])
        # 送一樣的內容不算改動,不多記一筆
        self.assertEqual(self.edit(self.phone, self.c.clerk, imei=IMEI_A, sn=SN_A).status_code, 200)
        self.assertEqual(ProductSerialCodeChange.objects.count(), 2)
        # 序號履歷看得到這一台被改過什麼(只有這一台的)
        shown = self.c.admin.get(f"/api/v1/serials/{self.phone.pk}/history/").json()["code_changes"]
        self.assertEqual([(c["changed_by"], c["before_imei"], c["before_sn"], c["after_imei"], c["after_sn"])
                          for c in shown], [("a-clerk", IMEI_A, "", IMEI_A, SN_A)])

    def test_only_an_admin_changes_a_code_that_is_already_there(self):
        for codes in ({"imei": IMEI_B, "sn": ""}, {"imei": "", "sn": SN_A}, {"imei": "", "sn": ""}):
            r = self.edit(self.phone, self.c.clerk, **codes)
            self.assertEqual(r.status_code, 400, codes)
            self.assertIn("只有管理員能改", r.content.decode())
        self.assertEqual(codes_of(self.unit(IMEI_A)), {"imei": IMEI_A, "sn": ""})
        r = self.edit(self.phone, self.c.admin, imei=IMEI_B, sn=SN_A)
        self.assertEqual((r.status_code, r.json()["serial_no"]), (200, IMEI_B))
        self.assertEqual(find_serial_ids(self.t, IMEI_A), [])        # 舊的碼不再指到任何一台
        self.assertEqual(self.unit(IMEI_B).pk, self.phone.pk)
        # 管理員可以清掉一格,但至少要留一個
        self.assertEqual(self.edit(self.phone, self.c.admin, imei="", sn=SN_A).json()["serial_no"], SN_A)
        r = self.edit(self.phone, self.c.admin, imei="", sn="")
        self.assertEqual(r.status_code, 400)
        self.assertIn("至少要填一個", r.content.decode())
        self.assertEqual(ProductSerialCodeChange.objects.filter(serial=self.phone).count(), 2)

    def test_who_may_edit_is_decided_after_the_unit_is_locked(self):
        """「在不在他的門市」要看鎖住之後重讀的那一列:先看再鎖,中間被調走 / 賣掉,原門市還是改得到。"""
        from .identifiers import IdentifierDenied, set_codes

        stale = ProductSerial.objects.get(pk=self.phone.pk)              # 讀到的時候還在湳雅店
        ProductSerial.objects.filter(pk=self.phone.pk).update(warehouse=self.c.warehouses[1])
        seen = []

        def check(unit):
            seen.append(unit.warehouse_id)
            raise IdentifierDenied("只能修改自己門市的設備")

        with self.assertRaises(IdentifierDenied):
            set_codes(stale, imei=IMEI_A, sn=SN_A, check=check)
        self.assertEqual(seen, [self.c.warehouses[1].id])                # 看到的是現在的門市,不是當初讀到的
        self.assertEqual(codes_of(self.unit(IMEI_A)), {"imei": IMEI_A, "sn": ""})
        self.assertEqual(ProductSerialCodeChange.objects.count(), 0)

    def test_codes_not_shown_on_screen_are_left_alone(self):
        """拍照入庫可能替一台多登記別的碼(IMEI2、第二個 SN)。補登 / 修改只換畫面上那兩個,其他的不能跟著不見。"""
        for kind, value in (("imei2", IMEI_C), ("sn", "EXTRASN1"), ("sn", "EXTRASN2")):
            ProductSerialIdentifier.objects.create(
                tenant=self.t, serial=self.phone, kind=kind, value=value,
                normalized_value=value, is_primary=False)
        # 同一種有兩個時,畫面顯示最新登記的那個(順序固定,顯示與修改才會指到同一列)
        shown, hidden = "EXTRASN2", "EXTRASN1"
        self.assertEqual(codes_of(self.unit(IMEI_A))["sn"], shown)
        self.assertEqual(self.api_unit(self.phone.pk)["sn"], shown)
        # 管理員把畫面上那個 SN 改成 SN_A:改完畫面上就是新的那個,不會換成另一個舊的
        r = self.edit(self.phone, self.c.admin, imei=IMEI_A, sn=SN_A)
        self.assertEqual((r.status_code, r.json()["sn"]), (200, SN_A))
        self.assertEqual(self.api_unit(self.phone.pk)["sn"], SN_A)
        self.assertEqual(find_serial_ids(self.t, shown), [])             # 被換掉的那個不見
        self.assertEqual(self.unit(SN_A).pk, self.phone.pk)
        # 沒顯示的那個 SN 與 IMEI2 都還在:刷得到同一台,別台也不能用
        self.assertEqual(self.unit(hidden).pk, self.phone.pk)
        self.assertEqual(self.unit(IMEI_C).pk, self.phone.pk)
        self.assertEqual(self.buy([{"imei": "", "sn": hidden}], ok=False).status_code, 400)
        # 把 SN 清掉:這一台另外登記的那個 SN 會顯示出來(它還佔著那個碼,不能藏著),可以再清一次
        r = self.edit(self.phone, self.c.admin, imei=IMEI_A, sn="")
        self.assertEqual((r.status_code, r.json()["sn"]), (200, hidden))
        r = self.edit(self.phone, self.c.admin, imei=IMEI_A, sn="")
        self.assertEqual((r.status_code, r.json()["sn"]), (200, ""))
        self.assertEqual(find_serial_ids(self.t, hidden), [])

    def test_cannot_take_another_units_code(self):
        for codes in ({"imei": IMEI_A, "sn": SN_B}, {"imei": IMEI_A, "sn": "g6t-zn0qwer"}):
            r = self.edit(self.phone, self.c.admin, **codes)
            self.assertEqual(r.status_code, 400, codes)
            self.assertIn("已經被別台設備用掉", r.content.decode())
        self.assertEqual(ProductSerialCodeChange.objects.count(), 0)
        self.assertEqual(self.unit(SN_B).pk, self.watch.pk)

    def test_void_units_and_other_stores_and_other_companies(self):
        ProductSerial.objects.filter(pk=self.watch.pk).update(status="void")
        r = self.edit(self.watch, self.c.admin, imei=IMEI_B, sn=SN_B)
        self.assertEqual(r.status_code, 400)
        self.assertIn("已經作廢", r.content.decode())
        # 鎖在自己門市的店員不能動別家門市的設備
        ProductSerial.objects.filter(pk=self.phone.pk).update(warehouse=self.c.warehouses[1])
        self.assertEqual(self.edit(self.phone, self.c.clerk, imei=IMEI_A, sn=SN_A).status_code, 403)
        # 已經賣出去的(不掛在任何門市):自己門市賣的可以補,別家門市賣的不行
        ProductSerial.objects.filter(pk=self.phone.pk).update(warehouse=self.c.wh)
        self.c.sell(serial_no=IMEI_A)
        self.assertEqual(ProductSerial.objects.get(pk=self.phone.pk).warehouse_id, None)
        r = self.edit(self.phone, self.c.clerk, imei=IMEI_A, sn=SN_A)
        self.assertEqual((r.status_code, r.json().get("sn")), (200, SN_A))
        self.c.purchase(warehouse=self.c.warehouses[1], phone_serials=[IMEI_C])
        self.c.sell(warehouse=self.c.warehouses[1], serial_no=IMEI_C)
        self.assertEqual(self.edit(self.unit(IMEI_C), self.c.clerk, imei=IMEI_C, sn="X1Y2Z3").status_code, 403)
        # 調撥中的不屬於任何一家門市:鎖倉店員不能動,管理員可以
        self.c.purchase(phone_serials=["358240051111110"])
        moving = self.unit("358240051111110")
        r = self.c.admin.post("/api/v1/transfer-orders/", {
            "from_warehouse": self.c.wh.id, "to_warehouse": self.c.warehouses[1].id,
            "items": [{"product": self.c.phone.id, "qty": 1, "serial_ids": [moving.pk]}],
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content.decode())
        self.assertEqual(self.edit(moving, self.c.clerk, imei="358240051111110", sn="M0V1NG").status_code, 403)
        self.assertEqual(self.edit(moving, self.c.admin, imei="358240051111110", sn="M0V1NG").status_code, 200)
        ProductSerialCodeChange.objects.all().delete()
        self.phone = ProductSerial.objects.get(pk=self.phone.pk)
        self.edit(self.phone, self.c.admin, imei=IMEI_A, sn="")      # 還原,下面照舊檢查
        ProductSerialCodeChange.objects.all().delete()
        # 別家公司根本看不到這一台
        b = Company("b", "乙通訊行", "乙")
        self.assertEqual(self.edit(self.phone, b.admin, imei=IMEI_A, sn=SN_A).status_code, 404)
        self.assertEqual(self.edit(self.phone, self.c.admin, imei=[IMEI_A], sn=SN_A).status_code, 400)
        self.assertEqual(codes_of(self.unit(IMEI_A)), {"imei": IMEI_A, "sn": ""})
        self.assertEqual(ProductSerialCodeChange.objects.count(), 0)


class OldDataTests(_Shop):
    """以前只有 serial_no、沒有登記碼的設備。"""

    def old_unit(self, serial_no):
        return ProductSerial.objects.create(      # 模擬舊資料:沒有走 create_serial
            tenant=self.t, product=self.c.phone, serial_no=serial_no, warehouse=self.c.wh)

    def backfill(self):
        module = importlib.import_module("apps.inventory.migrations.0012_backfill_serial_identifiers")
        module.backfill(django_apps, None)

    def test_backfill_registers_every_old_unit(self):
        a, b, clash = self.old_unit(IMEI_A), self.old_unit("AB-12"), self.old_unit("ab12")
        self.assertEqual(len(check_serials(self.t)[2]["samples"]), 3)
        self.backfill()
        self.assertEqual(
            sorted(ProductSerialIdentifier.objects.filter(tenant=self.t)
                   .values_list("serial_id", "kind", "value", "normalized_value", "is_primary")),
            sorted([(a.pk, "imei", IMEI_A, IMEI_A, True), (b.pk, "sn", "AB-12", "AB12", True)]))
        # 去掉破折號後跟別台相同的那一台不登記、不改資料,由每日對帳講出來
        result = check_serials(self.t)[2]
        self.assertEqual((result["key"], result["ok"], result["count"]), ("serial_codes", False, 1))
        self.assertIn("主序號沒有登記", result["samples"][0])
        self.assertIn("刷這個碼會對到兩台", result["samples"][0])
        # 用哪一種寫法找,兩台都找得到(撞在一起這件事看得見,不會只找到其中一台)
        for code in ("AB-12", "ab12", "AB12"):
            self.assertEqual(find_serial_ids(self.t, code), sorted([b.pk, clash.pk]), code)
        # 刷條碼用的 ?code= 也是兩台都回來:畫面看到不只一台就不自動掛(不會任選一台賣出去)
        found = self.c.admin.get("/api/v1/serials/", {"code": "AB12"}).json()["results"]
        self.assertEqual(sorted(s["id"] for s in found), sorted([b.pk, clash.pk]))
        self.backfill()                              # 再跑一次不會多出東西
        self.assertEqual(ProductSerialIdentifier.objects.filter(tenant=self.t).count(), 2)
        # 補登記之後,新進貨不能再用舊設備的碼
        r = self.buy([{"imei": "", "sn": "AB 12"}], ok=False)
        self.assertEqual(r.status_code, 400)

    def test_old_units_get_the_imei_as_main_code(self):
        """以前拍照入庫的設備,SN 被標成主碼、同一台也有 IMEI:升級後主碼換成 IMEI,原本的 SN 仍然刷得到。"""
        module = importlib.import_module("apps.inventory.migrations.0013_main_code_prefers_imei")

        def old_intake_unit(sn, imei):
            unit = self.old_unit(sn)
            for kind, value, primary in (("sn", sn, True), ("imei", imei, False)):
                ProductSerialIdentifier.objects.create(
                    tenant=self.t, serial=unit, kind=kind, value=value,
                    normalized_value=value, is_primary=primary)
            return unit

        fixed = old_intake_unit(SN_A, IMEI_A)
        blocked = old_intake_unit(SN_B, IMEI_B)
        other = self.old_unit(IMEI_B)                    # 那個 IMEI 已經是別台的主碼(不該發生):不硬改
        self.buy([{"imei": IMEI_C, "sn": "ZZTOP12345"}])  # 新規則入庫的:本來就是 IMEI 當主碼
        already = self.unit(IMEI_C)
        module.prefer_imei(django_apps, None)
        for unit in (fixed, blocked, other, already):
            unit.refresh_from_db()
        self.assertEqual((fixed.serial_no, blocked.serial_no, other.serial_no, already.serial_no),
                         (IMEI_A, SN_B, IMEI_B, IMEI_C))
        self.assertEqual(codes_of(fixed), {"imei": IMEI_A, "sn": SN_A})
        self.assertEqual(
            sorted(ProductSerialIdentifier.objects.filter(serial=fixed).values_list("kind", "is_primary")),
            [("imei", True), ("sn", False)])
        self.assertEqual((self.unit(SN_A).pk, self.unit(IMEI_A).pk), (fixed.pk, fixed.pk))
        self.assertEqual(self.api_unit(fixed.pk)["serial_no"], IMEI_A)
        module.prefer_imei(django_apps, None)             # 再跑一次不會再變
        fixed.refresh_from_db()
        self.assertEqual(fixed.serial_no, IMEI_A)

    def test_unregistered_unit_still_blocks_and_shows_its_code(self):
        old = self.old_unit(SN_A)
        self.assertEqual(self.api_unit(old.pk)["sn"], SN_A)
        self.assertEqual(find_serial_ids(self.t, SN_A), [old.pk])
        self.assertEqual(self.buy([{"imei": IMEI_A, "sn": SN_A}], ok=False).status_code, 400)
        # 大小寫不同也擋得住、找得到(主碼存原文,沒登記的那一台只能靠主碼比)
        self.assertEqual(find_serial_ids(self.t, SN_A.lower()), [old.pk])
        self.assertEqual(self.buy([{"imei": IMEI_A, "sn": SN_A.lower()}], ok=False).status_code, 400)
        lower = self.old_unit("ab12cd")
        self.assertEqual(find_serial_ids(self.t, "AB12CD"), [lower.pk])
        self.assertEqual(self.buy([{"imei": IMEI_A, "sn": "AB-12CD"}], ok=False).status_code, 400)

    def test_new_units_are_always_registered(self):
        self.buy([{"imei": IMEI_A, "sn": SN_A}, SN_B])
        result = check_serials(self.t)[2]
        self.assertEqual((result["ok"], result["count"]), (True, 0))


class EveryEntranceTests(TestCase):
    def test_nobody_creates_a_unit_without_registering_its_codes(self):
        """新增設備只能走 create_serial();直接建的那一台沒有登記碼,別台就能再用同一個碼。"""
        root = pathlib.Path(__file__).resolve().parents[1]
        pattern = re.compile(
            r"ProductSerial(\.objects\.(create|bulk_create|get_or_create|update_or_create)\b|\(\s*$|\(\w+=)")
        offenders = []
        for path in root.rglob("*.py"):
            rel = path.relative_to(root).as_posix()
            if ("/migrations/" in rel or "/tests/" in rel or path.name.startswith("test")
                    or path.name == "tests.py" or rel == "inventory/identifiers.py"):
                continue
            for n, line in enumerate(path.read_text().splitlines(), 1):
                if pattern.search(line) and not line.lstrip().startswith(("class ", "#")):
                    offenders.append(f"{rel}:{n}")
        self.assertEqual(offenders, [])

    def test_create_serial_refuses_a_taken_code(self):
        c = Company("a", "甲通訊行", "甲")
        create_serial(tenant=c.tenant, product=c.phone, imei=IMEI_A, sn=SN_A, warehouse=c.wh)
        for kwargs in ({"imei": IMEI_A}, {"sn": SN_A}, {"code": SN_A.lower()}):
            with self.assertRaises(IdentifierError):
                create_serial(tenant=c.tenant, product=c.phone, warehouse=c.wh, **kwargs)
        # 訊息講的是被用掉的那個碼(這裡是 SN),不是這一台的主碼
        with self.assertRaises(IdentifierError) as ctx:
            create_serial(tenant=c.tenant, product=c.phone, warehouse=c.wh, imei=IMEI_B, sn=SN_A)
        self.assertEqual(str(ctx.exception), f"序號已存在於系統:{SN_A}")
        self.assertEqual(ProductSerial.objects.count(), 1)
