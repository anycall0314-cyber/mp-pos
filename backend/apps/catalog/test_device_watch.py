"""型號庫自動更新(M1-D;owner 2026-10-16「對，做自動新增手機型號」):讀手機王、新機直接加、不齊的等、很像的給人按、
有勾的公司自動建品號、新機盯 60 天補顏色。規則在 `device_watch.py` / `sogi.py`。**全部是假網頁,不連外。**"""
from datetime import date, datetime
from unittest import mock
import urllib.error

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.backup.tests.factory import Company
from apps.catalog import device_catalog, device_watch, sogi
from apps.catalog.models import (
    Category,
    Condition,
    DeviceCandidate,
    DeviceCatalogChange,
    DeviceModel,
    DeviceWatchRun,
    PhoneModel,
    Product,
)
from apps.tenants.models import UserProfile

TODAY = date(2026, 10, 16)


def list_page(*items):
    return "".join(f'<div><a event-name="sogi.click" event-element-target="{name}" href="/products/{slug}/{pid}">'
                   f'<img alt="{name}"></a></div>' for name, slug, pid in items)


def product_page(name, *, launch="2026/09", variants=(("(8GB/256GB)", 19990), ("(12GB/512GB)", 23990)), colors=("曜石黑", "冰川藍"),
                 cls="雙卡雙待機"):
    v = "".join(f'<div class="col-auto"><a event-name="sogi.click" event-page-element="版本空機" class="stretched-link" '
                f'href="/prices/x/{i}">{label}</a><button type="button">i</button></div>'
                f'<div class="lead text-primary">$1,000</div><small class="d-block text-muted">原廠售價：${price:,}</small>'
                for i, (label, price) in enumerate(variants))
    launch_html = f"<small>上市日期：{launch}</small>" if launch else ""
    return (f"<h1 class='h2'>{name}</h1>{launch_html}{v}<table>"
            f'<tr><th class="active">機身顏色</th><td>{"、".join(colors)}</td></tr>'
            f'<tr><th class="active">裝置分類</th><td>{cls}</td></tr></table>')


class FakeSite:
    """假的手機王:path → 網頁內容(或丟的錯)。記下讀了哪幾頁。"""

    def __init__(self, pages):
        self.pages = dict(pages)
        self.read = []

    def opener(self, url):
        path = url.replace(sogi.BASE, "", 1)
        self.read.append(path)
        got = self.pages.get(path)
        if got is None:
            raise urllib.error.HTTPError(url, 404, "not found", {}, None)
        if isinstance(got, Exception):
            raise got
        return got

    def fetcher(self):
        return sogi.Fetcher(opener=self.opener, sleep=lambda s: None)


KNOWN = ("SAMSUNG Galaxy S25", "samsung-galaxy-s25", "100")   # 型號庫記過網址的那一支:每一頁清單都放(空的清單算讀失敗)


def lists(phones=(), tablets=(), wearables=()):
    return {"/search/cellphone": list_page(KNOWN, *phones), "/search/tablet": list_page(KNOWN, *tablets),
            "/search/wearable": list_page(KNOWN, *wearables)}


def seed_catalog():
    rows = [
        {"uid": "u-s25", "origin": "codex-v4", "category": "phone", "brand": "Samsung", "name": "Galaxy S25",
         "launched": "2025-02", "capacities": ["256GB"], "colors": ["黑"], "sources": ["https://www.sogi.com.tw/products/samsung-galaxy-s25/100"],
         "aliases": []},
        {"uid": "u-a57", "origin": "codex-v4", "category": "phone", "brand": "Samsung", "name": "Galaxy A57 5G",
         "launched": "2026-04", "capacities": ["256GB"], "colors": ["休閒藍"], "sources": ["https://m.eprice.com.tw/x"], "aliases": []},
        {"uid": "u-pad", "origin": "codex-v4", "category": "tablet", "brand": "Apple", "name": "iPad Air (2026) 11 吋",
         "launched": "2026-03", "capacities": ["128GB"], "colors": ["太空灰"], "sources": [], "aliases": []},
        {"uid": "u-honor", "origin": "codex-v4", "category": "phone", "brand": "HONOR", "name": "HONOR Magic V5",
         "launched": "2025-08", "capacities": ["512GB"], "colors": ["黑"], "sources": [], "aliases": []},
    ]
    device_catalog.sync({"models": rows}, source="test")


