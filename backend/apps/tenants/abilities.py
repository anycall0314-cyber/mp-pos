"""員工帳號的權限:每個店員帳號一項一項勾(owner 2026-10-10)。清單只有這一份。

- 記的是「關掉的項目」(`UserProfile.denied_abilities`):空的 = 全開(跟以前一樣)。
  之後這裡多加一項,既有的帳號預設都是開的 —— 沒有人會因為更新而突然被鎖。
- 管理員(公司管理員、平台管理員)永遠全開;勾選只對店員帳號有用。
- **擋在伺服器**:端點裡呼叫 `require(request.user, 項目)`,關掉的回 403 與一句話。
  畫面把按鈕收起來只是不讓人白按。
- 只放「已經真的會擋」的項目(放了沒有用的勾比沒有更糟)。要加一項:這裡加一筆 + 端點裡呼叫 `require` + 測試。
"""
from dataclasses import dataclass

from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import SAFE_METHODS

from .permissions import is_tenant_admin


@dataclass(frozen=True)
class Ability:
    key: str
    label: str          # 同一類的名稱字數一樣(owner:同一排的選項等長)
    group: str
    note: str = ""      # 這一項包含哪些(名稱講不完的才寫)


VOID_SALES = "void_sales"
SALES_RETURN = "sales_return"
VOID_PURCHASE = "void_purchase"
VOID_OTHERS = "void_others"
EDIT_PRODUCTS = "edit_products"
PURCHASE = "purchase"
SECONDHAND_BUY = "secondhand_buy"
CASH_OPS = "cash_ops"
VIEW_BUSINESS_DAILY = "view_business_daily"

ABILITIES = [
    Ability(VOID_SALES, "作廢銷貨單", "作廢與銷退"),
    Ability(SALES_RETURN, "開立銷退單", "作廢與銷退", "含作廢銷退單"),
    Ability(VOID_PURCHASE, "作廢進貨單", "作廢與銷退"),
    Ability(VOID_OTHERS, "作廢其他單", "作廢與銷退", "調撥、維修、雜支、現金調整、代收話費"),
    # 第二批(只擋「做」;查商品、查庫存、看進貨單與雜支清單照舊)
    Ability(EDIT_PRODUCTS, "商品建檔", "商品", "新增、修改商品與類別品牌,含批次與匯入"),
    Ability(PURCHASE, "進貨入庫", "進貨與帳務", "進貨單、進貨匯入、中古的廠商收購"),
    Ability(SECONDHAND_BUY, "中古收購", "進貨與帳務", "跟客人收購二手機"),
    Ability(CASH_OPS, "雜支調整", "進貨與帳務", "新增、修改雜支與現金調整"),
    Ability(VIEW_BUSINESS_DAILY, "營業日報", "進貨與帳務", "看營業日報"),
]
KEYS = frozenset(a.key for a in ABILITIES)
LABELS = {a.key: a.label for a in ABILITIES}


def denied(user) -> set[str]:
    """這個帳號被關掉的項目。管理員、沒有帳號設定的(只有平台的超級帳號會這樣)都是空的。"""
    if is_tenant_admin(user):
        return set()
    profile = getattr(user, "profile", None)
    stored = getattr(profile, "denied_abilities", None) or []
    # 只認清單裡有的、而且是字串的;資料庫裡的怪東西不當成任何項目
    return {k for k in stored if isinstance(k, str)} & KEYS


def can(user, key: str) -> bool:
    if key not in KEYS:
        raise KeyError(key)          # 寫程式時打錯字:不能默默當成可以
    return key not in denied(user)


def require(user, key: str) -> None:
    """不能做就丟 403(DRF 會回 `{"detail": …}`,畫面的錯誤訊息只認這一格)。"""
    if not can(user, key):
        # 項目的名稱有的是動作(作廢銷貨單)、有的是名詞(營業日報):用「沒有…的權限」兩種都通順
        raise PermissionDenied(f"這個帳號沒有「{LABELS[key]}」的權限,請管理員到「系統設定 → 員工帳號」開啟")


class WritesNeed:
    """viewset 用(放在繼承清單最前面):**會改資料的請求**(不是 GET / HEAD / OPTIONS)要有 `needs_ability` 這一項;看照舊。

    `ability_exempt` 裡的動作不看這一項 —— 它們自己另外擋(例:雜支的「作廢」看的是「作廢其他單」,不是「雜支調整」)。
    """

    needs_ability: str = ""
    ability_exempt: tuple = ()

    def check_permissions(self, request):
        super().check_permissions(request)
        if request.method in SAFE_METHODS or getattr(self, "action", None) in self.ability_exempt:
            return
        require(request.user, self.needs_ability)


def for_user(user) -> dict[str, bool]:
    """每一項能不能做(登入資料與員工帳號頁都用這個樣子)。"""
    off = denied(user)
    return {a.key: a.key not in off for a in ABILITIES}


def catalog() -> list[dict]:
    return [{"key": a.key, "label": a.label, "group": a.group, "note": a.note} for a in ABILITIES]


def change(profile, wanted: dict) -> list[str]:
    """把 `{項目: 可不可以}` 套到這個帳號上,回新的「關掉的項目」(照清單的順序;不在這次送來的項目不動)。"""
    off = {k for k in (profile.denied_abilities or []) if isinstance(k, str)}
    for key, allowed in wanted.items():
        if allowed:
            off.discard(key)
        else:
            off.add(key)
    ordered = [a.key for a in ABILITIES if a.key in off]
    # 清單裡已經沒有的舊項目留著(不替人丟資料),排在後面
    return ordered + sorted(off - KEYS)
