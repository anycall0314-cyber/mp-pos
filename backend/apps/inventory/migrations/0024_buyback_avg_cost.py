"""收購進來過的中古機品號,平均成本重算一次(2026-10-30)。

以前個人收購只把收購價記在那一台上,商品的平均成本沒動(`sales.services.acquire_secondhand_from_member`
2026-10-30 起照進貨的算法加進去),那些品號的平均成本少了收購價,送去整理完只剩整理費。
重算 = 現在算平均成本的那幾台(在庫 / 換貨中 / 已退 / 整理中,`COSTED_STATUSES`)每一台成本的平均
(中古機每一台自己的成本,收購價與整理費都在那一台上)。現在一台都沒有的不動。
"""
from decimal import Decimal

from django.db import migrations

COSTED = ("in_stock", "rma", "returned", "refurb")


def recompute(apps, schema_editor):
    Product = apps.get_model("catalog", "Product")
    ProductSerial = apps.get_model("inventory", "ProductSerial")
    bought = set(
        ProductSerial.objects.filter(acquired_via_sales_order__isnull=False).values_list("product_id", flat=True)
    )
    for product in Product.objects.filter(pk__in=bought).order_by("pk"):
        costs = list(
            ProductSerial.objects.filter(product=product, status__in=COSTED).values_list("purchase_unit_cost", flat=True)
        )
        if not costs:
            continue
        product.weighted_avg_cost = (sum(costs, Decimal("0")) / Decimal(len(costs))).quantize(Decimal("0.01"))
        product.save(update_fields=["weighted_avg_cost"])


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0023_serial_refurb"),
        ("catalog", "0034_product_telecom_carrier"),
    ]

    operations = [
        migrations.RunPython(recompute, migrations.RunPython.noop),
    ]
