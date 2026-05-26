"""匯入舊系統的會員主檔到 `parties.Member`。

用法:

    # 1) 預覽
    python manage.py import_legacy_members --csv path/to/legacy_members.csv

    # 2) 正式寫入
    python manage.py import_legacy_members --csv path/to/legacy_members.csv --confirm

CSV 欄位(第一列為標題;欄位順序可任意):

    name           姓名(必填)
    phone          電話(選填但強烈建議;為唯一比對鍵)
    national_id    身分證字號(選填)
    birthday       生日(YYYY-MM-DD;接受 YYYY/MM/DD;空白則略)
    address        地址(選填)
    note           備註(選填)

去重規則:
- 若該租戶內已有「相同 phone」的 Member,該列視為已存在,**預設略過**
- 加 `--update-existing` 改為:同 phone 用 CSV 內容更新姓名/身分證/生日/地址/備註
- phone 為空的列無法 dedup,一律新建(可能會重複,建議先補 phone 再匯)
"""
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.parties.models import Member
from apps.tenants.models import Tenant

REQUIRED_FIELDS = {"name"}
OPTIONAL_FIELDS = {"phone", "national_id", "birthday", "address", "note"}


def parse_date(s: str):
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


class Command(BaseCommand):
    help = "從 CSV 匯入會員主檔至 parties.Member"

    def add_arguments(self, parser):
        parser.add_argument("--csv", required=True, help="CSV 檔案路徑")
        parser.add_argument(
            "--tenant",
            default=None,
            help="租戶 code(預設取第一個 active tenant)",
        )
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="實際寫入;預設 dry-run",
        )
        parser.add_argument(
            "--update-existing",
            action="store_true",
            help="同 phone 的會員以 CSV 內容更新(預設略過)",
        )

    def handle(self, *args, **opts):
        path = Path(opts["csv"])
        if not path.exists():
            raise CommandError(f"找不到檔案:{path}")

        if opts["tenant"]:
            tenant = Tenant.objects.filter(code=opts["tenant"]).first()
        else:
            tenant = Tenant.objects.filter(is_active=True).order_by("id").first()
        if tenant is None:
            raise CommandError("找不到 tenant;請建立或指定 --tenant")

        confirm = bool(opts["confirm"])
        update_existing = bool(opts["update_existing"])

        # 既有 Member by phone(僅針對有 phone 的)
        existing_by_phone = {
            m.phone.strip(): m
            for m in Member.objects.for_tenant(tenant).exclude(phone="")
        }

        to_create = []
        to_update = []
        skipped = []
        errors = []

        with path.open(newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            headers = set(reader.fieldnames or [])
            missing = REQUIRED_FIELDS - headers
            if missing:
                raise CommandError(
                    f"CSV 缺少必要欄位:{sorted(missing)};"
                    f"目前欄位:{sorted(headers)}"
                )

            for idx, row in enumerate(reader, start=2):
                err = self._validate_row(row)
                if err:
                    errors.append({"line": idx, "row": dict(row), "error": err})
                    continue

                name = row["name"].strip()
                phone = (row.get("phone") or "").strip()
                national_id = (row.get("national_id") or "").strip()
                birthday = parse_date(row.get("birthday"))
                address = (row.get("address") or "").strip()
                note = (row.get("note") or "").strip()

                if phone and phone in existing_by_phone:
                    if update_existing:
                        m = existing_by_phone[phone]
                        to_update.append((idx, m, {
                            "name": name,
                            "national_id": national_id,
                            "birthday": birthday,
                            "address": address,
                            "note": note,
                        }))
                    else:
                        skipped.append({
                            "line": idx,
                            "reason": f"phone {phone} 已存在(會員號 {existing_by_phone[phone].code})",
                        })
                    continue

                to_create.append((idx, {
                    "tenant": tenant,
                    "name": name,
                    "phone": phone,
                    "national_id": national_id,
                    "birthday": birthday,
                    "address": address,
                    "note": note,
                }))

        self.stdout.write(self.style.NOTICE(
            f"檔案:{path.name}  租戶:{tenant.code}  "
            f"總 {len(to_create) + len(to_update) + len(skipped) + len(errors)} 列"
        ))
        self.stdout.write(self.style.SUCCESS(f"  新增:{len(to_create)} 列"))
        if update_existing:
            self.stdout.write(self.style.SUCCESS(f"  更新:{len(to_update)} 列"))
        self.stdout.write(self.style.WARNING(f"  略過:{len(skipped)} 列"))
        self.stdout.write(self.style.ERROR(f"  錯誤:{len(errors)} 列"))

        if errors:
            self.stdout.write("\n錯誤明細(前 20 行):")
            for e in errors[:20]:
                self.stdout.write(
                    f"  line {e['line']}  {e['error']}  原始:{e['row']}"
                )
        if skipped[:5]:
            self.stdout.write("\n略過範例(前 5):")
            for s in skipped[:5]:
                self.stdout.write(f"  line {s['line']}  {s['reason']}")

        if not confirm:
            self.stdout.write(self.style.NOTICE(
                "\n[dry-run] 未寫入任何資料。加 --confirm 才正式匯入。"
            ))
            return

        # Member.save 需要 tenant 來取 code,不能用 bulk_create
        # (TextChoices 子類序號自動產生在 save 內);改用逐筆 create
        created_count = 0
        with transaction.atomic():
            for _idx, kwargs in to_create:
                Member.objects.create(**kwargs)
                created_count += 1
            for _idx, m, fields in to_update:
                for k, v in fields.items():
                    setattr(m, k, v)
                m.save(update_fields=list(fields.keys()))

        self.stdout.write(self.style.SUCCESS(
            f"\n匯入完成,新增 {created_count} 筆,"
            f"更新 {len(to_update)} 筆 Member。"
        ))

    def _validate_row(self, row):
        if not (row.get("name") or "").strip():
            return "name 為空"
        bday_raw = (row.get("birthday") or "").strip()
        if bday_raw and parse_date(bday_raw) is None:
            return f"birthday 不合法:{bday_raw!r}"
        return None
