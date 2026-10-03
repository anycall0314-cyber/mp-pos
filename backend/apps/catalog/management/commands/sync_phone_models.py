"""只同步「機型主檔」,不建任何商品 SKU。

`import_taiwan_catalog` 是給「型錄從零開始」的新客戶用的:它會連
型號 × 容量 × 顏色的商品 SKU 一起建。但已經有自己商品的租戶
(例:從舊 POS 匯進來的店家)只缺 `PhoneModel` 這層機型身分——
灌整份型錄會憑空多出幾百個不存在的商品。

這支指令補那個缺口:讀同一份型錄 JSON,只確保 Brand / PhoneSeries /
PhoneModel 存在,一個 Product 都不動。

機型主檔是「配件 → 相容機型」比對的地基:沒有機型可對,比對只會一直
回「查不到」。

用法:
    # 預覽(不寫入)
    python manage.py sync_phone_models --tenant default --data apps/catalog/data/taiwan_catalog

    # 正式寫入
    python manage.py sync_phone_models --tenant default --data apps/catalog/data/taiwan_catalog --confirm

    # 另外補一份「只有機型身分、沒有價格顏色」的清單
    python manage.py sync_phone_models --tenant default \
        --data apps/catalog/data/taiwan_catalog \
        --extra apps/catalog/data/phone_models_extra.json --confirm

設計原則(對齊 import_taiwan_catalog):
- **可重複執行**:已存在的機型(以 match_key 認人)計為「略過」,不重複建。
- **全程 dry-run**,`--confirm` 才寫入。
- **品牌 / 系列語意沿用 import_taiwan_catalog**:直接複用它的 `_ensure_brands`
  / `_ensure_series`,避免兩套規則各走各的而長出同名不同 code 的品牌。
- 單筆失敗記錄但不中斷整批;最後若有失敗以非零 exit 結束。
"""
from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.catalog.models import PhoneModel
from apps.catalog.phone_model import _smart_join
from apps.catalog.services_model_bundle import (
    _format_phone_model_name,
    _get_or_create_phone_model,
)

from .import_taiwan_catalog import Command as CatalogCommand


class Command(BaseCommand):
    help = "從型錄 JSON 同步機型主檔(PhoneModel),不建立任何商品"

    def add_arguments(self, parser):
        parser.add_argument("--tenant", required=True, help="租戶 code 或 name(例:Default)")
        parser.add_argument("--data", required=True, help="型錄 JSON 檔或目錄")
        parser.add_argument("--extra", help="補充機型清單 JSON(只需 brand/series/generation/model_suffix)")
        parser.add_argument("--confirm", action="store_true",
                            help="正式寫入;不加則只預覽")

    def handle(self, *args, **opts):
        confirm = opts["confirm"]
        # 品牌 / 系列的建立語意直接借用型錄匯入指令,不另寫一套。
        helper = CatalogCommand()
        helper.stdout = self.stdout
        helper.style = self.style
        tenant = helper._resolve_tenant(opts["tenant"])

        payloads = self._load(opts["data"])
        if opts["extra"]:
            payloads += self._load(opts["extra"])

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"租戶:{tenant.code} {tenant.name} | "
            f"模式:{'正式寫入' if confirm else 'DRY-RUN 預覽'} | "
            f"讀到 {len(payloads)} 筆機型定義"
        ))

        # 品牌宣告散在各檔的 brands 區塊,_load 時已合併到 self._brands。
        brands, blocked = helper._ensure_brands(tenant, self._brands, confirm)

        created = skipped = 0
        errors = []
        series_cache = {}
        for idx, (m, src) in enumerate(payloads):
            label = f"{src}#{idx + 1} {m.get('brand')}/{m.get('series')}/{m.get('generation')}"
            try:
                bkey = m.get("brand")
                if bkey in blocked:
                    raise ValueError(f"品牌 {bkey} 有衝突未解決:{blocked[bkey]}")
                if bkey not in brands:
                    raise ValueError(f"品牌 {bkey!r} 未在清單的 brands 宣告")
                brand = brands.get(bkey)
                series = helper._ensure_series(
                    tenant, brand, m.get("series"), series_cache, confirm
                )
                name = self._model_name(series, m)
                if not name:
                    raise ValueError("品牌 / 系列 / 世代 / 後綴 全部空白,無法產生機型名稱")

                exists = PhoneModel.objects.for_tenant(tenant).filter(
                    match_key=name.strip().lower()
                ).exists()
                if exists:
                    skipped += 1
                    continue
                if confirm:
                    _get_or_create_phone_model(
                        tenant, name, brand, series,
                        m.get("generation"), m.get("model_suffix", ""),
                    )
                created += 1
                self.stdout.write(f"  + {name}")
            except Exception as e:                      # noqa: BLE001 — 單筆失敗不中斷整批
                errors.append(f"{label}:{e}")

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            f"新建機型 {created} 筆;已存在略過 {skipped} 筆;失敗 {len(errors)} 筆"
        ))
        for e in errors:
            self.stdout.write(self.style.ERROR(f"  ! {e}"))
        if not confirm:
            self.stdout.write(self.style.NOTICE("(DRY-RUN,未寫入。加 --confirm 才正式建立)"))
        if errors:
            raise CommandError(f"{len(errors)} 筆失敗")

    def _model_name(self, series, m):
        """算機型名稱。

        `_format_phone_model_name` 要有真的 PhoneSeries 物件才組得出字,但 dry-run
        時系列還沒建(`_ensure_series` 只在 --confirm 時建),名稱會全部算成空字串。
        所以系列已存在就照既有那筆的名字算(與正式寫入完全一致),還不存在就退回
        用清單宣告的系列字串預覽——組字規則共用同一個 `_smart_join`,不另寫一套。
        """
        if series is not None:
            return _format_phone_model_name(
                None, series, m.get("generation"), m.get("model_suffix", "")
            )
        parts = [(m.get("series") or "").strip()]
        if m.get("generation"):
            parts.append(str(m["generation"]))
        if m.get("model_suffix"):
            parts.append(m["model_suffix"])
        return _smart_join([p for p in parts if p]).strip()

    def _load(self, path_str):
        """讀一個 JSON 檔或一整個目錄,回傳 [(型號定義, 來源檔名)];
        同時把各檔的 brands 宣告合併到 self._brands。"""
        p = Path(path_str)
        if not p.exists():
            raise CommandError(f"找不到 {p}")
        files = sorted(p.glob("*.json")) if p.is_dir() else [p]
        if not files:
            raise CommandError(f"{p} 裡沒有 JSON 檔")
        out = []
        if not hasattr(self, "_brands"):
            self._brands = {}
        for f in files:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except json.JSONDecodeError as e:
                raise CommandError(f"{f.name} 不是合法 JSON:{e}") from e
            self._brands.update(data.get("brands") or {})
            for m in data.get("models") or []:
                if not isinstance(m, dict):
                    raise CommandError(f"{f.name} 的 models 裡有非物件元素")
                out.append((m, f.name))
        return out
