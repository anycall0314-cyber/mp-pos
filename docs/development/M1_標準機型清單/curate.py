"""M1a 草稿第二版:主要來源手機王(SOGI:名稱、每一種版本的原廠售價、機身顏色、上市年月),比價王(ePrice)核對與補漏,
創宇(查價系統的機型表)補舊機型,再對上 POS 現有的標準型錄。只產生草稿檔,不寫任何資料庫。

輸入(同一個資料夾):web/sogi_products.json(parse_sogi.py 讀商品頁的結果)、web/keys.json(keys.mjs 用查價系統的規則算的機型鍵)、
web/eprice_*.json(比價王的清單)、hub_by_model.json / hub_keys.json(創宇基準的機型與規格)。
輸出:standard_draft.json。
"""
import collections, glob, json, os, re

S = os.path.dirname(os.path.abspath(__file__)) + "/"
POS = os.path.normpath(os.path.join(S, "../../../backend/apps/catalog/data")) if os.path.exists(os.path.join(S, "../../../backend")) \
    else os.path.expanduser("~/MP_POS系統/backend/apps/catalog/data")

SHOW = {"samsung": "Samsung", "apple": "Apple", "小米": "小米", "xiaomi": "小米", "redmi": "小米", "poco": "POCO", "榮耀": "HONOR", "honor": "HONOR",
        "sony": "Sony", "moto": "Motorola", "motorola": "Motorola", "nokia": "Nokia", "huawei": "HUAWEI", "oppo": "OPPO", "vivo": "vivo",
        "realme": "realme", "google": "Google", "asus": "ASUS", "sharp": "SHARP", "htc": "HTC", "nothing": "Nothing", "lenovo": "Lenovo",
        "iqoo": "iQOO", "黑鯊": "黑鯊", "紅米": "小米"}
NO_PREFIX = {"Samsung", "Apple", "Google", "Sony", "SHARP", "ASUS"}          # 機型名稱自己就認得出來的品牌:名稱前面不帶品牌字
WORDS = {"pro": "Pro", "max": "Max", "ultra": "Ultra", "plus": "Plus", "lite": "Lite", "fusion": "Fusion", "power": "Power", "neo": "Neo",
         "fe": "FE", "gt": "GT", "flip": "Flip", "fold": "Fold", "5g": "5G", "4g": "4G", "edge": "Edge", "razr": "Razr", "redmi": "Redmi",
         "moto": "Moto", "pad": "Pad", "xl": "XL"}
SPECIAL = re.compile(r"限量|限定|聯名|特仕|權力遊戲|鋼鐵人|Hello Kitty|MOLLY|茉莉|特別版|Special Edition|套組|套裝|保護套")


def brand_of(name):
    first = name.split()[0]
    return SHOW.get(first.lower(), first)


def tidy_words(text):
    out = []
    for tok in text.split():
        low = tok.lower()
        plus = low.endswith("+")
        core = low[:-1] if plus else low
        out.append((WORDS[core] + "+") if plus and core in WORDS else WORDS.get(low, tok))
    return " ".join(out)


def standard_name(brand, display):
    """把來源給的品名變成標準名稱:拿掉重複的品牌字、統一大小寫、該帶品牌的帶上。"""
    n = re.sub(r"\s+", " ", display).strip()
    n = re.sub(r"^(SAMSUNG|Samsung|Apple|APPLE|Google|Sony|SONY|SHARP|ASUS|OPPO|vivo|realme|Motorola|Moto|Nokia|NOKIA|HUAWEI|HONOR|Honor|HTC|Nothing|Lenovo|iQOO|小米|Xiaomi(?= (?:Xiaomi|Redmi|REDMI|POCO|紅米)))\s+", "", n)
    n = n.replace("紅米", "Redmi")
    if brand == "Motorola":
        low = n.lower()
        if re.match(r"^moto [ge]", low):
            n = "Moto " + n[5].upper() + n[6:]
        elif re.match(r"^[ge]\d|^[ge] ", low):
            n = "Moto " + n[0].upper() + n[1:]
        elif low.startswith("pad"):
            n = "Moto " + n
        else:
            n = "Motorola " + n[0].upper() + n[1:]
        n = tidy_words(n).replace("ULTRA", "Ultra").replace("LITE", "Lite").replace("NEO", "Neo")
        return n
    n = tidy_words(n)
    if brand == "Apple":
        n = re.sub(r"^Watch ", "Apple Watch ", n)
    if brand == "小米":
        if not re.match(r"^(Xiaomi|Redmi|POCO|Leica)", n):
            n = "Xiaomi " + n
    elif brand == "Nothing":
        m = re.match(r"^Phone ?\((\w+)\)(.*)$", n)
        n = f"Nothing Phone ({m.group(1)}){m.group(2)}" if m else ("Nothing " + n if not n.startswith("CMF") else n)
    elif brand not in NO_PREFIX and not n.lower().startswith(brand.lower()):
        n = f"{brand} {n}"
    return re.sub(r"\s+", " ", n).strip()