class SogiParseTests(TestCase):
    def test_a_product_page_gives_launch_each_storage_with_price_colors_and_kind(self):
        page = product_page("SAMSUNG Galaxy Tab S12 Ultra Wi-Fi", launch="2026/10", cls="",
                            variants=(("(12GB/256GB)", 46490), ("鍵盤套裝組(16GB/1TB", 67590), ("512GB", 52490)))
        got = sogi.parse_product(page)
        self.assertEqual(got["launch"], "2026-10")
        self.assertEqual([(v["storage"], v["msrp"], v["bundle"]) for v in got["variants"]],
                         [("256GB", 46490, False), ("1TB", 67590, True), ("512GB", 52490, False)])
        self.assertEqual(got["colors"], ["曜石黑", "冰川藍"])

    def test_a_bundle_is_not_a_storage_size(self):
        page = sogi.parse_product(product_page("SAMSUNG Galaxy Tab S12 Ultra Wi-Fi", cls="",
                                               variants=(("(12GB/256GB)", 46490), ("鍵盤套裝組(16GB/1TB", 67590))))
        info = device_watch.info_of("tablet", {"id": "1", "name": "SAMSUNG Galaxy Tab S12 Ultra Wi-Fi", "path": "/products/x/1"}, page,
                                    {"samsung": "Samsung"})
        self.assertEqual((info["category"], info["name"], info["capacities"], info["connectivity"]),
                         ("tablet", "Galaxy Tab S12 Ultra", ["256GB"], ["WiFi"]))
        self.assertEqual([p["amount"] for p in info["prices"]], [46490])

    def test_a_list_page_gives_each_product_once(self):
        page = list_page(("SAMSUNG Galaxy S26", "samsung-galaxy-s26", "200"), ("SAMSUNG Galaxy S26", "samsung-galaxy-s26", "200"),
                         ("Apple iPhone 18 Pro", "apple-iphone-18-pro", "201"))
        self.assertEqual([(x["id"], x["name"]) for x in sogi.parse_list(page)], [("200", "SAMSUNG Galaxy S26"), ("201", "Apple iPhone 18 Pro")])

    def test_names_lose_storage_and_tablets_lose_the_connection_words(self):
        brands = {"samsung": "Samsung", "apple": "Apple", "xiaomi": "Xiaomi"}
        self.assertEqual(device_watch.split_list_name("cellphone", "SAMSUNG Galaxy A16 5G (4GB/128GB)", brands),
                         ("Samsung", "SAMSUNG", "Galaxy A16 5G", ["5G"]))
        self.assertEqual(device_watch.split_list_name("tablet", "SAMSUNG Galaxy Tab S10+ Wi-Fi 256GB", brands),
                         ("Samsung", "SAMSUNG", "Galaxy Tab S10+", ["WiFi"]))
        self.assertEqual(device_watch.split_list_name("cellphone", "小米 Redmi Note 15 5G", brands)[:3], ("Xiaomi", "小米", "Redmi Note 15 5G"))
        self.assertEqual(device_watch.split_list_name("cellphone", "Nokia 3310", brands)[:3], ("", "Nokia", "3310"))

    def test_the_same_name_written_differently_is_the_same_one(self):
        k = device_watch.strong_key
        self.assertEqual(k("iPad Air 11 (2026)", "Apple", phone=False), k("iPad Air (2026) 11 吋", "Apple", phone=False))
        self.assertEqual(k("Magic V6", "HONOR"), k("HONOR Magic V6", "HONOR"))
        self.assertNotEqual(k("Galaxy A57", "Samsung"), k("Galaxy A57 5G", "Samsung"), "手機的 4G 與 5G 是不同的手機")
        self.assertNotEqual(k("Galaxy S26+", "Samsung"), k("Galaxy S26", "Samsung"))
        self.assertEqual(device_watch.weak_key("Galaxy A57", "Samsung"), device_watch.weak_key("Galaxy A57 5G", "Samsung"))
        self.assertNotEqual(device_watch.weak_key("iPad Air 11 (2027)", "Apple"), device_watch.weak_key("iPad Air 11 (2026)", "Apple"),
                            "同名不同年是不同的機器,不要每一代都要人按")


