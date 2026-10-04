"""每日庫存快照 + 每日對帳(資料底層規劃 2.5)。"""
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.test import TestCase
from django.utils import timezone

from apps.backup.models import RestoreJob, TenantMaintenance
from apps.backup.tests.factory import Company
from apps.backup.tests.test_backup_restore import _Base
from apps.inventory.models import ProductSerial, StockBalance
from apps.ledger import daily
from apps.ledger.checks import run_checks
from apps.ledger.models import LedgerCheckRun, StockSnapshot, StockSnapshotDay
from apps.ledger.snapshot import CompanyBusy, take_snapshot
from apps.sales.models import SalesOrder, SalesOrderItem, SalesOrderPayment, SalesReturnItem

D = Decimal
TPE = ZoneInfo("Asia/Taipei")


def taipei(hh, mm):
    today = timezone.localdate()
    return datetime(today.year, today.month, today.day, hh, mm, tzinfo=TPE)


def shop(code="a", tag="甲"):
    """兩支手機、十個皮套;四個皮套調往第二家店還在路上;賣掉一支手機與兩個皮套。"""
    c = Company(code, f"{tag}通訊行", tag)
    c.purchase(phone_serials=[f"{tag}IMEI1", f"{tag}IMEI2"], case_qty=10)
    c._post("/api/v1/transfer-orders/", {
        "from_warehouse": c.warehouses[0].id, "to_warehouse": c.warehouses[1].id,
        "items": [{"product": c.case.id, "qty": 4}],
    })
    c.sell(serial_no=f"{tag}IMEI1", case_qty=2)
    return c


def by_key(rows, c):
    names = {w.id: w.name for w in c.warehouses}
    return {
        (names.get(r.warehouse_id), r.product.name, r.state): (r.qty, r.cost_value) for r in rows
    }


class SnapshotTests(TestCase):
    def setUp(self):
        self.c = shop()

    def test_snapshot_counts_every_place_stock_can_be(self):
        n = take_snapshot(self.c.tenant)
        rows = by_key(StockSnapshot.objects.filter(tenant=self.c.tenant), self.c)
        self.assertEqual(n, 3)
        self.assertEqual(rows, {
            ("甲湳雅店", "甲 iPhone 15 128GB 黑", "in_stock"): (1, D("20000.00")),
            ("甲湳雅店", self.c.case.name, "in_stock"): (4, D("400.00")),
            # 調撥中:記在目的門市,成本用派發時的
            ("甲民生店", self.c.case.name, "in_transit"): (4, D("400.00")),
        })

    def test_phone_on_the_way_is_counted_at_the_destination(self):
        phone = ProductSerial.objects.get(tenant=self.c.tenant, serial_no="甲IMEI2")
        self.c._post("/api/v1/transfer-orders/", {
            "from_warehouse": self.c.warehouses[0].id, "to_warehouse": self.c.warehouses[1].id,
            "items": [{"product": self.c.phone.id, "qty": 1, "serial_ids": [phone.id]}],
        })
        take_snapshot(self.c.tenant)
        rows = by_key(StockSnapshot.objects.filter(tenant=self.c.tenant), self.c)
        self.assertEqual(rows[("甲民生店", "甲 iPhone 15 128GB 黑", "in_transit")], (1, D("20000.00")))
        self.assertNotIn(("甲湳雅店", "甲 iPhone 15 128GB 黑", "in_stock"), rows)

    def test_same_day_is_replaced_and_other_company_untouched(self):
        other = shop("b", "乙")
        take_snapshot(self.c.tenant)
        take_snapshot(other.tenant)
        self.c.sell(case_qty=1)
        take_snapshot(self.c.tenant)
        rows = by_key(StockSnapshot.objects.filter(tenant=self.c.tenant), self.c)
        self.assertEqual(rows[("甲湳雅店", self.c.case.name, "in_stock")], (3, D("300.00")))
        self.assertEqual(StockSnapshot.objects.filter(tenant=other.tenant).count(), 3)

    def test_not_taken_while_the_company_is_being_restored(self):
        TenantMaintenance.objects.create(tenant=self.c.tenant, active=True, reason="資料還原中")
        with self.assertRaises(CompanyBusy):
            take_snapshot(self.c.tenant)
        with self.assertRaises(CompanyBusy):
            run_checks(self.c.tenant)
        self.assertFalse(StockSnapshot.objects.exists())
        self.assertFalse(LedgerCheckRun.objects.exists())


