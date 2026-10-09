"""舊庫存匯入指令會先清空整家公司:沒指名公司、沒再打一次公司代碼就不做(2026-10-09 加的保護)。"""
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from apps.backup.tests.factory import Company
from apps.inventory.models import StockMovement, Warehouse
from apps.purchasing.models import PurchaseOrderCategory
from apps.tenants.models import Tenant

from .models import Category, Product

COMMAND = "apps.catalog.management.commands.import_legacy_inventory"


class WipeGuardTests(TestCase):
    def setUp(self):
        self.c = Company("a", "甲通訊行", "甲")
        self.b = Company("b", "乙通訊行", "乙")

    def run_it(self, *args):
        out = StringIO()
        with mock.patch(f"{COMMAND}.parse_legacy_xls", return_value=[]), \
             mock.patch(f"{COMMAND}.load_mapping", return_value={}):
            call_command("import_legacy_inventory", "--xls", "x.xls", "--mapping", "m.xlsx", *args, stdout=out)
        return out.getvalue()

    def counts(self, company):
        t = company.tenant
        return (Product.objects.filter(tenant=t).count(), Category.objects.filter(tenant=t).count(),
                Warehouse.objects.filter(tenant=t).count())

    def test_the_company_must_be_named(self):
        """以前沒給就是 1 號公司。"""
        with self.assertRaises(CommandError) as raised:
            self.run_it("--confirm")
        self.assertIn("--tenant", str(raised.exception))
        self.assertEqual(self.counts(self.c), (3, 2, 2))

    def test_preview_changes_nothing_and_says_whose_data(self):
        text = self.run_it("--tenant", str(self.c.tenant.id))
        self.assertIn("甲通訊行", text)
        self.assertIn("代碼 a", text)
        self.assertIn("商品 3", text)
        self.assertIn("未改任何資料", text)
        self.assertEqual(self.counts(self.c), (3, 2, 2))

    def test_confirm_alone_is_refused_when_something_would_be_deleted(self):
        for extra in ([], ["--wipe-company", ""], ["--wipe-company", "b"], ["--wipe-company", "A"], ["--wipe-company", "甲通訊行"]):
            with self.subTest(extra=extra):
                with self.assertRaises(CommandError) as raised:
                    self.run_it("--tenant", str(self.c.tenant.id), "--confirm", *extra)
                said = str(raised.exception)
                self.assertIn("沒有執行", said)
                self.assertIn("商品 3 筆", said)
                self.assertIn("--wipe-company a", said)
                self.assertEqual(self.counts(self.c), (3, 2, 2))
        self.assertEqual(self.counts(self.b), (3, 2, 2))

    def test_naming_the_company_again_runs_it_and_only_that_company(self):
        text = self.run_it("--tenant", str(self.c.tenant.id), "--confirm", "--wipe-company", "a")
        self.assertIn("完成", text)
        self.assertEqual(self.counts(self.c), (0, 0, 0))
        self.assertEqual(self.counts(self.b), (3, 2, 2))

    def test_an_empty_company_needs_no_second_naming(self):
        empty = Tenant.objects.create(name="空的公司", code="empty")
        self.assertIn("這家公司現在是空的", self.run_it("--tenant", str(empty.id)))
        text = self.run_it("--tenant", str(empty.id), "--confirm")
        self.assertIn("完成", text)
        self.assertEqual(self.counts(self.c), (3, 2, 2))

    def test_any_single_kind_of_data_that_would_be_deleted_counts(self):
        """公司裡只剩「進貨單別」這一種(複審抓到的):它也會被刪,所以一樣要再指名一次。"""
        only = Tenant.objects.create(name="只剩單別的公司", code="only")
        PurchaseOrderCategory.objects.create(tenant=only, code="general", name="一般進貨")
        for extra in ([], ["--wipe-company", "a"]):
            with self.subTest(extra=extra):
                with self.assertRaises(CommandError) as raised:
                    self.run_it("--tenant", str(only.id), "--confirm", *extra)
                self.assertIn("進貨單別 1 筆", str(raised.exception))
                self.assertEqual(PurchaseOrderCategory.objects.filter(tenant=only).count(), 1)
        self.assertIn("完成", self.run_it("--tenant", str(only.id), "--confirm", "--wipe-company", "only"))
        self.assertEqual(PurchaseOrderCategory.objects.filter(tenant=only).count(), 0)

    def test_the_guard_counts_exactly_what_the_wipe_deletes(self):
        """數的跟刪的是同一份清單:清單裡每一種單獨存在時都數得到,而且清空之後一筆不剩。"""
        from apps.catalog.management.commands import import_legacy_inventory as command

        cmd = command.Command()
        counted = dict(cmd._doomed(self.c.tenant))
        self.assertEqual(set(counted), {label for label, _model in command.WIPED})
        self.assertEqual(len(counted), len(command.WIPED))
        self.assertIn(PurchaseOrderCategory, [model for _label, model in command.WIPED])
        self.assertIn(StockMovement, [model for _label, model in command.WIPED])
        self.run_it("--tenant", str(self.c.tenant.id), "--confirm", "--wipe-company", "a")
        self.assertEqual([count for _label, count in cmd._doomed(self.c.tenant)], [0] * len(command.WIPED))
