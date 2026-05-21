# Data migration: 既有供應商代碼全部重新編號為 S-000001 起,並給定 sort_order。
from django.db import migrations


def renumber(apps, schema_editor):
    Supplier = apps.get_model("parties", "Supplier")
    Tenant = apps.get_model("tenants", "Tenant")

    for tenant in Tenant.objects.all():
        suppliers = list(
            Supplier.objects.filter(tenant=tenant).order_by("code", "pk")
        )
        if not suppliers:
            continue
        # 兩階段重編,避免重編過程觸發 (tenant, code) 唯一限制的暫時衝突:
        # 1) 先把每筆改成以 pk 為基底、保證互不重複的暫時碼
        for sup in suppliers:
            Supplier.objects.filter(pk=sup.pk).update(code=f"__tmp{sup.pk}")
        # 2) 再依序寫入最終 S-000001 起的代碼與排序
        for idx, sup in enumerate(suppliers, start=1):
            Supplier.objects.filter(pk=sup.pk).update(
                code=f"S-{idx:06d}", sort_order=idx * 10
            )
        tenant.next_supplier_seq = len(suppliers) + 1
        tenant.save(update_fields=["next_supplier_seq"])


def noop(apps, schema_editor):
    # 不可逆:舊代碼已遺失,回滾僅保留現況
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("parties", "0009_alter_supplier_options_supplier_sort_order_and_more"),
        ("tenants", "0006_tenant_next_supplier_seq"),
    ]

    operations = [
        migrations.RunPython(renumber, noop),
    ]
