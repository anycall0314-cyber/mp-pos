"""報價連結的那一頁:給沒用這套 POS 的同行用手機打開(多半從 LINE 點進來)看現在的價(owner 2026-10-14)。

- **一個同行一條**(紅隊:一條大家共用的會被轉給零售客人與對手,關掉又連熟客一起斷)。看到的跟他在平台內看到的一樣:
  中古機(他看得到的話)與按數量賣的商品,價是**他的**價(折數照他的);不出現成本、序號、門市、別人的價。
- 中古機照型號一段一段、**一台一行**:成色、電池、備註(機況)、價、編號(買家在 LINE 講得清楚是哪一台)。
- 每一行一顆「複製」:複製的那一句帶賣家、型號、哪一格、價、編號與報價時間,貼到 LINE 就是一張報價(紅隊:看完回 LINE 憑記憶講,講錯就是一台上萬的糾紛)。
- 數量:賣家設定「顯示數量」才寫幾台,不然只寫有貨 / 缺貨(跟平台內同一條規則)。
- 頁面本身不帶任何外部資源、不給搜尋引擎收錄、不快取。
"""
import secrets
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from django.utils.html import escape

from . import listing, partners
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
        # 中古機一台一行:成色、電池、備註(機況)、價、編號(owner 2026-10-14:「中古機要能看到品項,電池,備註打的機況」;
        # 合成一行的話上架 300 台只看得到幾行)
        grade_rank = {g: i for i, g in enumerate(["S", "A", "B", "C", "D", ""])}
        units = listing.units_for_sale(seller).select_related("serial__product").order_by("serial__product__name", "id")
        groups: dict[int, dict] = {}
        for unit in units:
            serial = unit.serial
            bits = [f"{serial.condition_grade} 級" if serial.condition_grade else "",
                    f"電池 {serial.battery_health}%" if serial.battery_health is not None else "", (serial.condition_note or "").strip()]
            groups.setdefault(serial.product_id, {"name": serial.product.name, "kind": "unit", "lines": []})["lines"].append({
                "label": " ".join(b for b in bits if b), "price": unit.price, "stock": "", "code": f"U{unit.id}",
                "grade": serial.condition_grade or "", "battery": serial.battery_health,
                "rank": (grade_rank.get(serial.condition_grade, 9), -(serial.battery_health or 0), unit.price)})
        for section in groups.values():
            section["lines"].sort(key=lambda line: line.pop("rank"))
            out.append(section)
    if see_goods:
        offers = [o for o in listing.products_for_sale(seller).order_by("product__category__sort_order", "product__name", "id")
                  if not listing.is_unit_product(o.product)]
        left = listing.available_qty(seller, [o.product_id for o in offers])
        for offer in offers:
            price = listing.price_for(offer, partner)
            if price is None:
                continue
            n = left.get(offer.product_id, 0)
            out.append({"name": offer.product.name, "kind": "goods", "lines": [
                {"label": offer.product.spec or "", "price": price, "code": "", "grade": None, "battery": None,
                 "stock": ("缺貨" if n <= 0 else (f"{n} 個" if setting.show_qty else "有貨"))}]})
    out.sort(key=lambda s: s["name"])
    return out