def spec_of(label, rom, conn=None):
    label = (label or "").strip()
    m = re.search(r"\(?(\d+)\s*GB\s*/\s*(\d+\s*[GT]B)\)?", label)
    if m:
        before = label[:m.start()].strip(" (")
        text = (before + " " if before else "") + f"{m.group(1)}+{m.group(2).replace(' ', '')}"
    else:
        text = label or rom.replace(" ", "")
    if conn:
        text += " WiFi" if conn == "wifi" else " 插卡"
    return text


def wearable_kind(cls, name):
    blob = f"{cls} {name}"
    if re.search(r"耳機|Buds|AirPods|\bEar\b|WF-|WH-|WI-|FreeBuds|FreeClip|INZONE|Soundcore|ComfoBuds|Hammerhead|Cetra|TWS|Verve|Beats|1MORE", blob, re.I):
        return "耳機"
    if re.search(r"手環|Band|\bFit\d?\b|Inspire", blob, re.I):
        return "手環"
    if re.search(r"手錶|Watch|WATCH|Forerunner|Venu|Instinct|Approach|MARQ|vivomove|T-Rex|GT[RS] |Balance|Amazfit|Sense|Versa|Bip", blob):
        return "手錶"
    return "其他穿戴"


def nkey(text):
    text = text.lower().replace("plus", "+")
    return re.sub(r"[\s\-()（）吋\"'第代]", "", text)


keys = json.load(open(S + "web/keys.json", encoding="utf-8"))
products = json.load(open(S + "web/sogi_products.json", encoding="utf-8")) if os.path.exists(S + "web/sogi_products.json") else []
hub_models = json.load(open(S + "hub_by_model.json", encoding="utf-8"))
hub_keys = json.load(open(S + "hub_keys.json", encoding="utf-8"))

MARK = re.compile(r"\b(5G|4G|LTE)\b")


def marker(text):
    """名稱上寫的是 5G、4G(LTE),還是沒寫。"""
    m = MARK.search(text.replace("_", " "))
    return "" if not m else ("5G" if m.group(1) == "5G" else "4G")


def loose(name):
    """拿掉 4G / 5G 之後的比對鍵:同一支手機各家有的寫 5G、有的不寫。"""
    return nkey(MARK.sub(" ", name.replace("_", " ")))


out = collections.OrderedDict()            # (品牌, 比對鍵, 4G/5G) → 一筆
slots = collections.defaultdict(dict)      # (品牌, 比對鍵) → {"": 鍵, "4G": 鍵, "5G": 鍵}
multi = {}                                 # (來源, 品牌, 比對鍵) → 這個來源自己有沒有把 4G 與 5G 分成兩個商品


def place(source, brand, kind, name, source_markers):
    """這個品名是清單上的哪一筆(沒有就開一筆)。4G 與 5G 是不同的手機,但同一支常常有人寫 5G、有人不寫:
    - 寫法一樣的(都寫 5G、都沒寫)是同一筆;
    - 這個來源自己只有一種寫法、清單上也只有一筆、而且那一筆的來源也只有一種寫法 → 同一支,只是寫法不同;
    - 沒寫的與寫 4G 的是同一筆(旁邊有一支寫 5G 的時候,沒寫的那一支就是 4G 版)。"""
    lk, mk = loose(name), marker(name)
    here = slots[(brand, lk)]
    many = len(source_markers.get((brand, lk), {mk})) > 1
    key = here.get(mk)
    if key is None and mk in ("", "4G"):
        key = here.get("4G" if mk == "" else "")
    if key is None and not many and len(set(here.values())) == 1:
        only = next(iter(here.values()))
        if not out[only]["_many"]:
            key = only
    if key is None:
        key = (brand, lk, mk)
        out[key] = {"brand": brand, "kind": kind, "name": name, "launch": "", "variants": [], "colors": [],
                    "sogi": [], "eprice": [], "hub": [], "pos_name": "", "note": [], "_many": many}
    out[key]["_many"] = out[key]["_many"] or many
    here.setdefault(mk, key)
    return out[key]


