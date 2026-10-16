"""類別 → 品牌(中項)→ 型號 → 商品(owner 2026-10-16)。規則在 `category_template.py`、`tree.py`、CategoryViewSet 的 brands。全部是假資料。"""
from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.backup.tests.factory import STANDARD_NAME, Company
from apps.catalog import category_template, device_catalog, device_expand
from apps.catalog.models import Brand, Category, CategoryBrand, Condition, PhoneModel, Product, ProductRelation
from apps.tenants.models import Tenant, UserProfile

URL = "/api/v1/categories/"
TREE = "/api/v1/products/tree/"


def catalog():
    def d(uid, cat, brand, name):
        return {"uid": uid, "origin": "codex-v4", "category": cat, "brand": brand, "name": name, "launched": "2025-09",
                "capacities": ["256GB"] if cat in ("phone", "tablet") else [], "colors": ["黑"], "sources": [], "aliases": []}
    return {"models": [d("u1", "phone", "Samsung", "Galaxy S25"), d("u2", "phone", "Samsung", "Galaxy A57"),
                       d("u3", "phone", "Apple", "iPhone 17"), d("u4", "tablet", "Apple", "iPad Air (2025) 11 吋"),
                       d("u5", "watch", "Garmin", "Forerunner 970"), d("u6", "headphones", "Sony", "WF-1000XM6")]}


class TemplateTests(TestCase):
    def test_a_new_company_gets_the_template_with_catalog_brands(self):
        device_catalog.sync(catalog(), source="test")
        root = get_user_model().objects.create_user("platform-root", password="pw-12345")
        UserProfile.objects.create(user=root, role="platform_admin", is_warehouse_locked=False)
        r = Company.client(root).post("/api/v1/platform/tenants/", {"name": "丙通訊行", "code": "C"}, format="json")
        self.assertEqual(r.status_code, 201, r.content.decode()[:300])
        t = Tenant.objects.get(code="C")
        cats = {c.name: c for c in Category.objects.for_tenant(t)}
        self.assertEqual(list(Category.objects.for_tenant(t).order_by("sort_order").values_list("name", flat=True)),
                         ["手機", "平板", "穿戴", "皮套", "玻璃貼", "空壓殼", "傳輸線"])
        self.assertEqual({n: c.kind for n, c in cats.items()},
                         {"手機": "device", "平板": "device", "穿戴": "device", "皮套": "accessory", "玻璃貼": "accessory",
                          "空壓殼": "accessory", "傳輸線": "general"})
        names = lambda n: list(CategoryBrand.objects.filter(category=cats[n]).values_list("brand__name", flat=True))  # noqa: E731
        self.assertEqual(names("手機"), ["Samsung", "Apple"], "型號多的品牌排前面")
        self.assertEqual(names("平板"), ["Apple"])
        self.assertEqual(sorted(names("穿戴")), ["Garmin", "Sony"], "手錶、耳機都在穿戴")
        self.assertEqual(names("皮套"), [], "配件廠牌各家自己加")
        self.assertEqual(Brand.objects.for_tenant(t).filter(name="Apple").count(), 1, "同一個品牌在不同類別底下是同一筆")

    def test_running_it_again_or_on_a_company_with_its_own_categories_changes_nothing_it_has(self):
        device_catalog.sync(catalog(), source="test")
        c = Company("a", "甲通訊行", "甲")   # 已經有「手機」(PH)、「皮套」(LC)
        mine = Category.objects.get(tenant=c.tenant, name="皮套")
        category_template.apply(c.tenant)
        again = category_template.apply(c.tenant)
        self.assertEqual(again, {"categories": 0, "brands": 0})
        self.assertEqual(Category.objects.get(pk=mine.pk).code, "LC")
        self.assertEqual(Category.objects.filter(tenant=c.tenant, name="皮套").count(), 1)
        self.assertEqual(Category.objects.get(tenant=c.tenant, name="平板").code, "PD")


