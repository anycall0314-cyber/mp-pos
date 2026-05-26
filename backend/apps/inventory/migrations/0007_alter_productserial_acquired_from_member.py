# 把 ProductSerial.acquired_from_member 從 Customer FK 改指 Member。
# 既有資料已在 parties/0012 清空,直接 AlterField 即可。

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0006_stockmovement_product_stockmovement_qty_and_more'),
        ('parties', '0012_member'),
    ]

    operations = [
        migrations.AlterField(
            model_name='productserial',
            name='acquired_from_member',
            field=models.ForeignKey(
                blank=True,
                help_text='從個人會員收購的中古機,記錄賣家;廠商來源留空',
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='acquired_serials',
                to='parties.member',
                verbose_name='收購來源會員',
            ),
        ),
    ]
