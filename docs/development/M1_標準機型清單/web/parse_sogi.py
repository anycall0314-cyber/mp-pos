"""把抓下來的手機王商品頁讀成一筆一筆的資料:名稱、上市年月、每一種版本(容量 / RAM 或尺寸)與原廠售價、機身顏色、裝置分類。"""
import html, json, os, re

S = os.path.dirname(os.path.abspath(__file__)) + "/"
num = lambda s: int(re.sub(r"[^\d]", "", s)) if re.search(r"\d", s or "") else None
clean = lambda s: re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def parse(text):
    name = clean((re.search(r"<h1[^>]*>([\s\S]*?)</h1>", text) or [None, ""])[1])
    launch = (re.search(r"上市日期：\s*(\d{4}/\d{2})", text) or [None, ""])[1]
    variants = []
    for m in re.finditer(r'event-page-element="版本空機"[^>]*href="([^"]*)">\s*<div>([^<]*)</div>\s*<div class="lead[^"]*">([^<]*)</div>\s*(?:<small[^>]*>\s*原廠售價：([^<]*)</small>)?', text):
        variants.append({"label": clean(m.group(2)).strip("()"), "low": num(m.group(3)), "msrp": num(m.group(4) or "")})
    specs = {}
    for m in re.finditer(r'<th class="active"[^>]*>([^<]+)</th>\s*<td>([\s\S]*?)</td>', text):
        specs.setdefault(clean(m.group(1)), clean(m.group(2)))
    colors = [c.strip() for c in re.split(r"[,、，]", specs.get("機身顏色", "")) if c.strip()]
    return {"name": name, "launch": launch, "variants": variants, "colors": colors, "class": specs.get("裝置分類", ""),
            "screen": specs.get("主螢幕尺寸", ""), "ram": specs.get("RAM記憶體", ""), "rom": specs.get("ROM儲存空間", ""),
            "os": specs.get("作業系統與版本", "")}


if __name__ == "__main__":
    out, missing = [], 0
    for kind in ("cellphone", "tablet", "wearable"):
        for name, path in json.load(open(S + f"sogi_{kind}.json", encoding="utf-8")):
            pid = path.rstrip("/").split("/")[-1]
            f = S + "sogi/" + pid + ".html"
            if not os.path.exists(f):
                missing += 1
                continue
            row = parse(open(f, encoding="utf-8", errors="replace").read())
            row.update({"id": pid, "kind": kind, "list_name": name, "path": path})
            out.append(row)
    json.dump(out, open(S + "sogi_products.json", "w", encoding="utf-8"), ensure_ascii=False)
    print("讀了", len(out), "頁;還沒抓到的", missing)
