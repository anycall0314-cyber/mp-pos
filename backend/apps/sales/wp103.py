"""WP-103 三聯式發票機:把要印的東西排成一頁的文字,轉成機器收的位元組。

owner 2026-10-13:發票機是 WP-103,接 USB(Windows 認成 COM 埠);印的是三聯式收銀機發票 —— 整捲複寫紙、號碼已經印在紙上。
「現在設定的發票為電子收銀三聯式發票，屬於過渡型發票，之後未來還是會朝電子發票串接」→ 這裡只做最簡單夠用的:
伺服器把一頁排好、轉成位元組;接發票機的那台電腦用 Chrome 直接送進 COM 埠(畫面那一側在 `lib/serialPrinter.ts`)。

機器(原廠手冊 V1.03):九針撞擊式;一行半形 40 個字(一個中文字佔 2 個);直接送 BIG-5 的字就印;指令 ESC/POS 相容;
一頁預設 33 行(5.5 吋 = 一張發票的長度),`FF` = 印完跳到下一張的開頭。

紙(owner 給的樣張):框裡**已經印好**「日期:」「買受人:」(上面)與「銷售額:」「營業稅:」「總 計:」(下面),機器印的字要對著它們。
每一項印在第幾行、從第幾格開始(`ROWS`、`COLS_AT`)是從樣張的照片量的,**還沒有在實機上對過** ——
先印「行號測試」(每一行印自己的行號與格數的尺),拍照就知道印好的那幾個字各在第幾行、第幾格,再回來改這兩張表。
"""
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

# 一行最多印幾格(半形)。機器是 40;印滿 40 有的機器會自己多跳一行,所以留一格
LINE_COLS = 39
# 一頁幾行(一張發票的長度)
PAGE_LINES = 33
INIT = b"\x1b@"                    # ESC @:清掉機器裡還沒印的、回到預設
PAGE_LENGTH = b"\x1bC" + bytes([PAGE_LINES])   # ESC C n:一頁 n 行(預設就是 33;明講一次,不靠機器的預設)
LF = b"\n"
FF = b"\x0c"                       # 印完,跳到下一張的開頭

# ── 每一項印在第幾行(從機器的第一行算,1 開始)。照樣張的照片量的,實機對過之後改這裡 ──
ROWS = {
    "store": 1,          # 店名
    "address": 2,        # 郵遞區號-縣市-地址
    "tax_tel": 3,        # 統編:… TEL:…
    "date": 4,           # (印好的「日期:」後面)日期 時間 收銀機編號
    "buyer": 5,          # (印好的「買受人:」後面)買方統編;右邊 收銀員
    "doc_no": 7,         # 靠右:單號(交易序號)
    "items": 8,          # 品名從這一行開始
    "payments": 17,      # 付款方式從這一行開始,一種一行
    "subtotal": 22,      # (印好的「銷售額:」後面)
    "tax": 23,           # (印好的「營業稅:」後面)
    "total": 24,         # (印好的「總 計:」後面)
}
ITEM_ROWS = ROWS["payments"] - ROWS["items"]          # 品名最多幾行
# 「上面先空幾行」可以調的範圍(每一台機器紙的起始位置會差一點;記在那台電腦):最多空到「總計」剛好印在最後一行。
# 畫面那一側的上限(`frontend/src/lib/serialPrinter.ts` 的 `topMax`)要跟這裡一樣,有測試對
TOP_RANGE = (0, PAGE_LINES - ROWS["total"])
PAYMENT_ROWS = ROWS["subtotal"] - ROWS["payments"]    # 付款方式最多幾行
# ── 從第幾格開始印(0 開始)──
COLS_AT = {
    "text": 1,           # 店名、地址、品名、付款方式的名稱
    "after_label": 8,    # 印好的「日期:」「買受人:」後面
    "amount_label": 11,  # 印好的「銷售額:」等三個後面
    "right_edge": 32,    # 靠右的東西(單號、金額)的右邊界
}


class LayoutError(Exception):
    """這一張排不進一頁(品名或付款方式太多行)。不默默切掉:少印一行,發票上的金額就跟明細對不起來。"""


def char_cols(ch: str) -> int:
    """這個字在機器上佔幾格:BIG-5 兩個位元組的佔 2 格、一個位元組的 1 格;BIG-5 沒有的字會印成 `?`(1 格)。"""
    try:
        return len(ch.encode("big5"))
    except UnicodeEncodeError:
        return 1


def cols(text: str) -> int:
    return sum(char_cols(ch) for ch in text)


def encode(text: str) -> bytes:
    """轉成機器收的 BIG-5。機器沒有的字(簡體、表情符號…)印成 `?`,不讓一個字卡住整張發票。"""
    return b"".join(_encode_char(ch) for ch in text)


def _encode_char(ch: str) -> bytes:
    if ch in "\r\n\t\x0c\x1b":          # 不讓資料裡的控制字元變成機器的指令或多跳行
        return b" "
    try:
        return ch.encode("big5")
    except UnicodeEncodeError:
        return b"?"


def clean(text) -> str:
    """要印的字:去頭尾空白,中間的換行 / 定位字元當成一個空白。"""
    return " ".join(str(text or "").split())


def fit(text: str, width: int) -> str:
    """放不下就從後面切(不會切到半個中文字)。"""
    out, used = "", 0
    for ch in text:
        w = char_cols(ch)
        if used + w > width:
            break
        out, used = out + ch, used + w
    return out


def put(line: str, col: int, text: str) -> str:
    """在這一行的第 `col` 格放上這段字(前面補空白;後面原本有字就蓋過去)。超出一行的切掉。"""
    line = line + " " * max(0, col - cols(line))
    head = fit(line, col)
    head = head + " " * (col - cols(head))            # 切到半個中文字時補一格
    return fit(head + text, LINE_COLS)


