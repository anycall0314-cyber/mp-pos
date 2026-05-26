# 把 SalesOrder.member 從 Customer FK 改指 Member。
# 既有資料已在 parties/0012 清空,直接 AlterField 即可。

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0010_salesorder_member_alter_salesorder_customer'),
        ('parties', '0012_member'),
    ]

    operations = [
        migrations.AlterField(
            model_name='salesorder',
            name='member',
            field=models.ForeignKey(
                blank=True,
                help_text='掛載在這筆銷貨的會員(獨立主體);與 customer 不互斥',
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='sales_orders',
                to='parties.member',
                verbose_name='會員',
            ),
        ),
    ]
