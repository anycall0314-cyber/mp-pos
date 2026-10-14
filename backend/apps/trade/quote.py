"""報價連結的那一頁:給沒用這套 POS 的同行用手機打開(多半從 LINE 點進來)看現在的價(owner 2026-10-14)。

- **一個同行一條**(紅隊:一條大家共用的會被轉給零售客人與對手,關掉又連熟客一起斷)。看到的跟他在平台內看到的一樣:
  中古機(他看得到的話)與按數量賣的商品,價是**他的**價(折數照他的);不出現成本、序號、門市、別人的價。
- 中古機照型號一段一段:用同一格價目、同一個價的合成一行(「A 級 沒備註 11,800 有貨」);獨立定價的一台一行,帶編號(買家在 LINE 講得清楚是哪一台)。
- 每一行一顆「複製」:複製的那一句帶賣家、型號、哪一格、價、編號與報價時間,貼到 LINE 就是一張報價(紅隊:看完回 LINE 憑記憶講,講錯就是一台上萬的糾紛)。
- 數量:賣家設定「顯示數量」才寫幾台,不然只寫有貨 / 缺貨(跟平台內同一條規則)。
- 頁面本身不帶任何外部資源、不給搜尋引擎收錄、不快取。
"""
import secrets
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from django.utils.html import escape

from . import listing, partners, pricing
from .base import TradeError, setting_of
from .models import TradePartner, TradeQuoteLink

PER_MINUTE = 30


# ── 連結本身 ──────────────────────────────────────────────────────────────────
def _token() -> str:
    return secrets.token_urlsafe(24)          # 32 個字、隨機(網址裡這一串就是鑰匙)


def change(partner: TradePartner, user, do: str) -> TradeQuoteLink:
    """開(第一次開會建一條)、關、換一條(舊的立刻不能看)。"""
    if do not in ("on", "off", "new"):
        raise TradeError("要做什麼不對")
    link = TradeQuoteLink.objects.filter(partner=partner).first()
    if link is None:
        if do == "off":
            raise TradeError("這個同行還沒有報價連結")
        return TradeQuoteLink.objects.create(tenant=partner.tenant, partner=partner, token=_token(), created_by=user)
    if do == "new":
        link.token, link.is_on, link.opened_at, link.open_count, link.window_start, link.window_count = _token(), True, None, 0, None, 0
    else:
        link.is_on = do == "on"
    link.save()
    return link


def find(token) -> TradeQuoteLink | None:
    if not isinstance(token, str) or not 20 <= len(token) <= 64:
        return None
    return TradeQuoteLink.objects.filter(token=token).select_related("partner__tenant").first()


def hit(link: TradeQuoteLink) -> bool:
    """算一次「看過」、回這一次可不可以(每分鐘最多 `PER_MINUTE` 次)。鎖著那一列算:同時來的每一次拿到的是自己那一次的次數。"""
    now = timezone.now()
    with transaction.atomic():
        row = TradeQuoteLink.objects.select_for_update().filter(pk=link.pk).first()
        if row is None:
            return False
        if row.window_start is None or row.window_start <= now - timedelta(minutes=1):
            row.window_start, row.window_count = now, 1
        else:
            row.window_count += 1
        row.open_count, row.opened_at = row.open_count + 1, now
        row.save(update_fields=["window_start", "window_count", "open_count", "opened_at", "updated_at"])
        return row.window_count <= PER_MINUTE


def data_of(link: TradeQuoteLink | None) -> dict | None:
    """給賣家畫面看的(只有管理員看得到):連結的那一段、開著沒、上次看、看過幾次。"""
    if link is None:
        return None
    return {"path": f"/api/trade/quote/{link.token}/", "on": link.is_on, "count": link.open_count,
            "opened_at": timezone.localtime(link.opened_at).isoformat(timespec="minutes") if link.opened_at else ""}


# ── 那一頁 ──────────────────────────────────────────────────────────────────


def _money(value) -> str:
    return f"{int(value):,}"


