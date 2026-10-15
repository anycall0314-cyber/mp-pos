"""平台型號庫(M1;owner 2026-10-15):匯入可以重跑、收回,展開成一家公司的品號(全新、中古機;2026 年上市的加已拆封)。
規則在 `device_catalog.py` 與 `device_expand.py`。全部是假資料。"""
import copy
import io
from decimal import Decimal

from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.backup.tests.factory import Company
from apps.catalog import device_catalog, device_expand
from apps.catalog.models import (
    Brand,
    Condition,
    DeviceCatalogChange,
    DeviceCatalogRun,
    DeviceModel,
    PhoneModel,
    PhoneSeries,
    Product,
)

MSRP = "source_stated_manufacturer_msrp"
REFERENCE = "source_reported_suggested_price_not_verified_original_msrp"


def device(uid, name, *, brand="Samsung", category="phone", launched="2025-02", caps=("256GB", "512GB"),
           colors=("鈦黑", "鈦銀"), prices=(), **more):
    return {"uid": uid, "origin": more.pop("origin", "codex-v4"), "category": category, "brand": brand, "name": name,
            "launched": launched, "capacities": list(caps), "connectivity": more.pop("connectivity", []), "sizes_mm": [],
            "colors": list(colors), "prices": [dict(p) for p in prices], "sources": ["https://example.test/x"],
            "aliases": [], "needs_review": [], **more}


def catalog(*models, version="v1"):
    return {"version": version, "models": list(models)}


S25U = device("u-s25u", "Galaxy S25 Ultra", prices=[
    {"storage": "256GB", "amount": 43900, "kind": MSRP, "version": "256GB", "connectivity": None, "size_mm": None, "url": ""},
    {"storage": "512GB", "amount": 47900, "kind": REFERENCE, "version": "512GB", "connectivity": None, "size_mm": None, "url": ""},
])
NEW26 = device("u-a57", "Galaxy A57 5G", launched="2026-03", caps=("128GB",), colors=("冰藍",))
WATCH = device("u-aw", "Apple Watch Series 10 鋁金屬 46mm", brand="Apple", category="watch", launched="2024-09",
               caps=(), colors=("曜石黑",), connectivity=["LTE"])
OLD = device("u-ipx", "iPhone X", brand="Apple", launched="", caps=("64GB", "256GB"), colors=(), origin="m1-draft")


