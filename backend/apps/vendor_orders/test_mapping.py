"""品名連連看:廠商的品項 ↔ 店內商品。跑法:manage.py test apps.vendor_orders.test_mapping

owner 2026-10-10:「店內品名A=供應商品名甲,指定好之後,後續下訂,只需收貨,即可直接入庫」;沒有對應的可以當場建、店員都可以連與改。
"""
from apps.catalog.models import Product, SupplierProduct
from apps.identity.models import ProductAlias
from apps.identity.normalize import alias_key
from apps.identity.services import _vendor_sku_owner
from apps.parties.models import Supplier
from apps.purchasing.models import PurchaseOrder

from . import mapping
from .models import Vendor, VendorLink
from .test_receiving import G02, _Arrival
from .tests import MOCEO_BASE, ORDERS, Company

MAPPINGS = "/api/v1/vendor-orders/mappings/"
NOTE = r"^\d{4}-\d\d-\d\d \d\d:\d\d "


class _Linking(_Arrival):
    def rows(self, client=None, **params):
        return (client or self.clerk).get(MAPPINGS, {"warehouse": self.wh1.id, "vendor": "moceo", **params})

    def by_key(self, client=None):
        r = self.rows(client)
        self.assertEqual(r.status_code, 200, r.content.decode())
        return {row["key"]: row for row in r.json()["rows"]}

    def set(self, key="G02", product="film", client=None, **more):
        product = self.film if product == "film" else product
        body = {"warehouse": self.wh1.id, "vendor": "moceo", "key": key,
                "product": product.id if isinstance(product, Product) else product, **more}
        return (client or self.clerk).post(MAPPINGS, body, format="json")

    def saved(self):
        return sorted(SupplierProduct.objects.values_list("vendor_sku", "product_id", "is_active"))


class ListTests(_Linking):
    def test_it_lists_every_item_the_vendor_has_with_what_it_is_linked_to_and_no_prices(self):
        r = self.rows()
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.assertNoKeyIn(r)
        got = r.json()
        self.assertEqual((got["warehouse"], got["vendor"], got["supplier"]), (self.wh1.id, "moceo", None))
        self.assertEqual([row["key"] for row in got["rows"]], ["G02", "G01", "S09", "M01#901", "M01#902"])
        self.assertEqual(got["rows"][0], {
            "key": "G02", "sku": "G02", "spec_id": None, "name": "高透亮面", "spec_label": "", "kind": "片材規格",
            "size": "125*196", "unit": "片", "pack_qty": 25, "product": None})
        self.assertEqual((got["rows"][3]["spec_id"], got["rows"][3]["spec_label"]), (901, "K43 iPhone 15 Pro"))
        self.assertNotIn("price", r.content.decode())                # 進價是叫貨那一頁的事
        self.assertEqual(SupplierProduct.objects.count(), 0)         # 只是看,不會自己建供應商或對照
        self.assertIsNone(VendorLink.objects.get().supplier_id)

    def test_what_is_linked_shows_up_with_the_stores_own_number_and_name(self):
        self.assertEqual(self.set().status_code, 200)
        self.assertEqual(self.set("M01#902", self.film2).status_code, 200)
        rows = self.by_key()
        self.assertEqual(rows["G02"]["product"],
                         {"id": self.film.id, "sku": self.film.sku, "name": self.film.name, "is_active": True})
        self.assertEqual((rows["M01#902"]["product"]["id"], rows["M01#901"]["product"], rows["G01"]["product"]),
                         (self.film2.id, None, None))
        self.assertEqual(self.rows().json()["supplier"]["name"], "膜總裁")

    def test_the_vendor_not_answering_is_said_not_shown_as_an_empty_list(self):
        self.vendor.read_down = True
        r = self.rows()
        self.assertEqual((r.status_code, "連不到" in r.json()["detail"]), (400, True), r.content.decode())
        self.assertNotIn("rows", r.json())