def _stock_text(setting, n: int) -> str:
    if n <= 0:
        return "缺貨"
    return f"{n} 台" if setting.show_qty else "有貨"


def sections(seller, partner) -> list[dict]:
    """這個同行現在看得到的:[{name, lines: [{label, price, stock, code}]}],照型號排。"""
    setting = setting_of(seller)
    see_units, see_goods = partners.can_see(setting, partner)
    out = []
    if see_units:
        units = list(listing.units_for_sale(seller).select_related("serial__product").order_by("serial__product__name", "price", "id"))
        rules = pricing.rules_of(seller, {u.serial.product_id for u in units})
        groups: dict[int, dict] = {}
        for unit in units:
            serial = unit.serial
            product = serial.product
            section = groups.setdefault(product.id, {"name": product.name, "merged": {}, "single": []})
            if unit.own_price:
                bits = [f"{serial.condition_grade} 級" if serial.condition_grade else "",
                        f"電池 {serial.battery_health}%" if serial.battery_health is not None else "", (serial.condition_note or "").strip()]
                section["single"].append({"label": " ".join(b for b in bits if b), "price": unit.price, "stock": "1 台", "code": f"U{unit.id}"})
                continue
            rule = pricing.best(rules.get(product.id, []), serial)
            label = pricing.text_of(rule) if rule is not None else (f"{serial.condition_grade} 級" if serial.condition_grade else "")
            key = (label, unit.price)
            section["merged"][key] = section["merged"].get(key, 0) + 1
        for section in groups.values():
            lines = [{"label": label, "price": price, "stock": _stock_text(setting, n), "code": ""}
                     for (label, price), n in sorted(section["merged"].items(), key=lambda kv: (-kv[0][1], kv[0][0]))]
            lines += sorted(section["single"], key=lambda line: -line["price"])
            out.append({"name": section["name"], "lines": lines})
    if see_goods:
        offers = [o for o in listing.products_for_sale(seller).order_by("product__category__sort_order", "product__name", "id")
                  if not listing.is_unit_product(o.product)]
        left = listing.available_qty(seller, [o.product_id for o in offers])
        for offer in offers:
            price = listing.price_for(offer, partner)
            if price is None:
                continue
            n = left.get(offer.product_id, 0)
            out.append({"name": offer.product.name, "lines": [
                {"label": offer.product.spec or "", "price": price, "code": "",
                 "stock": ("缺貨" if n <= 0 else (f"{n} 個" if setting.show_qty else "有貨"))}]})
    out.sort(key=lambda s: s["name"])
    return out


STYLE = """
:root { --bg:#f6f7f9; --card:#fff; --text:#1d2129; --dim:#6b7280; --line:#e5e7eb; --accent:#2563eb; --warn:#b45309; }
@media (prefers-color-scheme: dark) { :root { --bg:#111418; --card:#1b1f24; --text:#e8eaed; --dim:#9aa0a6; --line:#2c3138; --accent:#6ea8ff; --warn:#f0b35a; } }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--text); font:17px/1.5 -apple-system, "PingFang TC", "Noto Sans TC", sans-serif; }
header { padding:16px; background:var(--card); border-bottom:1px solid var(--line); }
h1 { margin:0 0 4px; font-size:21px; }
.meta { color:var(--dim); font-size:15px; overflow-wrap:anywhere; }
.search { position:sticky; top:0; padding:10px 16px; background:var(--bg); border-bottom:1px solid var(--line); }
.search input { width:100%; min-height:44px; padding:0 12px; font:inherit; color:var(--text); background:var(--card); border:1px solid var(--line); border-radius:10px; }
main { padding:8px 16px 32px; }
section { margin:12px 0; background:var(--card); border:1px solid var(--line); border-radius:12px; }
h2 { margin:0; padding:12px 14px 6px; font-size:18px; }
.line { display:flex; flex-wrap:wrap; align-items:center; gap:4px 10px; padding:10px 14px; border-top:1px solid var(--line); }
.label { flex:1 1 12em; min-width:0; overflow-wrap:anywhere; }
.code { color:var(--dim); font-size:14px; }
.price { font-weight:700; white-space:nowrap; }
.stock { color:var(--dim); white-space:nowrap; }
.stock.out { color:var(--warn); }
button { min-height:40px; padding:0 14px; font:inherit; font-size:15px; color:var(--accent); background:transparent; border:1px solid var(--accent); border-radius:999px; }
footer { padding:0 16px 32px; color:var(--dim); font-size:14px; }
.empty { padding:24px 16px; color:var(--dim); }
"""