class CheckTests(TestCase):
    def setUp(self):
        self.c = shop()
        self.t = self.c.tenant

    def results(self):
        return {r["key"]: r for r in run_checks(self.t).results}

    def assert_only_problem(self, key, *also):
        res = self.results()
        bad = sorted(k for k, r in res.items() if not r["ok"])
        self.assertEqual(bad, sorted([key, *also]), {k: res[k]["samples"] for k in bad})
        return res[key]

    def test_normal_business_is_all_consistent(self):
        so = SalesOrder.objects.get(tenant=self.t)
        line = SalesOrderItem.objects.get(so=so, product=self.c.case)
        self.c._post("/api/v1/sales-returns/", {
            "original_so": so.id, "warehouse": self.c.wh.id, "payment_method": "cash",
            "items": [{"original_item": line.id, "qty": 1, "unit_price": str(line.unit_price)}],
        })
        take_snapshot(self.t)
        run = run_checks(self.t)
        self.assertTrue(run.ok, [r for r in run.results if not r["ok"]])
        self.assertEqual(run.problem_count, 0)

    def test_each_kind_of_damage_is_caught(self):
        so = SalesOrder.objects.get(tenant=self.t)
        case_line = SalesOrderItem.objects.get(so=so, product=self.c.case)
        back = self.c._post("/api/v1/sales-returns/", {
            "original_so": so.id, "warehouse": self.c.wh.id, "payment_method": "cash",
            "items": [{"original_item": case_line.id, "qty": 1,
                       "unit_price": str(case_line.unit_price)}],
        })
        take_snapshot(self.t)
        self.assertTrue(run_checks(self.t).ok)

        from apps.sales.models import SalesReturn
        sr = SalesReturn.objects.get(pk=back["id"])
        SalesReturn.objects.filter(pk=sr.pk).update(subtotal=sr.subtotal + 1)
        self.assertIn(sr.no, self.assert_only_problem("return_header", "return_line_tax")["samples"][0])
        SalesReturn.objects.filter(pk=sr.pk).update(subtotal=sr.subtotal)
        ri = SalesReturnItem.objects.get(sr=sr)
        SalesReturnItem.objects.filter(pk=ri.pk).update(tax_amount=ri.tax_amount + 1)
        self.assert_only_problem("return_line_tax")
        SalesReturnItem.objects.filter(pk=ri.pk).update(tax_amount=ri.tax_amount)

        SalesOrder.objects.filter(pk=so.pk).update(subtotal=so.subtotal + 1)
        # 單頭被改:明細加總對不上,每行未稅加總也對不上單頭
        self.assertIn(so.no, self.assert_only_problem("sales_header", "sales_line_tax")["samples"][0])
        SalesOrder.objects.filter(pk=so.pk).update(subtotal=so.subtotal)

        line = SalesOrderItem.objects.filter(so=so).first()
        SalesOrderItem.objects.filter(pk=line.pk).update(untaxed_amount=line.untaxed_amount + 1)
        self.assert_only_problem("sales_line_tax")
        SalesOrderItem.objects.filter(pk=line.pk).update(untaxed_amount=line.untaxed_amount)

        pay = SalesOrderPayment.objects.get(so=so)
        SalesOrderPayment.objects.filter(pk=pay.pk).update(amount=pay.amount - 1)
        self.assert_only_problem("sales_payment")
        SalesOrderPayment.objects.filter(pk=pay.pk).update(amount=pay.amount)

        bal = StockBalance.objects.get(tenant=self.t, product=self.c.case, warehouse=self.c.wh)
        StockBalance.objects.filter(pk=bal.pk).update(qty=bal.qty + 5)
        res = self.results()
        self.assertFalse(res["stock_balance"]["ok"])
        self.assertIn("庫存 10,異動合計 5", res["stock_balance"]["samples"][0])
        StockBalance.objects.filter(pk=bal.pk).update(qty=bal.qty)

        phone = ProductSerial.objects.get(tenant=self.t, serial_no="甲IMEI2")
        # 序號被改動,庫存也跟今天拍的快照不一樣了
        ProductSerial.objects.filter(pk=phone.pk).update(warehouse=None)
        self.assert_only_problem("serial_place", "snapshot")
        ProductSerial.objects.filter(pk=phone.pk).update(status="sold", warehouse=None)
        self.assertIn("沒有有效的銷貨",
                      self.assert_only_problem("serial_record", "snapshot")["samples"][0])
        ProductSerial.objects.filter(pk=phone.pk).update(status="in_stock", warehouse=self.c.wh)

        snap = StockSnapshot.objects.filter(tenant=self.t).first()
        StockSnapshot.objects.filter(pk=snap.pk).update(qty=snap.qty + 1)
        self.assert_only_problem("snapshot")
        StockSnapshot.objects.filter(pk=snap.pk).update(qty=snap.qty)

        self.assertTrue(run_checks(self.t).ok)

    def test_sold_phone_back_in_stock_without_a_return_is_caught(self):
        sold = ProductSerial.objects.get(tenant=self.t, serial_no="甲IMEI1")
        ProductSerial.objects.filter(pk=sold.pk).update(status="in_stock", warehouse=self.c.wh)
        self.assertIn("有銷貨沒退", self.assert_only_problem("serial_record")["samples"][0])

    def test_return_reversing_more_cost_than_was_booked_is_caught(self):
        so = SalesOrder.objects.get(tenant=self.t)
        line = SalesOrderItem.objects.get(so=so, product=self.c.case)
        self.c._post("/api/v1/sales-returns/", {
            "original_so": so.id, "warehouse": self.c.wh.id, "payment_method": "cash",
            "items": [{"original_item": line.id, "qty": 1, "unit_price": str(line.unit_price)}],
        })
        SalesReturnItem.objects.update(cost_at_post=line.cost_at_post + 1)
        self.assert_only_problem("return_over")

    def test_stock_without_a_movement_record_is_listed(self):
        # 像舊庫存匯入那樣:只寫庫存餘額、沒有異動紀錄
        StockBalance.objects.create(
            tenant=self.t, product=self.c.case, warehouse=self.c.warehouses[1], qty=7,
            weighted_avg_cost=D("100"),
        )
        r = self.assert_only_problem("stock_balance")
        self.assertIn("庫存 7,異動合計 0", r["samples"][0])

    def test_missing_snapshot_days_are_listed(self):
        from datetime import timedelta

        today = timezone.localdate()
        take_snapshot(self.t)
        # 假裝第一次拍是三天前,中間兩天漏拍
        StockSnapshot.objects.filter(tenant=self.t).update(business_date=today - timedelta(days=3))
        StockSnapshotDay.objects.filter(tenant=self.t).update(business_date=today - timedelta(days=3))
        take_snapshot(self.t)
        r = self.results()["snapshot_gap"]
        self.assertEqual(r["count"], 2)
        for d in (today - timedelta(days=2), today - timedelta(days=1)):
            self.assertIn(d.isoformat(), r["detail"])
        self.assertNotIn((today - timedelta(days=3)).isoformat(), r["detail"])

    def test_legacy_history_totals_are_checked(self):
        import shutil
        import tempfile
        from pathlib import Path

        from apps.legacy import importer
        from apps.legacy.models import LegacyDocument
        from apps.legacy.tests.archive_builder import ArchiveBuilder
        from apps.legacy.tests.test_legacy_history import PERIOD, _period, standard

        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        b = ArchiveBuilder(tmp / "archive")
        standard(b)
        root = b.finish()
        importer.run(self.t, root, period=_period(PERIOD), write=True, reconciled_only=True)
        res = self.results()
        self.assertTrue(res["legacy_docs"]["ok"])
        self.assertEqual(res["legacy_open"]["count"], 1)
        self.assertGreater(res["legacy_unmapped"]["count"], 0)
        doc = LegacyDocument.objects.filter(tenant=self.t).first()
        LegacyDocument.objects.filter(pk=doc.pk).update(net_amount_minor=doc.net_amount_minor + 1)
        self.assertIn(doc.document_number_raw, self.assert_only_problem("legacy_docs")["samples"][0])


