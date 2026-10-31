"""帶序號的新機(不是中古機)平均成本重算一次(2026-10-31)。

以前新機賣掉記的是那一台自己的進價,所以帳上剩下的貨值 = 剩下那幾台進價的加總;商品上的平均成本只在進貨時加權、
賣掉不動,跟剩下那幾台的平均會有差。2026-10-31 起賣掉改記平均成本(`inventory.models.book_cost`),
換過去的這一刻先把平均成本對齊剩下那幾台:現在算平均成本的那幾台(在庫 / 調撥中 / 換貨中 / 已退 / 整理中)
每一台進價的平均。現在一台都沒有的不動(下次進貨就是那一批的進價)。中古機不動。
"""
from decimal import Decimal

from django.db import migrations
from django.db.models import Count, Sum

COSTED = ("in_stock", "rma", "returned", "refurb", "in_transit")


def recompute(apps, schema_editor):
    Product = apps.get_model("catalog", "Product")
    ProductSerial = apps.get_model("inventory", "ProductSerial")
    rows = (
        ProductSerial.objects.filter(status__in=COSTED, product__requires_serial=True, product__is_secondhand=False)
        .values("product_id").annotate(total=Sum("purchase_unit_cost"), n=Count("id")).order_by("product_id")
    )
    for row in rows:
        Product.objects.filter(pk=row["product_id"]).update(
            weighted_avg_cost=(Decimal(row["total"]) / Decimal(row["n"])).quantize(Decimal("0.01"))
        )


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0024_buyback_avg_cost"),
    ]

    operations = [
        migrations.RunPython(recompute, migrations.RunPython.noop),
    ]
