"""發票的期別:兩個月一期(1-2、3-4、5-6、7-8、9-10、11-12 月)。一期用它第一天的日期代表(奇數月 1 日)。

owner 2026-10-13:「發票字軌設定不但有指定年月與字軌數字，跳月如未設定新的符合年月與字軌，則自動提示」
- 字軌登記是哪一期的;開單只取「發票日期那一期」的字軌 —— 上一期的號碼換期之後不能再開。
- 換期了還沒設定新的字軌:開單頁直接講是哪一期還沒設定(結帳也會被擋);快換期的最後幾天先提醒。
"""
from datetime import date, timedelta

# 這一期剩幾天以內,開始提醒「下一期的字軌還沒設定」
REMIND_DAYS = 7


def is_start(day: date) -> bool:
    return day.day == 1 and day.month % 2 == 1


def start_of(day: date) -> date:
    """這一天是哪一期的(那一期的第一天)。"""
    return date(day.year, day.month if day.month % 2 else day.month - 1, 1)


def next_start(start: date) -> date:
    return date(start.year + 1, 1, 1) if start.month == 11 else date(start.year, start.month + 2, 1)


def last_day(start: date) -> date:
    return next_start(start) - timedelta(days=1)


def label(start: date) -> str:
    """民國年 + 月份,例 `115年11-12月`。"""
    return f"{start.year - 1911}年{start.month}-{start.month + 1}月"


def days_left(day: date) -> int:
    """這一期還剩幾天(今天是最後一天 = 0)。"""
    return (last_day(start_of(day)) - day).days