class WearTests(TestCase):
    def test_watches_and_earphones_go_into_wear_when_the_company_has_it(self):
        """owner 2026-10-16「都進穿戴」:範本的公司只有「穿戴」;還沒改的公司照舊放手錶 / 耳機音訊(其他測試)。"""
        device_catalog.sync(catalog(), source="test")
        c = Company("a", "甲通訊行", "甲")
        for i, (code, n, used) in enumerate([("new", "全新", False), ("open", "已拆封", False), ("used", "中古機", True)]):
            Condition.objects.create(tenant=c.tenant, code=code, name=n, is_secondhand=used, sort_order=i)
        category_template.apply(c.tenant)
        report = device_expand.expand(c.tenant, categories=("watch", "headphones"), confirm=True)
        self.assertEqual(report.problems, [])
        self.assertEqual(set(Product.objects.filter(tenant=c.tenant, phone_model__device_uid__in=["u5", "u6"])
                             .values_list("category__name", flat=True)), {"穿戴"})


class CategoryApiTests(TestCase):
    def setUp(self):
        self.c = Company("a", "甲通訊行", "甲")

    def test_a_new_category_must_say_which_kind_and_the_kind_sets_both_flags(self):
        r = self.c.admin.post(URL, {"code": "BK", "name": "背蓋"}, format="json")
        self.assertEqual((r.status_code, r.json()["detail"]), (400, ["要選這個類別是主機、配件還是一般"]))
        r = self.c.admin.post(URL, {"code": "BK", "name": "背蓋", "kind": "accessory"}, format="json")
        self.assertEqual(r.status_code, 201, r.content.decode())
        self.assertEqual((r.json()["kind"], r.json()["needs_host_model"], r.json()["holds_devices"]), ("accessory", True, False))
        r = self.c.admin.patch(f"{URL}{r.json()['id']}/", {"kind": "device"}, format="json")
        self.assertEqual((r.json()["kind"], r.json()["needs_host_model"], r.json()["holds_devices"]), ("device", False, True))
        r = self.c.admin.patch(f"{URL}{r.json()['id']}/", {"name": "背蓋殼"}, format="json")
        self.assertEqual((r.status_code, r.json()["kind"]), (200, "device"), "改名稱不用再選一次")

    def test_brands_under_a_category_can_be_added_removed_and_ordered_without_touching_products(self):
        case = Category.objects.get(tenant=self.c.tenant, name="皮套")
        dap = Brand.objects.create(tenant=self.c.tenant, code="dap", name="DAP")
        p = Product.objects.create(tenant=self.c.tenant, category=case, name="皮套/DAP/黑", brand=dap)
        u = f"{URL}{case.pk}/brands/"
        self.assertEqual(self.c.admin.post(u, {"brand": dap.pk}, format="json").json()["brands"], [{"id": dap.pk, "name": "DAP"}])
        r = self.c.admin.post(u, {"name": "太空盾"}, format="json")
        made = Brand.objects.get(tenant=self.c.tenant, name="太空盾")
        self.assertEqual([b["name"] for b in r.json()["brands"]], ["DAP", "太空盾"])
        self.assertEqual(self.c.admin.post(u, {"name": "太空盾"}, format="json").json()["brands"][1]["id"], made.pk, "同名的不再建")
        r = self.c.admin.post(f"{u}order/", {"brands": [made.pk, dap.pk]}, format="json")
        self.assertEqual([b["name"] for b in r.json()["brands"]], ["太空盾", "DAP"])
        r = self.c.admin.delete(f"{u}{dap.pk}/")
        self.assertEqual([b["name"] for b in r.json()["brands"]], ["太空盾"])
        p.refresh_from_db()
        self.assertEqual(p.brand, dap, "拿掉只是不列在這個類別底下")
        self.assertTrue(Brand.objects.filter(pk=dap.pk).exists())
        from apps.tenants import abilities
        UserProfile.objects.filter(user=self.c.clerk_user).update(denied_abilities=[abilities.EDIT_PRODUCTS])
        self.c.clerk_user.profile.refresh_from_db()   # 測試的連線一直拿著同一個帳號物件
        self.assertEqual(self.c.clerk.post(u, {"name": "店員加的"}, format="json").status_code, 403, "要有商品建檔的權限")
        other = Company("b", "乙通訊行", "乙")
        self.assertEqual(other.admin.post(u, {"name": "別家"}, format="json").status_code, 404)
        self.assertEqual(self.c.admin.post(u, {"brand": Brand.objects.create(tenant=other.tenant, code="x", name="X").pk},
                                           format="json").status_code, 400, "別家的品牌不能掛")


