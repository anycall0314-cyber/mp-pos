"""匯入表格(全站檢視 D7 / D8):先選類別、按數量 / 逐件記序號一定要選、主機類別不收、品號可以空著、類別不自動建。"""
import io
import json

from django.test import TestCase

from apps.backup.tests.factory import Company
from apps.catalog.models import Category, Product

URL = "/api/v1/products/import/"


class ProductImportTests(TestCase):
    def setUp(self):
        self.c = Company("a", "甲通訊行", "甲")
        self.cat = self.c.cat_case                       # 皮套(配件)
        self.cat_phone = self.c.cat_phone
        self.cat_phone.holds_devices = True
        self.cat_phone.save()

    def post(self, body, fmt="json"):
        return self.c.admin.post(URL, body, format=fmt)

    def paste(self, rows, **extra):
        body = {"rows": rows, "category": self.cat.id, "requires_serial": "false", "first_row": 1, **extra}
        r = self.post(body)
        self.assertEqual(r.status_code, 200, r.content.decode())
        return r.json()

    def test_category_and_the_serial_choice_must_be_given_and_devices_are_refused(self):
        rows = [{"品名": "甲 新皮套 A1"}]
        r = self.post({"rows": rows, "requires_serial": "false"})
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "請先選類別"))
        r = self.post({"rows": rows, "category": self.cat.id})
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "請選按數量或逐件記序號"))
        r = self.post({"rows": rows, "category": self.cat_phone.id, "requires_serial": "true"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("手機型號", r.json()["detail"])
        other = Company("b", "乙通訊行", "乙")
        r = self.post({"rows": rows, "category": other.cat_case.id, "requires_serial": "false"})
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "請先選類別"))
        self.assertFalse(Product.objects.filter(name="甲 新皮套 A1").exists())

    def test_pasted_accessories_are_counted_by_quantity_and_get_a_sku(self):
        before = Category.objects.get(pk=self.cat.pk).next_sku_seq
        preview = self.paste([{"品名": "甲 新皮套 A1", "規格": "黑", "建議售價": "390"}])
        self.assertEqual((preview["dry_run"], preview["success_count"]), (True, 1))
        self.assertFalse(Product.objects.filter(name="甲 新皮套 A1").exists())
        self.assertEqual(Category.objects.get(pk=self.cat.pk).next_sku_seq, before)    # 預覽不吃號

        done = self.paste([{"品名": "甲 新皮套 A1", "規格": "黑", "建議售價": "390"}], dry_run="false")
        self.assertEqual(done["success_count"], 1)
        p = Product.objects.get(name="甲 新皮套 A1")
        self.assertEqual((p.requires_serial, p.spec, p.category_id, int(p.list_price)), (False, "黑", self.cat.id, 390))
        self.assertTrue(p.sku.startswith(f"{self.cat.code}-"))

    def test_the_serial_choice_is_what_gets_saved(self):
        self.paste([{"品名": "甲 高價耳機 Z"}], requires_serial="true", allows_commission="true", dry_run="false")
        p = Product.objects.get(name="甲 高價耳機 Z")
        self.assertEqual((p.requires_serial, p.allows_commission), (True, True))

    def test_rows_naming_a_device_or_unknown_category_are_skipped_and_no_category_is_made(self):
        out = self.paste([
            {"品名": "甲 某手機", "類別": "手機"},
            {"品名": "甲 某配件", "類別": "打錯的類別"},
            {"品名": "甲 另一個皮套", "類別": "LC"},
            {"品名": ""},
        ], dry_run="false")
        reasons = {r["name"]: r["reason"] for r in out["skip_rows"]}
        self.assertIn("手機型號", reasons["甲 某手機"])
        self.assertEqual(reasons["甲 某配件"], "類別「打錯的類別」不存在")
        self.assertEqual(reasons[""], "沒有品名")
        self.assertEqual([r["row_no"] for r in out["skip_rows"]], [1, 2, 4])
        self.assertEqual(out["success_count"], 1)
        self.assertFalse(Category.objects.filter(tenant=self.c.tenant, name="打錯的類別").exists())

    def test_a_file_without_sku_and_the_old_paste_template_both_work(self):
        csv = (
            "品名,規格,建議售價,類別\n"                 # 以前「批次貼上」下載的範例檔
            "甲 原廠保護貼,iPhone 15 Pro,490,皮套\n"
        ).encode("utf-8-sig")
        f = io.BytesIO(csv)
        f.name = "範例.csv"
        r = self.post({"file": f, "category": self.cat.id, "requires_serial": "false", "dry_run": "false"}, fmt="multipart")
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.assertEqual((r.json()["success_count"], r.json()["skip_count"]), (1, 0))
        p = Product.objects.get(name="甲 原廠保護貼")
        self.assertEqual((p.spec, p.requires_serial), ("iPhone 15 Pro", False))

    def test_rows_sent_as_a_json_string_in_a_form_are_read_too(self):
        r = self.post({"rows": json.dumps([{"品名": "甲 表單送來的"}]), "category": self.cat.id,
                       "requires_serial": "false", "dry_run": "false"}, fmt="multipart")
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.assertTrue(Product.objects.filter(name="甲 表單送來的").exists())
        r = self.post({"rows": "不是表格", "category": self.cat.id, "requires_serial": "false"}, fmt="multipart")
        self.assertEqual(r.status_code, 400)

    def test_prices_with_thousands_separators_are_read_and_unreadable_ones_are_skipped(self):
        # Codex 複審 P1:Excel 複製出來的「1,290」以前會默默存成售價 0
        out = self.paste([
            {"品名": "甲 千分位", "建議售價": "1,290"},
            {"品名": "甲 有小數", "建議售價": "390.6"},
            {"品名": "甲 看不懂", "建議售價": "洽詢"},
            {"品名": "甲 負的", "建議售價": "-5"},
            {"品名": "甲 安全庫存錯", "安全庫存": "三個"},
        ], dry_run="false")
        self.assertEqual({r["name"]: r["list_price"] for r in out["success_rows"]}, {"甲 千分位": 1290, "甲 有小數": 391})
        reasons = {r["name"]: r["reason"] for r in out["skip_rows"]}
        self.assertEqual(reasons["甲 看不懂"], "建議售價「洽詢」看不懂")
        self.assertEqual(reasons["甲 負的"], "建議售價「-5」看不懂")
        self.assertEqual(reasons["甲 安全庫存錯"], "安全庫存「三個」看不懂")
        self.assertEqual(int(Product.objects.get(name="甲 千分位").list_price), 1290)
        self.assertFalse(Product.objects.filter(name__in=["甲 看不懂", "甲 負的", "甲 安全庫存錯"]).exists())
