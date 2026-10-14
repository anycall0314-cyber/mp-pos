"""舊系統「IMEI 明細表」= 12/1 盤點入庫時的參考清單(2026-10-14)。

手機、中古機在新系統裡一台都沒有,盤點時刷到的碼系統都不認得。這份清單讓刷到的那一台帶出舊系統的舊品號、舊品名、
成本(存量金額表)與售價(商品價格查詢表),管理員核准時照著指定入哪個品號(`inventory/stockcount.py::approve`)。

- **只是參考,不是庫存**:清單上有、沒刷到的不會入庫;刷到的也要管理員核准才入。
- 舊資料很髒:同一台登記好幾筆(收回來再賣,IMEI 尾巴加 A / I 繞過不能重複)、14 / 16 碼的、很久以前的還掛著。
  原文照存;比對鍵 `unit_key` 把「14~16 碼數字前後多一個字母」去掉那個字母。同一個鍵好幾筆 → 用進貨日期最新的那一筆。
- 店員會習慣刷舊貼紙(紅隊第 1 條):中古機舊系統一台一個品號(IMEI + I),貼紙對得到那一台 → 當成刷了它的 IMEI;
  新機的舊品號是型號用的(好幾台共用)→ 請他改刷 IMEI。
- 重匯 = 整份換掉(清單反映最新的那一份匯出);盤點單上刷過的那幾台照抄當時的內容,不受影響。
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date

from django.db import transaction
from django.utils import timezone

from apps.identity.normalize import normalize_serial

from .archive import SOURCE_SYSTEM
from .models import LegacyUnit
from .products import ReportError

_IMEI_BODY = re.compile(r"[A-Z]?(\d{14,16})[A-Z]?")


def unit_key(code) -> str:
    """比對鍵:去符號、大寫;前後多一個字母的 IMEI(`354679848372002I`)去掉那個字母。序號(英數混合)照原樣。"""
    key = normalize_serial(str(code or "").strip().lstrip("'"))
    m = _IMEI_BODY.fullmatch(key)
    return m[1] if m else key


def _day(text) -> date | None:
    text = re.sub(r"\D", "", str(text or ""))
    try:
        return date(int(text[:4]), int(text[4:6]), int(text[6:8])) if len(text) == 8 else None
    except ValueError:
        return None


@dataclass
class Loaded:
    rows: int = 0              # 報表上「庫存中」的列
    units: int = 0             # 寫進清單的台數
    no_code: int = 0           # 沒有 IMEI 的列(不收)
    duplicate_keys: int = 0    # 同一個比對鍵登記了不只一筆的(舊資料重複登記)
    with_cost: int = 0
    with_price: int = 0
    by_prefix: dict = field(default_factory=dict)   # 舊品名第一段 → 幾台


def load_units(tenant, rows: list[dict[str, str]], costs: dict | None = None, prices: dict | None = None,
               *, write=False) -> Loaded:
    """IMEI 明細表的列 → 這家公司的舊系統機器清單(整份換掉)。`costs` / `prices` = 舊品號 → 成本 / 零售價。
    `write=False` 是試算(不寫)。"""
    from .products import prefix_of

    if rows and "IMEI" not in rows[0]:
        raise ReportError("這份報表沒有「IMEI」")
    costs, prices = costs or {}, prices or {}
    out, now, made, seen = Loaded(), timezone.now(), [], {}
    for r in rows:
        if r.get("目前狀態", "庫存中").strip() not in ("庫存中", ""):
            continue
        out.rows += 1
        code = (r.get("IMEI") or "").strip().lstrip("'").strip()
        if not code:
            out.no_code += 1
            continue
        if code in seen:                 # 同一份報表同一個原文出現兩次:只收一次
            continue
        key = unit_key(code)
        old = (r.get("品號") or "").strip()
        name = (r.get("品名") or "").strip()
        seen[code] = key
        made.append(LegacyUnit(
            tenant=tenant, source_system=SOURCE_SYSTEM, code_raw=code[:80], code_key=key[:80],
            sn_raw=(r.get("S/N") or "").strip().lstrip("'").strip()[:80],
            product_code_raw=old[:60], product_code_key=normalize_serial(old)[:80], product_name_raw=name[:500],
            store_raw=(r.get("店別") or "").strip()[:60], purchased_on=_day(r.get("進貨日期")),
            supplier_raw=(r.get("進貨廠商") or "").strip()[:60],
            cost=costs.get(old), price=prices.get(old), imported_at=now,
        ))
        prefix = prefix_of(name)
        out.by_prefix[prefix] = out.by_prefix.get(prefix, 0) + 1
    out.units = len(made)
    out.duplicate_keys = sum(1 for n in Counter(u.code_key for u in made).values() if n > 1)
    out.with_cost = sum(1 for u in made if u.cost is not None)
    out.with_price = sum(1 for u in made if u.price is not None)
    if write:
        with transaction.atomic():
            LegacyUnit.objects.filter(tenant=tenant, source_system=SOURCE_SYSTEM).delete()
            LegacyUnit.objects.bulk_create(made, batch_size=1000)
    return out


def prices_from(items) -> dict:
    """商品價格查詢表讀出來的品項(`products.stock_items`)→ 舊品號 → 零售價(有填的)。"""
    return {i.code: i.price for i in items if i.price is not None}


@dataclass
class Hit:
    unit: LegacyUnit
    code: str              # 這一台要用來入庫的碼(刷舊貼紙時換成那一台的 IMEI)


class ModelSticker(Exception):
    """刷到的是型號用的舊貼紙(好幾台共用一個舊品號)。"""


def lookup(tenant, code) -> Hit | None:
    """刷到的碼在舊系統的機器清單裡是哪一台。型號貼紙丟 `ModelSticker`;都不是回 None。"""
    key = unit_key(code)
    if not key:
        return None
    units = LegacyUnit.objects.filter(tenant=tenant, source_system=SOURCE_SYSTEM)
    same = units.filter(code_key=key).order_by("-purchased_on", "-id").first()
    if same is not None:
        # IMEI 前後多一個字母的(舊貼紙 `…I`)用純數字那一串入庫;序號照刷到的原樣
        return Hit(same, key if key.isdigit() else str(code).strip())
    by_code = list(units.filter(product_code_key=normalize_serial(str(code).strip()))[:2])
    if len(by_code) == 1 and by_code[0].code_key and by_code[0].code_key in by_code[0].product_code_key:
        unit = by_code[0]                 # 中古機的舊貼紙:舊品號就是那一台的 IMEI + I
        return Hit(unit, unit.code_key)
    if by_code:
        raise ModelSticker(by_code[0].product_name_raw)
    return None


def group_of(name: str) -> str:
    """核准時分組用(紅隊第 2 條:同一組一次指定型號):舊品名的前三段,例 `中古/IP13P/256G`、`手機/三星-A17 6/128逆襲黑`。"""
    return "/".join(part.strip() for part in (name or "").split("/")[:3])


_BATTERY = re.compile(r"(?<!\d)(\d{2,3})\s*%")


def battery_of(name: str) -> int | None:
    """舊品名裡寫的電池健康度(`中古/IP16/128G/80%/黑/R` → 80);沒寫或不合理就是 None。"""
    m = _BATTERY.search(name or "")
    return int(m[1]) if m and 1 <= int(m[1]) <= 100 else None


def costs_from(rows) -> dict:
    """存量金額表(`products.read_ored_rows`)→ 舊品號 → 一件的成本。"""
    from .products import old_costs

    return old_costs(rows)


def not_in_yet(tenant) -> list[LegacyUnit]:
    """舊系統清單上有、新系統還沒有的那幾台(紅隊第 3 條:沒刷到的要讓老闆看見,不能只看刷到的)。
    同一台登記好幾筆的只算一次(進貨日期最新的那一筆);碼已經在新系統裡(不管在哪、什麼狀態,作廢的不算)的不列。"""
    from apps.inventory.identifiers import taken

    latest: dict[str, LegacyUnit] = {}
    for u in LegacyUnit.objects.filter(tenant=tenant, source_system=SOURCE_SYSTEM).order_by("purchased_on", "id"):
        if u.code_key:
            latest[u.code_key] = u          # 照日期由舊到新,後面的蓋掉前面的
    inside = set(taken(tenant, list(latest)))
    return sorted((u for k, u in latest.items() if k not in inside),
                  key=lambda u: (u.store_raw, u.product_name_raw, u.id))
