"""金額的進位規則(全站唯一的一份)。

2026-10-06 起:**單據上的金額一律整數元、四捨五入**(明細金額、未稅小計、稅額、含稅總額)。
在這之前是算到分、而且用的是 Python 預設的「四捨六入五成雙」(4.5 → 4),跟發票上的算法不一樣,
應稅外加時還會出現 115.50 這種收不到的總額。

**成本不收成整數**(落地成本、加權平均成本、銷貨當下成本):那是平均值,收成整數會越算越偏
(95.24 的線材進 1000 條會差 240 元)。成本照舊算到分,只在畫面上顯示成整數。
"""
from decimal import ROUND_HALF_UP, Decimal

ONE = Decimal("1")
CENTS = Decimal("0.01")


def round_money(value) -> Decimal:
    """四捨五入到整數元。剛好一半一律進位(負數往離 0 遠的那一邊:-2.5 → -3)。"""
    return Decimal(value).quantize(ONE, rounding=ROUND_HALF_UP)


def money_int(value) -> int:
    """給報表加總用的整數(空的當 0)。不要用 int():那是無條件捨去。"""
    return int(round_money(value or 0))


def money_text(value) -> str:
    """寫進訊息裡的金額:整數元就不帶小數點(116,不是 116.00)。
    真的帶小數的數字(別的程式送進來的 115.50)照原樣印,才看得出兩個數字差在哪。"""
    d = Decimal(value)
    return f"{int(d):,}" if d == d.to_integral_value() else f"{d:,}"
