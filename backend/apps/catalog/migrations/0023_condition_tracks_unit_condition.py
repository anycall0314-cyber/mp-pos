from django.db import migrations, models


def seed_tracks_unit_condition(apps, schema_editor):
    """全新機不用逐台記機況;其餘(已拆封 / 中古)都要。

    欄位 default=True,所以這裡只把「全新且不是中古機」的 `brand-new` 改成 False。
    有些租戶可能把 brand-new 手動改成中古機了,那筆不能關(中古機的成色與
    每台成本本來就必填,關掉會讓進貨卡死)。
    經銷商自己加的狀態維持 True(記多了可以不填,漏記會救不回來)。
    """
    Condition = apps.get_model("catalog", "Condition")
    Condition.objects.filter(code="brand-new", is_secondhand=False).update(
        tracks_unit_condition=False
    )
    # 中古機一律逐台記(順手修掉任何既有的矛盾資料,CheckConstraint 才加得上)
    Condition.objects.filter(is_secondhand=True).update(tracks_unit_condition=True)


def unseed(apps, schema_editor):
    # 欄位會被整個移除,不需要回復資料
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0022_product_capacity_product_color_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="condition",
            name="tracks_unit_condition",
            field=models.BooleanField(
                default=True,
                help_text=(
                    "勾選後,進貨時這個狀態的每一台都可以記成色 / 電池 / 個別售價 / 備註。"
                    "與「視為中古機」分開:已拆封不是中古機,但一樣要逐台記。"
                    "成本政策仍只看「視為中古機」"
                ),
                verbose_name="逐台記機況",
            ),
        ),
        migrations.RunPython(seed_tracks_unit_condition, unseed),
        migrations.AddConstraint(
            model_name="condition",
            constraint=models.CheckConstraint(
                check=~models.Q(is_secondhand=True, tracks_unit_condition=False),
                name="condition_secondhand_tracks_unit",
            ),
        ),
    ]
