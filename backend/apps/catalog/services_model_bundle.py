"""新增手機型號 bundle service。

把「狀態 × 容量 × 顏色」cartesian 展開成主機 SKU,並依範本同時建好
配件 placeholder 與維修零件 SKU,全部用 ProductRelation 綁定到該機型。

用途:wizard「+ 新增 iPhone 17 Pro」按下「建立全部」時呼叫此 service,
之後遇到全新 / 已拆封 / 中古機收購 都不用再多一道「先建商品」手續,
直接掛序號即可。

呼叫者:
- POST /api/v1/products/create-phone-model/  (dry_run=true 預覽,false 真建)
"""
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Optional

from django.db import IntegrityError, transaction
from django.utils.text import slugify

from .models import (
    Brand,
    Category,
    Condition,
    PartTemplate,
    PhoneModel,
    PhoneSeries,
    Product,
    ProductRelation,
)
from .phone_model import compute_phone_model_key, compute_phone_model_name
from apps.core.money import round_money


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


def _check_len(field: str, value: str, label: str):
    """擋掉超過 Product 欄位長度的值。

    不先擋的話會在 `save()` 才丟 DataError(HTTP 500);endpoint 只接
    ValueError,擋在這裡使用者看到的是 400 加上「哪一欄太長」。
    上限直接讀 model 欄位定義,避免另外維護一份常數而不同步。
    """
    limit = Product._meta.get_field(field).max_length
    if limit is not None and len(value) > limit:
        raise ValueError(f"{label}「{value}」超過 {limit} 字上限")
    return value


def _price_ceiling() -> Decimal:
    """建議售價那一欄放得下的最大整數(照欄位的定義算,不另外寫死一個數字)。"""
    field = Product._meta.get_field("list_price")
    return Decimal(10) ** (field.max_digits - field.decimal_places) - 1


def _price(value, label: str) -> Decimal:
    """建議售價:要是 0 以上、欄位放得下的數字,收成整數元(金額一律整數)。沒填的由呼叫的人決定當成什麼,不會進來這裡。

    預覽與建立都過這裡:預覽放行的,存檔時不能才因為數字太大而失敗。
    """
    try:
        price = Decimal(str(value).strip())
    except InvalidOperation:
        raise ValueError(f"{label}要是數字") from None
    if not price.is_finite():
        raise ValueError(f"{label}要是數字")
    if price < 0:
        raise ValueError(f"{label}不能是負的")
    ceiling = _price_ceiling()
    # 先擋再收整數:位數多到離譜的(1e28)連四捨五入都做不了
    if price > ceiling + 1:
        raise ValueError(f"{label}太大了")
    price = round_money(price)
    if price > ceiling:
        raise ValueError(f"{label}太大了")
    return price


def _blank(value) -> bool:
    """沒填:沒給,或只有空白。(`0` 是有填。)"""
    return value is None or str(value).strip() == ""


def _prices_by_capacity(payload, capacities) -> dict:
    """每一個容量的建議售價 {容量: 整數元}。

    `list_prices` = {容量: 價錢}:手機同一款不同容量價錢不一樣(owner 2026-10-08:以前整批只有一個價錢,建完要一個一個改)。
    那個容量沒給、或給空的,用整批的 `list_price`(沒給就是 0)—— 舊的呼叫端(型錄匯入)只給 `list_price`,照舊。
    指到沒有要建的容量是寫錯了(`256G` 寫成 `256GB` 的話,那個容量會悄悄變成 0 元),直接講。
    同一個容量不分品況都是這個價錢:已拆封、中古機本來就每一台另外定價,這個數字只是沒定價時的預設。
    """
    # 整批那一個:空的、只有空白、沒給(以及以前就當成 0 的 False / [] / {})都是 0
    single = payload.get("list_price")
    base = _price("0" if not single or _blank(single) else single, "建議售價")
    given = payload.get("list_prices")
    if given is None:
        given = {}
    if not isinstance(given, dict):
        raise ValueError("list_prices 要是 {容量: 價錢}")
    by_capacity = {}
    for raw, value in given.items():
        cap = str(raw).strip()
        if not cap:
            # 空白的容量不會被建(容量那一串也是先去空白、丟掉空的),它的價錢跟著丟掉,不算寫錯
            continue
        if cap in by_capacity:
            # `"256GB"` 與 `" 256GB "` 去掉空白是同一個:哪一個算數要看順序,不猜
            raise ValueError(f"{cap} 的建議售價給了兩次")
        by_capacity[cap] = value
    unknown = [k for k in by_capacity if k not in capacities]
    if unknown:
        raise ValueError("建議售價指到沒有要建的容量:" + "、".join(unknown[:5]))
    prices = {}
    for cap in capacities:
        value = by_capacity.get(cap)
        prices[cap] = base if _blank(value) else _price(value, f"{cap} 的建議售價")
    return prices