class LinkTests(_Linking):
    def test_a_clerk_links_an_item_and_it_is_remembered_with_the_vendors_own_wording(self):
        r = self.set()
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.assertNoKeyIn(r)
        self.assertEqual((r.json()["key"], r.json()["product"]["id"], r.json()["name"]), ("G02", self.film.id, "高透亮面"))
        row = SupplierProduct.objects.get()
        supplier = Supplier.objects.get(tenant=self.t, name="膜總裁")
        self.assertEqual((row.product_id, row.supplier_id, row.platform, row.vendor_sku, row.source_name, row.variant,
                          row.pack_qty, row.confirmed_by_id, row.is_active, row.note),
                         (self.film.id, supplier.id, "moceo", "G02", "高透亮面", "", 25, self.c.clerk_user.id, True, ""))
        self.assertIsNotNone(row.confirmed_at)
        self.assertEqual(VendorLink.objects.get().supplier_id, supplier.id)      # 入庫供應商記回串接,之後入庫用同一個

    def test_an_item_with_sizes_is_linked_one_size_at_a_time(self):
        self.assertEqual(self.set("M01#901").status_code, 200)
        self.assertEqual(self.set("M01#902", self.film2).status_code, 200)
        self.assertEqual(self.saved(), sorted([("M01#spec901", self.film.id, True), ("M01#spec902", self.film2.id, True)]))
        self.assertEqual(SupplierProduct.objects.get(vendor_sku="M01#spec901").variant, "K43 iPhone 15 Pro")

    def test_two_vendor_items_may_be_the_same_thing_in_the_store(self):
        self.assertEqual(self.set("G02").status_code, 200)
        self.assertEqual(self.set("G01").status_code, 200)
        self.assertEqual(self.saved(), sorted([("G02", self.film.id, True), ("G01", self.film.id, True)]))

    def test_names_and_pack_size_come_from_the_vendor_not_from_the_screen(self):
        r = self.set(name="亂寫的", spec_label="亂寫", pack_qty=999, sku="G01", spec_id=901)
        self.assertEqual(r.status_code, 200, r.content.decode())
        row = SupplierProduct.objects.get()
        self.assertEqual((row.vendor_sku, row.source_name, row.variant, row.pack_qty), ("G02", "高透亮面", "", 25))

    def test_linking_the_same_thing_again_changes_nothing(self):
        self.assertEqual(self.set().status_code, 200)
        self.assertEqual(self.set().status_code, 200)
        self.assertEqual(self.saved(), [("G02", self.film.id, True)])
        self.assertEqual(SupplierProduct.objects.get().note, "")

    def test_a_clerk_changes_it_and_the_old_one_is_kept_with_who_when_and_to_what(self):
        self.assertEqual(self.set(client=self.admin).status_code, 200)
        r = self.set(product=self.film2)
        self.assertEqual((r.status_code, r.json()["product"]["id"]), (200, self.film2.id), r.content.decode())
        self.assertEqual(self.saved(), sorted([("G02", self.film.id, False), ("G02", self.film2.id, True)]))
        old = SupplierProduct.objects.get(is_active=False)
        self.assertRegex(old.note, NOTE + f"{self.c.clerk_user.username} 改對到 {self.film2.sku}$")
        self.assertEqual(self.by_key()["G02"]["product"]["id"], self.film2.id)

    def test_unlinking_keeps_the_old_one_too(self):
        self.assertEqual(self.set().status_code, 200)
        r = self.set(product=None)
        self.assertEqual((r.status_code, r.json()["product"]), (200, None), r.content.decode())
        self.assertEqual(self.saved(), [("G02", self.film.id, False)])
        self.assertRegex(SupplierProduct.objects.get().note, NOTE + f"{self.c.clerk_user.username} 解除對照$")
        self.assertIsNone(self.by_key()["G02"]["product"])
        self.assertEqual(self.set(product=None).status_code, 200)        # 本來就沒連:不是錯

    def test_another_suppliers_item_with_the_same_number_is_left_alone(self):
        """別家供應商剛好也有一個料號叫 G02:那是另一回事,改 / 解除這一家的不會動到它。"""
        other = Supplier.objects.create(tenant=self.t, name="別家")
        SupplierProduct.objects.create(tenant=self.t, product=self.film2, supplier=other, vendor_sku="G02")
        self.assertIsNone(self.by_key()["G02"]["product"])                # 別家的對照不算這一家的
        self.assertEqual(self.set().status_code, 200)
        self.assertEqual(self.set(product=self.film2).status_code, 200)
        self.assertEqual(self.set(product=None).status_code, 200)
        theirs = SupplierProduct.objects.get(supplier=other)
        self.assertEqual((theirs.is_active, theirs.product_id, theirs.note), (True, self.film2.id, ""))

    def test_an_item_the_vendor_does_not_have_now_cannot_be_linked(self):
        for key in ("NOPE", "G02#901", "M01", "M01#903", "", None, 5, "g02"):
            r = self.set(key)
            self.assertEqual(r.status_code, 400, (key, r.content.decode()))
        self.assertEqual(self.set("NOPE").json()["detail"], "膜總裁現在沒有這個品項,請重新整理")
        self.assertEqual(SupplierProduct.objects.count(), 0)

    def test_only_goods_kept_by_count_can_be_linked(self):
        other = Company("b", "乙通訊行", "乙")
        theirs = Product.objects.create(tenant=other.tenant, category=other.cat_case, name="乙 的膜", requires_serial=False)
        cases = [
            (self.c.phone, "只能入到按數量管的一般商品"),
            (self.product("甲 虛擬", is_virtual=True), "只能入到按數量管的一般商品"),
            (self.product("甲 停用的膜", is_active=False), "已經停用"),
            (theirs, "找不到這個商品"),
            (999999, "找不到這個商品"),
            ("abc", "商品不對"),
            (True, "商品不對"),
        ]
        for product, why in cases:
            r = self.set(product=product)
            self.assertEqual((r.status_code, why in r.json()["detail"]), (400, True), (product, r.content.decode()))
        self.assertEqual((SupplierProduct.objects.count(), SupplierProduct.objects.filter(tenant=other.tenant).count()), (0, 0))

    def test_changing_to_something_that_cannot_be_stocked_leaves_the_old_link_alone(self):
        self.assertEqual(self.set().status_code, 200)
        self.assertEqual(self.set(product=self.c.phone).status_code, 400)
        self.assertEqual(self.saved(), [("G02", self.film.id, True)])
        self.assertEqual(SupplierProduct.objects.get().note, "")

    def test_a_name_taught_elsewhere_cannot_be_overruled_or_removed_from_here(self):
        """拍照入庫教過的叫法(別名表)先認領:這裡看得到它對到誰,改不了、也解除不了(要到那個商品把叫法拿掉)。"""
        supplier = Supplier.objects.create(tenant=self.t, name="膜總裁")
        ProductAlias.objects.create(tenant=self.t, product=self.film, supplier=supplier, kind=ProductAlias.Kind.VENDOR_SKU,
                                    value="G02", normalized_value=alias_key("G02"), verified=True)
        self.assertEqual(self.link(key="", supplier=supplier.id).status_code, 200)
        self.assertEqual(self.by_key()["G02"]["product"]["id"], self.film.id)
        for product in (self.film2, None):
            r = self.set(product=product, client=self.admin)
            self.assertEqual((r.status_code, "其他叫法" in r.json()["detail"]), (400, True), r.content.decode())
        self.assertEqual(SupplierProduct.objects.count(), 0)
        self.assertEqual(self.set().status_code, 200)             # 連到它本來就對到的那一個:沒事,也不多記一筆
        self.assertEqual(SupplierProduct.objects.count(), 0)