class DailyTests(TestCase):
    def setUp(self):
        self.a = shop()
        self.b = shop("b", "乙")

    def test_runs_once_after_closing_time(self):
        daily.run_due(now=taipei(9, 0))
        self.assertFalse(StockSnapshot.objects.exists())
        self.assertFalse(LedgerCheckRun.objects.exists())
        daily.run_due(now=taipei(23, 40))
        daily.run_due(now=taipei(23, 41))
        for c in (self.a, self.b):
            self.assertEqual(LedgerCheckRun.objects.filter(tenant=c.tenant).count(), 1)
            self.assertEqual(StockSnapshot.objects.filter(tenant=c.tenant).count(), 3)

    def test_company_being_restored_is_skipped_and_others_still_run(self):
        TenantMaintenance.objects.create(tenant=self.a.tenant, active=True, reason="資料還原中")
        logs = []
        daily.run_due(now=taipei(23, 40), log=logs.append)
        self.assertFalse(LedgerCheckRun.objects.filter(tenant=self.a.tenant).exists())
        self.assertTrue(LedgerCheckRun.objects.filter(tenant=self.b.tenant).exists())
        self.assertTrue(any("跳過" in m for m in logs), logs)
        # 還原結束後,下一次呼叫就補做
        TenantMaintenance.objects.filter(tenant=self.a.tenant).update(active=False)
        daily.run_due(now=taipei(23, 50))
        self.assertTrue(LedgerCheckRun.objects.filter(tenant=self.a.tenant).exists())

    def test_one_company_failing_does_not_stop_the_others(self):
        from unittest import mock

        real = daily.run_checks

        def broken(tenant, now=None, **kw):
            if tenant.pk == self.a.tenant.pk:
                raise RuntimeError("壞掉")
            return real(tenant, now, **kw)
        logs = []
        with mock.patch.object(daily, "run_checks", broken):
            daily.run_due(now=taipei(23, 40), log=logs.append)
        self.assertTrue(LedgerCheckRun.objects.filter(tenant=self.b.tenant).exists())
        self.assertTrue(any("失敗" in m for m in logs), logs)


