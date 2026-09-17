"""匯入台灣市售 3C 型錄(手機 / 平板 / 手錶),自動建立型號 SKU。

給「剛接觸、型錄從零開始」的新客戶用:餵一份台灣近幾年市售機型清單,
一次把品牌 / 系列 / 型號(狀態 × 容量 × 顏色)全部建好。

用法:
    # 預覽(不寫入,只報告會建幾個型號 / 幾個 SKU)
    python manage.py import_taiwan_catalog --tenant JB --data apps/catalog/data/taiwan_catalog

    # 正式寫入
    python manage.py import_taiwan_catalog --tenant JB --data apps/catalog/data/taiwan_catalog --confirm

設計原則:
- **可重複執行**:已存在的型號(service 以品名判定「已經建過了」)計為「略過」,
  不重複建、不算失敗。未來新機上市,加進 JSON 再跑一次即可。
- **類別用名稱對應,不寫死 code**:不同租戶的類別 code 可能不同
  (手錶在某租戶是 WA、另一租戶是 WH),但名稱都是「手機 / 平板 / 手錶」。
- **不動既有資料**:品牌同名不同 code(舊拼錯)衝突時,記錄並跳過該品牌的型號,
  不自動改既有 code(那要另外的品牌合併流程)。
- 全程 dry-run,--confirm 才寫;任一型號失敗記錄但不中斷整批;
  最後若有失敗以非零 exit 結束(補跑不受影響)。

JSON 格式:見 apps/catalog/data/taiwan_catalog/*.json。
"""
from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError

from apps.catalog.models import Brand, Category, Condition, PhoneModel, PhoneSeries, Product
from apps.catalog.services_model_bundle import (
    _format_phone_model_name,
    create_phone_model_bundle,
)
from apps.tenants.models import Tenant

# create_phone_model_bundle 對「這批型號的商品早就建過」會 raise 的訊息前綴
_ALREADY_EXISTS = "這些商品已經建過了"