class AfterLinkingTests(_Linking):
    def test_once_linked_arrivals_go_straight_in_without_picking_again(self):
        """owner:「指定好之後,後續下訂,只需收貨,即可直接入庫」—— 入庫那一頁打開就已經帶好品號。"""
        self.assertEqual(self.set().status_code, 200)
        line = self.plan().json()["lines"][0]
        self.assertEqual((line["key"], line["product"]["id"]), (G02, self.film.id))
        r = self.take([{"key": G02, "qty": 50, "product": line["product"]["id"]}])
        self.assertEqual(r.status_code, 201, r.content.decode())
        self.assertEqual((self.stock(self.film)[0], PurchaseOrder.objects.filter(tenant=self.t).count()), (50, 1))
        self.assertEqual(self.saved(), [("G02", self.film.id, True)])         # 入庫沒有多記一筆對照

    def test_changing_the_link_later_does_not_touch_what_already_came_in(self):
        self.assertEqual(self.set().status_code, 200)
        self.assertEqual(self.take([self.line(qty=20)]).status_code, 201)
        self.assertEqual(self.set(product=self.film2).status_code, 200)
        self.assertEqual((self.stock(self.film)[0], self.stock(self.film2)[0]), (20, 0))
        got = self.clerk.get(f"{ORDERS}{self.o['id']}/receiving/").json()["lines"][0]
        self.assertEqual((got["received_qty"], got["product"]["id"]), (20, self.film2.id))
        self.assertEqual(self.take([self.line(qty=30, product=self.film2)], key="recv-0002").status_code, 201)
        self.assertEqual((self.stock(self.film)[0], self.stock(self.film2)[0]), (20, 30))


