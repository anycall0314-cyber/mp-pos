"""配件跨型號共用(V1;owner 2026-10-18「這樣做可以，玻璃貼也有可能共用」):平台在型號庫設「新機的配件跟哪一支一樣」,
螢幕 / 機身分開勾,適用舊機的配件加上新機。規則在 `device_share.py`。全部是假資料。"""
from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.backup.models import TenantMaintenance
from apps.backup.tests.factory import Company
from apps.catalog import device_catalog, device_expand, device_share
from apps.catalog.models import Category, Condition, DeviceModel, DeviceShare, PhoneModel, Product, ProductRelation
from apps.catalog.test_device_catalog import catalog, device
from apps.tenants.models import UserProfile


def tablet(uid, name, launched="2024-05"):
    return DeviceModel.objects.create(uid=uid, category="tablet", brand="Apple", name=name, launched=launched, content_hash=uid)


class Shop:
    """一家店:平板機型(對到型號庫)、玻璃貼 / 皮套 / 維修料三類、幾個配件。"""

    def __init__(self, code, name, tag, uids):
        self.c = Company(code, name, tag)
        t = self.t = self.c.tenant
        self.models = {}
        for uid, d in uids.items():
            self.models[uid] = PhoneModel.objects.create(tenant=t, code=uid, name=d.name, match_key=d.name.casefold(),
                                                         device_uid=uid)
        self.glass_cat = Category.objects.create(tenant=t, code="PP", name="玻璃貼")
        self.parts_cat = Category.objects.create(tenant=t, code="RP", name="維修料")
        self.case_cat = self.c.cat_case                                                    # 皮套

    def item(self, name, category, *fits):
        p = Product.objects.create(tenant=self.t, category=category, name=f"{self.c.tag}{name}", requires_serial=False)
        for uid in fits:
            ProductRelation.objects.create(tenant=self.t, accessory_product=p, host_model=self.models[uid])
        return p

    def fits(self, product) -> set[str]:
        return set(ProductRelation.objects.filter(accessory_product=product).values_list("host_model__device_uid", flat=True))


class PartTests(TestCase):
    def test_a_category_follows_the_screen_or_the_body_by_its_name_unless_the_shop_chose(self):
        t = Company("a", "甲通訊行", "甲").tenant
        guess = {n: device_share.part_of(Category.objects.create(tenant=t, code=f"c{i}", name=n))
                 for i, n in enumerate(["玻璃貼", "保護貼", "鏡頭貼", "背蓋", "空壓殼", "維修料", "包膜", "鏡頭保護貼"])}
        self.assertEqual(guess, {"玻璃貼": "screen", "保護貼": "screen", "鏡頭貼": "body", "背蓋": "body", "空壓殼": "body",
                                 "維修料": "", "包膜": "", "鏡頭保護貼": "body"})
        chosen = Category.objects.create(tenant=t, code="x1", name="維修料2", shares_by="screen")
        off = Category.objects.create(tenant=t, code="x2", name="玻璃貼2", shares_by="none")
        general = Category.objects.create(tenant=t, code="x3", name="玻璃貼3", needs_host_model=False)
        host = Category.objects.create(tenant=t, code="x4", name="玻璃貼4", holds_devices=True)
        self.assertEqual([device_share.part_of(c) for c in (chosen, off, general, host)], ["screen", "", "", ""])


