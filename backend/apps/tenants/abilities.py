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
VENDOR_ORDER = "vendor_order"
REPORT_SALES_DAILY = "report_sales_daily"
REPORT_EXPLORE = "report_explore"
REPORT_PARTS = "report_parts"
REPORT_STAFF = "report_staff"
REPORT_PRODUCTS = "report_products"
REPORT_COMMISSION = "report_commission"
REPORT_DAILY = "report_daily"

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
    # 跟供應商的下單系統叫貨(會花到這家門市在廠商那邊的額度);金鑰只有管理員能設,不在這個勾裡
    Ability(VENDOR_ORDER, "廠商叫貨", "進貨與帳務", "送出叫貨單;看得到進價"),
    # 第三批:報表一張一個勾(鎖在門市的帳號本來就只看自己門市)
    Ability(REPORT_SALES_DAILY, "銷貨日報", "報表", "只收起這一頁;內容跟銷貨單清單看得到的一樣"),
    Ability(REPORT_EXPLORE, "自訂分析", "報表", "要業績彙總、商品排行、每日彙總、營業日報都開著"),
    Ability(REPORT_PARTS, "零件耗用", "報表"),
    Ability(REPORT_STAFF, "業績彙總", "報表"),
    Ability(REPORT_PRODUCTS, "商品排行", "報表"),
    Ability(REPORT_COMMISSION, "佣金明細", "報表"),
    Ability(REPORT_DAILY, "每日彙總", "報表"),
]
KEYS = frozenset(a.key for a in ABILITIES)
LABELS = {a.key: a.label for a in ABILITIES}

# 這一項要另外那幾項都開著才能用。自訂分析什麼數字都組得出來(照業務員分、照商品分、一天一列、每天收了多少錢):
# 那幾張報表有一張被關掉的帳號,自訂分析也跟著不能用 —— 不然關掉「業績彙總」的人到自訂分析挑同樣的指標與分組就看到了
# (複審 2026-10-10 抓到的)。固定的報表(analytics/presets.py)每加一張都要列進來,有測試擋。
ALSO_NEEDS = {REPORT_EXPLORE: (REPORT_STAFF, REPORT_PRODUCTS, REPORT_DAILY, VIEW_BUSINESS_DAILY)}


def switched_off(profile) -> set[str]:
    """管理員在員工帳號頁關掉的那幾項(資料庫裡記的)。只認清單裡有的、而且是字串的;怪東西不當成任何項目。"""
    stored = getattr(profile, "denied_abilities", None) or []
    return {k for k in stored if isinstance(k, str)} & KEYS


def blocked_by(off: set[str], key: str) -> list[str]:
    """這一項是被哪幾項連帶關掉的(那幾項的代碼,照清單的順序);自己被關掉、或沒有連帶 → 空的。"""
    return [] if key in off else [k for k in ALSO_NEEDS.get(key, ()) if k in off]


def with_blocked(off: set[str]) -> set[str]:
    """關掉的那幾項,加上被它們連帶關掉的。"""
    return off | {key for key in ALSO_NEEDS if blocked_by(off, key)}


def denied(user) -> set[str]:
    """這個帳號不能做的項目(關掉的 + 連帶的)。管理員、沒有帳號設定的(只有平台的超級帳號會這樣)都是空的。"""
    if is_tenant_admin(user):
        return set()
    return with_blocked(switched_off(getattr(user, "profile", None)))


def can(user, key: str) -> bool:
    if key not in KEYS:
        raise KeyError(key)          # 寫程式時打錯字:不能默默當成可以
    return key not in denied(user)


def require(user, key: str) -> None:
    """不能做就丟 403(DRF 會回 `{"detail": …}`,畫面的錯誤訊息只認這一格)。"""
    if not can(user, key):
        because = blocked_by(switched_off(getattr(user, "profile", None)), key)
        if because:
            # 這一項本身沒有被關,是連帶的:講是哪幾項(管理員照著「開啟自訂分析」去找會找不到問題在哪)
            names = "、".join(LABELS[k] for k in because)
            raise PermissionDenied(
                f"這個帳號的「{names}」被關掉了,「{LABELS[key]}」也不能用,請管理員到「系統設定 → 員工帳號」開啟")
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