def markers_of(pairs):
    seen = collections.defaultdict(set)
    for brand, name in pairs:
        seen[(brand, loose(name))].add(marker(name))
    return seen


ep_years = set()                           # 比價王寫了年份的品名:(品牌, 比對鍵)
for _lib in ("mobile", "pad"):
    if os.path.exists(S + f"web/eprice_{_lib}.json"):
        for _full, _pid in json.load(open(S + f"web/eprice_{_lib}.json", encoding="utf-8")):
            if re.search(r"\(20\d\d\)$", _full.strip()):
                _b = brand_of(_full)
                ep_years.add((_b, nkey(standard_name(_b, _full))))

# ── 1. 手機王(名稱以它為準) ──
KIND = {"cellphone": "手機", "tablet": "平板"}
prepared = []
for p in products:
    k = keys.get(f"sogi|{p['kind']}|{p['list_name']}") or {}
    brand = brand_of(p["list_name"])
    display = k.get("display") or p["list_name"]
    conn = k.get("connectivity")
    raw_display = display
    if p["kind"] == "wearable":
        display = re.sub(r"\s*\(?\b(Wi-?Fi|LTE)\b\)?|\s*\(?藍牙版\)?", "", display)
        kind = wearable_kind(p["class"], display)
    else:
        kind = KIND[p["kind"]]
        display = re.sub(r"\s(\d{2,4}\s*GB|[12]\s*TB)\s*(?=\(|$)", " ", display)        # 品名中間的容量:iPad Pro 12.9 Wi-Fi 64GB (2018)
    name = standard_name(brand, display)
    if p["launch"] and (brand, nkey(f"{name} ({p['launch'][:4]})")) in ep_years:
        name = f"{name} ({p['launch'][:4]})"
    if p["kind"] == "tablet" and brand in ("Apple", "Samsung") and k.get("hub"):
        name = k["hub"]["name"] if brand == "Apple" else "Galaxy " + k["hub"]["name"].replace("Galaxy ", "")   # iPad 用世代 / 晶片的寫法(手機王寫年份)
    prepared.append((p, k, brand, kind, name, conn, raw_display))
sogi_markers = markers_of((x[2], x[4]) for x in prepared if x[0]["kind"] == "cellphone")
for p, k, brand, kind, name, conn, raw_display in prepared:
    row = place("sogi", brand, kind, name, sogi_markers if p["kind"] == "cellphone" else {})
    row["sogi"].append(p["list_name"])
    if p["launch"] and (not row["launch"] or p["launch"] < row["launch"]):
        row["launch"] = p["launch"]
    for c in p["colors"]:
        if c not in row["colors"]:
            row["colors"].append(c)
    for v in p["variants"]:
        label = v["label"]
        if p["kind"] == "wearable":
            blob = f"{label} {raw_display}"
            net = "LTE" if re.search(r"LTE|4G|5G|行動網路", blob) else ("藍牙" if re.search(r"Bluetooth|Wi-?Fi|GPS|藍牙", blob) else "")
            rest = re.sub(r"\b(4G|5G)\b|\bLTE\b|Bluetooth|Wi-?Fi|\bGPS\b|藍牙版?", "", label).strip(" -")
            rest = re.sub(r"\s+", " ", rest)
            if re.fullmatch(r"\d+(\.\d+)?\s*mm", rest) and rest.replace(" ", "") in name.replace(" ", ""):
                rest = ""
            spec = " ".join(x for x in (rest, net) if x) or "單一規格"
        else:
            if not label.strip() and k.get("capacityRaw"):     # 舊機型一個容量一個商品:容量與 RAM 寫在品名上
                label = (f"{k['ramGb']}GB/" if k.get("ramGb") else "") + k["capacityRaw"].upper()
            spec = spec_of(label, p["rom"], conn)
        if spec not in [x["spec"] for x in row["variants"]]:
            row["variants"].append({"spec": spec, "msrp": v["msrp"]})
    if not p["variants"] and p["kind"] != "wearable":
        ram = re.findall(r"\d+", p["ram"])
        for rom in [x.strip().replace(" ", "") for x in p["rom"].split(",") if x.strip()]:
            spec = spec_of((f"{ram[0]}GB/" if len(ram) == 1 else "") + rom, "", conn)
            if spec not in [x["spec"] for x in row["variants"]]:
                row["variants"].append({"spec": spec, "msrp": None})
    if SPECIAL.search(p["list_name"]) and "特別版 / 套組" not in row["note"]:
        row["note"].append("特別版 / 套組")