STYLE = """
:root { --bg:#f6f7f9; --card:#fff; --text:#1d2129; --dim:#6b7280; --line:#e5e7eb; --accent:#2563eb; --warn:#b45309; --on:#dbeafe; }
@media (prefers-color-scheme: dark) { :root { --bg:#111418; --card:#1b1f24; --text:#e8eaed; --dim:#9aa0a6; --line:#2c3138; --accent:#6ea8ff; --warn:#f0b35a; --on:#1e3a5f; } }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--text); font:17px/1.5 -apple-system, "PingFang TC", "Noto Sans TC", sans-serif; padding-bottom:84px; }
header { padding:14px 16px; background:var(--card); border-bottom:1px solid var(--line); }
h1 { margin:0 0 4px; font-size:21px; }
.meta { color:var(--dim); font-size:15px; overflow-wrap:anywhere; }
.bar { display:flex; flex-direction:column; gap:8px; padding:10px 16px; background:var(--bg); border-bottom:1px solid var(--line); }
.bar input { min-height:44px; padding:0 12px; font:inherit; color:var(--text); background:var(--card); border:1px solid var(--line); border-radius:10px; min-width:0; }
.row { display:flex; flex-wrap:wrap; align-items:center; gap:6px; }
.row > button { min-width:44px; padding:0 8px; }
.row .tag { color:var(--dim); font-size:15px; min-width:2.4em; }
.price { display:flex; align-items:center; gap:6px; flex:1 1 14em; }
.price input { flex:1 1 0; width:0; }
button { min-height:40px; padding:0 12px; font:inherit; font-size:15px; color:var(--accent); background:var(--card); border:1px solid var(--accent); border-radius:999px; }
button.on { background:var(--on); font-weight:700; }
.sum { justify-content:space-between; color:var(--dim); font-size:15px; }
main { padding:8px 16px 16px; }
section { margin:10px 0; background:var(--card); border:1px solid var(--line); border-radius:12px; overflow:hidden; }
.head { display:flex; flex-wrap:wrap; align-items:center; gap:2px 10px; width:100%; padding:12px 14px; text-align:left; color:var(--text); background:var(--card); border:0; border-radius:0; min-height:56px; }
.head .name { font-size:18px; font-weight:700; flex:1 1 12em; }
.head .n { color:var(--dim); font-size:15px; white-space:nowrap; }
.head .chev { color:var(--accent); font-size:22px; line-height:1; transition:transform .15s; }
section.open .head .chev { transform:rotate(90deg); }
.head .grades { flex:1 1 100%; color:var(--dim); font-size:15px; overflow-wrap:anywhere; }
h2 { margin:0; padding:12px 14px 6px; font-size:18px; }
.line { display:grid; grid-template-columns:1fr auto auto; align-items:center; gap:4px 10px; padding:10px 14px; border-top:1px solid var(--line); }
.line .stock { grid-column:2; }
.label { min-width:0; overflow-wrap:anywhere; }
.code { display:block; }
.code { color:var(--dim); font-size:14px; }
.pr { font-weight:700; white-space:nowrap; }
.stock { color:var(--dim); white-space:nowrap; }
.stock.out { color:var(--warn); }
.none { padding:8px 4px; color:var(--dim); font-size:15px; }
.cart { position:fixed; left:0; right:0; bottom:0; z-index:3; display:flex; align-items:center; gap:10px; padding:12px 16px; background:var(--card); border-top:1px solid var(--line); }
.cart .t { flex:1; font-weight:700; }
footer { padding:0 16px 24px; color:var(--dim); font-size:14px; }
.empty { padding:24px 16px; color:var(--dim); }
[hidden] { display:none !important; }
"""

