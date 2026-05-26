# Generated for Member 獨立主檔重構。
#
# 改動:
#   1. 建立 Member 表
#   2. 把 SalesOrder.member 與 ProductSerial.acquired_from_member 的 FK 值清空
#      (專案上線前重構,既有測試資料不保留)
#   3. 刪除原 is_member=True 的 Customer 列(已不再被會員身分使用)
#
# 後續 migration 會:
#   sales/0011 → AlterField member.to = Member
#   inventory/0007 → AlterField acquired_from_member.to = Member
#   parties/0013 → RemoveField Customer.is_member

from django.db import migrations, models
import django.db.models.deletion


def wipe_member_data(apps, schema_editor):
    SalesOrder = apps.get_model("sales", "SalesOrder")
    SalesOrder.objects.exclude(member__isnull=True).update(member=None)

    ProductSerial = apps.get_model("inventory", "ProductSerial")
    ProductSerial.objects.exclude(acquired_from_member__isnull=True).update(
        acquired_from_member=None,
        acquired_via_sales_order=None,
    )

    Customer = apps.get_model("parties", "Customer")
    Customer.objects.filter(is_member=True).delete()


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('parties', '0011_alter_customer_options_and_more'),
        ('tenants', '0010_tenant_next_member_seq'),
        ('sales', '0010_salesorder_member_alter_salesorder_customer'),
        ('inventory', '0006_stockmovement_product_stockmovement_qty_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='Member',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='建立時間')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='更新時間')),
                ('code', models.SlugField(blank=True, editable=False, help_text='系統自動產生:M-{5位流水};前端不顯示也不輸入', max_length=20, verbose_name='會員編號')),
                ('name', models.CharField(max_length=120, verbose_name='姓名')),
                ('phone', models.CharField(blank=True, max_length=40, verbose_name='電話')),
                ('national_id', models.CharField(blank=True, max_length=20, verbose_name='身分證字號')),
                ('birthday', models.DateField(blank=True, null=True, verbose_name='生日')),
                ('address', models.CharField(blank=True, max_length=200, verbose_name='地址')),
                ('note', models.CharField(blank=True, max_length=200, verbose_name='備註')),
                ('is_active', models.BooleanField(default=True, verbose_name='啟用')),
                ('tenant', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to='tenants.tenant', verbose_name='租戶')),
            ],
            options={
                'verbose_name': '會員',
                'verbose_name_plural': '會員',
                'ordering': ['code'],
                'constraints': [models.UniqueConstraint(fields=('tenant', 'code'), name='uniq_member_tenant_code')],
            },
        ),
        migrations.RunPython(wipe_member_data, noop),
    ]
