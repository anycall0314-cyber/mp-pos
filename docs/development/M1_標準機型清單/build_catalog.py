"""M1-A:平台型號庫的定稿資料 → backend/apps/catalog/data/device_catalog.json(owner 2026-10-15「照你建議」:Codex v4 為主、補草稿裡它沒有的舊機)。

來源:
- Codex 整理的 `taiwan-device-catalog-v4`(owner 的 ~/Documents/Codex/2026-10-14/new-chat/outputs/;不進版本庫,路徑用 --v4 給)。1,400 個,2018-10-14 以後上市。
- 這個資料夾的 `standard_draft.json`(第二版草稿)。草稿裡 v4 沒有的,**只補 Jev 有把握說「都不是」的**(`jev_draft_decisions.json`);
  Jev 說是同一支的不補(v4 已經有);沒把握的不補、列在 `pending_review.json` 給 owner 定(補了會變成同一支兩個型號,庫存拆兩半)。

每個型號留:穩定編號 `uid`(v4 的 model_id;草稿補的用品牌 + 名稱算一個)、類別、品牌、名稱(一般寫法,照 v4)、上市年月、容量、連線、尺寸、顏色、
有寫明種類的台幣價格(只是參考,不是門市售價)、來源網址、別名(來源上的寫法、v4 的舊編號)。
顏色照來源的順序取第一個有的:手機王(sogi)→ 原廠台灣官網 → 比價王(eprice)→ 媒體,不同來源不合併(不同寫法會變成重複的顏色);容量每個來源都收(含價格上寫的)。

跑法:python3 build_catalog.py --v4 <taiwan-device-catalog-v4 資料夾>(只讀來源、只寫輸出檔)。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
OUT = REPO / "backend/apps/catalog/data/device_catalog.json"
PENDING = HERE / "pending_review.json"
PROVIDER_ORDER = ("sogi", "official_tw", "eprice", "media_tw")
KIND = {"手機": "phone", "平板": "tablet", "手錶": "watch", "手環": "band", "耳機": "headphones", "其他穿戴": "other"}
BRAND = {"小米": "Xiaomi"}
# 草稿補進來的編號:固定的命名空間 + 品牌 + 名稱(重跑同一個)
DRAFT_NS = uuid.UUID("6f1d2c4e-5b7a-4c1e-9a3f-2d8b0e7c9a11")


def provider(record_id: str) -> str:
    return record_id.split(":", 1)[0]


def by_preference(rows, field):
    """[{record_id, <field>}] 照來源順序排;同一個來源保留原本的先後。"""
    rank = {p: i for i, p in enumerate(PROVIDER_ORDER)}
    return sorted(rows, key=lambda r: rank.get(provider(r["record_id"]), len(rank)))


def storage_key(label: str) -> float:
    m = re.match(r"^(\d+(?:\.\d+)?)\s*(MB|GB|TB)$", label or "", re.I)
    if not m:
        return 1e18
    n, unit = float(m.group(1)), m.group(2).upper()
    return n * {"MB": 1 / 1024, "GB": 1, "TB": 1024}[unit]


def first_source_values(m, pick):
    """照來源順序,第一個有值的來源給的值(去重、保留順序)。"""
    for row in by_preference(m.get("variants_by_source", []), "variants"):
        vals = []
        for v in row["variants"]:
            x = pick(v.get("dimensions") or {})
            if x and x not in vals:
                vals.append(x)
        if vals:
            return vals
    return []


def launch_of(m) -> str:
    vals = sorted(d["value"] for d in m.get("launch_dates_by_source", []) if d.get("value"))
    return vals[0] if vals else ""


def from_v4(m, prices) -> dict:
    colors = []
    for row in by_preference(m.get("colors_by_source", []), "colors"):
        if row["colors"]:
            colors = list(dict.fromkeys(row["colors"]))
            break
    # 容量:每個來源、每筆價格上寫的儲存空間都收(手機王常只列一種;容量是事實,不像顏色有好幾種寫法)
    caps = {(v.get("dimensions") or {}).get("storage") for row in m.get("variants_by_source", []) for v in row["variants"]}
    caps |= {p["storage"] for p in prices.get(m["model_id"], [])}
    # 超過 4TB 的是來源打錯(iPad Pro (2021) 有一筆「21TB」)
    caps = sorted((c for c in caps if c and storage_key(c) <= 4096), key=storage_key)
    return {
        "uid": m["model_id"],
        "origin": "codex-v4",
        "category": m["category"],
        "brand": m["brand"],
        "name": m["name"],
        "launched": launch_of(m),
        "capacities": caps,
        "connectivity": first_source_values(m, lambda d: d.get("connectivity")),
        "sizes_mm": first_source_values(m, lambda d: str(d["size_mm"]) if d.get("size_mm") else None),
        "colors": colors,
        "prices": prices.get(m["model_id"], []),
        "sources": [s["url"] for s in m.get("sources", []) if s.get("url")],
        "aliases": sorted({n for n in m.get("source_names", []) if n and n != m["name"]}),
        "needs_review": list(m.get("review_reasons") or []),
    }


def from_draft(d) -> dict:
    brand = BRAND.get(d["brand"], d["brand"])
    caps, conn = [], []
    for v in d.get("variants") or []:
        spec = (v.get("spec") if isinstance(v, dict) else str(v)) or ""
        # 「6+128GB」「32GB WiFi」「64GB 插卡」:容量只留儲存空間,WiFi / 插卡另外記
        found = re.findall(r"(\d+(?:\.\d+)?\s*(?:MB|GB|TB))", spec, re.I)
        st = found[-1].replace(" ", "").upper() if found else ""
        if st and st not in caps:
            caps.append(st)
        for word, label in (("wifi", "WiFi"), ("插卡", "LTE"), ("lte", "LTE"), ("5g", "5G")):
            if word in spec.lower() and label not in conn:
                conn.append(label)
    return {
        "uid": str(uuid.uuid5(DRAFT_NS, f"{brand}|{d['name']}")),
        "origin": "m1-draft",
        "category": KIND.get(d.get("kind"), "other"),
        "brand": brand,
        "name": d["name"],
        "launched": (d.get("launch") or "").replace("/", "-"),
        "capacities": sorted(caps, key=storage_key),
        "connectivity": conn,
        "sizes_mm": [],
        "colors": list(dict.fromkeys(d.get("colors") or [])),
        "prices": [],
        "sources": [],
        "aliases": sorted({n for n in [*(d.get("sogi") or []), *(d.get("eprice") or [])] if n and n != d["name"]}),
        "needs_review": [],
    }


def price_rows(facts) -> dict:
    out: dict[str, list] = {}
    for f in facts:
        if f.get("currency") != "TWD" or not isinstance(f.get("amount"), int):
            continue
        dims = f.get("version_dimensions") or {}
        row = {
            "version": f.get("version_label") or "",
            "storage": dims.get("storage"),
            "connectivity": dims.get("connectivity"),
            "size_mm": dims.get("size_mm"),
            "amount": f["amount"],
            "kind": f.get("price_kind") or "",
            "url": f.get("source_url") or "",
        }
        for mid in f.get("research_model_ids") or []:
            out.setdefault(mid, []).append(row)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--v4", required=True, type=Path)
    args = ap.parse_args()
    v4 = json.loads((args.v4 / "data/models.json").read_text())
    facts = json.loads((args.v4 / "data/research-price-facts.json").read_text())
    aliases = json.loads((args.v4 / "review/identity-reconciliation.json").read_text())
    draft = json.loads((HERE / "standard_draft.json").read_text())
    decisions = json.loads((HERE / "jev_draft_decisions.json").read_text())

    prices = price_rows(facts)
    models = [from_v4(m, prices) for m in v4]
    by_uid = {m["uid"]: m for m in models}
    for a in aliases.get("reviewed_family_aliases", []):
        target = by_uid.get(a["canonical_model_id"])
        if target is not None:
            target.setdefault("old_uids", []).append(a["alias_model_id"])
            if a.get("alias_name"):
                target["aliases"] = sorted({*target["aliases"], a["alias_name"]})
    assert not ({a["alias_model_id"] for a in aliases.get("reviewed_family_aliases", [])} & set(by_uid)), "舊編號不應該自己是一個型號"

    added, pending = [], []
    for d_id, dec in decisions.items():
        d = draft[int(d_id)]
        if dec["verdict"] == "採用" and dec["answer"] == "none":
            added.append(from_draft(d))
        elif dec["verdict"] != "採用":
            pending.append({"draft": f"{d['brand']} {d['name']}", "jev_answer": dec["answer_text"],
                            "confidence": dec["confidence"], "verdict": dec["verdict"]})
    seen = {(m["brand"].lower(), m["name"].lower()) for m in models}
    for m in added:
        assert (m["brand"].lower(), m["name"].lower()) not in seen, m["name"]
        seen.add((m["brand"].lower(), m["name"].lower()))
    models.extend(added)
    models.sort(key=lambda m: (m["category"], m["brand"].lower(), m["name"].lower()))
    payload = {
        "_why": "平台型號庫(M1);產生方式見 docs/development/M1_標準機型清單/build_catalog.py。價格只是參考,不是門市售價。",
        "version": hashlib.sha256(json.dumps(models, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:12],
        "models": models,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n")
    PENDING.write_text(json.dumps(sorted(pending, key=lambda p: p["draft"]), ensure_ascii=False, indent=1) + "\n")
    cats = {}
    for m in models:
        cats[m["category"]] = cats.get(m["category"], 0) + 1
    print(f"{len(models)} 個(v4 {len(v4)} + 草稿補 {len(added)});{cats};待 owner 定 {len(pending)};版本 {payload['version']}")


if __name__ == "__main__":
    main()
