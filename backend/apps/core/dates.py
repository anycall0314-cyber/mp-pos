"""日期的小工具。"""
import calendar
from datetime import date


def add_months(day: date, months: int) -> date:
    """往後推幾個月,落在同一天;那個月沒有這一天(1/31 推一個月)就落在月底。"""
    index = day.month - 1 + months
    year = day.year + index // 12
    month = index % 12 + 1
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(day.day, last))