class SyncTests(TestCase):
    def test_the_same_file_twice_changes_nothing_the_second_time(self):
        p = device_catalog.plan(catalog(S25U, NEW26))
        self.assertEqual((len(p["created"]), len(p["updated"]), p["unchanged"]), (2, 0, 0))
        self.assertFalse(DeviceModel.objects.exists(), "試算不寫")
        run = device_catalog.sync(catalog(S25U, NEW26), source="test")
        self.assertEqual(run.counts, {"created": 2, "updated": 0, "unchanged": 0})
        self.assertIsNone(device_catalog.sync(catalog(S25U, NEW26), source="test"))
        self.assertEqual((DeviceModel.objects.count(), DeviceCatalogRun.objects.count(), DeviceCatalogChange.objects.count()), (2, 1, 2))
        d = DeviceModel.objects.get(uid="u-s25u")
        self.assertEqual((d.brand, d.name, d.category, d.launched, d.data["capacities"]), ("Samsung", "Galaxy S25 Ultra", "phone", "2025-02", ["256GB", "512GB"]))

    def test_a_changed_model_is_updated_and_the_old_content_is_kept(self):
        device_catalog.sync(catalog(S25U), source="v1")
        changed = copy.deepcopy(S25U)
        changed["colors"].append("鈦藍")
        run = device_catalog.sync(catalog(changed, NEW26), source="v2")
        self.assertEqual(run.counts, {"created": 1, "updated": 1, "unchanged": 0})
        c = run.changes.get(uid="u-s25u")
        self.assertEqual((c.action, c.before["data"]["colors"], c.after["data"]["colors"]), ("updated", ["鈦黑", "鈦銀"], ["鈦黑", "鈦銀", "鈦藍"]))

    def test_bad_files_are_refused_whole(self):
        twin = dict(S25U, uid="u-other")
        cases = [
            (catalog(S25U, S25U), "編號重複:u-s25u"),
            (catalog(S25U, twin), "同一個型號出現兩次:Samsung Galaxy S25 Ultra"),
            (catalog(dict(S25U, category="pager")), "Samsung Galaxy S25 Ultra:類別「pager」不認得"),
            (catalog(dict(S25U, name="")), "有一筆沒有編號 / 品牌 / 型號:u-s25u"),
            (catalog(dict(S25U, old_uids=["u-a57"]), NEW26), "舊編號跟另一支的編號一樣:u-a57"),
            (catalog(S25U, dict(S25U, uid="u-space", name="Galaxy S25  ultra")), "同一個型號出現兩次:Samsung Galaxy S25  ultra"),
            ({"models": []}, "檔案裡沒有型號(要有 models)"),
        ]
        for payload, says in cases:
            with self.assertRaisesMessage(device_catalog.CatalogError, says):
                device_catalog.sync(payload, source="x")
        self.assertFalse(DeviceModel.objects.exists())
        device_catalog.sync(catalog(S25U), source="x")
        with self.assertRaisesMessage(device_catalog.CatalogError, "跟型號庫裡另一個編號撞名:Samsung Galaxy S25 Ultra"):
            device_catalog.sync(catalog(twin), source="y")

    def test_undo_puts_it_back_and_refuses_what_it_cannot(self):
        first = device_catalog.sync(catalog(S25U), source="v1")
        changed = copy.deepcopy(S25U)
        changed["launched"] = "2025-01"
        second = device_catalog.sync(catalog(changed, NEW26), source="v2")
        with self.assertRaisesMessage(device_catalog.CatalogError, "之後的匯入又改過這幾支,先收回後面那一次:u-s25u"):
            device_catalog.undo(first.pk)
        c = Company("a", "甲通訊行", "甲")
        pm = PhoneModel.objects.create(tenant=c.tenant, code="a57", name="Galaxy A57 5G", match_key="galaxy a57 5g", device_uid="u-a57")
        with self.assertRaisesMessage(device_catalog.CatalogError, "這幾支已經有公司對到,不能刪:Samsung Galaxy A57 5G"):
            device_catalog.undo(second.pk)
        self.assertEqual(DeviceModel.objects.get(uid="u-s25u").launched, "2025-01", "收不回就整批不動")
        pm.delete()
        self.assertEqual(device_catalog.undo(second.pk), {"deleted": 1, "restored": 1})
        self.assertEqual(DeviceModel.objects.get(uid="u-s25u").launched, "2025-02")
        self.assertFalse(DeviceModel.objects.filter(uid="u-a57").exists())
        with self.assertRaisesMessage(device_catalog.CatalogError, "這一次已經收回過了"):
            device_catalog.undo(second.pk)
        DeviceModel.objects.filter(uid="u-s25u").update(content_hash="edited")
        with self.assertRaisesMessage(device_catalog.CatalogError, "「Samsung Galaxy S25 Ultra」在這一次之後又被改過,不能收回"):
            device_catalog.undo(first.pk)

    def test_the_command_tries_first_and_writes_only_with_confirm(self):
        call_command("sync_device_catalog", stdout=io.StringIO())
        self.assertFalse(DeviceModel.objects.exists())
        call_command("sync_device_catalog", "--confirm", stdout=io.StringIO())
        n = DeviceModel.objects.count()
        self.assertGreater(n, 1400, "版本庫裡的定稿資料檔")
        call_command("sync_device_catalog", "--confirm", stdout=io.StringIO())
        self.assertEqual((DeviceModel.objects.count(), DeviceCatalogRun.objects.count()), (n, 1))


