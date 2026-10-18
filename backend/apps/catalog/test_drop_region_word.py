from django.test import TestCase

from apps.backup.tests.factory import Company
from apps.catalog.management.commands.drop_region_word import drop_region_word
from apps.catalog.models import Product


class DropRegionWordTests(TestCase):
    """品名不寫台版(owner 2026-10-17)。"""

    def setUp(self):
        c = Company("JB", "甲通訊行", "甲")
        self.t, cat = c.tenant, c.cat_phone
        mk = lambda name, **kw: Product.objects.create(tenant=self.t, category=cat, name=name, requires_serial=False, **kw)  # noqa: E731
        self.tw = mk("iPhone 17 256GB 黑色 台版 全新", spec="256GB 黑色 台版 全新", region_version="台版")
        self.hk = mk("iPhone 17 256GB 白色 港版 全新", region_version="港版")
        self.dup_old = mk("iPhone 17 512GB 黑色 全新")
        self.dup_new = mk("iPhone 17 512GB 黑色 台版 全新", region_version="台版")
        self.glued = mk("背蓋/台版限定/IP17")

    def names(self):
        return {p.pk: (p.name, p.spec, p.region_version) for p in Product.objects.filter(tenant=self.t)}

    def test_dry_run_writes_nothing(self):
        before = self.names()
        self.assertEqual(drop_region_word(self.t)[0], 1)
        self.assertEqual(self.names(), before)

    def test_drops_the_word_and_leaves_clashes_and_other_regions(self):
        changed, clashes = drop_region_word(self.t, confirm=True)
        got = self.names()
        self.assertEqual(got[self.tw.pk], ("iPhone 17 256GB 黑色 全新", "256GB 黑色 全新", ""))
        self.assertEqual(got[self.hk.pk][0], "iPhone 17 256GB 白色 港版 全新", "港版不動")
        self.assertEqual(got[self.dup_new.pk][0], "iPhone 17 512GB 黑色 台版 全新", "拿掉會跟另一個同名:不改、列出來")
        self.assertEqual(clashes, [(self.dup_new.sku, "iPhone 17 512GB 黑色 台版 全新")])
        self.assertEqual(got[self.glued.pk][0], "背蓋/台版限定/IP17", "不是單獨一段的不動")
        self.assertEqual((changed, drop_region_word(self.t, confirm=True)[0]), (1, 0), "再跑一次什麼都不變")
