import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0013_legacypurchase'),
        ('parties', '0013_remove_customer_is_member'),
        ('inventory', '0007_alter_productserial_acquired_from_member'),
        ('catalog', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='salesorder',
            name='invoice_voided',
            field=models.BooleanField(
                default=False,
                help_text='銷退單建立時若選「作廢原發票」,系統把此旗標標 True;發票字軌號碼仍保留供查詢',
                verbose_name='原發票已作廢',
            ),
        ),
        migrations.CreateModel(
            name='SalesReturn',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='建立時間')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='更新時間')),
                ('no', models.CharField(blank=True, editable=False, help_text='系統自動產生:SR-{6位流水}', max_length=30, verbose_name='單號')),
                ('doc_date', models.DateField(verbose_name='單據日期')),
                ('payment_method', models.CharField(help_text='必須與原銷貨單付款方式中的某一筆相符;對應 PaymentMethod.code', max_length=20, verbose_name='退款方式')),
                ('void_original_invoice', models.BooleanField(default=True, help_text='True 時:提交銷退單會把原 SalesOrder.invoice_voided 標 True(已標過則不重覆)', verbose_name='作廢原發票')),
                ('note', models.CharField(blank=True, max_length=200, verbose_name='備註')),
                ('is_void', models.BooleanField(default=False, verbose_name='作廢')),
                ('subtotal', models.DecimalField(decimal_places=2, default=0, editable=False, max_digits=14, verbose_name='未稅小計')),
                ('tax_amount', models.DecimalField(decimal_places=2, default=0, editable=False, max_digits=14, verbose_name='稅額')),
                ('total', models.DecimalField(decimal_places=2, default=0, editable=False, help_text='正數,代表退給客戶的金額', max_digits=14, verbose_name='含稅退款額')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='作業者')),
                ('customer', models.ForeignKey(blank=True, help_text='自原銷貨單帶入,不可改', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='sales_returns', to='parties.customer', verbose_name='客戶')),
                ('member', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='sales_returns', to='parties.member', verbose_name='會員')),
                ('original_so', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='returns', to='sales.salesorder', verbose_name='原銷貨單')),
                ('tenant', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to='tenants.tenant', verbose_name='租戶')),
                ('warehouse', models.ForeignKey(help_text='原則上 = 原銷貨倉,讓退貨庫存回原倉', on_delete=django.db.models.deletion.PROTECT, related_name='sales_returns', to='inventory.warehouse', verbose_name='退回倉')),
            ],
            options={
                'verbose_name': '銷退單',
                'verbose_name_plural': '銷退單',
                'ordering': ['-doc_date', '-id'],
                'constraints': [models.UniqueConstraint(fields=('tenant', 'no'), name='uniq_salesreturn_tenant_no')],
            },
        ),
        migrations.CreateModel(
            name='SalesReturnItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='建立時間')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='更新時間')),
                ('line_no', models.PositiveIntegerField(default=1, verbose_name='行號')),
                ('qty', models.PositiveIntegerField(verbose_name='退貨數量')),
                ('unit_price', models.DecimalField(decimal_places=2, help_text='鎖定為原銷貨單的單價,不可改', max_digits=14, verbose_name='單價')),
                ('amount', models.DecimalField(decimal_places=2, editable=False, max_digits=14, verbose_name='小計')),
                ('original_item', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='returned_in', to='sales.salesorderitem', verbose_name='原銷貨明細')),
                ('product', models.ForeignKey(help_text='自 original_item 帶入,供查詢方便', on_delete=django.db.models.deletion.PROTECT, related_name='+', to='catalog.product', verbose_name='商品')),
                ('sr', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='items', to='sales.salesreturn', verbose_name='銷退單')),
                ('tenant', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to='tenants.tenant', verbose_name='租戶')),
            ],
            options={
                'verbose_name': '銷退明細',
                'verbose_name_plural': '銷退明細',
                'ordering': ['sr', 'line_no', 'id'],
            },
        ),
        migrations.CreateModel(
            name='SalesReturnItemSerial',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='建立時間')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='更新時間')),
                ('line_pos', models.PositiveIntegerField(default=1, verbose_name='行內序')),
                ('item', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='serials', to='sales.salesreturnitem', verbose_name='銷退明細')),
                ('serial', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='return_lines', to='inventory.productserial', verbose_name='序號')),
                ('tenant', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to='tenants.tenant', verbose_name='租戶')),
            ],
            options={
                'verbose_name': '銷退序號',
                'verbose_name_plural': '銷退序號',
                'ordering': ['item', 'line_pos', 'id'],
                'constraints': [models.UniqueConstraint(fields=('item', 'serial'), name='uniq_salesreturn_item_serial')],
            },
        ),
    ]