SCRIPT = """
(function () {
  var $ = function (s, el) { return (el || document).querySelector(s); };
  var $$ = function (s, el) { return Array.prototype.slice.call((el || document).querySelectorAll(s)); };
  var f = { q: '', g: {}, b: '', lo: null, hi: null };
  var picked = [];
  var money = function (n) { return n.toLocaleString('en-US'); };
  var num = function (v) { var t = String(v).replace(/[^0-9]/g, ''); return t === '' ? null : Number(t); };
  function okBattery(line) {
    if (!f.b) return true;
    var b = line.dataset.b === '' ? null : Number(line.dataset.b);
    if (b === null) return false;
    return f.b === '-79' ? b <= 79 : b >= Number(f.b);
  }
  function okPrice(line) {
    var p = Number(line.dataset.p);
    return (f.lo === null || p >= f.lo) && (f.hi === null || p <= f.hi);
  }
  function apply() {
    var grades = Object.keys(f.g).filter(function (k) { return f.g[k]; });
    var total = 0, shown = 0, hiddenModels = 0;
    $$('section.unit').forEach(function (sec) {
      var nameHit = f.q === '' || sec.dataset.name.indexOf(f.q) >= 0;
      var per = {}, n = 0;
      $$('.line', sec).forEach(function (line) {
        var hit = nameHit && (grades.length === 0 || grades.indexOf(line.dataset.g) >= 0) && okBattery(line) && okPrice(line);
        line.hidden = !hit;
        if (hit) {
          n += 1;
          var g = line.dataset.g || '-', p = Number(line.dataset.p);
          if (!per[g]) per[g] = { n: 0, lo: p, hi: p };
          per[g].n += 1; per[g].lo = Math.min(per[g].lo, p); per[g].hi = Math.max(per[g].hi, p);
        }
      });
      sec.hidden = n === 0;
      if (n === 0) { hiddenModels += 1; return; }
      shown += 1; total += n;
      $('.n', sec).textContent = n + ' 台';
      $('.grades', sec).textContent = ['S', 'A', 'B', 'C', 'D', '-'].filter(function (g) { return per[g]; }).map(function (g) {
        var x = per[g];
        return (g === '-' ? '' : g + ' ') + x.n + ' 台 ' + money(x.lo) + (x.hi > x.lo ? ' 起' : '');
      }).join(' · ');
    });
    $$('.goods .line').forEach(function (line) {
      var hit = (f.q === '' || line.dataset.t.indexOf(f.q) >= 0) && okPrice(line);
      line.hidden = !hit;
    });
    var goods = $('.goods');
    if (goods) goods.hidden = $$('.line', goods).every(function (l) { return l.hidden; });
    var active = f.q !== '' || grades.length > 0 || f.b !== '' || f.lo !== null || f.hi !== null;
    // 篩到只剩一個型號就直接展開
    if (shown === 1) $$('section.unit').forEach(function (sec) { if (!sec.hidden) open(sec, true); });
    $('#count').textContent = '符合 ' + total + ' 台';
    var none = $('#none');
    none.hidden = !(active && hiddenModels > 0);
    $('#none-n').textContent = hiddenModels;
    $('#clear').hidden = !active;
  }
  function open(sec, on) {
    sec.classList.toggle('open', on);
    $('.lines', sec).hidden = !on;
  }
  $$('section.unit .head').forEach(function (h) {
    h.addEventListener('click', function () { var sec = h.parentNode; open(sec, !sec.classList.contains('open')); });
  });
  $('#q').addEventListener('input', function (e) { f.q = e.target.value.trim().toLowerCase(); apply(); });
  $$('[data-g]', $('#grades')).forEach(function (b) {
    b.addEventListener('click', function () { f.g[b.dataset.g] = !f.g[b.dataset.g]; b.classList.toggle('on', f.g[b.dataset.g]); apply(); });
  });
  $$('[data-b]', $('#batteries')).forEach(function (b) {
    b.addEventListener('click', function () {
      f.b = f.b === b.dataset.b ? '' : b.dataset.b;
      $$('[data-b]', $('#batteries')).forEach(function (x) { x.classList.toggle('on', x.dataset.b === f.b); });
      apply();
    });
  });
  $('#lo').addEventListener('input', function (e) { f.lo = num(e.target.value); apply(); });
  $('#hi').addEventListener('input', function (e) { f.hi = num(e.target.value); apply(); });
  function clear() {
    f = { q: '', g: {}, b: '', lo: null, hi: null };
    $('#q').value = ''; $('#lo').value = ''; $('#hi').value = '';
    $$('.bar button.on').forEach(function (b) { b.classList.remove('on'); });
    apply();
  }
  $('#clear').addEventListener('click', clear);
  $('#none-clear').addEventListener('click', clear);
  // 加入 / 取消:底下一條「已選幾台、合計」,一次複製全部(紅隊:湊一批的人不用一台一台貼回 LINE)
  function cart() {
    var bar = $('.cart');
    bar.hidden = picked.length === 0;
    var sum = picked.reduce(function (a, b) { return a + Number(b.dataset.p); }, 0);
    $('.cart .t').textContent = '已選 ' + picked.length + ' · ' + money(sum);
  }
  $$('button[data-copy]').forEach(function (b) {
    b.addEventListener('click', function () {
      var line = b.closest('.line');
      var at = picked.indexOf(line);
      if (at >= 0) { picked.splice(at, 1); b.textContent = '加入'; b.classList.remove('on'); }
      else { picked.push(line); b.textContent = '取消'; b.classList.add('on'); }
      cart();
    });
  });
  $('#copy').addEventListener('click', function () {
    var sum = picked.reduce(function (a, b) { return a + Number(b.dataset.p); }, 0);
    var text = picked.map(function (l) { return $('button[data-copy]', l).getAttribute('data-copy'); }).join('\\n')
      + '\\n共 ' + picked.length + ' · ' + money(sum);
    var done = function () { $('#copy').textContent = '已複製'; setTimeout(function () { $('#copy').textContent = '複製'; }, 1500); };
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(done, function () { fallback(text); done(); });
    else { fallback(text); done(); }
  });
  function fallback(text) {
    var t = document.createElement('textarea'); t.value = text; document.body.appendChild(t); t.select();
    try { document.execCommand('copy'); } catch (e) {} document.body.removeChild(t);
  }
  apply();
})();
"""


def _page(title: str, body: str) -> str:
    return ("<!doctype html><html lang='zh-Hant'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'><meta name='robots' content='noindex, nofollow'>"
            f"<title>{escape(title)}</title><style>{STYLE}</style></head><body>{body}</body></html>")


def closed_page(message: str) -> str:
    return _page("報價", f"<div class='empty'>{escape(message)}</div>")


