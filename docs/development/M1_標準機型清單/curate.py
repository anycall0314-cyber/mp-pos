"""M1a 草稿:把查價系統(創宇基準)的機型整理成「一般寫法」的標準名稱,並跟 POS 現有的標準型錄合在一起。只產生草稿檔,不寫任何資料庫。

輸入:同一個資料夾的 `hub_by_model.json`(2026-10-14 從查價系統的正式庫唯讀匯出的機型名稱與規格;重抓的查法見 README.md)
     與 `backend/apps/catalog/data/` 現有的標準型錄。
輸出:`standard_draft.json`(一筆一個機型:品牌、類型、標準名稱、規格、創宇的原寫法、POS 現在的名稱、註記)。
跑法:python3 curate.py
"""
import collections, glob, json, os, re

S = os.path.dirname(os.path.abspath(__file__)) + "/"
POS = os.path.normpath(os.path.join(S, "../../../backend/apps/catalog/data"))

# 查價系統的品牌 → (代碼, 顯示的品牌, 機型名稱前面要不要帶品牌字)
BRANDS = {
    "Apple": ("apple", "Apple", ""), "Samsung": ("samsung", "Samsung", ""), "Google": ("google", "Google", ""),
    "ASUS": ("asus", "ASUS", ""), "SHARP": ("sharp", "SHARP", ""), "SONY": ("sony", "Sony", ""),
    "OPPO": ("oppo", "OPPO", "OPPO "), "vivo": ("vivo", "vivo", "vivo "), "realme": ("realme", "realme", "realme "),
    "紅米": ("redmi", "紅米", "紅米 "), "小米": ("xiaomi", "小米", "小米 "), "POCO": ("poco", "POCO", "POCO "),
    "Motorola": ("motorola", "Motorola", None), "Nothing": ("nothing", "Nothing", None),
    "HTC": ("htc", "HTC", "HTC "), "NOKIA": ("nokia", "Nokia", "Nokia "), "HONOR": ("honor", "HONOR", "HONOR "),
    "HUAWEI": ("huawei", "HUAWEI", "HUAWEI "), "黑鯊": ("blackshark", "黑鯊", "黑鯊 "), "iQOO": ("iqoo", "iQOO", "iQOO "),
    "Lenovo": ("lenovo", "Lenovo", "Lenovo "),
}
WORDS = {"pro": "Pro", "max": "Max", "ultra": "Ultra", "plus": "Plus", "lite": "Lite", "fusion": "Fusion", "power": "Power",
         "play": "Play", "fe": "FE", "gt": "GT", "neo": "Neo", "flip": "Flip", "fold": "Fold", "edition": "Edition",
         "ultimate": "Ultimate", "5g": "5G", "4g": "4G", "edge": "Edge", "razr": "Razr", "narzo": "Narzo", "xl": "XL"}
SPECIAL = re.compile(r"限量|聯名|特仕|權力遊戲|鋼鐵人|Hello Kitty|MOLLY")


def tidy(name):
    name = name.replace("_", " ")
    out = []
    for tok in name.split():
        low = tok.lower()
        plus = low.endswith("+")
        core = low[:-1] if plus else low
        out.append((WORDS[core] + "+") if plus and core in WORDS else WORDS.get(low, tok))
    return re.sub(r"\s+", " ", " ".join(out)).strip()


