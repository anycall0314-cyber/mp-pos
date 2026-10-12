"""用店內品名叫貨(交接包 V1)。跑法:manage.py test apps.vendor_orders.test_internal

owner(交接包 §2):日常叫貨顯示自家的品名、以自家商品為主;廠商的品名 / 料號只拿來核對與送給廠商;
沒連的廠商品項不擋已經連好的;同一個店內商品可以連好幾家廠商,各記各的。

要守住的:叫貨清單上的「店內商品」跟對照分頁 / 到貨入庫是同一套查法;**送給廠商的內容一個字不變**;
畫面看到的對照跟現在的不一樣就不送(不能畫面寫 P、存下來是 Q);叫貨單記的是當時的,之後對照怎麼改、商品怎麼改名都不動它。
"""
from django.db import connection

from apps.backup.tests.factory import Company
from apps.catalog.models import Product, SupplierProduct

from .models import VendorItem, VendorLink, VendorOrder, VendorOrderItem
from .test_manual import _Manual
from .test_mapping import _Linking
from .tests import CATALOG, KEY, LINKS, ORDERS

MAPPINGS = "/api/v1/vendor-orders/mappings/"


def internal(order: dict) -> list:
    return [(i["sku"], i["product"], i["product_sku"], i["product_name"]) for i in order["items"]]


class CatalogTests(_Linking):
    """全自動的廠商(假的膜總裁)。`_Linking` 開場已經叫過一張 G02(還沒有任何對照的時候)。"""

    def catalog(self, client=None):
        r = (client or self.clerk).get(CATALOG)
        self.assertEqual(r.status_code, 200, r.content.decode())
        return {row["key"]: row for row in r.json()["rows"]}

    def test_every_row_says_which_store_product_it_is_linked_to(self):
        self.assertEqual({row["product"] for row in self.catalog().values()}, {None})       # 還沒連:全部是空的
        self.assertEqual(self.set().status_code, 200)                                        # G02 → 甲 高透亮面保護貼
        self.assertEqual(self.set("M01#902", self.film2).status_code, 200)
        rows = self.catalog()
        self.assertEqual(rows["G02"]["product"],
                         {"id": self.film.id, "sku": self.film.sku, "name": self.film.name, "is_active": True})
        self.assertEqual((rows["M01#902"]["product"]["id"], rows["M01#901"]["product"], rows["G01"]["product"]),
                         (self.film2.id, None, None))
        # 廠商自己的品名、料號、包裝、價錢照舊(核對與送單用)
        self.assertEqual((rows["G02"]["name"], rows["G02"]["sku"], rows["G02"]["pack_qty"], rows["G02"]["unit_price"]),
                         ("高透亮面", "G02", 25, "150.00"))

    def test_it_is_the_same_answer_as_the_mapping_page(self):
        self.assertEqual(self.set().status_code, 200)
        self.assertEqual(self.set("G01", self.film2).status_code, 200)
        self.assertEqual({key: row["product"] for key, row in self.catalog().items()},
                         {key: row["product"] for key, row in self.by_key().items()})

    def test_a_product_switched_off_is_still_named_and_marked(self):
        self.assertEqual(self.set().status_code, 200)
        Product.objects.filter(pk=self.film.pk).update(is_active=False)
        self.assertEqual(self.catalog()["G02"]["product"],
                         {"id": self.film.id, "sku": self.film.sku, "name": self.film.name, "is_active": False})

    def test_another_company_sees_only_its_own_links(self):
        self.assertEqual(self.set().status_code, 200)
        other = Company("b", "乙通訊行", "乙")
        body = {"warehouse": other.warehouses[0].id, "vendor": "moceo", "key": KEY, "ship_name": "乙店",
                "ship_phone": "035550000", "ship_address": "新竹市某路 2 號", "invoice_email": "b@b.com"}
        self.assertEqual(other.admin.post(LINKS, body, format="json").status_code, 200)
        rows = other.clerk.get(CATALOG).json()["rows"]
        self.assertEqual({row["product"] for row in rows}, {None})


