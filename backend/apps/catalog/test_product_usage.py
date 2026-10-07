"""用過的商品不能改會影響庫存怎麼算的屬性(需追蹤序號 / 中古機 / 虛擬商品);沒用過的照舊隨便改。規則在 `catalog/usage.py`。"""
import threading
import time
import warnings

from django.db import connections
from django.test import SimpleTestCase, TestCase, TransactionTestCase

from apps.backup.tests.factory import Company
from apps.catalog.models import Category, Product
from apps.catalog.usage import (
    StockFlagsLocked,
    category_cascade_blockers,
    flags_after_save,
    product_usage,
    save_arguments,
    used_product_ids,
)
from apps.inventory.models import StockBalance

IMEI_A = "490154203237518"
IMEI_B = "356938035643809"


class FlagsAfterSaveTests(SimpleTestCase):
    """存檔之後三個屬性實際的值(`Product.save` 與存檔前的檢查用同一份)。"""

    def flags(self, **kw):
        base = dict(category_secondhand=False, is_secondhand=False, requires_serial=False, is_virtual=False)
        return flags_after_save(**{**base, **kw})

    def test_plain_product_keeps_what_was_asked(self):
        self.assertEqual(self.flags(), {"is_secondhand": False, "requires_serial": False, "is_virtual": False})
        self.assertEqual(self.flags(requires_serial=True)["requires_serial"], True)
        self.assertEqual(self.flags(is_virtual=True)["is_virtual"], True)

    def test_secondhand_always_tracks_serials_and_is_never_virtual(self):
        self.assertEqual(self.flags(is_secondhand=True, is_virtual=True),
                         {"is_secondhand": True, "requires_serial": True, "is_virtual": False})

    def test_secondhand_category_makes_the_product_secondhand(self):
        self.assertEqual(self.flags(category_secondhand=True),
                         {"is_secondhand": True, "requires_serial": True, "is_virtual": False})


class SaveArgumentsTests(SimpleTestCase):
    """這一次 `save()` 會寫哪些欄位(None = 全部),以及要往下傳的那一份參數(全部換成關鍵字)。"""

    def test_keyword_positional_and_none(self):
        self.assertEqual(save_arguments((), {}), (None, {}))
        self.assertEqual(save_arguments((), {"update_fields": None}), (None, {"update_fields": None}))
        self.assertEqual(save_arguments((), {"update_fields": ["name"]})[0], frozenset({"name"}))
        self.assertEqual(save_arguments((), {"update_fields": []})[0], frozenset())     # 空的 = 什麼都不寫
        # 照位置給:save(force_insert, force_update, using, update_fields)
        self.assertEqual(
            save_arguments((False, True, "x", ["list_price"]), {}),
            (frozenset({"list_price"}),
             {"force_insert": False, "force_update": True, "using": "x", "update_fields": frozenset({"list_price"})}),
        )
        self.assertEqual(save_arguments((False, False, None, []), {})[0], frozenset())  # 照位置給空的也一樣
        self.assertIsNone(save_arguments((False, False, None, None), {})[0])
        self.assertEqual(save_arguments((True, False), {}), (None, {"force_insert": True, "force_update": False}))
        self.assertEqual(save_arguments((), {"using": "x"}), (None, {"using": "x"}))    # 別的關鍵字原樣留著

    def test_what_is_passed_on_can_be_read_again(self):
        """人家給的是只能看一次的產生器:往下傳的要是整理過的那一份,不是已經被看完的那一個。"""
        fields, kwargs = save_arguments((), {"update_fields": (f for f in ["name", "spec"]), "using": "x"})
        self.assertEqual(fields, frozenset({"name", "spec"}))
        self.assertEqual(kwargs, {"update_fields": frozenset({"name", "spec"}), "using": "x"})
        fields, kwargs = save_arguments((True, False, "x", iter(["name"])), {})
        self.assertEqual(fields, frozenset({"name"}))
        self.assertEqual(kwargs["update_fields"], frozenset({"name"}))

    def test_the_callers_own_dict_is_left_alone(self):
        given = {"update_fields": ["name"]}
        save_arguments((True,), given)
        self.assertEqual(given, {"update_fields": ["name"]})

    def test_position_and_keyword_together_follow_djangos_rule(self):
        """位置與關鍵字同時給:關鍵字是預設值 → 用照位置給的;不是預設值 → 重複給了,丟錯(跟 Django 一樣)。"""
        fields, kwargs = save_arguments((False, False, None, ["name"]), {"update_fields": None})
        self.assertEqual(fields, frozenset({"name"}))
        self.assertEqual(kwargs["update_fields"], frozenset({"name"}))
        self.assertEqual(save_arguments((False, False, None, iter([])), {"update_fields": None})[0], frozenset())
        self.assertEqual(save_arguments((True,), {"force_insert": False})[1], {"force_insert": True})
        with self.assertRaisesRegex(TypeError, "multiple values for argument 'update_fields'"):
            save_arguments((False, False, None, ["name"]), {"update_fields": ["spec"]})
        with self.assertRaisesRegex(TypeError, "multiple values for argument 'force_insert'"):
            save_arguments((False,), {"force_insert": True})
        with self.assertRaisesRegex(TypeError, "but 6 were given"):
            save_arguments((False, False, None, None, "多的"), {})

    def test_same_answer_as_django_itself(self):
        """拿 Django 自己對回名字的那一段來對(6.0 拿掉照位置給參數之後,這個比對就沒有東西可比了)。"""
        parse = getattr(Product, "_parse_params", None)
        if parse is None:
            self.skipTest("這一版 Django 已經不收照位置給的參數")
        defaults = {"force_insert": False, "force_update": False, "using": None, "update_fields": None}
        positional = [(), (True,), (False, True), (False, False, "x"), (False, False, None, ("name",)),
                      (False, False, None, None), (False, False, None, ()), (1, 2, 3, ("a",), 5)]
        keywords = [{}, {"update_fields": None}, {"update_fields": ("spec",)}, {"force_insert": True},
                    {"force_insert": False, "using": None}, {"using": "y"}, {"force_update": True, "update_fields": ()}]
        compared = 0
        for args in positional:
            for kwargs in keywords:
                theirs = ours = None
                if args:
                    try:
                        with warnings.catch_warnings():
                            warnings.simplefilter("ignore")
                            theirs = parse(Product(), *args, method_name="save", **{**defaults, **kwargs})
                    except TypeError:
                        theirs = TypeError
                else:
                    theirs = list({**defaults, **kwargs}.values())
                try:
                    named = {**defaults, **save_arguments(args, kwargs)[1]}
                    ours = [named[k] for k in defaults]
                except TypeError:
                    ours = TypeError
                if theirs is not TypeError and theirs[3] is not None:
                    theirs[3] = frozenset(theirs[3])
                self.assertEqual(ours, theirs, (args, kwargs))
                compared += 1
        self.assertEqual(compared, 56)