# ── 2. 創宇(查價系統的機型表):對得上的補 RAM 等規格;對不上的是舊機型,補進來 ──
HUB_BRAND = {"紅米": "小米", "小米": "小米", "SONY": "Sony", "NOKIA": "Nokia"}


def hub_name(hk):
    raw, brand = hk["name"], hk["brand"]
    prefix = {"紅米": "Redmi ", "小米": "Xiaomi ", "POCO": "POCO "}.get(brand, "")
    raw = raw.replace("_LTE", " 4G").replace("_", " ").replace("/WIFI", "")
    if brand == "Apple":
        raw = re.sub(r"^iPhone (\d+)\+$", r"iPhone \1 Plus", raw)
        raw = re.sub(r"^iPhone SE(\d)$", r"iPhone SE \1", raw)
    if brand == "Samsung":
        raw = re.sub(r"Galaxy Note (\d+)", r"Galaxy Note\1", raw)
        raw = re.sub(r"Galaxy Z (Fold|Flip) (\d)(?!G)", r"Galaxy Z \1\2", raw)
    if brand == "OPPO":
        raw = "Reno 十倍變焦版" if "倍變焦" in raw else raw
        raw = re.sub(r"Reno (\d+)", r"Reno\1", raw)
        raw = re.sub(r"Reno(\d+)\s*([FZT])\b", r"Reno\1 \2", raw)
    if brand == "ASUS":
        raw = raw.replace("ZenFone", "Zenfone")
    if brand == "SHARP":
        raw = re.sub(r"AQUOS (sense|wish|zero) ?(\d+\w*)", r"AQUOS \1\2", raw).replace("AQUOS R5G 5G", "AQUOS R5G")
    if brand == "vivo":
        raw = re.sub(r"^(Y\d+)\((20\d\d)\) 5G$", r"\1 5G (\2)", raw)
    if brand == "realme":
        raw = re.sub(r"^(\d+)X\b", r"\1x", raw)
    return standard_name(HUB_BRAND.get(brand, brand), prefix + raw)


hub_rows = [(hk, HUB_BRAND.get(hk["brand"], hk["brand"]), hub_name(hk)) for hk in hub_keys]
hub_markers = markers_of((b, n) for _, b, n in hub_rows)
for hk, brand, name in hub_rows:
    form = hk["form"]
    if (hk["brand"] == "HUAWEI" and "MatePad" in hk["name"]) or (hk["brand"] == "NOKIA" and hk["name"] == "T21"):
        form = "tablet"
    row = place("hub", brand, {"phone": "手機", "tablet": "平板"}[form], name, hub_markers)
    row["hub"].append(hk["brand"] + "|" + hk["name"])
    v = hub_models.get(hk["brand"] + "|" + hk["name"], {"variants": []})
    have = {re.sub(r"^\d+\+", "", x["spec"]) for x in row["variants"]} | {x["spec"] for x in row["variants"]}
    for storage, ram, conn in v["variants"]:
        t = f"{ram}+{storage}" if ram else storage
        if form == "tablet" and conn:
            t += " WiFi" if conn == "wifi" else " 插卡"
        if t not in have and re.sub(r"^\d+\+", "", t) not in have:
            row["variants"].append({"spec": t, "msrp": None})
            have.add(t)
    if SPECIAL.search(name) and "特別版 / 套組" not in row["note"]:
        row["note"].append("特別版 / 套組")

# ── 3. 比價王:對得上的記來源;兩邊都沒有的才補進來 ──
EP_KIND = {"mobile": "手機", "pad": "平板", "market": None}
EP_SAME = {"Xiaomi Leica Leitzphone": "Leica Leitzphone powered by Xiaomi", "三星智慧手環 Fit3": "Galaxy Fit3",
           "Xiaomi Pad 8 Pro 柔光螢幕": "Xiaomi Pad 8 Pro 奈米柔光螢幕版", "HUAWEI Watch GT2 Pro 智慧手錶": "HUAWEI Watch GT2 Pro"}
