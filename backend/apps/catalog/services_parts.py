"""零件批次建立 service。

兩個維度同時處理:
- 零件種類維度 → PartTemplate(可重複套用的範本)
- 機型維度 → 對選定的 model_keys 做笛卡兒積展開
"""
import re
from decimal import Decimal

from django.db import transaction

from .models import (
    Category,
    PartTemplate,
    Product,
    ProductRelation,
)

# 常見品牌縮寫對照表(未列的會自動取前 3 個英文字母大寫)
BRAND_ABBREV_MAP = {
    "apple": "APL",
    "samsung": "SAM",
    "xiaomi": "XIA",
    "redmi": "RED",
    "oppo": "OPP",
    "vivo": "VIV",
    "asus": "ASU",
    "huawei": "HUA",
    "honor": "HON",
    "sony": "SNY",
    "google": "GGL",
    "pixel": "GGL",
    "nokia": "NOK",
    "motorola": "MOT",
    "realme": "RLM",
    "oneplus": "OPL",
}


def derive_brand_code(brand: str) -> str:
    key = (brand or "").lower().strip()
    if key in BRAND_ABBREV_MAP:
        return BRAND_ABBREV_MAP[key]
    letters = re.sub(r"[^A-Za-z]", "", brand or "")
    return (letters[:3].upper()) or "BRD"


def derive_model_code(model_name: str, brand: str = "") -> str:
    """iPhone 13 Pro Max → 13PM;Galaxy S24 Ultra → S24U;Pixel 8 Pro → 8P。"""
    name = model_name or ""
    if brand and name.lower().startswith(brand.lower()):
        name = name[len(brand):].strip()
    for prefix in ("iPhone", "Galaxy", "Redmi", "Pixel"):
        if name.lower().startswith(prefix.lower()):
            name = name[len(prefix):].strip()
            break
    # 尾段縮寫(順序很重要:長詞先匹配)
    rules = [
        (r"\s*Pro\s+Max\b", "PM"),
        (r"\s*Plus\b", "L"),
        (r"\s*Ultra\b", "U"),
        (r"\s*Pro\b", "P"),
        (r"\s*Max\b", "M"),
        (r"\s*Mini\b", "MN"),
        (r"\s*FE\b", "FE"),
    ]
    for pattern, sub in rules:
        name = re.sub(pattern, sub, name, flags=re.I)
    name = re.sub(r"\s+", "", name)
    return (name.upper()) or "X"


def build_preview(tenant, template_id, model_keys, defaults=None):
    """每個 model_key × 範本零件 組合一筆預覽 row。

    defaults: {"cost": str, "safety_stock": int}(統一套用值,個別 item 有 default 會優先)
    回傳 rows list,每筆含 sku/name/cost/safety_stock + exists 標記。
    """
    defaults = defaults or {}
    default_cost = Decimal(str(defaults.get("cost") or "0"))
    default_safety = int(defaults.get("safety_stock") or 0)

    template = (
        PartTemplate.objects.for_tenant(tenant)
        .prefetch_related("items")
        .get(pk=template_id)
    )

    hosts = Product.objects.for_tenant(tenant).filter(
        accessory_type=Product.AccessoryType.NONE,
        is_active=True,
        is_virtual=False,
    )
    keys_lower = {k.lower().strip() for k in model_keys}
    host_by_key: dict[str, Product] = {}
    for p in hosts:
        k = p.phone_model_key
        if k and k in keys_lower and k not in host_by_key:
            host_by_key[k] = p

    existing_skus = set(
        Product.objects.for_tenant(tenant).values_list("sku", flat=True)
    )

    rows = []
    for k in keys_lower:
        host = host_by_key.get(k)
        model_name = host.phone_model_name if host else k
        brand = host.brand if host else ""
        brand_code = derive_brand_code(brand)
        model_code = derive_model_code(model_name, brand)
        for item in template.items.all():
            sku = f"PRT-{brand_code}-{model_code}-{item.code}"
            name = f"{model_name} {item.name}"
            cost = item.default_cost if item.default_cost else default_cost
            safety = (
                item.default_safety_stock
                if item.default_safety_stock
                else default_safety
            )
            rows.append(
                {
                    "model_key": k,
                    "model_name": model_name,
                    "brand": brand,
                    "brand_code": brand_code,
                    "model_code": model_code,
                    "item_id": item.id,
                    "item_name": item.name,
                    "item_code": item.code,
                    "name": name,
                    "sku": sku,
                    "cost": str(cost),
                    "safety_stock": safety,
                    "exists": sku in existing_skus,
                }
            )
    return rows


@transaction.atomic
def bulk_create_parts(tenant, category_id, rows):
    """批次建立零件 Product + ProductRelation。

    每筆 row: {model_key, name, sku, cost, safety_stock}
    """
    category = Category.objects.for_tenant(tenant).get(pk=category_id)

    hosts_by_key: dict[str, Product] = {}
    for p in Product.objects.for_tenant(tenant).filter(
        accessory_type=Product.AccessoryType.NONE, is_active=True
    ):
        k = p.phone_model_key
        if k and k not in hosts_by_key:
            hosts_by_key[k] = p

    created = 0
    skipped: list[str] = []
    errors: list[dict] = []

    for r in rows:
        sku = (r.get("sku") or "").strip()
        if not sku:
            errors.append({"sku": "", "error": "品號為空"})
            continue
        if Product.objects.for_tenant(tenant).filter(sku=sku).exists():
            skipped.append(sku)
            continue
        try:
            prod = Product.objects.create(
                tenant=tenant,
                category=category,
                sku=sku,
                name=(r.get("name") or sku).strip(),
                accessory_type=Product.AccessoryType.PHONE_SPECIFIC,
                warehouse_type=Product.WarehouseType.PARTS,
                requires_serial=False,
                is_virtual=False,
                is_secondhand=False,
                lifecycle_status=Product.LifecycleStatus.ACTIVE,
                safety_stock=int(r.get("safety_stock") or 0),
                weighted_avg_cost=Decimal(str(r.get("cost") or "0")),
            )
            model_key = (r.get("model_key") or "").lower().strip()
            host = hosts_by_key.get(model_key)
            if host and host.id != prod.id:
                ProductRelation.objects.create(
                    tenant=tenant,
                    host_product=host,
                    host_model_key=model_key,
                    accessory_product=prod,
                )
            created += 1
        except Exception as e:  # noqa: BLE001
            errors.append({"sku": sku, "error": str(e)})

    return {"created": created, "skipped": skipped, "errors": errors}