class ShareTests(TestCase):
    def setUp(self):
        self.air7, self.air8, self.air9 = tablet("u-air7", "iPad Air 7"), tablet("u-air8", "iPad Air 8"), tablet("u-air9", "iPad Air 9")
        self.phone = DeviceModel.objects.create(uid="u-ip17", category="phone", brand="Apple", name="iPhone 17", content_hash="x")
        self.a = Shop("a", "甲通訊行", "甲", {d.uid: d for d in (self.air7, self.air8)})
        a = self.a
        self.glass7 = a.item("9H/AIR7", a.glass_cat, "u-air7")
        self.case7 = a.item("皮套/AIR7", a.case_cat, "u-air7")
        self.case8 = a.item("皮套/AIR8", a.case_cat, "u-air8")
        self.part7 = a.item("維修料/AIR7/螢幕", a.parts_cat, "u-air7")
        self.both = a.item("9H/AIR7-8", a.glass_cat, "u-air7", "u-air8")

    def test_screen_only_puts_the_new_model_on_glass_that_fits_the_old_one(self):
        r = device_share.set_rule("u-air8", "u-air7", screen=True, body=False)
        self.assertEqual((r["tenants"], r["products"]), (1, 1))
        a = self.a
        self.assertEqual(a.fits(self.glass7), {"u-air7", "u-air8"})
        self.assertEqual(a.fits(self.case7), {"u-air7"})          # 機身沒勾
        self.assertEqual(a.fits(self.part7), {"u-air7"})          # 維修料不共用
        self.assertEqual(a.fits(self.both), {"u-air7", "u-air8"})  # 本來就有,不重複
        found = a.c.admin.get("/api/v1/products/", {"search": "iPad Air 8"}).json()["results"]
        self.assertIn(self.glass7.id, [p["id"] for p in found])   # 櫃檯打新機找得到

    def test_only_the_new_model_follows_the_old_one(self):
        device_share.set_rule("u-air8", "u-air7", screen=True, body=True)
        self.assertEqual(self.a.fits(self.case7), {"u-air7", "u-air8"})
        self.assertEqual(self.a.fits(self.case8), {"u-air8"})     # 只寫新機的不補舊機(紅隊)

    def test_ticking_the_body_later_adds_only_the_body_and_what_the_shop_took_off_stays_off(self):
        device_share.set_rule("u-air8", "u-air7", screen=True, body=False)
        ProductRelation.objects.filter(accessory_product=self.glass7, host_model=self.a.models["u-air8"]).delete()   # 店裡拿掉
        r = device_share.set_rule("u-air8", "u-air7", screen=True, body=True)
        self.assertEqual(r["products"], 1)
        self.assertEqual(self.a.fits(self.case7), {"u-air7", "u-air8"})
        self.assertEqual(self.a.fits(self.glass7), {"u-air7"})
        self.assertEqual(DeviceShare.objects.count(), 1)
        rule = DeviceShare.objects.get()
        self.assertEqual((rule.screen, rule.body), (True, True))

    def test_cancelling_keeps_what_was_added_and_stops_adding(self):
        rule = device_share.set_rule("u-air8", "u-air7", screen=True, body=False)["rule"]
        device_share.remove_rule(rule.pk)
        self.assertEqual(self.a.fits(self.glass7), {"u-air7", "u-air8"})   # 已經加上的不收回(紅隊)
        b = Shop("b", "乙通訊行", "乙", {"u-air7": self.air7})
        glass = b.item("9H/AIR7", b.glass_cat, "u-air7")
        PhoneModel.objects.create(tenant=b.t, code="air8", name="iPad Air 8", match_key="ipad air 8")
        device_expand.apply_links(b.t, {"iPad Air 8": "u-air8"}, confirm=True)
        self.assertEqual(b.fits(glass), {"u-air7"})

    def test_a_shop_that_gets_the_new_model_later_gets_it_then(self):
        b = Shop("b", "乙通訊行", "乙", {"u-air7": self.air7})
        glass, case = b.item("9H/AIR7", b.glass_cat, "u-air7"), b.item("皮套/AIR7", b.case_cat, "u-air7")
        r = device_share.set_rule("u-air8", "u-air7", screen=True, body=False)
        self.assertEqual((r["tenants"], r["products"]), (1, 1))   # 乙還沒有 Air 8,只有甲
        self.assertEqual(b.fits(glass), {"u-air7"})
        PhoneModel.objects.create(tenant=b.t, code="air8", name="iPad Air 8", match_key="ipad air 8")
        self.assertEqual(device_expand.apply_links(b.t, {"iPad Air 8": "u-air8"}, confirm=True), [])
        self.assertEqual((b.fits(glass), b.fits(case)), ({"u-air7", "u-air8"}, {"u-air7"}))
        self.assertEqual(self.a.fits(self.case7), {"u-air7"})     # 別家不動

    def test_expanding_the_new_model_into_a_shop_brings_the_shared_accessories(self):
        device_catalog.sync(catalog(device("u-air10", "iPad Air 10", brand="Apple", category="tablet", launched="2026-03",
                                           caps=("128GB",), colors=("灰",))), source="test")
        device_share.set_rule("u-air10", "u-air7", screen=True, body=False)
        a = self.a
        Category.objects.create(tenant=a.t, code="TB", name="平板", holds_devices=True, needs_host_model=False)
        for i, (code, n, used) in enumerate([("new", "全新", False), ("open", "已拆封", False), ("used", "中古機", True)]):
            Condition.objects.create(tenant=a.t, code=code, name=n, is_secondhand=used, sort_order=i)
        report = device_expand.expand(a.t, uids=["u-air10"], confirm=True)
        self.assertEqual((report.problems, report.shared), ([], 2))
        self.assertEqual((a.fits(self.glass7), a.fits(self.both)), ({"u-air7", "u-air10"}, {"u-air7", "u-air8", "u-air10"}))
        self.assertEqual(a.fits(self.case7), {"u-air7"})

    def test_it_carries_on_down_a_chain_whichever_was_set_first(self):
        PhoneModel.objects.create(tenant=self.a.t, code="air9", name="iPad Air 9", match_key="ipad air 9", device_uid="u-air9")
        device_share.set_rule("u-air9", "u-air8", screen=True, body=False)
        self.assertEqual(self.a.fits(self.glass7), {"u-air7"})
        device_share.set_rule("u-air8", "u-air7", screen=True, body=True)
        self.assertEqual(self.a.fits(self.glass7), {"u-air7", "u-air8", "u-air9"})
        self.assertEqual(self.a.fits(self.case7), {"u-air7", "u-air8"})   # Air 9 只有螢幕一樣

    def test_what_it_refuses(self):
        for args, msg in [(("u-air8", "u-air8", True, False), "不能跟自己一樣"),
                          (("u-ip17", "u-air7", True, False), "要同一類才能共用"),
                          (("u-air8", "u-air7", False, False), "至少勾一格"),
                          (("u-nope", "u-air7", True, False), "型號庫沒有這一支")]:
            with self.assertRaisesMessage(device_share.ShareError, msg):
                device_share.set_rule(args[0], args[1], screen=args[2], body=args[3])
        TenantMaintenance.objects.create(tenant=self.a.t, active=True, reason="還原")
        with self.assertRaisesMessage(device_share.ShareError, "「甲通訊行」正在還原資料"):
            device_share.set_rule("u-air8", "u-air7", screen=True, body=False)
        self.assertFalse(DeviceShare.objects.exists())
        self.assertEqual(self.a.fits(self.glass7), {"u-air7"})