class CheckTests(TestCase):
    def setUp(self):
        patch = mock.patch.object(device_watch, "MIN_LIST", 1)   # 假網頁的清單只有幾支
        patch.start()
        self.addCleanup(patch.stop)
        seed_catalog()
        c = self.c = Company("a", "甲通訊行", "甲")
        Category.objects.create(tenant=c.tenant, code="TB", name="平板")
        Category.objects.create(tenant=c.tenant, code="WA", name="手錶")
        for i, (code, n, used) in enumerate([("new", "全新", False), ("open", "已拆封", False), ("used", "中古機", True)]):
            Condition.objects.create(tenant=c.tenant, code=code, name=n, is_secondhand=used, sort_order=i)
        c.tenant.auto_device_models = True
        c.tenant.save()
        self.off = Company("b", "乙通訊行", "乙")
        for i, (code, n, used) in enumerate([("new", "全新", False), ("open", "已拆封", False), ("used", "中古機", True)]):
            Condition.objects.create(tenant=self.off.tenant, code=code, name=n, is_secondhand=used, sort_order=i)

    def check(self, site, **kw):
        with mock.patch.object(timezone, "localdate", return_value=TODAY):
            return device_watch.check(site.fetcher(), today=TODAY, **kw)

    def products(self, company, prefix):
        return sorted(Product.objects.for_tenant(company.tenant).filter(name__startswith=prefix).values_list("name", flat=True))

    def test_a_new_phone_with_full_data_goes_straight_in_and_the_ticked_company_gets_its_products(self):
        site = FakeSite({**lists(phones=[("SAMSUNG Galaxy Z Fold8", "samsung-galaxy-z-fold8", "300")]),
                         "/products/samsung-galaxy-z-fold8/300": product_page("SAMSUNG Galaxy Z Fold8")})
        report = self.check(site)
        self.assertTrue(report.ok, report.notes)
        self.assertNotIn("/products/samsung-galaxy-s25/100", site.read, "型號庫記過網址的不讀商品頁")
        d = DeviceModel.objects.get(name="Galaxy Z Fold8")
        self.assertEqual((d.brand, d.category, d.launched, d.data["capacities"], d.data["colors"], d.data["origin"]),
                         ("Samsung", "phone", "2026-09", ["256GB", "512GB"], ["曜石黑", "冰川藍"], "sogi-auto"))
        self.assertEqual({p["kind"] for p in d.data["prices"]}, {device_watch.PRICE_KIND})
        self.assertEqual(DeviceCandidate.objects.get(source_id="300").status, DeviceCandidate.Status.ADDED)
        names = self.products(self.c, "Galaxy Z Fold8")
        self.assertEqual(names, sorted(f"Galaxy Z Fold8 {cap} {col} 台版 {cond}" for cond in ("全新", "已拆封", "中古機")
                                       for cap in ("256GB", "512GB") for col in ("曜石黑", "冰川藍")))
        self.assertEqual(set(Product.objects.for_tenant(self.c.tenant).filter(name__startswith="Galaxy Z Fold8").values_list("list_price", flat=True)),
                         {0}, "手機王的原廠售價不算原廠明示的建議價,不帶進售價")
        self.assertEqual(PhoneModel.objects.for_tenant(self.c.tenant).get(device_uid=d.uid).name, "Galaxy Z Fold8")
        self.assertEqual(self.products(self.off, "Galaxy Z Fold8"), [], "沒勾的公司一個品號都不多")
        again = self.check(site)
        self.assertEqual((again.counts.get("added", 0), DeviceModel.objects.filter(name="Galaxy Z Fold8").count()), (0, 1), "重跑什麼都不加")
        self.assertEqual(len(self.products(self.c, "Galaxy Z Fold8")), 12)

    def test_a_name_the_catalog_already_has_is_not_read_and_not_added(self):
        site = FakeSite(lists(phones=[("榮耀 Magic V5", "honor-magic-v5", "301")],
                              tablets=[("Apple iPad Air 11 (2026) Wi-Fi", "apple-ipad-air-11-2026-wifi", "302")]))
        report = self.check(site)
        self.assertEqual(report.counts.get("known"), 2)
        self.assertEqual(dict(DeviceCandidate.objects.values_list("source_id", "uid")), {"301": "u-honor", "302": "u-pad"})
        self.assertEqual(site.read, ["/search/cellphone", "/search/tablet", "/search/wearable"])
        self.assertEqual(DeviceModel.objects.count(), 4)

    def test_a_page_on_two_lists_is_handled_once(self):
        both = ("SAMSUNG Galaxy Z Fold8", "samsung-galaxy-z-fold8", "300")
        site = FakeSite({**lists(phones=[both], tablets=[both]), "/products/samsung-galaxy-z-fold8/300": product_page("SAMSUNG Galaxy Z Fold8")})
        self.check(site)
        self.assertEqual(site.read.count("/products/samsung-galaxy-z-fold8/300"), 1)
        self.assertEqual(DeviceModel.objects.get(name="Galaxy Z Fold8").category, "phone")

    def test_the_wifi_and_5g_pages_of_one_tablet_become_one_model(self):
        site = FakeSite({**lists(tablets=[("SAMSUNG Galaxy Tab S12 Wi-Fi", "tab-s12-wifi", "310"), ("SAMSUNG Galaxy Tab S12 5G", "tab-s12-5g", "311")]),
                         "/products/tab-s12-wifi/310": product_page("SAMSUNG Galaxy Tab S12 Wi-Fi", cls="", variants=(("256GB", 30990),)),
                         "/products/tab-s12-5g/311": product_page("SAMSUNG Galaxy Tab S12 5G", cls="", variants=(("256GB", 34990), ("512GB", 39990)))})
        self.check(site)
        d = DeviceModel.objects.get(name="Galaxy Tab S12")
        self.assertEqual((d.category, d.data["capacities"], d.data["connectivity"]), ("tablet", ["256GB", "512GB"], ["WiFi", "5G"]))
        self.assertEqual(set(DeviceCandidate.objects.values_list("uid", flat=True)), {d.uid})

    def test_a_4g_phone_next_to_an_existing_5g_one_waits_for_a_person(self):
        site = FakeSite({**lists(phones=[("SAMSUNG Galaxy A57", "samsung-galaxy-a57", "320")]),
                         "/products/samsung-galaxy-a57/320": product_page("SAMSUNG Galaxy A57")})
        report = self.check(site)
        c = DeviceCandidate.objects.get(source_id="320")
        self.assertEqual((c.status, c.reason), (DeviceCandidate.Status.REVIEW, "可能是型號庫的「Samsung Galaxy A57 5G」"))
        self.assertEqual(c.data["near"], [{"uid": "u-a57", "name": "Samsung Galaxy A57 5G"}])
        self.assertEqual((report.counts.get("review"), DeviceModel.objects.filter(name="Galaxy A57").exists()), (1, False))

    def test_a_new_brand_and_an_unclear_wearable_wait_for_a_person(self):
        site = FakeSite({**lists(phones=[("Nokia 3310", "nokia-3310", "330")], wearables=[("Apple Ring", "apple-ring", "331")]),
                         "/products/nokia-3310/330": product_page("Nokia 3310"),
                         "/products/apple-ring/331": product_page("Apple Ring", cls="")})
        self.check(site)
        self.assertEqual(dict(DeviceCandidate.objects.values_list("source_id", "reason")),
                         {"330": "新的品牌「Nokia」", "331": "看不出是手錶、手環還是耳機"})
        self.assertEqual(DeviceModel.objects.count(), 4)

    def test_missing_colours_wait_and_go_in_the_day_they_show_up(self):
        path = "/products/apple-iphone-18/340"
        site = FakeSite({**lists(phones=[("Apple iPhone 18", "apple-iphone-18", "340")]), path: product_page("Apple iPhone 18", colors=())})
        self.check(site)
        c = DeviceCandidate.objects.get(source_id="340")
        self.assertEqual((c.status, c.reason), (DeviceCandidate.Status.WAITING, "還沒有顏色"))
        site.pages[path] = product_page("Apple iPhone 18", launch="2026/11")
        self.check(site)
        self.assertEqual(DeviceCandidate.objects.get(source_id="340").reason, "還沒上市(2026-11)")
        site.pages[path] = product_page("Apple iPhone 18", launch="2026/10")
        site.pages["/search/cellphone"] = list_page(KNOWN)   # 清單上暫時沒有它也照網址再讀
        self.check(site)
        self.assertEqual(DeviceCandidate.objects.get(source_id="340").status, DeviceCandidate.Status.ADDED)
        self.assertEqual(len(self.products(self.c, "iPhone 18 ")), 12)

    def test_a_waiting_one_the_catalog_got_meanwhile_is_not_added_twice(self):
        path = "/products/apple-iphone-18/340"
        site = FakeSite({**lists(phones=[("Apple iPhone 18", "apple-iphone-18", "340")]), path: product_page("Apple iPhone 18", colors=())})
        self.check(site)
        device_catalog.sync({"models": [{"uid": "u-ip18", "origin": "codex-v4", "category": "phone", "brand": "Apple", "name": "iPhone 18",
                                         "launched": "2026-09", "capacities": ["256GB"], "colors": ["黑"], "sources": [], "aliases": []}]}, source="t")
        site.pages[path] = product_page("Apple iPhone 18")
        self.check(site)
        c = DeviceCandidate.objects.get(source_id="340")
        self.assertEqual((c.status, c.uid), (DeviceCandidate.Status.KNOWN, "u-ip18"))
        self.assertEqual(DeviceModel.objects.filter(brand="Apple", name__startswith="iPhone 18").count(), 1)

    def test_what_the_platform_admin_decided_while_the_check_was_reading_is_kept(self):
        path = "/products/apple-iphone-18/340"
        site = FakeSite({**lists(phones=[("Apple iPhone 18", "apple-iphone-18", "340")]), path: product_page("Apple iPhone 18", colors=())})
        self.check(site)
        real_get = sogi.Fetcher.get

        def get_and_dismiss(fetcher, p):
            body = real_get(fetcher, p)
            if p == path:   # 讀商品頁的這段時間,平台管理員按了「不收」
                DeviceCandidate.objects.filter(source_id="340").update(status=DeviceCandidate.Status.DISMISSED)
            return body
        site.pages[path] = product_page("Apple iPhone 18")
        with mock.patch.object(sogi.Fetcher, "get", get_and_dismiss):
            report = self.check(site)
        self.assertEqual(DeviceCandidate.objects.get(source_id="340").status, DeviceCandidate.Status.DISMISSED)
        self.assertFalse(DeviceModel.objects.filter(name="iPhone 18").exists())
        self.assertIn("Apple iPhone 18:平台管理員剛處理過,這次不動", report.notes)

    def test_being_blocked_stops_everything_and_writes_nothing(self):
        site = FakeSite({"/search/cellphone": urllib.error.HTTPError("x", 403, "no", {}, None)})
        report = self.check(site)
        self.assertEqual((report.ok, report.notes), (False, ["手機王不讓讀(HTTP 403)"]))
        self.assertEqual(site.read, ["/search/cellphone"], "被擋就整個停,不再讀別頁")
        self.assertFalse(DeviceCandidate.objects.exists())

    def test_being_blocked_halfway_through_the_product_pages_adds_nothing(self):
        site = FakeSite({**lists(phones=[("SAMSUNG Galaxy Z Fold8", "samsung-galaxy-z-fold8", "300"), ("Apple iPhone 18", "apple-iphone-18", "340")]),
                         "/products/samsung-galaxy-z-fold8/300": product_page("SAMSUNG Galaxy Z Fold8"),
                         "/products/apple-iphone-18/340": urllib.error.HTTPError("x", 429, "slow down", {}, None)})
        report = self.check(site)
        self.assertFalse(report.ok)
        self.assertIn("手機王不讓讀(HTTP 429),這一次什麼都不改", report.notes)
        self.assertFalse(DeviceModel.objects.filter(name="Galaxy Z Fold8").exists(), "前面讀到的也不加")
        self.assertEqual(self.products(self.c, "Galaxy Z Fold8"), [])

    def test_being_blocked_while_watching_new_ones_grows_nothing(self):
        fold, phone = "/products/samsung-galaxy-z-fold8/300", "/products/apple-iphone-18/340"
        site = FakeSite({**lists(phones=[("SAMSUNG Galaxy Z Fold8", "samsung-galaxy-z-fold8", "300"), ("Apple iPhone 18", "apple-iphone-18", "340")]),
                         fold: product_page("SAMSUNG Galaxy Z Fold8"), phone: product_page("Apple iPhone 18")})
        self.check(site)
        site.pages[fold] = product_page("SAMSUNG Galaxy Z Fold8", colors=("曜石黑", "冰川藍", "珊瑚粉"))
        site.pages[phone] = urllib.error.HTTPError("x", 403, "no", {}, None)
        report = self.check(site)
        self.assertFalse(report.ok)
        self.assertEqual(DeviceModel.objects.get(name="Galaxy Z Fold8").data["colors"], ["曜石黑", "冰川藍"], "讀到一半被擋,一支都不補")

    def test_a_list_that_suddenly_shrinks_counts_as_a_failed_read(self):
        DeviceWatchRun.objects.create(day=date(2026, 10, 15), ok=True, counts={"list_cellphone": 277})
        site = FakeSite({**lists(phones=[("SAMSUNG Galaxy Z Fold8", "samsung-galaxy-z-fold8", "300")]),
                         "/products/samsung-galaxy-z-fold8/300": product_page("SAMSUNG Galaxy Z Fold8")})
        report = self.check(site)
        self.assertFalse(report.ok)
        self.assertIn("cellphone 清單只讀到 2 支(上一次 277 支),當成這次讀失敗", report.notes)
        self.assertFalse(DeviceModel.objects.filter(name="Galaxy Z Fold8").exists())

    def test_too_many_new_ones_at_once_all_wait_for_a_person(self):
        phones = [(f"SAMSUNG Galaxy X{i}", f"samsung-galaxy-x{i}", str(400 + i)) for i in range(device_watch.MAX_AUTO + 1)]
        site = FakeSite({**lists(phones=phones), **{f"/products/{slug}/{pid}": product_page(name) for name, slug, pid in phones}})
        self.check(site)
        self.assertEqual(set(DeviceCandidate.objects.values_list("status", flat=True)), {DeviceCandidate.Status.REVIEW})
        self.assertEqual(DeviceModel.objects.count(), 4)

    def test_a_watched_new_phone_gets_its_later_colour_and_existing_products_stay_as_they_were(self):
        path = "/products/samsung-galaxy-z-fold8/300"
        site = FakeSite({**lists(phones=[("SAMSUNG Galaxy Z Fold8", "samsung-galaxy-z-fold8", "300")]), path: product_page("SAMSUNG Galaxy Z Fold8")})
        self.check(site)
        before = dict(Product.objects.for_tenant(self.c.tenant).filter(name__startswith="Galaxy Z Fold8").values_list("name", "id"))
        Product.objects.filter(id=before["Galaxy Z Fold8 256GB 曜石黑 台版 全新"]).update(list_price=55990)
        site.pages[path] = product_page("SAMSUNG Galaxy Z Fold8", colors=("曜石黑", "冰川藍", "珊瑚粉"),
                                        variants=(("(8GB/256GB)", 19990), ("(12GB/512GB)", 23990), ("(16GB/1TB)", 29990)))
        report = self.check(site)
        self.assertEqual(report.counts.get("updated"), 1)
        d = DeviceModel.objects.get(name="Galaxy Z Fold8")
        self.assertEqual((d.data["colors"], d.data["capacities"]), (["曜石黑", "冰川藍", "珊瑚粉"], ["256GB", "512GB", "1TB"]))
        self.assertTrue(DeviceCatalogChange.objects.filter(uid=d.uid, action="updated").exists(), "補的那一次也可以收回")
        now = dict(Product.objects.for_tenant(self.c.tenant).filter(name__startswith="Galaxy Z Fold8").values_list("name", "id"))
        self.assertEqual(len(now), 3 * 3 * 3)
        self.assertEqual({k: now[k] for k in before}, before, "原本的品號一個都沒換")
        self.assertEqual(Product.objects.get(id=before["Galaxy Z Fold8 256GB 曜石黑 台版 全新"]).list_price, 55990, "店家填的售價不動")

    def test_a_company_that_already_made_the_model_by_hand_is_linked_not_doubled(self):
        from apps.catalog.services_model_bundle import _get_or_create_phone_model
        from apps.catalog.device_expand import _brand, _series
        brand = _brand(self.c.tenant, "Samsung")
        pm = _get_or_create_phone_model(self.c.tenant, "Galaxy Z Fold 8", brand, _series(self.c.tenant, brand, "Galaxy Z Fold"), 8, "")
        site = FakeSite({**lists(phones=[("SAMSUNG Galaxy Z Fold8", "samsung-galaxy-z-fold8", "300")]),
                         "/products/samsung-galaxy-z-fold8/300": product_page("SAMSUNG Galaxy Z Fold8")})
        self.check(site)
        pm.refresh_from_db()
        self.assertEqual(pm.device_uid, DeviceModel.objects.get(name="Galaxy Z Fold8").uid)
        self.assertEqual(PhoneModel.objects.for_tenant(self.c.tenant).filter(name__icontains="Fold").count(), 1)

    def test_a_dry_run_reads_but_writes_nothing(self):
        site = FakeSite({**lists(phones=[("SAMSUNG Galaxy Z Fold8", "samsung-galaxy-z-fold8", "300"), ("榮耀 Magic V5", "honor-magic-v5", "301")]),
                         "/products/samsung-galaxy-z-fold8/300": product_page("SAMSUNG Galaxy Z Fold8")})
        report = self.check(site, write=False)
        self.assertEqual((report.counts.get("added"), report.counts.get("known")), (1, 1))
        self.assertEqual((DeviceCandidate.objects.count(), DeviceModel.objects.count(), Product.objects.filter(name__startswith="Galaxy Z Fold8").count()), (0, 4, 0))


