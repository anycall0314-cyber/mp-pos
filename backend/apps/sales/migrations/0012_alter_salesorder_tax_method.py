# 新增 TaxMethod.UNTAXED;舊值 tax_free / zero_tax 仍保留在 choices 以相容歷史資料,
# 但 UI 不再顯示;同時把現有 tax_free / zero_tax 一次性遷移為 untaxed。

from django.db import migrations, models


def migrate_legacy(apps, schema_editor):
    SalesOrder = apps.get_model("sales", "SalesOrder")
    SalesOrder.objects.filter(tax_method__in=["tax_free", "zero_tax"]).update(
        tax_method="untaxed"
    )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0011_alter_salesorder_member'),
    ]

    operations = [
        migrations.AlterField(
            model_name='salesorder',
            name='tax_method',
            field=models.CharField(
                choices=[
                    ('taxable_included', '應稅內含'),
                    ('taxable_excluded', '應稅外加'),
                    ('untaxed', '未稅'),
                    ('tax_free', '免稅'),
                    ('zero_tax', '零稅'),
                ],
                default='taxable_included',
                max_length=20,
                verbose_name='課稅別',
            ),
        ),
        migrations.RunPython(migrate_legacy, noop),
    ]