class Command(BaseCommand):
    help = "匯入台灣市售 3C 型錄(手機 / 平板 / 手錶),自動建立型號 SKU"

    def add_arguments(self, parser):
        parser.add_argument("--tenant", required=True, help="租戶 code(例:JB)")
        parser.add_argument("--data", required=True, help="型錄 JSON 檔或目錄")
        parser.add_argument("--confirm", action="store_true",
                            help="正式寫入(否則只 dry-run 預覽)")
        parser.add_argument("--condition", default="brand-new",
                            help="要建的商品狀態 code(預設 brand-new 全新)")

    def handle(self, *args, **opts):
        tenant = self._resolve_tenant(opts["tenant"])
        data = self._load(opts["data"])
        confirm = opts["confirm"]

        cond = Condition.objects.for_tenant(tenant).filter(code=opts["condition"]).first()
        if cond is None:
            raise CommandError(
                f"租戶 {tenant.code} 沒有狀態 code={opts['condition']};"
                f"現有:{[c.code for c in Condition.objects.for_tenant(tenant)]}"
            )
        cat_by_name = {c.name: c for c in Category.objects.for_tenant(tenant)}

        self.stdout.write(self.style.NOTICE(
            f"租戶:{tenant.code} {tenant.name} | "
            f"模式:{'正式寫入' if confirm else 'DRY-RUN 預覽'} | 狀態:{cond.name}"
        ))

        # ── 1. 品牌:確保存在。同名不同 code(舊拼錯)衝突 → 記錄,不動既有。
        brands, blocked_brands = self._ensure_brands(
            tenant, data.get("brands") or {}, confirm
        )

        # ── 2. 逐型號
        new_models = new_skus = skipped = 0
        errors = []
        series_cache = {}

        for idx, m in enumerate(data.get("models") or []):
            try:
                if not isinstance(m, dict):
                    raise ValueError(f"第 {idx + 1} 筆不是物件(型號應為 JSON 物件)")
                label = self._label(m)

                bkey = m.get("brand")
                if bkey in blocked_brands:
                    raise ValueError(f"品牌 {bkey} 有衝突未解決:{blocked_brands[bkey]}")
                # 品牌一定要在清單的 brands 宣告過。未宣告(拼錯 key)要報錯,
                # 不能跟「已宣告、預計新建(dry-run 時值為 None)」混為一談。
                if bkey not in brands:
                    raise ValueError(f"品牌 {bkey!r} 未在清單的 brands 宣告")
                brand = brands.get(bkey)

                cat = cat_by_name.get(m.get("kind"))
                if cat is None:
                    raise ValueError(
                        f"找不到類別「{m.get('kind')}」;租戶現有:{list(cat_by_name)}"
                    )

                # 容量 / 顏色一定要是陣列。傳字串會被逐字拆成一堆 SKU;
                # [null] 會寫成 "None"。都要擋掉,不能靜默字串化。
                for field in ("capacities", "colors"):
                    v = m.get(field)
                    if not isinstance(v, list):
                        raise ValueError(f"{field} 必須是陣列,不能是 {type(v).__name__}")
                    for x in v:
                        if not isinstance(x, str) or not x.strip():
                            raise ValueError(f"{field} 有非文字或空白元素:{x!r}")
                caps = [c.strip() for c in m["capacities"]]
                cols = [c.strip() for c in m["colors"]]
                if not caps or not cols:
                    raise ValueError("capacities / colors 不可為空陣列")

                series = self._ensure_series(tenant, brand, m.get("series"),
                                             series_cache, confirm)

                payload = {
                    "brand_id": brand.id if brand else None,
                    "series_id": series.id if series else None,
                    "generation": m.get("generation"),
                    "model_suffix": m.get("model_suffix", ""),
                    "main_category_id": cat.id,
                    "list_price": str(m.get("list_price") or "0"),
                    "condition_ids": [cond.id],
                    "capacities": caps,
                    "colors": cols,
                    "region_version": m.get("region_version", ""),
                }

                # 算出「本次這個型號會建的完整品名集合」,查 DB 有幾個已存在。
                # 用品名集合(而非只比數量):黑+紅 改成 黑+白 時,數量都是 2 但
                # 白色其實沒建,只比數量會誤判略過。用集合才精確。
                planned = self._planned_names(brand, series, m, caps, cols, cond)
                exist = set(
                    Product.objects.for_tenant(tenant)
                    .filter(name__in=list(planned)).values_list("name", flat=True)
                )
                expected, existing = len(planned), len(exist)

                if existing == expected:
                    skipped += 1
                    self.stdout.write(f"  [略過] {label}(已存在 {existing})")
                    continue
                if existing > 0:
                    raise ValueError(
                        f"部分已存在({existing}/{expected}),可能改了容量/顏色/版本;"
                        "請確認後手動處理,不自動補建"
                    )

                if not confirm:
                    new_models += 1
                    new_skus += expected
                    self.stdout.write(f"  [型號] {label} → {expected} 個 SKU")
                    continue

                res = create_phone_model_bundle(tenant, payload)
                new_models += 1
                new_skus += res["main_count"]
                self.stdout.write(f"  [型號] {res['model_name']} → 建 {res['main_count']} 個 SKU")

            except Exception as e:  # noqa: BLE001
                lbl = self._label(m) if isinstance(m, dict) else f"第 {idx + 1} 筆"
                errors.append(f"{lbl}: {e}")
                self.stdout.write(self.style.WARNING(f"  [失敗] {lbl}: {e}"))

        # ── 3. 報告
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            f"{'預計新增' if not confirm else '新增'}型號:{new_models} | "
            f"SKU:{new_skus} | 略過(已存在):{skipped} | 失敗:{len(errors)}"
        ))
        for b, why in blocked_brands.items():
            self.stdout.write(self.style.WARNING(f"  [品牌未解決] {b}: {why}"))
        if errors:
            self.stdout.write(self.style.WARNING("失敗清單:"))
            for e in errors[:40]:
                self.stdout.write(f"  - {e}")
        if not confirm:
            self.stdout.write(self.style.NOTICE("(DRY-RUN,未寫入。加 --confirm 才正式建立)"))

        # 有任何失敗 / 品牌衝突 → 非零 exit(不回滾已成功的,補跑即可)
        if errors or blocked_brands:
            raise CommandError(
                f"有 {len(errors)} 個型號失敗、{len(blocked_brands)} 個品牌衝突未解決"
            )

    # ── helpers ───────────────────────────────────────────────
    def _ensure_brands(self, tenant, brand_map, confirm):
        """回 (可用品牌 dict, 衝突品牌 dict{code:原因})。

        Brand 有 (tenant,code) 與 (tenant,name) 兩個唯一鍵。清單提供的 code
        找不到、但同 name 已被別的 code 佔用(舊拼錯)時,不自動改既有 code
        —— 記成衝突,該品牌的型號全部跳過,交由人另外合併。
        """
        brands, blocked = {}, {}
        for code, name in brand_map.items():
            b = Brand.objects.for_tenant(tenant).filter(code=code).first()
            if b is not None:
                brands[code] = b
                continue
            clash = Brand.objects.for_tenant(tenant).filter(name=name).first()
            if clash is not None:
                blocked[code] = f"已有同名品牌 code={clash.code!r},請先合併再匯入"
                continue
            if confirm:
                try:
                    b = Brand.objects.create(tenant=tenant, code=code, name=name)
                except IntegrityError as e:
                    blocked[code] = f"建立失敗:{e}"
                    continue
                brands[code] = b
            else:
                brands[code] = None
                self.stdout.write(f"  [品牌] 會新增 {code} / {name}")
        return brands, blocked

    def _ensure_series(self, tenant, brand, sname, cache, confirm):
        """取得 / 建立系列。兩側都正規化(去空白 + 忽略大小寫)後比對;
        同品牌多筆同名時報錯。"""
        sname = (sname or "").strip()
        if not sname or brand is None:
            return None
        norm = sname.casefold()
        ckey = (brand.id, norm)
        if ckey in cache:
            return cache[ckey]
        # iexact 不去除 DB 欄位的首尾空白,既有「 iPhone 」不會被視為相同。
        # 拉出同品牌全部系列,在 Python 端兩側 strip+casefold 比對。
        matches = [
            s for s in PhoneSeries.objects.for_tenant(tenant).filter(brand=brand)
            if (s.name or "").strip().casefold() == norm
        ]
        if len(matches) > 1:
            raise ValueError(
                f"品牌 {brand.code} 底下有多筆同名系列「{sname}」,請先整理:"
                f"{[s.code for s in matches]}"
            )
        series = matches[0] if matches else None
        if series is None and confirm:
            series = self._create_series(tenant, brand, sname)
        cache[ckey] = series
        return series

    def _planned_names(self, brand, series, m, caps, cols, cond):
        """算出這個型號本次會建的「完整品名集合」,跟 service 的命名一致。

        品名 = 機型名 + 容量 + 顏色 +(地區版本)+ 狀態名。用集合去查 DB 已存在
        哪些,才能精確分辨「全建過(略過)/ 部分建過(報錯)/ 全新(建)」——
        只比數量會被「黑+紅 改 黑+白」這種等量換色騙過。
        """
        model_name = _format_phone_model_name(
            brand, series, m.get("generation"), m.get("model_suffix", "")
        )
        region = (m.get("region_version") or "").strip()
        names = set()
        for cap in caps:
            for col in cols:
                bits = [cap, col]
                if region:
                    bits.append(region)
                bits.append(cond.name)
                names.add(f"{model_name} {' '.join(bits)}")
        return names

    def _create_series(self, tenant, brand, sname):
        """建系列。PhoneSeries.code 上限截短 + 撞碼加序號。"""
        from django.utils.text import slugify
        maxlen = PhoneSeries._meta.get_field("code").max_length or 20
        base = (slugify(f"{brand.code}-{sname}") or "series")[:maxlen]
        code, n = base, 1
        while PhoneSeries.objects.for_tenant(tenant).filter(code=code).exists():
            n += 1
            suffix = f"-{n}"
            code = base[: maxlen - len(suffix)] + suffix
        return PhoneSeries.objects.create(tenant=tenant, brand=brand, name=sname, code=code)

    def _label(self, m):
        return " ".join(str(m.get(k, "")).strip()
                        for k in ("brand", "series", "generation", "model_suffix")
                        if str(m.get(k, "")).strip())

    def _resolve_tenant(self, code):
        t = Tenant.objects.filter(code=code).first()
        if t is None:
            avail = [f"{x.code}({x.name})" for x in Tenant.objects.all()]
            raise CommandError(f"找不到租戶 code={code};現有:{avail}")
        return t

    def _load(self, path):
        p = Path(path)
        if not p.exists():
            raise CommandError(f"找不到型錄檔 / 目錄:{path}")
        files = sorted(p.glob("*.json")) if p.is_dir() else [p]
        if not files:
            raise CommandError(f"目錄 {path} 底下沒有任何 .json")
        brands, models = {}, []
        for f in files:
            with open(f, encoding="utf-8") as fh:
                d = json.load(fh)
            if not isinstance(d, dict):
                raise CommandError(f"{f.name} 頂層不是物件")
            brands.update(d.get("brands") or {})
            ms = d.get("models") or []
            if not isinstance(ms, list):
                raise CommandError(f"{f.name} 的 models 不是陣列")
            models.extend(ms)
        return {"brands": brands, "models": models}