class ApiTests(TestCase):
    def setUp(self):
        tablet("u-air7", "iPad Air 7")
        tablet("u-air8", "iPad Air 8")
        self.a = Shop("a", "甲通訊行", "甲", {d.uid: d for d in DeviceModel.objects.all()})
        self.glass = self.a.item("9H/AIR7", self.a.glass_cat, "u-air7")
        self.root = get_user_model().objects.create_user(username="platform-root", password="pw-12345")
        UserProfile.objects.create(user=self.root, role="platform_admin", tenant=None, is_warehouse_locked=False)
        self.api = Company.client(self.root)

    def test_the_platform_sets_lists_and_cancels(self):
        found = self.api.get("/api/v1/platform/devices/", {"q": "air 8"}).json()["devices"]
        self.assertEqual([(d["uid"], d["category_label"]) for d in found], [("u-air8", "平板")])
        r = self.api.post("/api/v1/platform/device-shares/", {"device": "u-air8", "same_as": "u-air7", "screen": True}, format="json")
        self.assertEqual(r.status_code, 200, r.json())
        body = r.json()
        self.assertEqual((body["tenants"], body["products"], body["rule"]["device"]["name"], body["rule"]["same_as"]["name"],
                          body["rule"]["screen"], body["rule"]["body"]), (1, 1, "iPad Air 8", "iPad Air 7", True, False))
        self.assertEqual(self.a.fits(self.glass), {"u-air7", "u-air8"})
        rows = self.api.get("/api/v1/platform/device-shares/").json()["rules"]
        self.assertEqual([(x["device"]["uid"], x["created_by"]) for x in rows], [("u-air8", "platform-root")])
        bad = self.api.post("/api/v1/platform/device-shares/", {"device": "u-air8", "same_as": "u-air8", "screen": True}, format="json")
        self.assertEqual((bad.status_code, bad.json()["detail"]), (400, "不能跟自己一樣"))
        self.assertEqual(self.api.delete(f"/api/v1/platform/device-shares/{rows[0]['id']}/").status_code, 204)
        self.assertEqual(self.api.delete(f"/api/v1/platform/device-shares/{rows[0]['id']}/").status_code, 404)
        self.assertEqual(self.a.fits(self.glass), {"u-air7", "u-air8"})

    def test_only_the_platform_admin(self):
        c = self.a.c
        self.assertEqual(c.admin.get("/api/v1/platform/device-shares/").status_code, 403)
        r = c.admin.post("/api/v1/platform/device-shares/", {"device": "u-air8", "same_as": "u-air7", "screen": True}, format="json")
        self.assertEqual(r.status_code, 403)
        self.assertFalse(DeviceShare.objects.exists())

    def test_a_shop_can_choose_what_a_category_follows(self):
        c = self.a.c
        rows = {x["name"]: x for x in c.admin.get("/api/v1/categories/", {"page_size": 100}).json()["results"]}
        self.assertEqual((rows["玻璃貼"]["shares_part"], rows["皮套"]["shares_part"], rows["維修料"]["shares_part"]), ("screen", "body", ""))
        r = c.admin.patch(f"/api/v1/categories/{rows['維修料']['id']}/", {"shares_by": "screen"}, format="json")
        self.assertEqual((r.status_code, r.json()["shares_part"]), (200, "screen"))
        r = c.admin.patch(f"/api/v1/categories/{rows['玻璃貼']['id']}/", {"shares_by": "none"}, format="json")
        self.assertEqual(r.json()["shares_part"], "")
