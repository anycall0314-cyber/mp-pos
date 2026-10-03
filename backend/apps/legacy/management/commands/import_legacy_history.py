"""匯入舊 POS(歐睿)十年會員消費封存。

    # 1) 試算(預設,不寫任何東西):核對封存、算出會新增 / 換版 / 不變多少
    python manage.py import_legacy_history --tenant JB \\
        --archive "/path/ten-years-20161003-20261003" --period 2016-10-03:2026-10-03

    # 2) 寫入:明確指定公司;封存有來源差異時要加 --reconciled-only
    python manage.py import_legacy_history --tenant JB --archive ... --period ... \\
        --confirm --reconciled-only

    # 撤回某一批(只動那一批帶進來的東西)
    python manage.py import_legacy_history --tenant JB --rollback 3 --confirm

一定要指定 --tenant(不會自動選第一家公司)與 --period(要等於封存涵蓋的期間)。
報告用 --report 存成 JSON。
"""
import json
from datetime import date

from django.core.management.base import BaseCommand, CommandError

from apps.legacy import importer
from apps.legacy.archive import ArchiveError
from apps.legacy.models import HistoryImportBatch


class Command(BaseCommand):
    help = "匯入舊 POS 十年會員消費封存(預設只試算)"

    def add_arguments(self, parser):
        parser.add_argument("--tenant", required=True, help="公司代碼")
        parser.add_argument("--archive", help="封存解壓後的根目錄(有 manifest.json 的那一層)")
        parser.add_argument("--period", help="期間 YYYY-MM-DD:YYYY-MM-DD,要等於封存涵蓋的期間")
        parser.add_argument("--confirm", action="store_true", help="真的寫入(沒有就只試算)")
        parser.add_argument(
            "--reconciled-only", action="store_true",
            help="只匯已核對的部分;來源差異另存待核(封存有差異時寫入必須加)",
        )
        parser.add_argument("--rollback", type=int, help="撤回 MP 這邊的某一個匯入批次編號")
        parser.add_argument("--report", help="把完整報告存成這個 JSON 檔")

    def handle(self, *args, **opts):
        from apps.tenants.models import Tenant

        tenant = Tenant.objects.filter(code=opts["tenant"]).first()
        if tenant is None:
            raise CommandError(f"找不到公司代碼「{opts['tenant']}」")

        if opts["rollback"] is not None:
            batch = HistoryImportBatch.objects.filter(tenant=tenant, pk=opts["rollback"]).first()
            if batch is None:
                raise CommandError("這家公司沒有這個匯入批次")
            if not opts["confirm"]:
                self.stdout.write(
                    f"將撤回批次 #{batch.pk}({batch.period_start}~{batch.period_end},"
                    f"狀態 {batch.get_status_display()})。加 --confirm 才會執行。"
                )
                return
            try:
                counts = importer.rollback_batch(batch)
            except importer.RollbackBlocked as exc:
                raise CommandError(str(exc))
            self.stdout.write(self.style.SUCCESS(f"已撤回批次 #{batch.pk}:{counts}"))
            return

        if not opts["archive"] or not opts["period"]:
            raise CommandError("要指定 --archive 與 --period")
        try:
            start, end = (date.fromisoformat(x) for x in opts["period"].split(":"))
        except ValueError:
            raise CommandError("--period 的格式是 YYYY-MM-DD:YYYY-MM-DD")

        try:
            report = importer.run(
                tenant, opts["archive"], period=(start, end),
                write=opts["confirm"], reconciled_only=opts["reconciled_only"],
                log=lambda msg: self.stdout.write(msg),
            )
        except (ArchiveError, importer.ImportBlocked) as exc:
            raise CommandError(str(exc))

        if opts["report"]:
            with open(opts["report"], "w") as f:
                json.dump(report, f, ensure_ascii=False, indent=2, default=str)
        self._print(report)

    def _print(self, report):
        w = self.stdout.write
        mode = "寫入" if report["write"] else "試算(沒有寫入任何東西)"
        w(f"\n公司 {report['tenant']}|{mode}|封存 {report['covered_period'][0]}~{report['covered_period'][1]}")
        for b in report["batches"]:
            t, e, m = b["totals"], b["effect"], b["mapping"]
            w(f"\n批次 {b['archive_batch_id']}  {b['period'][0]}~{b['period'][1]}"
              + (f"(MP 批次 #{b['batch_id']})" if b["batch_id"] else ""))
            w(f"  已核對:會員 {t['members'] - t['exception_members']}、單據 {t['documents']}、"
              f"明細 {t['items']}、原始額 {_money(t['raw_amount_minor'])}、淨額 {_money(t['net_amount_minor'])}")
            w(f"  負金額明細 {t['negative_amount_items']}、空白單價 {t['null_unit_price_items']}、"
              f"單別 {t['document_types']}")
            if t["exception_members"]:
                w(f"  待核(不併入):會員 {t['exception_members']}、單據 {t['exception_documents']}、"
                  f"明細 {t['exception_items']}、清單 {_money(t['exception_list_amount_minor'])}、"
                  f"明細淨額 {_money(t['exception_net_amount_minor'])}、差 {_money(t['exception_difference_minor'])}")
            w(f"  效果:會員 新增 {e['members_new']} / 更新 {e['members_updated']} / 不變 {e['members_unchanged']};"
              f"單據 新增 {e['documents_new']} / 換版 {e['documents_replaced']} / 不變 {e['documents_unchanged']}"
              f" / 較舊擷取 {e['documents_older_capture']};明細寫入 {e['items_written']}")
            w(f"  對照:會員 已對照 {m['members_linked']}、電話單一候選 {m['members_phone_single_candidate']}、"
              f"多個候選 {m['members_phone_multiple_candidates']}、無候選 {m['members_no_candidate']};"
              f"店別 {m['stores_mapped']}/{m['stores']}、品號 {m['product_codes_mapped']}/{m['product_codes']}、"
              f"業務員 {m['salespersons_mapped']}/{m['salespersons']}")
            if b["overlap_legacy_purchases"]:
                w(f"  注意:既有「舊系統消費紀錄」裡有 {b['overlap_legacy_purchases']} 張單號 + 日期相同的單,請核對")
        if "mismatches" in report:
            w("\n合計與封存核對值:" + ("一致" if not report["mismatches"] else ";".join(report["mismatches"])))


def _money(minor):
    sign = "-" if minor < 0 else ""
    minor = abs(minor)
    whole, cents = divmod(minor, 100)
    return f"{sign}{whole:,}" + (f".{cents:02d}" if cents else "")