ep = []
for lib in ("mobile", "pad", "market"):
    f = S + f"web/eprice_{lib}.json"
    if not os.path.exists(f):
        continue
    for full, _pid in json.load(open(f, encoding="utf-8")):
        if re.search(r"鍵盤|套裝|連接線|轉接器|充電器|AirTag|Pencil|HomePod|電視盒|歡迎電洽", full):
            continue                                        # 配件、組合包、店家自己寫的品名:不是機型
        k = keys.get(f"eprice|{lib}|{full}") or {}
        brand = brand_of(full)
        display = k.get("display") or full
        display = re.sub(r"\s*[（(][^）)]*(鋁金屬|鈦金屬|藍牙版|Wi-?Fi|5G|柔光)[^）)]*[）)]", "", display)
        display = re.sub(r"^(APPLE|SAMSUNG|HUAWEI|Samsung|Xiaomi)\s+(?=(Apple|SAMSUNG|Galaxy|AirPods|Watch|HUAWEI|三星|Xiaomi|Redmi|紅米))", "", display)
        display = re.sub(r"^(Apple )?Watch (\d+)\b", r"Apple Watch Series \2", display)
        display = re.sub(r"^(Apple )?Watch S(\d+)\b", r"Apple Watch Series \2", display)
        display = re.sub(r"^(Apple )?Watch SE(\d)\b", r"Apple Watch SE \2", display)
        name = standard_name(brand, display)
        if lib == "pad" and brand in ("Apple", "Samsung") and k.get("hub"):
            name = k["hub"]["name"] if brand == "Apple" else "Galaxy " + k["hub"]["name"].replace("Galaxy ", "")
        ep.append((lib, full, brand, name))
ep_markers = markers_of((b, n) for lib, _, b, n in ep if lib == "mobile")
for lib, full, brand, name in ep:
    if lib == "market":                                     # 穿戴:比價王只寫到系列(Apple Watch Series 11),手機王有分材質與尺寸 —— 有同系列的就不另外開一筆
        family = nkey(name)
        if any(b == brand and lk.startswith(family) for (b, lk) in list(slots)):
            for (b, lk), here in slots.items():
                if b == brand and lk.startswith(family):
                    for key in set(here.values()):
                        if full not in out[key]["eprice"]:
                            out[key]["eprice"].append(full)
            continue
    name = EP_SAME.get(name, name)
    base = SPECIAL.split(name)[0].strip() if SPECIAL.search(name) else ""
    if base and slots.get((brand, loose(base))):
        for key in set(slots[(brand, loose(base))].values()):
            out[key]["eprice"].append(full)
        continue
    if not slots.get((brand, loose(name))):                 # 這邊沒有:看是不是哪一筆名稱的開頭(Nokia 215 4G / Nokia 215 4G (2024))
        longer = {kk for (b, lk), here in slots.items() if b == brand and lk.startswith(loose(name)) and len(loose(name)) >= 8 for kk in here.values()}
        if len(longer) == 1:
            out[next(iter(longer))]["eprice"].append(full)
            continue
    row = place("eprice", brand, EP_KIND[lib] or wearable_kind("", name), name, ep_markers if lib == "mobile" else {})
    row["eprice"].append(full)

for row in out.values():
    if not row["sogi"] and not row["eprice"] and row["hub"]:
        row["note"].append("舊機型(只有創宇有)")
    if not row["sogi"] and not row["hub"] and row["eprice"]:
        row["note"].append("只有比價王有")

# ── 4. POS 現有的標準型錄:對上的記下現在的名稱(之後改名用),對不上的補進來 ──
POS_BRAND = {"apple": "Apple", "samsung": "Samsung", "google": "Google", "oppo": "OPPO", "vivo": "vivo", "realme": "realme",
             "xiaomi": "小米", "redmi": "小米", "asus": "ASUS", "sony": "Sony"}
alias = {}
for key, row in out.items():
    for text in [row["name"]] + [h.split("|", 1)[1] for h in row["hub"]] + row["sogi"] + row["eprice"]:
        alias.setdefault((row["brand"], nkey(re.sub(r"\b[45]G\b", "", text))), key)
SAME = {("apple", "iPhone 10"): "iPhone X", ("apple", "iPhone 10 R"): "iPhone XR", ("apple", "iPhone 10 S"): "iPhone XS",
        ("apple", "iPhone 10 S Max"): "iPhone XS Max", ("apple", "iPhone 17 Air"): "iPhone Air", ("apple", "iPad 11 (A16)"): "iPad 11",
        ("apple", "iPad Air 5 (M1)"): "iPad Air 5", ("apple", "iPad mini 7 (A17 Pro)"): "iPad mini 7"}