class RoundOneTests(TestCase):
    """Codex 第一輪提的狀況。"""

    def setUp(self):
        self.c = shop()
        self.t = self.c.tenant

    def results(self):
        return {r["key"]: r for r in run_checks(self.t).results}

    def test_company_with_no_stock_is_snapshotted_once(self):
        from unittest import mock

        empty = Company("z", "空公司", "空")
        with mock.patch.object(daily, "take_snapshot", wraps=daily.take_snapshot) as spy:
            daily.run_due(now=taipei(23, 40), tenants=[empty.tenant])
            daily.run_due(now=taipei(23, 41), tenants=[empty.tenant])
        self.assertEqual(StockSnapshot.objects.filter(tenant=empty.tenant).count(), 0)
        mark = StockSnapshotDay.objects.get(tenant=empty.tenant)
        self.assertEqual((mark.row_count, mark.taken_at), (0, taipei(23, 40)))
        self.assertEqual(spy.call_count, 2)          # 第二次進去看到已拍,不重拍
        self.assertEqual(LedgerCheckRun.objects.filter(tenant=empty.tenant).count(), 1)

    def test_days_with_zero_stock_are_not_missing(self):
        from datetime import timedelta

        today = timezone.localdate()
        # 三天前有庫存(有快照列),前兩天庫存是零(有拍、零列)
        take_snapshot(self.t)
        StockSnapshot.objects.filter(tenant=self.t).update(business_date=today - timedelta(days=3))
        StockSnapshotDay.objects.filter(tenant=self.t).update(business_date=today - timedelta(days=3))
        for back in (2, 1):
            StockSnapshotDay.objects.create(
                tenant=self.t, business_date=today - timedelta(days=back),
                taken_at=timezone.now(), row_count=0,
            )
        r = self.results()["snapshot_gap"]
        self.assertEqual((r["count"], r["detail"]), (0, "沒有漏拍"))

    def test_checks_are_redone_after_a_restore_the_same_day(self):
        from apps.backup.models import RestoreJob

        daily.run_due(now=taipei(23, 40), tenants=[self.t])
        first = LedgerCheckRun.objects.get(tenant=self.t)
        RestoreJob.objects.create(tenant=self.t, status=RestoreJob.Status.DONE,
                                  file_sha256="0" * 64, finished_at=taipei(23, 45))
        body = self.c.admin.get("/api/v1/ledger/checks/").json()
        self.assertTrue(body["latest"]["before_restore"])
        daily.run_due(now=taipei(23, 50), tenants=[self.t])
        self.assertEqual(LedgerCheckRun.objects.filter(tenant=self.t).count(), 2)
        body = self.c.admin.get("/api/v1/ledger/checks/").json()
        self.assertFalse(body["latest"]["before_restore"])
        self.assertTrue(next(h for h in body["history"] if h["id"] == first.id)["before_restore"])

    def test_tenant_command_waits_for_closing_time(self):
        from datetime import time
        from io import StringIO
        from unittest import mock

        from django.core.management import call_command

        out = StringIO()
        with mock.patch.object(daily, "daily_time", return_value=time.max):
            call_command("run_daily_ledger", "--tenant", "a", stdout=out)
        self.assertIn("還沒到收店時間", out.getvalue())
        self.assertFalse(LedgerCheckRun.objects.exists())
        with mock.patch.object(daily, "daily_time", return_value=time.max):
            call_command("run_daily_ledger", "--tenant", "a", "--now", stdout=out)
        self.assertTrue(LedgerCheckRun.objects.filter(tenant=self.t).exists())

    def test_serial_product_with_accessory_stock_is_not_double_counted(self):
        StockBalance.objects.create(
            tenant=self.t, product=self.c.phone, warehouse=self.c.wh, qty=3,
            weighted_avg_cost=D("20000"),
        )
        take_snapshot(self.t)
        rows = by_key(StockSnapshot.objects.filter(tenant=self.t), self.c)
        self.assertEqual(rows[("甲湳雅店", "甲 iPhone 15 128GB 黑", "in_stock")], (1, D("20000.00")))
        res = self.results()
        self.assertFalse(res["stock_balance_kind"]["ok"])
        self.assertIn("湳雅店:3", res["stock_balance_kind"]["samples"][0])

    def _phone(self, no):
        return ProductSerial.objects.get(tenant=self.t, serial_no=no)

    def test_serial_states_must_match_exact_counts(self):
        sold = self._phone("甲IMEI1")
        in_stock = self._phone("甲IMEI2")
        # 已退,但銷貨沒退掉
        ProductSerial.objects.filter(pk=sold.pk).update(status="returned", warehouse=self.c.wh)
        samples = self.results()["serial_record"]["samples"]
        self.assertTrue(any("甲IMEI1" in x and "有銷貨沒退" in x for x in samples), samples)
        # 已退,但完全沒有銷貨 / 銷退
        ProductSerial.objects.filter(pk=sold.pk).update(status="sold", warehouse=None)
        ProductSerial.objects.filter(pk=in_stock.pk).update(status="returned")
        samples = self.results()["serial_record"]["samples"]
        self.assertTrue(any("甲IMEI2" in x and "沒有有效的銷退" in x for x in samples), samples)
        ProductSerial.objects.filter(pk=in_stock.pk).update(status="in_stock")
        self.assertTrue(self.results()["serial_record"]["ok"])
        # 已售卻掛在兩張有效的銷貨
        from apps.sales.models import SalesOrderItemSerial
        link = SalesOrderItemSerial.objects.get(serial=sold)
        SalesOrderItemSerial.objects.create(tenant=self.t, item=link.item, serial=sold, line_pos=2)
        samples = self.results()["serial_record"]["samples"]
        self.assertTrue(any("2 張有效的銷貨" in x for x in samples), samples)

    def test_serial_numbers_are_kept_to_the_last_six(self):
        ProductSerial.objects.filter(tenant=self.t, serial_no="甲IMEI2").update(
            serial_no="354123456789012", warehouse=None)
        run = run_checks(self.t)
        sample = next(r for r in run.results if r["key"] == "serial_place")["samples"][0]
        self.assertIn("…789012", sample)
        self.assertNotIn("354123456789012", str(run.results))

    def test_more_returns_than_sales_is_caught(self):
        from apps.sales.models import SalesReturn, SalesReturnItemSerial

        so = SalesOrder.objects.get(tenant=self.t)
        line = SalesOrderItem.objects.get(so=so, product=self.c.phone)
        sr = SalesReturn.objects.create(tenant=self.t, original_so=so, warehouse=self.c.wh,
                                        payment_method="cash")
        for _ in range(2):
            item = SalesReturnItem.objects.create(
                tenant=self.t, sr=sr, original_item=line, product=self.c.phone, qty=1,
                unit_price=line.unit_price, amount=line.unit_price,
            )
            SalesReturnItemSerial.objects.create(tenant=self.t, item=item,
                                                 serial=self._phone("甲IMEI1"))
        samples = self.results()["serial_record"]["samples"]
        self.assertTrue(any("銷退比銷貨多" in x for x in samples), samples)

    def test_two_runners_take_turns(self):
        from django.db import OperationalError, connection, connections

        other = connections.create_connection("default")
        other.ensure_connection()
        self.addCleanup(other.close)
        import hashlib
        key = int.from_bytes(
            hashlib.sha256(f"mppos-ledger-daily:{self.t.pk}".encode()).digest()[:8], "big",
            signed=True,
        )
        with other.cursor() as cur:
            cur.execute("SELECT pg_advisory_lock(%s)", [key])
        with connection.cursor() as cur:
            cur.execute("SET lock_timeout = '300ms'")
        with self.assertRaises(OperationalError):
            take_snapshot(self.t)
        with self.assertRaises(OperationalError):
            run_checks(self.t)


