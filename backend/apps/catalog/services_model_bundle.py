"""新增手機型號 bundle service。

把「狀態 × 容量 × 顏色」cartesian 展開成主機 SKU,並依範本同時建好
配件 placeholder 與維修零件 SKU,全部用 ProductRelation 綁定到該機型。

用途:wizard「+ 新增 iPhone 17 Pro」按下「建立全部」時呼叫此 service,
之後遇到全新 / 已拆封 / 中古機收購 都不用再多一道「先建商品」手續,
直接掛序號即可。

呼叫者:
- POST /api/v1/products/create-phone-model/  (dry_run=true 預覽,false 真建)
"""
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from django.db import transaction

from .models import (
    Brand,
    Category,
    Condition,
    PartTemplate,
    PhoneSeries,
    Product,
    ProductRelation,
)
from .phone_model import compute_phone_model_key, compute_phone_model_name


@dataclass
class PartItemSpec:
    name: str
    code: str
    default_cost: str = "0"
    default_safety_stock: int = 0
    shared_across_models: bool = False


def _format_phone_model_name(brand, series, generation, model_suffix):
    """利用既有 compute_phone_model_name 把標題組出來。

    這裡建一個臨時 Product instance(不 save)餵給 helper,確保命名邏輯
    跟「型號展開頁」/「商品搜尋分組」完全一致。
    """
    tmp = Product(
        brand=brand,
        series=series,
        generation=generation,
        model_suffix=model_suffix or "",
        name="",
        spec="",
    )
    return compute_phone_model_name(tmp).strip()


def _resolve_or_error(model_cls, tenant, **kwargs):
    """依 id 查 per-tenant 物件,找不到丟 ValueError(會被 endpoint 翻成 400)。"""
    qs = model_cls.objects.for_tenant(tenant).filter(**kwargs)
    obj = qs.first()
    if not obj:
        raise ValueError(
            f"{model_cls.__name__} 找不到符合條件:{kwargs}"
        )
    return obj


def preview_phone_model_bundle(tenant, payload):
    """dry_run 預覽 — 算出會建幾個 SKU,以及每個 SKU 的名稱,但不寫 DB。"""
    return _build_bundle(tenant, payload, dry_run=True)


def create_phone_model_bundle(tenant, payload):
    """真的建立 — 寫入 DB,回傳建好的 SKU 摘要。"""
    return _build_bundle(tenant, payload, dry_run=False)


