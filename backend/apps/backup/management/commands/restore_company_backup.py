"""新環境復原:憑備份檔與復原憑證,在這台伺服器上把一家公司建回來。

    python manage.py restore_company_backup 備份檔.mppos-backup \\
        --code newshop --admin boss

會提示輸入復原憑證與復原管理員的密碼(不會出現在指令紀錄裡)。
只給「這台伺服器上還沒有這家公司」的情況用;既有公司要回到較早的備份,
請由公司管理員在「設定 → 備份與還原」操作,那條流程會先做安全備份。
"""
import getpass

from django.core.management.base import BaseCommand, CommandError

from apps.backup import keys, restore


class Command(BaseCommand):
    help = "在新環境上從備份檔復原一家公司"

    def add_arguments(self, parser):
        parser.add_argument("file", help="備份檔路徑(.mppos-backup)")
        parser.add_argument("--code", required=True, help="這家公司在這台伺服器上的代碼")
        parser.add_argument("--name", default="", help="公司名稱(不給就用備份裡的)")
        parser.add_argument("--admin", required=True, help="復原管理員的帳號")

    def handle(self, *args, **opts):
        credential = getpass.getpass("復原憑證(MP-XXXX-…):")
        password = getpass.getpass("復原管理員的密碼:")
        if password != getpass.getpass("再輸入一次:"):
            raise CommandError("兩次輸入的密碼不一樣")
        if len(password) < 8:
            raise CommandError("密碼至少 8 個字")
        try:
            tenant, result = restore.restore_new_company(
                opts["file"], credential, code=opts["code"], name=opts["name"],
                admin_username=opts["admin"], admin_password=password,
            )
        except (restore.RestoreError, keys.KeyError_) as exc:
            raise CommandError(str(exc))
        self.stdout.write(self.style.SUCCESS(f"已復原「{tenant.name}」,共 {result['rows']} 筆資料"))
        self.stdout.write(f"  備份時間點:{result['snapshot_at']}")
        self.stdout.write(f"  附件:{result['attachments']} 個")
        self.stdout.write(
            f"  重建帳號:{result['accounts_created']} 個(都還沒有密碼,請用復原管理員登入後逐一重設)"
        )
        for old, new in result["accounts_renamed"].items():
            self.stdout.write(f"    帳號「{old}」已被別人使用,改名為「{new}」")
        if result["accounts_without_store"]:
            self.stdout.write(f"  有 {result['accounts_without_store']} 個帳號的門市對不回來,已維持鎖定")
        if result["invoice_tracks_on_hold"]:
            self.stdout.write(self.style.WARNING(
                f"  發票字軌 {result['invoice_tracks_on_hold']} 組已先停用:"
                "請核對備份之後原本那邊又開到幾號,確認後再到設定頁啟用"
            ))
        self.stdout.write(self.style.WARNING(
            "  進貨 / 銷貨 / 調撥單號會接著備份裡最後一張往下編;"
            "備份之後原本那邊如果還開過單,請先確認不會重號"
        ))