class ExpandTests(TestCase):
    def setUp(self):
        c = self.c = Company("a", "甲通訊行", "甲")
        from apps.catalog.models import Category
        self.tablet = Category.objects.create(tenant=c.tenant, code="TB", name="平板")
        self.watch = Category.objects.create(tenant=c.tenant, code="WA", name="手錶")
        self.cond = {n: Condition.objects.create(tenant=c.tenant, code=code, name=n, is_secondhand=used, sort_order=i)
                     for i, (code, n, used) in enumerate([("new", "全新", False), ("open", "已拆封", False),
                                                           ("usedw", "中古機(保固內)", True), ("used", "中古機", True)])}
        device_catalog.sync(catalog(S25U, NEW26, WATCH, OLD), source="test")

    def names(self, **filters):
        return sorted(Product.objects.for_tenant(self.c.tenant).filter(requires_serial=True, **filters).values_list("name", flat=True))

    def test_a_new_model_gets_new_and_used_and_2026_ones_also_opened(self):
        report = device_expand.expand(self.c.tenant, confirm=True)
        self.assertEqual(report.problems, [])
        s25 = [n for n in self.names() if n.startswith("Galaxy S25 Ultra")]
        self.assertEqual(s25, sorted(f"Galaxy S25 Ultra {cap} {col} 台版 {cond}" for cond in ("全新", "中古機")
                                     for cap in ("256GB", "512GB") for col in ("鈦黑", "鈦銀")))
        a57 = [n for n in self.names() if n.startswith("Galaxy A57")]
        self.assertEqual(a57, sorted(f"Galaxy A57 5G 128GB 冰藍 台版 {c}" for c in ("全新", "已拆封", "中古機")))
        self.assertFalse(Product.objects.filter(condition=self.cond["中古機(保固內)"]).exists(), "保固內不展開(owner)")
        pm = PhoneModel.objects.get(tenant=self.c.tenant, device_uid="u-s25u")
        self.assertEqual((pm.name, pm.brand.name, pm.series.name, pm.generation, pm.model_suffix), ("Galaxy S25 Ultra", "Samsung", "Galaxy", None, "S25 Ultra"))
        p = Product.objects.get(tenant=self.c.tenant, name="Galaxy S25 Ultra 256GB 鈦黑 台版 中古機")
        self.assertEqual((p.phone_model, p.capacity, p.color, p.region_version, p.is_secondhand, p.category, p.list_price),
                         (pm, "256GB", "鈦黑", "台版", True, self.c.cat_phone, Decimal("0")))

    def test_only_a_stated_original_price_becomes_the_new_price(self):
        device_expand.expand(self.c.tenant, confirm=True)
        price = dict(Product.objects.filter(tenant=self.c.tenant, name__startswith="Galaxy S25 Ultra").values_list("name", "list_price"))
        self.assertEqual(price["Galaxy S25 Ultra 256GB 鈦黑 台版 全新"], Decimal("43900"))
        self.assertEqual(price["Galaxy S25 Ultra 512GB 鈦黑 台版 全新"], Decimal("0"), "參考價不帶(紅隊)")
        self.assertEqual(price["Galaxy S25 Ultra 256GB 鈦黑 台版 中古機"], Decimal("0"))

    def test_watches_use_gps_or_bluetooth_and_missing_colours_or_sizes_still_work(self):
        device_expand.expand(self.c.tenant, confirm=True)
        self.assertEqual(self.names(name__startswith="Apple Watch"),
                         sorted(f"Apple Watch Series 10 鋁金屬 46mm {cap} 曜石黑 台版 {c}" for cap in ("GPS", "GPS+行動網路") for c in ("全新", "中古機")))
        self.assertEqual(Product.objects.get(tenant=self.c.tenant, name__startswith="Apple Watch", capacity="GPS", condition=self.cond["全新"]).category, self.watch)
        self.assertEqual(self.names(name__startswith="iPhone X"),
                         sorted(f"iPhone X {cap} 不分色 台版 {c}" for cap in ("64GB", "256GB") for c in ("全新", "中古機")))

    def test_old_models_can_be_used_only(self):
        device_expand.expand(self.c.tenant, new_for_old=False, confirm=True)
        self.assertEqual(self.names(name__startswith="iPhone X"), ["iPhone X 256GB 不分色 台版 中古機", "iPhone X 64GB 不分色 台版 中古機"])
        self.assertIn("Galaxy S25 Ultra 256GB 鈦黑 台版 全新", self.names(), "Codex 那份的照舊有全新")

    def test_a_model_the_shop_already_has_keeps_its_own_spelling_and_only_gets_what_is_missing(self):
        c = self.c
        brand = Brand.objects.create(tenant=c.tenant, code="samsung", name="Samsung")
        series = PhoneSeries.objects.create(tenant=c.tenant, brand=brand, code="gs", name="Galaxy S")
        pm = PhoneModel.objects.create(tenant=c.tenant, code="gs25u", name="Galaxy S 25 Ultra", match_key="galaxy s 25 ultra",
                                       brand=brand, series=series, generation=25, model_suffix="Ultra")
        mine = Product.objects.create(
            tenant=c.tenant, category=c.cat_phone, name="Galaxy S 25 Ultra 256GB 鈦黑色 台版 全新", capacity="256GB", color="鈦黑色",
            region_version="台版", phone_model=pm, brand=brand, series=series, generation=25, model_suffix="Ultra",
            condition=self.cond["全新"], requires_serial=True, list_price=Decimal("41990"))
        problems = device_expand.apply_links(c.tenant, {"Galaxy S 25 Ultra": "u-s25u"}, confirm=True)
        self.assertEqual(problems, [])
        report = device_expand.expand(c.tenant, confirm=True)
        self.assertEqual(self.names(phone_model=pm), ["Galaxy S 25 Ultra 256GB 鈦黑色 台版 中古機", "Galaxy S 25 Ultra 256GB 鈦黑色 台版 全新"])
        self.assertIn(("Galaxy S 25 Ultra", ["512GB", "鈦黑", "鈦銀"]), report.extra_variants)
        self.assertFalse(Product.objects.filter(tenant=c.tenant, name__startswith="Galaxy S25 Ultra").exists(), "同一支不會多一個機型")
        mine.refresh_from_db()
        self.assertEqual((mine.list_price, mine.name, mine.condition), (Decimal("41990"), "Galaxy S 25 Ultra 256GB 鈦黑色 台版 全新", self.cond["全新"]))

    def test_a_model_with_exactly_the_same_name_is_the_same_model(self):
        c = self.c
        pm = PhoneModel.objects.create(tenant=c.tenant, code="a57", name="Galaxy A57 5G", match_key="galaxy a57 5g")
        Product.objects.create(tenant=c.tenant, category=c.cat_phone, name="Galaxy A57 5G 128GB 冰川藍 台版 全新", capacity="128GB",
                               color="冰川藍", region_version="台版", phone_model=pm, condition=self.cond["全新"], requires_serial=True)
        report = device_expand.expand(c.tenant, confirm=True)
        self.assertEqual(report.linked, 1)
        pm.refresh_from_db()
        self.assertEqual(pm.device_uid, "u-a57")
        self.assertEqual(PhoneModel.objects.filter(tenant=c.tenant, name__istartswith="galaxy a57").count(), 1)
        self.assertEqual(self.names(phone_model=pm), sorted(f"Galaxy A57 5G 128GB 冰川藍 台版 {x}" for x in ("全新", "已拆封", "中古機")))

    def test_names_that_differ_only_in_spaces_are_the_same_model(self):
        # 公司的舊機型是「系列 世代 後綴」接空白組的:「Galaxy Tab S 10 Ultra」就是型號庫的「Galaxy Tab S10 Ultra」
        c = self.c
        device_catalog.sync(catalog(S25U, NEW26, WATCH, OLD, device("u-tab", "Galaxy Tab S10 Ultra", category="tablet", caps=("256GB",), colors=("灰",))), source="more")
        pm = PhoneModel.objects.create(tenant=c.tenant, code="tab", name="Galaxy Tab S 10 Ultra", match_key="galaxy tab s 10 ultra")
        report = device_expand.expand(c.tenant, confirm=True)
        pm.refresh_from_db()
        self.assertEqual((pm.device_uid, report.problems), ("u-tab", []))
        self.assertEqual(PhoneModel.objects.filter(tenant=c.tenant, name__icontains="tab").count(), 1)
        self.assertEqual(self.names(phone_model=pm), ["Galaxy Tab S 10 Ultra 256GB 灰 台版 中古機", "Galaxy Tab S 10 Ultra 256GB 灰 台版 全新"])

    def test_a_new_model_whose_name_only_differs_in_spaces_from_a_linked_one_is_not_built(self):
        c = self.c
        device_catalog.sync(catalog(S25U, NEW26, WATCH, OLD, device("u-dup", "Galaxy S 25 Ultra 5G", caps=("256GB",))), source="more")
        mine = PhoneModel.objects.create(tenant=c.tenant, code="m", name="Galaxy S25 Ultra 5G", match_key="galaxy s25 ultra 5g", device_uid="u-s25u")
        report = device_expand.expand(c.tenant, confirm=True)
        self.assertIn("Samsung Galaxy S 25 Ultra 5G:名稱跟公司的「Galaxy S25 Ultra 5G」只差空白,它已經對到型號庫另一支", report.problems)
        self.assertEqual(PhoneModel.objects.filter(tenant=c.tenant, device_uid="u-dup").count(), 0)
        self.assertFalse(Product.objects.filter(tenant=c.tenant, name__startswith="Galaxy S 25 Ultra 5G").exists())
        mine.refresh_from_db()
        self.assertEqual(mine.device_uid, "u-s25u")

    def test_two_shop_models_that_differ_only_in_spaces_are_not_guessed(self):
        c = self.c
        PhoneModel.objects.create(tenant=c.tenant, code="a", name="Galaxy A57 5G", match_key="galaxy a57 5g")
        PhoneModel.objects.create(tenant=c.tenant, code="b", name="Galaxy A 57 5G", match_key="galaxy a 57 5g")
        report = device_expand.expand(c.tenant, confirm=True)
        self.assertIn("Samsung Galaxy A57 5G:公司有兩個只差空白的機型,看不出是哪一個,先不展開", report.problems)
        self.assertFalse(PhoneModel.objects.filter(tenant=c.tenant, device_uid="u-a57").exists())

    def test_a_trial_counts_the_links_but_writes_nothing(self):
        c = self.c
        pm = PhoneModel.objects.create(tenant=c.tenant, code="gs25u", name="Galaxy S 25 Ultra", match_key="galaxy s 25 ultra")
        report = device_expand.expand(c.tenant, links={"Galaxy S 25 Ultra": "u-s25u"}, confirm=False)
        self.assertEqual(report.new_models, 3, "S25 Ultra 照對照算進舊的機型,不算新的")
        self.assertEqual(sum(report.created.values()), 2 * 2 * 2 + 3 + 2 * 2 + 2 * 2)
        self.assertFalse(Product.objects.filter(tenant=c.tenant, requires_serial=True).exclude(pk=c.phone.pk).exists())
        pm.refresh_from_db()
        self.assertEqual(pm.device_uid, "")
        self.assertFalse(Brand.objects.filter(tenant=c.tenant).exists())

    def test_held_models_are_left_out_and_a_second_run_adds_nothing(self):
        first = device_expand.expand(self.c.tenant, holds=["u-s25u"], confirm=True)
        self.assertEqual(first.held, 1)
        self.assertFalse(Product.objects.filter(tenant=self.c.tenant, name__startswith="Galaxy S25").exists())
        n = Product.objects.filter(tenant=self.c.tenant).count()
        again = device_expand.expand(self.c.tenant, holds=["u-s25u"], confirm=True)
        self.assertEqual((sum(again.created.values()), again.new_models, Product.objects.filter(tenant=self.c.tenant).count()), (0, 0, n))

    def test_links_that_do_not_fit_stop_everything(self):
        c = self.c
        PhoneModel.objects.create(tenant=c.tenant, code="m1", name="Galaxy S 25 Ultra", match_key="galaxy s 25 ultra")
        PhoneModel.objects.create(tenant=c.tenant, code="m2", name="Galaxy S25U", match_key="galaxy s25u")
        problems = device_expand.apply_links(c.tenant, {"Galaxy S 25 Ultra": "u-s25u", "Galaxy S25U": "u-s25u",
                                                        "沒有這個": "u-a57", "Galaxy S 25 Ultra ": "nope"}, confirm=True)
        self.assertEqual(problems, ["同一支對到兩個機型:Galaxy S 25 Ultra、Galaxy S25U", "公司沒有這個機型:沒有這個",
                                    "公司沒有這個機型:Galaxy S 25 Ultra "])
        self.assertFalse(PhoneModel.objects.filter(tenant=c.tenant).exclude(device_uid="").exists())

    def test_a_second_set_of_links_cannot_point_another_model_at_the_same_device(self):
        # 複審 P1:先對 A、再另外對 B 到同一支,兩次都過 → 同一支手機兩個機型
        c = self.c
        PhoneModel.objects.create(tenant=c.tenant, code="m1", name="Galaxy S 25 Ultra", match_key="galaxy s 25 ultra")
        PhoneModel.objects.create(tenant=c.tenant, code="m2", name="Galaxy S25U", match_key="galaxy s25u")
        self.assertEqual(device_expand.apply_links(c.tenant, {"Galaxy S 25 Ultra": "u-s25u"}, confirm=True), [])
        self.assertEqual(device_expand.apply_links(c.tenant, {"Galaxy S 25 Ultra": "u-s25u"}, confirm=True), [], "同一個再對一次照收")
        self.assertEqual(device_expand.apply_links(c.tenant, {"Galaxy S25U": "u-s25u"}, confirm=True),
                         ["這一支已經對到「Galaxy S 25 Ultra」,不能再對到「Galaxy S25U」"])
        self.assertEqual(PhoneModel.objects.get(tenant=c.tenant, code="m2").device_uid, "")
        with self.assertRaises(IntegrityError), transaction.atomic():
            PhoneModel.objects.filter(tenant=c.tenant, code="m2").update(device_uid="u-s25u")
        other = Company("b", "乙通訊行", "乙")
        PhoneModel.objects.create(tenant=other.tenant, code="x", name="Galaxy S25 Ultra", match_key="galaxy s25 ultra", device_uid="u-s25u")

    def test_another_company_is_untouched(self):
        other = Company("b", "乙通訊行", "乙")
        before = Product.objects.filter(tenant=other.tenant).count()
        device_expand.expand(self.c.tenant, confirm=True)
        self.assertEqual(Product.objects.filter(tenant=other.tenant).count(), before)
        self.assertFalse(PhoneModel.objects.filter(tenant=other.tenant).exists())

    def test_a_shop_without_the_conditions_is_refused(self):
        other = Company("b", "乙通訊行", "乙")
        with self.assertRaisesMessage(device_expand.ExpandError, "這家公司沒有這幾種品況:全新、中古機、已拆封"):
            device_expand.expand(other.tenant, confirm=True)

    def test_names_split_into_series_generation_and_suffix(self):
        cases = {
            ("Samsung", "Galaxy S25 Ultra"): ("Galaxy", None, "S25 Ultra"),
            ("Apple", "iPhone 16 Pro Max"): ("iPhone", 16, "Pro Max"),
            ("ASUS", "ZenFone 6 (ZS630KL)"): ("ZenFone", 6, "(ZS630KL)"),
            ("Apple", "iPad Air (2024) 11 吋"): ("iPad Air", None, "(2024) 11 吋"),
            ("Nokia", "215 4G (2024)"): ("Nokia", 215, "4G (2024)"),
            ("Xiaomi", "Redmi Note 13 Pro+ 5G"): ("Redmi Note", 13, "Pro+ 5G"),
        }
        for (brand, name), want in cases.items():
            self.assertEqual(device_expand.split_name(brand, name), want, name)
            s, g, x = want
            if brand != "Nokia":
                self.assertEqual(device_expand._model_name(s, g, x), name)
