# 廠商換貨補上配件(2026-10-21):設備可以空著、多了商品 / 數量 / 回來的數量 / 單位成本、「不換了」。
# 0019 只上過測試站;已經有的紀錄(都是設備)商品照那一台補上。
import django.db.models.deletion
from django.db import migrations, models


def fill_product(apps, schema_editor):
    VendorExchange = apps.get_model("inventory", "VendorExchange")
    for x in VendorExchange.objects.filter(product__isnull=True).select_related("serial"):
        x.product_id = x.serial.product_id
        x.unit_cost = x.serial.purchase_unit_cost
        x.save(update_fields=["product", "unit_cost"])


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0034_product_telecom_carrier"),
        ("inventory", "0019_vendor_exchange"),
    ]

    operations = [
        migrations.AlterField(
            model_name="vendorexchange",
            name="serial",
            field=models.ForeignKey(
                blank=True, help_text="配件(按數量的)是空的", null=True,
                on_delete=django.db.models.deletion.PROTECT, related_name="vendor_exchanges",
                to="inventory.productserial", verbose_name="設備"),
        ),
        migrations.AddField(
            model_name="vendorexchange",
            name="product",
            field=models.ForeignKey(
                null=True, on_delete=django.db.models.deletion.PROTECT, related_name="vendor_exchanges",
                to="catalog.product", verbose_name="商品"),
        ),
        migrations.AddField(
            model_name="vendorexchange",
            name="qty",
            field=models.PositiveIntegerField(db_default=1, default=1, verbose_name="送出數量"),
        ),
        migrations.AddField(
            model_name="vendorexchange",
            name="back_qty",
            field=models.PositiveIntegerField(db_default=0, default=0, verbose_name="回來的數量"),
        ),
        migrations.AddField(
            model_name="vendorexchange",
            name="unit_cost",
            field=models.DecimalField(
                db_default=0, decimal_places=2, default=0, max_digits=14,
                help_text="配件:送出那一刻這家門市的平均成本(換回來照這個加回去);設備:那一台的成本",
                verbose_name="送出時的單位成本"),
        ),
        migrations.RunPython(fill_product, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="vendorexchange",
            name="product",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT, related_name="vendor_exchanges",
                to="catalog.product", verbose_name="商品"),
        ),
        migrations.AlterField(
            model_name="vendorexchange",
            name="status",
            field=models.CharField(
                choices=[("pending", "換貨中"), ("done", "已換貨"), ("cancelled", "取消"), ("unreturned", "不換了")],
                default="pending", max_length=12, verbose_name="狀態"),
        ),
        migrations.AddConstraint(
            model_name="vendorexchange",
            constraint=models.CheckConstraint(
                condition=models.Q(("back_qty__lte", models.F("qty")), ("qty__gte", 1)),
                name="vendor_exchange_qty_ok"),
        ),
    ]
