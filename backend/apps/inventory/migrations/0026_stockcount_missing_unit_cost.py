"""盤虧那一台記下標成盤虧當下的成本(2026-10-31)。

新機帳上的成本改成平均成本之後,盤虧金額要是即時讀平均,之後一進貨,已核准的盤點單金額就跟著變。
以前已經標成盤虧的那幾台補上當時畫面上的數字(那一台的成本 `purchase_unit_cost`),金額不變。
"""
from django.db import migrations, models
from django.db.models import OuterRef, Subquery


def backfill(apps, schema_editor):
    StockCountMissing = apps.get_model("inventory", "StockCountMissing")
    ProductSerial = apps.get_model("inventory", "ProductSerial")
    StockCountMissing.objects.filter(applied=True, unit_cost__isnull=True).update(
        unit_cost=Subquery(ProductSerial.objects.filter(pk=OuterRef("serial_id")).values("purchase_unit_cost")[:1])
    )


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0025_new_phone_avg_cost"),
    ]

    operations = [
        migrations.AddField(
            model_name="stockcountmissing",
            name="unit_cost",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True, verbose_name="盤虧當下的成本"),
        ),
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