def standard_name(brand, raw):
    """回 (標準名稱, 類型有沒有要改, 註記)。"""
    n, note, form = tidy(raw), [], None
    if brand == "Samsung":
        n = re.sub(r"Galaxy Note (\d+)", r"Galaxy Note\1", n)
        n = re.sub(r"Galaxy Z (Fold|Flip) (\d)(?!G)", r"Galaxy Z \1\2", n)
    elif brand == "OPPO":
        if "倍變焦" in n:
            n = "Reno 十倍變焦版"
        n = re.sub(r"Reno (\d+)", r"Reno\1", n)
        n = re.sub(r"Reno(\d+)\s*([FZT])\b", r"Reno\1 \2", n)
        n = re.sub(r"^(A\d+\w*) (20\d\d)$", r"\1 (\2)", n)
    elif brand == "vivo":
        n = re.sub(r"X Fold (\d)", r"X Fold\1", n)
        n = re.sub(r"^(Y\d+)\((20\d\d)\) 5G$", r"\1 5G (\2)", n)
        n = re.sub(r"^(Y\d+)S\b", r"\1s", n)
    elif brand == "realme":
        n = re.sub(r"^(\d+)X\b", r"\1x", n)
        n = re.sub(r"^(C\d+) (20\d\d)$", r"\1 (\2)", n)
    elif brand in ("紅米", "小米"):
        n = re.sub(r"\bLTE\b", "4G", n)
    elif brand == "Motorola":
        low = n.lower()
        if "one vision plus" in low:
            n = "Motorola One Vision Plus"
        elif low.startswith("one "):
            n = "Motorola " + n
        elif re.match(r"^[eg]\b|^[eg]\d", low):
            n = "Moto " + n[0].upper() + n[1:]
        else:
            n = "Motorola " + n[0].upper() + n[1:]
        n = re.sub(r"\b(Razr) fold\b", r"\1 Fold", n)
    elif brand == "Apple":
        n = re.sub(r"^iPhone (\d+)\+$", r"iPhone \1 Plus", n)
        n = re.sub(r"^iPhone SE(\d)$", r"iPhone SE \1", n)
        n = re.sub(r"^(iPad Pro \d+(?:\.\d)?) (\d)$", r"\1 第\2代", n)
    elif brand == "ASUS":
        n = n.replace("ZenFone", "Zenfone")
    elif brand == "SHARP":
        n = re.sub(r"AQUOS (sense|wish|zero) ?(\d+\w*)", r"AQUOS \1\2", n)
        n = n.replace("sense4+", "sense4 plus").replace("sense4 Plus", "sense4 plus").replace("sense7 Plus", "sense7 plus")
        n = n.replace("AQUOS R5G 5G", "AQUOS R5G")
    elif brand == "Nothing":
        m = re.match(r"^Phone ?\((\w+)\)(.*)$", n)
        n = f"Nothing Phone ({m.group(1)}){m.group(2)}" if m else n
    elif brand == "HUAWEI":
        if "MatePad" in n:
            form = "tablet"
            n = n.replace("/WIFI", "")
    elif brand == "NOKIA" and n == "T21":
        form = "tablet"
    prefix = BRANDS[brand][2]
    if prefix:
        n = prefix + n
    if SPECIAL.search(n):
        note.append("特別版")
    if form:
        note.append("改成平板")
    return re.sub(r"\s+", " ", n).strip(), form, note


def norm(s):
    s = s.lower().replace("plus", "+")
    s = re.sub(r"\b[45]g\b", "", s)
    return re.sub(r"[\s\-()（）吋\"'第代]", "", s)


def spec_text(v, form):
    storage, ram, conn = v
    text = f"{ram}+{storage}" if ram else storage
    if form == "tablet" and conn:
        text += " WiFi" if conn == "wifi" else " 插卡"
    return text


hub = json.load(open(S + "hub_by_model.json", encoding="utf-8"))
out = collections.OrderedDict()            # (品牌代碼, 標準名稱) → 一筆
for key, v in hub.items():
    brand, raw = key.split("|", 1)
    name, form, note = standard_name(brand, raw)
    form = form or v["form"]
    code, shown, _ = BRANDS[brand]
    row = out.setdefault((code, name), {"brand": shown, "brand_code": code, "kind": {"phone": "手機", "tablet": "平板"}[form],
                                        "name": name, "specs": [], "from_hub": [], "pos_name": "", "note": list(note)})
    if row["from_hub"]:
        row["note"].append("創宇有兩種寫法,併成一筆")
    row["from_hub"].append(raw)
    for x in v["variants"]:
        t = spec_text(tuple(x), form)
        if t not in row["specs"]:
            row["specs"].append(t)

# ── POS 現有的標準型錄:對得上的記下現在的名稱(之後改名用),對不上的補進來 ──
POS_BRAND = {"apple": "Apple", "samsung": "Samsung", "google": "Google", "oppo": "OPPO", "vivo": "vivo", "realme": "realme",
             "xiaomi": "小米", "redmi": "紅米", "asus": "ASUS", "sony": "Sony"}
index = collections.defaultdict(list)
for (code, name), row in out.items():
    index[(code, norm(name))].append((code, name))
    for raw in row["from_hub"]:
        index[(code, norm(raw))].append((code, name))


def pos_new_style(code, series, gen, suffix, kind):
    """POS 現有的那一筆照一般寫法會叫什麼(只給對不上創宇的那幾筆用)。"""
    series, suffix = (series or "").strip(), (suffix or "").strip()
    gen = "" if gen in (None, "") else str(gen)
    tight = bool(re.search(r"Galaxy (S|A|M|Note|Z Fold|Z Flip|Tab S|Tab A|Watch)$|^Reno$|^Find X$", series))
    head = series + ("" if tight else " ") + gen if gen else series
    attach = bool(re.match(r"^(\+|[a-z]\b|[A-Z]\b(?! ))", suffix)) and suffix not in ("Pro", "Max", "Air")
    name = (head + ("" if attach else " ") + suffix).strip() if suffix else head.strip()
    name = name.replace("Xiaomi Watch", "小米 Watch").replace("Redmi ", "紅米 ")
    if code in ("oppo", "vivo") and not name.lower().startswith(code):
        name = POS_BRAND[code] + " " + name
    if series == "Apple Watch" and gen:
        name = name.replace(f"Apple Watch {gen}", f"Apple Watch Series {gen}")
    name = name.replace("Apple Watch SE 第2代", "Apple Watch SE 2")
    return re.sub(r"\s+", " ", name).strip()