class TreeTests(TestCase):
    def setUp(self):
        c = self.c = Company("a", "甲通訊行", "甲")
        t = c.tenant
        for i, (code, n, used) in enumerate([("new", "全新", False), ("open", "已拆封", False), ("used", "中古機", True)]):
            Condition.objects.create(tenant=t, code=code, name=n, is_secondhand=used, sort_order=i)
        Category.objects.filter(pk=c.cat_phone.pk).update(holds_devices=True, needs_host_model=False)
        device_catalog.sync(catalog(), source="test")
        device_expand.expand(t, categories=("phone",), confirm=True)
        self.apple = Brand.objects.get(tenant=t, name="Apple")
        self.case = Category.objects.get(tenant=t, name="皮套")
        self.ip17 = PhoneModel.objects.get(tenant=t, name="iPhone 17")
        self.s25 = PhoneModel.objects.get(tenant=t, name="Galaxy S25")
        self.dap = Brand.objects.create(tenant=t, code="dap", name="DAP")
        self.ki = Brand.objects.create(tenant=t, code="ki", name="太空盾")
        self.a1 = self._acc("DAP 柔幻磁吸 iPhone 17 粉", self.dap, [self.ip17])
        self.a2 = self._acc("太空盾 磁吸殼 iPhone 17 灰", self.ki, [self.ip17, self.s25])
        self.a3 = self._acc("皮套/舊的沒掛機型", None, [])

    def _acc(self, name, maker, models):
        p = Product.objects.create(tenant=self.c.tenant, category=self.case, name=name, brand=maker,
                                   accessory_type=Product.AccessoryType.PHONE_SPECIFIC)
        for m in models:
            ProductRelation.objects.create(tenant=self.c.tenant, accessory_product=p, host_model=m, host_model_key=m.match_key)
        return p

    def get(self, **params):
        r = self.c.admin.get(TREE, params)
        self.assertEqual(r.status_code, 200, r.content.decode()[:300])
        return r.json()

    def test_a_device_category_goes_brand_then_model(self):
        cats = {c["name"]: c for c in self.get()["items"]}
        self.assertEqual(cats["手機"]["kind"], "device")
        brands = self.get(category=self.c.cat_phone.pk)["items"]
        self.assertEqual([(b["name"], b["count"]) for b in brands if b["name"] in ("Samsung", "Apple")], [("Apple", 1), ("Samsung", 2)],
                         "建品號時掛到類別底下的照掛的順序")
        self.assertIn("未分", [b["name"] for b in brands], "工廠建的那一支手機沒有品牌")
        models = self.get(category=self.c.cat_phone.pk, brand=self.apple.pk)
        self.assertEqual((models["level"], [(m["name"], m["key"], m["sku_count"]) for m in models["items"]]),
                         ("models", [("iPhone 17", self.ip17.match_key, 2)]))

    def test_a_brand_linked_to_the_category_shows_even_with_nothing_under_it_and_comes_first(self):
        u = f"{URL}{self.c.cat_phone.pk}/brands/"
        google = Brand.objects.get(pk=self.c.admin.post(u, {"name": "Google"}, format="json").json()["brands"][-1]["id"])
        self.c.admin.post(f"{u}order/", {"brands": [google.pk]}, format="json")
        brands = self.get(category=self.c.cat_phone.pk)["items"]
        self.assertEqual((brands[0]["name"], brands[0]["count"]), ("Google", 0))

    def test_an_accessory_by_phone_goes_phone_brand_then_model_then_grouped_by_maker(self):
        brands = self.get(category=self.case.pk)
        self.assertEqual((brands["mode"], [(b["name"], b["count"]) for b in brands["items"]]),
                         ("phone", [("Apple", 2), ("Samsung", 1), ("未分", 2)]))
        models = self.get(category=self.case.pk, brand=self.apple.pk)["items"]
        self.assertEqual([(m["name"], m["count"]) for m in models], [("iPhone 17", 2)])
        got = self.get(category=self.case.pk, brand=self.apple.pk, model=self.ip17.pk)
        self.assertEqual([(g["maker"], [p["name"] for p in g["products"]]) for g in got["items"]],
                         [("DAP", ["DAP 柔幻磁吸 iPhone 17 粉"]), ("太空盾", ["太空盾 磁吸殼 iPhone 17 灰"])])
        self.assertEqual(got["items"][1]["products"][0]["fits"], ["iPhone 17", "Galaxy S25"])
        loose = self.get(category=self.case.pk, brand="none")
        self.assertEqual(sorted(p["name"] for g in loose["items"] for p in g["products"]), sorted(["皮套/舊的沒掛機型", STANDARD_NAME]))

    def test_an_accessory_fitting_a_model_without_a_brand_is_listed_under_unsorted(self):
        """複審 P2:沒有品牌的機型,依手機那一層把它算進「未分」,點進去也要看得到。"""
        loose_model = PhoneModel.objects.create(tenant=self.c.tenant, name="山寨機 X1")
        odd = self._acc("皮套/山寨機 X1", self.dap, [loose_model])
        counted = {b["name"]: b["count"] for b in self.get(category=self.case.pk)["items"]}
        listed = [p["name"] for g in self.get(category=self.case.pk, brand="none")["items"] for p in g["products"]]
        self.assertEqual(counted["未分"], len(listed))
        self.assertIn(odd.name, listed)

    def test_an_accessory_by_maker_lists_products_with_what_they_fit(self):
        CategoryBrand.objects.create(tenant=self.c.tenant, category=self.case, brand=self.ki, sort_order=0)
        brands = self.get(category=self.case.pk, mode="maker")["items"]
        self.assertEqual([(b["name"], b["count"]) for b in brands], [("太空盾", 1), ("DAP", 1), ("未分", 2)], "類別底下掛的排前面")
        got = self.get(category=self.case.pk, mode="maker", brand=self.ki.pk)
        self.assertEqual([(p["name"], p["fits"]) for p in got["items"]], [("太空盾 磁吸殼 iPhone 17 灰", ["iPhone 17", "Galaxy S25"])])

    def test_a_general_category_only_goes_by_maker(self):
        cable = Category.objects.create(tenant=self.c.tenant, code="CH", name="傳輸線", needs_host_model=False)
        Product.objects.create(tenant=self.c.tenant, category=cable, name="C to C 1m", brand=self.apple)
        self.assertEqual(self.get(category=cable.pk)["mode"], "maker")
        self.assertEqual([p["name"] for p in self.get(category=cable.pk, brand=self.apple.pk)["items"]], ["C to C 1m"])

    def test_another_companys_category_is_not_found(self):
        other = Company("b", "乙通訊行", "乙")
        self.assertEqual(other.admin.get(TREE, {"category": self.case.pk}).status_code, 404)

    def test_typing_a_model_name_finds_the_accessories_that_fit_it(self):
        """紅隊第 1 條:櫃檯是打字找配件。品名裡沒有 iPhone 17 的配件,掛了這支也要找得到。"""
        hidden = self._acc("磁吸殼 粉", self.dap, [self.ip17])
        names = [p["name"] for p in self.c.admin.get("/api/v1/products/", {"search": "iphone17"}).json()["results"]]
        self.assertIn(hidden.name, names)
        names = [p["name"] for p in self.c.admin.get("/api/v1/products/", {"search": "Galaxy S25"}).json()["results"]]
        self.assertIn(self.a2.name, names)
        self.assertNotIn(hidden.name, names)

    def test_building_from_the_catalog_puts_the_brand_under_the_category(self):
        self.assertEqual(set(CategoryBrand.objects.filter(category=self.c.cat_phone).values_list("brand__name", flat=True)),
                         {"Samsung", "Apple"})