SCRIPT = """
document.querySelector('.search input').addEventListener('input', function (e) {
  var q = e.target.value.trim().toLowerCase();
  document.querySelectorAll('section').forEach(function (s) {
    var hit = s.getAttribute('data-q').indexOf(q) >= 0;
    s.style.display = q === '' || hit ? '' : 'none';
  });
});
document.querySelectorAll('button[data-copy]').forEach(function (b) {
  b.addEventListener('click', function () {
    var text = b.getAttribute('data-copy');
    var done = function () { b.textContent = '已複製'; setTimeout(function () { b.textContent = '複製'; }, 1500); };
    if (navigator.clipboard && navigator.clipboard.writeText) { navigator.clipboard.writeText(text).then(done, function () { fallback(text); done(); }); }
    else { fallback(text); done(); }
  });
});
function fallback(text) {
  var t = document.createElement('textarea'); t.value = text; document.body.appendChild(t); t.select();
  try { document.execCommand('copy'); } catch (e) {} document.body.removeChild(t);
}
"""


def _page(title: str, body: str) -> str:
    return ("<!doctype html><html lang='zh-Hant'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'><meta name='robots' content='noindex, nofollow'>"
            f"<title>{escape(title)}</title><style>{STYLE}</style></head><body>{body}</body></html>")


def closed_page(message: str) -> str:
    return _page("報價", f"<div class='empty'>{escape(message)}</div>")


def render(seller, partner, now=None) -> str:
    """整頁 HTML。每一段的 `data-q` 是型號與每一行的字(搜尋用)。"""
    setting = setting_of(seller)
    now = timezone.localtime(now or timezone.now())
    stamp = now.strftime("%m/%d %H:%M")
    found = sections(seller, partner)
    parts = []
    for section in found:
        rows = []
        for line in section["lines"]:
            words = " ".join(w for w in (section["name"], line["label"], _money(line["price"]), line["code"] and f"編號 {line['code']}") if w)
            copy = f"{seller.name} {words}({stamp} 報價)"
            out = " out" if line["stock"] == "缺貨" else ""
            rows.append(
                "<div class='line'>"
                + (f"<span class='label'>{escape(line['label'])}{f' <span class=code>編號 {escape(line['code'])}</span>' if line['code'] else ''}</span>"
                   if line["label"] or line["code"] else "")
                + 
                f"<span class='price'>{_money(line['price'])}</span><span class='stock{out}'>{escape(line['stock'])}</span>"
                f"<button type='button' data-copy='{escape(copy)}'>複製</button></div>")
        q = " ".join([section["name"], *(line["label"] for line in section["lines"])]).lower()
        parts.append(f"<section data-q='{escape(q)}'><h2>{escape(section['name'])}</h2>{''.join(rows)}</section>")
    contact = " · ".join(x for x in (setting.contact.strip(), setting.pay_note.strip()) if x)
    body = (
        f"<header><h1>{escape(seller.name)} 報價</h1>"
        f"<div class='meta'>給 {escape(partner.name)} · {stamp}</div>"
        + (f"<div class='meta'>{escape(contact)}</div>" if contact else "")
        + "</header>"
        "<div class='search'><input type='search' placeholder='找型號' aria-label='找型號'></div>"
        f"<main>{''.join(parts) or '<div class=empty>目前沒有報價</div>'}</main>"
        "<footer>以下單為準</footer>"
        f"<script>{SCRIPT}</script>")
    return _page(f"{seller.name} 報價", body)
