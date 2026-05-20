from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0005_product_is_secondhand"),
    ]

    operations = [
        migrations.AddField(
            model_name="category",
            name="is_secondhand_default",
            field=models.BooleanField(
                default=False,
                help_text="勾起時,本類別下所有新增/編輯的商品自動標為中古機(逐隻記成色 / 電池 / 自定售價)",
                verbose_name="中古機類別",
            ),
        ),
    ]