class WhoTests(_Linking):
    def test_either_ordering_or_receiving_is_enough_and_neither_is_not(self):
        for off, ok in ((("vendor_order",), True), (("purchase",), True), (("vendor_order", "purchase"), False)):
            self.turn_off(*off)
            got = (self.rows().status_code, self.set().status_code)
            self.assertEqual(got, (200, 200) if ok else (403, 403), off)
        self.assertEqual(self.rows().json()["detail"], "這個帳號沒有開「廠商叫貨」或「進貨入庫」")
        self.assertEqual((self.rows(self.admin).status_code, self.set(client=self.admin).status_code), (200, 200))

    def test_a_store_set_to_managers_only_for_ordering_still_lets_clerks_link(self):
        """「只限管理員叫貨」管的是叫貨與進價;收貨的店員照樣要能連(這一頁沒有價錢)。"""
        VendorLink.objects.update(clerk_ordering=False)
        self.assertEqual((self.rows().status_code, self.set().status_code), (200, 200))

    def test_a_clerk_locked_to_one_store_cannot_touch_another_stores(self):
        self.assertEqual(self.link(store=self.wh2).status_code, 200)
        r = self.clerk.get(MAPPINGS, {"warehouse": self.wh2.id, "vendor": "moceo"})
        self.assertEqual(r.status_code, 403, r.content.decode())
        r = self.clerk.post(MAPPINGS, {"warehouse": self.wh2.id, "vendor": "moceo", "key": "G02", "product": self.film.id},
                            format="json")
        self.assertEqual((r.status_code, SupplierProduct.objects.count()), (403, 0))
        r = self.admin.get(MAPPINGS, {"warehouse": self.wh2.id, "vendor": "moceo"})
        self.assertEqual(r.status_code, 200, r.content.decode())

    def test_a_store_that_has_not_been_set_up_or_a_vendor_not_on_the_list_is_said(self):
        r = self.admin.get(MAPPINGS, {"warehouse": self.wh2.id, "vendor": "moceo"})
        self.assertEqual((r.status_code, "還沒有設定膜總裁的金鑰" in r.json()["detail"]), (400, True))
        r = self.rows(vendor="nobody")
        self.assertEqual(r.status_code, 400, r.content.decode())
        self.assertEqual(self.clerk.get(MAPPINGS).status_code, 200)       # 鎖在門市 + 名單上只有一家:都不用講

    def test_another_company_sees_nothing_of_it(self):
        self.assertEqual(self.set().status_code, 200)
        other = Company("b", "乙通訊行", "乙")
        r = other.admin.get(MAPPINGS, {"warehouse": self.wh1.id, "vendor": "moceo"})
        self.assertEqual(r.status_code, 400, r.content.decode())
        r = other.admin.post(MAPPINGS, {"warehouse": self.wh1.id, "vendor": "moceo", "key": "G02", "product": self.film2.id},
                             format="json")
        self.assertEqual((r.status_code, self.saved()), (400, [("G02", self.film.id, True)]))

    def test_a_vendor_no_longer_worked_with_can_still_be_seen_and_fixed(self):
        """廠商停用了,已經叫的貨還要入庫 —— 對照照樣看得到、改得了。"""
        Vendor.objects.filter(code="moceo").update(is_active=False)
        self.assertEqual((self.rows().status_code, self.set().status_code), (200, 200))

    def test_a_key_only_ever_goes_to_its_own_vendor(self):
        self.vendor.bases.clear()
        self.assertEqual((self.rows().status_code, self.set().status_code), (200, 200))
        self.assertEqual(set(self.vendor.bases), {MOCEO_BASE})


