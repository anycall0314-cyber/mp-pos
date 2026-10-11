from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("vendor_orders", "0004_manual_vendors"), ("purchasing", "0009_purchaseorder_cash_paid")]
    operations = [migrations.AddField(
        model_name="vendorreceipt", name="shipping_paid",
        field=models.DecimalField("本次實付運費", max_digits=14, decimal_places=2, null=True, blank=True),
    )]
