from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("purchasing", "0008_billed_qty_zero_is_zero")]
    operations = [migrations.AddField(
        model_name="purchaseorder", name="cash_paid",
        field=models.DecimalField("現金實付", max_digits=14, decimal_places=2, null=True, blank=True, editable=False,
                                  help_text="廠商貨到付款的實際支出，包含本次實付運費；空白的舊單沿用含稅總額"),
    )]