def put_right(line: str, edge: int, text: str) -> str:
    """把這段字靠右放,右邊界在第 `edge` 格。"""
    return put(line, max(0, edge - cols(text)), text)


def money(value) -> str:
    """金額:整數(四捨五入)、千分位、前面一個 `$`(全站金額一律整數)。"""
    return f"${int(Decimal(str(value)).quantize(Decimal('1'), rounding=ROUND_HALF_UP)):,}"


def roc_stamp(when: datetime) -> str:
    """民國年/月/日 時:分(發票上的日期)。"""
    return f"{when.year - 1911}/{when.month:02d}/{when.day:02d} {when.hour:02d}:{when.minute:02d}"


def invoice_lines(inv: dict, top: int = 0) -> list[str]:
    """一張發票排成一頁的每一行(沒印東西的行是空字串)。`top` = 上面先空幾行(對紙用)。

    `inv`:store / address / seller_tax_id / tel / when(datetime)/ register(收銀機編號)/ buyer_tax_id / cashier /
    doc_no / items[{name, qty, amount}] / payments[{name, amount}] / subtotal / tax / total。
    """
    if len(inv["items"]) > ITEM_ROWS:
        raise LayoutError(f"品名最多印 {ITEM_ROWS} 行,這一張有 {len(inv['items'])} 行")
    if len(inv["payments"]) > PAYMENT_ROWS:
        raise LayoutError(f"付款方式最多印 {PAYMENT_ROWS} 行,這一張有 {len(inv['payments'])} 行")
    page = [""] * PAGE_LINES
    text, after, amount, right = (COLS_AT[k] for k in ("text", "after_label", "amount_label", "right_edge"))

    def row(name, offset=0):
        return top + ROWS[name] - 1 + offset

    def write(index, line):
        if index >= PAGE_LINES:
            raise LayoutError("上面空太多行,這一張印不進一頁")
        page[index] = line.rstrip()

    write(row("store"), put("", text, clean(inv["store"])))
    write(row("address"), put("", text, clean(inv["address"])))
    tax_tel = f"統編:{clean(inv['seller_tax_id'])}"
    if clean(inv.get("tel")):
        tax_tel += f" TEL:{clean(inv['tel'])}"
    write(row("tax_tel"), put("", text, tax_tel))
    stamp = roc_stamp(inv["when"])
    if clean(inv.get("register")):
        stamp += f" {clean(inv['register'])}機"
    write(row("date"), put("", after, stamp))
    buyer = put("", after, clean(inv.get("buyer_tax_id")))
    if clean(inv.get("cashier")):
        buyer = put(buyer, after + 10, f"收銀員:{clean(inv['cashier'])}")
    write(row("buyer"), buyer)
    write(row("doc_no"), put_right("", right, clean(inv["doc_no"])))
    for i, item in enumerate(inv["items"]):
        price = money(item["amount"])
        qty = f"x{item['qty']}"
        # 品名放左邊,數量與金額靠右;品名太長切掉尾巴(數量與金額不能被蓋掉)
        room = right - cols(price) - 2 - cols(qty) - 1 - text
        line = put("", text, fit(clean(item["name"]), room))
        line = put_right(line, right - cols(price) - 2, qty)
        write(row("items", i), put_right(line, right, price))
    for i, pay in enumerate(inv["payments"]):
        line = put("", text, f"{clean(pay['name'])}:")
        write(row("payments", i), put_right(line, right, money(pay["amount"])))
    write(row("subtotal"), put("", amount, money(inv["subtotal"])))
    write(row("tax"), put("", amount, money(inv["tax"])))
    write(row("total"), put("", amount, money(inv["total"])))
    return page


def ruler_lines() -> list[str]:
    """行號測試:每一行印自己的行號(前兩格)與一把格數的尺。印在一張發票上、拍照,就知道紙上印好的字各在第幾行、第幾格。"""
    ruler = "".join(str((i + 1) // 10 % 10) if (i + 1) % 10 == 0 else ":" if (i + 1) % 5 == 0 else "." for i in range(LINE_COLS))
    return [f"{n:02d}" + ruler[2:] for n in range(1, PAGE_LINES + 1)]


def sample_invoice(when: datetime) -> dict:
    """樣張:照 owner 給的那一張的內容排(店名、號碼都是假的),拿來看每一行有沒有對到紙上印好的字。"""
    return {
        "store": "測試門市", "address": "300-新竹市-測試路1號", "seller_tax_id": "00000000", "tel": "03-0000000",
        "when": when, "register": "01", "buyer_tax_id": "12345678", "cashier": "TEST",
        "doc_no": "SO-000000",
        "items": [{"name": "通訊器材", "qty": 4, "amount": 45233}],
        "payments": [{"name": "現金", "amount": 12000}, {"name": "信用卡", "amount": 33233}],
        "subtotal": 43079, "tax": 2154, "total": 45233,
    }


def page_bytes(lines: list[str]) -> bytes:
    """一頁的每一行 → 送給機器的位元組:先重設、講一頁幾行,一行一行印,最後跳到下一張的開頭。
    最後面沒印東西的行不送(`FF` 會把紙走完);超過一頁、一行超過寬度的不印(排的人要先處理)。"""
    if len(lines) > PAGE_LINES:
        raise LayoutError(f"一頁最多 {PAGE_LINES} 行")
    for line in lines:
        if cols(line) > LINE_COLS:
            raise LayoutError(f"一行最多 {LINE_COLS} 格:{line}")
    while lines and not lines[-1]:
        lines = lines[:-1]
    return INIT + PAGE_LENGTH + b"".join(encode(line) + LF for line in lines) + FF
