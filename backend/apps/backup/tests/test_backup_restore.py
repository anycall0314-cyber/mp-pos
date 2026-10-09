"""公司備份與還原的演練(開發計畫 §10.2)。

都用 TransactionTestCase:匯出要自己開 REPEATABLE READ 交易,不能被測試框架的
外層交易包住;併發與故障注入也需要真的提交。只在 PostgreSQL 上有意義。
"""
import json
import os
import shutil
import tempfile
import threading
import zipfile
from datetime import timedelta
from unittest import mock

from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.files.base import ContentFile
from django.db import connection, connections
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from apps.backup import container, export, jobs, keys, registry, restore
from apps.backup.models import (
    BackupAuditLog,
    BackupJob,
    BackupKey,
    RestoreJob,
    TenantMaintenance,
)
from apps.catalog.models import Product
from apps.identity.models import IntakeDocument, ProductAlias
from apps.identity.product_match import find_candidates
from apps.inventory.models import ProductSerial, StockBalance, StockMovement, Warehouse
from apps.purchasing.models import PurchaseOrder
from apps.sales.models import SalesOrder
from apps.tenants.models import (
    DocNumberFloor,
    InvoiceTrack,
    InvoiceType,
    Tenant,
    UserProfile,
)
from apps.transfers.models import TransferOrder

from .factory import STANDARD_NAME, Company, standard_company

FOUR_PHRASINGS = [
    "reno16 皮套 藍色", "reno-16 側翻皮套 藍", "reno16/側翻/藍", "reno16/皮套/側翻藍",
]


def business_view(tenant):
    """一家公司「帳上長什麼樣」,不含任何資料庫 id。還原前後拿來整份比對。"""
    def money(v):
        return str(v)

    return {
        "warehouses": sorted(Warehouse.objects.filter(tenant=tenant).values_list("code", "name")),
        "products": sorted(
            Product.objects.filter(tenant=tenant)
            .values_list("sku", "name", "is_active", "weighted_avg_cost")
        ),
        "stock": sorted(
            (w, p, q, money(c)) for w, p, q, c in StockBalance.objects.filter(tenant=tenant)
            .values_list("warehouse__code", "product__name", "qty", "weighted_avg_cost")
        ),
        "serials": sorted(
            ProductSerial.objects.filter(tenant=tenant).values_list(
                "serial_no", "status", "warehouse__code", "purchase_unit_cost",
                "product__name",
            )
        ),
        "movements": sorted(
            (p or "", f or "", t or "", str(rest))
            for p, f, t, *rest in StockMovement.objects.filter(tenant=tenant).values_list(
                "product__name", "from_warehouse__code", "to_warehouse__code",
                "serial__serial_no",
            )
        ),
        "purchases": sorted(
            (po.no, po.supplier.name, po.warehouse.code, po.is_void, sorted(
                po.items.values_list("product__name", "qty", "unit_price")
            )) for po in PurchaseOrder.objects.filter(tenant=tenant)
        ),
        "sales": sorted(
            (so.no, so.customer.name, so.warehouse.code, money(so.total), so.is_void,
             so.sales_person.name if so.sales_person else "",
             sorted(so.items.values_list("product__name", "qty", "unit_price", "cost_at_post")),
             sorted(so.payments.values_list("method", "amount")))
            for so in SalesOrder.objects.filter(tenant=tenant)
        ),
        "transfers": sorted(
            (t.no, t.from_warehouse.code, t.to_warehouse.code, t.status, sorted(
                t.items.values_list("product__name", "qty")
            )) for t in TransferOrder.objects.filter(tenant=tenant)
        ),
        "aliases": sorted(
            ProductAlias.objects.filter(tenant=tenant)
            .values_list("value", "product__name", "verified", "is_active")
        ),
        "documents": sorted(
            (d.original_filename, d.content_hash, d.image.read() if d.image else b"")
            for d in IntakeDocument.objects.filter(tenant=tenant)
        ),
        "invoice_tracks": sorted(
            InvoiceTrack.objects.filter(tenant=tenant)
            .values_list("prefix", "range_start", "range_end")
        ),
    }


def raw_digest(tenant):
    """每張表逐列內容的指紋(不含 id / 外鍵)。用來證明「一個位元都沒變」。"""
    out = {}
    for model in registry.ordered_company_models():
        cols = [f.attname for f in restore._non_relational(model)]
        out[registry.label_of(model)] = restore._table_digest(
            __import__("hashlib").sha256(export.dump_json(row)).digest()
            for row in model._base_manager.filter(tenant=tenant).values(*cols)
        )
    return out


