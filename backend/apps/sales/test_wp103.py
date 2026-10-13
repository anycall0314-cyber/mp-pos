"""WP-103 三聯式發票機:一張發票排成一頁、轉成機器收的位元組;測試頁的端點。

owner 2026-10-13:發票機是 WP-103(三聯式收銀機發票,號碼已經印在紙上);樣張上機器印的字要對著紙上印好的「日期:」「買受人:」「銷售額:」…。
每一項在第幾行、第幾格還沒有在實機上對過(`wp103.ROWS`、`COLS_AT`)—— 這裡驗的是「照那兩張表排、不會排壞」。
"""
import base64
from datetime import datetime

from django.test import SimpleTestCase, TestCase

from apps.backup.tests.factory import Company

from . import wp103

WHEN = datetime(2026, 10, 12, 16, 7)


def invoice(**over):
    return {**wp103.sample_invoice(WHEN), **over}


class TextTests(SimpleTestCase):
    def test_a_chinese_character_takes_two_cells(self):
        self.assertEqual([wp103.cols(t) for t in ("AB12", "發票", "統編:37", "", "é", "🙂")], [4, 4, 7, 0, 1, 1])
        self.assertEqual(wp103.fit("通訊器材ABC", 5), "通訊")              # 不切半個中文字
        self.assertEqual(wp103.fit("通訊器材ABC", 9), "通訊器材A")
        self.assertEqual(wp103.fit("ABC", 10), "ABC")

    def test_text_becomes_big5_and_unknown_characters_become_a_question_mark(self):
        self.assertEqual(wp103.encode("發票A1"), bytes.fromhex("b56fb2bc") + b"A1")
        self.assertEqual(wp103.encode("简🙂é"), b"???")                   # 機器沒有的字:印成 ?,不卡住整張
        # 資料裡的控制字元不能變成機器的指令或多跳行
        self.assertEqual(wp103.encode("A\nB\x1b@C\x0cD\tE\r"), b"A B @C D E ")
        self.assertEqual(wp103.clean("  通訊\n器材 \t x "), "通訊 器材 x")

    def test_putting_text_at_a_column_and_against_the_right_edge(self):
        self.assertEqual(wp103.put("", 3, "AB"), "   AB")
        self.assertEqual(wp103.put("發票", 3, "X"), "發 X")                 # 第 3 格在「票」的中間:那個字讓出來
        self.assertEqual(wp103.put("ABCDEFG", 2, "xy"), "ABxy")
        self.assertEqual(wp103.put_right("", 10, "$1,234"), "    $1,234")
        self.assertEqual(wp103.put_right("現金:", 12, "$5"), "現金:     $5")
        self.assertEqual(wp103.cols(wp103.put("", 30, "很長很長很長很長很長")), wp103.LINE_COLS - 1)   # 超出一行的切掉(不切半個字)

    def test_money_and_the_roc_date(self):
        self.assertEqual([wp103.money(v) for v in (45233, "2154.00", 0, "0.4", "0.5", 1000000)],
                         ["$45,233", "$2,154", "$0", "$0", "$1", "$1,000,000"])           # 四捨五入
        self.assertEqual(wp103.roc_stamp(WHEN), "115/10/12 16:07")
        self.assertEqual(wp103.roc_stamp(datetime(2027, 1, 3, 9, 5)), "116/01/03 09:05")


