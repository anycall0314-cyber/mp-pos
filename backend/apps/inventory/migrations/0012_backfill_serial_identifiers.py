"""把既有設備的主碼補登記到識別碼表。

以前只有拍照入庫會寫識別碼表,一般進貨 / 個人收購 / 匯入的設備只有 `serial_no`。
現在「一個碼只能屬於一台」靠識別碼表把關,所以每一台既有設備都要有一列:
15 碼數字且檢查碼正確的當 IMEI,其餘當 SN。

同一家公司裡兩台的碼去掉空白 / 破折號後變成同一個(例如 AB-12 與 AB12)時,後面那一台不登記
(不改任何既有資料),每日對帳「序號:每一台的碼都有登記」會把它列出來讓人處理。
"""
import re

from django.db import migrations


def _normalize(text):
    return re.sub(r"[\s\-_.]+", "", str(text or "").strip()).upper()


def _luhn_ok(digits):
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def _looks_like_imei(nv):
    return len(nv) == 15 and nv.isascii() and nv.isdigit() and _luhn_ok(nv)


def backfill(apps, schema_editor):
    Serial = apps.get_model("inventory", "ProductSerial")
    Identifier = apps.get_model("inventory", "ProductSerialIdentifier")
    known = set(Identifier.objects.values_list("tenant_id", "normalized_value"))
    rows = []
    for pk, tenant_id, serial_no in (
        Serial.objects.order_by("pk").values_list("pk", "tenant_id", "serial_no").iterator(chunk_size=5000)
    ):
        nv = _normalize(serial_no)
        if not nv or (tenant_id, nv) in known:
            continue
        known.add((tenant_id, nv))
        rows.append(Identifier(
            tenant_id=tenant_id, serial_id=pk, value=serial_no, normalized_value=nv,
            kind="imei" if _looks_like_imei(nv) else "sn", is_primary=True,
        ))
        if len(rows) >= 2000:
            Identifier.objects.bulk_create(rows)
            rows = []
    if rows:
        Identifier.objects.bulk_create(rows)


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0011_serial_code_change"),
    ]

    operations = [
        # 往回不用做事:補登的列留著不影響舊版程式
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