def _get_or_create_phone_model(tenant, model_name, brand, series, generation, model_suffix):
    """取得(或建立)這個機型在主檔裡的那一筆。

    以 match_key(lowercase 機型名稱)認人:同一款手機不管跑幾次精靈、
    補了幾個顏色容量,都掛到同一筆機型上。
    """
    match_key = model_name.strip().lower()
    if not match_key:
        return None
    pm = PhoneModel.objects.for_tenant(tenant).filter(match_key=match_key).first()
    if pm is not None:
        return pm

    base = slugify(model_name)[:40] or "model"   # 純中文機型名 slugify 後是空的
    code, n = base, 1
    # 兩個人同時建同一個機型(或兩個不同機型的 slug 都退回 "model")時,
    # 查完到寫入之間會被對方插隊。包 savepoint 重試:撞 match_key 就沿用
    # 對方剛建的那筆;只是 code 撞到就換下一個號再試。
    for _ in range(20):
        while PhoneModel.objects.for_tenant(tenant).filter(code=code).exists():
            n += 1
            suffix = f"-{n}"
            code = base[: 40 - len(suffix)] + suffix
        try:
            with transaction.atomic():
                return PhoneModel.objects.create(
                    tenant=tenant,
                    code=code,
                    name=model_name,
                    match_key=match_key,
                    brand=brand,
                    series=series,
                    generation=generation if generation else None,
                    model_suffix=model_suffix or "",
                    is_active=True,
                )
        except IntegrityError as e:
            if "uniq_phone_model_tenant_match_key" in str(e):
                pm = PhoneModel.objects.for_tenant(tenant).filter(
                    match_key=match_key
                ).first()
                if pm is not None:
                    return pm
                raise
            if "uniq_phone_model_tenant_code" not in str(e):
                raise
            n += 1
            suffix = f"-{n}"
            code = base[: 40 - len(suffix)] + suffix
    raise ValueError(f"機型代碼產生失敗(試了 20 次都撞號):{model_name}")


def _assert_reusable_part(existing, parts_category, part_spec):
    """同名的既有商品要真的是同一顆零件才能重用。

    只比品名太寬:可能撞到商品倉的手機、需要序號的商品、或別的類別 / 規格的
    東西,直接重用會把不相干的商品掛成這個機型的維修零件。不符就明確報錯,
    讓使用者自己改名或去挑既有商品。
    """
    problems = []
    if existing.warehouse_type != Product.WarehouseType.PARTS:
        problems.append("不是零件倉商品")
    if existing.category_id != parts_category.id:
        problems.append(f"類別是「{existing.category.name}」")
    if existing.requires_serial:
        problems.append("需要追蹤序號")
    if existing.is_virtual:
        problems.append("是虛擬商品")
    if part_spec and existing.spec and existing.spec != part_spec:
        problems.append(f"規格是「{existing.spec}」,不是「{part_spec}」")
    if problems:
        raise ValueError(
            f"已有同名商品「{existing.name}」({existing.sku}),但"
            + "、".join(problems)
            + ",不能當成這個機型的零件重用"
        )


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


def create_phone_model_bundle(tenant, payload, user=None):
    """真的建立 — 寫入 DB,回傳建好的 SKU 摘要。"""
    return _build_bundle(tenant, payload, dry_run=False, user=user)