class DecideTests(TestCase):
    def setUp(self):
        patch = mock.patch.object(device_watch, "MIN_LIST", 1)   # 假網頁的清單只有幾支
        patch.start()
        self.addCleanup(patch.stop)
        seed_catalog()
        self.c = Company("a", "甲通訊行", "甲")
        for i, (code, n, used) in enumerate([("new", "全新", False), ("open", "已拆封", False), ("used", "中古機", True)]):
            Condition.objects.create(tenant=self.c.tenant, code=code, name=n, is_secondhand=used, sort_order=i)
        self.c.tenant.auto_device_models = True
        self.c.tenant.save()
        from django.contrib.auth import get_user_model
        self.root = get_user_model().objects.create_user(username="platform-root", password="pw-12345")
        UserProfile.objects.create(user=self.root, role="platform_admin", tenant=None, is_warehouse_locked=False)
        self.api = Company.client(self.root)
        site = FakeSite({**lists(phones=[("SAMSUNG Galaxy A57", "samsung-galaxy-a57", "320"), ("Nokia 3310", "nokia-3310", "330")],
                                 tablets=[("SAMSUNG Galaxy Tab A57 Wi-Fi", "tab-a57-wifi", "350"), ("SAMSUNG Galaxy Tab A57 5G", "tab-a57-5g", "351")]),
                         "/products/samsung-galaxy-a57/320": product_page("SAMSUNG Galaxy A57"),
                         "/products/nokia-3310/330": product_page("Nokia 3310"),
                         "/products/tab-a57-wifi/350": product_page("SAMSUNG Galaxy Tab A57 Wi-Fi", cls="", colors=()),
                         "/products/tab-a57-5g/351": product_page("SAMSUNG Galaxy Tab A57 5G", cls="", colors=())})
        with mock.patch.object(timezone, "localdate", return_value=TODAY):
            device_watch.check(site.fetcher(), today=TODAY)

    def post(self, source_id, **body):
        c = DeviceCandidate.objects.get(source_id=source_id)
        with mock.patch.object(timezone, "localdate", return_value=TODAY):
            return self.api.post(f"/api/v1/platform/device-candidates/{c.id}/", body, format="json")

    def test_the_page_lists_what_waits_and_the_last_check(self):
        DeviceWatchRun.objects.create(day=TODAY, ok=True, finished_at=timezone.now(), counts={"list_cellphone": 2})
        with mock.patch.object(timezone, "localdate", return_value=TODAY):
            r = self.api.get("/api/v1/platform/device-watch/")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual((body["last"]["ok"], body["auto_tenants"], body["at"]), (True, ["a"], "05:30"))
        rows = {x["list_name"]: x for x in body["candidates"]}
        self.assertEqual(set(rows), {"SAMSUNG Galaxy A57", "Nokia 3310", "SAMSUNG Galaxy Tab A57 Wi-Fi", "SAMSUNG Galaxy Tab A57 5G"})
        self.assertEqual((rows["SAMSUNG Galaxy A57"]["status"], rows["SAMSUNG Galaxy A57"]["can_add"]), ("review", True))
        self.assertEqual((rows["SAMSUNG Galaxy Tab A57 5G"]["status"], rows["SAMSUNG Galaxy Tab A57 5G"]["can_add"]), ("waiting", False))

    def test_only_the_platform_admin_can_see_or_press(self):
        r = self.c.admin.get("/api/v1/platform/device-watch/")
        self.assertEqual(r.status_code, 403)
        c = DeviceCandidate.objects.get(source_id="320")
        self.assertEqual(self.c.admin.post(f"/api/v1/platform/device-candidates/{c.id}/", {"action": "dismiss"}, format="json").status_code, 403)
        self.assertEqual(DeviceCandidate.objects.get(source_id="320").status, DeviceCandidate.Status.REVIEW)

    def test_add_puts_it_in_the_catalog_and_builds_the_ticked_companys_products(self):
        r = self.post("320", action="add")
        self.assertEqual(r.status_code, 200, r.json())
        d = DeviceModel.objects.get(name="Galaxy A57")
        c = DeviceCandidate.objects.get(source_id="320")
        self.assertEqual((c.status, c.uid, c.decided_by_id), (DeviceCandidate.Status.ADDED, d.uid, self.root.id))
        self.assertEqual(Product.objects.for_tenant(self.c.tenant).filter(name__startswith="Galaxy A57 ").count(), 12)
        again = self.post("320", action="dismiss")
        self.assertEqual((again.status_code, again.json()["detail"]), (400, "這一筆已經是「自動加進型號庫」了,請重新整理"))

    def test_add_with_a_new_name_the_catalog_already_has_is_refused(self):
        r = self.post("320", action="add", name="Galaxy A57 (5G)")
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "型號庫已經有「Samsung Galaxy A57 5G」,是同一支請按「同一型號」"))
        self.assertEqual(DeviceModel.objects.filter(brand="Samsung", name__startswith="Galaxy A57").count(), 1)
        self.assertEqual(DeviceCandidate.objects.get(source_id="320").status, DeviceCandidate.Status.REVIEW)

    def test_add_can_rename_a_new_brand(self):
        r = self.post("330", action="add", name="3310 (2026)")
        self.assertEqual(r.status_code, 200, r.json())
        d = DeviceModel.objects.get(name="3310 (2026)")
        self.assertEqual((d.brand, d.category), ("Nokia", "phone"))

    def test_same_links_it_and_adds_nothing(self):
        r = self.post("320", action="same", uid="u-a57")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(DeviceCandidate.objects.get(source_id="320").status, DeviceCandidate.Status.LINKED)
        self.assertEqual(DeviceModel.objects.count(), 4)
        self.assertEqual(self.post("330", action="same", uid="u-nope").json()["detail"], "型號庫沒有這一支")

    def test_waiting_data_cannot_be_added_and_dismiss_takes_both_pages_of_one_tablet(self):
        r = self.post("350", action="add")
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "資料還不齊:還沒有顏色"))
        self.assertEqual(self.post("350", action="dismiss").json()["count"], 2)
        self.assertEqual(set(DeviceCandidate.objects.filter(source_id__in=["350", "351"]).values_list("status", flat=True)),
                         {DeviceCandidate.Status.DISMISSED})