class OrderSnapshotTests(_Linking):
    def setUp(self):
        super().setUp()
        self.assertEqual(self.set().status_code, 200)                                        # G02 → film
        self.vendor.calls.clear()

    def buy(self, lines, key="draft-v001", **extra):
        return self.order(lines, key=key, **extra)

    def test_the_order_remembers_the_store_product_of_each_line(self):
        r = self.buy([{"key": "G02", "packs": 2, "was": self.film.id}, {"key": "G01", "packs": 1, "was": None}])
        self.assertEqual(r.status_code, 201, r.content.decode())
        self.assertEqual(internal(r.json()), [("G02", self.film.id, self.film.sku, "甲 高透亮面保護貼"), ("G01", None, "", "")])
        saved = list(VendorOrderItem.objects.filter(order_id=r.json()["id"]).order_by("line_no")
                     .values_list("sku", "product_id", "product_sku", "product_name"))
        self.assertEqual(saved, [("G02", self.film.id, self.film.sku, "甲 高透亮面保護貼"), ("G01", None, "", "")])
        # 廠商的品名、包裝照舊記著
        self.assertEqual([(i["name"], i["pack_qty"], i["qty"]) for i in r.json()["items"]],
                         [("高透亮面", 25, 50), ("D3O 7H", 10, 10)])

    def test_what_goes_to_the_vendor_is_exactly_what_it_was(self):
        r = self.buy([{"key": "G02", "packs": 2, "was": self.film.id}, {"key": "M01#901", "packs": 3, "was": None}])
        self.assertEqual(r.status_code, 201, r.content.decode())
        sent = self.vendor.posts()[0][3]
        self.assertEqual(sent["items"], [{"sku": "G02", "spec_id": None, "qty": 50}, {"sku": "M01", "spec_id": 901, "qty": 15}])
        self.assertNotIn("甲 高透亮面保護貼", str(sent))                                      # 店內的品名不會送出去
        self.assertNotIn(self.film.sku, str(sent))
        self.assertEqual(sorted(sent), ["delivery_method", "idempotency_key", "invoice", "items", "payment_method", "ship_to"])

    def test_a_screen_that_says_nothing_about_links_still_works(self):
        """舊畫面(沒有帶 `was`)送來的:照現在的對照記,不擋。"""
        r = self.buy([{"key": "G02", "packs": 1}])
        self.assertEqual(r.status_code, 201, r.content.decode())
        self.assertEqual(internal(r.json()), [("G02", self.film.id, self.film.sku, "甲 高透亮面保護貼")])

    def test_the_order_made_before_any_link_stays_blank(self):
        """開場那一張是在連之前叫的:不拿現在的對照回頭去填。"""
        first = self.clerk.get(f"{ORDERS}{self.o['id']}/").json()
        self.assertEqual(internal(first), [("G02", None, "", "")])

    def test_later_changes_do_not_rewrite_the_order(self):
        made = self.buy([{"key": "G02", "packs": 2, "was": self.film.id}]).json()
        self.assertEqual(self.set("G02", self.film2).status_code, 200)                       # 對照改到另一個商品
        Product.objects.filter(pk=self.film.pk).update(name="甲 改過名字的膜")                # 原本那個商品也改名了
        again = self.clerk.get(f"{ORDERS}{made['id']}/").json()
        self.assertEqual(internal(again), [("G02", self.film.id, self.film.sku, "甲 高透亮面保護貼")])
        listed = next(o for o in self.clerk.get(ORDERS).json()["results"] if o["id"] == made["id"])
        self.assertEqual(internal(listed), internal(again))
        # 之後再叫的照新的對照
        newer = self.buy([{"key": "G02", "packs": 1, "was": self.film2.id}], key="draft-v002").json()
        self.assertEqual(internal(newer), [("G02", self.film2.id, self.film2.sku, "甲 D3O 保護貼")])

    def test_a_link_changed_behind_the_screen_is_not_sent(self):
        before = VendorOrder.objects.count()
        cases = [
            # (畫面上看到的, 訊息裡要有的)
            (self.film2.id, "畫面上是「甲 D3O 保護貼」,現在是「甲 高透亮面保護貼」"),        # 畫面是舊的對照
            (None, "畫面上是沒有對照,現在是「甲 高透亮面保護貼」"),                          # 畫面載入之後才有人連上
        ]
        for n, (was, said) in enumerate(cases):
            r = self.buy([{"key": "G01", "packs": 1, "was": None}, {"key": "G02", "packs": 2, "was": was}], key=f"draft-s{n:03d}")
            self.assertEqual(r.status_code, 400, r.content.decode())
            detail = r.json()["detail"]
            self.assertIn("「高透亮面」連到的店內商品剛剛被改了", detail)                     # 講的是哪一項(廠商的品名)
            self.assertIn(said, detail)
            self.assertIn("數量都還在", detail)
        # 被解除了
        self.assertEqual(self.set("G02", None).status_code, 200)
        r = self.buy([{"key": "G02", "packs": 2, "was": self.film.id}], key="draft-s009")
        self.assertEqual(r.status_code, 400, r.content.decode())
        self.assertIn("畫面上是「甲 高透亮面保護貼」,現在是沒有對照", r.json()["detail"])
        self.assertEqual(VendorOrder.objects.count(), before)                                # 一張都沒成立
        self.assertEqual(self.vendor.posts(), [])                                            # 也沒有送給廠商

    def test_the_same_key_again_returns_the_order_that_was_made(self):
        """已經成立的那一張:同一把鑰匙再來(回應沒回來、重新整理)照樣回它,不因為之後對照改了就說不行。"""
        lines = [{"key": "G02", "packs": 2, "was": self.film.id}]
        made = self.buy(lines).json()
        self.assertEqual(self.set("G02", self.film2).status_code, 200)
        r = self.buy(lines)
        self.assertEqual((r.status_code, r.json()["id"]), (200, made["id"]), r.content.decode())
        self.assertEqual(internal(r.json()), [("G02", self.film.id, self.film.sku, "甲 高透亮面保護貼")])
        self.assertEqual(len(self.vendor.posts()), 1)

    def test_what_the_screen_claims_must_be_a_product_number_or_nothing(self):
        for bad in ("12", True, 1.5, [self.film.id], {"id": self.film.id}):
            r = self.buy([{"key": "G02", "packs": 1, "was": bad}], key="draft-b001")
            self.assertEqual((r.status_code, r.json()["detail"]), (400, "商品不對"), (bad, r.content.decode()))
        self.assertEqual(self.vendor.posts(), [])

    def test_another_companys_product_number_is_just_a_mismatch(self):
        other = Company("b", "乙通訊行", "乙")
        theirs = Product.objects.create(tenant=other.tenant, category=other.cat_case, name="乙家的秘密商品", requires_serial=False)
        r = self.buy([{"key": "G02", "packs": 1, "was": theirs.id}])
        self.assertEqual(r.status_code, 400, r.content.decode())
        self.assertNotIn("乙家的秘密商品", r.json()["detail"])                                # 別家公司的品名不會被講出來
        self.assertIn("畫面上是沒有對照,現在是「甲 高透亮面保護貼」", r.json()["detail"])


