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
from .phone_model import infer_brand_from_name

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

    # 預先依品牌分組,給「跨機型共用」的零件用 — brand 取 FK code,沒設則從品名推斷
    by_brand: dict[str, list[tuple[str, str, str]]] = {}
    for k in keys_lower:
        host = host_by_key.get(k)
        model_name = host.phone_model_name if host else k
        brand_code = ""
        if host and host.brand_id:
            brand_code = host.brand.code
        if not brand_code:
            brand_code = infer_brand_from_name(host.name if host else k)
        by_brand.setdefault(brand_code, []).append((k, model_name, brand_code))

    rows = []
    for item in template.items.all():
        cost = item.default_cost if item.default_cost else default_cost
        safety = (
            item.default_safety_stock
            if item.default_safety_stock
            else default_safety
        )
        if item.shared_across_models:
            # 共用:每個品牌一筆,相容該品牌所有選定機型
            for brand, model_list in by_brand.items():
                brand_code = derive_brand_code(brand)
                sku = f"PRT-{brand_code}-SHARED-{item.code}"
                # 共用品名取品牌或第一支機型名
                brand_label = brand or (model_list[0][1] if model_list else "")
                name = f"{brand_label} {item.name}(共用)"
                model_keys_list = [k for k, _, _ in model_list]
                model_names_list = [n for _, n, _ in model_list]
                rows.append(
                    {
                        "model_key": ",".join(model_keys_list),
                        "model_keys": model_keys_list,
                        "model_name": " / ".join(model_names_list),
                        "brand": brand,
                        "brand_code": brand_code,
                        "model_code": "SHARED",
                        "item_id": item.id,
                        "item_name": item.name,
                        "item_code": item.code,
                        "name": name,
                        "sku": sku,
                        "cost": str(cost),
                        "safety_stock": safety,
                        "exists": sku in existing_skus,
                        "shared": True,
                    }
                )
        else:
            # 單機型專屬:每個 model_key 一筆(預設行為)
            for k in keys_lower:
                host = host_by_key.get(k)
                model_name = host.phone_model_name if host else k
                # brand: FK code 優先,沒設就推斷
                raw_brand = ""
                if host and host.brand_id:
                    raw_brand = host.brand.code
                if not raw_brand:
                    raw_brand = infer_brand_from_name(
                        host.name if host else k
                    )
                brand_code = derive_brand_code(raw_brand)
                brand = raw_brand
                model_code = derive_model_code(model_name, brand)
                sku = f"PRT-{brand_code}-{model_code}-{item.code}"
                name = f"{model_name} {item.name}"
                rows.append(
                    {
                        "model_key": k,
                        "model_keys": [k],
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
                        "shared": False,
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
            # 支援單機型 or 跨機型共用兩種 row:
            # - shared rows: r["model_keys"] 為 list,逐一建關聯
            # - 一般 rows: 用 r["model_key"]
            target_keys: list[str] = []
            mk_list = r.get("model_keys")
            if isinstance(mk_list, list) and mk_list:
                target_keys = [str(x).lower().strip() for x in mk_list if x]
            else:
                single = (r.get("model_key") or "").lower().strip()
                if single:
                    target_keys = [single]
            for mk in target_keys:
                host = hosts_by_key.get(mk)
                if host and host.id != prod.id:
                    ProductRelation.objects.get_or_create(
                        tenant=tenant,
                        host_product=host,
                        host_model_key=mk,
                        accessory_product=prod,
                    )
            created += 1
        except Exception as e:  # noqa: BLE001
            errors.append({"sku": sku, "error": str(e)})

    return {"created": created, "skipped": skipped, "errors": errors}