class SameAnswerTests(_Linking):
    def test_the_whole_list_lookup_agrees_with_the_one_at_a_time_lookup(self):
        """清單用的整批查法(`owners_of`)跟入庫用的一筆一筆查(`_vendor_sku_owner`)說的要是同一個商品。"""
        mine, other = Supplier.objects.create(tenant=self.t, name="膜總裁"), Supplier.objects.create(tenant=self.t, name="別家")
        third = self.product("甲 第三個膜")

        def alias(value, product, supplier=None, **more):
            ProductAlias.objects.create(tenant=self.t, product=product, supplier=supplier, kind=ProductAlias.Kind.VENDOR_SKU,
                                        value=value, normalized_value=alias_key(value), **{"verified": True, **more})

        def listed(sku, product, supplier=mine, **more):
            SupplierProduct.objects.create(tenant=self.t, product=product, supplier=supplier, vendor_sku=sku, **more)

        listed("A1", self.film)                                         # 只有對照
        alias("B1", self.film2, mine); listed("B1", self.film)          # 這家的別名蓋過對照
        alias("C1", self.film2); listed("C1", self.film)                # 不分廠商的別名也蓋過對照
        alias("D1", self.film, mine); alias("D1", self.film2)           # 這家的別名優先於不分廠商的
        alias("E1", self.film, other); listed("E1", self.film2, other)  # 別家的:不算
        alias("F1", self.film, mine, verified=False)                    # 只是搜尋用的字:不算
        alias("G1", self.film, mine, is_active=False); listed("G1", self.film2, is_active=False)     # 停用的:不算
        listed("H-1", third)                                            # 寫法不同(符號、大小寫)是同一個料號
        asked = ["A1", "B1", "C1", "D1", "E1", "F1", "G1", "h1", "H-1", "ZZ", "", "M01#spec901"]
        got = mapping.owners_of(self.t, mine, asked)
        one = {sku: _vendor_sku_owner(self.t, mine, sku) for sku in asked}
        self.assertEqual({k: v.id for k, v in got.items()}, {k: v.id for k, v in one.items() if v is not None})
        self.assertEqual({k: v.id for k, v in got.items()},
                         {"A1": self.film.id, "B1": self.film2.id, "C1": self.film2.id, "D1": self.film.id,
                          "h1": third.id, "H-1": third.id})
        self.assertEqual(mapping.owners_of(self.t, None, asked), {})
        other_company = Company("b", "乙通訊行", "乙")
        self.assertEqual(mapping.owners_of(other_company.tenant, mine, asked), {})