class RollOutTests(_Linking):
    def test_a_line_written_by_the_program_from_before_still_goes_in(self):
        """上線是「先改資料庫、打包前端、才重啟程式」:中間那一兩分鐘跑的還是舊程式,它新增明細時不知道有店內商品那三格 ——
        資料庫要自己補空的,不能讓那時候叫的貨整張失敗。"""
        old = VendorOrderItem.objects.get(order_id=self.o["id"])
        table = connection.ops.quote_name(VendorOrderItem._meta.db_table)
        unknown = {"id", "product_id", "product_sku", "product_name"}
        cols = ", ".join(connection.ops.quote_name(f.column) for f in VendorOrderItem._meta.concrete_fields
                         if f.column not in unknown)
        with connection.cursor() as cur:
            cur.execute(f"INSERT INTO {table} ({cols}) SELECT {cols} FROM {table} WHERE id = %s", [old.id])
        new = VendorOrderItem.objects.order_by("-id").first()
        self.assertNotEqual(new.id, old.id)
        self.assertEqual((new.sku, new.product_id, new.product_sku, new.product_name), ("G02", None, "", ""))
        # 舊程式寫的那一張照樣讀得出來
        self.assertEqual(self.clerk.get(f"{ORDERS}{self.o['id']}/").status_code, 200)