class RoundTwoTests(TestCase):
    def setUp(self):
        self.c = shop()
        self.t = self.c.tenant

    def test_past_midnight_the_day_is_skipped_not_misdated(self):
        from datetime import timedelta

        yesterday = timezone.localdate() - timedelta(days=1)
        logs = []
        self.assertFalse(daily.run_for(self.t, None, logs.append, day=yesterday))
        self.assertFalse(StockSnapshotDay.objects.exists())
        self.assertFalse(LedgerCheckRun.objects.exists())
        self.assertTrue(any("過了午夜" in m for m in logs), logs)

    def test_each_company_reads_the_clock_on_its_own_turn(self):
        from unittest import mock

        with mock.patch.object(daily, "run_for", return_value=True) as spy:
            self.assertEqual(daily.run_due(force=True, tenants=[self.t]), [])
        self.assertIsNone(spy.call_args.args[1])        # 沒有把開始時間傳下去

    def test_tenant_command_reports_failure(self):
        from django.core.management import CommandError, call_command

        TenantMaintenance.objects.create(tenant=self.t, active=True, reason="資料還原中")
        with self.assertRaisesMessage(CommandError, "沒做成的公司:a"):
            call_command("run_daily_ledger", "--tenant", "a", "--now")


class DailySafetyTests(TestCase):
    def test_bad_closing_time_setting_falls_back(self):
        from datetime import time

        from django.test import override_settings

        with override_settings(LEDGER_DAILY_AT="半夜"):
            self.assertEqual(daily.daily_time(), time(23, 30))
        with override_settings(LEDGER_DAILY_AT="22:15"):
            self.assertEqual(daily.daily_time(), time(22, 15))

    def test_backup_worker_survives_a_failing_daily_run(self):
        from io import StringIO
        from unittest import mock

        from django.core.management import call_command

        out = StringIO()
        with mock.patch.object(daily, "run_due", side_effect=RuntimeError("壞掉")):
            call_command("run_backup_worker", "--once", stdout=out)
        self.assertIn("每日對帳失敗", out.getvalue())


