"""舊 POS 十年會員消費:匯入、對照、查詢、撤回的驗收(對接規格第 6 節)。

封存全部用 archive_builder 造的假資料,不用真實會員個資。
"""
import json
import shutil
import sqlite3
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.catalog.models import Category, Product
from apps.inventory.models import StockMovement, Warehouse
from apps.legacy import importer, mapping
from apps.legacy.archive import ArchiveError
from apps.legacy.models import (
    HistoryImportBatch,
    LegacyDocument,
    LegacyDocumentVersion,
    LegacyItem,
    LegacyMappingLog,
    LegacyMember,
    LegacyProductMap,
    LegacySourceException,
    LegacySourceSnapshot,
    LegacyStoreMap,
    MapStatus,
)
from apps.parties.models import Member
from apps.sales.models import SalesOrder
from apps.tenants.models import Tenant, UserProfile

from .archive_builder import ArchiveBuilder, doc, line

OLDER = ("2016-10-03", "2021-10-02")
NEWER = ("2021-10-03", "2026-10-03")
PERIOD = ("2016-10-03", "2026-10-03")


def _period(p):
    from datetime import date

    return tuple(date.fromisoformat(x) for x in p)


class _Base(TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.a = Tenant.objects.create(name="甲通訊行", code="a")
        self.b = Tenant.objects.create(name="乙通訊行", code="b")
        User = get_user_model()
        self.boss = User.objects.create_user("a-boss", password="pw-12345")
        UserProfile.objects.create(user=self.boss, tenant=self.a, role="tenant_admin",
                                   is_warehouse_locked=False)
        self.clerk = User.objects.create_user("a-clerk", password="pw-12345")
        UserProfile.objects.create(user=self.clerk, tenant=self.a, role="tenant_user")
        self.b_boss = User.objects.create_user("b-boss", password="pw-12345")
        UserProfile.objects.create(user=self.b_boss, tenant=self.b, role="tenant_admin",
                                   is_warehouse_locked=False)

    def client_for(self, user):
        c = APIClient()
        c.force_authenticate(user)
        return c

    def build(self, setup, root=None, **kw):
        b = ArchiveBuilder(root or (self.tmp / f"archive-{len(list(self.tmp.iterdir()))}"))
        setup(b)
        return b.finish(**kw)

    def run_import(self, root, tenant=None, write=True, **kw):
        kw.setdefault("reconciled_only", True)
        return importer.run(tenant or self.a, root, period=_period(PERIOD), write=write, **kw)


def standard(b: ArchiveBuilder):
    """兩批期間;一位會員兩期都有(共用精確編號);一位帶 Tab;一位來源差異。"""
    older, newer = b.batch(*OLDER), b.batch(*NEWER)
    padded = b.member("00          ", "王小明", "0912-345-678")
    tab = b.member("A\t12", "陳 Tab", "0922000111")
    zero = b.member("007", "林零", "0933000222")
    mismatch = b.member(" 81  ", "差異", "0944000333")
    b.period(older, padded, [
        doc("湳雅店", "E13", "1060213005", "2017-02-13", [
            line("A1", "手機/X", "1", "4500", 4500),
            line("A2", "保貼", "1", "250", 250),
            line("A2", "保貼", "1", "250", 250),          # 同一張單內一模一樣的列
        ]),
        doc("民生店", "F13", "1060214001", "2017-02-14", [line("A1", "手機/X", "-1", "1190", -1190)]),
    ])
    b.period(older, mismatch, [doc("湳雅店", "E11", "1080926001", "2019-09-26", [
        line("C1", "配件", "1", "490", 490), line("C2", "配件2", "1", "800", 800),
    ])], list_amount=2400)
    b.period(newer, padded, [doc("湳雅店", "E11", "1100101001", "2021-12-01", [
        line("B1", "皮套\n換行品名", "2", "", 0, remarks="\n-尾約金 客人"),     # 空白單價、零元
        line("B2", "退款", "1", "-100", -100),
    ])])
    b.period(newer, tab, [doc("亞太巨城", "E01", "1110101001", "2022-01-01",
                              [line("D1", "門號", "1", "21000", 21000)])])
    b.period(newer, zero, [doc("維修倉", "FS11", "1120101001", "2023-01-01",
                               [line("E1", "收購", "1", "400", 400)])])


class ImportTests(_Base):
    def test_dry_run_writes_nothing_and_reports_everything(self):
        root = self.build(standard)
        report = self.run_import(root, write=False)
        self.assertEqual(LegacyMember.objects.count() + LegacyDocument.objects.count(), 0)
        t = report["totals"]
        self.assertEqual((t["documents"], t["items"]), (5, 8))
        self.assertEqual((t["exception_members"], t["exception_documents"], t["exception_items"]),
                         (1, 1, 2))
        self.assertEqual(t["exception_difference_minor"], (1290 - 2400) * 100)
        self.assertEqual(report["mismatches"], [])
        # 兩批共有的那一位,第二批算「已存在」不是「新增」
        second = report["batches"][1]["effect"]
        self.assertEqual((second["members_new"], second["members_unchanged"]), (2, 1))

    def test_writing_needs_explicit_reconciled_only_when_source_differs(self):
        root = self.build(standard)
        with self.assertRaisesMessage(importer.ImportBlocked, "reconciled_only"):
            self.run_import(root, reconciled_only=False)
        self.assertFalse(HistoryImportBatch.objects.exists())

    def test_everything_round_trips_unchanged(self):
        root = self.build(standard)
        self.run_import(root)
        self.assertEqual(LegacyMember.objects.filter(tenant=self.a).count(), 4)
        self.assertEqual(LegacyDocument.objects.count(), 5)
        self.assertEqual(LegacyItem.objects.count(), 8)
        # 精確編號:空白、Tab、前導零原樣;顯示才去空白
        padded = LegacyMember.objects.get(source_member_id="00          ")
        self.assertEqual(padded.display_id, "00")
        self.assertTrue(LegacyMember.objects.filter(source_member_id="A\t12").exists())
        self.assertTrue(LegacyMember.objects.filter(source_member_id="007").exists())
        self.assertEqual(padded.phone_digits, "0912345678")
        # 同一張單內一模一樣的兩列都在
        first = LegacyDocument.objects.get(document_number_raw="1060213005")
        self.assertEqual(
            list(first.items.values_list("product_code_raw", "amount_minor")),
            [("A1", 450000), ("A2", 25000), ("A2", 25000)],
        )
        # 空白單價 = NULL(不補零)、零元、換行、負數都照原樣;淨額照單別正負
        blank = LegacyItem.objects.get(product_code_raw="B1")
        self.assertIsNone(blank.unit_price_minor)
        self.assertEqual((blank.amount_minor, blank.quantity_decimal), (0, "2"))
        self.assertEqual(blank.product_name_raw, "皮套\n換行品名")
        self.assertEqual(blank.remarks_raw, "\n-尾約金 客人")
        refund = LegacyDocument.objects.get(document_number_raw="1060214001")
        self.assertEqual((refund.report_amount_minor, refund.net_amount_minor), (-119000, 119000))
        fs11 = LegacyDocument.objects.get(document_type_raw="FS11")
        self.assertEqual(fs11.net_amount_minor, -40000)
        # 每一列的報表原文都留著
        self.assertEqual(json.loads(blank.source_row_json)[4], "皮套\n換行品名")

    def test_source_difference_is_kept_apart(self):
        root = self.build(standard)
        self.run_import(root)
        e = LegacySourceException.objects.get()
        self.assertEqual(
            (e.list_amount_minor, e.detail_net_amount_minor, e.difference_minor, e.line_count),
            (240000, 129000, -111000, 2),
        )
        self.assertEqual(len(json.loads(e.rows_json)), 2)
        self.assertEqual(e.status, "open")
        # 不進已核對的單據
        self.assertFalse(LegacyDocument.objects.filter(document_number_raw="1080926001").exists())
        # 但會員與快照都在
        self.assertTrue(LegacySourceSnapshot.objects.filter(legacy_member=e.legacy_member).exists())

    def test_rerun_adds_nothing(self):
        root = self.build(standard)
        self.run_import(root)
        before = (LegacyMember.objects.count(), LegacyDocument.objects.count(),
                  LegacyItem.objects.count(), LegacyDocumentVersion.objects.count(),
                  LegacySourceSnapshot.objects.count(), LegacySourceException.objects.count())
        report = self.run_import(root)
        after = (LegacyMember.objects.count(), LegacyDocument.objects.count(),
                 LegacyItem.objects.count(), LegacyDocumentVersion.objects.count(),
                 LegacySourceSnapshot.objects.count(), LegacySourceException.objects.count())
        self.assertEqual(before, after)
        self.assertEqual(sum(b["effect"]["documents_new"] for b in report["batches"]), 0)

    def test_no_side_effects_on_daily_operations(self):
        root = self.build(standard)
        self.run_import(root)
        self.assertEqual(SalesOrder.objects.count(), 0)
        self.assertEqual(StockMovement.objects.count(), 0)
        self.assertEqual(Member.objects.count(), 0)          # 不會自己建 MP 會員
        self.assertEqual(Product.objects.count(), 0)         # 舊商品不建假商品
        # 舊品號 / 店別 / 業務員:建好「未對照」的對照列,等人確認
        self.assertEqual(LegacyStoreMap.objects.filter(tenant=self.a).count(), 4)
        self.assertFalse(LegacyProductMap.objects.exclude(status=MapStatus.UNMAPPED).exists())

    def test_unknown_document_type_blocks_everything(self):
        def setup(b):
            standard(b)
            b.periods[-1].docs[0].kind = "X99"
        root = self.build(setup)
        with self.assertRaisesMessage(ArchiveError, "不認得的單別"):
            self.run_import(root)
        self.assertEqual(LegacyDocument.objects.count(), 0)
        self.assertEqual(LegacyMember.objects.count(), 0)

    def test_tampered_archives_are_refused(self):
        root = self.build(standard)

        def expect(message, mutate):
            work = self.tmp / f"t-{len(list(self.tmp.iterdir()))}"
            shutil.copytree(root, work)
            mutate(work)
            with self.assertRaisesMessage(ArchiveError, message):
                self.run_import(work, write=False)

        def flip_db(work):
            p = work / "database" / "ored-history.sqlite"
            data = bytearray(p.read_bytes())
            data[-1] ^= 1
            p.write_bytes(bytes(data))
        expect("封存資料庫的雜湊", flip_db)

        def payload(work):
            (work / "import-payloads" / "batch-1" / "normalized-records.json").write_text("{}")
        expect("匯入內容檔雜湊不符", payload)

        def resign(work, sql):
            p = work / "database" / "ored-history.sqlite"
            con = sqlite3.connect(p)
            con.execute(sql)
            con.commit()
            con.close()
            m = json.loads((work / "manifest.json").read_text())
            import hashlib
            m["database_sha256"] = hashlib.sha256(p.read_bytes()).hexdigest()
            (work / "manifest.json").write_text(json.dumps(m))

        expect("全文雜湊不符", lambda w: resign(
            w, "UPDATE source_snapshots SET raw_json = raw_json || ' ' WHERE id = 1"))
        expect("版本內容雜湊不符", lambda w: resign(
            w, "UPDATE document_versions SET rows_json = replace(rows_json, '4500', '4501')"))
        expect("明細正負", lambda w: resign(
            w, "UPDATE legacy_items SET net_sign = -1 WHERE document_id = 1"))
        # 標準化欄位被改、報表列原文沒動:逐欄核對抓得到
        expect("欄位跟報表列原文不一致", lambda w: resign(
            w, "UPDATE legacy_items SET amount_minor = amount_minor + 1 WHERE document_id = 1 "
               "AND item_ordinal = 1"))
        expect("欄位跟報表列原文不一致", lambda w: resign(
            w, "UPDATE legacy_items SET product_code_raw = 'OTHER' WHERE document_id = 1 "
               "AND item_ordinal = 1"))
        expect("單頭", lambda w: resign(
            w, "UPDATE legacy_documents SET store_name_raw = '別家店' WHERE id = 1"))
        # 單據掛到別的會員的快照上
        expect("別的會員", lambda w: resign(
            w, "UPDATE legacy_documents SET snapshot_id = (SELECT id FROM source_snapshots "
               "WHERE member_id != legacy_documents.member_id LIMIT 1) WHERE id = 1"))
        # 待核紀錄:差額、金額、單別都要重算
        expect("差額", lambda w: resign(
            w, "UPDATE source_amount_exceptions SET difference_minor = 0"))
        expect("明細金額或單據數", lambda w: resign(
            w, "UPDATE source_amount_exceptions SET detail_raw_amount_minor = 1"))
        expect("不認得的單別", lambda w: resign(
            w, "UPDATE source_amount_exceptions SET rows_json = replace(rows_json, 'E11', 'X99')"))
        expect("結構版本", lambda w: resign(
            w, "UPDATE archive_metadata SET value='4' WHERE key='archive_schema_version'"))
        expect("正負規則", lambda w: resign(
            w, "UPDATE archive_metadata SET value='{\"E01\":1}' WHERE key='net_sign_rule'"))

        def payload_drift(work):
            """匯入內容檔跟資料庫說法不同(雜湊都重簽過,只有逐筆比對抓得到)。"""
            import hashlib
            f = work / "import-payloads" / "batch-2" / "normalized-records.json"
            data = json.loads(f.read_text())
            data["lines"][0]["source_row_raw"][7] = "999999"
            f.write_text(json.dumps(data, ensure_ascii=False))
            digest = hashlib.sha256(f.read_bytes()).hexdigest()
            m = json.loads((work / "manifest.json").read_text())
            for entry in m["source_archives"]:
                if entry["import_batch_id"] == 2:
                    entry["import_payload_sha256"] = digest
            (work / "manifest.json").write_text(json.dumps(m))
            resign(work, f"UPDATE import_batches SET content_sha256 = '{digest}' WHERE id = 2")
        expect("跟匯入內容檔不一致", payload_drift)

        # 會員清單累計自己重算:已核對的人清單金額被改 → 拒絕(不是照封存的分類照收)
        expect("卻沒有被標成待核", lambda w: resign(
            w, "UPDATE member_list_snapshots SET list_amount_raw = '1.00' WHERE member_id = 1 "
               "AND import_batch_id = 1"))
        # 待核記的清單金額跟清單原文不一致
        expect("清單原文", lambda w: resign(
            w, "UPDATE source_amount_exceptions SET list_amount_minor = 100, "
               "difference_minor = detail_net_amount_minor - 100"))
        # 封存自己標的待核數跟實際不一致
        expect("待核會員數", lambda w: resign(
            w, "UPDATE archive_metadata SET value = '0' WHERE key = 'unresolved_source_member_count'"))
        # 報表列日期必須正好 8 位數字的合法日期(後面多東西、不存在的日期都不收)
        from apps.legacy.archive import ROW_WIDTH, row_document_key
        base = ["01", "E11", "N1", "P", "品", "1", "1", "1", "1", "0", "店", "20170213", "S", "", "", ""]
        self.assertEqual(row_document_key(base)[3], "2017-02-13")
        for bad in ["20170213x", "2017021", "20170230", "2017-02-13"]:
            row = list(base)
            row[11] = bad
            self.assertEqual(len(row), ROW_WIDTH)
            with self.assertRaises(ArchiveError):
                row_document_key(row)

        # 單據記的擷取時間跟它的快照時間不一致
        expect("快照時間不一致", lambda w: resign(
            w, "UPDATE legacy_documents SET last_captured_at = '2099-01-01T00:00:00.000Z' WHERE id = 1"))

        def payload_version(work):
            import hashlib
            f = work / "import-payloads" / "batch-1" / "normalized-records.json"
            data = json.loads(f.read_text())
            data["schema_version"] = 3
            f.write_text(json.dumps(data, ensure_ascii=False))
            digest = hashlib.sha256(f.read_bytes()).hexdigest()
            m = json.loads((work / "manifest.json").read_text())
            m["source_archives"][0]["import_payload_sha256"] = digest
            (work / "manifest.json").write_text(json.dumps(m))
            resign(work, f"UPDATE import_batches SET content_sha256 = '{digest}' WHERE id = 1")
        expect("格式版本", payload_version)

        def manifest_dup(work):
            m = json.loads((work / "manifest.json").read_text())
            m["source_archives"].append(dict(m["source_archives"][0]))
            (work / "manifest.json").write_text(json.dumps(m))
        expect("重複的批次編號", manifest_dup)

        def manifest_file(work):
            m = json.loads((work / "manifest.json").read_text())
            m["source_archives"][0]["import_payload_file"] = "import-payloads/other.json"
            (work / "manifest.json").write_text(json.dumps(m))
        expect("匯入內容檔跟封存資料庫不一致", manifest_file)

        def no_total(work):
            m = json.loads((work / "manifest.json").read_text())
            del m["counts"]["trusted_items"]
            (work / "manifest.json").write_text(json.dumps(m))
        expect("沒有這個核對值", no_total)

        def counts(work):
            m = json.loads((work / "manifest.json").read_text())
            m["counts"]["trusted_items"] += 1
            (work / "manifest.json").write_text(json.dumps(m))
        expect("核對值不一致", counts)

        with self.assertRaisesMessage(ArchiveError, "期間"):
            importer.run(self.a, root, period=_period(("2016-10-03", "2026-10-02")))
        self.assertEqual(LegacyDocument.objects.count(), 0)

    def _capture(self, name, period, lines, captured_at):
        """一份只有一批的封存(例如切換前的「補抓」),同一位會員、同一張單。"""
        def setup(b):
            batch = b.batch(*period)
            m = b.member("M1", "改單", "0955000111", captured_at=captured_at)
            b.period(batch, m, [doc("湳雅店", "E11", "1100930001", "2021-09-30", lines,
                                    captured_at=captured_at)], captured_at=captured_at)
        return self.build(setup, root=self.tmp / name), _period(period)

    def test_corrected_document_replaces_and_keeps_previous_version(self):
        """之後的補抓又擷取到同一張單、內容改過而且比較新:整張換掉,舊內容留在版本。
        撤回補抓那一批,整張換回原本的明細。"""
        first, p1 = self._capture("ten-years", ("2016-10-03", "2026-10-03"),
                                  [line("P1", "舊", "1", "100", 100)], "2026-10-03T00:00:00.000Z")
        later, p2 = self._capture("delta", ("2021-09-28", "2026-12-31"),
                                  [line("P1", "新", "1", "120", 120), line("P2", "加購", "1", "30", 30)],
                                  "2026-12-31T00:00:00.000Z")
        importer.run(self.a, first, period=p1, write=True)
        d = LegacyDocument.objects.get()
        self.assertEqual(d.report_amount_minor, 10000)
        importer.run(self.a, later, period=p2, write=True)
        d.refresh_from_db()
        self.assertEqual((d.report_amount_minor, d.item_count), (15000, 2))
        versions = list(d.versions.order_by("id"))
        self.assertEqual(len(versions), 2)
        self.assertIsNotNone(versions[0].superseded_at)
        self.assertEqual(json.loads(versions[0].items_json)[0]["amount_minor"], 10000)
        self.assertIsNone(versions[1].superseded_at)
        lm = LegacyMember.objects.get()
        self.assertEqual(lm.last_captured_at.year, 2026)

        delta = HistoryImportBatch.objects.get(period_end="2026-12-31")
        importer.rollback_batch(delta, self.boss)
        d.refresh_from_db()
        self.assertEqual((d.report_amount_minor, d.item_count), (10000, 1))
        self.assertEqual(list(d.items.values_list("product_name_raw", flat=True)), ["舊"])
        self.assertEqual(d.versions.count(), 1)
        delta.refresh_from_db()
        self.assertEqual(delta.status, HistoryImportBatch.Status.ROLLED_BACK)
        # 撤回後可以再匯一次,結果跟第一次一樣
        importer.run(self.a, later, period=p2, write=True)
        d.refresh_from_db()
        self.assertEqual(d.report_amount_minor, 15000)

    def test_identical_recapture_adds_a_version_but_changes_nothing(self):
        first, p1 = self._capture("ten-years", ("2016-10-03", "2026-10-03"),
                                  [line("P1", "同", "1", "100", 100)], "2026-10-03T00:00:00.000Z")
        later, p2 = self._capture("delta", ("2021-09-28", "2026-12-31"),
                                  [line("P1", "同", "1", "100", 100)], "2026-12-31T00:00:00.000Z")
        importer.run(self.a, first, period=p1, write=True)
        report = importer.run(self.a, later, period=p2, write=True)
        self.assertEqual(report["batches"][0]["effect"]["documents_unchanged"], 1)
        d = LegacyDocument.objects.get()
        self.assertEqual((d.item_count, d.versions.count()), (1, 2))
        # 單據改以較新的那次擷取為準(跟舊會員的最後擷取時間一致)
        lm = LegacyMember.objects.get()
        self.assertEqual(d.last_captured_at, lm.last_captured_at)
        self.assertEqual(d.versions.filter(superseded_at__isnull=True).count(), 1)
        # 撤回較早的那一批:單據改以補抓那一次為準,明細不動
        ten = HistoryImportBatch.objects.get(period_start="2016-10-03")
        importer.rollback_batch(ten, self.boss)
        d.refresh_from_db()
        self.assertEqual((d.item_count, d.report_amount_minor, d.versions.count()), (1, 10000, 1))
        self.assertEqual(d.first_batch.period_end.isoformat(), "2026-12-31")

    def test_undoing_an_identical_recapture_points_back_to_the_first_capture(self):
        first, p1 = self._capture("ten-years", ("2016-10-03", "2026-10-03"),
                                  [line("P1", "同", "1", "100", 100)], "2026-10-03T00:00:00.000Z")
        later, p2 = self._capture("delta", ("2021-09-28", "2026-12-31"),
                                  [line("P1", "同", "1", "100", 100)], "2026-12-31T00:00:00.000Z")
        importer.run(self.a, first, period=p1, write=True)
        importer.run(self.a, later, period=p2, write=True)
        importer.rollback_batch(HistoryImportBatch.objects.get(period_end="2026-12-31"), self.boss)
        d = LegacyDocument.objects.get()
        self.assertEqual(d.last_captured_at.isoformat()[:10], "2026-10-03")
        self.assertEqual((d.item_count, d.versions.count()), (1, 1))
        self.assertIsNone(d.versions.get().superseded_at)

    def test_product_map_keeps_the_latest_name_seen(self):
        first, p1 = self._capture("ten-years", ("2016-10-03", "2026-10-03"),
                                  [line("P1", "舊品名", "1", "100", 100)], "2026-10-03T00:00:00.000Z")
        later, p2 = self._capture("delta", ("2021-09-28", "2026-12-31"),
                                  [line("P1", "新品名", "1", "120", 120)], "2026-12-31T00:00:00.000Z")
        importer.run(self.a, first, period=p1, write=True)
        importer.run(self.a, later, period=p2, write=True)
        self.assertEqual(LegacyProductMap.objects.get(product_code_raw="P1").product_name_seen, "新品名")

    def test_rollback_restores_the_product_name_from_what_is_left(self):
        first, p1 = self._capture("ten-years", ("2016-10-03", "2026-10-03"),
                                  [line("P1", "舊品名", "1", "100", 100)], "2026-10-03T00:00:00.000Z")
        later, p2 = self._capture("delta", ("2021-09-28", "2026-12-31"),
                                  [line("P1", "新品名", "1", "120", 120)], "2026-12-31T00:00:00.000Z")
        importer.run(self.a, first, period=p1, write=True)
        importer.run(self.a, later, period=p2, write=True)
        importer.rollback_batch(HistoryImportBatch.objects.get(period_end="2026-12-31"), self.boss)
        pm = LegacyProductMap.objects.get(product_code_raw="P1")
        self.assertEqual(pm.product_name_seen, "舊品名")
        self.assertEqual(pm.product_name_seen_at.isoformat()[:10], "2026-10-03")

    def test_rollback_falls_back_to_the_latest_remaining_capture(self):
        """同內容擷取了三次(依序匯入 t1、t3、t0);撤回 t3 時應該退回剩下裡最新的 t1。"""
        t1, p1 = self._capture("t1", ("2016-10-03", "2026-10-03"),
                               [line("P1", "同", "1", "100", 100)], "2026-10-03T00:00:00.000Z")
        t3, p3 = self._capture("t3", ("2021-09-28", "2026-12-31"),
                               [line("P1", "同", "1", "100", 100)], "2026-12-31T00:00:00.000Z")
        t0, p0 = self._capture("t0", ("2016-10-03", "2026-09-30"),
                               [line("P1", "同", "1", "100", 100)], "2026-09-30T00:00:00.000Z")
        for root, period in [(t1, p1), (t3, p3), (t0, p0)]:
            importer.run(self.a, root, period=period, write=True)
        importer.rollback_batch(HistoryImportBatch.objects.get(period_end="2026-12-31"), self.boss)
        d = LegacyDocument.objects.get()
        self.assertEqual(d.last_captured_at.isoformat()[:10], "2026-10-03")

    def test_older_capture_imported_later_can_be_rolled_back_to(self):
        """先匯較新的 V3,再匯較舊、內容不同的 V1(只留成版本);撤回 V3 → 退回 V1 的內容。"""
        v3, p3 = self._capture("v3", ("2021-09-28", "2026-12-31"),
                               [line("P1", "新", "1", "120", 120)], "2026-12-31T00:00:00.000Z")
        v1, p1 = self._capture("v1", ("2016-10-03", "2026-10-03"),
                               [line("P1", "舊", "1", "100", 100), line("P2", "加", "1", "5", 5)],
                               "2026-10-03T00:00:00.000Z")
        importer.run(self.a, v3, period=p3, write=True)
        importer.run(self.a, v1, period=p1, write=True)
        d = LegacyDocument.objects.get()
        self.assertEqual(d.report_amount_minor, 12000)                # 較舊的不覆蓋
        importer.rollback_batch(HistoryImportBatch.objects.get(period_end="2026-12-31"), self.boss)
        d.refresh_from_db()
        self.assertEqual((d.report_amount_minor, d.item_count), (10500, 2))
        self.assertEqual(list(d.items.values_list("product_name_raw", flat=True)), ["舊", "加"])

    def test_rollback_clears_the_product_name_when_nothing_is_left(self):
        only, p1 = self._capture("only", ("2016-10-03", "2026-10-03"),
                                 [line("P1", "唯一", "1", "100", 100)], "2026-10-03T00:00:00.000Z")
        importer.run(self.a, only, period=p1, write=True)
        importer.rollback_batch(HistoryImportBatch.objects.get(), self.boss)
        pm = LegacyProductMap.objects.get(product_code_raw="P1")
        self.assertEqual((pm.product_name_seen, pm.product_name_seen_at), ("", None))

    def test_older_capture_does_not_overwrite_newer_content(self):
        newer, p2 = self._capture("delta", ("2021-09-28", "2026-12-31"),
                                  [line("P1", "新", "1", "120", 120)], "2026-12-31T00:00:00.000Z")
        older, p1 = self._capture("ten-years", ("2016-10-03", "2026-10-03"),
                                  [line("P1", "舊", "1", "100", 100)], "2026-10-03T00:00:00.000Z")
        importer.run(self.a, newer, period=p2, write=True)
        report = importer.run(self.a, older, period=p1, write=True)
        self.assertEqual(report["batches"][0]["effect"]["documents_older_capture"], 1)
        d = LegacyDocument.objects.get()
        self.assertEqual(d.report_amount_minor, 12000)
        self.assertEqual(d.versions.count(), 2)          # 舊的那次擷取也留成歷史版本

    def test_rollback_only_touches_that_batch(self):
        root = self.build(standard)
        self.run_import(root)
        older = HistoryImportBatch.objects.get(archive_batch_id=1)
        counts = importer.rollback_batch(older, self.boss)
        self.assertEqual(counts["documents_removed"], 2)
        # 只在較早期間出現的「差異」會員被移除;兩期都有的那位留著(改掛到較新的一批)
        self.assertFalse(LegacyMember.objects.filter(source_member_id=" 81  ").exists())
        padded = LegacyMember.objects.get(source_member_id="00          ")
        self.assertEqual(padded.first_batch.archive_batch_id, 2)
        self.assertEqual(LegacyDocument.objects.count(), 3)
        self.assertFalse(LegacySourceException.objects.exists())
        with self.assertRaisesMessage(importer.RollbackBlocked, "撤回過"):
            importer.rollback_batch(older, self.boss)

    def test_rollback_refuses_to_drop_a_confirmed_link(self):
        def setup(b):
            older = b.batch(*OLDER)
            b.batch(*NEWER)
            m = b.member("ONLY-OLD", "只在早期", "0966000111")
            b.period(older, m, [doc()])
        root = self.build(setup)
        self.run_import(root)
        lm = LegacyMember.objects.get()
        person = Member(tenant=self.a, name="只在早期", phone="0966000111")
        person.save()
        mapping.link_member(lm, person, self.boss)
        with self.assertRaisesMessage(importer.RollbackBlocked, "撤銷對照"):
            importer.rollback_batch(HistoryImportBatch.objects.get(archive_batch_id=1), self.boss)
        self.assertEqual(LegacyDocument.objects.count(), 1)       # 整個撤回都沒做

    def test_same_document_with_several_versions_in_one_archive_is_refused(self):
        """同一份封存裡同一張單有好幾個版本:哪一版生效不猜,整份拒絕(補抓請分開封存)。"""
        def setup(b):
            older, newer = b.batch(*OLDER), b.batch(*NEWER)
            m = b.member("M1", "改單", "0955000111")
            b.period(older, m, [doc("湳雅店", "E11", "1100930001", "2021-09-30",
                                    [line("P1", "舊", "1", "100", 100)],
                                    captured_at="2026-10-01T00:00:00.000Z")])
            b.period(newer, m, [doc("湳雅店", "E11", "1100930001", "2021-09-30",
                                    [line("P1", "新", "1", "120", 120)],
                                    captured_at="2026-10-03T00:00:00.000Z")])
        with self.assertRaisesMessage(ArchiveError, "多個版本"):
            self.run_import(self.build(setup), write=False)
        self.assertFalse(LegacyDocument.objects.exists())

    def test_values_that_do_not_fit_are_caught_before_writing(self):
        def setup(b):
            standard(b)
            b.members[1].source_id = "X" * 65          # 精確編號超過 64 字
        root = self.build(setup)
        with self.assertRaisesMessage(ArchiveError, "太長"):
            self.run_import(root)
        self.assertFalse(HistoryImportBatch.objects.exists())
        self.assertFalse(LegacyMember.objects.exists())

    def test_same_capture_time_with_different_content_is_a_conflict(self):
        first, p1 = self._capture("ten-years", ("2016-10-03", "2026-10-03"),
                                  [line("P1", "甲", "1", "100", 100)], "2026-10-03T00:00:00.000Z")
        other, p2 = self._capture("other", ("2021-09-28", "2026-12-31"),
                                  [line("P1", "乙", "1", "120", 120)], "2026-10-03T00:00:00.000Z")
        importer.run(self.a, first, period=p1, write=True)
        # 試算就要先講出來,不能等到真的寫入才發現
        with self.assertRaisesMessage(ArchiveError, "同一個擷取時間有兩種不同內容"):
            importer.run(self.a, other, period=p2)
        with self.assertRaisesMessage(ArchiveError, "同一個擷取時間有兩種不同內容"):
            importer.run(self.a, other, period=p2, write=True)
        self.assertEqual(LegacyDocument.objects.get().report_amount_minor, 10000)
        self.assertEqual(HistoryImportBatch.objects.count(), 1)

    def test_import_stops_if_the_company_starts_restoring(self):
        from apps.backup.models import RestoreJob, TenantMaintenance
        root = self.build(standard)
        job = RestoreJob.objects.create(tenant=self.a, status=RestoreJob.Status.QUEUED,
                                        file_sha256="0" * 64)
        TenantMaintenance.objects.create(tenant=self.a, active=True, restore_job=job,
                                         reason="資料還原中")
        with self.assertRaisesMessage(importer.ImportBlocked, "還原"):
            self.run_import(root)
        TenantMaintenance.objects.filter(tenant=self.a).update(active=False)
        # 還原在匯入途中發生:寫到一半的那位會員之後就停下
        real = importer._guard_against_restore
        calls = []

        def restored_midway(tenant, since):
            calls.append(1)
            # 第 1 次:開始寫之前;第 2 次:建立第一批;第 3 次:第一位會員;第 4 次:第二位會員
            if len(calls) == 4:
                from django.utils import timezone
                RestoreJob.objects.filter(pk=job.pk).update(
                    status=RestoreJob.Status.DONE, finished_at=timezone.now())
            return real(tenant, since)
        from unittest import mock
        with mock.patch.object(importer, "_guard_against_restore", restored_midway):
            with self.assertRaisesMessage(importer.ImportBlocked, "匯入途中被還原過"):
                self.run_import(root)
        self.assertEqual(LegacyMember.objects.count(), 1)       # 只有第一位寫進去,其餘停下
        with self.assertRaisesMessage(importer.RollbackBlocked, "還原"):
            TenantMaintenance.objects.filter(tenant=self.a).update(active=True)
            importer.rollback_batch(HistoryImportBatch.objects.first(), self.boss)

    def test_each_company_has_its_own_copy(self):
        root = self.build(standard)
        self.run_import(root, tenant=self.a)
        self.run_import(root, tenant=self.b)
        self.assertEqual(LegacyDocument.objects.filter(tenant=self.a).count(), 5)
        self.assertEqual(LegacyDocument.objects.filter(tenant=self.b).count(), 5)


class MappingTests(_Base):
    def setUp(self):
        super().setUp()
        self.run_import(self.build(standard))
        self.padded = LegacyMember.objects.get(tenant=self.a, source_member_id="00          ")

    def test_candidates_by_phone_only_suggest(self):
        wang = Member(tenant=self.a, name="王先生", phone="0912345678")
        wang.save()
        found = mapping.member_candidates(self.padded)
        self.assertEqual([(m.pk, how) for m, how in found], [(wang.pk, "phone")])
        self.padded.refresh_from_db()
        self.assertEqual(self.padded.status, MapStatus.UNMAPPED)          # 只列候選
        self.assertEqual([lm.pk for lm, _ in mapping.legacy_candidates(wang)], [self.padded.pk])

    def test_name_candidates_ignore_stray_spaces_in_the_source(self):
        LegacyMember.objects.filter(pk=self.padded.pk).update(name_raw="\t王小明  ", phone_digits="")
        wang = Member(tenant=self.a, name="王小明", phone="")
        wang.save()
        self.assertEqual([lm.pk for lm, _ in mapping.legacy_candidates(wang)], [self.padded.pk])

    def test_link_unlink_and_log(self):
        wang = Member(tenant=self.a, name="王先生", phone="0912345678")
        wang.save()
        mapping.link_member(self.padded, wang, self.boss, method="phone")
        self.padded.refresh_from_db()
        self.assertEqual((self.padded.member_id, self.padded.status), (wang.pk, "confirmed"))
        other = Member(tenant=self.a, name="別人", phone="")
        other.save()
        with self.assertRaisesMessage(mapping.MappingError, "先撤銷"):
            mapping.link_member(self.padded, other, self.boss)
        mapping.unlink_member(self.padded, self.boss, note="對錯人")
        self.padded.refresh_from_db()
        self.assertIsNone(self.padded.member_id)
        log = list(LegacyMappingLog.objects.filter(kind="member").values_list("action", flat=True))
        self.assertEqual(log, ["revoke", "confirm"])

    def test_platform_admin_cannot_use_the_company_admin_pages(self):
        root = get_user_model().objects.create_user("platform-root", password="pw-12345")
        UserProfile.objects.create(user=root, role="platform_admin", is_warehouse_locked=False)
        c = self.client_for(root)
        for url in [f"/api/v1/legacy/members/?tenant={self.a.pk}",
                    f"/api/v1/legacy/members/{self.padded.pk}/evidence/?tenant={self.a.pk}",
                    f"/api/v1/legacy/maps/products/?tenant={self.a.pk}",
                    f"/api/v1/legacy/exceptions/?tenant={self.a.pk}"]:
            self.assertEqual(c.get(url).status_code, 403, url)
        r = c.post(f"/api/v1/legacy/members/{self.padded.pk}/create-member/?tenant={self.a.pk}")
        self.assertEqual(r.status_code, 403)
        doc = LegacyDocument.objects.filter(tenant=self.a).first()
        r = c.get(f"/api/v1/legacy/history/{doc.pk}/?tenant={self.a.pk}")
        self.assertEqual(r.status_code, 404)        # 也不能用「管理員」身分看原文

    def test_create_member_refuses_when_same_phone_exists(self):
        lm, member = mapping.create_member_from_legacy(self.padded, self.boss)
        self.assertEqual((member.name, member.phone), ("王小明", "0912-345-678"))
        self.assertEqual(lm.method, "created")
        same = LegacyMember.objects.create(
            tenant=self.a, source_system=lm.source_system, source_member_id="X",
            source_member_id_raw="X", name_raw="另一個號", phone_raw="0912345678",
            phone_digits="0912345678", last_captured_at=lm.last_captured_at,
            first_batch=lm.first_batch,
        )
        with self.assertRaisesMessage(mapping.MappingError, "同電話"):
            mapping.create_member_from_legacy(same, self.boss)

    def test_create_member_refuses_a_short_phone_that_already_exists(self):
        """電話不到 8 碼(例如室內電話)也一樣:同公司已經有同電話的人就不再建。"""
        LegacyMember.objects.filter(pk=self.padded.pk).update(phone_raw="5551234", phone_digits="5551234")
        self.padded.refresh_from_db()
        existing = Member(tenant=self.a, name="別名", phone="555-1234")
        existing.save()
        with self.assertRaisesMessage(mapping.MappingError, "同電話"):
            mapping.create_member_from_legacy(self.padded, self.boss)
        self.assertEqual(Member.objects.filter(tenant=self.a).count(), 1)

    def test_cannot_link_across_companies(self):
        stranger = Member(tenant=self.b, name="乙的人", phone="0912345678")
        stranger.save()
        with self.assertRaisesMessage(mapping.MappingError, "別家公司"):
            mapping.link_member(self.padded, stranger, self.boss)
        store = LegacyStoreMap.objects.filter(tenant=self.a).first()
        b_store = Warehouse.objects.create(tenant=self.b, code="w1", name="湳雅店")
        with self.assertRaisesMessage(mapping.MappingError, "別家公司"):
            mapping.confirm_map("store", store, b_store, self.boss)

    def test_store_and_product_maps(self):
        nanya = Warehouse.objects.create(tenant=self.a, code="w1", name="湳雅店")
        store = LegacyStoreMap.objects.get(tenant=self.a, store_name_raw="湳雅店")
        self.assertEqual(mapping.store_candidates(store), [nanya])
        mapping.confirm_map("store", store, nanya, self.boss)
        cat = Category.objects.create(tenant=self.a, code="LC", name="皮套")
        p = Product.objects.create(tenant=self.a, category=cat, name="保貼", barcode="A2",
                                   requires_serial=False)
        pm = LegacyProductMap.objects.get(tenant=self.a, product_code_raw="A2")
        found = mapping.product_candidates(pm)
        self.assertEqual((found[0][0].pk, found[0][1]), (p.pk, "code"))
        mapping.confirm_map("product", pm, p, self.boss, method="code")
        # 透過對照,舊明細可以照 MP 的門市 / 品類查
        from django.db.models import Sum
        by_cat = dict(
            LegacyItem.objects.filter(tenant=self.a)
            .values_list("product_map__product__category__name")
            .annotate(s=Sum("amount_minor"))
        )
        self.assertEqual(by_cat["皮套"], 50000)
        by_store = dict(
            LegacyDocument.objects.filter(tenant=self.a)
            .values_list("store_map__warehouse__name").annotate(s=Sum("net_amount_minor"))
        )
        self.assertEqual(by_store["湳雅店"], (4500 + 250 + 250 - 100) * 100)
        self.assertIsNone(by_store.get("民生店"))
        self.assertIn(None, by_store)                                    # 未對照的另外一組
        mapping.revoke_map("product", pm, self.boss)
        pm.refresh_from_db()
        self.assertEqual((pm.status, pm.product_id), ("unmapped", None))


class ApiTests(_Base):
    def setUp(self):
        super().setUp()

        def setup(b):
            standard(b)
            older = 1
            big = b.member("BIG", "很多單", "0977000111")
            b.period(older, big, [
                doc("民生店", "E11" if i % 10 else "F11", f"2000{i:06d}", f"2018-{1 + i % 12:02d}-{1 + i % 28:02d}",
                    [line("Z1", "配件", "1", "10", 10 + i)])
                for i in range(250)
            ])
        self.run_import(self.build(setup))
        self.member = Member(tenant=self.a, name="很多單", phone="0977000111")
        self.member.save()
        self.big = LegacyMember.objects.get(tenant=self.a, source_member_id="BIG")
        self.admin = self.client_for(self.boss)
        self.staff = self.client_for(self.clerk)

    def test_history_shows_only_confirmed_links(self):
        r = self.staff.get(f"/api/v1/legacy/history/?member={self.member.pk}")
        self.assertEqual((r.status_code, r.json()["count"]), (200, 0))
        mapping.link_member(self.big, self.member, self.boss)
        r = self.staff.get(f"/api/v1/legacy/history/?member={self.member.pk}")
        self.assertEqual(r.json()["count"], 250)

    def test_totals_cover_every_page_not_just_the_first(self):
        mapping.link_member(self.big, self.member, self.boss)
        r = self.staff.get(f"/api/v1/legacy/history/?member={self.member.pk}&page_size=50")
        body = r.json()
        self.assertEqual(len(body["results"]), 50)
        expected_net = sum((10 + i) * (1 if i % 10 else -1) for i in range(250)) * 100
        self.assertEqual(body["summary"]["documents"], 250)
        self.assertEqual(body["summary"]["net_amount"]["minor"], expected_net)
        seen = set()
        for page in range(1, 6):
            r = self.staff.get(
                f"/api/v1/legacy/history/?member={self.member.pk}&page_size=50&page={page}")
            seen |= {row["id"] for row in r.json()["results"]}
        self.assertEqual(len(seen), 250)
        r = self.staff.get(
            f"/api/v1/legacy/history/?member={self.member.pk}&page_size=500")
        self.assertEqual(len(r.json()["results"]), 200)          # 一頁最多 200
        # 篩選:合計跟著篩選變
        r = self.staff.get(f"/api/v1/legacy/history/?member={self.member.pk}&doc_type=F11")
        self.assertEqual(r.json()["summary"]["documents"], 25)
        r = self.staff.get(
            f"/api/v1/legacy/history/?member={self.member.pk}&date_from=2018-01-01&date_to=2018-01-31")
        self.assertTrue(all(row["document_date"].startswith("2018-01") for row in r.json()["results"]))
        r = self.staff.get(f"/api/v1/legacy/history/?member={self.member.pk}&date_from=昨天")
        self.assertEqual(r.status_code, 400)

    def test_document_detail_and_evidence_permissions(self):
        doc_id = LegacyDocument.objects.filter(legacy_member=self.big).first().pk
        url = f"/api/v1/legacy/history/{doc_id}/?member={self.member.pk}"
        self.assertEqual(self.staff.get(url).status_code, 404)        # 還沒對照
        r = self.admin.get(f"/api/v1/legacy/history/{doc_id}/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("source_row", r.json()["items"][0])
        mapping.link_member(self.big, self.member, self.boss)
        r = self.staff.get(url)
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("source_row", r.json()["items"][0])         # 原文只給管理員
        # 不帶會員、或帶另一位會員:不能拿單據編號翻別人的舊單
        self.assertEqual(self.staff.get(f"/api/v1/legacy/history/{doc_id}/").status_code, 404)
        someone = Member(tenant=self.a, name="別人", phone="")
        someone.save()
        self.assertEqual(self.staff.get(
            f"/api/v1/legacy/history/{doc_id}/?member={someone.pk}").status_code, 404)
        for url in ["/api/v1/legacy/members/", f"/api/v1/legacy/members/{self.big.pk}/evidence/",
                    "/api/v1/legacy/exceptions/", "/api/v1/legacy/maps/products/",
                    "/api/v1/legacy/batches/"]:
            self.assertEqual(self.staff.get(url).status_code, 403, url)
        r = self.admin.get(f"/api/v1/legacy/members/{self.big.pk}/evidence/")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["snapshots"][0]["raw_sha256"])

    def test_other_company_sees_nothing(self):
        mapping.link_member(self.big, self.member, self.boss)
        other = self.client_for(self.b_boss)
        doc_id = LegacyDocument.objects.filter(legacy_member=self.big).first().pk
        self.assertEqual(other.get(f"/api/v1/legacy/history/?member={self.member.pk}").status_code, 404)
        self.assertEqual(other.get(f"/api/v1/legacy/history/{doc_id}/").status_code, 404)
        self.assertEqual(other.get(f"/api/v1/legacy/members/{self.big.pk}/").status_code, 404)
        r = other.post(f"/api/v1/legacy/members/{self.big.pk}/link/", {"member": self.member.pk},
                       format="json")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(other.get("/api/v1/legacy/members/").json()["count"], 0)

    def test_pending_source_difference_is_flagged_on_the_member_page(self):
        lm = LegacyMember.objects.get(tenant=self.a, source_member_id=" 81  ")
        person = Member(tenant=self.a, name="差異", phone="0944000333")
        person.save()
        mapping.link_member(lm, person, self.boss)
        r = self.staff.get(f"/api/v1/legacy/history/?member={person.pk}")
        body = r.json()
        self.assertEqual(body["summary"]["documents"], 0)            # 待核不算進已核對
        self.assertEqual((body["pending"]["count"], body["pending"]["items"]), (1, 2))

    def test_admin_mapping_endpoints(self):
        r = self.admin.get(f"/api/v1/legacy/candidates/?member={self.member.pk}")
        self.assertEqual([row["id"] for row in r.json()["results"]], [self.big.pk])
        r = self.admin.post(f"/api/v1/legacy/members/{self.big.pk}/link/",
                            {"member": self.member.pk, "method": "phone"}, format="json")
        self.assertEqual((r.status_code, r.json()["status"]), (200, "confirmed"))
        r = self.admin.get("/api/v1/legacy/members/?status=confirmed")
        self.assertEqual(r.json()["summary"]["confirmed"], 1)
        r = self.admin.post(f"/api/v1/legacy/members/{self.big.pk}/unlink/", {}, format="json")
        self.assertEqual(r.json()["status"], "unmapped")
        r = self.admin.get("/api/v1/legacy/maps/stores/")
        rows = {row["key"]: row for row in r.json()["results"]}
        self.assertEqual(rows["民生店"]["items"], 251)
        nanya = Warehouse.objects.create(tenant=self.a, code="w1", name="湳雅店")
        sid = rows["湳雅店"]["id"]
        r = self.admin.get(f"/api/v1/legacy/maps/stores/{sid}/candidates/")
        self.assertEqual(r.json()["results"][0]["id"], nanya.pk)
        r = self.admin.post(f"/api/v1/legacy/maps/stores/{sid}/confirm/", {"target": nanya.pk},
                            format="json")
        self.assertEqual((r.status_code, r.json()["status"]), (200, "confirmed"))
        b_store = Warehouse.objects.create(tenant=self.b, code="w9", name="乙店")
        r = self.admin.post(f"/api/v1/legacy/maps/stores/{rows['民生店']['id']}/confirm/",
                            {"target": b_store.pk}, format="json")
        self.assertEqual(r.status_code, 400)                        # 別家公司的門市找不到
        e = LegacySourceException.objects.get(tenant=self.a)
        r = self.admin.post(f"/api/v1/legacy/exceptions/{e.pk}/resolve/", {"note": "查過"},
                            format="json")
        self.assertEqual(r.status_code, 400)                        # 沒有新的來源證據不能結案
        r = self.admin.post(f"/api/v1/legacy/exceptions/{e.pk}/resolve/",
                            {"note": None, "evidence": None}, format="json")
        self.assertEqual(r.status_code, 400)                        # null 不能冒充證據
        r = self.admin.post(f"/api/v1/legacy/exceptions/{e.pk}/resolve/",
                            {"note": "查過", "evidence": "重查截圖與報表"}, format="json")
        self.assertEqual(r.json()["status"], "resolved")
        self.assertEqual((r.json()["resolved_by"], r.json()["resolution_evidence"]),
                         ("a-boss", "重查截圖與報表"))
        r = self.admin.post(f"/api/v1/legacy/exceptions/{e.pk}/resolve/",
                            {"note": "再結一次", "evidence": "別的"}, format="json")
        self.assertEqual(r.status_code, 409)
        e.refresh_from_db()
        self.assertEqual(e.difference_minor, -111000)              # 原始數字不改