@transaction.atomic
def _build_bundle(tenant, payload, *, dry_run, user=None):
    """核心邏輯。dry_run=True 時 atomic 外殼仍會用,確保 raise 都會回滾;
    但只要不 raise、不 save,就不會有任何寫入。
    """
    from apps.identity.dedup import BatchGuard, MainUnit

    # 防重複:預覽時把可能重複的列出來;正式建立時每一筆各自帶理由
    # (distinct_reasons = {品名: 哪裡不同})才放行
    guard = BatchGuard(
        tenant, payload.get("distinct_reasons"), dry_run=dry_run, user=user
    )
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
    model_suffix = _check_len(
        "model_suffix", str(payload.get("model_suffix") or "").strip(), "型號後綴"
    )

    main_category_id = payload.get("main_category_id")
    if not main_category_id:
        raise ValueError("main_category_id 必填(主機類別)")
    main_category = _resolve_or_error(Category, tenant, id=main_category_id)

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

    capacities = [
        _check_len("capacity", str(c).strip(), "容量")
        for c in (payload.get("capacities") or [])
        if str(c).strip()
    ]
    colors = [
        _check_len("color", str(c).strip(), "顏色")
        for c in (payload.get("colors") or [])
        if str(c).strip()
    ]
    if not capacities:
        raise ValueError("至少要選 1 個容量")
    if not colors:
        raise ValueError("至少要選 1 個顏色")
    price_of = _prices_by_capacity(payload, capacities)

    # 地區版本:整批一個值(台版 / 港版 …),不當成第 4 個維度爆 SKU 數。
    # 要建不同版本就再跑一次精靈。有值時會併進品名,避免撞 uniq_product_tenant_name。
    region_version = _check_len(
        "region_version", str(payload.get("region_version") or "").strip(), "地區版本"
    )

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
    # 機型主檔:dry_run 不建,正式建立時取得(或沿用既有那一筆)
    phone_model = (
        None if dry_run
        else _get_or_create_phone_model(
            tenant, model_name, brand, series, generation, model_suffix
        )
    )

    # 先算出所有要建的主機品名,擋掉會撞 uniq_product_tenant_name 的情況。
    # 不先擋的話會在 save() 丟 IntegrityError,endpoint 只接 ValueError,
    # 使用者看到的是 500 而不是「這個組合已經建過了」。
    planned_names = []
    for cond in conditions:
        for cap in capacities:
            for col in colors:
                bits = [cap, col]
                if region_version:
                    bits.append(region_version)
                bits.append(cond.name)
                planned_names.append(
                    _check_len("name", f"{model_name} {' '.join(bits)}", "品名")
                )
    dupes_in_batch = sorted(
        {n for n, c in Counter(planned_names).items() if c > 1}
    )
    if dupes_in_batch:
        raise ValueError(
            "這批內品名重複:" + "、".join(dupes_in_batch[:5])
            + (f" 等 {len(dupes_in_batch)} 筆" if len(dupes_in_batch) > 5 else "")
        )
    clashed = list(
        Product.objects.for_tenant(tenant)
        .filter(name__in=planned_names)
        .values_list("name", flat=True)[:5]
    )
    if clashed:
        raise ValueError("這些商品已經建過了:" + "、".join(clashed))

    # ── Phase 1:主機 SKU(狀態 × 容量 × 顏色)
    for cond in conditions:
        for cap in capacities:
            for col in colors:
                # 容量 / 顏色 / 版本同時寫進結構化欄位與顯示字串。
                # 結構化欄位是識別引擎「容量對不上就標衝突」那道防呆的依據,
                # 留空等於把防呆關掉,所以這裡一定要帶。
                bits = [cap, col]
                if region_version:
                    bits.append(region_version)
                bits.append(cond.name)
                spec = _check_len("spec", " ".join(bits), "規格")
                name = _check_len("name", f"{model_name} {' '.join(bits)}", "品名")
                # 主機只跟「可能是同一台主機」的比(配件、另一個品況不算;見 MainUnit)
                unit = MainUnit(cond.id, cap)
                if not guard.allow(name, unit=unit, is_secondhand=cond.is_secondhand):
                    continue
                if dry_run:
                    main_results.append(
                        {
                            "name": name,
                            "spec": spec,
                            "condition_id": cond.id,
                            "condition_name": cond.name,
                            "capacity": cap,
                            "color": col,
                            "region_version": region_version,
                            "is_secondhand": cond.is_secondhand,
                            "list_price": str(price_of[cap]),
                        }
                    )
                    continue
                p = Product(
                    tenant=tenant,
                    category=main_category,
                    name=name,
                    spec=spec,
                    capacity=cap,
                    color=col,
                    region_version=region_version,
                    phone_model=phone_model,
                    brand=brand,
                    series=series,
                    generation=generation if generation else None,
                    model_suffix=model_suffix,
                    condition=cond,
                    is_secondhand=cond.is_secondhand,
                    requires_serial=True,
                    list_price=price_of[cap],
                    accessory_type=Product.AccessoryType.NONE,
                    warehouse_type=Product.WarehouseType.PRODUCT,
                )
                p.save()
                guard.created(p)
                main_results.append(
                    {
                        "id": p.id,
                        "sku": p.sku,
                        "name": p.name,
                        "spec": p.spec,
                        "capacity": p.capacity,
                        "color": p.color,
                        "region_version": p.region_version,
                        "condition_id": p.condition_id,
                        "condition_name": cond.name,
                        "is_secondhand": p.is_secondhand,
                        "list_price": str(price_of[cap]),
                    }
                )
                if main_first_product is None:
                    main_first_product = p

    # 主機 model_key:有主檔就用主檔的(穩定),沒有才用第一支算
    if phone_model is not None:
        model_key = phone_model.match_key
    elif main_first_product is not None:
        model_key = compute_phone_model_key(main_first_product)

    # ── Phase 2:配件「相容類別槽位」記錄(不建 SKU)
    # 設計文件第 5 節:配件是獨立商品樹(品牌 × 功能 × 顏色),
    # 透過相容對應表掛到型號。建手機時觸發的是「相容類別槽位」,
    # 不是直接生出配件 SKU。實際配件 SKU 走「+ 新增配件」獨立 wizard。
    accessory_slots = list(accessory_categories or [])

    # ── Phase 3:維修零件 SKU
    #
    # 零件名稱不帶地區版本 —— iPhone 15 Pro 的電池就是同一顆,不會因為主機
    # 賣台版還是港版而變成兩種料。所以同型號再跑一次精靈(換版本 / 補顏色)
    # 時要「找回既有零件」而不是重建,否則會撞 uniq_product_tenant_name
    # 讓整批(含主機)一起回滾。
    parts_results = []
    seen_part_names = set()
    for item in parts_items:
        # 名稱與規格的驗證都放在 dry_run 分支之前,預覽與正式建立用同一份結果,
        # 不會發生「預覽過了、按下建立才炸」。
        full_name = _check_len("name", f"{model_name} {item.name}", "零件品名")
        part_spec = _check_len("spec", item.code, "零件規格")
        if full_name in seen_part_names:
            raise ValueError(f"零件品名重複:{full_name}")
        # 零件名稱不能跟這批要建的主機撞名,否則會把剛建好的主機當零件重用,
        # 觸發 product_relation_not_self 讓整批回滾成 500。
        if full_name in set(planned_names):
            raise ValueError(f"零件品名與主機品名相同:{full_name}")
        seen_part_names.add(full_name)
        existing = Product.objects.for_tenant(tenant).filter(name=full_name).first()
        if existing is not None:
            _assert_reusable_part(existing, parts_category, part_spec)
        # 新零件在預覽時就過防重複關卡(同名可重用的不算新零件,照舊沿用)。
        # 只在正式建立才檢查的話,預覽沒有地方填理由,按下建立才被擋。
        if existing is None and not guard.allow(full_name):
            continue
        if dry_run:
            parts_results.append(
                {
                    "name": full_name,
                    "code": item.code,
                    "shared_across_models": item.shared_across_models,
                    "reused": existing is not None,
                }
            )
            continue
        p = existing
        reused = p is not None
        if p is None:
            p = Product(
                tenant=tenant,
                category=parts_category,
                name=full_name,
                spec=part_spec,
                requires_serial=False,
                accessory_type=Product.AccessoryType.NONE,
                warehouse_type=Product.WarehouseType.PARTS,
                list_price=Decimal("0"),
            )
            p.save()
            guard.created(p)
        if model_key and (phone_model or main_first_product):
            ProductRelation.objects.get_or_create(
                tenant=tenant,
                host_model_key=model_key,
                accessory_product=p,
                defaults={
                    "host_model": phone_model,
                    "host_product": main_first_product,
                },
            )
        parts_results.append(
            {"id": p.id, "sku": p.sku, "name": p.name, "reused": reused}
        )

    guard.finish()
    summary = {
        "model_name": model_name,
        "model_key": model_key,
        # 預覽時:可能跟既有商品重複的清單(正式建立要帶 distinct_reason)
        "possible_duplicates": guard.found,
        "main_count": len(main_results),
        "parts_count": len(parts_results),
        "accessory_slots": accessory_slots,
        "main": main_results,
        "parts": parts_results,
    }
    return summary