class LayoutTests(SimpleTestCase):
    def test_every_item_lands_on_its_row(self):
        page = wp103.invoice_lines(invoice())
        self.assertEqual(len(page), wp103.PAGE_LINES)
        at = lambda name, offset=0: page[wp103.ROWS[name] - 1 + offset]
        self.assertEqual(at("store"), " 測試門市")
        self.assertEqual(at("address"), " 300-新竹市-測試路1號")
        self.assertEqual(at("tax_tel"), " 統編:00000000 TEL:03-0000000")
        self.assertEqual(at("date"), " " * 8 + "115/10/12 16:07 01機")
        self.assertEqual(at("buyer"), " " * 8 + "12345678  收銀員:TEST")
        self.assertEqual(at("doc_no"), " " * 23 + "SO-000000")
        self.assertEqual(at("items"), " 通訊器材            x4  $45,233")
        self.assertEqual((at("payments"), at("payments", 1)), (" 現金:                   $12,000", " 信用卡:                 $33,233"))
        self.assertEqual((at("subtotal"), at("tax"), at("total")), (" " * 11 + "$43,079", " " * 11 + "$2,154", " " * 11 + "$45,233"))
        # 靠右的都對齊同一條右邊界
        for line in (at("doc_no"), at("items"), at("payments"), at("payments", 1)):
            self.assertEqual(wp103.cols(line), wp103.COLS_AT["right_edge"])
        # 其他行都是空的
        used = {wp103.ROWS[k] for k in wp103.ROWS} | {wp103.ROWS["payments"] + 1}
        self.assertEqual([i + 1 for i, line in enumerate(page) if line], sorted(used))

    def test_blank_lines_on_top_push_everything_down_together(self):
        base, pushed = wp103.invoice_lines(invoice()), wp103.invoice_lines(invoice(), top=3)
        self.assertEqual(pushed, [""] * 3 + base[:-3])
        self.assertEqual(len(pushed), wp103.PAGE_LINES)
        with self.assertRaisesMessage(wp103.LayoutError, "上面空太多行"):       # 推到印不進一頁:不印,不默默少印最下面的總計
            wp103.invoice_lines(invoice(), top=wp103.PAGE_LINES - wp103.ROWS["total"] + 1)
        self.assertTrue(wp103.invoice_lines(invoice(), top=wp103.PAGE_LINES - wp103.ROWS["total"])[-1])

    def test_optional_parts_are_left_out_cleanly(self):
        page = wp103.invoice_lines(invoice(tel="", register="", buyer_tax_id="", cashier=""))
        self.assertEqual(page[wp103.ROWS["tax_tel"] - 1], " 統編:00000000")
        self.assertEqual(page[wp103.ROWS["date"] - 1], " " * 8 + "115/10/12 16:07")
        self.assertEqual(page[wp103.ROWS["buyer"] - 1], "")
        only_cashier = wp103.invoice_lines(invoice(buyer_tax_id=""))
        self.assertEqual(only_cashier[wp103.ROWS["buyer"] - 1], " " * 18 + "收銀員:TEST")

    def test_a_long_name_is_cut_but_quantity_and_amount_stay(self):
        long = "9H/平板/IMOS/低藍光/IPAD/AIR/13吋(2024)"
        line = wp103.invoice_lines(invoice(items=[{"name": long, "qty": 12, "amount": 1234567}]))[wp103.ROWS["items"] - 1]
        self.assertTrue(line.endswith(" x12  $1,234,567"), line)
        self.assertEqual(wp103.cols(line), wp103.COLS_AT["right_edge"])
        self.assertTrue(line.startswith(" 9H/平板/IMOS"), line)
        # 品名與數量之間一定留一格(品名先切到放得下,不是被數量蓋掉)
        plain = wp103.invoice_lines(invoice(items=[{"name": "A" * 40, "qty": 12, "amount": 1234567}]))[wp103.ROWS["items"] - 1]
        self.assertEqual(plain, " " + "A" * 15 + " x12  $1,234,567")

    def test_too_many_rows_is_refused_not_trimmed(self):
        items = [{"name": f"品{i}", "qty": 1, "amount": 10} for i in range(wp103.ITEM_ROWS + 1)]
        with self.assertRaisesMessage(wp103.LayoutError, f"品名最多印 {wp103.ITEM_ROWS} 行"):
            wp103.invoice_lines(invoice(items=items))
        page = wp103.invoice_lines(invoice(items=items[:-1]))                 # 剛好放滿:最後一行品名在付款方式的上一行
        self.assertTrue(page[wp103.ROWS["payments"] - 2].startswith(f" 品{wp103.ITEM_ROWS - 1}"))
        pays = [{"name": f"付{i}", "amount": 1} for i in range(wp103.PAYMENT_ROWS + 1)]
        with self.assertRaisesMessage(wp103.LayoutError, f"付款方式最多印 {wp103.PAYMENT_ROWS} 行"):
            wp103.invoice_lines(invoice(payments=pays))
        page = wp103.invoice_lines(invoice(payments=pays[:-1]))
        self.assertTrue(page[wp103.ROWS["subtotal"] - 2].startswith(f" 付{wp103.PAYMENT_ROWS - 1}:"))

    def test_the_rows_keep_their_order_and_fit_the_page(self):
        order = ["store", "address", "tax_tel", "date", "buyer", "doc_no", "items", "payments", "subtotal", "tax", "total"]
        rows = [wp103.ROWS[k] for k in order]
        self.assertEqual(rows, sorted(set(rows)))
        self.assertLessEqual(rows[-1] + wp103.TOP_RANGE[0], wp103.PAGE_LINES)
        self.assertGreater(wp103.ITEM_ROWS, 0)
        self.assertGreater(wp103.PAYMENT_ROWS, 0)
        self.assertLess(wp103.COLS_AT["right_edge"], wp103.LINE_COLS + 1)

    def test_the_ruler_numbers_every_row_and_counts_the_columns(self):
        ruler = wp103.ruler_lines()
        self.assertEqual(len(ruler), wp103.PAGE_LINES)
        self.assertEqual([line[:2] for line in ruler], [f"{n:02d}" for n in range(1, wp103.PAGE_LINES + 1)])
        self.assertEqual({wp103.cols(line) for line in ruler}, {wp103.LINE_COLS})
        self.assertEqual({line[2:] for line in ruler}, {"..:....1....:....2....:....3....:...."})    # 第 10、20、30 格寫 1、2、3
        self.assertEqual((ruler[0][9], ruler[0][19], ruler[0][29], ruler[0][4]), ("1", "2", "3", ":"))


