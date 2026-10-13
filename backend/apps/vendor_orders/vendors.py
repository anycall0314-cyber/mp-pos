"""平台的廠商名單:查一家廠商、跟它講話要用哪一支。

公司的資料(串接、叫貨單)只記廠商的代碼;要名稱、網址、能不能叫貨都從這裡問。
名單上找不到那個代碼(備份還原到別台、那邊沒有這一家)= 那幾張單照樣看得到,但不能再對廠商做任何事。
"""
from . import standard
from .models import Vendor


class UnknownVendor(Exception):
    """名單上沒有這個代碼。"""


def find(code) -> Vendor | None:
    return Vendor.objects.filter(code=code).first() if isinstance(code, str) and code else None


def company_codes(vendor: Vendor) -> list[str]:
    """這家廠商的名單上有哪幾家公司(代碼,照存的順序、不重複)。"""
    seen = []
    for code in vendor.only_for.split(","):
        code = code.strip()
        if code and code not in seen:
            seen.append(code)
    return seen


def open_to(vendor: Vendor, tenant) -> bool:
    """這家公司看不看得到這家廠商(廠商清單、價目、開通、連品名、叫貨)。
    沒有設「只給指定的公司」→ 每一家都看得到;有設 → 只有名單上的(名單空的 = 沒有人)。"""
    if not vendor.is_private:
        return True
    return tenant is not None and tenant.code in company_codes(vendor)


def name_of(code) -> str:
    """畫面與訊息裡怎麼稱呼這一家。名單上沒有就寫代碼(至少認得出是哪一家)。"""
    vendor = find(code)
    return vendor.name if vendor is not None else str(code)


def client(vendor: Vendor):
    """跟這家廠商講話的那一支。現在只有一種接法(標準格式);之後不同格式的廠商在這裡分。"""
    if vendor.protocol == Vendor.Protocol.STANDARD and vendor.api_base:
        return standard.Client(vendor.api_base, vendor.name)
    raise UnknownVendor(f"「{vendor.name}」還沒有設定怎麼連線,請平台管理員處理")
