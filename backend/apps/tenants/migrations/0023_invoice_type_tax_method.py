from django.db import migrations, models


def keep_old_meaning(apps, schema_editor):
    """以前「免用」一律切成未稅:既有的免用照舊帶未稅(要改的店家在業務設定改)。"""
    InvoiceType = apps.get_model("tenants", "InvoiceType")
    InvoiceType.objects.filter(code="none").update(tax_method="untaxed")


class Migration(migrations.Migration):

    dependencies = [
        ('tenants', '0022_auto_device_models'),
    ]

    operations = [
        migrations.AddField(
            model_name='invoicetype',
            name='tax_method',
            field=models.CharField(blank=True, choices=[('', '不帶'), ('taxable_included', '應稅內含'), ('taxable_excluded', '應稅外加'), ('untaxed', '未稅')], db_default='', default='', max_length=20, verbose_name='帶入課稅別'),
        ),
        migrations.RunPython(keep_old_meaning, migrations.RunPython.noop),
    ]
