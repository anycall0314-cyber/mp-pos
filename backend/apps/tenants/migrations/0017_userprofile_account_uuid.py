"""帳號的固定識別碼(公司備份用它認「是不是同一個人」)。

跟 0016 的公司識別碼一樣分三步:先加可空欄位 → 逐筆填不同的值 → 再設成唯一且必填。
"""
import uuid

from django.db import migrations, models


def _fill(apps, schema_editor):
    UserProfile = apps.get_model("tenants", "UserProfile")
    for profile in UserProfile.objects.filter(account_uuid__isnull=True).iterator():
        profile.account_uuid = uuid.uuid4()
        profile.save(update_fields=["account_uuid"])


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0016_backup_uuid_and_doc_number_floor"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="account_uuid",
            field=models.UUIDField(editable=False, null=True, verbose_name="帳號識別碼"),
        ),
        migrations.RunPython(_fill, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="userprofile",
            name="account_uuid",
            field=models.UUIDField(
                default=uuid.uuid4, editable=False, unique=True, verbose_name="帳號識別碼",
            ),
        ),
    ]
