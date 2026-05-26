import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0012_alter_salesorder_tax_method'),
        ('parties', '0013_remove_customer_is_member'),
        ('catalog', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='LegacyPurchase',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='建立時間')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='更新時間')),
                ('qty', models.PositiveIntegerField(default=1, verbose_name='數量')),
                ('unit_price', models.DecimalField(decimal_places=2, help_text='舊系統當時成交價(已含稅或未稅依舊系統而定,匯入時保持原值)', max_digits=14, verbose_name='單價')),
                ('doc_date', models.DateField(verbose_name='交易日期')),
                ('source_no', models.CharField(blank=True, help_text='舊系統的銷貨單號;僅供對照,無業務邏輯', max_length=40, verbose_name='舊單號')),
                ('serial_no', models.CharField(blank=True, help_text='如為手機可填,僅供查詢對照', max_length=80, verbose_name='序號 / IMEI')),
                ('note', models.CharField(blank=True, max_length=200, verbose_name='備註')),
                ('member', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='legacy_purchases', to='parties.member', verbose_name='會員')),
                ('product', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='legacy_purchases', to='catalog.product', verbose_name='商品')),
                ('tenant', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to='tenants.tenant', verbose_name='租戶')),
            ],
            options={
                'verbose_name': '舊系統消費紀錄',
                'verbose_name_plural': '舊系統消費紀錄',
                'ordering': ['-doc_date', '-id'],
            },
        ),
        migrations.AddIndex(
            model_name='legacypurchase',
            index=models.Index(fields=['member', 'product'], name='sales_legac_member__1f8b3c_idx'),
        ),
        migrations.AddIndex(
            model_name='legacypurchase',
            index=models.Index(fields=['tenant', 'doc_date'], name='sales_legac_tenant__9d2a1e_idx'),
        ),
    ]