@transaction.atomic
def _build_bundle(tenant, payload, *, dry_run):
    """核心邏輯。dry_run=True 時 atomic 外殼仍會用,確保 raise 都會回滾;
    但只要不 raise、不 save,就不會有任何寫入。
    """
    # ── 基本資料(必填)
    brand_id = payload.get("brand_id")
    if not brand_id:
        raise ValueError("brand_id 必填")
    brand = _resolve_or_error(Brand, tenant, id=brand_id)

    series_id = payload.get("series_id")
    series = None
    if series_id:
        series = _resolve_or_error(PhoneSeries, tenant, id=series_id)

    generation = payload.get("generation")  # int or None
    model_suffix = (payload.get("model_suffix") or "").strip()

    main_category_id = payload.get("main_category_id")
    if not main_category_id:
        raise ValueError("main_category_id 必填(主機類別)")
    main_category = _resolve_or_error(Category, tenant, id=main_category_id)

    list_price = payload.get("list_price") or "0"

    # 配件 / 零件用的 Category — 沒指定就退回 main_category
    accessory_category_id = payload.get("accessory_category_id") or main_category_id
    accessory_category = _resolve_or_error(
        Category, tenant, id=accessory_category_id
    )
    parts_category_id = payload.get("parts_category_id") or main_category_id
    parts_category = _resolve_or_error(Category, tenant, id=parts_category_id)

    # ── 維度資料
    condition_ids = payload.get("condition_ids") or []
    if not condition_ids:
        raise ValueError("至少要選 1 個狀態")
    conditions = list(
        Condition.objects.for_tenant(tenant)
        .filter(id__in=condition_ids, is_active=True)
        .order_by("sort_order", "id")
    )
    if len(conditions) != len(condition_ids):
        raise ValueError("有 condition_id 找不到或已停用")

    capacities = [c.strip() for c in (payload.get("capacities") or []) if c.strip()]
    colors = [c.strip() for c in (payload.get("colors") or []) if c.strip()]
    if not capacities:
        raise ValueError("至少要選 1 個容量")
    if not colors:
        raise ValueError("至少要選 1 個顏色")

    accessory_categories = [
        c.strip() for c in (payload.get("accessory_categories") or []) if c.strip()
    ]

    # 零件:範本提供 + payload 可覆寫
    template_id = payload.get("template_id")
    parts_items: list[PartItemSpec] = []
    template = None
    if template_id:
        template = _resolve_or_error(PartTemplate, tenant, id=template_id)
    parts_input = payload.get("parts_items")
    if parts_input:
        for p in parts_input:
            parts_items.append(
                PartItemSpec(
                    name=p.get("name", "").strip(),
                    code=(p.get("code") or "").strip().upper(),
                    default_cost=str(p.get("default_cost") or "0"),
                    default_safety_stock=int(p.get("default_safety_stock") or 0),
                    shared_across_models=bool(p.get("shared_across_models")),
                )
            )
    elif template:
        for it in template.items.all().order_by("sort_order", "id"):
            parts_items.append(
                PartItemSpec(
                    name=it.name,
                    code=it.code,
                    default_cost=str(it.default_cost),
                    default_safety_stock=it.default_safety_stock,
                    shared_across_models=it.shared_across_models,
                )
            )

    # ── 算 model 名稱
    model_name = _format_phone_model_name(brand, series, generation, model_suffix)
    if not model_name:
        raise ValueError("品牌 / 系列 / 世代 / 後綴 全部空白,無法產生機型名稱")

    main_results = []
    main_first_product: Optional[Product] = None
    model_key = ""

    # ── Phase 1:主機 SKU(狀態 × 容量 × 顏色)
    for cond in conditions:
        for cap in capacities:
            for col in colors:
                spec = " ".join([cap, col, cond.name])
                name = f"{model_name} {cap} {col} {cond.name}"
                if dry_run:
                    main_results.append(
                        {
                            "name": name,
                            "spec": spec,
                            "condition_id": cond.id,
                            "condition_name": cond.name,
                            "capacity": cap,
                            "color": col,
                            "is_secondhand": cond.is_secondhand,
                        }
                    )
                    continue
                p = Product(
                    tenant=tenant,
                    category=main_category,
                    name=name,
                    spec=spec,
                    brand=brand,
                    series=series,
                    generation=generation if generation else None,
                    model_suffix=model_suffix,
                    condition=cond,
                    is_secondhand=cond.is_secondhand,
                    requires_serial=True,
                    list_price=Decimal(str(list_price)),
                    accessory_type=Product.AccessoryType.NONE,
                    warehouse_type=Product.WarehouseType.PRODUCT,
                )
                p.save()
                main_results.append(
                    {
                        "id": p.id,
                        "sku": p.sku,
                        "name": p.name,
                        "spec": p.spec,
                        "is_secondhand": p.is_secondhand,
                    }
                )
                if main_first_product is None:
                    main_first_product = p

    # 主機 model_key:用第一支算
    if main_first_product is not None:
        model_key = compute_phone_model_key(main_first_product)

    # ── Phase 2:配件 placeholder SKU(每類別 1 個,綁此機型)
    accessory_results = []
    for acc_name in accessory_categories:
        full_name = f"{model_name} {acc_name}"
        if dry_run:
            accessory_results.append(
                {"name": full_name, "category_label": acc_name}
            )
            continue
        p = Product(
            tenant=tenant,
            category=accessory_category,
            name=full_name,
            spec=acc_name,
            requires_serial=False,
            accessory_type=Product.AccessoryType.PHONE_SPECIFIC,
            warehouse_type=Product.WarehouseType.PRODUCT,
            list_price=Decimal("0"),
        )
        p.save()
        if main_first_product and model_key:
            ProductRelation.objects.create(
                tenant=tenant,
                host_product=main_first_product,
                host_model_key=model_key,
                accessory_product=p,
            )
        accessory_results.append({"id": p.id, "sku": p.sku, "name": p.name})

    # ── Phase 3:維修零件 SKU
    parts_results = []
    for item in parts_items:
        full_name = f"{model_name} {item.name}"
        if dry_run:
            parts_results.append(
                {
                    "name": full_name,
                    "code": item.code,
                    "shared_across_models": item.shared_across_models,
                }
            )
            continue
        p = Product(
            tenant=tenant,
            category=parts_category,
            name=full_name,
            spec=item.code,
            requires_serial=False,
            accessory_type=Product.AccessoryType.NONE,
            warehouse_type=Product.WarehouseType.PARTS,
            list_price=Decimal("0"),
        )
        p.save()
        if main_first_product and model_key:
            ProductRelation.objects.create(
                tenant=tenant,
                host_product=main_first_product,
                host_model_key=model_key,
                accessory_product=p,
            )
        parts_results.append({"id": p.id, "sku": p.sku, "name": p.name})

    summary = {
        "model_name": model_name,
        "model_key": model_key,
        "main_count": len(main_results),
        "accessory_count": len(accessory_results),
        "parts_count": len(parts_results),
        "main": main_results,
        "accessories": accessory_results,
        "parts": parts_results,
    }
    return summary