class DailyTests(TestCase):
    def setUp(self):
        patch = mock.patch.object(device_watch, "MIN_LIST", 1)   # 假網頁的清單只有幾支
        patch.start()
        self.addCleanup(patch.stop)
        seed_catalog()
        self.site = FakeSite(lists(phones=[("SAMSUNG Galaxy S25", "samsung-galaxy-s25", "100")]))

    def test_once_a_day_unless_asked_again(self):
        first = device_watch.run_today(fetcher=self.site.fetcher())
        self.assertTrue(first.ok, first.notes)
        self.assertIsNone(device_watch.run_today(fetcher=self.site.fetcher()))
        again = device_watch.run_today(again=True, fetcher=self.site.fetcher())
        self.assertEqual((again.pk, DeviceWatchRun.objects.count()), (first.pk, 1))

    def test_it_waits_for_the_time_and_can_be_turned_off(self):
        early = timezone.make_aware(datetime(2026, 10, 16, 5, 0))
        late = timezone.make_aware(datetime(2026, 10, 16, 6, 0))
        with mock.patch.object(sogi, "Fetcher", lambda: self.site.fetcher()):
            self.assertIsNone(device_watch.run_due(now=early))
            with override_settings(DEVICE_WATCH_AT=""):
                self.assertIsNone(device_watch.run_due(now=late))
            self.assertIsNotNone(device_watch.run_due(now=late))

    def test_an_unexpected_error_is_written_down_not_raised(self):
        with mock.patch.object(device_watch, "check", side_effect=RuntimeError("壞了")):
            run = device_watch.run_today(fetcher=self.site.fetcher())
        self.assertEqual((run.ok, run.notes), (False, ["檢查失敗 RuntimeError: 壞了"]))