def _line(seller, section, line, stamp) -> str:
    words = " ".join(w for w in (section["name"], line["label"], _money(line["price"]), line["code"] and f"編號 {line['code']}") if w)
    copy = f"{seller.name} {words}({stamp} 報價)"
    out = " out" if line["stock"] == "缺貨" else ""
    battery = "" if line["battery"] is None else str(line["battery"])
    return (f"<div class='line' data-g='{escape(line['grade'] or '')}' data-b='{battery}' data-p='{int(line['price'])}'"
            f" data-t='{escape((section['name'] + ' ' + line['label']).lower())}'>"
            + (f"<span class='label'>{escape(line['label'])}{f' <span class=code>編號 {escape(line['code'])}</span>' if line['code'] else ''}</span>"
               if line["label"] or line["code"] else "")
            + f"<span class='pr'>{_money(line['price'])}</span>"
            + (f"<span class='stock{out}'>{escape(line['stock'])}</span>" if line["stock"] else "")
            + f"<button type='button' data-copy='{escape(copy)}'>加入</button></div>")


def render(seller, partner, now=None) -> str:
    """整頁 HTML。中古機一個型號一段、預設收起來(owner:「預設顯示把型號下方的所有明細先折疊起來」),型號那一列寫每個成色幾台、從多少起;
    上面一條篩選(找型號、成色、電池、價格)在手機上就篩;全新機與配件放最後「其他商品」那一段(成色 / 電池不會把它們藏起來)。"""
    setting = setting_of(seller)
    now = timezone.localtime(now or timezone.now())
    stamp = now.strftime("%m/%d %H:%M")
    found = sections(seller, partner)
    units = [s for s in found if s.get("kind") == "unit"]
    goods = [s for s in found if s.get("kind") != "unit"]
    parts = []
    for section in units:
        rows = "".join(_line(seller, section, line, stamp) for line in section["lines"])
        parts.append(f"<section class='unit' data-name='{escape(section['name'].lower())}'>"
                     f"<button type='button' class='head'><span class='name'>{escape(section['name'])}</span>"
                     f"<span class='n'>{len(section['lines'])} 台</span><span class='chev'>›</span><span class='grades'></span></button>"
                     f"<div class='lines' hidden>{rows}</div></section>")
    if goods:
        rows = "".join(_line(seller, section, {**line, "label": " ".join(x for x in (section["name"], line["label"]) if x)}, stamp)
                       for section in goods for line in section["lines"])
        parts.append(f"<section class='goods'><h2>其他商品</h2>{rows}</section>")
    contact = " · ".join(x for x in (setting.contact.strip(), setting.pay_note.strip()) if x)
    grade_buttons = "".join(f"<button type='button' data-g='{g}'>{g}</button>" for g in ("S", "A", "B", "C", "D"))
    battery_buttons = "".join(f"<button type='button' data-b='{v}'>{t}</button>" for v, t in (("95", "95↑"), ("90", "90↑"), ("85", "85↑"), ("80", "80↑"), ("-79", "79↓")))
    body = (
        f"<header><h1>{escape(seller.name)} 報價</h1>"
        f"<div class='meta'>給 {escape(partner.name)} · {stamp}</div>"
        + (f"<div class='meta'>{escape(contact)}</div>" if contact else "")
        + "</header>"
        "<div class='bar'><input id='q' type='search' placeholder='找型號' aria-label='找型號'>"
        + (f"<div class='row' id='grades'><span class='tag'>成色</span>{grade_buttons}</div>"
           f"<div class='row' id='batteries'><span class='tag'>電池</span>{battery_buttons}</div>" if units else "<div id='grades'></div><div id='batteries'></div>")
        + "<div class='row'><span class='tag'>價格</span><div class='price'><input id='lo' inputmode='numeric' placeholder='從'>–<input id='hi' inputmode='numeric' placeholder='到'></div></div>"
        "<div class='row sum'><span id='count'></span><button type='button' id='clear' hidden>清除</button></div></div>"
        f"<main>{''.join(parts) or '<div class=empty>目前沒有報價</div>'}"
        "<div class='none' id='none' hidden>另外 <span id='none-n'></span> 款不符合 <button type='button' id='none-clear'>清除</button></div></main>"
        "<footer>以下單為準</footer>"
        "<div class='cart' hidden><span class='t'></span><button type='button' id='copy'>複製</button></div>"
        f"<script>{SCRIPT}</script>")
    return _page(f"{seller.name} 報價", body)
