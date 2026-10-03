"""別名:通用別名唯一、已確認才唯一、記錄建立 / 修改者。

加唯一約束前先檢查既有資料。有衝突就**停下來列出來**,不自動刪除或合併 ——
哪一筆才對要人來判斷,migration 猜不出來。
"""
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def _check_generic_alias_conflicts(apps, schema_editor):
    ProductAlias = apps.get_model("identity", "ProductAlias")
    from django.db.models import Count

    dupes = list(
        ProductAlias.objects
        .filter(supplier__isnull=True, is_active=True, verified=True)
        .values("tenant_id", "kind", "normalized_value")
        .annotate(n=Count("id"))
        .filter(n__gt=1)
        .order_by("tenant_id", "kind", "normalized_value")
    )
    if not dupes:
        return
    lines = []
    for d in dupes[:50]:
        rows = ProductAlias.objects.filter(
            supplier__isnull=True, is_active=True, verified=True,
            tenant_id=d["tenant_id"], kind=d["kind"],
            normalized_value=d["normalized_value"],
        ).values_list("id", "value", "product_id")
        detail = "、".join(f"別名#{i}「{v}」→ 商品#{p}" for i, v, p in rows)
        lines.append(f"  租戶 {d['tenant_id']} / {d['kind']}:{detail}")
    raise RuntimeError(
        "通用別名有重複,無法加上唯一約束。請先在別名管理把每組留一筆"
        "(其餘停用,或把「已確認」取消改成關鍵字)再重跑 migrate:\n"
        + "\n".join(lines)
        + (f"\n  …另有 {len(dupes) - 50} 組" if len(dupes) > 50 else "")
    )


class Migration(migrations.Migration):

    dependencies = [
        ("identity", "0007_intakeitem_alias_conflicts"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="productalias",
            name="created_by",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name="+", to=settings.AUTH_USER_MODEL, verbose_name="建立者",
            ),
        ),
        migrations.AddField(
            model_name="productalias",
            name="updated_by",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name="+", to=settings.AUTH_USER_MODEL, verbose_name="最後修改者",
            ),
        ),
        migrations.AlterField(
            model_name="productalias",
            name="verified",
            field=models.BooleanField(
                default=True,
                help_text=(
                    "True = 這個叫法只指這一個商品,下次可以直接對應。"
                    "False = 只是搜尋用的關鍵字(太籠統、或同一句話有好幾款),"
                    "找得到候選但不會自動對應,同一句話可以掛在多個商品上"
                ),
                verbose_name="已確認",
            ),
        ),
        # 這條只是放寬(原本所有啟用中的都唯一 → 現在只有已確認的唯一),
        # 既有資料一定滿足,不需要檢查。
        migrations.RemoveConstraint(
            model_name="productalias",
            name="uniq_alias_vendor_ref",
        ),
        migrations.AddConstraint(
            model_name="productalias",
            constraint=models.UniqueConstraint(
                condition=models.Q(("is_active", True), ("verified", True)),
                fields=("tenant", "supplier", "kind", "normalized_value"),
                name="uniq_alias_vendor_ref",
            ),
        ),
        migrations.RunPython(_check_generic_alias_conflicts, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="productalias",
            constraint=models.UniqueConstraint(
                condition=models.Q(
                    ("is_active", True), ("supplier__isnull", True), ("verified", True)
                ),
                fields=("tenant", "kind", "normalized_value"),
                name="uniq_alias_generic",
            ),
        ),
    ]