def _locks(queries, table):
    return [q["sql"] for q in queries if "FOR NO KEY UPDATE" in q["sql"] and f'FROM "{table}"' in q["sql"]]


def _category_locks(queries):
    return _locks(queries, "catalog_category")


def _product_locks(queries):
    return _locks(queries, "catalog_product")


def _position(queries, wanted):
    """第一個符合的查詢排第幾個(沒有就丟錯)。"""
    return next(i for i, q in enumerate(queries) if wanted(q["sql"]))


class ProductUsageTests(TestCase):
    def setUp(self):
        self.c = Company("a", "甲通訊行", "甲")
        self.hq, self.branch = self.c.warehouses

    # ── 小工具 ──
    def patch(self, product, **body):
        return self.c.admin.patch(f"/api/v1/products/{product.id}/", body, format="json")

    def flags_of(self, product):
        p = Product.objects.get(pk=product.pk)
        return (p.requires_serial, p.is_secondhand, p.is_virtual)

    def void(self, kind, doc):
        r = self.c.admin.post(f"/api/v1/{kind}/{doc['id']}/void/")
        self.assertEqual(r.status_code, 200, r.content.decode())

    def usage_api(self, product, client=None):
        return (client or self.c.admin).get(f"/api/v1/products/{product.id}/usage/")

    # ── 沒用過:照舊隨便改 ──
    def test_unused_product_can_change_every_flag(self):
        self.assertEqual(product_usage(self.c.case).reasons, ())
        r = self.patch(self.c.case, requires_serial=True)
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.assertEqual(self.flags_of(self.c.case), (True, False, False))
        r = self.patch(self.c.case, requires_serial=False, is_virtual=True)
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.assertEqual(self.flags_of(self.c.case), (False, False, True))
        r = self.patch(self.c.case, is_virtual=False, is_secondhand=True)
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.assertEqual(self.flags_of(self.c.case), (True, True, False))   # 中古機一定追蹤序號
        body = self.usage_api(self.c.case).json()
        self.assertEqual((body["locked"], body["reasons"]), (False, []))
        self.assertEqual(body["fields"], ["requires_serial", "is_secondhand", "is_virtual"])

    # ── 用過:三個屬性都不能改,其他欄位照舊 ──
    def test_accessory_with_stock_cannot_become_serial_tracked(self):
        self.c.purchase(case_qty=5)
        r = self.patch(self.c.case, requires_serial=True)
        self.assertEqual(r.status_code, 400, r.content.decode())
        detail = str(r.json()["detail"])
        self.assertIn("「需追蹤序號」不能改", detail)
        self.assertIn("1 張進貨單", detail)
        self.assertIn("庫存 5 件", detail)
        self.assertIn("作廢", detail)                                     # 有講出路
        self.assertEqual(self.flags_of(self.c.case), (False, False, False))

    def test_each_flag_is_refused_on_a_used_product(self):
        self.c.purchase(case_qty=5)
        for body, label in (({"is_virtual": True}, "虛擬商品"),
                            ({"is_secondhand": True}, "中古機")):
            r = self.patch(self.c.case, **body)
            self.assertEqual(r.status_code, 400, (body, r.content.decode()))
            self.assertIn(f"「{label}」", str(r.json()["detail"]))
        self.assertEqual(self.flags_of(self.c.case), (False, False, False))

    def test_serial_tracked_phone_with_units_cannot_become_quantity_based(self):
        self.c.purchase(phone_serials=[IMEI_A, IMEI_B])
        r = self.patch(self.c.phone, requires_serial=False)
        self.assertEqual(r.status_code, 400, r.content.decode())
        self.assertIn("2 台序號", str(r.json()["detail"]))
        self.assertEqual(self.flags_of(self.c.phone)[0], True)

    def test_other_fields_stay_editable_on_a_used_product(self):
        self.c.purchase(case_qty=5)
        r = self.patch(self.c.case, name="改過的品名 透明殼", spec="霧面", list_price="490")
        self.assertEqual(r.status_code, 200, r.content.decode())
        # 三個屬性原樣送回去(表單每次都整份送)也不算改
        r = self.patch(self.c.case, requires_serial=False, is_secondhand=False, is_virtual=False,
                       list_price="590")
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.assertEqual(str(Product.objects.get(pk=self.c.case.pk).list_price), "590.00")

    def test_sold_out_is_still_used(self):
        """賣到庫存 0 也算用過:那張銷貨單之後還可能作廢 / 退貨,要照原本的記法加回去。"""
        self.c.purchase(case_qty=2)
        self.c.sell(case_qty=2)
        self.assertEqual(StockBalance.objects.get(product=self.c.case, warehouse=self.hq).qty, 0)
        usage = product_usage(self.c.case)
        self.assertEqual(usage.reasons, ("1 張進貨單", "1 張銷貨單"))
        self.assertEqual(self.patch(self.c.case, requires_serial=True).status_code, 400)

    # ── 出路:把單作廢、庫存歸零就可以改 ──
    def test_voiding_the_documents_unlocks_the_product(self):
        po = self.c.purchase(case_qty=2)
        so = self.c.sell(case_qty=1)
        self.assertEqual(self.patch(self.c.case, requires_serial=True).status_code, 400)
        self.void("sales-orders", so)
        self.assertEqual(self.patch(self.c.case, requires_serial=True).status_code, 400)   # 進貨單還在
        self.void("purchase-orders", po)
        self.assertEqual(product_usage(self.c.case).reasons, ())
        # 庫存那一筆還在、只是數量回到 0:一次查一批的那一支(類別連動用的)也要說它沒用過
        self.assertEqual(StockBalance.objects.get(product=self.c.case, warehouse=self.hq).qty, 0)
        self.assertEqual(used_product_ids([self.c.case.pk]), set())
        r = self.patch(self.c.case, requires_serial=True)
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.assertEqual(self.flags_of(self.c.case), (True, False, False))

    def test_voided_serials_do_not_count(self):
        po = self.c.purchase(phone_serials=[IMEI_A])
        self.void("purchase-orders", po)
        self.assertEqual(product_usage(self.c.phone).reasons, ())
        self.assertEqual(self.patch(self.c.phone, requires_serial=False).status_code, 200)

    def test_transfer_in_transit_counts(self):
        self.c.purchase(case_qty=4)
        r = self.c.admin.post("/api/v1/transfer-orders/", {
            "from_warehouse": self.hq.id, "to_warehouse": self.branch.id,
            "items": [{"product": self.c.case.id, "qty": 4}],
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content.decode())
        # 派發之後來源門市數量是 0、目的門市還沒加上:帳上沒有庫存,但那張調撥單還要確認
        reasons = product_usage(self.c.case).reasons
        self.assertIn("1 張調撥單", reasons)
        self.assertEqual(self.patch(self.c.case, requires_serial=True).status_code, 400)

    # ── 其他幾種「用過」 ──
    def test_returned_goods_still_count(self):
        """整張銷退之後庫存回來了,但那張銷退單還可能被作廢(東西又算賣出去):還是用過。"""
        self.c.purchase(case_qty=2)
        so = self.c.sell(case_qty=1)
        self.c._post("/api/v1/sales-returns/", {"original_so": so["id"], "payment_method": "cash"})
        self.assertEqual(product_usage(self.c.case).reasons,
                         ("1 張進貨單", "1 張銷貨單", "1 張銷退單", "庫存 2 件"))

    def test_repair_parts_count_until_the_repair_is_voided(self):
        import datetime

        from apps.repairs.models import RepairOrder, RepairOrderPart

        order = RepairOrder.objects.create(tenant=self.c.tenant, customer=self.c.customer,
                                           received_date=datetime.date(2026, 10, 7), warehouse=self.hq)
        RepairOrderPart.objects.create(tenant=self.c.tenant, repair_order=order,
                                       part_product=self.c.case, qty=1)
        self.assertEqual(product_usage(self.c.case).reasons, ("1 張維修單",))
        self.assertEqual(self.patch(self.c.case, requires_serial=True).status_code, 400)
        RepairOrder.objects.filter(pk=order.pk).update(is_void=True)
        self.assertEqual(product_usage(self.c.case).reasons, ())

    def test_pending_intake_counts_but_cancelled_or_posted_does_not(self):
        from apps.identity.models import IntakeBatch, IntakeItem

        batch = IntakeBatch.objects.create(tenant=self.c.tenant)
        IntakeItem.objects.create(tenant=self.c.tenant, batch=batch, line_no=1, raw_text="透明殼 x2",
                                  matched_product=self.c.case)
        self.assertEqual(batch.status, IntakeBatch.Status.OPEN)
        self.assertEqual(product_usage(self.c.case).reasons, ("1 筆待確認入庫",))
        self.assertEqual(self.patch(self.c.case, requires_serial=True).status_code, 400)
        for status in (IntakeBatch.Status.RESOLVED,):
            IntakeBatch.objects.filter(pk=batch.pk).update(status=status)
            self.assertTrue(product_usage(self.c.case).locked, status)
        # 取消了、或已經過帳(過帳的那一張算在進貨單那一項):這一項不算
        for status in (IntakeBatch.Status.CANCELLED, IntakeBatch.Status.COMMITTED):
            IntakeBatch.objects.filter(pk=batch.pk).update(status=status)
            self.assertEqual(product_usage(self.c.case).reasons, (), status)

    def test_another_products_documents_do_not_count(self):
        self.c.purchase(phone_serials=[IMEI_A])                            # 只進了手機
        self.assertEqual(product_usage(self.c.case).reasons, ())
        self.assertEqual(self.patch(self.c.case, requires_serial=True).status_code, 200)

    # ── 換類別連帶變成中古機 ──
    def secondhand_category(self):
        return Category.objects.create(tenant=self.c.tenant, code="SH", name="中古機",
                                       is_secondhand_default=True)

    def test_moving_a_used_product_into_a_secondhand_category_is_refused(self):
        cat = self.secondhand_category()
        self.c.purchase(case_qty=1)
        before = Product.objects.get(pk=self.c.case.pk).category_id
        r = self.patch(self.c.case, category=cat.id)
        self.assertEqual(r.status_code, 400, r.content.decode())
        self.assertIn("「需追蹤序號」、「中古機」不能改", str(r.json()["detail"]))
        p = Product.objects.get(pk=self.c.case.pk)
        self.assertEqual((p.category_id, p.is_secondhand), (before, False))

    def test_moving_an_unused_product_into_a_secondhand_category_still_works(self):
        cat = self.secondhand_category()
        r = self.patch(self.c.case, category=cat.id)
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.assertEqual(self.flags_of(self.c.case), (True, True, False))

    def test_moving_a_used_product_between_ordinary_categories_is_fine(self):
        other = Category.objects.create(tenant=self.c.tenant, code="ZZ", name="別的類別")
        self.c.purchase(case_qty=1)
        r = self.patch(self.c.case, category=other.id)
        self.assertEqual(r.status_code, 200, r.content.decode())
        p = Product.objects.get(pk=self.c.case.pk)
        self.assertEqual(p.category_id, other.id)
        self.assertEqual(p.sku, self.c.case.sku)                          # 品號不跟著類別變

    # ── 類別勾「中古機類別」(會把底下所有商品一起改) ──
    def tick_secondhand(self, category):
        return self.c.admin.patch(f"/api/v1/categories/{category.id}/",
                                  {"is_secondhand_default": True}, format="json")

    def test_category_cannot_become_secondhand_while_used_products_would_change(self):
        cat = Product.objects.get(pk=self.c.case.pk).category
        self.c.purchase(case_qty=1)
        r = self.tick_secondhand(cat)
        self.assertEqual(r.status_code, 400, r.content.decode())
        message = str(r.json()["detail"])
        self.assertIn("不能勾「中古機類別」", message)
        self.assertIn(f"「{self.c.case.name}」", message)
        self.assertEqual(Category.objects.get(pk=cat.pk).is_secondhand_default, False)
        self.assertEqual(self.flags_of(self.c.case), (False, False, False))

    def test_category_can_become_secondhand_when_nothing_used_would_change(self):
        cat = Category.objects.create(tenant=self.c.tenant, code="NW", name="新類別")
        fresh = Product.objects.create(tenant=self.c.tenant, category=cat, name="還沒用過的東西",
                                       requires_serial=False)
        r = self.tick_secondhand(cat)
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.assertEqual(self.flags_of(fresh), (True, True, False))        # 連動照舊

    def test_products_already_secondhand_do_not_block_the_category(self):
        cat = Category.objects.create(tenant=self.c.tenant, code="OK", name="本來就都是中古的類別")
        used = Product.objects.create(tenant=self.c.tenant, category=cat, name="中古 iPhone 12",
                                      is_secondhand=True, requires_serial=True)
        self.c._post("/api/v1/purchase-orders/", {
            "supplier": self.c.supplier.id, "warehouse": self.hq.id, "tax_method": "untaxed",
            "items": [{"product": used.id, "qty": 1, "unit_price": "8000",
                       "serial_numbers": [{"imei": IMEI_A, "sn": ""}]}],
        })
        self.assertTrue(product_usage(used).locked)
        self.assertEqual(list(category_cascade_blockers(cat)), [])
        self.assertEqual(self.tick_secondhand(cat).status_code, 200)

    # ── 不走畫面那條路的也過不去(模型自己的最後一道) ──
    def test_model_save_refuses_too(self):
        self.c.purchase(case_qty=3)
        p = Product.objects.get(pk=self.c.case.pk)
        p.requires_serial = True
        with self.assertRaises(StockFlagsLocked) as caught:
            p.save()
        self.assertIn("庫存 3 件", str(caught.exception))
        self.assertEqual(self.flags_of(self.c.case), (False, False, False))

    def test_saving_only_other_columns_is_not_checked(self):
        """只寫別的欄位的存檔(進貨更新加權平均成本)不會動到那三個屬性:照過,而且不多查、不鎖類別。"""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        self.c.purchase(case_qty=3)
        p = Product.objects.get(pk=self.c.case.pk)
        p.requires_serial = True                                           # 記憶體裡被改了,但沒有要寫
        with CaptureQueriesContext(connection) as seen:
            p.save(update_fields=["weighted_avg_cost"])
        # 兩次查詢 = 原本就有的「看類別是不是中古機類別」+ 寫入;沒有多出「用過沒有」的那幾個查詢,也沒有鎖
        self.assertEqual(len(seen), 2, [q["sql"][:60] for q in seen])
        self.assertEqual(_category_locks(seen) + _product_locks(seen), [])
        self.assertEqual(self.flags_of(self.c.case), (False, False, False))

    # ── 只存部分欄位:只比這一次真的會寫進去的 ──
    def test_partial_save_ignores_flags_it_does_not_write(self):
        self.c.purchase(case_qty=3)
        p = Product.objects.get(pk=self.c.case.pk)
        p.is_virtual = True                                                # 只改了記憶體,這次不寫
        p.list_price = 990
        p.save(update_fields=["requires_serial", "list_price"])            # 有寫的那一格沒變:不算改
        fresh = Product.objects.get(pk=p.pk)
        self.assertEqual((fresh.requires_serial, fresh.is_secondhand, fresh.is_virtual), (False, False, False))
        self.assertEqual(str(fresh.list_price), "990.00")

    def test_partial_save_that_really_writes_a_changed_flag_is_refused(self):
        self.c.purchase(case_qty=3)
        p = Product.objects.get(pk=self.c.case.pk)
        p.requires_serial = True
        with self.assertRaises(StockFlagsLocked):
            p.save(update_fields=["requires_serial"])
        self.assertEqual(self.flags_of(self.c.case), (False, False, False))

    def test_category_partial_save_without_the_flag_neither_cascades_nor_blocks(self):
        cat = Product.objects.get(pk=self.c.case.pk).category
        self.c.purchase(case_qty=1)
        cat.is_secondhand_default = True                                   # 只改了記憶體
        cat.name = "改過名字的類別"
        cat.save(update_fields=["name"])                                   # 沒有要寫那一格:不連動、不擋
        cat.save(update_fields=[])                                         # 什麼都不寫
        fresh = Category.objects.get(pk=cat.pk)
        self.assertEqual((fresh.name, fresh.is_secondhand_default), ("改過名字的類別", False))
        self.assertEqual(self.flags_of(self.c.case), (False, False, False))

    # ── 類別改成中古機類別 與 商品移進這個類別:排隊做,而且看的是類別現在的設定 ──
    def test_product_save_reads_the_category_as_it_is_now(self):
        """另一個請求剛把這個類別改成中古機類別(已經提交),這一邊記憶體裡那一份還是舊的:存檔時要看現在的。"""
        cat = Category.objects.create(tenant=self.c.tenant, code="RC", name="會變的類別")
        self.c.purchase(case_qty=1)
        p = Product.objects.get(pk=self.c.case.pk)
        original = p.category_id
        p.category = cat                                                   # 記憶體裡這一份:不是中古機類別
        Category.objects.filter(pk=cat.pk).update(is_secondhand_default=True)   # 對方提交了
        with self.assertRaises(StockFlagsLocked):
            p.save()
        fresh = Product.objects.get(pk=p.pk)
        self.assertEqual((fresh.category_id, fresh.is_secondhand), (original, False))

    def test_staying_in_a_category_that_became_secondhand_follows_it(self):
        """沒有換類別也一樣看類別**現在**的設定(記憶體裡那一份是舊的):沒用過的跟著變中古機,用過的擋下來。"""
        p = Product.objects.get(pk=self.c.case.pk)
        self.assertEqual(p.category.is_secondhand_default, False)          # 記憶體裡這一份:不是中古機類別
        Category.objects.filter(pk=p.category_id).update(is_secondhand_default=True)   # 對方提交了
        p.name = "跟著類別變中古"
        p.save()
        self.assertEqual(self.flags_of(p), (True, True, False))
        used = Product.objects.get(pk=self.c.phone.pk)
        self.c.purchase(phone_serials=[IMEI_A])
        Category.objects.filter(pk=used.category_id).update(is_secondhand_default=True)
        used.name = "用過的不能被連帶改"
        with self.assertRaises(StockFlagsLocked):
            used.save()
        self.assertEqual(self.flags_of(used), (True, False, False))

    def test_both_paths_take_the_same_category_lock(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        cat = Category.objects.create(tenant=self.c.tenant, code="LK", name="要鎖的類別")
        p = Product.objects.get(pk=self.c.case.pk)
        with CaptureQueriesContext(connection) as moved:
            p.category = cat
            p.save()
        with CaptureQueriesContext(connection) as ticked:
            cat.is_secondhand_default = True
            cat.save()
        self.assertEqual(len(_category_locks(moved)), 1)                   # 商品移進這個類別
        self.assertEqual(len(_category_locks(ticked)), 1)                  # 類別改成中古機類別
        self.assertIn(f"= {cat.pk}", _category_locks(moved)[0])            # 鎖的是要移進去的那一個
        self.assertEqual(self.flags_of(self.c.case), (True, True, False))  # 沒用過的商品照舊被連帶改
        # 兩邊都是先類別、後商品(方向相反就會互等)
        for seen in (moved, ticked):
            category = _position(seen, lambda sql: sql in _category_locks(seen))
            product = _position(seen, lambda sql: sql in _product_locks(seen))
            self.assertLess(category, product, [q["sql"][:70] for q in seen])

    def test_saving_without_moving_takes_no_category_lock(self):
        """只改品名、售價:不拿類別的鎖(不然兩批跨類別的批次修改會互等),只鎖商品自己這一列。"""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        p = Product.objects.get(pk=self.c.case.pk)
        p.name = "改過名字的殼"
        with CaptureQueriesContext(connection) as seen:
            p.save()
        self.assertEqual(_category_locks(seen), [])
        self.assertEqual(len(_product_locks(seen)), 1, [q["sql"][:70] for q in seen])
        self.assertIn(f'"id" = {p.pk}', _product_locks(seen)[0])
        # 鎖到之後才寫
        self.assertLess(_position(seen, lambda sql: sql in _product_locks(seen)),
                        _position(seen, lambda sql: sql.startswith('UPDATE "catalog_product"')))
        # 只寫類別那一格、但類別沒變:一樣不拿類別的鎖
        with CaptureQueriesContext(connection) as same:
            p.save(update_fields=["category"])
        self.assertEqual(_category_locks(same), [])
        # 記憶體裡換了類別、但這一次沒有要寫類別那一格:商品不會被移過去,也就不拿那個類別的鎖
        original = p.category_id
        p.category = Category.objects.create(tenant=self.c.tenant, code="NW", name="沒有要寫進去的類別")
        with CaptureQueriesContext(connection) as unwritten:
            p.save(update_fields=["requires_serial"])
        self.assertEqual(_category_locks(unwritten), [])
        self.assertEqual(Product.objects.get(pk=p.pk).category_id, original)

    def test_flags_are_compared_with_the_row_as_locked(self):
        """沒鎖的時候讀到的那一份可能已經過時(對方剛改完):有沒有變,比的是鎖到的那一份。"""
        from unittest import mock

        from apps.catalog import usage

        self.c.purchase(case_qty=1)
        real = usage.stored_flags

        def stale_until_locked(product, *, lock=False):
            row = real(product, lock=lock)
            return row if lock else {**row, "requires_serial": True}       # 沒鎖時看到的:好像已經是序號制

        p = Product.objects.get(pk=self.c.case.pk)
        p.requires_serial = True
        with mock.patch("apps.catalog.usage.stored_flags", side_effect=stale_until_locked):
            with self.assertRaises(StockFlagsLocked):
                p.save()
        self.assertEqual(self.flags_of(self.c.case), (False, False, False))

    def test_moved_away_by_someone_else_in_between_still_takes_the_category_lock(self):
        """沒鎖時讀到「本來就在這個類別」、鎖到時已經被別人移走:這一次存檔等於移回來,要拿那個類別的鎖。"""
        from unittest import mock

        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        from apps.catalog import usage

        target = Category.objects.create(tenant=self.c.tenant, code="BK", name="要移回來的類別")
        real = usage.stored_flags

        def stale_until_locked(product, *, lock=False):
            row = real(product, lock=lock)
            return row if lock else {**row, "category_id": target.pk}      # 沒鎖時看到的:還在這個類別

        p = Product.objects.get(pk=self.c.case.pk)
        p.category = target
        with mock.patch("apps.catalog.usage.stored_flags", side_effect=stale_until_locked):
            with CaptureQueriesContext(connection) as seen:
                p.save()
        self.assertEqual(len(_category_locks(seen)), 1, [q["sql"][:70] for q in seen])
        self.assertIn(f"= {target.pk}", _category_locks(seen)[0])
        self.assertEqual(Product.objects.get(pk=p.pk).category_id, target.pk)

    def test_cascade_locks_every_product_in_the_category_first(self):
        """類別連帶改商品:先照編號把底下**全部**的商品鎖住(本來就是中古機的也鎖 —— 可能正有人在把它改成不是),
        才看哪些用過、才改。跟進貨鎖商品同一個順序。"""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        cat = Category.objects.create(tenant=self.c.tenant, code="CS", name="要變中古的類別")
        plain = [Product.objects.create(tenant=self.c.tenant, category=cat, name=f"一般 {n}", requires_serial=False)
                 for n in range(3)]
        already = Product.objects.create(tenant=self.c.tenant, category=cat, name="本來就是中古",
                                         is_secondhand=True, requires_serial=True)
        cat.is_secondhand_default = True
        with CaptureQueriesContext(connection) as seen:
            cat.save()
        locks = _product_locks(seen)
        self.assertEqual(len(locks), 1, [q["sql"][:70] for q in seen])
        self.assertIn(f'WHERE "catalog_product"."category_id" = {cat.pk} ORDER BY "catalog_product"."id" ASC', locks[0])
        self.assertNotIn("is_secondhand", locks[0].split("WHERE")[1])       # 沒有挑,整個類別都鎖
        at = _position(seen, lambda sql: sql in locks)
        self.assertLess(_position(seen, lambda sql: sql in _category_locks(seen)), at)            # 先類別
        self.assertLess(at, _position(seen, lambda sql: "purchasing_purchaseorderitem" in sql))   # 鎖了才看用過沒有
        self.assertLess(at, _position(seen, lambda sql: sql.startswith('UPDATE "catalog_category"')))
        self.assertLess(at, _position(seen, lambda sql: sql.startswith('UPDATE "catalog_product"')))
        for p in plain + [already]:
            self.assertEqual(self.flags_of(p), (True, True, False))

    # ── update_fields 給的是只能看一次的產生器 ──
    def test_update_fields_given_as_a_generator_still_saves(self):
        p = Product.objects.get(pk=self.c.case.pk)
        p.name = "用產生器存的品名"
        p.save(update_fields=(f for f in ["name"]))
        self.assertEqual(Product.objects.get(pk=p.pk).name, "用產生器存的品名")
        cat = p.category
        cat.name = "用產生器存的類別"
        cat.save(update_fields=(f for f in ["name"]))
        self.assertEqual(Category.objects.get(pk=cat.pk).name, "用產生器存的類別")
        # 空的產生器 = 什麼都不寫(不是出錯)
        p.name = "不會被存"
        p.save(update_fields=(f for f in []))
        self.assertEqual(Product.objects.get(pk=p.pk).name, "用產生器存的品名")

    def test_update_fields_given_as_a_generator_is_still_checked(self):
        self.c.purchase(case_qty=1)
        p = Product.objects.get(pk=self.c.case.pk)
        p.requires_serial = True
        with self.assertRaises(StockFlagsLocked):
            p.save(update_fields=(f for f in ["requires_serial"]))
        cat = p.category
        cat.is_secondhand_default = True
        with self.assertRaises(StockFlagsLocked):
            cat.save(update_fields=(f for f in ["is_secondhand_default"]))
        self.assertEqual(self.flags_of(self.c.case), (False, False, False))
        self.assertEqual(Category.objects.get(pk=cat.pk).is_secondhand_default, False)

    def test_position_with_the_keyword_left_at_none_writes_only_what_was_listed(self):
        """`save(False, False, None, ["name"], update_fields=None)`:Django 只寫 name,這裡的檢查也只能當它寫 name。"""
        self.c.purchase(case_qty=1)
        p = Product.objects.get(pk=self.c.case.pk)
        cat = p.category
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")                                # 照位置給參數是舊寫法,會有提醒
            p.requires_serial = True                                       # 只改了記憶體,這次沒有要寫
            p.name = "修改後名稱"
            p.save(False, False, None, ["name"], update_fields=None)
            p.name = "不會被存"
            p.save(False, False, None, iter([]), update_fields=None)       # 空的:什麼都不寫,不是出錯
            cat.is_secondhand_default = True                               # 只改了記憶體
            cat.name = "只改名字的類別"
            cat.save(False, False, None, ["name"], update_fields=None)
            with self.assertRaises(TypeError):
                p.save(False, False, None, ["name"], update_fields=["spec"])   # 重複給:跟 Django 一樣是寫錯了
        fresh = Product.objects.get(pk=p.pk)
        self.assertEqual((fresh.name, fresh.requires_serial), ("修改後名稱", False))
        self.assertEqual(Category.objects.filter(pk=cat.pk).values_list("name", "is_secondhand_default").get(),
                         ("只改名字的類別", False))

    def test_update_fields_given_by_position_as_a_generator(self):
        cat = Category.objects.create(tenant=self.c.tenant, code="PG", name="照位置給的類別")
        fresh = Product.objects.create(tenant=self.c.tenant, category=cat, name="照位置存", requires_serial=False)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")                                # 照位置給參數是舊寫法,會有提醒
            fresh.name = "照位置存好了"
            fresh.save(False, False, None, iter(["name"]))
            cat.is_secondhand_default = True
            cat.save(False, False, None, iter(["is_secondhand_default"]))
        self.assertEqual(Product.objects.get(pk=fresh.pk).name, "照位置存好了")
        self.assertEqual(Category.objects.get(pk=cat.pk).is_secondhand_default, True)
        self.assertEqual(self.flags_of(fresh), (True, True, False))        # 有寫那一格:照樣連帶改

    def test_refusal_found_only_at_save_time_is_still_a_400(self):
        """先擋的那一次過了、存檔時鎖著類別再看才發現不行(同一時間類別被改成中古機類別):一樣回 400,不是 500。"""
        from unittest import mock

        other = Category.objects.create(tenant=self.c.tenant, code="RX", name="同時被改的類別")
        self.c.purchase(case_qty=1)
        with mock.patch("apps.catalog.usage.lock_category", return_value=True):
            r = self.patch(self.c.case, category=other.id)
        self.assertEqual(r.status_code, 400, r.content.decode())
        self.assertIn("不能改", str(r.json()["detail"]))
        self.assertEqual(self.flags_of(self.c.case), (False, False, False))

    def test_category_model_save_refuses_too(self):
        cat = Product.objects.get(pk=self.c.case.pk).category
        self.c.purchase(case_qty=1)
        cat.is_secondhand_default = True
        with self.assertRaises(StockFlagsLocked):
            cat.save()
        self.assertEqual(Category.objects.get(pk=cat.pk).is_secondhand_default, False)
        self.assertEqual(self.flags_of(self.c.case), (False, False, False))

    # ── 批次修改 ──
    def test_bulk_edit_reports_the_used_product_and_changes_nothing(self):
        fresh = Product.objects.create(tenant=self.c.tenant, category=self.c.case.category,
                                       name="還沒用過的殼", requires_serial=False)
        self.c.purchase(case_qty=1)
        r = self.c.admin.post("/api/v1/products/bulk-edit/",
                              {"ids": [self.c.case.id, fresh.id], "patch": {"requires_serial": True}},
                              format="json")
        self.assertEqual(r.status_code, 400, r.content.decode())
        errors = r.json()["errors"]
        self.assertEqual([e["id"] for e in errors], [self.c.case.id])
        self.assertIn("不能改", str(errors[0]["errors"]))
        # 整批復原:沒用過的那一個也沒有被改
        self.assertEqual(self.flags_of(fresh), (False, False, False))
        self.assertEqual(self.flags_of(self.c.case), (False, False, False))

    def test_bulk_edit_locks_the_category_first_and_products_in_id_order(self):
        """批次修改把商品移進別的類別:動任何商品之前先拿好那個類別的鎖;商品照編號一個一個來(不是照品號)。"""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        target = Category.objects.create(tenant=self.c.tenant, code="ZT", name="要移進去的類別")
        early = Category.objects.create(tenant=self.c.tenant, code="0A", name="品號排最前面的類別")
        late = Product.objects.create(tenant=self.c.tenant, category=early, name="編號最大、品號最前",
                                      requires_serial=False)
        ids = sorted([self.c.case.id, self.c.phone.id, late.id])
        self.assertEqual(Product.objects.filter(pk__in=ids).first().pk, late.pk)   # 照品號排它在最前面
        # 編號最小的那一個本來就在那個類別(它自己不用拿類別的鎖):鎖還是要在碰它之前就拿好
        Product.objects.filter(pk=ids[0]).update(category=target)
        with CaptureQueriesContext(connection) as seen:
            r = self.c.admin.post("/api/v1/products/bulk-edit/",
                                  {"ids": ids, "patch": {"category": target.id}}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.assertEqual(set(Product.objects.filter(pk__in=ids).values_list("category_id", flat=True)), {target.id})
        products = _product_locks(seen)
        self.assertEqual([next(i for i in ids if f'"id" = {i} ' in sql) for sql in products], ids)
        self.assertIn(f"= {target.id}", _category_locks(seen)[0])
        self.assertLess(_position(seen, lambda sql: sql in _category_locks(seen)),
                        _position(seen, lambda sql: sql in products))

    def test_bulk_edit_with_a_category_that_is_not_ours_is_a_400(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        other = Company("b", "乙通訊行", "乙")
        theirs = other.case.category_id
        original = Product.objects.get(pk=self.c.case.pk).category_id
        for value in (theirs, 99999999, "abc", None, [1], True):
            with CaptureQueriesContext(connection) as seen:
                r = self.c.admin.post("/api/v1/products/bulk-edit/",
                                      {"ids": [self.c.case.id], "patch": {"category": value}}, format="json")
            self.assertEqual(r.status_code, 400, (value, r.content.decode()))
            if value is not True:                                          # True 會被當成編號 1,鎖不鎖都無妨
                self.assertEqual(_category_locks(seen), [], value)         # 別家的、亂填的:不去鎖
        self.assertEqual(Product.objects.get(pk=self.c.case.pk).category_id, original)

    # ── 編輯表單打開時問的 ──
    def test_usage_endpoint_says_where_it_was_used(self):
        self.c.purchase(phone_serials=[IMEI_A, IMEI_B], case_qty=5)
        self.c.sell(serial_no=IMEI_A, case_qty=2)
        phone, case = self.usage_api(self.c.phone).json(), self.usage_api(self.c.case).json()
        self.assertEqual((phone["locked"], phone["reasons"]),
                         (True, ["1 張進貨單", "1 張銷貨單", "2 台序號"]))
        self.assertEqual((case["locked"], case["reasons"]),
                         (True, ["1 張進貨單", "1 張銷貨單", "庫存 3 件"]))
        self.assertIn("作廢", case["way_out"])

    def test_stock_without_any_document_points_to_the_only_way_out(self):
        """舊資料匯入的庫存沒有單可以作廢:不能叫人「先把這些單作廢」。"""
        StockBalance.objects.create(tenant=self.c.tenant, product=self.c.case, warehouse=self.hq, qty=7)
        usage = product_usage(self.c.case)
        self.assertEqual((usage.reasons, usage.has_documents), (("庫存 7 件",), False))
        r = self.patch(self.c.case, requires_serial=True)
        self.assertEqual(r.status_code, 400, r.content.decode())
        detail = str(r.json()["detail"])
        self.assertIn("停用這個品號", detail)
        self.assertNotIn("作廢", detail)
        self.assertNotIn("作廢", self.usage_api(self.c.case).json()["way_out"])
        # 沒用過的商品沒有「怎麼辦」可講
        self.assertEqual(self.usage_api(self.c.phone).json()["way_out"], "")

    def test_serials_without_any_document_also_have_nothing_to_void(self):
        from apps.inventory.identifiers import create_serial

        create_serial(tenant=self.c.tenant, product=self.c.phone, warehouse=self.hq, imei=IMEI_A)
        usage = product_usage(self.c.phone)
        self.assertEqual((usage.reasons, usage.has_documents), (("1 台序號",), False))

    def test_stock_is_added_up_across_stores(self):
        StockBalance.objects.create(tenant=self.c.tenant, product=self.c.case, warehouse=self.hq, qty=3)
        StockBalance.objects.create(tenant=self.c.tenant, product=self.c.case, warehouse=self.branch, qty=4)
        self.assertEqual(product_usage(self.c.case).reasons, ("庫存 7 件",))

    def test_saving_a_second_object_with_the_same_id_is_checked_too(self):
        self.c.purchase(case_qty=1)
        original = Product.objects.get(pk=self.c.case.pk)
        clone = Product(**{f.attname: getattr(original, f.attname) for f in Product._meta.concrete_fields})
        self.assertTrue(clone._state.adding)                               # 剛 new 出來的,但編號是既有的那一筆
        clone.requires_serial = True
        with self.assertRaises(StockFlagsLocked):
            clone.save()
        self.assertEqual(self.flags_of(self.c.case), (False, False, False))

    def test_usage_endpoint_is_read_only_and_per_company(self):
        other = Company("b", "乙通訊行", "乙")
        self.assertEqual(self.usage_api(self.c.case, client=other.admin).status_code, 404)
        self.assertEqual(self.c.admin.post(f"/api/v1/products/{self.c.case.id}/usage/").status_code, 405)

    def test_used_ids_in_bulk_match_one_by_one(self):
        fresh = Product.objects.create(tenant=self.c.tenant, category=self.c.case.category,
                                       name="還沒用過的殼", requires_serial=False)
        self.c.purchase(phone_serials=[IMEI_A], case_qty=1)
        ids = used_product_ids(Product.objects.filter(tenant=self.c.tenant).values("pk"))
        self.assertEqual(ids, {self.c.phone.id, self.c.case.id})
        self.assertNotIn(fresh.id, ids)


class TwoPeopleAtOnceTests(TransactionTestCase):
    """真的兩條連線同時做(「另一個人」用另一條連線:鎖住、改掉、停一下才提交)。
    這一邊的動作必須等他做完、看到他改過的結果才做 —— 規則都是「先鎖、鎖到之後才看」,只看發出去的查詢驗不到「真的有等」。"""

    def setUp(self):
        self.c = Company("a", "甲通訊行", "甲")

    def flags_of(self, product):
        return Product.objects.filter(pk=product.pk).values_list(
            "requires_serial", "is_secondhand", "is_virtual").get()

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

    def test_cascade_waits_for_a_save_on_a_product_it_would_not_have_changed(self):
        """類別要改成中古機類別的同時,有人正把底下一個**本來就是中古機**的商品改成不是(存到一半):
        連帶改要等他存完、再把那個商品帶回中古機。只鎖「現在看起來要改的」就不會等,最後類別是中古機類別、底下卻有一個不是。"""
        cat = Category.objects.create(tenant=self.c.tenant, code="CW", name="要變中古的類別")
        p = Product.objects.create(tenant=self.c.tenant, category=cat, name="本來是中古",
                                   is_secondhand=True, requires_serial=True)
        t = self.meanwhile([
            ("SELECT 1 FROM catalog_product WHERE id = %s FOR NO KEY UPDATE", [p.pk]),
            ("UPDATE catalog_product SET is_secondhand = false, requires_serial = false WHERE id = %s", [p.pk]),
        ])
        cat.is_secondhand_default = True
        cat.save()
        t.join()
        self.assertTrue(Category.objects.get(pk=cat.pk).is_secondhand_default)
        self.assertEqual(self.flags_of(p), (True, True, False))

    def test_save_waits_for_a_cascade_and_does_not_write_the_old_flags_back(self):
        """商品存檔(沒換類別)的同時,類別正被改成中古機類別、連帶改到這個商品(還沒提交):
        存檔要等它提交、照改完的樣子存;不能拿等之前讀到的「不是中古機」寫回去。"""
        p = Product.objects.get(pk=self.c.case.pk)                         # 記憶體裡這一份:不是中古機
        cat_id = p.category_id
        t = self.meanwhile([
            ("SELECT 1 FROM catalog_category WHERE id = %s FOR NO KEY UPDATE", [cat_id]),
            ("UPDATE catalog_category SET is_secondhand_default = true WHERE id = %s", [cat_id]),
            ("SELECT 1 FROM catalog_product WHERE id = %s FOR NO KEY UPDATE", [p.pk]),
            ("UPDATE catalog_product SET is_secondhand = true, requires_serial = true, is_virtual = false "
             "WHERE id = %s", [p.pk]),
        ])
        p.name = "同時被改名"
        p.save()
        t.join()
        self.assertEqual(Product.objects.get(pk=p.pk).name, "同時被改名")
        self.assertEqual(self.flags_of(p), (True, True, False))

    def test_moving_in_waits_for_the_category_being_ticked(self):
        """把用過的商品移進一個類別的同時,那個類別正被改成中古機類別(還沒提交):
        要等它提交、看到它現在是中古機類別 → 擋下來。不等的話讀到的是「還不是」,就移進去了。"""
        self.c.purchase(case_qty=1)
        target = Category.objects.create(tenant=self.c.tenant, code="MV", name="正在變中古的類別")
        t = self.meanwhile([
            ("SELECT 1 FROM catalog_category WHERE id = %s FOR NO KEY UPDATE", [target.pk]),
            ("UPDATE catalog_category SET is_secondhand_default = true WHERE id = %s", [target.pk]),
        ])
        p = Product.objects.get(pk=self.c.case.pk)
        original = p.category_id
        p.category = target                                                # 記憶體裡這一份:還不是中古機類別
        with self.assertRaises(StockFlagsLocked):
            p.save()
        t.join()
        self.assertEqual(Product.objects.get(pk=p.pk).category_id, original)
        self.assertEqual(self.flags_of(p), (False, False, False))

    def test_ticking_the_category_waits_for_a_product_being_moved_in(self):
        """把類別改成中古機類別的同時,有人正把一個用過的商品移進來(還沒提交):
        要等他移完、看到底下有用過的商品 → 擋下來。不等的話檢查時看不到它,改完之後它卻在裡面。"""
        self.c.purchase(case_qty=1)
        target = Category.objects.create(tenant=self.c.tenant, code="MW", name="有人正移進來的類別")
        t = self.meanwhile([
            ("SELECT 1 FROM catalog_category WHERE id = %s FOR NO KEY UPDATE", [target.pk]),
            ("UPDATE catalog_product SET category_id = %s WHERE id = %s", [target.pk, self.c.case.pk]),
        ])
        target.is_secondhand_default = True
        with self.assertRaises(StockFlagsLocked):
            target.save()
        t.join()
        self.assertFalse(Category.objects.get(pk=target.pk).is_secondhand_default)
        self.assertEqual(Product.objects.get(pk=self.c.case.pk).category_id, target.pk)
        self.assertEqual(self.flags_of(self.c.case), (False, False, False))