pos_total = matched = 0
for f in sorted(glob.glob(POS + "/taiwan_catalog/*.json")) + [POS + "/phone_models_extra.json"]:
    for m in json.load(open(f, encoding="utf-8"))["models"]:
        pos_total += 1
        brand = POS_BRAND.get(m["brand"], m["brand"])
        gen = "" if m.get("generation") in (None, "") else str(m["generation"])
        current = " ".join(x for x in (m.get("series") or "", gen, m.get("model_suffix") or "") if x)
        series, suffix = (m.get("series") or "").strip(), (m.get("model_suffix") or "").strip()
        tight = bool(re.search(r"Galaxy (S|A|M|Note|Z Fold|Z Flip|Tab S|Tab A|Watch)$|^Reno$|^Find X$", series))
        head = (series + ("" if tight else " ") + gen) if gen else series
        attach = bool(re.match(r"^(\+|[a-z]\b|[A-Z]\b(?! ))", suffix)) and suffix not in ("Pro", "Max", "Air")
        plain = (head + ("" if attach else " ") + suffix).strip() if suffix else head.strip()
        plain = re.sub(r"(Apple Watch) (\d+)", r"\1 Series \2", plain).replace("Apple Watch SE 第2代", "Apple Watch SE 2")
        plain = plain.replace("小米平板", "Xiaomi Pad").replace("小米手環", "Xiaomi 手環").replace("小米 ", "Xiaomi ")
        pos_name = standard_name(brand, plain)
        tries = [SAME.get((m["brand"], current), current), pos_name]
        tries += [re.sub(r"^(小米|Redmi|Xiaomi|realme)\s*", "", current), "Xiaomi " + re.sub(r"^小米\s*", "", current),
                  re.sub(r"(Apple Watch) (\d+)", r"\1 Series \2", current), re.sub(r"吋 \((M\d)\)", r" \1", current)]
        key = next((alias[(brand, nkey(re.sub(r"\b[45]G\b", "", t)))] for t in tries if (brand, nkey(re.sub(r"\b[45]G\b", "", t))) in alias), None)
        if key is not None:
            matched += 1
            out[key]["pos_name"] = current
            if not out[key]["colors"] and m.get("colors"):
                out[key]["colors"] = list(m["colors"])
            continue
        kind = m.get("kind") or "手機"
        row = out.setdefault(("pos", brand, nkey(current)), {"brand": brand, "kind": kind, "name": pos_name, "launch": "", "variants": [], "colors": [],
                                                            "sogi": [], "eprice": [], "hub": [], "pos_name": "", "note": []})
        row["pos_name"] = current
        row["note"].append("只有 POS 原本有")
        row["variants"] = [{"spec": c, "msrp": m.get("list_price")} for c in (m.get("capacities") or [])]
        row["colors"] = list(m.get("colors") or [])

def spec_order(v):
    """規格照容量、RAM 由小到大排;讀不出容量的排後面。"""
    t = v["spec"]
    m = re.search(r"(?:(\d+)\+)?(\d+)\s*(GB|TB)", t)
    if not m:
        return (1, 0, 0, t)
    size = int(m.group(2)) * (1024 if m.group(3) == "TB" else 1)
    return (0, size, int(m.group(1) or 0), t)


for row in out.values():
    row["variants"].sort(key=spec_order)
ORDER = {"手機": 0, "平板": 1, "手錶": 2, "手環": 3, "耳機": 4, "其他穿戴": 5}
for row in out.values():
    row.pop("_many", None)
rows = sorted(out.values(), key=lambda r: (r["brand"].lower(), ORDER.get(r["kind"], 9), -int((r["launch"] or "0000/00").replace("/", "")), r["name"].lower()))
json.dump(rows, open(S + "standard_draft.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("草稿共", len(rows), "個機型 | 手機王頁數", len(products), "| POS 現有", pos_total, "對上", matched)
print("依類型", dict(collections.Counter(r["kind"] for r in rows)))
print("有顏色", sum(1 for r in rows if r["colors"]), "| 有原廠售價", sum(1 for r in rows if any(v["msrp"] for v in r["variants"])), "| 有上市年月", sum(1 for r in rows if r["launch"]))
print("來源", {"手機王": sum(1 for r in rows if r["sogi"]), "比價王": sum(1 for r in rows if r["eprice"]), "創宇": sum(1 for r in rows if r["hub"])})
print("註記", dict(collections.Counter(n for r in rows for n in r["note"])))
print("依品牌", collections.Counter(r["brand"] for r in rows).most_common(30))
