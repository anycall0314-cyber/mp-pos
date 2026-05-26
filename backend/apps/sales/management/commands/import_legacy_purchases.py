"""匯入舊系統會員消費紀錄(輕量版,只進 LegacyPurchase 表)。

用法:

    # 1) 預覽(不會改資料)
    python manage.py import_legacy_purchases --csv path/to/legacy_purchases.csv

    # 2) 正式寫入
    python manage.py import_legacy_purchases --csv path/to/legacy_purchases.csv --confirm

CSV 欄位(第一列為標題;欄位順序可任意,以標題對應):

    member_phone     會員電話(必填;以此 lookup 對應 Member)
    product_sku      商品品號(必填;以此 lookup 對應 Product)
    qty              數量(整數,留空則預設 1)
    unit_price       單價(數字,可帶小數;0 元贈品列**會被排除**,因為 last-price 查詢會跳過)
    doc_date         交易日期(YYYY-MM-DD;接受 YYYY/MM/DD)
    source_no        舊單號(選填)
    serial_no        序號 / IMEI(選填)
    note             備註(選填)

行為:
- 查無 Member(以 phone)或 Product(以 sku):**該列略過並計入錯誤報告**,不中斷整批
- 0 元的列:也匯入(讓會員消費頁可以看到完整歷史),但 last-price 查詢內建會自動跳過
- 全程包在一個 transaction;`--confirm` 之前是 dry-run,只跑驗證 + 報表
- 預設用第一個 tenant;多租戶請以 `--tenant <code>` 指定
"""
from __future__ import annotations

import csv
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.catalog.models import Product
from apps.parties.models import Member
from apps.sales.models import LegacyPurchase
from apps.tenants.models import Tenant

REQUIRED_FIELDS = {"member_phone", "product_sku", "unit_price", "doc_date"}
OPTIONAL_FIELDS = {"qty", "source_no", "serial_no", "note"}


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


def parse_decimal(s: str):
    try:
        return Decimal(str(s or "0").strip())
    except (InvalidOperation, ValueError):
        return None


class Command(BaseCommand):
    help = "從 CSV 匯入舊系統會員消費紀錄至 LegacyPurchase 表"

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

    def handle(self, *args, **opts):
        path = Path(opts["csv"])
        if not path.exists():
            raise CommandError(f"找不到檔案:{path}")

        # 解析 tenant
        if opts["tenant"]:
            tenant = Tenant.objects.filter(code=opts["tenant"]).first()
        else:
            tenant = Tenant.objects.filter(is_active=True).order_by("id").first()
        if tenant is None:
            raise CommandError("找不到 tenant;請建立或指定 --tenant")

        confirm = bool(opts["confirm"])

        # 建立查詢 cache(電話/SKU → 物件)
        members_by_phone = {
            m.phone.strip(): m
            for m in Member.objects.for_tenant(tenant).exclude(phone="")
        }
        products_by_sku = {
            p.sku.strip(): p
            for p in Product.objects.for_tenant(tenant)
        }

        ok_rows = []
        err_rows = []

        with path.open(newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            headers = set(reader.fieldnames or [])
            missing = REQUIRED_FIELDS - headers
            if missing:
                raise CommandError(
                    f"CSV 缺少必要欄位:{sorted(missing)};"
                    f"目前欄位:{sorted(headers)}"
                )

            for idx, row in enumerate(reader, start=2):  # 2 因為第一列是標題
                err = self._validate_row(row, members_by_phone, products_by_sku)
                if err:
                    err_rows.append({"line": idx, "row": dict(row), "error": err})
                    continue
                ok_rows.append((idx, row))

        self.stdout.write(self.style.NOTICE(
            f"檔案:{path.name}  租戶:{tenant.code}  共 {len(ok_rows) + len(err_rows)} 列"
        ))
        self.stdout.write(self.style.SUCCESS(f"  可匯入:{len(ok_rows)} 列"))
        self.stdout.write(self.style.WARNING(f"  略過 :{len(err_rows)} 列"))

        if err_rows:
            self.stdout.write("\n錯誤明細(前 20 行):")
            for e in err_rows[:20]:
                self.stdout.write(
                    f"  line {e['line']}  {e['error']}  原始:{e['row']}"
                )

        if not confirm:
            self.stdout.write(self.style.NOTICE(
                "\n[dry-run] 未寫入任何資料。加 --confirm 才正式匯入。"
            ))
            return

        with transaction.atomic():
            objs = []
            for _idx, row in ok_rows:
                member = members_by_phone[row["member_phone"].strip()]
                product = products_by_sku[row["product_sku"].strip()]
                qty = int(row.get("qty") or 1)
                unit_price = parse_decimal(row["unit_price"]) or Decimal("0")
                doc_date = parse_date(row["doc_date"])
                objs.append(
                    LegacyPurchase(
                        tenant=tenant,
                        member=member,
                        product=product,
                        qty=max(1, qty),
                        unit_price=unit_price,
                        doc_date=doc_date,
                        source_no=(row.get("source_no") or "").strip(),
                        serial_no=(row.get("serial_no") or "").strip(),
                        note=(row.get("note") or "").strip(),
                    )
                )
            LegacyPurchase.objects.bulk_create(objs, batch_size=500)

        self.stdout.write(self.style.SUCCESS(
            f"\n匯入完成,寫入 {len(ok_rows)} 筆 LegacyPurchase。"
        ))

    def _validate_row(self, row, members_by_phone, products_by_sku):
        phone = (row.get("member_phone") or "").strip()
        sku = (row.get("product_sku") or "").strip()
        if not phone:
            return "member_phone 為空"
        if not sku:
            return "product_sku 為空"
        if phone not in members_by_phone:
            return f"查無會員 phone={phone}"
        if sku not in products_by_sku:
            return f"查無商品 sku={sku}"

        up = parse_decimal(row.get("unit_price"))
        if up is None or up < 0:
            return f"unit_price 不合法:{row.get('unit_price')!r}"

        dd = parse_date(row.get("doc_date"))
        if dd is None:
            return f"doc_date 不合法:{row.get('doc_date')!r}"

        qty_raw = (row.get("qty") or "").strip()
        if qty_raw:
            try:
                if int(qty_raw) < 1:
                    return f"qty < 1:{qty_raw}"
            except ValueError:
                return f"qty 不是整數:{qty_raw}"

        return None