class _Base(TransactionTestCase):
    def setUp(self):
        if connection.vendor != "postgresql":
            self.skipTest("需要 PostgreSQL")
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        override = override_settings(
            MEDIA_ROOT=os.path.join(self.tmp, "media"),
            BACKUP_ROOT=os.path.join(self.tmp, "backup_store"),
            BACKUP_RESTORE_GRACE_SECONDS=0,
        )
        override.enable()
        self.addCleanup(override.disable)
        self.a = standard_company("a", "甲通訊行", "甲")
        self.b = standard_company("b", "乙通訊行", "乙")
        self.key_a, self.credential_a = keys.create_key(self.a.tenant, self.a.admin_user)
        self.key_b, self.credential_b = keys.create_key(self.b.tenant, self.b.admin_user)

    # ── 小工具 ──
    def backup(self, company):
        job, _ = jobs.request_backup(company.tenant, company.admin_user)
        claimed = jobs.claim_next()
        self.assertEqual(claimed.pk, job.pk)
        job = jobs.run_backup(claimed)
        self.assertEqual(job.status, BackupJob.Status.VERIFIED, job.error)
        return job

    def path(self, job):
        return str(jobs.file_path(job))

    def other_worker_holds(self, kind, pk):
        """模擬「另一個還活著的 worker 正在做這個工作」:用另一條資料庫連線握著
        這個工作的鎖。回傳的函式呼叫後 = 那個 worker 死了(連線斷掉,鎖自動放開)。"""
        other = connections.create_connection("default")
        other.ensure_connection()
        with other.cursor() as cur:
            cur.execute("SELECT pg_advisory_lock(%s)", [jobs._lock_id(kind, pk)])
        self.addCleanup(other.close)
        return other.close

    def unpack(self, job, credential):
        """把備份解開成 {檔名: bytes}。"""
        plain = os.path.join(self.tmp, f"plain-{job.pk}.zip")
        container.decrypt_file(self.path(job), plain, keys.parse_secret(credential))
        with zipfile.ZipFile(plain) as zf:
            return {name: zf.read(name) for name in zf.namelist()}

    def repack(self, job, credential, mutate):
        """解開 → 改 → 用同一組憑證包回去。拿來做「被動過手腳的備份檔」。"""
        entries = self.unpack(job, credential)
        mutate(entries)
        plain = os.path.join(self.tmp, "tampered.zip")
        with zipfile.ZipFile(plain, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, data in entries.items():
                zf.writestr(name, data)
        out = os.path.join(self.tmp, f"tampered-{os.urandom(4).hex()}.mppos-backup")
        container.encrypt_file(plain, out, keys.parse_secret(credential))
        return out

    def upload(self, path):
        with open(path, "rb") as f:
            return SimpleUploadedFile("backup.mppos-backup", f.read())

    def rollback(self, company, path, credential=""):
        """上傳 → 預檢 → 確認 → 執行。回傳跑完的 RestoreJob。"""
        job = restore.stage_upload(company.tenant, self.upload(path), company.admin_user,
                                   credential=credential)
        if job.status != RestoreJob.Status.PRECHECKED:
            return job
        restore.confirm(job, company.admin_user)
        claimed = restore.claim_next()
        self.assertEqual(claimed.pk, job.pk)
        return restore.run_restore(claimed)


class BackupContentTests(_Base):
    def test_whole_company_both_stores_and_nothing_from_the_other(self):
        job = self.backup(self.a)
        entries = self.unpack(job, self.credential_a)
        manifest = json.loads(entries["manifest.json"])

        # 兩家店都在,不看「畫面上選哪一家」
        self.assertEqual([w["name"] for w in manifest["warehouses"]], ["甲湳雅店", "甲民生店"])
        balances = [json.loads(l) for l in entries["data/inventory.StockBalance.jsonl"].splitlines()]
        self.assertEqual(sorted(b["qty"] for b in balances), [4, 4])
        # 零庫存與停用的商品也在
        names = entries["data/catalog.Product.jsonl"].decode()
        self.assertIn("停用的舊皮套", names)
        # 筆數清單跟實際一致
        for label, n in manifest["tables"].items():
            self.assertEqual(len(entries[f"data/{label}.jsonl"].splitlines()), n, label)
        self.assertEqual(manifest["tables"]["sales.SalesOrder"], 1)
        self.assertEqual(manifest["tables"]["transfers.TransferOrder"], 1)

        # 乙公司的任何東西都不在裡面:資料、帳號、附件
        blob = b"\n".join(entries.values())
        for marker in ["乙", "b-boss", "b-clerk"]:
            self.assertNotIn(marker.encode(), blob, marker)
        # 也沒有密碼、token、連線字串、主機路徑
        accounts = json.loads(entries["accounts.json"])
        self.assertEqual(sorted(a["username"] for a in accounts), ["a-boss", "a-clerk"])
        self.assertTrue(all("password" not in a for a in accounts))
        for forbidden in [b"pbkdf2_", b"postgres://", self.tmp.encode()]:
            self.assertNotIn(forbidden, blob)
        self.assertNotIn(self.credential_a.encode(), blob)

    def test_file_is_encrypted_and_needs_this_companys_credential(self):
        job = self.backup(self.a)
        with open(self.path(job), "rb") as f:
            raw = f.read()
        for marker in ["甲通訊行", "IMEI001", "0912000111"]:
            self.assertNotIn(marker.encode(), raw, marker)
        with self.assertRaisesMessage(container.ContainerError, "復原憑證不正確"):
            self.unpack(job, self.credential_b)
        # 不放在會被網頁伺服器直接送出的目錄
        self.assertFalse(self.path(job).startswith(str(default_storage.location)))

    def test_attachment_is_inside_the_backup(self):
        job = self.backup(self.a)
        entries = self.unpack(job, self.credential_a)
        att = json.loads(entries["manifest.json"])["attachments"]
        self.assertEqual(len(att), 1)
        self.assertEqual(entries[f"files/{att[0]['index']}"], "甲 的進貨單原圖".encode() * 50)

    def test_accounts_of_outsiders_stay_out_of_the_backup(self):
        """平台管理員代操作過的單:備份裡不能出現那個帳號的名稱,那一欄留空。"""
        from django.contrib.auth import get_user_model
        outsider = get_user_model().objects.create_user("platform-root", password="pw-12345")
        UserProfile.objects.create(user=outsider, role="platform_admin")
        SalesOrder.objects.filter(tenant=self.a.tenant).update(created_by=outsider)
        other = self.b.admin_user                      # 別家公司的人
        PurchaseOrder.objects.filter(tenant=self.a.tenant).update(created_by=other)

        entries = self.unpack(self.backup(self.a), self.credential_a)
        accounts = json.loads(entries["accounts.json"])
        self.assertEqual(
            sorted(a["username"] for a in accounts), ["a-boss", "a-clerk"])
        blob = b"".join(entries.values())
        self.assertNotIn(b"platform-root", blob)
        self.assertNotIn(b"b-boss", blob)
        for name in ("sales.SalesOrder", "purchasing.PurchaseOrder"):
            for line in entries[f"data/{name}.jsonl"].splitlines():
                self.assertIsNone(json.loads(line)["created_by_id"])

    def test_missing_or_changed_attachment_fails_the_backup(self):
        doc = IntakeDocument.objects.get(tenant=self.a.tenant)
        original = doc.image.path
        os.rename(original, original + ".gone")
        job, _ = jobs.request_backup(self.a.tenant, self.a.admin_user)
        job = jobs.run_backup(jobs.claim_next())
        self.assertEqual(job.status, BackupJob.Status.FAILED)
        self.assertIn("附件遺失", job.error)
        self.assertEqual(job.file_name, "")
        with self.assertRaises(jobs.BackupError):
            jobs.file_path(job)
        # 沒有留下半份檔
        leftovers = [
            f for _, _, files in os.walk(os.path.join(self.tmp, "backup_store")) for f in files
        ]
        self.assertEqual(leftovers, [])

        os.rename(original + ".gone", original)
        with open(original, "ab") as f:
            f.write(b"tampered")
        jobs.request_backup(self.a.tenant, self.a.admin_user)
        job = jobs.run_backup(jobs.claim_next())
        self.assertEqual(job.status, BackupJob.Status.FAILED)
        self.assertIn("內容跟上傳時不一樣", job.error)

    def test_snapshot_is_one_point_in_time(self):
        """匯出途中有人開單:備份裡要嘛整張單都在,要嘛整張都不在。"""
        before = {
            "orders": SalesOrder.objects.filter(tenant=self.a.tenant).count(),
            "case_qty": StockBalance.objects.get(
                tenant=self.a.tenant, warehouse=self.a.wh, product=self.a.case).qty,
        }
        real_order = registry.ordered_company_models
        sold = []

        def order_with_a_sale_in_the_middle():
            for model in real_order():
                yield model
                if registry.label_of(model) == "sales.SalesOrder" and not sold:
                    # 銷貨單頭已經匯出、明細與庫存還沒 —— 這時候別的連線開一張單並提交
                    t = threading.Thread(target=self._sell_in_other_connection, args=(sold,))
                    t.start()
                    t.join(timeout=30)

        with mock.patch.object(
            registry, "ordered_company_models", order_with_a_sale_in_the_middle
        ):
            job = self.backup(self.a)
        self.assertEqual(sold, ["ok"])                    # 那張單真的開成了
        self.assertEqual(
            SalesOrder.objects.filter(tenant=self.a.tenant).count(), before["orders"] + 1
        )

        entries = self.unpack(job, self.credential_a)
        rows = lambda label: [  # noqa: E731
            json.loads(l) for l in entries[f"data/{label}.jsonl"].splitlines()
        ]
        order_ids = {r["id"] for r in rows("sales.SalesOrder")}
        self.assertEqual(len(order_ids), before["orders"])
        # 明細、付款都只屬於備份裡有的那幾張單
        self.assertTrue(all(r["so_id"] in order_ids for r in rows("sales.SalesOrderItem")))
        self.assertTrue(all(r["so_id"] in order_ids for r in rows("sales.SalesOrderPayment")))
        # 庫存是開單「之前」的數字,跟單據對得起來
        qty = [
            r["qty"] for r in rows("inventory.StockBalance")
            if r["warehouse_id"] == self.a.wh.id and r["product_id"] == self.a.case.id
        ]
        self.assertEqual(qty, [before["case_qty"]])

    def _sell_in_other_connection(self, sold):
        try:
            self.a.sell(case_qty=1)
            sold.append("ok")
        except Exception as exc:  # noqa: BLE001
            sold.append(repr(exc))
        finally:
            connection.close()


class BackupJobTests(_Base):
    def test_double_click_and_retry_give_the_same_job(self):
        j1, created1 = jobs.request_backup(self.a.tenant, self.a.admin_user, idempotency_key="k1")
        j2, created2 = jobs.request_backup(self.a.tenant, self.a.admin_user, idempotency_key="k1")
        j3, created3 = jobs.request_backup(self.a.tenant, self.a.admin_user, idempotency_key="k2")
        self.assertEqual((created1, created2, created3), (True, False, False))
        self.assertEqual({j1.pk, j2.pk, j3.pk}, {j1.pk})
        # 做完之後,同一個重送鍵還是拿到同一筆,不會再備份一次
        jobs.run_backup(jobs.claim_next())
        j4, created4 = jobs.request_backup(self.a.tenant, self.a.admin_user, idempotency_key="k1")
        self.assertEqual((j4.pk, created4), (j1.pk, False))
        # 別家公司不受影響
        jb, created_b = jobs.request_backup(self.b.tenant, self.b.admin_user, idempotency_key="k1")
        self.assertTrue(created_b)
        self.assertNotEqual(jb.pk, j1.pk)

    def test_interrupted_job_is_picked_up_again_then_given_up(self):
        job, _ = jobs.request_backup(self.a.tenant, self.a.admin_user)
        for attempt in range(1, jobs.MAX_ATTEMPTS + 1):
            claimed = jobs.claim_next()               # worker 拿走…
            self.assertEqual((claimed.pk, claimed.attempts), (job.pk, attempt))
            self.assertIsNone(jobs.claim_next())      # 租約內別人拿不到
            BackupJob.objects.filter(pk=job.pk).update(   # …然後死掉,租約過期
                lease_until=timezone.now() - timedelta(seconds=1)
            )
        self.assertIsNone(jobs.claim_next())
        job.refresh_from_db()
        self.assertEqual(job.status, BackupJob.Status.FAILED)
        self.assertIn("中斷多次", job.error)

    def test_slow_job_that_is_still_running_is_not_taken_over(self):
        """備份跑得比租約久(資料多的公司):另一個 worker 不能把它當成死了再做一次。"""
        job, _ = jobs.request_backup(self.a.tenant, self.a.admin_user)
        claimed = jobs.claim_next()
        worker_dies = self.other_worker_holds("backup", claimed.pk)
        BackupJob.objects.filter(pk=job.pk).update(
            lease_until=timezone.now() - timedelta(seconds=1)
        )
        self.assertIsNone(jobs.claim_next())
        job.refresh_from_db()
        self.assertEqual((job.status, job.attempts), (BackupJob.Status.RUNNING, 1))
        worker_dies()
        again = jobs.claim_next()
        self.assertEqual((again.pk, again.attempts), (job.pk, 2))

    def test_two_computers_asking_at_once_get_one_job(self):
        """兩台電腦同時按備份:還沒有任何工作時也只會排出一個。"""
        results, barrier = [], threading.Barrier(2)

        def ask():
            try:
                barrier.wait(5)
                job, created = jobs.request_backup(self.a.tenant, self.a.admin_user)
                results.append((job.pk, created))
            finally:
                connection.close()

        threads = [threading.Thread(target=ask) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len({pk for pk, _ in results}), 1, results)
        self.assertEqual(sorted(c for _, c in results), [False, True])
        self.assertEqual(BackupJob.objects.filter(tenant=self.a.tenant).count(), 1)

    def test_verified_means_it_would_pass_the_restore_check(self):
        """「已驗證」= 這份檔現在拿去還原,檢查會過。過不了的不給下載。"""
        job, _ = jobs.request_backup(self.a.tenant, self.a.admin_user)
        bad = {"ok": False, "problems": ["catalog.Product:有一筆資料的內容不合法"], "warnings": []}
        with mock.patch.object(restore, "validate", return_value=bad):
            job = jobs.run_backup(jobs.claim_next())
        self.assertEqual(job.status, BackupJob.Status.FAILED)
        self.assertIn("沒有通過還原檢查", job.error)
        self.assertEqual(job.file_name, "")
        self.assertEqual(os.listdir(os.path.join(self.tmp, "backup_store", "tmp")), [])

    def test_expired_backup_cannot_be_downloaded(self):
        job = self.backup(self.a)
        path = self.path(job)
        BackupJob.objects.filter(pk=job.pk).update(
            expires_at=timezone.now() - timedelta(minutes=1)
        )
        job.refresh_from_db()
        with self.assertRaisesMessage(jobs.BackupError, "已經過期"):
            jobs.file_path(job)
        self.assertEqual(jobs.expire_old(), 1)
        self.assertFalse(os.path.exists(path))
        job.refresh_from_db()
        self.assertEqual(job.status, BackupJob.Status.EXPIRED)
        self.assertTrue(job.file_sha256)       # 雜湊留著,之後還能驗證店家手上的檔

    def test_backup_that_cannot_be_reopened_is_not_offered(self):
        """封裝完要再整包解開核對。寫出來的檔壞了(磁碟問題)就不能標成可下載。"""
        real = container.encrypt_file

        def writes_a_damaged_file(src, dst, secret, **kw):
            digest = real(src, dst, secret, **kw)
            with open(dst, "r+b") as f:
                f.seek(-20, os.SEEK_END)
                f.write(b"\x00" * 8)
            return digest

        jobs.request_backup(self.a.tenant, self.a.admin_user)
        with mock.patch.object(container, "encrypt_file", writes_a_damaged_file):
            job = jobs.run_backup(jobs.claim_next())
        self.assertEqual(job.status, BackupJob.Status.FAILED)
        self.assertEqual(job.file_name, "")
        leftovers = [
            f for _, _, files in os.walk(os.path.join(self.tmp, "backup_store")) for f in files
        ]
        self.assertEqual(leftovers, [])

    def test_backup_whose_content_differs_after_reopening_is_not_offered(self):
        real = container.decrypt_file

        def reopens_as_something_else(src, dst, secret, **kw):
            real(src, dst, secret, **kw)
            with open(dst, "ab") as f:
                f.write(b"extra")

        jobs.request_backup(self.a.tenant, self.a.admin_user)
        with mock.patch.object(container, "decrypt_file", reopens_as_something_else):
            job = jobs.run_backup(jobs.claim_next())
        self.assertEqual(job.status, BackupJob.Status.FAILED)
        self.assertIn("驗證失敗", job.error)

    def test_no_backup_without_a_recovery_credential(self):
        c = Company("c", "丙通訊行", "丙")
        with self.assertRaisesMessage(jobs.BackupError, "復原憑證"):
            jobs.request_backup(c.tenant, c.admin_user)

    def test_registry_refuses_unknown_tables(self):
        with mock.patch.dict(registry.REGISTRY):
            del registry.REGISTRY["sales.SalesOrderPayment"]
            with self.assertRaisesMessage(registry.RegistryError, "sales.SalesOrderPayment"):
                registry.check_registry()
            job, _ = jobs.request_backup(self.a.tenant, self.a.admin_user)
            job = jobs.run_backup(jobs.claim_next())
            self.assertEqual(job.status, BackupJob.Status.FAILED)


class NewEnvironmentRestoreTests(_Base):
    """原伺服器不能用:只憑硬碟上的檔案 + 抄下來的憑證,把公司建回來。"""

    def restore_as_new(self, **kw):
        job = self.backup(self.a)
        offline = os.path.join(self.tmp, "on-the-disk.mppos-backup")
        shutil.copy(self.path(job), offline)
        expected = business_view(self.a.tenant)
        users_before = set(
            UserProfile.objects.filter(tenant=self.a.tenant).values_list("user__username", flat=True)
        )
        # 模擬「原本那家公司不在這台伺服器上」:換掉識別碼,並讓伺服器忘記憑證
        import uuid
        Tenant.objects.filter(pk=self.a.tenant.pk).update(backup_uuid=uuid.uuid4())
        self.key_a.delete()
        tenant, result = restore.restore_new_company(
            offline, self.credential_a, code="a2", admin_username="recovery-boss",
            admin_password="recover-12345", **kw,
        )
        return tenant, result, expected, users_before

    def test_books_come_back_exactly(self):
        tenant, result, expected, _ = self.restore_as_new()
        self.assertEqual(business_view(tenant), expected)
        self.assertEqual(result["rows"], sum(result["tables"].values()))
        self.assertEqual(result["attachments"], 1)
        # 原圖是真的檔案,而且是新的一份(不是指回舊路徑)
        doc = IntakeDocument.objects.get(tenant=tenant)
        old = IntakeDocument.objects.get(tenant=self.a.tenant)
        self.assertNotEqual(doc.image.name, old.image.name)
        self.assertTrue(default_storage.exists(doc.image.name))
        # 沒有重播交易:異動筆數跟備份一樣,沒有多出來
        self.assertEqual(
            StockMovement.objects.filter(tenant=tenant).count(),
            StockMovement.objects.filter(tenant=self.a.tenant).count(),
        )
        # 所有外鍵都指回自己公司(沒有指到原公司的資料)
        for model in registry.ordered_company_models():
            for f in registry._fk_fields(model):
                if registry.label_of(f.related_model) not in {
                    registry.label_of(m) for m in registry.company_models()
                }:
                    continue
                leaked = model._base_manager.filter(tenant=tenant).exclude(
                    **{f"{f.name}__isnull": True}
                ).exclude(**{f"{f.name}__tenant": tenant}).count()
                self.assertEqual(leaked, 0, f"{registry.label_of(model)}.{f.name}")

    def test_learned_aliases_and_four_phrasings_still_work(self):
        tenant, *_ = self.restore_as_new()
        case = Product.objects.get(tenant=tenant, name=STANDARD_NAME)
        for phrase in FOUR_PHRASINGS:
            self.assertEqual(find_candidates(tenant, phrase).product_ids[:1], [case.id], phrase)
        self.assertEqual(
            find_candidates(tenant, "OPPO16代保護套-海洋").status, "existing"
        )
        # 再入庫:只加既有商品的庫存,不重建料號
        admin = Company.client(
            UserProfile.objects.get(tenant=tenant, user__username="recovery-boss").user
        )
        before = Product.objects.filter(tenant=tenant).count()
        wh = Warehouse.objects.get(tenant=tenant, code="w1")
        from apps.parties.models import Supplier
        supplier = Supplier.objects.get(tenant=tenant)
        r = admin.post("/api/v1/purchase-orders/", {
            "supplier": supplier.id, "warehouse": wh.id, "tax_method": "untaxed",
            "items": [{"product": case.id, "qty": 3, "unit_price": "100"}],
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(Product.objects.filter(tenant=tenant).count(), before)
        self.assertEqual(StockBalance.objects.get(tenant=tenant, warehouse=wh, product=case).qty, 7)
        # 下一張單號接著備份裡最後一張,不撞號
        self.assertEqual(r.json()["no"], "PO-000002")

    def test_new_numbers_do_not_collide(self):
        tenant, *_ = self.restore_as_new()
        admin = Company.client(
            UserProfile.objects.get(tenant=tenant, user__username="recovery-boss").user
        )
        from apps.catalog.models import Category
        case_cat = Category.objects.get(tenant=tenant, code="LC")
        r = admin.post("/api/v1/products/", {
            "name": "Reno20 磁吸殼 黑", "category": case_cat.id, "requires_serial": False,
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        skus = list(Product.objects.filter(tenant=tenant).values_list("sku", flat=True))
        self.assertEqual(len(skus), len(set(skus)))
        r = admin.post("/api/v1/customers/", {"name": "新客人", "kind": "individual"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)

    def test_accounts_and_store_locks(self):
        tenant, result, _, users_before = self.restore_as_new()
        # 復原管理員可以登入
        from django.contrib.auth import authenticate
        self.assertIsNotNone(authenticate(username="recovery-boss", password="recover-12345"))
        profiles = {
            p.user.username: p for p in UserProfile.objects.filter(tenant=tenant)
            .select_related("user", "default_warehouse")
        }
        # 帳號名稱已被原公司的人用掉 → 改名重建
        self.assertEqual(result["accounts_renamed"], {"a-boss": "a-boss-a2", "a-clerk": "a-clerk-a2"})
        clerk = profiles["a-clerk-a2"]
        self.assertEqual(clerk.role, "tenant_user")
        self.assertTrue(clerk.is_warehouse_locked)
        self.assertEqual(clerk.default_warehouse.code, "w1")
        self.assertEqual(clerk.default_warehouse.tenant_id, tenant.id)
        # 重建的帳號沒有密碼、沒有 token:舊的登入憑證不會因為還原復活
        self.assertFalse(clerk.user.has_usable_password())
        from rest_framework.authtoken.models import Token
        self.assertFalse(Token.objects.filter(user__profile__tenant=tenant).exists())
        # 店員的銷貨歸屬還在
        so = SalesOrder.objects.get(tenant=tenant)
        self.assertEqual(so.sales_person.user, clerk.user)
        # 鎖倉仍然有效:店員看不到另一家店的單
        store2 = Warehouse.objects.get(tenant=tenant, code="w2")
        c = Company.client(clerk.user)
        r = c.post("/api/v1/sales-orders/", {
            "customer": so.customer_id, "warehouse": store2.id, "tax_method": "untaxed",
            "items": [], "payments": [],
        }, format="json")
        self.assertIn(r.status_code, (400, 403), r.content)

    def test_turned_off_permissions_come_back_with_the_accounts(self):
        """員工帳號被關掉的權限,搬到新環境還原時跟著回來 —— 不然還原之後大家變回全開。"""
        UserProfile.objects.filter(user=self.a.clerk_user).update(denied_abilities=["void_sales", "sales_return"])
        tenant, result, _, _ = self.restore_as_new()
        clerk = UserProfile.objects.get(tenant=tenant, role="tenant_user")
        self.assertEqual(clerk.denied_abilities, ["void_sales", "sales_return"])
        so = SalesOrder.objects.get(tenant=tenant)
        r = Company.client(clerk.user).post(f"/api/v1/sales-orders/{so.id}/void/", {}, format="json")
        self.assertEqual(r.status_code, 403, r.content)
        self.assertFalse(SalesOrder.objects.get(pk=so.pk).is_void)
        boss = UserProfile.objects.get(tenant=tenant, user__username="a-boss-a2")
        self.assertEqual(boss.denied_abilities, [])

    def test_account_names_never_collide_or_overflow(self):
        """改名後的名字也被用掉、或原名已經頂到長度上限:都要找得到一個放得下、沒人用的名字。"""
        from django.contrib.auth import get_user_model
        User = get_user_model()
        User.objects.create_user("a-boss-a2", password="x")          # 改名的第一個選擇也被佔了
        tenant, result, *_ = self.restore_as_new()
        self.assertEqual(result["accounts_renamed"]["a-boss"], "a-boss-a2-2")
        self.assertTrue(UserProfile.objects.filter(
            tenant=tenant, user__username="a-boss-a2-2", role="tenant_admin").exists())

        long_name = "u" * 150
        User.objects.create_user(long_name, password="x")
        got = restore._free_username(long_name, "a2")
        self.assertEqual((len(got), got.endswith("-a2")), (150, True))
        self.assertFalse(User.objects.filter(username=got).exists())
        User.objects.create_user(got, password="x")
        again = restore._free_username(long_name, "a2")
        self.assertTrue(len(again) <= 150 and again.endswith("-a2-2"), again)
        self.assertEqual(restore._free_username("nobody-has-this", "a2"), "nobody-has-this")

    def test_accounts_keep_their_identity_on_the_new_server(self):
        """搬到新伺服器後,重建的帳號沿用原本的識別碼:之後拿這家公司更早的備份回溯,
        還認得出誰是誰(即使帳號名稱因為撞名被改過)。"""
        import uuid
        originals = dict(UserProfile.objects.filter(tenant=self.a.tenant)
                         .values_list("user__username", "account_uuid"))
        job = self.backup(self.a)
        offline = os.path.join(self.tmp, "on-the-disk.mppos-backup")
        shutil.copy(self.path(job), offline)
        # 模擬「這台伺服器上沒有原本那家公司」:公司與帳號的識別碼都不在這裡
        Tenant.objects.filter(pk=self.a.tenant.pk).update(backup_uuid=uuid.uuid4())
        for profile in UserProfile.objects.filter(tenant=self.a.tenant):
            UserProfile.objects.filter(pk=profile.pk).update(account_uuid=uuid.uuid4())
        self.key_a.delete()
        tenant, result = restore.restore_new_company(
            offline, self.credential_a, code="a2", admin_username="recovery-boss",
            admin_password="recover-12345",
        )
        rebuilt = dict(UserProfile.objects.filter(tenant=tenant)
                       .exclude(user__username="recovery-boss")
                       .values_list("user__username", "account_uuid"))
        self.assertEqual(rebuilt, {
            "a-boss-a2": originals["a-boss"], "a-clerk-a2": originals["a-clerk"]})
        # 在新伺服器上拿同一份(更早的)備份回溯:帳號都對得回來
        admin = UserProfile.objects.get(tenant=tenant, user__username="recovery-boss").user
        staged = restore.stage_upload(tenant, self.upload(offline), admin)
        self.assertEqual(staged.status, RestoreJob.Status.PRECHECKED, staged.report)
        self.assertFalse(any("不在這家公司" in w for w in staged.report["warnings"]))

    def test_invoice_numbering_is_held_until_checked(self):
        tenant, result, *_ = self.restore_as_new()
        self.assertEqual(result["invoice_tracks_on_hold"], 1)
        track = InvoiceTrack.objects.get(tenant=tenant)
        self.assertFalse(track.is_active)
        self.assertEqual(track.next_number, 10000007)

    def test_refuses_when_company_already_here_or_wrong_credential(self):
        job = self.backup(self.a)
        with self.assertRaisesMessage(restore.RestoreError, "已經在這台伺服器上"):
            restore.restore_new_company(
                self.path(job), self.credential_a, code="a2", admin_username="x-boss")
        with self.assertRaisesMessage(restore.RestoreError, "復原憑證不正確"):
            restore.restore_new_company(
                self.path(job), self.credential_b, code="a2", admin_username="x-boss")
        self.assertFalse(Tenant.objects.filter(code="a2").exists())


class RollbackTests(_Base):
    """既有公司回到較早的備份。"""

    def setUp(self):
        super().setUp()
        self.job = self.backup(self.a)
        self.saved = os.path.join(self.tmp, "saved.mppos-backup")
        shutil.copy(self.path(self.job), self.saved)
        self.at_backup = business_view(self.a.tenant)
        self.b_before = raw_digest(self.b.tenant)
        self.b_view = business_view(self.b.tenant)

    def change_things_after_backup(self):
        self.a.purchase(case_qty=5)                       # PO-000002
        self.a.sell(case_qty=1)                           # SO-000002
        self.a.sell(case_qty=1)                           # SO-000003
        Product.objects.create(
            tenant=self.a.tenant, category=self.a.cat_case, name="備份之後才建的商品",
            requires_serial=False,
        )
        InvoiceTrack.objects.filter(tenant=self.a.tenant).update(next_number=10000020)
        Tenant.objects.filter(pk=self.a.tenant.pk).update(next_customer_seq=9)
        self.a.intake_document(b"after backup", "之後的單據.jpg")

    def test_books_return_to_the_backup(self):
        self.change_things_after_backup()
        self.assertNotEqual(business_view(self.a.tenant), self.at_backup)
        old_doc = IntakeDocument.objects.get(tenant=self.a.tenant, original_filename="之後的單據.jpg")
        old_path = old_doc.image.name
        job = self.rollback(self.a, self.saved)
        self.assertEqual(job.status, RestoreJob.Status.DONE, job.error)
        self.assertEqual(business_view(self.a.tenant), self.at_backup)
        # 還原前有做安全備份,而且它留著(不隨資料回溯消失)
        safety = job.safety_backup
        self.assertEqual((safety.kind, safety.status), ("safety", BackupJob.Status.VERIFIED))
        self.assertTrue(os.path.exists(self.path(safety)))
        self.assertGreater(safety.summary["tables"]["sales.SalesOrder"], 1)
        # 維護鎖解開了;備份之後才上傳的附件不再被任何資料指到,已清掉
        self.assertFalse(jobs.in_maintenance(self.a.tenant))
        self.assertFalse(default_storage.exists(old_path))
        # 操作紀錄留著
        actions = list(
            BackupAuditLog.objects.filter(tenant=self.a.tenant).values_list("action", flat=True)
        )
        for action in ["restore.prechecked", "restore.confirmed", "restore.done"]:
            self.assertIn(action, actions)

    def test_photo_edits_in_progress_do_not_block_the_restore_or_outlive_it(self):
        """商品照片的編輯作業(暫存)不進備份,卻指到商品。還原時要先清掉、連還沒掛到商品的暫存檔:
        不然舊商品刪掉之後它們指到不存在的列(還原做不完),或還原之後還能拿舊的作業去改還原回來的照片。"""
        from io import BytesIO

        from PIL import Image

        from apps.photos.models import PhotoDraft, PhotoUpload, ProductPhoto

        api = self.a.admin

        def picture(color):
            buf = BytesIO()
            Image.new("RGB", (640, 480), color).save(buf, "JPEG")
            return SimpleUploadedFile("a.jpg", buf.getvalue(), content_type="image/jpeg")

        def draft(**body):
            return api.post("/api/v1/photo-drafts/", body, format="json").json()["uid"]

        def upload(uid, key, color=(200, 30, 30)):
            r = api.post(f"/api/v1/photo-drafts/{uid}/uploads/",
                         {"uid": key, "file": picture(color)}, format="multipart")
            self.assertEqual(r.status_code, 201, r.content)

        # 備份之前:皮套有一張存好的照片
        case = self.a.case
        first = draft(product=case.id)
        upload(first, "kept")
        r = api.patch(f"/api/v1/products/{case.id}/",
                      {"photos": {"draft": first, "seen": [],
                                  "items": [{"upload": "kept", "caption": "正面"}]}},
                      format="json")
        self.assertEqual(r.status_code, 200, r.content)
        saved = self.path(self.backup(self.a))

        # 備份之後:有人正在編輯皮套的照片(還沒存),也有人新增商品加了照片(還沒存)
        editing = draft(product=case.id)
        upload(editing, "not-saved", (10, 10, 200))
        adding = draft(label="還沒存的新商品")
        upload(adding, "new", (10, 200, 10))
        loose = [u.image.name for u in PhotoUpload.objects.filter(uid__in=["not-saved", "new"])]
        self.assertTrue(all(default_storage.exists(n) for n in loose))
        # 另一家公司也有人正在加照片:還原甲公司不能動到它
        other = self.b.admin.post("/api/v1/photo-drafts/", {}, format="json").json()["uid"]
        r = self.b.admin.post(f"/api/v1/photo-drafts/{other}/uploads/",
                              {"uid": "b-photo", "file": picture((90, 90, 90))}, format="multipart")
        self.assertEqual(r.status_code, 201, r.content)
        other_file = PhotoUpload.objects.get(uid="b-photo").image.name

        job = self.rollback(self.a, saved)
        self.assertEqual(job.status, RestoreJob.Status.DONE, job.error)
        # 編輯作業與暫存都清掉了,還沒掛到商品的檔案也刪了
        self.assertFalse(PhotoDraft.objects.filter(tenant=self.a.tenant).exists())
        self.assertFalse(PhotoUpload.objects.filter(tenant=self.a.tenant).exists())
        self.assertFalse(any(default_storage.exists(n) for n in loose))
        # 存好的那一張跟著備份回來,檔案打得開
        self.a.reload()
        photos = list(ProductPhoto.objects.filter(product=self.a.case))
        self.assertEqual([(p.caption, p.is_primary) for p in photos], [("正面", True)])
        self.assertTrue(default_storage.exists(photos[0].image.name))
        # 還原之前開的那一份編輯作業已經不能用:拿它來存,商品與照片都不動
        r = api.patch(f"/api/v1/products/{self.a.case.id}/",
                      {"photos": {"draft": editing, "seen": [photos[0].id], "items": []}}, format="json")
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(ProductPhoto.objects.filter(product=self.a.case).count(), 1)
        # 別家公司的照片作業與暫存檔原封不動
        self.assertEqual(PhotoUpload.objects.get(uid="b-photo").status, "ready")
        self.assertTrue(PhotoDraft.objects.filter(uid=other, state="open").exists())
        self.assertTrue(default_storage.exists(other_file))

    def test_contract_follow_ups_and_the_reminder_setting_come_back(self):
        """門號合約的聯絡紀錄(掛在銷貨明細上)與「到期前幾個月提醒」的設定,跟著備份回來。"""
        from datetime import date

        from apps.parties.models import Carrier, TelecomPlan
        from apps.sales import contracts as contract_rules
        from apps.sales.models import ContractFollowUp, SalesOrderItem

        carrier = Carrier.objects.create(tenant=self.a.tenant, code="FET", name="遠傳")
        plan = TelecomPlan.objects.create(
            tenant=self.a.tenant, carrier=carrier, name="599 續約", monthly_fee=599,
            contract_months=24, kind="renewal",
        )
        Product.objects.filter(pk=self.a.case.pk).update(allows_telecom_line=True)

        def sell(msisdn):
            r = self.a.admin.post("/api/v1/sales-orders/", {
                "customer": self.a.customer.id, "warehouse": self.a.wh.id, "tax_method": "untaxed",
                "payments": [], "items": [{
                    "product": self.a.case.id, "qty": 1, "unit_price": "0", "msisdn": msisdn,
                    "telecom_plan": plan.id, "activation_date": date.today().isoformat()}],
            }, format="json")
            self.assertEqual(r.status_code, 201, r.content)
            return SalesOrderItem.objects.get(so_id=r.json()["id"])

        kept = sell("0911000001")
        contract_rules.set_follow_up(self.a.tenant, kept.id, "declined", "攜碼到別家", self.a.admin_user)
        Tenant.objects.filter(pk=self.a.tenant.pk).update(contract_remind_months=6)
        saved = self.path(self.backup(self.a))

        # 備份之後:原本那一筆被改成已聯絡、又多標了一筆、設定也改了
        contract_rules.set_follow_up(self.a.tenant, kept.id, "contacted", "之後改的", self.a.admin_user)
        later = sell("0911000002")
        contract_rules.set_follow_up(self.a.tenant, later.id, "contacted", "", self.a.admin_user)
        Tenant.objects.filter(pk=self.a.tenant.pk).update(contract_remind_months=1)

        job = self.rollback(self.a, saved)
        self.assertEqual(job.status, RestoreJob.Status.DONE, job.error)
        rows = list(ContractFollowUp.objects.filter(tenant=self.a.tenant).select_related("item", "updated_by"))
        self.assertEqual([(f.item.msisdn, f.status, f.note) for f in rows],
                         [("0911000001", "declined", "攜碼到別家")])
        self.assertEqual(rows[0].updated_by, self.a.admin_user)     # 誰標的對得回同一個帳號
        self.assertEqual(Tenant.objects.get(pk=self.a.tenant.pk).contract_remind_months, 6)
        state = contract_rules.contracts(self.a.tenant).get(msisdn="0911000001").state
        self.assertEqual(state, contract_rules.DECLINED)

    def test_the_staff_cost_rules_and_what_was_recorded_come_back(self):
        """業務員成本:全公司的那一條、商品自己的設定、成交時記在單上的數字,跟著備份回來。"""
        from decimal import Decimal

        from apps.sales.models import SalesOrderItem

        t = self.a.tenant
        Tenant.objects.filter(pk=t.pk).update(staff_cost_mode="percent", staff_cost_value=Decimal("20"))
        Product.objects.filter(pk=self.a.case.pk).update(staff_cost_mode="plus", staff_cost_value=Decimal("35.50"))
        self.a.purchase(case_qty=4)
        sold = self.a.sell(case_qty=2)
        line = lambda: SalesOrderItem.objects.filter(tenant=t, so__no=sold["no"]).values_list(
            "cost_at_post", "staff_cost", "staff_cost_rule").get()
        recorded = line()
        self.assertEqual(recorded[1:], (Decimal("271.00"), "product:plus:35.50"))     # (100 + 35.5) × 2
        saved = self.path(self.backup(self.a))

        # 備份之後:規則都改掉、單上記的被清掉
        Tenant.objects.filter(pk=t.pk).update(staff_cost_mode="", staff_cost_value=0)
        Product.objects.filter(pk=self.a.case.pk).update(staff_cost_mode="fixed", staff_cost_value=1)
        SalesOrderItem.objects.filter(tenant=t, so__no=sold["no"]).update(staff_cost=None, staff_cost_rule="")

        job = self.rollback(self.a, saved)
        self.assertEqual(job.status, RestoreJob.Status.DONE, job.error)
        company = Tenant.objects.get(pk=t.pk)
        self.assertEqual((company.staff_cost_mode, company.staff_cost_value), ("percent", Decimal("20")))
        self.a.reload()
        self.assertEqual((self.a.case.staff_cost_mode, self.a.case.staff_cost_value), ("plus", Decimal("35.50")))
        self.assertEqual(line(), recorded)

    def test_numbers_only_move_forward(self):
        self.change_things_after_backup()
        job = self.rollback(self.a, self.saved)
        self.assertEqual(job.status, RestoreJob.Status.DONE, job.error)
        # 備份之後開過 SO-000002、SO-000003(收據已經給客人了)→ 下一張是 000004
        self.a.reload()
        self.assertEqual(self.a.sell(case_qty=1)["no"], "SO-000004")
        self.assertEqual(self.a.purchase(case_qty=1)["no"], "PO-000003")
        self.assertEqual(
            dict(DocNumberFloor.objects.filter(tenant=self.a.tenant).values_list("prefix", "floor")),
            {"PO": 2, "SO": 3, "TR": 1},
        )
        # 發票字軌、客戶流水不倒退
        self.assertEqual(InvoiceTrack.objects.get(tenant=self.a.tenant).next_number, 10000020)
        self.a.tenant.refresh_from_db()
        self.assertEqual(self.a.tenant.next_customer_seq, 9)
        # 類別的品號流水:備份之後多建過一個商品,下一個品號不重用
        cat = self.a.cat_case
        cat.refresh_from_db()
        from apps.catalog.models import Category
        self.assertEqual(Category.objects.get(tenant=self.a.tenant, code="LC").next_sku_seq, 4)

    def test_other_company_is_not_touched(self):
        self.change_things_after_backup()
        self.rollback(self.a, self.saved)
        self.assertEqual(raw_digest(self.b.tenant), self.b_before)
        self.assertEqual(business_view(self.b.tenant), self.b_view)
        self.assertEqual(self.b.sell(case_qty=1)["no"], "SO-000002")

    def test_accounts_stay_and_locks_are_not_loosened(self):
        # 備份之後:新開一家店、一個綁在新店的店員
        new_store = Warehouse.objects.create(tenant=self.a.tenant, code="w3", name="甲新店")
        newcomer = self.a._user("a-newcomer", "tenant_user", new_store)
        from rest_framework.authtoken.models import Token
        token = Token.objects.create(user=self.a.clerk_user)

        staged = restore.stage_upload(self.a.tenant, self.upload(self.saved), self.a.admin_user)
        self.assertTrue(any("a-newcomer" in w for w in staged.report["warnings"]), staged.report)
        restore.confirm(staged, self.a.admin_user)
        job = restore.run_restore(restore.claim_next())
        self.assertEqual(job.status, RestoreJob.Status.DONE, job.error)

        # 帳號都還在、登入憑證沒被動
        self.assertTrue(Token.objects.filter(pk=token.pk).exists())
        self.assertTrue(self.a.admin_user.check_password("pw-12345"))
        clerk = UserProfile.objects.get(user=self.a.clerk_user)
        self.assertTrue(clerk.is_warehouse_locked)
        self.assertEqual(clerk.default_warehouse.code, "w1")
        self.assertEqual(clerk.default_warehouse.tenant_id, self.a.tenant.id)
        # 新店不在備份裡 → 那個店員沒有門市可用,而且仍然鎖著(不會變成看全部)
        late = UserProfile.objects.get(user=newcomer)
        self.assertIsNone(late.default_warehouse_id)
        self.assertTrue(late.is_warehouse_locked)
        self.assertEqual(job.result["profiles_without_store"], 1)
        r = Company.client(newcomer).get("/api/v1/sales-orders/")
        self.assertEqual(r.json()["count"], 0)
        # 單據的經手人對得回原本的帳號
        so = SalesOrder.objects.get(tenant=self.a.tenant)
        self.assertEqual(so.sales_person.user, self.a.clerk_user)

    def test_old_documents_follow_the_person_not_the_username(self):
        """備份之後原本的店員改了帳號名稱,那個名稱又被新人拿去用。回溯時舊單據的
        經手人要跟著「原本那個人」,不能因為名稱一樣就掛到新人頭上。"""
        from django.contrib.auth import get_user_model
        User = get_user_model()
        original = self.a.clerk_user
        User.objects.filter(pk=original.pk).update(username="a-clerk-renamed")
        impostor = self.a._user("a-clerk", "tenant_user", self.a.wh)     # 新人用了舊名稱
        staged = restore.stage_upload(self.a.tenant, self.upload(self.saved), self.a.admin_user)
        self.assertFalse(any("不在這家公司" in w for w in staged.report["warnings"]))
        restore.confirm(staged, self.a.admin_user)
        job = restore.run_restore(restore.claim_next())
        self.assertEqual(job.status, RestoreJob.Status.DONE, job.error)
        so = SalesOrder.objects.get(tenant=self.a.tenant)
        self.assertEqual(so.sales_person.user_id, original.pk)
        self.assertNotEqual(so.sales_person.user_id, impostor.pk)
        doc = IntakeDocument.objects.get(tenant=self.a.tenant)
        self.assertEqual(doc.created_by_id, self.a.admin_user.pk)

    def test_someone_who_left_the_company_is_not_matched(self):
        """備份裡的帳號現在不在這家公司(調去別家、或帳號刪了):留空並列出來,
        不會去別家公司找同名的人,也不會因為識別碼還在就掛回去。"""
        from django.contrib.auth import get_user_model
        clerk = self.a.clerk_user
        from apps.parties.models import SalesPerson
        SalesPerson.objects.filter(user=clerk).update(user=None)
        UserProfile.objects.filter(user=clerk).update(
            tenant=self.b.tenant, default_warehouse=self.b.wh)       # 調去乙公司
        get_user_model().objects.filter(pk=clerk.pk).update(username="moved-away")
        self.b._user("a-clerk", "tenant_user", self.b.wh)             # 乙公司有個同名的人
        staged = restore.stage_upload(self.a.tenant, self.upload(self.saved), self.a.admin_user)
        self.assertTrue(
            any("不在這家公司" in w and "a-clerk" in w for w in staged.report["warnings"]),
            staged.report["warnings"])
        restore.confirm(staged, self.a.admin_user)
        job = restore.run_restore(restore.claim_next())
        self.assertEqual(job.status, RestoreJob.Status.DONE, job.error)
        so = SalesOrder.objects.get(tenant=self.a.tenant)
        self.assertIsNone(so.sales_person.user_id)

    def test_backup_made_with_an_older_credential_can_still_be_restored(self):
        """伺服器上的憑證後來由維運重發過一組。舊備份用舊憑證打開、還原得回去,
        而且伺服器現在用的那組不會被換回舊的。"""
        BackupKey.objects.filter(tenant=self.a.tenant).delete()
        _, newer = keys.create_key(self.a.tenant, self.a.admin_user)
        self.a.sell(case_qty=1)

        rejected = restore.stage_upload(
            self.a.tenant, self.upload(self.saved), self.a.admin_user)
        self.assertEqual(rejected.status, RestoreJob.Status.REJECTED)   # 沒給舊憑證打不開

        job = self.rollback(self.a, self.saved, credential=self.credential_a)
        self.assertEqual(job.status, RestoreJob.Status.DONE, job.error)
        self.assertEqual(business_view(self.a.tenant), self.at_backup)
        self.assertEqual(keys.get_secret(self.a.tenant), keys.parse_secret(newer))

    def test_confirm_is_bound_to_the_precheck(self):
        staged = restore.stage_upload(self.a.tenant, self.upload(self.saved), self.a.admin_user)
        self.assertEqual(staged.status, RestoreJob.Status.PRECHECKED)
        self.a.sell(case_qty=1)          # 預檢之後又有人開單
        with self.assertRaisesMessage(restore.RestoreError, "資料有變動"):
            restore.confirm(staged, self.a.admin_user)
        staged.refresh_from_db()
        self.assertEqual(staged.status, RestoreJob.Status.CANCELLED)

        staged = restore.stage_upload(self.a.tenant, self.upload(self.saved), self.a.admin_user)
        RestoreJob.objects.filter(pk=staged.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        staged.refresh_from_db()
        with self.assertRaisesMessage(restore.RestoreError, "過期"):
            restore.confirm(staged, self.a.admin_user)


    def test_company_is_locked_from_the_moment_of_confirmation(self):
        """按下確認的那一刻就鎖,不是等背景程式接手才鎖。這段空檔開的單會被還原吃掉。"""
        from rest_framework.authtoken.models import Token
        from rest_framework.test import APIClient
        clerk = APIClient()
        clerk.credentials(
            HTTP_AUTHORIZATION="Token " + Token.objects.create(user=self.a.clerk_user).key)
        staged = restore.stage_upload(self.a.tenant, self.upload(self.saved), self.a.admin_user)
        self.assertEqual(clerk.get("/api/v1/products/").status_code, 200)   # 預檢不擋營業
        restore.confirm(staged, self.a.admin_user)
        self.assertTrue(jobs.in_maintenance(self.a.tenant))                 # worker 還沒動
        self.assertEqual(clerk.get("/api/v1/products/").status_code, 503)
        self.assertEqual(clerk.post("/api/v1/sales-orders/", {}, format="json").status_code, 503)
        # 同一家公司不能同時有第二個還原
        other = restore.stage_upload(self.a.tenant, self.upload(self.saved), self.a.admin_user)
        with self.assertRaisesMessage(restore.RestoreError, "已經有一個還原"):
            restore.confirm(other, self.a.admin_user)
        restore.cancel(other, self.a.admin_user)
        with open(self.saved, "rb") as f:        # 走網頁的話,連上傳都不收
            r = self.a.admin.post("/api/v1/backup/restores/", {"file": f}, format="multipart")
        self.assertEqual(r.status_code, 409)
        # 還在排隊:可以取消,取消就解鎖,資料沒動
        staged.refresh_from_db()
        restore.cancel(staged, self.a.admin_user, reason="管理員取消")
        self.assertFalse(jobs.in_maintenance(self.a.tenant))
        self.assertEqual(clerk.get("/api/v1/products/").status_code, 200)
        self.assertIsNone(restore.claim_next())
        self.assertEqual(business_view(self.a.tenant), self.at_backup)
        self.assertEqual(os.listdir(os.path.join(self.tmp, "backup_store", "staging")), [])

    def test_platform_console_cannot_change_a_company_being_restored(self):
        """平台後台改門市 / 帳號 / 公司不帶 ?tenant=,登入那一層看不出要動誰 ——
        要照「實際要改的那一筆」擋。不然還原到一半門市被改名,改完又被蓋掉或變成幽靈資料。"""
        from django.contrib.auth import get_user_model
        root = get_user_model().objects.create_user("platform-root", password="pw-12345")
        UserProfile.objects.create(user=root, role="platform_admin", is_warehouse_locked=False)
        platform = Company.client(root)
        wh_a, wh_b = self.a.wh.pk, self.b.wh.pk
        attempts = [
            ("patch", f"/api/v1/platform/warehouses/{wh_a}/", {"name": "改名"}),
            ("delete", f"/api/v1/platform/warehouses/{wh_a}/", None),
            ("post", "/api/v1/platform/warehouses/",
             {"tenant": self.a.tenant.pk, "code": "w9", "name": "新門市"}),
            ("patch", f"/api/v1/platform/tenants/{self.a.tenant.pk}/", {"name": "改名"}),
            ("patch", f"/api/v1/platform/users/{self.a.clerk_user.pk}/", {"first_name": "改"}),
            ("post", f"/api/v1/platform/users/{self.a.clerk_user.pk}/reset-password/",
             {"password": "new-pw-123"}),
            # 把別家公司的人搬進維護中的公司
            ("patch", f"/api/v1/platform/users/{self.b.clerk_user.pk}/",
             {"tenant": self.a.tenant.pk}),
        ]
        staged = restore.stage_upload(self.a.tenant, self.upload(self.saved), self.a.admin_user)
        restore.confirm(staged, self.a.admin_user)
        for method, url, body in attempts:
            with self.subTest(url=url, method=method):
                r = getattr(platform, method)(url, body, format="json")
                self.assertEqual(r.status_code, 503, r.content)
        # 查看不擋;別家公司照常
        self.assertEqual(platform.get(f"/api/v1/platform/warehouses/{wh_a}/").status_code, 200)
        r = platform.patch(f"/api/v1/platform/warehouses/{wh_b}/", {"name": "乙改名"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(business_view(self.a.tenant), self.at_backup)
        # 還原取消(解鎖)之後就可以改了
        staged.refresh_from_db()
        restore.cancel(staged, self.a.admin_user)
        r = platform.patch(f"/api/v1/platform/warehouses/{wh_a}/", {"name": "改名"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)

    def test_account_without_a_company_cannot_slip_into_the_default_one(self):
        """平台管理員沒有自己的公司;不帶 ?tenant=(或帶了不存在的編號)時,系統會讓
        他落到「預設公司」。預設公司在還原,就要擋 —— 鎖看的公司要跟實際會動到的一致。"""
        from django.contrib.auth import get_user_model
        from django.test import RequestFactory
        from rest_framework.authtoken.models import Token
        from rest_framework.test import APIClient
        from apps.tenants import middleware

        root = get_user_model().objects.create_user("platform-root", password="pw-12345")
        UserProfile.objects.create(user=root, role="platform_admin", is_warehouse_locked=False)
        platform = APIClient()
        platform.credentials(HTTP_AUTHORIZATION="Token " + Token.objects.create(user=root).key)
        a, b = self.a.tenant.pk, self.b.tenant.pk

        with override_settings(DEFAULT_TENANT_ID=a):
            # 鎖用的規則跟系統實際解析公司的規則,答案要一樣
            for user, query in [(root, ""), (root, "?tenant=987654"), (root, f"?tenant={b}"),
                                (root, "?tenant=abc"), (self.b.clerk_user, f"?tenant={a}")]:
                request = RequestFactory().get("/api/v1/products/" + query)
                request.user = user
                self.assertEqual(
                    middleware.effective_tenant_id(request, user),
                    middleware._resolve_tenant_from_request(request).pk, query)

            staged = restore.stage_upload(self.a.tenant, self.upload(self.saved), self.a.admin_user)
            restore.confirm(staged, self.a.admin_user)
            self.assertEqual(platform.get("/api/v1/products/").status_code, 503)
            self.assertEqual(platform.get("/api/v1/products/?tenant=987654").status_code, 503)
            self.assertEqual(platform.get(f"/api/v1/products/?tenant={a}").status_code, 503)
            r = platform.patch("/api/v1/tenant-settings/", {"repair_warranty_days": 1}, format="json")
            self.assertEqual(r.status_code, 503)
            r = platform.post("/api/v1/products/", {"name": "混進來的商品"}, format="json")
            self.assertEqual(r.status_code, 503)
            # 明確指到別家公司、以及平台後台自己的畫面,照常
            self.assertEqual(platform.get(f"/api/v1/products/?tenant={b}").status_code, 200)
            self.assertEqual(platform.get("/api/v1/platform/warehouses/").status_code, 200)
            self.assertEqual(platform.get("/api/v1/auth/me/").status_code, 200)
        with override_settings(DEFAULT_TENANT_ID=b):        # 預設公司不是維護中的那家:不擋
            self.assertEqual(platform.get("/api/v1/products/").status_code, 200)
            self.assertEqual(platform.get(f"/api/v1/products/?tenant={a}").status_code, 503)

    def test_django_admin_is_read_only_while_any_company_is_restoring(self):
        """Django 管理後台用另一套登入,不經過 API 的維護鎖,而且一個畫面能改任何公司。
        有公司在還原時整個管理後台只能看、不能改。"""
        from django.contrib.auth import get_user_model
        from django.test import Client
        get_user_model().objects.create_superuser("ops", password="pw-12345")
        ops = Client()
        add_user = "/admin/auth/user/add/"
        form = {"username": "made-in-admin", "password1": "Zx9!kq2#Lm", "password2": "Zx9!kq2#Lm"}

        staged = restore.stage_upload(self.a.tenant, self.upload(self.saved), self.a.admin_user)
        restore.confirm(staged, self.a.admin_user)
        # 登入不擋
        r = ops.post("/admin/login/", {"username": "ops", "password": "pw-12345"})
        self.assertEqual(r.status_code, 302, r.content[:200])
        self.assertEqual(ops.get("/admin/catalog/product/").status_code, 200)     # 看可以
        r = ops.post(add_user, form)
        self.assertEqual(r.status_code, 503)
        self.assertIn("還原", r.content.decode())
        product = Product.objects.filter(tenant=self.a.tenant).first()
        r = ops.post(f"/admin/catalog/product/{product.pk}/delete/", {"post": "yes"})
        self.assertEqual(r.status_code, 503)
        self.assertTrue(Product.objects.filter(pk=product.pk).exists())
        self.assertFalse(get_user_model().objects.filter(username="made-in-admin").exists())
        # 還原結束(這裡用取消)就恢復
        staged.refresh_from_db()
        restore.cancel(staged, self.a.admin_user)
        self.assertEqual(ops.post(add_user, form).status_code, 302)
        self.assertTrue(get_user_model().objects.filter(username="made-in-admin").exists())

    def test_platform_console_keeps_stores_inside_their_company(self):
        """平台後台不能把帳號綁到別家公司的門市、也不能把門市換到別家公司 ——
        那會讓那家公司的還原刪不掉門市(整個失敗),備份也出現跨公司的參照。"""
        from django.contrib.auth import get_user_model
        root = get_user_model().objects.create_user("platform-root", password="pw-12345")
        UserProfile.objects.create(user=root, role="platform_admin", is_warehouse_locked=False)
        platform = Company.client(root)
        b_clerk = self.b.clerk_user.pk
        r = platform.patch(f"/api/v1/platform/users/{b_clerk}/",
                           {"default_warehouse": self.a.wh.pk}, format="json")
        self.assertEqual(r.status_code, 400, r.content)
        r = platform.post("/api/v1/platform/users/", {
            "username": "new-b", "password": "pw-12345", "role": "tenant_user",
            "tenant": self.b.tenant.pk, "default_warehouse": self.a.wh.pk,
        }, format="json")
        self.assertEqual(r.status_code, 400, r.content)
        r = platform.patch(f"/api/v1/platform/users/{b_clerk}/",
                           {"tenant": self.a.tenant.pk}, format="json")    # 換公司卻留著舊門市
        self.assertEqual(r.status_code, 400, r.content)
        # 代碼刻意取乙公司沒有的,才不會被「同公司代碼重複」先擋掉、測不到這一道
        only_a = Warehouse.objects.create(tenant=self.a.tenant, code="w7", name="甲獨有")
        r = platform.patch(f"/api/v1/platform/warehouses/{only_a.pk}/",
                           {"tenant": self.b.tenant.pk}, format="json")
        self.assertEqual(r.status_code, 400, r.content)
        self.assertIn("不能換公司", r.content.decode())
        only_a.refresh_from_db()
        self.assertEqual(only_a.tenant_id, self.a.tenant.pk)
        # 同一家公司裡照常
        r = platform.patch(f"/api/v1/platform/users/{b_clerk}/",
                           {"default_warehouse": self.b.warehouses[1].pk}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        r = platform.patch(f"/api/v1/platform/warehouses/{self.a.wh.pk}/",
                           {"tenant": self.a.tenant.pk, "name": "甲改名"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(UserProfile.objects.get(user_id=b_clerk).default_warehouse.tenant_id,
                         self.b.tenant.pk)
        # 甲在還原:把任何帳號綁到甲的門市都擋(看的是門市屬於哪家,不只看帳號)
        staged = restore.stage_upload(self.a.tenant, self.upload(self.saved), self.a.admin_user)
        restore.confirm(staged, self.a.admin_user)
        r = platform.patch(f"/api/v1/platform/users/{b_clerk}/",
                           {"default_warehouse": self.a.wh.pk}, format="json")
        self.assertEqual(r.status_code, 503, r.content)

    def test_store_held_by_another_company_stops_the_precheck(self):
        """舊資料裡已經有別家公司的帳號綁著這家公司的門市:預檢就擋下來並列出是誰,
        不要等鎖了公司、做完安全備份,才在刪門市那一步整個失敗。"""
        UserProfile.objects.filter(user=self.b.clerk_user).update(default_warehouse=self.a.wh)
        staged = restore.stage_upload(self.a.tenant, self.upload(self.saved), self.a.admin_user)
        self.assertEqual(staged.status, RestoreJob.Status.REJECTED)
        self.assertIn("別家公司的帳號綁著這家公司的門市", staged.report["problems"][0])
        self.assertIn("b-clerk", staged.report["problems"][0])
        self.assertFalse(jobs.in_maintenance(self.a.tenant))

    def test_data_changed_after_confirmation_stops_the_restore(self):
        """上鎖之後資料還是變了(繞過網頁的管理指令、上鎖前一刻放行的請求):
        動手前再比一次,對不上就不還原 —— 不然那筆變動會無聲消失。"""
        staged = restore.stage_upload(self.a.tenant, self.upload(self.saved), self.a.admin_user)
        restore.confirm(staged, self.a.admin_user)
        self.a.sell(case_qty=1)          # force_authenticate 的測試用戶端不經過維護鎖
        view = business_view(self.a.tenant)
        job = restore.run_restore(restore.claim_next())
        self.assertEqual(job.status, RestoreJob.Status.FAILED)
        self.assertIn("確認之後公司資料有變動", job.error)
        self.assertEqual(business_view(self.a.tenant), view)
        self.assertFalse(jobs.in_maintenance(self.a.tenant))

    def test_waits_for_writers_and_gives_up_cleanly(self):
        """別的交易正在新增這家公司的資料(新增時資料庫會對公司那一列上共享鎖):
        還原要等它;等不到就放棄,資料不動、解鎖。不會跟它交錯。"""
        staged = restore.stage_upload(self.a.tenant, self.upload(self.saved), self.a.admin_user)
        restore.confirm(staged, self.a.admin_user)
        view = business_view(self.a.tenant)
        writer = connections.create_connection("default")
        writer.ensure_connection()
        writer.set_autocommit(False)
        self.addCleanup(writer.close)
        with writer.cursor() as cur:       # 跟「新增一筆這家公司的資料」拿的是同一把鎖
            cur.execute(
                "SELECT 1 FROM tenants_tenant WHERE id = %s FOR KEY SHARE", [self.a.tenant.pk])
        with mock.patch.object(restore, "LOCK_TIMEOUT_SECONDS", 1):
            job = restore.run_restore(restore.claim_next())
        writer.rollback()
        self.assertEqual(job.status, RestoreJob.Status.FAILED)
        self.assertIn("還有進行中的作業", job.error)
        self.assertEqual(business_view(self.a.tenant), view)
        self.assertFalse(jobs.in_maintenance(self.a.tenant))
        # 別家公司的交易不會讓這家等:乙公司有交易開著,甲照樣還原
        with writer.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM tenants_tenant WHERE id = %s FOR KEY SHARE", [self.b.tenant.pk])
        with mock.patch.object(restore, "LOCK_TIMEOUT_SECONDS", 1):
            job = self.rollback(self.a, self.saved)
        writer.rollback()
        self.assertEqual(job.status, RestoreJob.Status.DONE, job.error)

    def test_waits_out_requests_admitted_before_the_lock(self):
        """上鎖後要等滿寬限時間(比網頁伺服器的請求逾時長)才開始動資料。"""
        staged = restore.stage_upload(self.a.tenant, self.upload(self.saved), self.a.admin_user)
        restore.confirm(staged, self.a.admin_user)
        slept = []
        with override_settings(BACKUP_RESTORE_GRACE_SECONDS=75), \
                mock.patch.object(restore.time, "sleep", slept.append):
            job = restore.run_restore(restore.claim_next())
        self.assertEqual(job.status, RestoreJob.Status.DONE, job.error)
        self.assertTrue(slept and 60 < slept[0] <= 75, slept)

    def test_floor_left_by_an_earlier_restore_is_not_lost(self):
        """之前還原留下的單號下限、備份之後才申請的發票字軌,備份裡都沒有 ——
        再還原一次也不能弄丟,不然會重用已經開出去的號碼。"""
        DocNumberFloor.objects.create(tenant=self.a.tenant, prefix="SO", floor=40)
        e_invoice = InvoiceType.objects.create(tenant=self.a.tenant, code="e_invoice", name="電子發票")
        InvoiceTrack.objects.create(
            tenant=self.a.tenant, invoice_type=e_invoice, period_label="115年7-8月",
            prefix="CD", range_start=20000000, range_end=20000049, next_number=20000013,
        )
        InvoiceTrack.objects.filter(tenant=self.a.tenant, prefix="AB").update(next_number=10000020)
        job = self.rollback(self.a, self.saved)
        self.assertEqual(job.status, RestoreJob.Status.DONE, job.error)
        self.a.reload()
        self.assertEqual(self.a.sell(case_qty=1)["no"], "SO-000041")
        kept = InvoiceTrack.objects.get(tenant=self.a.tenant, prefix="CD")
        self.assertEqual(
            (kept.next_number, kept.range_end, kept.invoice_type.code, kept.period_label),
            (20000013, 20000049, "e_invoice", "115年7-8月"),
        )
        self.assertEqual(job.result["invoice_tracks_kept"], ["CD 20000000-20000049"])
        # 還原前各種號碼用到哪裡,留在紀錄裡
        before = job.result["numbers_before"]
        self.assertEqual(before["doc_floor"], {"SO": 40})
        self.assertEqual(before["doc_seq"]["SO"], 1)
        self.assertEqual(
            before["invoice_tracks"], {"AB 10000000": 10000020, "CD 20000000": 20000013})
        self.assertEqual(before["counters"]["next_customer_seq"], self.a.tenant.next_customer_seq)

    def test_attachment_still_used_elsewhere_is_not_deleted(self):
        """還原後不再需要的舊附件:只要還有任何一筆資料(包括別家公司)指著它,就不能刪。"""
        doc = self.a.intake_document(b"after backup", "之後的單據.jpg")
        shared = doc.image.name
        theirs = IntakeDocument.objects.filter(tenant=self.b.tenant).first()
        IntakeDocument.objects.filter(pk=theirs.pk).update(image=shared)
        job = self.rollback(self.a, self.saved)
        self.assertEqual(job.status, RestoreJob.Status.DONE, job.error)
        self.assertTrue(default_storage.exists(shared))
        theirs.refresh_from_db()
        self.assertEqual(theirs.image.read(), b"after backup")


    def test_old_attachment_is_not_deleted_while_someone_is_writing(self):
        """「查還有沒有人用」跟「刪檔」之間不能有空檔:別的交易正在寫帶附件的表時,
        先不刪(等不到就留著,只是佔空間),不能賭它不會指到這個檔。"""
        doc = self.a.intake_document(b"orphan soon", "孤兒.jpg")
        name = doc.image.name
        IntakeDocument.objects.filter(pk=doc.pk).delete()      # 已經沒有任何資料指著它
        writer = connections.create_connection("default")
        writer.ensure_connection()
        writer.set_autocommit(False)
        self.addCleanup(writer.close)
        with writer.cursor() as cur:        # 跟「正在新增 / 修改一筆進貨單據」拿的是同一種鎖
            cur.execute("LOCK TABLE identity_intakedocument IN ROW EXCLUSIVE MODE")
        with mock.patch.object(restore, "CLEANUP_LOCK_TIMEOUT_SECONDS", 1):
            self.assertEqual(restore._delete_unreferenced([name]), 0)
        self.assertTrue(default_storage.exists(name))
        writer.rollback()
        self.assertEqual(restore._delete_unreferenced([name]), 1)
        self.assertFalse(default_storage.exists(name))


class RejectionTests(_Base):
    """有問題的檔案要在動到任何正式資料之前就被拒絕。"""

    def setUp(self):
        super().setUp()
        self.job = self.backup(self.a)
        self.before = raw_digest(self.a.tenant)
        self.files_before = sorted(os.listdir(os.path.join(self.tmp, "media", "intake_docs")))

    def assert_rejected(self, path, needle, credential=""):
        staged = restore.stage_upload(
            self.a.tenant, self.upload(path), self.a.admin_user, credential=credential
        )
        self.assertEqual(staged.status, RestoreJob.Status.REJECTED, staged.report)
        self.assertIn(needle, " ".join(staged.report["problems"]))
        self.assertEqual(staged.staged_file, "")
        self.assertEqual(raw_digest(self.a.tenant), self.before)
        self.assertFalse(jobs.in_maintenance(self.a.tenant))
        with self.assertRaises(restore.RestoreError):
            restore.confirm(staged, self.a.admin_user)

    def test_wrong_credential(self):
        self.assert_rejected(self.path(self.job), "復原憑證不正確", credential=self.credential_b)

    def test_damaged_and_truncated_files(self):
        raw = open(self.path(self.job), "rb").read()
        damaged = os.path.join(self.tmp, "damaged")
        with open(damaged, "wb") as f:
            f.write(raw[:len(raw) // 2] + b"\x00" + raw[len(raw) // 2 + 1:])
        self.assert_rejected(damaged, "")
        cut = os.path.join(self.tmp, "cut")
        with open(cut, "wb") as f:
            f.write(raw[:-100])
        self.assert_rejected(cut, "")
        junk = os.path.join(self.tmp, "junk")
        with open(junk, "wb") as f:
            f.write(b"not a backup at all")
        self.assert_rejected(junk, "不是 MP POS 的備份檔")

    def test_another_companys_backup(self):
        other = self.backup(self.b)
        # 乙的檔案配乙的憑證打得開,但它不是甲的備份
        self.assert_rejected(self.path(other), "不是這家公司的", credential=self.credential_b)

    def test_uploading_with_another_credential_never_replaces_ours(self):
        """上傳別家的檔 + 別家的憑證:被拒絕,而且我們公司的憑證不能因此被換掉
        (不然之後的備份會改用別人知道的那一組加密,自己抄的那組反而打不開)。"""
        other = self.backup(self.b)
        before = keys.get_secret(self.a.tenant)
        self.assert_rejected(self.path(other), "不是這家公司的", credential=self.credential_b)
        self.assertEqual(keys.get_secret(self.a.tenant), before)
        self.key_a.refresh_from_db()
        self.assertEqual(self.key_a.fingerprint, keys.fingerprint(before))
        # 之後的備份仍然用自己的憑證打得開
        self.unpack(self.backup(self.a), self.credential_a)

    def test_tampered_company_identity(self):
        def swap(entries):
            m = json.loads(entries["manifest.json"])
            m["company"]["uuid"] = str(self.b.tenant.backup_uuid)
            entries["manifest.json"] = json.dumps(m).encode()
        self.assert_rejected(self.repack(self.job, self.credential_a, swap), "不是這家公司的")

    def test_unsupported_version(self):
        def bump(entries):
            m = json.loads(entries["manifest.json"])
            m["schema_fingerprint"] = "0" * 16
            m["schema"]["sales"] = m["schema"]["sales"] + ["9999_from_the_future"]
            entries["manifest.json"] = json.dumps(m).encode()
        self.assert_rejected(self.repack(self.job, self.credential_a, bump), "不同版本")

        def wrong_fingerprint(entries):              # 版本清單沒動,指紋對不上
            m = json.loads(entries["manifest.json"])
            m["schema_fingerprint"] = "0" * 16
            entries["manifest.json"] = json.dumps(m).encode()
        self.assert_rejected(self.repack(self.job, self.credential_a, wrong_fingerprint), "不同版本")

        def bump_keeping_fingerprint(entries):       # 版本清單改了,指紋留著原本的
            m = json.loads(entries["manifest.json"])
            m["schema"]["sales"] = m["schema"]["sales"] + ["9999_from_the_future"]
            entries["manifest.json"] = json.dumps(m).encode()
        self.assert_rejected(
            self.repack(self.job, self.credential_a, bump_keeping_fingerprint), "不同版本")

        def older_history(entries):                  # 最新那一版一樣,中間的歷史不一樣
            m = json.loads(entries["manifest.json"])
            m["schema"]["sales"] = ["0000_something_else"] + m["schema"]["sales"][1:]
            m["schema_fingerprint"] = export.schema_fingerprint(m["schema"])
            entries["manifest.json"] = json.dumps(m).encode()
        self.assert_rejected(self.repack(self.job, self.credential_a, older_history), "不同版本")

        def not_a_list(entries):
            m = json.loads(entries["manifest.json"])
            m["schema"]["sales"] = "0009_latest_only"
            entries["manifest.json"] = json.dumps(m).encode()
        self.assert_rejected(self.repack(self.job, self.credential_a, not_a_list), "版本資訊")

        def fmt(entries):
            m = json.loads(entries["manifest.json"])
            m["format"] = 99
            entries["manifest.json"] = json.dumps(m).encode()
        self.assert_rejected(self.repack(self.job, self.credential_a, fmt), "不支援這個備份格式")

    def test_tampered_foreign_key_and_rows(self):
        def dangling(entries):
            lines = entries["data/sales.SalesOrderItem.jsonl"].splitlines()
            row = json.loads(lines[0])
            row["product_id"] = 99999999
            lines[0] = json.dumps(row).encode()
            entries["data/sales.SalesOrderItem.jsonl"] = b"\n".join(lines) + b"\n"
        self.assert_rejected(
            self.repack(self.job, self.credential_a, dangling), "指到備份裡不存在")

        def extra_row(entries):
            entries["data/catalog.Product.jsonl"] += entries["data/catalog.Product.jsonl"].splitlines()[0] + b"\n"
        self.assert_rejected(self.repack(self.job, self.credential_a, extra_row), "")

        def extra_column(entries):
            lines = entries["data/catalog.Product.jsonl"].splitlines()
            row = json.loads(lines[0])
            row["tenant_id"] = self.b.tenant.id        # 想把資料塞進別家公司
            lines[0] = json.dumps(row).encode()
            entries["data/catalog.Product.jsonl"] = b"\n".join(lines) + b"\n"
        self.assert_rejected(self.repack(self.job, self.credential_a, extra_column), "欄位")

    def test_path_traversal_and_foreign_entries(self):
        for name in ["../../etc/cron.d/evil", "/etc/passwd", "files/../../x", "data/auth.User.jsonl",
                     "run.sh"]:
            def add(entries, name=name):
                entries[name] = b"x"
            self.assert_rejected(self.repack(self.job, self.credential_a, add), "")
        self.assertEqual(
            sorted(os.listdir(os.path.join(self.tmp, "media", "intake_docs"))), self.files_before
        )

    def _edit_row(self, table, change):
        def mutate(entries):
            lines = entries[f"data/{table}.jsonl"].splitlines()
            row = json.loads(lines[0])
            change(row)
            lines[0] = json.dumps(row).encode()
            entries[f"data/{table}.jsonl"] = b"\n".join(lines) + b"\n"
        return self.repack(self.job, self.credential_a, mutate)

    def _edit_json(self, name, change):
        def mutate(entries):
            data = json.loads(entries[name])
            data = change(data) or data
            entries[name] = json.dumps(data).encode()
        return self.repack(self.job, self.credential_a, mutate)

    def test_values_that_would_not_fit_are_caught_before_anything_is_locked(self):
        """寫不進去的值要在預檢就擋下,不能等到鎖了公司、做完安全備份才失敗。"""
        cases = [
            ("catalog.Product", lambda r: r.update(name="長" * 500), "name 太長"),
            ("catalog.Product", lambda r: r.update(name=None), "name 不可以是空的"),
            ("catalog.Product", lambda r: r.update(name=["a"]), "name 格式不對"),
            ("catalog.Product", lambda r: r.update(list_price="很多錢"), "list_price 格式不對"),
            ("catalog.Product", lambda r: r.update(category_id="1; DROP"), "category 格式不對"),
            ("catalog.Product", lambda r: r.update(id="7"), "資料編號"),
            ("inventory.ProductSerial", lambda r: r.update(status="stolen"), "status 不在允許的選項裡"),
            ("sales.SalesOrder", lambda r: r.update(doc_date="昨天"), "doc_date 格式不對"),
            ("sales.SalesOrderItem", lambda r: r.update(so_id=None), "so 不可以是空的"),
        ]
        for table, change, needle in cases:
            with self.subTest(needle=needle):
                self.assert_rejected(self._edit_row(table, change), needle)

        def not_an_object(entries):
            entries["data/catalog.Brand.jsonl"] = b"[1, 2, 3]\n"
        self.assert_rejected(self.repack(self.job, self.credential_a, not_an_object), "")

        def same_sku_twice(entries):          # 兩個商品同一個品號
            lines = entries["data/catalog.Product.jsonl"].splitlines()
            first, second = json.loads(lines[0]), json.loads(lines[1])
            second["sku"] = first["sku"]
            lines[1] = json.dumps(second).encode()
            entries["data/catalog.Product.jsonl"] = b"\n".join(lines) + b"\n"
        self.assert_rejected(self.repack(self.job, self.credential_a, same_sku_twice), "sku 重複")

        with mock.patch.object(restore, "MAX_ROW_BYTES", 200):
            self.assert_rejected(self.path(self.job), "單筆資料過大")

    def test_attachments_must_match_the_list_exactly(self):
        def extra_file(entries):
            entries["files/7"] = b"smuggled"
        self.assert_rejected(
            self.repack(self.job, self.credential_a, extra_file), "附件跟清單對不起來")

        def drop_from_list(m):
            m["attachments"] = []
        def drop_everywhere(entries):
            m = json.loads(entries["manifest.json"])
            m["attachments"] = []
            entries["manifest.json"] = json.dumps(m).encode()
            del entries["files/0"]
        self.assert_rejected(self._edit_json("manifest.json", drop_from_list), "附件跟清單對不起來")
        self.assert_rejected(
            self.repack(self.job, self.credential_a, drop_everywhere), "附件不在備份清單裡")

        def orphan_in_list(m):
            m["attachments"][0]["pk"] = 987654
        self.assert_rejected(self._edit_json("manifest.json", orphan_in_list), "附件")

        def listed_but_no_row(entries):       # 清單多列一個附件,沒有任何資料用到它
            m = json.loads(entries["manifest.json"])
            m["attachments"].append({**m["attachments"][0], "index": 1, "pk": 987654})
            entries["manifest.json"] = json.dumps(m).encode()
            entries["files/1"] = entries["files/0"]
        self.assert_rejected(
            self.repack(self.job, self.credential_a, listed_but_no_row), "沒有對應的資料")

        for bad in ["../../etc/passwd", "/etc/passwd", "a\\b.jpg", "intake_docs//x.jpg",
                    "x" * 500]:
            with self.subTest(path=bad):
                def point_elsewhere(entries, bad=bad):
                    m = json.loads(entries["manifest.json"])
                    m["attachments"][0]["name"] = bad
                    entries["manifest.json"] = json.dumps(m).encode()
                    lines = entries["data/identity.IntakeDocument.jsonl"].splitlines()
                    row = json.loads(lines[0])
                    row["image"] = bad
                    lines[0] = json.dumps(row).encode()
                    entries["data/identity.IntakeDocument.jsonl"] = b"\n".join(lines) + b"\n"
                self.assert_rejected(
                    self.repack(self.job, self.credential_a, point_elsewhere), "檔案路徑不合法")
        self.assertEqual(
            sorted(os.listdir(os.path.join(self.tmp, "media", "intake_docs"))), self.files_before
        )

    def test_malformed_lists_are_rejected_not_crashed_on(self):
        """清單 / 帳號對照的形狀不對:結果是「這份檔不能用」,不是伺服器錯誤;暫存檔要清掉。"""
        cases = [
            ("accounts.json", lambda d: ["a-boss", "a-clerk"]),
            # 帳號數照舊(不然會先被「帳號數不符」擋掉,測不到角色那一道)
            ("accounts.json", lambda d: [{**d[0], "role": "platform_admin"}, d[1]]),
            ("accounts.json", lambda d: [{**d[0], "username": ""}, d[1]]),
            ("accounts.json", lambda d: [d[0], d[0]]),
            ("accounts.json", lambda d: [{**d[0], "uuid": "not-a-uuid"}, d[1]]),
            ("accounts.json", lambda d: [{k: v for k, v in d[0].items() if k != "uuid"}, d[1]]),
            ("accounts.json", lambda d: [d[0], {**d[1], "uuid": d[0]["uuid"]}]),
            ("accounts.json", lambda d: [{**d[0], "uuid": d[0]["uuid"].upper()}, d[1]]),
            ("accounts.json", lambda d: {"id": 1}),
            # 帳號被關掉的權限:要是字串的清單(少了這一格、不是清單、裡面不是字串、太長都不收)
            ("accounts.json", lambda d: [{k: v for k, v in d[0].items() if k != "denied_abilities"}, d[1]]),
            ("accounts.json", lambda d: [{**d[0], "denied_abilities": "void_sales"}, d[1]]),
            ("accounts.json", lambda d: [{**d[0], "denied_abilities": [7]}, d[1]]),
            ("accounts.json", lambda d: [{**d[0], "denied_abilities": [""]}, d[1]]),
            ("accounts.json", lambda d: [{**d[0], "denied_abilities": ["x" * 61]}, d[1]]),
            ("accounts.json", lambda d: [{**d[0], "denied_abilities": ["a"] * 201}, d[1]]),
            ("manifest.json", lambda d: d.update(tables={k: "3" for k in d["tables"]})),
            ("manifest.json", lambda d: d.update(warehouses="w1")),
            ("manifest.json", lambda d: d.update(snapshot_at=None)),
            ("manifest.json", lambda d: d.update(accounts=99)),
            ("manifest.json", lambda d: d.update(attachments={"0": {}})),
            ("manifest.json", lambda d: d["company"].update(counters={"next_customer_seq": -5})),
            ("manifest.json", lambda d: d["company"].update(settings={"is_superuser": True})),
            ("manifest.json", lambda d: d["company"].update(
                settings={"name": "甲", "repair_warranty_days": "很久"})),
            ("manifest.json", lambda d: d.pop("company")),
            ("manifest.json", lambda d: [1, 2]),
        ]
        for name, change in cases:
            with self.subTest(name=name, change=change):
                self.assert_rejected(self._edit_json(name, change), "")
        self.assertEqual(os.listdir(os.path.join(self.tmp, "backup_store", "staging")), [])

    def test_lists_too_big_to_hold_in_memory_are_refused(self):
        """會整個讀進記憶體的清單檔、壓縮檔目錄各有自己的上限(整包上限是幾 GB,
        不能拿來當這幾樣的上限,不然一份惡意的檔可以把伺服器的記憶體吃光)。"""
        for name, value, needle in [
            ("MAX_MANIFEST_BYTES", 100, "manifest.json 過大"),
            ("MAX_ACCOUNTS_BYTES", 10, "accounts.json 過大"),
            ("MAX_ZIP_ENTRIES", 5, "項目過多"),
            ("MAX_ZIP_DIRECTORY_BYTES", 100, "項目過多"),
        ]:
            with self.subTest(limit=name), mock.patch.object(restore, name, value):
                self.assert_rejected(self.path(self.job), needle)
        self.assertEqual(os.listdir(os.path.join(self.tmp, "backup_store", "staging")), [])

    def test_backup_bigger_than_this_server_allows(self):
        """預檢與還原要把每張表的編號放在記憶體裡:資料量有上限。超過的在預檢就拒絕,
        而且備份完成時的自我檢查就會失敗,不會等到真的要還原那天。"""
        with override_settings(BACKUP_MAX_ROWS=10):
            self.assert_rejected(self.path(self.job), "超過這台伺服器允許的上限")
            job, _ = jobs.request_backup(self.a.tenant, self.a.admin_user)
            job = jobs.run_backup(jobs.claim_next())
        self.assertEqual(job.status, BackupJob.Status.FAILED)
        self.assertIn("超過這台伺服器允許的上限", job.error)

    def test_unexpected_error_while_checking_still_ends_as_rejected(self):
        with mock.patch.object(restore, "validate", side_effect=ZeroDivisionError("boom")):
            staged = restore.stage_upload(
                self.a.tenant, self.upload(self.path(self.job)), self.a.admin_user)
        self.assertEqual(staged.status, RestoreJob.Status.REJECTED)
        self.assertNotIn("boom", json.dumps(staged.report, ensure_ascii=False))
        self.assertEqual(os.listdir(os.path.join(self.tmp, "backup_store", "staging")), [])

    def test_upload_that_breaks_midway_leaves_a_record_and_no_file(self):
        """上傳到一半斷線、磁碟滿了:留一筆「沒收成」的紀錄,半個檔不能留在暫存區。"""
        class Broken:
            size = 10

            def chunks(self):
                yield b"MPPOSBK"
                raise OSError("No space left on device")

        staged = restore.stage_upload(self.a.tenant, Broken(), self.a.admin_user)
        self.assertEqual(staged.status, RestoreJob.Status.REJECTED)
        self.assertIn("沒有完整收到", staged.report["problems"][0])
        self.assertNotIn("No space", json.dumps(staged.report, ensure_ascii=False))
        self.assertEqual(os.listdir(os.path.join(self.tmp, "backup_store", "staging")), [])
        self.assertTrue(BackupAuditLog.objects.filter(
            tenant=self.a.tenant, action="restore.prechecked", ok=False).exists())

    def test_a_different_credential_can_never_take_over(self):
        """系統金鑰換過、伺服器讀不出憑證時:只能重新登記「原本那一組」。"""
        import secrets as pysecrets
        stranger = keys.format_secret(pysecrets.token_bytes(20))
        with override_settings(SECRET_KEY="rotated-" + "x" * 40):
            self.assertIsNone(keys.get_secret(self.a.tenant))
            with self.assertRaisesMessage(keys.KeyError_, "不是同一組"):
                keys.register_key(self.a.tenant, stranger, self.a.admin_user)
            r = self.a.admin.post(
                "/api/v1/backup/key/register/", {"credential": stranger}, format="json")
            self.assertEqual(r.status_code, 409)
            self.assertIsNone(keys.get_secret(self.a.tenant))
            # 8 碼核對碼剛好一樣的另一組(核對碼只有 32 bits,湊得出來)也不行:
            # 認的是完整雜湊
            with mock.patch.object(keys, "fingerprint", return_value=self.key_a.fingerprint):
                with self.assertRaisesMessage(keys.KeyError_, "不是同一組"):
                    keys.register_key(self.a.tenant, stranger, self.a.admin_user)
            # 沒有完整雜湊的舊紀錄、伺服器那份又讀不出來:無從證明,一律不收
            saved_hash = self.key_a.secret_hash
            self.assertEqual(saved_hash, keys.identity(keys.parse_secret(self.credential_a)))
            BackupKey.objects.filter(pk=self.key_a.pk).update(secret_hash="")
            with self.assertRaisesMessage(keys.KeyError_, "不是同一組"):
                keys.register_key(self.a.tenant, self.credential_a, self.a.admin_user)
            BackupKey.objects.filter(pk=self.key_a.pk).update(secret_hash=saved_hash)
            r = self.a.admin.post(
                "/api/v1/backup/key/register/", {"credential": self.credential_a}, format="json")
            self.assertEqual(r.status_code, 200, r.content)
            self.assertEqual(keys.get_secret(self.a.tenant), keys.parse_secret(self.credential_a))
            # 舊紀錄但伺服器那份讀得出來:直接比內容
            BackupKey.objects.filter(pk=self.key_a.pk).update(secret_hash="")
            with self.assertRaisesMessage(keys.KeyError_, "不是同一組"):
                keys.register_key(self.a.tenant, stranger, self.a.admin_user)
            keys.register_key(self.a.tenant, self.credential_a, self.a.admin_user)
            self.key_a.refresh_from_db()
            self.assertEqual(self.key_a.secret_hash, saved_hash)

    def test_tampered_attachment(self):
        def swap(entries):
            entries["files/0"] = b"not the original scan"
        self.assert_rejected(self.repack(self.job, self.credential_a, swap), "附件內容不符")

    def test_upload_size_limit(self):
        with override_settings(BACKUP_MAX_UPLOAD_BYTES=100):
            with self.assertRaisesMessage(restore.RestoreError, "大小上限"):
                restore.stage_upload(
                    self.a.tenant, self.upload(self.path(self.job)), self.a.admin_user)


class FailureInjectionTests(_Base):
    """還原做到一半出事:不能留下半套資料,附件與資料庫不能各走各的。"""

    def setUp(self):
        super().setUp()
        self.job = self.backup(self.a)
        self.saved = os.path.join(self.tmp, "saved.mppos-backup")
        shutil.copy(self.path(self.job), self.saved)
        self.a.purchase(case_qty=5)
        self.a.sell(case_qty=1)
        self.a.intake_document(b"after backup", "之後的單據.jpg")
        self.before = raw_digest(self.a.tenant)
        self.view = business_view(self.a.tenant)

    def media_files(self):
        return sorted(
            os.path.join(root, f)[len(self.tmp):]
            for root, _, files in os.walk(os.path.join(self.tmp, "media")) for f in files
        )

    def assert_untouched(self, job, needle):
        self.assertEqual(job.status, RestoreJob.Status.FAILED)
        self.assertIn(needle, job.error)
        self.assertEqual(raw_digest(self.a.tenant), self.before)
        self.assertEqual(business_view(self.a.tenant), self.view)
        self.assertFalse(jobs.in_maintenance(self.a.tenant))
        # 失敗的還原不會重跑:上傳的那份檔(最大 2GB)不能留在伺服器上
        self.assertEqual(job.staged_file, "")
        self.assertEqual(os.listdir(os.path.join(self.tmp, "backup_store", "staging")), [])
        self.assertEqual(self.a.sell(case_qty=1)["no"], "SO-000003")   # 還能正常營業

    def test_failure_while_writing_rows(self):
        files = self.media_files()
        real = restore._row_digest
        calls = []

        def explode(model, row):
            calls.append(1)
            if registry.label_of(model) == "sales.SalesOrderItem":
                raise RuntimeError("磁碟滿了")
            return real(model, row)

        with mock.patch.object(restore, "_row_digest", explode):
            job = self.rollback(self.a, self.saved)
        self.assertTrue(calls)
        self.assertEqual(self.media_files(), files)       # 寫到一半的附件有清掉
        self.assert_untouched(job, "磁碟滿了")

    def test_failure_at_final_verification(self):
        files = self.media_files()
        # 讓「寫完之後讀回來核對」這一步對不上(每次算出來的指紋都不一樣)
        counter = iter(range(10 ** 6))
        with mock.patch.object(
            restore, "_table_digest", lambda digests: f"mismatch-{next(counter)}"
        ):
            job = self.rollback(self.a, self.saved)
        self.assertEqual(self.media_files(), files)
        self.assert_untouched(job, "內容跟備份不一致")

    def test_no_restore_without_a_safety_backup(self):
        with mock.patch.object(jobs, "export_company", side_effect=export.ExportError("磁碟滿了")):
            job = self.rollback(self.a, self.saved)
        self.assert_untouched(job, "安全備份沒有成功")

    def test_interrupted_restore_stays_locked_until_admin_checks(self):
        staged = restore.stage_upload(self.a.tenant, self.upload(self.saved), self.a.admin_user)
        restore.confirm(staged, self.a.admin_user)
        claimed = restore.claim_next()
        self.assertIsNone(restore.claim_next())            # 剛接手:不會馬上被當成死了
        claimed.refresh_from_db()
        self.assertEqual(claimed.status, RestoreJob.Status.RUNNING)
        with self.assertRaisesMessage(restore.RestoreError, "還在進行中"):
            restore.release_after_interruption(self.a.tenant, self.a.admin_user)
        # worker 接手之後整個死掉(沒有任何行程握著這個工作)
        RestoreJob.objects.filter(pk=claimed.pk).update(
            started_at=timezone.now() - timedelta(minutes=10)
        )
        self.assertIsNone(restore.claim_next())
        claimed.refresh_from_db()
        self.assertEqual(claimed.status, RestoreJob.Status.NEEDS_ATTENTION)
        self.assertIn("資料維持還原前的狀態", claimed.error)
        self.assertTrue(jobs.in_maintenance(self.a.tenant))     # 不自動開放營業
        self.assertEqual(raw_digest(self.a.tenant), self.before)
        # 維護中:這家公司的操作被擋,別家照常
        r = self.a.admin.get("/api/v1/products/")
        self.assertEqual(r.status_code, 200)       # force_authenticate 不經過登入驗證
        from rest_framework.authtoken.models import Token
        from rest_framework.test import APIClient
        real = APIClient()
        real.credentials(HTTP_AUTHORIZATION="Token " + Token.objects.create(user=self.a.clerk_user).key)
        self.assertEqual(real.get("/api/v1/products/").status_code, 503)
        self.assertEqual(real.post("/api/v1/sales-orders/", {}, format="json").status_code, 503)
        self.assertEqual(real.get("/api/v1/auth/me/").status_code, 200)
        other = APIClient()
        other.credentials(HTTP_AUTHORIZATION="Token " + Token.objects.create(user=self.b.clerk_user).key)
        self.assertEqual(other.get("/api/v1/products/").status_code, 200)
        # 維護中不能再排備份或還原
        with self.assertRaises(jobs.BackupError):
            jobs.request_backup(self.a.tenant, self.a.admin_user)
        # 管理員確認後解除;中斷的還原不能重跑,上傳的那份檔跟著清掉
        staging = os.path.join(self.tmp, "backup_store", "staging")
        self.assertEqual(len(os.listdir(staging)), 1)       # 等管理員處理的期間還留著
        restore.reconcile()
        self.assertEqual(len(os.listdir(staging)), 1)
        restore.release_after_interruption(self.a.tenant, self.a.admin_user)
        self.assertFalse(jobs.in_maintenance(self.a.tenant))
        self.assertEqual(os.listdir(staging), [])
        claimed.refresh_from_db()
        self.assertEqual((claimed.status, claimed.staged_file), (RestoreJob.Status.FAILED, ""))
        self.assertEqual(real.get("/api/v1/products/").status_code, 200)


    def test_long_restore_that_is_still_running_is_not_called_interrupted(self):
        """還原跑得很久(超過租約)但 worker 還活著:不能被判成中斷,也不能被解除維護 ——
        那樣店裡會在資料換到一半的時候恢復開單。"""
        staged = restore.stage_upload(self.a.tenant, self.upload(self.saved), self.a.admin_user)
        restore.confirm(staged, self.a.admin_user)
        claimed = restore.claim_next()
        worker_dies = self.other_worker_holds("restore", claimed.pk)
        RestoreJob.objects.filter(pk=claimed.pk).update(
            started_at=timezone.now() - timedelta(hours=3),
            lease_until=timezone.now() - timedelta(hours=2),
        )
        self.assertIsNone(restore.claim_next())
        claimed.refresh_from_db()
        self.assertEqual(claimed.status, RestoreJob.Status.RUNNING)
        with self.assertRaisesMessage(restore.RestoreError, "還在進行中"):
            restore.release_after_interruption(self.a.tenant, self.a.admin_user)
        self.assertTrue(jobs.in_maintenance(self.a.tenant))
        worker_dies()
        self.assertIsNone(restore.claim_next())
        claimed.refresh_from_db()
        self.assertEqual(claimed.status, RestoreJob.Status.NEEDS_ATTENTION)

    def test_releasing_a_dead_restore_directly_still_writes_a_full_record(self):
        """背景程式還沒把它整理成「需要處理」,管理員就直接解除:紀錄一樣要寫完整。"""
        staged = restore.stage_upload(self.a.tenant, self.upload(self.saved), self.a.admin_user)
        restore.confirm(staged, self.a.admin_user)
        claimed = restore.claim_next()
        RestoreJob.objects.filter(pk=claimed.pk).update(
            started_at=timezone.now() - timedelta(minutes=10))
        restore.release_after_interruption(self.a.tenant, self.a.admin_user)
        claimed.refresh_from_db()
        self.assertEqual(claimed.status, RestoreJob.Status.FAILED)
        self.assertIn("中斷", claimed.error)
        self.assertIsNotNone(claimed.finished_at)
        self.assertIsNone(claimed.lease_until)
        self.assertEqual(claimed.staged_file, "")
        self.assertFalse(jobs.in_maintenance(self.a.tenant))

    def test_job_marked_interrupted_cannot_finish_afterwards(self):
        """已經被標成中斷(管理員可能已經解除維護、店裡恢復開單)的還原,
        之後就算那個 worker 又動起來,也不能再把資料換掉。"""
        staged = restore.stage_upload(self.a.tenant, self.upload(self.saved), self.a.admin_user)
        restore.confirm(staged, self.a.admin_user)
        claimed = restore.claim_next()
        RestoreJob.objects.filter(pk=claimed.pk).update(status=RestoreJob.Status.NEEDS_ATTENTION)
        job = restore.run_restore(claimed)
        self.assertEqual(job.status, RestoreJob.Status.NEEDS_ATTENTION)
        self.assertEqual(raw_digest(self.a.tenant), self.before)
        self.assertEqual(business_view(self.a.tenant), self.view)
        self.assertTrue(jobs.in_maintenance(self.a.tenant))      # 仍然等管理員處理

    def test_attachment_that_did_not_land_intact_fails_the_restore(self):
        """附件寫回儲存區之後要讀回來核對。寫壞了(磁碟滿、寫到一半)就整批不算。"""
        files = self.media_files()
        real_save = default_storage.save

        def half_written(name, content, max_length=None):
            return real_save(name, ContentFile(content.read()[:10]), max_length=max_length)

        with mock.patch.object(default_storage, "save", half_written):
            job = self.rollback(self.a, self.saved)
        self.assertEqual(self.media_files(), files)
        self.assert_untouched(job, "附件寫回後內容不符")

    def test_leftovers_are_tidied_up(self):
        """worker 每一輪會收拾:結束了卻沒解開的鎖、過期沒人確認的預檢、暫存區的孤兒檔。"""
        staging = os.path.join(self.tmp, "backup_store", "staging")
        # 1. 過期的預檢
        staged = restore.stage_upload(self.a.tenant, self.upload(self.saved), self.a.admin_user)
        self.assertEqual(len(os.listdir(staging)), 1)
        RestoreJob.objects.filter(pk=staged.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1))
        # 2. 沒有任何工作在用的舊暫存檔;以及一個剛寫的(可能正在上傳)
        old, fresh = os.path.join(staging, "orphan.upload"), os.path.join(staging, "fresh.upload")
        for path in (old, fresh):
            with open(path, "wb") as f:
                f.write(b"x")
        long_ago = (timezone.now() - timedelta(days=2)).timestamp()
        os.utime(old, (long_ago, long_ago))
        # 3. 鎖開著,但它對應的還原已經結束
        finished = RestoreJob.objects.create(
            tenant=self.b.tenant, status=RestoreJob.Status.FAILED, file_sha256="0" * 64)
        restore.lock(self.b.tenant, finished, "資料還原中")

        # 4. 還在跑的備份(跑超過一天)的暫存檔:再舊也不能動
        tmp = os.path.join(self.tmp, "backup_store", "tmp")
        slow, _ = jobs.request_backup(self.a.tenant, self.a.admin_user)
        BackupJob.objects.filter(pk=slow.pk).update(status=BackupJob.Status.RUNNING)
        working = os.path.join(tmp, f"{slow.backup_id}.1.4242.zip")
        stray = os.path.join(tmp, "0000-not-a-job.1.4242.zip")
        for path in (working, stray):
            with open(path, "wb") as f:
                f.write(b"x")
            os.utime(path, (long_ago, long_ago))

        restore.reconcile()
        staged.refresh_from_db()
        self.assertEqual(staged.status, RestoreJob.Status.CANCELLED)
        self.assertEqual(os.listdir(staging), ["fresh.upload"])
        self.assertEqual(os.listdir(tmp), [os.path.basename(working)])
        self.assertFalse(jobs.in_maintenance(self.b.tenant))
        self.assertEqual(raw_digest(self.a.tenant), self.before)
        # 那個備份結束之後,它留下的暫存檔就會被清掉
        BackupJob.objects.filter(pk=slow.pk).update(status=BackupJob.Status.FAILED)
        restore.reconcile()
        self.assertEqual(os.listdir(tmp), [])
        # 已經結束的工作還記著檔名(刪檔那一刻失敗):那個檔一樣是孤兒
        leftover = os.path.join(staging, "leftover.upload")
        with open(leftover, "wb") as f:
            f.write(b"x")
        os.utime(leftover, (long_ago, long_ago))
        RestoreJob.objects.filter(pk=finished.pk).update(staged_file="staging/leftover.upload")
        restore.reconcile()
        self.assertEqual(os.listdir(staging), ["fresh.upload"])
        # 還原正在跑的時候,暫存區的檔(解開的備份)一律不動
        with open(old, "wb") as f:
            f.write(b"x")
        os.utime(old, (long_ago, long_ago))
        running = RestoreJob.objects.create(
            tenant=self.b.tenant, status=RestoreJob.Status.RUNNING, file_sha256="0" * 64,
            started_at=timezone.now())
        restore.reconcile()
        self.assertIn("orphan.upload", os.listdir(staging))
        RestoreJob.objects.filter(pk=running.pk).update(status=RestoreJob.Status.FAILED)
        restore.reconcile()
        self.assertEqual(os.listdir(staging), ["fresh.upload"])


class ApiPermissionTests(_Base):
    def setUp(self):
        super().setUp()
        self.job = self.backup(self.a)

    def test_only_company_admin(self):
        from django.contrib.auth import get_user_model
        platform = get_user_model().objects.create_user(username="platform", password="x")
        UserProfile.objects.create(user=platform, role="platform_admin", is_warehouse_locked=False)
        outsiders = {
            "店員": self.a.clerk,
            "別家公司的管理員": self.b.admin,
            "平台管理員": Company.client(platform),
        }
        url = f"/api/v1/backup/jobs/{self.job.id}/"
        self.assertEqual(self.a.admin.get(url).status_code, 200)
        self.assertEqual(self.a.clerk.get(url).status_code, 403)
        self.assertEqual(self.b.admin.get(url).status_code, 404)        # 猜編號也拿不到
        # 平台管理員帶 ?tenant= 也不行:這是公司入口
        self.assertEqual(
            outsiders["平台管理員"].get(url + f"?tenant={self.a.tenant.id}").status_code, 403)
        own_job_paths = [
            f"/api/v1/backup/jobs/{self.job.id}/download-ticket/",
            f"/api/v1/backup/jobs/{self.job.id}/verify-local/",
        ]
        company_paths = ["/api/v1/backup/jobs/", "/api/v1/backup/key/reveal/",
                         "/api/v1/backup/restores/", "/api/v1/backup/maintenance/release/"]
        for who, client in outsiders.items():
            # 甲公司的備份:三種人都碰不到
            for path in own_job_paths:
                r = client.post(path, {}, format="json")
                self.assertIn(r.status_code, (403, 404), (who, path, r.status_code))
        for who in ("店員", "平台管理員"):
            for path in company_paths:
                r = outsiders[who].post(path, {}, format="json")
                self.assertEqual(r.status_code, 403, (who, path, r.status_code))
        self.assertEqual(self.a.clerk.get("/api/v1/backup/overview/").status_code, 403)
        # 別家公司的管理員排的備份是他自己公司的
        r = self.b.admin.post("/api/v1/backup/jobs/", {}, format="json")
        self.assertEqual(BackupJob.objects.get(pk=r.json()["id"]).tenant, self.b.tenant)

    def test_download_ticket_is_single_use_and_rechecked(self):
        from django.test import Client
        ticket = self.a.admin.post(
            f"/api/v1/backup/jobs/{self.job.id}/download-ticket/").json()["ticket"]
        browser = Client()
        r = browser.get("/api/v1/backup/download/", {"ticket": ticket})
        self.assertEqual(r.status_code, 200)
        body = b"".join(r.streaming_content)
        self.assertEqual(__import__("hashlib").sha256(body).hexdigest(), self.job.file_sha256)
        self.assertIn(".mppos-backup", r["Content-Disposition"])
        self.assertEqual(browser.get("/api/v1/backup/download/", {"ticket": ticket}).status_code, 403)
        self.assertEqual(browser.get("/api/v1/backup/download/", {"ticket": "guess"}).status_code, 403)
        self.assertEqual(browser.get("/api/v1/backup/download/").status_code, 403)
        self.job.refresh_from_db()
        self.assertIsNotNone(self.job.download_started_at)
        self.assertIsNone(self.job.local_verified_at)       # 開始下載 ≠ 已存進硬碟

        # 換票之後被降成店員:用票的當下會再查一次
        ticket = self.a.admin.post(
            f"/api/v1/backup/jobs/{self.job.id}/download-ticket/").json()["ticket"]
        UserProfile.objects.filter(user=self.a.admin_user).update(role="tenant_user")
        self.assertEqual(browser.get("/api/v1/backup/download/", {"ticket": ticket}).status_code, 403)

    def test_expired_backup_gets_no_ticket(self):
        BackupJob.objects.filter(pk=self.job.pk).update(
            expires_at=timezone.now() - timedelta(minutes=1))
        r = self.a.admin.post(f"/api/v1/backup/jobs/{self.job.id}/download-ticket/")
        self.assertEqual(r.status_code, 409)

    def test_verify_local_file(self):
        url = f"/api/v1/backup/jobs/{self.job.id}/verify-local/"
        r = self.a.admin.post(url, {"sha256": "0" * 64, "size": self.job.file_size}, format="json")
        self.assertEqual(r.status_code, 400)
        r = self.a.admin.post(
            url, {"sha256": self.job.file_sha256, "size": self.job.file_size}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIsNotNone(r.json()["local_verified_at"])
        r = self.a.admin.post(url, {"sha256": self.job.file_sha256, "size": "很大"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_backup_folder_must_not_be_served_by_the_web_server(self):
        from apps.backup.apps import backup_root_is_private
        self.assertEqual(backup_root_is_private(None), [])
        media = os.path.join(self.tmp, "media")
        for root in (os.path.join(media, "backups"), media, self.tmp):
            with self.subTest(root=root), override_settings(BACKUP_ROOT=root):
                self.assertEqual([e.id for e in backup_root_is_private(None)], ["backup.E002"])

    def test_restore_via_api_needs_typed_confirmation(self):
        with open(self.path(self.job), "rb") as f:
            r = self.a.admin.post("/api/v1/backup/restores/", {"file": f}, format="multipart")
        self.assertEqual(r.status_code, 201, r.content)
        body = r.json()
        self.assertEqual(body["status"], "prechecked")
        self.assertEqual(body["report"]["source"]["warehouses"], ["甲湳雅店", "甲民生店"])
        self.assertEqual(body["report"]["source"]["company"], "甲通訊行")
        rid = body["id"]
        self.assertEqual(
            self.a.admin.post(f"/api/v1/backup/restores/{rid}/confirm/", {"confirm": "好"},
                              format="json").status_code, 400)
        self.assertEqual(self.b.admin.post(
            f"/api/v1/backup/restores/{rid}/confirm/", {"confirm": "還原"}, format="json"
        ).status_code, 404)
        r = self.a.admin.post(
            f"/api/v1/backup/restores/{rid}/confirm/", {"confirm": "還原"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["status"], "queued")          # 回的是確認之後的狀態
        ov = self.a.admin.get("/api/v1/backup/overview/").json()["maintenance"]
        self.assertEqual(
            (ov["active"], ov["restore_job"], ov["can_cancel"], ov["can_release"]),
            (True, rid, True, False))
        r = self.a.admin.post(f"/api/v1/backup/restores/{rid}/cancel/")
        self.assertEqual((r.status_code, r.json()["status"]), (200, "cancelled"), r.content)
        self.assertFalse(self.a.admin.get("/api/v1/backup/overview/").json()["maintenance"]["active"])

        with open(self.path(self.job), "rb") as f:
            rid = self.a.admin.post(
                "/api/v1/backup/restores/", {"file": f}, format="multipart").json()["id"]
        self.a.admin.post(
            f"/api/v1/backup/restores/{rid}/confirm/", {"confirm": "還原"}, format="json")
        done = restore.run_restore(restore.claim_next())
        self.assertEqual(done.status, RestoreJob.Status.DONE, done.error)

    def test_key_shown_once_then_logged_on_reveal(self):
        c = Company("c", "丙通訊行", "丙")
        r = c.admin.post("/api/v1/backup/key/")
        self.assertEqual(r.status_code, 201)
        credential = r.json()["credential"]
        self.assertRegex(credential, r"^MP(-[0-9A-Z]{4}){8}$")
        self.assertEqual(c.admin.post("/api/v1/backup/key/").status_code, 409)
        self.assertEqual(c.admin.post("/api/v1/backup/key/reveal/").json()["credential"], credential)
        log = list(BackupAuditLog.objects.filter(tenant=c.tenant).values_list("action", "detail"))
        self.assertEqual([a for a, _ in log], ["key.revealed", "key.created"])
        self.assertNotIn(credential, json.dumps([d for _, d in log]))
        self.assertFalse(TenantMaintenance.objects.filter(tenant=c.tenant, active=True).exists())

