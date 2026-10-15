"""平台型號庫(M1):匯入與收回。表在 `models.py` 的 `DeviceModel` / `DeviceCatalogRun` / `DeviceCatalogChange`。

- 資料檔 `data/device_catalog.json`(產生方式 `docs/development/M1_標準機型清單/build_catalog.py`):`{"version", "models": [...]}`。
- **匯入可以重跑**:照 `uid` 對;內容(雜湊)一樣的不動、不記;不一樣的改掉並記改之前的內容;檔案裡沒有的不刪、不停用(之後的自動更新也只加不刪)。
- 同一個類別 + 品牌 + 型號名稱只能有一支:檔案裡自己重複、或跟庫裡另一個編號撞名,整批不做、講是哪幾個。
- **收回一次匯入**(`undo`):新增的刪掉(已經有公司對到它就整批不收)、修改的倒回改之前;收回之後又被改過的不收(整批不做)。
- 價格只是參考(Codex 整理的,有寫明種類),**不會寫進任何一家的售價**;展開到公司是另一件事(`device_expand.py`)。
"""
from __future__ import annotations

import hashlib
import json

from django.db import transaction
from django.utils import timezone

from .models import DeviceCatalogChange, DeviceCatalogRun, DeviceModel, PhoneModel

DATA_KEYS = ("origin", "capacities", "connectivity", "sizes_mm", "colors", "prices", "sources", "aliases",
             "old_uids", "needs_review")
CATEGORIES = {c.value for c in DeviceModel.Category}


class CatalogError(Exception):
    """整批不能做的原因(可以直接給人看)。"""


def _row(m: dict) -> dict:
    """檔案裡的一支 → 要存進表的樣子(欄位 + data)。"""
    uid = str(m.get("uid") or "").strip()
    name = str(m.get("name") or "").strip()
    brand = str(m.get("brand") or "").strip()
    category = str(m.get("category") or "").strip()
    if not uid or not name or not brand:
        raise CatalogError(f"有一筆沒有編號 / 品牌 / 型號:{uid or name or '(空白)'}")
    if category not in CATEGORIES:
        raise CatalogError(f"{brand} {name}:類別「{category}」不認得")
    if len(uid) > 64 or len(name) > 160 or len(brand) > 80:
        raise CatalogError(f"{brand} {name}:編號 / 品牌 / 型號太長")
    return {
        "uid": uid, "category": category, "brand": brand, "name": name,
        "launched": str(m.get("launched") or "").strip()[:10],
        "data": {k: m[k] for k in DATA_KEYS if k in m},
    }


def _hash(row: dict) -> str:
    body = {k: row[k] for k in ("category", "brand", "name", "launched", "data")}
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _snapshot(d: DeviceModel) -> dict:
    return {"uid": d.uid, "category": d.category, "brand": d.brand, "name": d.name, "launched": d.launched,
            "data": d.data, "content_hash": d.content_hash, "is_active": d.is_active}


def _name_key(row) -> tuple:
    return (row["category"], row["brand"].casefold(), row["name"].casefold())


def plan(payload: dict) -> dict:
    """只讀:這份檔案匯進去會新增 / 修改 / 不動幾支。回 {"created": [row], "updated": [(DeviceModel, row)], "unchanged": n}。"""
    models = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(models, list) or not models:
        raise CatalogError("檔案裡沒有型號(要有 models)")
    rows, seen_uid, seen_name = [], set(), {}
    for m in models:
        row = _row(m)
        if row["uid"] in seen_uid:
            raise CatalogError(f"編號重複:{row['uid']}")
        key = _name_key(row)
        if key in seen_name:
            raise CatalogError(f"同一個型號出現兩次:{row['brand']} {row['name']}")
        seen_uid.add(row["uid"])
        seen_name[key] = row["uid"]
        row["content_hash"] = _hash(row)
        rows.append(row)
    old_uids = {u for r in rows for u in r["data"].get("old_uids", [])}
    if old_uids & seen_uid:
        raise CatalogError("舊編號跟另一支的編號一樣:" + "、".join(sorted(old_uids & seen_uid)[:5]))
    existing = {d.uid: d for d in DeviceModel.objects.all()}
    taken = {(d.category, d.brand.casefold(), d.name.casefold()): d.uid for d in existing.values()}
    clashes = [f"{r['brand']} {r['name']}" for r in rows if taken.get(_name_key(r), r["uid"]) != r["uid"]]
    if clashes:
        raise CatalogError("跟型號庫裡另一個編號撞名:" + "、".join(clashes[:5]) + (f" 等 {len(clashes)} 支" if len(clashes) > 5 else ""))
    created, updated, unchanged = [], [], 0
    for r in rows:
        d = existing.get(r["uid"])
        if d is None:
            created.append(r)
        elif d.content_hash != r["content_hash"]:
            updated.append((d, r))
        else:
            unchanged += 1
    return {"created": created, "updated": updated, "unchanged": unchanged}