SAME = {   # (品牌, POS 現在接出來的名稱) → 標準名稱
    ("apple", "iPhone 10"): "iPhone X", ("apple", "iPhone 10 R"): "iPhone XR", ("apple", "iPhone 10 S"): "iPhone XS",
    ("apple", "iPhone 10 S Max"): "iPhone XS Max", ("apple", "iPhone 17 Air"): "iPhone Air",
    ("apple", "iPad 11 (A16)"): "iPad 11", ("apple", "iPad Air 5 (M1)"): "iPad Air 5", ("apple", "iPad mini 7 (A17 Pro)"): "iPad mini 7",
}
pos_total = matched = 0
for p in sorted(glob.glob(POS + "/taiwan_catalog/*.json")) + [POS + "/phone_models_extra.json"]:
    d = json.load(open(p, encoding="utf-8"))
    for m in d["models"]:
        pos_total += 1
        code = m["brand"]
        gen = "" if m.get("generation") in (None, "") else str(m["generation"])
        current = " ".join(x for x in (m.get("series") or "", gen, m.get("model_suffix") or "") if x)   # 現在 POS 接出來的名稱
        cands = index.get((code, norm(current)), []) or index.get((code, norm(POS_BRAND.get(code, "") + current)), [])
        if not cands and code in ("xiaomi", "redmi"):
            stripped = re.sub(r"^(小米|Redmi|Xiaomi)\s*", "", current)
            cands = index.get((code, norm(stripped)), []) or index.get((code, norm(("小米 " if code == "xiaomi" else "紅米 ") + stripped)), [])
        if (code, current) in SAME and (code, SAME[(code, current)]) in out:
            cands = [(code, SAME[(code, current)])]
        if not cands and code == "realme":
            cands = index.get((code, norm(re.sub(r"^realme\s*", "", current))), [])
        kind = m.get("kind") or ""
        if cands:
            matched += 1
            row = out[cands[0]]
            row["pos_name"] = current
            if m.get("colors"):
                row["colors"] = m["colors"]
            continue
        name = pos_new_style(code, m.get("series"), m.get("generation"), m.get("model_suffix"), kind)
        row = out.setdefault((code, name), {"brand": POS_BRAND.get(code, code), "brand_code": code, "kind": kind or "手機", "name": name,
                                            "specs": [], "from_hub": [], "pos_name": current, "note": []})
        row["pos_name"] = current
        row["note"].append("創宇沒有,POS 原本就有")
        for c in m.get("capacities") or []:
            if c not in row["specs"]:
                row["specs"].append(c)
        if m.get("colors"):
            row["colors"] = m["colors"]

rows = sorted(out.values(), key=lambda r: (r["brand"].lower(), {"手機": 0, "平板": 1, "手錶": 2}.get(r["kind"], 3), r["name"].lower()))
json.dump(rows, open(S + "standard_draft.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("草稿共", len(rows), "個機型 | POS 現有", pos_total, "對上創宇", matched)
print("依類型", collections.Counter(r["kind"] for r in rows))
print("依品牌", collections.Counter(r["brand"] for r in rows).most_common())
print("註記", collections.Counter(n for r in rows for n in r["note"]))
changed = [(r["pos_name"], r["name"]) for r in rows if r["pos_name"] and r["pos_name"] != r["name"]]
print("POS 現有的名稱要改的", len(changed), "例:", changed[:14])
print("POS 原本就有、創宇沒有:", [r["name"] for r in rows if "創宇沒有,POS 原本就有" in r["note"]])
by = collections.defaultdict(list)
for r in rows:
    if r["from_hub"] and r["from_hub"][0] != r["name"].replace(BRANDS.get(r["brand"], ("", "", ""))[2] or "", "", 1):
        by[r["brand"]].append(f'{r["from_hub"][0]} → {r["name"]}')
for b, xs in by.items():
    print(f"## {b} 改了寫法的 {len(xs)}:", " | ".join(xs[:14]))
print("特別版:", [r["name"] for r in rows if "特別版" in r["note"]])
print("沒有規格的:", len([r for r in rows if not r["specs"]]), "| 有顏色的:", len([r for r in rows if r.get("colors")]))