class SeveralVendorsTests(_Manual):
    """半自動的兩家:乙配件(`20W 充電頭` 一包 5 個)、丁零件(`丁家的充電頭` 一包 10 個)都連到店裡同一個「甲 20W 充電頭」。"""

    def setUp(self):
        super().setUp()
        VendorItem.objects.create(vendor=self.gamma, sku="H50", name="丁家的充電頭", unit="個", pack_qty=10, ref_price=70)
        self.assertEqual(self.open().status_code, 200)
        self.assertEqual(self.admin.post(LINKS, {"warehouse": self.wh1.id, "vendor": "gamma", "opened": True,
                                                 "ship_name": "甲湳雅店", "ship_phone": "035551234",
                                                 "ship_address": "新竹市湳雅街 1 號"}, format="json").status_code, 200)
        self.tie("acme", "H01", self.head)
        self.tie("gamma", "H50", self.head)

    def tie(self, vendor, key, product):
        r = self.clerk.post(MAPPINGS, {"warehouse": self.wh1.id, "vendor": vendor, "key": key,
                                       "product": product.id if product else None}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())

    def rows(self, vendor):
        r = self.clerk.get(f"{CATALOG}?vendor={vendor}")
        self.assertEqual(r.status_code, 200, r.content.decode())
        return {row["key"]: row for row in r.json()["rows"]}

    def test_one_store_product_at_two_vendors_each_with_its_own_pack(self):
        a, b = self.rows("acme"), self.rows("gamma")
        self.assertEqual((a["H01"]["product"]["name"], a["H01"]["pack_qty"], a["H01"]["name"]), ("甲 20W 充電頭", 5, "20W 充電頭"))
        self.assertEqual((b["H50"]["product"]["name"], b["H50"]["pack_qty"], b["H50"]["name"]), ("甲 20W 充電頭", 10, "丁家的充電頭"))
        # 各叫 2 包:店內都是同一個商品,個數是 10 與 20
        one = self.buy([{"key": "H01", "packs": 2, "was": self.head.id}], key="draft-a001")
        two = self.clerk.post(ORDERS, {"request_key": "draft-g001", "warehouse": self.wh1.id, "vendor": "gamma",
                                       "lines": [{"key": "H50", "packs": 2, "was": self.head.id}]}, format="json")
        self.assertEqual((one.status_code, two.status_code), (201, 201), (one.content.decode(), two.content.decode()))
        self.assertEqual([(i["product_name"], i["name"], i["packs"], i["qty"]) for i in one.json()["items"]],
                         [("甲 20W 充電頭", "20W 充電頭", 2, 10)])
        self.assertEqual([(i["product_name"], i["name"], i["packs"], i["qty"]) for i in two.json()["items"]],
                         [("甲 20W 充電頭", "丁家的充電頭", 2, 20)])
        self.assertNothingWentOut()

    def test_changing_one_vendors_link_leaves_the_other_alone(self):
        self.tie("acme", "H01", self.cable)
        self.assertEqual(self.rows("acme")["H01"]["product"]["name"], "甲 快充線 1M")
        self.assertEqual(self.rows("gamma")["H50"]["product"]["name"], "甲 20W 充電頭")
        self.tie("acme", "H01", None)
        self.assertIsNone(self.rows("acme")["H01"]["product"])
        self.assertEqual(self.rows("gamma")["H50"]["product"]["name"], "甲 20W 充電頭")
        # 兩家各自的入庫供應商、各自的對照
        suppliers = dict(VendorLink.objects.filter(tenant=self.t).values_list("provider", "supplier_id"))
        self.assertNotEqual(suppliers["acme"], suppliers["gamma"])
        self.assertEqual(sorted(SupplierProduct.objects.filter(is_active=True).values_list("supplier_id", "vendor_sku", "product_id")),
                         [(suppliers["gamma"], "H50", self.head.id)])

    def test_items_that_are_not_linked_do_not_get_in_the_way(self):
        rows = self.rows("acme")
        self.assertEqual((rows["C01"]["product"], rows["C02"]["product"]), (None, None))     # 廠商另外有沒連的品項
        r = self.buy([{"key": "H01", "packs": 1, "was": self.head.id}], key="draft-a002")
        self.assertEqual(r.status_code, 201, r.content.decode())
        # 沒連的照樣可以叫(到貨時再連),記成沒有店內商品
        r = self.buy([{"key": "H01", "packs": 1, "was": self.head.id}, {"key": "C02", "packs": 3, "was": None}], key="draft-a003")
        self.assertEqual(r.status_code, 201, r.content.decode())
        self.assertEqual(internal(r.json()), [("H01", self.head.id, self.head.sku, "甲 20W 充電頭"), ("C02", None, "", "")])

    def test_the_text_for_the_vendor_uses_the_vendors_own_words(self):
        r = self.buy([{"key": "H01", "packs": 2, "was": self.head.id}], key="draft-a004")
        self.assertEqual(r.status_code, 201, r.content.decode())
        message = r.json()["message"]
        self.assertIn("20W 充電頭", message)
        self.assertNotIn("甲 20W 充電頭", message)                                            # 店內的叫法廠商看不懂
        self.assertNotIn(self.head.sku, message)

    def test_a_link_changed_behind_the_screen_is_not_placed(self):
        self.tie("acme", "H01", self.cable)
        before = VendorOrder.objects.count()
        r = self.buy([{"key": "C01", "packs": 1, "was": None}, {"key": "H01", "packs": 2, "was": self.head.id}], key="draft-a005")
        self.assertEqual(r.status_code, 400, r.content.decode())
        self.assertIn("「20W 充電頭」連到的店內商品剛剛被改了:畫面上是「甲 20W 充電頭」,現在是「甲 快充線 1M」", r.json()["detail"])
        self.assertEqual(VendorOrder.objects.count(), before)
        # 看過新的對照再送就可以
        r = self.buy([{"key": "C01", "packs": 1, "was": None}, {"key": "H01", "packs": 2, "was": self.cable.id}], key="draft-a005")
        self.assertEqual(r.status_code, 201, r.content.decode())
        self.assertEqual(internal(r.json())[1], ("H01", self.cable.id, self.cable.sku, "甲 快充線 1M"))