def sync(payload: dict, *, source: str) -> DeviceCatalogRun | None:
    """寫進型號庫。沒有要改的 → 不記一次匯入、回 None(重跑同一份 = 什麼都不動)。"""
    with transaction.atomic():
        p = plan(payload)
        if not p["created"] and not p["updated"]:
            return None
        run = DeviceCatalogRun.objects.create(source=source[:200])
        changes = []
        for r in p["created"]:
            d = DeviceModel.objects.create(**{k: r[k] for k in ("uid", "category", "brand", "name", "launched", "data", "content_hash")})
            changes.append(DeviceCatalogChange(run=run, uid=d.uid, action=DeviceCatalogChange.Action.CREATED, before=None, after=_snapshot(d)))
        for d, r in p["updated"]:
            before = _snapshot(d)
            for k in ("category", "brand", "name", "launched", "data", "content_hash"):
                setattr(d, k, r[k])
            d.save()
            changes.append(DeviceCatalogChange(run=run, uid=d.uid, action=DeviceCatalogChange.Action.UPDATED, before=before, after=_snapshot(d)))
        DeviceCatalogChange.objects.bulk_create(changes)
        run.counts = {"created": len(p["created"]), "updated": len(p["updated"]), "unchanged": p["unchanged"]}
        run.save(update_fields=["counts", "updated_at"])
        return run


def undo(run_id: int) -> dict:
    """收回一次匯入。整批在一個交易裡:任何一支收不回(有公司對到、之後又被改過)就整批不動。"""
    with transaction.atomic():
        run = DeviceCatalogRun.objects.select_for_update().filter(pk=run_id).first()
        if run is None:
            raise CatalogError(f"沒有這一次匯入:{run_id}")
        if run.undone_at:
            raise CatalogError(f"這一次已經收回過了({run.undone_at:%Y-%m-%d %H:%M})")
        changes = list(run.changes.order_by("-id"))
        rows = {d.uid: d for d in DeviceModel.objects.select_for_update().filter(uid__in=[c.uid for c in changes])}
        later = set(DeviceCatalogChange.objects.filter(uid__in=rows, run__undone_at__isnull=True, run_id__gt=run.pk)
                    .values_list("uid", flat=True))
        if later:
            raise CatalogError("之後的匯入又改過這幾支,先收回後面那一次:" + "、".join(sorted(later)[:5]))
        created = [c.uid for c in changes if c.action == DeviceCatalogChange.Action.CREATED]
        linked = sorted(set(PhoneModel.objects.filter(device_uid__in=created).values_list("device_uid", flat=True)))
        if linked:
            names = [str(rows[u]) for u in linked if u in rows]
            raise CatalogError("這幾支已經有公司對到,不能刪:" + "、".join(names[:5]))
        restored = deleted = 0
        for c in changes:
            d = rows.get(c.uid)
            if d is None:
                continue
            if d.content_hash != c.after.get("content_hash"):
                raise CatalogError(f"「{d}」在這一次之後又被改過,不能收回")
            if c.action == DeviceCatalogChange.Action.CREATED:
                d.delete()
                deleted += 1
            else:
                for k in ("category", "brand", "name", "launched", "data", "content_hash", "is_active"):
                    setattr(d, k, c.before[k])
                d.save()
                restored += 1
        run.undone_at = timezone.now()
        run.save(update_fields=["undone_at", "updated_at"])
        return {"deleted": deleted, "restored": restored}