class ApiTests(TestCase):
    def setUp(self):
        self.a = shop()
        self.b = shop("b", "乙")
        take_snapshot(self.a.tenant)
        run_checks(self.a.tenant)

    def test_company_admin_sees_own_results_only(self):
        r = self.a.admin.get("/api/v1/ledger/checks/")
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertTrue(body["latest"]["ok"])
        self.assertEqual(body["snapshot"]["qty"], 9)
        self.assertGreater(len(body["latest"]["results"]), 5)
        other = self.b.admin.get("/api/v1/ledger/checks/").json()
        self.assertIsNone(other["latest"])
        self.assertIsNone(other["snapshot"])

    def test_clerk_cannot_see(self):
        self.assertEqual(self.a.clerk.get("/api/v1/ledger/checks/").status_code, 403)


class RestoreTests(_Base):
    def test_snapshots_come_back_after_restore(self):
        take_snapshot(self.a.tenant)
        before = by_key(StockSnapshot.objects.filter(tenant=self.a.tenant), self.a)
        job = self.backup(self.a)
        import os
        import shutil
        saved = os.path.join(self.tmp, "saved.mppos-backup")
        shutil.copy(self.path(job), saved)
        StockSnapshot.objects.filter(tenant=self.a.tenant).delete()
        done = self.rollback(self.a, saved)
        self.assertEqual(done.status, RestoreJob.Status.DONE, done.error)
        self.a.reload()
        self.assertEqual(by_key(StockSnapshot.objects.filter(tenant=self.a.tenant), self.a), before)
