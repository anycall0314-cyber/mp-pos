import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cash', '0002_cashadjustment'),
        ('parties', '0013_remove_customer_is_member'),
    ]

    operations = [
        migrations.AddField(
            model_name='pettyexpense',
            name='handled_by',
            field=models.ForeignKey(
                blank=True,
                help_text='實際支出的執行人(從業務員主檔挑);用於老闆對帳',
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='petty_expenses_handled',
                to='parties.salesperson',
                verbose_name='經手人',
            ),
        ),
    ]
