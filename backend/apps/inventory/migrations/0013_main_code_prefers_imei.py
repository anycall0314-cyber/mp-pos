"""既有設備的主碼校正成「有 IMEI 就用 IMEI」。

以前只有拍照入庫會替一台登記多個碼,而且主碼是看「哪一個被標成主識別碼」:SN 被標成主碼、同一台也有 IMEI 時,
`serial_no` 是 SN。現在的規則是有 IMEI 就以 IMEI 為主碼(新入庫的已經照做),這裡把既有的那幾台補齊。

只動「有登記 IMEI、但主碼不是那個 IMEI」的設備:把 `serial_no` 換成 IMEI、主識別碼的標記移到 IMEI 那一列。
原本的 SN 仍然登記著,刷得到同一台。那個 IMEI 已經是別台的主碼(不該發生)就不動,留給每日對帳與人工處理。
"""
import re

from django.db import migrations


def _normalize(text):
    return re.sub(r"[\s\-_.]+", "", str(text or "").strip()).upper()


def prefer_imei(apps, schema_editor):
    Serial = apps.get_model("inventory", "ProductSerial")
    Identifier = apps.get_model("inventory", "ProductSerialIdentifier")
    imeis = {}       # 設備 → 它的 IMEI 那一列(主識別碼優先,其次最新登記的;跟畫面顯示同一套順序)
    for row in Identifier.objects.filter(kind="imei").order_by("serial_id", "-is_primary", "-id"):
        imeis.setdefault(row.serial_id, row)
    for serial in Serial.objects.filter(pk__in=list(imeis)).order_by("pk"):
        row = imeis[serial.pk]
        if _normalize(serial.serial_no) == row.normalized_value:
            continue
        if Serial.objects.filter(tenant_id=serial.tenant_id, serial_no=row.value).exclude(pk=serial.pk).exists():
            continue
        Serial.objects.filter(pk=serial.pk).update(serial_no=row.value)
        Identifier.objects.filter(serial_id=serial.pk).exclude(pk=row.pk).update(is_primary=False)
        Identifier.objects.filter(pk=row.pk).update(is_primary=True)


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0012_backfill_serial_identifiers"),
    ]

    operations = [
        # 往回不用做事:主碼是 IMEI 或 SN 舊版程式都讀得懂
        migrations.RunPython(prefer_imei, migrations.RunPython.noop),
    ]