class BytesTests(SimpleTestCase):
    def test_a_page_is_reset_lines_and_a_form_feed(self):
        data = wp103.page_bytes(["A", "", "發票", "", ""])
        self.assertEqual(data, b"\x1b@" + b"\x1bC" + bytes([33]) + b"A\n" + b"\n" + bytes.fromhex("b56fb2bc") + b"\n" + b"\x0c")
        self.assertEqual(wp103.page_bytes([]), b"\x1b@\x1bC!\x0c")
        self.assertEqual(wp103.page_bytes(wp103.ruler_lines()).count(b"\n"), wp103.PAGE_LINES)
        self.assertEqual(wp103.page_bytes(wp103.ruler_lines()).count(b"\x0c"), 1)

    def test_a_page_that_is_too_long_or_too_wide_is_refused(self):
        with self.assertRaisesMessage(wp103.LayoutError, "一頁最多 33 行"):
            wp103.page_bytes(["x"] * 34)
        with self.assertRaisesMessage(wp103.LayoutError, "一行最多 39 格"):
            wp103.page_bytes(["發" * 20])
        wp103.page_bytes(["發" * 19 + "A"])                                   # 39 格:剛好

    def test_a_whole_invoice_fits_the_printer_buffer(self):
        full = invoice(items=[{"name": "通訊器材" * 5, "qty": 99, "amount": 9999999}] * wp103.ITEM_ROWS,
                       payments=[{"name": "信用卡", "amount": 9999999}] * wp103.PAYMENT_ROWS)
        self.assertLess(len(wp103.page_bytes(wp103.invoice_lines(full))), 4096)       # 機器的緩衝區 4K


class TestPageApiTests(TestCase):
    URL = "/api/v1/invoice-printer/test/"

    def setUp(self):
        self.c = Company("a", "甲通訊行", "甲")

    def test_ruler_and_sample_come_with_the_bytes_to_send(self):
        got = self.c.clerk.get(self.URL).json()                              # 沒講哪一種 = 行號測試
        self.assertEqual((got["kind"], got["lines"], got["page_lines"]), ("ruler", wp103.ruler_lines(), 33))
        self.assertEqual(base64.b64decode(got["data"]), wp103.page_bytes(wp103.ruler_lines()))
        # 行號測試量的是紙上真正的第幾行:不被「上面空幾行」推
        self.assertEqual(self.c.clerk.get(self.URL, {"kind": "ruler", "top": "5"}).json()["lines"], wp103.ruler_lines())
        got = self.c.clerk.get(self.URL, {"kind": "sample", "top": "2"}).json()
        self.assertEqual((got["kind"], got["top"], got["lines"][:2]), ("sample", 2, ["", ""]))
        self.assertEqual(got["lines"][2], " 測試門市")
        self.assertEqual(base64.b64decode(got["data"]), wp103.page_bytes(got["lines"]))
        self.assertTrue(base64.b64decode(got["data"]).endswith(b"\x0c"))

    def test_blank_lines_can_go_up_to_where_the_total_still_fits(self):
        """「上面空幾行」的上限:空到「總計」剛好印在最後一行。調到上限也印得出來(不會按了 + 之後才報錯);畫面的上限是同一個數字。"""
        low, high = wp103.TOP_RANGE
        self.assertEqual((low, high), (0, wp103.PAGE_LINES - wp103.ROWS["total"]))
        got = self.c.clerk.get(self.URL, {"kind": "sample", "top": str(high)})
        self.assertEqual(got.status_code, 200, got.content.decode())
        self.assertEqual(got.json()["lines"][-1], " " * 11 + "$45,233")
        from pathlib import Path
        front = Path(__file__).resolve().parents[3] / "frontend" / "src" / "lib" / "serialPrinter.ts"
        self.assertIn(f"topMax: {high} }}", front.read_text(encoding="utf-8"))

    def test_odd_requests(self):
        low, high = wp103.TOP_RANGE
        for raw, top in (("", low), ("abc", low), ("-3", low), ("999", high), ("３", low)):
            self.assertEqual(self.c.clerk.get(self.URL, {"kind": "sample", "top": raw}).json()["top"], top, raw)
        self.assertEqual(self.c.clerk.get(self.URL, {"kind": "invoice"}).status_code, 400)
        from rest_framework.test import APIClient
        self.assertEqual(APIClient().get(self.URL).status_code, 401)         # 要登入
