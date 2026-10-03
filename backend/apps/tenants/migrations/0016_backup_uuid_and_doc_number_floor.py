"""公司穩定識別碼(備份用)+ 單號下限。

`backup_uuid` 分三步加:先加可空欄位 → 逐筆填不同的值 → 再設成唯一且必填。
直接加一個帶 `default=uuid.uuid4` 的唯一欄位的話,Django 只會算一次預設值、
把同一個 uuid 填給所有既有公司,加唯一約束時就會失敗。
"""
import uuid

import django.db.models.deletion
from django.db import migrations, models


def _fill_backup_uuid(apps, schema_editor):
    Tenant = apps.get_model("tenants", "Tenant")
    for tenant in Tenant.objects.filter(backup_uuid__isnull=True).iterator():
        tenant.backup_uuid = uuid.uuid4()
        tenant.save(update_fields=["backup_uuid"])


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0015_next_style_seq"),
    ]

    operations = [
        migrations.AddField(
            model_name="tenant",
            name="backup_uuid",
            field=models.UUIDField(
                editable=False, null=True, verbose_name="公司識別碼"
            ),
        ),
        migrations.RunPython(_fill_backup_uuid, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="tenant",
            name="backup_uuid",
            field=models.UUIDField(
                default=uuid.uuid4, editable=False, unique=True,
                verbose_name="公司識別碼",
            ),
        ),
        migrations.CreateModel(
            name="DocNumberFloor",
            fields=[
                ("id", models.BigAutoField(
                    auto_created=True, primary_key=True, serialize=False,
                    verbose_name="ID",
                )),
                ("created_at", models.DateTimeField(
                    auto_now_add=True, verbose_name="建立時間",
                )),
                ("updated_at", models.DateTimeField(
                    auto_now=True, verbose_name="更新時間",
                )),
                ("prefix", models.CharField(max_length=8, verbose_name="單號字首")),
                ("floor", models.PositiveIntegerField(
                    default=0, verbose_name="已用過的最大流水",
                )),
                ("tenant", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT, related_name="+",
                    to="tenants.tenant", verbose_name="租戶",
                )),
            ],
            options={
                "verbose_name": "單號下限",
                "verbose_name_plural": "單號下限",
                "abstract": False,
                "constraints": [
                    models.UniqueConstraint(
                        fields=("tenant", "prefix"), name="uniq_doc_number_floor",
                    ),
                ],
            },
        ),
    ]
