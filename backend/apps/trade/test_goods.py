"""批發品(按數量賣的)批次上架 / 改價。跑法:manage.py test apps.trade.test_goods

要守住的(owner 2026-10-14:「一般商品也要可以用批次上架,可以依品牌,類別,關鍵字,型號等,用多重分類去選取與批次上架改價」;紅隊三條):
1. 類別、品牌、型號可以各點好幾個、疊在一起用;型號 = 商品本身的機型或它適用的機型;「新到幾天」篩得出新進的那一批;每一類帶數量(別的條件照舊)。
2. 三種價:固定價 / 門市價的幾 %(每個同行一樣、門市價改了跟著變)/ 照同行折數。買家看到的、下單凍在單上的、報價連結上的都照它。
3. 整批一起成立;一次最多 2,000 個;每一個有變的記一筆改價紀錄。
"""
from datetime import timedelta
from decimal import Decimal as D
from unittest import mock

from django.test import Client, TestCase
from django.utils import timezone

from apps.catalog.models import Brand, PhoneModel, Product, ProductRelation
from apps.purchasing.models import PurchaseOrder

from . import listing
from .models import TradeOrderLine, TradePartner, TradePriceChange, TradeProduct
from .tests import T, _Helpers


class GoodsTests(_Helpers, TestCase):
    def setUp(self):
        super().setUp()
        self.open_shop()
        t = self.seller
        self.apple = Brand.objects.create(tenant=t, code="AP", name="Apple")
        self.samsung = Brand.objects.create(tenant=t, code="SS", name="Samsung")
        self.i16 = PhoneModel.objects.create(tenant=t, brand=self.apple, code="I16", name="iPhone 16", match_key="iphone16")
        self.i16p = PhoneModel.objects.create(tenant=t, brand=self.apple, code="I16P", name="iPhone 16 Pro", match_key="iphone16pro")
        self.s25 = PhoneModel.objects.create(tenant=t, brand=self.samsung, code="S25", name="Galaxy S25", match_key="galaxys25")
        self.screen = self.a.cat_case.__class__.objects.create(tenant=t, code="SC", name="螢幕")
        mk = lambda name, cat, price, **extra: Product.objects.create(tenant=t, category=cat, name=name, list_price=price, **extra)   # noqa: E731
        self.s1 = mk("iPhone 16 副廠螢幕 A", self.screen, 2000, brand=self.apple)
        self.s2 = mk("iPhone 16 Pro 副廠螢幕", self.screen, 3000, brand=self.apple)
        self.s3 = mk("S25 螢幕", self.screen, 2500, brand=self.samsung)
        for product, model in ((self.s1, self.i16), (self.s2, self.i16p), (self.s3, self.s25)):
            ProductRelation.objects.create(tenant=t, accessory_product=product, host_model=model, host_model_key=model.match_key)
        self.inside = self.approve(self.b, percent=90)

    def goods(self, expect=200, **params):
        query = "&".join(f"{k}={v}" for k, v in {"state": "all", "limit": 2000, **params}.items())
        r = self.a.admin.get(f"{T}products/?{query}")
        self.assertEqual(r.status_code, expect, r.content.decode())
        return r.json()

    def names(self, **params):
        return sorted(r["name"] for r in self.goods(**params)["results"])

    def put(self, rows, expect=200):
        r = self.a.admin.post(T + "products/", {"rows": rows}, format="json")
        self.assertEqual(r.status_code, expect, r.content.decode())
        return r.json()

    def test_many_classifications_stack(self):
        self.assertEqual(self.names(category=self.screen.id), ["S25 螢幕", "iPhone 16 Pro 副廠螢幕", "iPhone 16 副廠螢幕 A"])
        self.assertEqual(self.names(category=f"{self.screen.id},{self.a.cat_case.id}", brand=self.apple.id),
                         ["iPhone 16 Pro 副廠螢幕", "iPhone 16 副廠螢幕 A"])
        self.assertEqual(self.names(model=f"{self.i16.id},{self.i16p.id}"), ["iPhone 16 Pro 副廠螢幕", "iPhone 16 副廠螢幕 A"])   # 型號可以點好幾個
        self.assertEqual(len(self.names(category=f"{self.screen.id},{self.a.cat_case.id}")), 4)              # 類別點兩個:兩類都有(停用的不算)
        self.assertEqual(self.names(model=self.s25.id, q="螢幕"), ["S25 螢幕"])
        self.assertEqual(self.names(model=self.s25.id, q="不存在"), [])
        got = self.goods(category=self.screen.id, brand=self.apple.id)
        # 每一類的數字:別的條件照舊、只換這一類
        self.assertEqual({c["name"]: c["count"] for c in got["facets"]["categories"]}["螢幕"], 2)
        self.assertEqual({b["name"]: b["count"] for b in got["facets"]["brands"]}, {"Apple": 2, "Samsung": 1})
        self.assertEqual({m["name"]: m["count"] for m in got["facets"]["models"]}, {"iPhone 16": 1, "iPhone 16 Pro": 1})
        # 同一個型號好幾個商品:數字是幾個(不是每個商品各一顆)
        extra = Product.objects.create(tenant=self.seller, category=self.screen, name="iPhone 16 副廠螢幕 B", list_price=1800, brand=self.apple)
        ProductRelation.objects.create(tenant=self.seller, accessory_product=extra, host_model=self.i16, host_model_key=self.i16.match_key)
        self.assertEqual({m["name"]: m["count"] for m in self.goods(category=self.screen.id)["facets"]["models"]}, {"iPhone 16": 2, "iPhone 16 Pro": 1, "Galaxy S25": 1})
        # 同一個型號底下有手機本身(機型)也有零件(適用機型):兩邊都算到
        for n in (1, 2):
            Product.objects.create(tenant=self.seller, category=self.a.cat_phone, name=f"iPhone 16 128GB 黑 {n}", list_price=26000, phone_model=self.i16, brand=self.apple)
        self.assertEqual({m["name"]: m["count"] for m in self.goods()["facets"]["models"]}["iPhone 16"], 4)
        self.assertEqual(len(self.names(model=self.i16.id)), 4)
        Product.objects.filter(pk=self.s3.pk).update(list_price=D("100.99"))
        self.assertEqual(next(r for r in self.goods()["results"] if r["product"] == self.s3.id)["list_price"], 100.99)   # 門市價不截小數(畫面算 % 要跟伺服器一樣)
        row = next(r for r in got["results"] if r["name"] == "iPhone 16 副廠螢幕 A")
        self.assertEqual((row["brand"], row["models"], row["percent"], row["price"], row["is_listed"]), ("Apple", ["iPhone 16"], None, None, False))

    def test_state_price_kind_and_newly_arrived(self):
        self.put([{"product": self.s1.id, "is_listed": True, "percent": 70}, {"product": self.s2.id, "is_listed": True, "price": 2100}])
        self.assertEqual(self.names(state="listed", category=self.screen.id), ["iPhone 16 Pro 副廠螢幕", "iPhone 16 副廠螢幕 A"])
        self.assertEqual(self.names(state="unlisted", category=self.screen.id), ["S25 螢幕"])
        self.assertEqual(self.names(priced="percent"), ["iPhone 16 副廠螢幕 A"])
        self.assertEqual(self.names(priced="fixed"), ["iPhone 16 Pro 副廠螢幕"])
        self.assertIn("S25 螢幕", self.names(priced="none"))
        # 新到 7 天:這幾天有進貨的;作廢的進貨單不算
        self.a.purchase(case_qty=3)
        self.assertEqual(self.names(fresh=7), [self.a.case.name])
        PurchaseOrder.objects.filter(tenant=self.seller).update(doc_date=timezone.localdate() - timedelta(days=10))
        self.assertEqual(self.names(fresh=7), [])
        self.assertEqual(self.names(fresh=30), [self.a.case.name])
        PurchaseOrder.objects.filter(tenant=self.seller).update(is_void=True)
        self.assertEqual(self.names(fresh=30), [])

    def test_percent_of_the_shop_price_follows_the_shop_price_and_is_the_same_for_everyone(self):
        self.a.purchase(case_qty=5)
        far = self.approve(self.c, percent=80)
        self.put([{"product": self.a.case.id, "is_listed": True}])
        price = lambda buyer: self.products(buyer)[self.a.case.sku]["unit_price"]   # noqa: E731
        list_price = int(self.a.case.list_price)
        self.assertEqual((price(self.b), price(self.c)), (int(listing.round_money(D(list_price) * D("0.9"))), int(listing.round_money(D(list_price) * D("0.8")))))
        self.put([{"product": self.a.case.id, "percent": 70}])
        self.assertEqual(price(self.b), price(self.c))                               # 每個同行一樣
        self.assertEqual(price(self.b), int(listing.round_money(D(list_price) * D("0.7"))))
        Product.objects.filter(pk=self.a.case.pk).update(list_price=1000)            # 門市價改了:跟著變
        self.assertEqual(price(self.b), 700)
        got = self.buy(self.b, [{"sku": self.a.case.sku, "spec_id": None, "qty": 2}])
        self.assertEqual(got["total_amount"], 1400)                                  # 下單凍在單上的也是它
        # 報價連結上也是它
        link = self.a.admin.post(T + "partners/external/", {"name": "外面的丁", "contact": "0911"}, format="json").json()["partner"]
        TradePartner.objects.filter(pk=link["id"]).update(status="approved")
        page = Client().get(link["quote"]["path"]).content.decode()
        self.assertIn("700", page)
        # 之後再改:已經下的單不變
        self.put([{"product": self.a.case.id, "percent": 50}])
        self.assertEqual(int(TradeOrderLine.objects.get(order__no=got["order_no"]).unit_price), 700)
        self.put([{"product": self.a.case.id, "percent": 70}])
        self.put([{"product": self.a.case.id, "price": 650}])                       # 固定價:% 清掉
        self.assertEqual(TradeProduct.objects.values_list("price", "percent").get(product=self.a.case), (D("650"), None))
        self.assertEqual(price(self.c), 650)
        self.put([{"product": self.a.case.id, "price": None}])                      # 清掉 = 回到照各同行的折數
        self.assertEqual((price(self.b), price(self.c)), (900, 800))
        self.assertIsNotNone(far)

    def test_the_whole_batch_or_nothing_and_the_limits(self):
        self.put([{"product": self.s1.id, "is_listed": True, "percent": 70}])
        for bad in ([{"product": self.s2.id, "is_listed": True}, {"product": self.s1.id, "percent": 0}],
                    [{"product": self.s2.id, "is_listed": True}, {"product": self.s1.id, "percent": 201}],
                    [{"product": self.s2.id, "is_listed": True}, {"product": self.s1.id, "percent": "70"}],
                    [{"product": self.s2.id, "is_listed": True}, {"product": self.s1.id, "price": 100, "percent": 70}],
                    [{"product": self.s2.id, "is_listed": True}, {"product": 999999, "is_listed": True}]):
            self.put(bad, expect=400)
        self.assertEqual(list(TradeProduct.objects.values_list("product_id", "is_listed", "percent")), [(self.s1.id, True, 70)])
        got = self.put([{"product": 900000 + i, "is_listed": True} for i in range(501)], expect=400)   # 501 個:不是被個數擋掉的
        self.assertEqual(got["detail"], "有一個商品找不到")
        # 真的 2,000 個過得去、2,001 個擋掉
        many = Product.objects.bulk_create([Product(tenant=self.seller, category=self.screen, name=f"零件 {i:04d}", sku=f"PT-{i:05d}", list_price=100,
                                                    requires_serial=False) for i in range(2001)])
        got = self.put([{"product": p.id, "is_listed": True, "percent": 60} for p in many], expect=400)
        self.assertEqual(got["detail"], "一次最多改 2000 個")
        self.assertEqual(self.put([{"product": p.id, "is_listed": True, "percent": 60} for p in many[:2000]]), {"changed": 2000})
        self.assertEqual(TradeProduct.objects.filter(percent=60, is_listed=True).count(), 2000)
        with mock.patch.object(listing, "MAX_ROWS", 2):
            got = self.put([{"product": p.id, "is_listed": True} for p in (self.s1, self.s2, self.s3)], expect=400)
        self.assertEqual(got["detail"], "一次最多改 2 個")

    def test_every_change_is_logged(self):
        self.put([{"product": self.s1.id, "is_listed": True, "percent": 70}, {"product": self.s2.id, "is_listed": True, "price": 2100}])
        self.put([{"product": self.s1.id, "percent": 75}, {"product": self.s2.id, "price": 2100}])       # 第二個沒變:不記
        self.put([{"product": self.s2.id, "is_listed": False}])
        got = [(c.product.name, c.what, c.scope, c.old_low and int(c.old_low), c.new_low and int(c.new_low)) for c in TradePriceChange.objects.order_by("id")]
        self.assertEqual(got, [
            ("iPhone 16 副廠螢幕 A", "list", "門市價 70%", None, 1400), ("iPhone 16 Pro 副廠螢幕", "list", "固定價", None, 2100),
            ("iPhone 16 副廠螢幕 A", "price", "門市價 70% → 門市價 75%", 1400, 1500), ("iPhone 16 Pro 副廠螢幕", "unlist", "固定價", 2100, None)])
        r = self.a.admin.get(f"{T}units/changes/").json()
        self.assertEqual(r["total"], 4)
        # 沒開放的只改價:還是沒開放、不記成「上架」
        self.put([{"product": self.s3.id, "percent": 60}])
        self.assertEqual(TradeProduct.objects.values_list("is_listed", "percent").get(product=self.s3), (False, 60))
        self.assertEqual(TradePriceChange.objects.count(), 4)

    def test_only_managers(self):
        self.assertEqual(self.a.clerk.get(f"{T}products/").status_code, 403)
        self.assertEqual(self.a.clerk.post(T + "products/", {"rows": [{"product": self.s1.id, "is_listed": True}]}, format="json").status_code, 403)
        theirs = self.b.admin.get(f"{T}products/?state=all&limit=2000").json()                 # 別家公司只看到自己的
        self.assertFalse({r["product"] for r in theirs["results"]} & {self.s1.id, self.s2.id, self.s3.id, self.a.case.id})
        self.assertNotIn("螢幕", [c["name"] for c in theirs["facets"]["categories"]])
