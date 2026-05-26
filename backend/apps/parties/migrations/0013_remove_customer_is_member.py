# 移除 Customer.is_member;會員身分已搬到獨立的 Member 表。

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('parties', '0012_member'),
        ('sales', '0011_alter_salesorder_member'),
        ('inventory', '0007_alter_productserial_acquired_from_member'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='customer',
            name='is_member',
        ),
    ]
