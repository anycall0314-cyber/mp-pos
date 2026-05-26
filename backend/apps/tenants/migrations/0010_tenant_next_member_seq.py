from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenants', '0009_tenant_next_cash_adj_seq'),
    ]

    operations = [
        migrations.AddField(
            model_name='tenant',
            name='next_member_seq',
            field=models.PositiveIntegerField(default=1, editable=False, verbose_name='下一會員流水'),
        ),
    ]
