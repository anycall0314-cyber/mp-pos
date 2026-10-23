from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('parties', '0017_customer_is_sales_default_member_contact_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='supplier',
            name='short_name',
            field=models.CharField(blank=True, db_default='', default='', max_length=20, verbose_name='簡稱'),
        ),
    ]
