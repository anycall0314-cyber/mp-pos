"""PostgreSQL pg_trgm extension + GIN trigram indexes for fuzzy search.

只在 PostgreSQL 上有效;SQLite 跑這支 migration 會被 RunSQL 內的 if 跳過。
"""
from django.contrib.postgres.operations import TrigramExtension
from django.db import migrations


# (table, column) pairs needing trigram GIN index for ?search= 模糊查詢
TRGM_TARGETS = [
    ("catalog_product", "name"),
    ("catalog_product", "sku"),
    ("catalog_product", "barcode"),
    ("catalog_product", "spec"),
    ("parties_customer", "name"),
    ("parties_customer", "phone"),
    ("parties_customer", "tax_id"),
    ("parties_supplier", "name"),
    ("parties_supplier", "code"),
    ("parties_carrier", "name"),
    ("parties_carrier", "code"),
    ("parties_telecomplan", "name"),
    ("parties_telecomplan", "code"),
    ("parties_simcard", "card_no"),
    ("parties_salesperson", "name"),
    ("parties_salesperson", "code"),
    ("inventory_warehouse", "name"),
    ("inventory_warehouse", "code"),
    ("inventory_productserial", "serial_no"),
]


def _make_sql():
    forwards, reverses = [], []
    for table, col in TRGM_TARGETS:
        idx = f"idx_{table}_{col}_trgm"[:63]
        forwards.append(
            f'CREATE INDEX IF NOT EXISTS "{idx}" ON "{table}" USING gin ("{col}" gin_trgm_ops);'
        )
        reverses.append(f'DROP INDEX IF EXISTS "{idx}";')
    return "\n".join(forwards), "\n".join(reverses)


_FWD, _REV = _make_sql()


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0004_product_counts_cash_product_counts_margin_and_more"),
        ("parties", "0008_carrier_next_plan_seq_telecomplan_name_and_more"),
        ("inventory", "0003_productserial_purchase_order_item"),
    ]

    operations = [
        TrigramExtension(),
        migrations.RunSQL(sql=_FWD, reverse_sql=_REV),
    ]
