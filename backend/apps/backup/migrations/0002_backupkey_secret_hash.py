"""復原憑證多存一份完整雜湊,用來判斷「輸入的是不是原本那一組」。

既有的紀錄:伺服器那份讀得出來就補上;讀不出來(系統金鑰換過)就留空,之後
重新登記時無法證明是同一組,會被拒絕,要由維運處理。
"""
import hashlib

from django.db import migrations, models


def _fill(apps, schema_editor):
    from cryptography.fernet import InvalidToken

    from apps.backup.keys import _wrapper

    BackupKey = apps.get_model("backup", "BackupKey")
    for key in BackupKey.objects.filter(secret_hash=""):
        try:
            secret = _wrapper().decrypt(key.wrapped.encode())
        except InvalidToken:
            continue
        key.secret_hash = hashlib.sha256(b"mppos-backup-id:" + secret).hexdigest()
        key.save(update_fields=["secret_hash"])


class Migration(migrations.Migration):

    dependencies = [
        ("backup", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="backupkey",
            name="secret_hash",
            field=models.CharField(
                blank=True, default="", max_length=64, verbose_name="憑證雜湊"
            ),
        ),
        migrations.RunPython(_fill, migrations.RunPython.noop),
    ]
