"""標籤資料:印出來的東西要對得上那一台 / 那個商品 —— 條碼刷不到正確的東西、售價印成別台的、印到別家公司的都算錯。"""
from django.test import TestCase
from rest_framework.test import APIClient

from apps.backup.tests.factory import Company
from apps.catalog.models import Product
from apps.inventory.models import ProductSerial
from apps.sales.models import SalesOrder

URL = "/api/v1/labels/"
IMEI_A, IMEI_B = "356789012345671", "356789012345689"


class _Shop(TestCase):
    def setUp(self):
        self.c = Company("a", "甲通訊行", "甲")

    def labels(self, expect=200, client=None, **params):
        resp = (client or self.c.admin).get(URL, params)
        self.assertEqual(resp.status_code, expect, resp.content)
        return resp.json()

    def serial(self, code):
        return ProductSerial.objects.get(tenant=self.c.tenant, serial_no=code)


class PurchaseOrderLabelTests(_Shop):
    def test_one_label_per_unit_and_one_entry_per_accessory_line(self):
        po = self.c.purchase(phone_serials=(IMEI_A, IMEI_B), case_qty=3)
        data = self.labels(po=po["id"])
        self.assertEqual(data["source"], {"kind": "po", "no": po["no"]})
        units = [x for x in data["labels"] if x["serial_id"]]
        self.assertEqual([(x["code"], x["code_kind"], x["last5"], x["copies"]) for x in units],
                         [(IMEI_A, "serial", "45671", 1), (IMEI_B, "serial", "45689", 1)])
        self.assertEqual({(x["name"], x["sku"], x["price"], x["grade"]) for x in units},
                         {(self.c.phone.name, self.c.phone.sku, 25000, "")})
        self.assertEqual({(x["doc_no"], x["doc_date"]) for x in data["labels"]}, {(po["no"], po["doc_date"])})
        (case,) = [x for x in data["labels"] if not x["serial_id"]]
        # 配件沒有原廠條碼:條碼印品號;一行一筆,張數 = 進貨數量
        self.assertEqual((case["code"], case["code_kind"], case["copies"], case["price"], case["last5"]),
                         (self.c.case.sku, "sku", 3, 390, ""))
        self.assertEqual(len({x["key"] for x in data["labels"]}), 3)

    def test_accessory_with_a_maker_barcode_prints_that_barcode(self):
        Product.objects.filter(pk=self.c.case.pk).update(barcode=" 4710000123456 ")
        po = self.c.purchase(case_qty=1)
        (case,) = self.labels(po=po["id"])["labels"]
        self.assertEqual((case["code"], case["code_kind"]), ("4710000123456", "barcode"))

    def test_voided_purchase_order_and_voided_units_are_not_printed(self):
        po = self.c.purchase(phone_serials=(IMEI_A,), case_qty=1)
        r = self.c.admin.post(f"/api/v1/purchase-orders/{po['id']}/void/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIn("作廢", self.labels(400, po=po["id"])["detail"])
        self.labels(400, serials=str(self.serial(IMEI_A).id))       # 作廢的那一台也不能單獨印
        self.labels(400, po=999999)

    def test_a_purchase_line_with_many_pieces_is_capped_and_says_so(self):
        po = self.c.purchase(case_qty=900)
        data = self.labels(po=po["id"])
        self.assertEqual(data["labels"][0]["copies"], 500)
        self.assertEqual(len(data["notes"]), 1)
        self.assertIn("900", data["notes"][0])
        self.assertEqual(self.labels(po=self.c.purchase(case_qty=3)["id"])["notes"], [])

    def test_a_serial_line_with_fewer_printable_units_says_so(self):
        # 舊資料那一行沒有逐台的序號、或其中幾台已經作廢:少印了幾台要講,不能看起來像整張都印了
        po = self.c.purchase(phone_serials=(IMEI_A, IMEI_B))
        ProductSerial.objects.filter(pk=self.serial(IMEI_B).pk).update(status="void")
        data = self.labels(po=po["id"])
        self.assertEqual([x["code"] for x in data["labels"]], [IMEI_A])
        self.assertEqual(len(data["notes"]), 1)
        self.assertIn("進貨 2 台,可以印的只有 1 台", data["notes"][0])

    def test_a_purchase_order_with_too_many_units_is_refused(self):
        from unittest import mock

        from apps.inventory import labels as rules

        po = self.c.purchase(phone_serials=(IMEI_A, IMEI_B))
        with mock.patch.object(rules, "MAX_UNITS", 1):
            self.assertIn("分批", self.labels(400, po=po["id"])["detail"])
        self.assertEqual(len(self.labels(po=po["id"])["labels"]), 2)

    def test_unit_priced_products_print_that_units_own_price_and_grade(self):
        # 中古機:每一台自己的售價與成色;沒填個別售價的那一台退回建議售價
        po = self.c.purchase(phone_serials=(IMEI_A, IMEI_B))
        Product.objects.filter(pk=self.c.phone.pk).update(is_secondhand=True)
        ProductSerial.objects.filter(pk=self.serial(IMEI_A).pk).update(
            custom_unit_price=18500, condition_grade="A")
        ProductSerial.objects.filter(pk=self.serial(IMEI_B).pk).update(condition_grade="B")
        by_code = {x["code"]: x for x in self.labels(po=po["id"])["labels"]}
        self.assertEqual((by_code[IMEI_A]["price"], by_code[IMEI_A]["grade"]), (18500, "A"))
        self.assertEqual((by_code[IMEI_B]["price"], by_code[IMEI_B]["grade"]), (25000, "B"))
        # 個別售價是 0 或負的 = 沒填(銷貨開單帶價也是 > 0 才用):印建議售價,標籤跟結帳帶出來的價錢要一樣
        for unset in (0, -100):
            ProductSerial.objects.filter(pk=self.serial(IMEI_A).pk).update(custom_unit_price=unset)
            (label,) = self.labels(serials=str(self.serial(IMEI_A).id))["labels"]
            self.assertEqual(label["price"], 25000, unset)
        ProductSerial.objects.filter(pk=self.serial(IMEI_A).pk).update(custom_unit_price=18500)
        # 不是逐台定價的商品:那一台就算有個別售價、成色也不印(那是別的流程留下的)
        Product.objects.filter(pk=self.c.phone.pk).update(is_secondhand=False)
        by_code = {x["code"]: x for x in self.labels(po=po["id"])["labels"]}
        self.assertEqual((by_code[IMEI_A]["price"], by_code[IMEI_A]["grade"]), (25000, ""))

    def test_units_keep_their_own_codes_after_the_product_stops_tracking_serials(self):
        # 進貨之後商品被改成「不追序號」:這張單的每一台還是各印各的碼,不能全部變成同一個商品條碼
        po = self.c.purchase(phone_serials=(IMEI_A, IMEI_B))
        Product.objects.filter(pk=self.c.phone.pk).update(requires_serial=False)
        data = self.labels(po=po["id"])
        self.assertEqual([(x["code"], x["code_kind"], x["copies"]) for x in data["labels"]],
                         [(IMEI_A, "serial", 1), (IMEI_B, "serial", 1)])
        self.assertTrue(all(x["serial_id"] for x in data["labels"]))
        self.assertEqual(data["notes"], [])
        # 反過來:當初當配件進的(沒有逐台的設備),後來商品改成要追序號 —— 沒有碼可以印,要講
        Product.objects.filter(pk=self.c.case.pk).update(requires_serial=True)
        po2 = self.c_purchase_cases_before_flag(4)
        data = self.labels(po=po2)
        self.assertEqual(data["labels"], [])
        self.assertIn("進貨 4 台,可以印的只有 0 台", data["notes"][0])

    def c_purchase_cases_before_flag(self, qty):
        """配件當初是不追序號進的貨:先把旗標關掉進貨,再打開(模擬事後改設定)。"""
        Product.objects.filter(pk=self.c.case.pk).update(requires_serial=False)
        po = self.c.purchase(case_qty=qty)
        Product.objects.filter(pk=self.c.case.pk).update(requires_serial=True)
        return po["id"]

    def test_opened_box_products_also_print_each_units_own_price_and_grade(self):
        # 逐台定價不只中古機:品況是「已拆封」(要逐台記機況)的商品也是
        from apps.catalog.models import Condition

        opened = Condition.objects.create(
            tenant=self.c.tenant, code="opened", name="已拆封", tracks_unit_condition=True)
        po = self.c.purchase(phone_serials=(IMEI_A,))
        Product.objects.filter(pk=self.c.phone.pk).update(condition=opened, is_secondhand=False)
        ProductSerial.objects.filter(pk=self.serial(IMEI_A).pk).update(
            custom_unit_price=21900, condition_grade="S")
        (label,) = self.labels(po=po["id"])["labels"]
        self.assertEqual((label["price"], label["grade"]), (21900, "S"))

    def test_no_price_is_printed_when_there_is_none(self):
        Product.objects.filter(pk=self.c.case.pk).update(list_price=0)
        po = self.c.purchase(case_qty=1)
        self.assertIsNone(self.labels(po=po["id"])["labels"][0]["price"])
        Product.objects.filter(pk=self.c.case.pk).update(list_price="0.40")      # 四捨五入是 0:一樣不印
        self.assertIsNone(self.labels(po=po["id"])["labels"][0]["price"])
        Product.objects.filter(pk=self.c.case.pk).update(list_price=-5)
        self.assertIsNone(self.labels(po=po["id"])["labels"][0]["price"])


class ReprintTests(_Shop):
    def test_units_are_printed_in_the_order_asked(self):
        po = self.c.purchase(phone_serials=(IMEI_A, IMEI_B))
        a, b = self.serial(IMEI_A), self.serial(IMEI_B)
        data = self.labels(serials=f"{b.id},{a.id},{b.id}")
        self.assertEqual([x["code"] for x in data["labels"]], [IMEI_B, IMEI_A])     # 重複的只印一張
        self.assertEqual(data["labels"][0]["doc_no"], po["no"])
        self.labels(400, serials=f"{a.id},999999")
        self.labels(400, serials="abc")
        # 全形數字、長到資料庫放不下的編號:好好講格式不對,不是出錯
        for bad in ("１２３", "²", "9" * 30):
            self.labels(400, serials=bad)
            self.labels(400, po=bad)
            self.labels(400, product=bad, copies=1)
        self.labels(400, product=self.c.case.id, copies="１")
        # 一次太多台:講的是「太多」,不是「找不到」(不然是靠後面那一關剛好擋下來的)
        self.assertIn("最多", self.labels(400, serials=",".join(str(n) for n in range(1, 400)))["detail"])

    def test_spaces_around_a_units_code_are_not_part_of_the_code(self):
        self.c.purchase(phone_serials=(IMEI_A,))
        unit = self.serial(IMEI_A)
        ProductSerial.objects.filter(pk=unit.pk).update(serial_no=f"  {IMEI_A} ")
        (label,) = self.labels(serials=str(unit.id))["labels"]
        self.assertEqual((label["code"], label["last5"]), (IMEI_A, "45671"))

    def test_a_unit_bought_from_a_person_shows_that_buy_back_document(self):
        self.c.purchase(phone_serials=(IMEI_A,), case_qty=2)
        so = SalesOrder.objects.get(pk=self.c.sell(case_qty=1)["id"])
        ProductSerial.objects.filter(pk=self.serial(IMEI_A).pk).update(
            purchase_order_item=None, acquired_via_sales_order=so)
        (label,) = self.labels(serials=str(self.serial(IMEI_A).id))["labels"]
        self.assertEqual((label["doc_no"], label["doc_date"]), (so.no, so.doc_date.isoformat()))
        # 兩個來源都不知道:不印、不猜
        ProductSerial.objects.filter(pk=self.serial(IMEI_A).pk).update(acquired_via_sales_order=None)
        (label,) = self.labels(serials=str(self.serial(IMEI_A).id))["labels"]
        self.assertEqual((label["doc_no"], label["doc_date"]), ("", ""))

    def test_accessory_reprint_by_count(self):
        (label,) = self.labels(product=self.c.case.id, copies=12)["labels"]
        self.assertEqual((label["code"], label["copies"], label["price"], label["doc_no"]),
                         (self.c.case.sku, 12, 390, ""))
        self.assertEqual(self.labels(product=self.c.case.id)["labels"][0]["copies"], 1)   # 沒講張數 = 1 張
        for bad in ("0", "501", "abc", "-3", "1.5"):
            self.labels(400, product=self.c.case.id, copies=bad)
        # 有序號的商品要選哪一台
        self.assertIn("哪一台", self.labels(400, product=self.c.phone.id, copies=1)["detail"])
        # 虛擬商品(手續費、折抵)沒有東西可以貼
        Product.objects.filter(pk=self.c.case.pk).update(is_virtual=True)
        self.assertIn("虛擬", self.labels(400, product=self.c.case.id, copies=1)["detail"])
        Product.objects.filter(pk=self.c.case.pk).update(is_virtual=False)
        self.labels(400, product=999999)

    def test_exactly_one_kind_of_request(self):
        po = self.c.purchase(case_qty=1)
        self.labels(400)
        self.labels(400, po=po["id"], product=self.c.case.id)


class WhoCanPrintTests(_Shop):
    def test_other_company_cannot_print_ours(self):
        po = self.c.purchase(phone_serials=(IMEI_A,), case_qty=1)
        other = Company("b", "乙通訊行", "乙")
        self.labels(400, client=other.admin, po=po["id"])
        self.labels(400, client=other.admin, serials=str(self.serial(IMEI_A).id))
        self.labels(400, client=other.admin, product=self.c.case.id, copies=1)

    def test_store_clerk_can_print(self):
        # 標籤上的東西庫存查詢本來就看得到:鎖門市的店員一樣能印(含別家門市進的貨調過來要貼的)
        po = self.c.purchase(warehouse=self.c.warehouses[1], phone_serials=(IMEI_A,))
        self.assertEqual(len(self.labels(client=self.c.clerk, po=po["id"])["labels"]), 1)

    def test_login_required(self):
        self.assertIn(APIClient().get(URL, {"product": self.c.case.id}).status_code, (401, 403))
