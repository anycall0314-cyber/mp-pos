"""員工帳號的權限:每個店員帳號一項一項勾(owner 2026-10-10)。清單只有這一份。

- 記的是「關掉的項目」(`UserProfile.denied_abilities`):空的 = 全開(跟以前一樣)。
  之後這裡多加一項,既有的帳號預設都是開的 —— 沒有人會因為更新而突然被鎖。
- 管理員(公司管理員、平台管理員)永遠全開;勾選只對店員帳號有用。
- **擋在伺服器**:端點裡呼叫 `require(request.user, 項目)`,關掉的回 403 與一句話。
  畫面把按鈕收起來只是不讓人白按。
- 只放「已經真的會擋」的項目(放了沒有用的勾比沒有更糟)。要加一項:這裡加一筆 + 端點裡呼叫 `require` + 測試。
- **預設不開的項目**(`opt_in=True`,2026-10-23 起;owner「此權限作為開關形式,可以讓管理員指派」):
  管理員勾了才算開,記成同一個清單裡的一筆 `+代碼`(`GRANT`)—— 不用另外一個欄位,公司備份照樣帶著。
- **身份別**(2026-10-27 起;`StaffRole`):店員帳號跟著身份別走 —— 帳號關掉的 = 身份別關掉的,加上帳號自己多關的、
  減掉帳號自己多開的(例外,記在 `UserProfile.denied_abilities`:代碼 = 多關、`+代碼` = 多開)。
  兩邊都記同一種寫法;跟身份別一樣的不記,所以改身份別的勾選,那個身份的人一起變。沒有身份別 = 照預設。
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
    opt_in: bool = False  # 預設不開:管理員勾了才算開


VOID_SALES = "void_sales"
SALES_RETURN = "sales_return"
VOID_PURCHASE = "void_purchase"
VOID_OTHERS = "void_others"
EDIT_PRODUCTS = "edit_products"
STOCK_COUNT = "stock_count"
RELEASE_RETURNED = "release_returned"
REMEMBER_BARCODE = "remember_barcode"
PURCHASE = "purchase"
SECONDHAND_BUY = "secondhand_buy"
CASH_OPS = "cash_ops"
VIEW_BUSINESS_DAILY = "view_business_daily"
VENDOR_ORDER = "vendor_order"
INVOICE_TRACKS = "invoice_tracks"
TRADE_SELL = "trade_sell"
REPORT_SALES_DAILY = "report_sales_daily"
REPORT_EXPLORE = "report_explore"
REPORT_PARTS = "report_parts"
REPORT_STAFF = "report_staff"
REPORT_PRODUCTS = "report_products"
REPORT_COMMISSION = "report_commission"
REPORT_DAILY = "report_daily"
REPORT_ACTIVATIONS = "report_activations"
REPORT_INVOICES = "report_invoices"
REPORT_REPAIRS = "report_repairs"

ABILITIES = [
    Ability(VOID_SALES, "作廢銷貨單", "作廢與銷退"),
    Ability(SALES_RETURN, "開立銷退單", "作廢與銷退", "含作廢銷退單"),
    Ability(VOID_PURCHASE, "作廢進貨單", "作廢與銷退"),
    Ability(VOID_OTHERS, "作廢其他單", "作廢與銷退", "調撥、維修、雜支、現金調整、代收話費"),
    # 第二批(只擋「做」;查商品、查庫存、看進貨單與雜支清單照舊)
    Ability(EDIT_PRODUCTS, "商品建檔", "商品", "新增、修改商品與類別品牌,含批次與匯入"),
    # 盤點(2026-10-12):開盤點單、輸入數到的數量、刷手機、送出。**核准才動庫存,核准只有管理員**,不在這個勾裡
    Ability(STOCK_COUNT, "盤點作業", "商品", "開盤點單、盤、送出;核准只有管理員"),
    # 銷退退回來的手機是「已退」(不能賣),確認可以賣才回在庫(owner 2026-10-23「先標不能賣,確認可賣再點回倉」;
    # 紅隊:放行的人老闆要能收回)
    Ability(RELEASE_RETURNED, "確認可賣", "商品", "銷退退回來的手機確認可以再賣、回到在庫"),
    # 進貨 / 盤點刷到不認得的條碼,用某一款時順便把條碼記到那個商品上(之後刷這個條碼直接對到)。
    # 記錯了之後每一刷都帶錯 → 預設不開,管理員勾給信得過的人(owner 2026-10-23)
    Ability(REMEMBER_BARCODE, "記住條碼", "商品", "刷到不認得的條碼,用這款時記到商品上;預設不開", opt_in=True),
    Ability(PURCHASE, "進貨入庫", "進貨與帳務", "進貨單、進貨匯入、中古的廠商收購"),
    Ability(SECONDHAND_BUY, "中古收購", "進貨與帳務", "跟客人收購二手機"),
    Ability(CASH_OPS, "雜支調整", "進貨與帳務", "新增雜支與現金調整"),  # 存好不能改,記錯作廢重記(2026-10-24)
    Ability(VIEW_BUSINESS_DAILY, "營業日報", "進貨與帳務", "看營業日報"),
    # 跟供應商的下單系統叫貨(會花到這家門市在廠商那邊的額度);金鑰只有管理員能設,不在這個勾裡
    Ability(VENDOR_ORDER, "廠商叫貨", "進貨與帳務", "送出叫貨單;看得到進價"),
    # 發票字軌(2026-10-13):新增、修改、刪除字軌與跳號。看字軌、開單取號不在這個勾裡(開單一定要取得到號)
    Ability(INVOICE_TRACKS, "發票字軌", "進貨與帳務", "新增、修改字軌與跳號"),
    # 批發(2026-10-14):看同行下的單、接單、出貨(會開銷貨單)、中古機上架。設定、同行、價錢、收款只有管理員,不在這個勾裡
    Ability(TRADE_SELL, "批發出貨", "進貨與帳務", "同行的訂單:接單、出貨、中古機上架"),
    # 第三批:報表一張一個勾(鎖在門市的帳號本來就只看自己門市)
    Ability(REPORT_SALES_DAILY, "銷貨日報", "報表", "只收起這一頁;內容跟銷貨單清單看得到的一樣"),
    Ability(REPORT_EXPLORE, "自訂分析", "報表", "要業績彙總、商品排行、每日彙總、開通統計、營業日報都開著"),
    Ability(REPORT_PARTS, "零件耗用", "報表"),
    Ability(REPORT_STAFF, "業績彙總", "報表"),
    Ability(REPORT_PRODUCTS, "商品排行", "報表"),
    Ability(REPORT_COMMISSION, "佣金明細", "報表"),
    Ability(REPORT_DAILY, "每日彙總", "報表"),
    # 客戶排行不在這裡:只有管理員看得到(owner 2026-10-12「客戶排行不用給店員看」),沒有勾可以開
    Ability(REPORT_ACTIVATIONS, "開通統計", "報表", "各家電信、各種方案開了幾門"),
    Ability(REPORT_INVOICES, "發票明細", "報表", "開過的發票逐張列出來"),
    Ability(REPORT_REPAIRS, "維修月報", "報表", "完工的維修單:件數、毛利、每個人分到多少"),
]
KEYS = frozenset(a.key for a in ABILITIES)
OPT_IN = frozenset(a.key for a in ABILITIES if a.opt_in)
GRANT = "+"
LABELS = {a.key: a.label for a in ABILITIES}

# 這一項要另外那幾項都開著才能用。自訂分析什麼數字都組得出來(照業務員分、照商品分、一天一列、每天收了多少錢):
# 那幾張報表有一張被關掉的帳號,自訂分析也跟著不能用 —— 不然關掉「業績彙總」的人到自訂分析挑同樣的指標與分組就看到了
# (複審 2026-10-10 抓到的)。固定的報表(analytics/presets.py)每加一張都要列進來,有測試擋。
# 只有管理員看得到的那一張(客戶排行)不列:它的分組(客戶、會員)在自訂分析裡也只有管理員能用。
ALSO_NEEDS = {REPORT_EXPLORE: (REPORT_STAFF, REPORT_PRODUCTS, REPORT_DAILY, REPORT_ACTIVATIONS, VIEW_BUSINESS_DAILY)}


def _stored(value) -> set[str]:
    """資料庫裡記的清單;只認字串,怪東西不當成任何項目。"""
    return {k for k in (value or []) if isinstance(k, str)} if isinstance(value, list) else set()


def _granted(stored: set[str]) -> set[str]:
    return {k[len(GRANT):] for k in stored if k.startswith(GRANT)} & KEYS


def role_off(role) -> set[str]:
    """身份別關掉的那幾項:勾掉的,加上預設不開、也沒有被勾的。沒有身份別 = 照預設(只有預設不開的那幾項是關的)。"""
    stored = _stored(getattr(role, "denied_abilities", None)) if role is not None else set()
    return (stored & KEYS) | (OPT_IN - _granted(stored))


def switched_off(profile) -> set[str]:
    """這個帳號關掉的那幾項:身份別關掉的、減掉帳號多開的、加上帳號多關的(兩邊都記到同一項時算關,不放寬)。
    只認清單裡有的、而且是字串的。"""
    role = getattr(profile, "staff_role", None) if profile is not None else None
    stored = _stored(getattr(profile, "denied_abilities", None))
    return (role_off(role) - _granted(stored)) | (stored & KEYS)


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
    profile = getattr(user, "profile", None)
    if profile is None:
        return set()
    return with_blocked(switched_off(profile))


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


def own(off: set[str]) -> dict[str, bool]:
    """每一項自己開或關(不算連帶的);身份別頁、帳號頁的勾選照這個畫。"""
    return {a.key: a.key not in off for a in ABILITIES}


def exceptions(profile) -> list[str]:
    """帳號跟身份別不一樣的項目(照清單的順序;畫面標「例外」)。跟身份別一樣的記錄不算。"""
    base, off = role_off(getattr(profile, "staff_role", None)), switched_off(profile)
    return [a.key for a in ABILITIES if (a.key in off) != (a.key in base)]


def catalog() -> list[dict]:
    return [
        {"key": a.key, "label": a.label, "group": a.group, "note": a.note, "opt_in": a.opt_in,
         "needs": list(ALSO_NEEDS.get(a.key, ()))}
        for a in ABILITIES
    ]


def _apply(current, wanted: dict, allowed_by_default) -> list[str]:
    """把 `{項目: 可不可以}` 套到記的清單上:跟預設一樣 → 不記;不一樣 → 關記代碼、開記 `+代碼`。
    不在這次送來的項目不動;照清單的順序排。"""
    stored = _stored(current)
    for key, allowed in wanted.items():
        stored.discard(key)
        stored.discard(GRANT + key)
        if allowed != allowed_by_default(key):
            stored.add(GRANT + key if allowed else key)
    ordered = [a.key for a in ABILITIES if a.key in stored] + [GRANT + a.key for a in ABILITIES if GRANT + a.key in stored]
    # 清單裡已經沒有的舊項目留著(不替人丟資料),排在後面
    return ordered + sorted(stored - set(ordered))


def change(profile, wanted: dict) -> list[str]:
    """把 `{項目: 可不可以}` 套到這個帳號上,回新的例外清單。跟身份別一樣的 → 回到身份別(不記)。"""
    base = role_off(getattr(profile, "staff_role", None))
    return _apply(profile.denied_abilities, wanted, lambda key: key not in base)


def change_role(role, wanted: dict) -> list[str]:
    """把 `{項目: 可不可以}` 套到身份別上,回新的「關掉的項目」。跟預設一樣的不記。"""
    return _apply(role.denied_abilities, wanted, lambda key: key not in OPT_IN)


def leftovers(stored) -> list[str]:
    """換身份別時:例外全部清掉(完全照新身份別;畫面同一次再送要的例外),只留清單裡已經沒有的舊項目(不替人丟資料)。"""
    return sorted(k for k in _stored(stored) if k.removeprefix(GRANT) not in KEYS)


def turned_on_but_blocked(after: set[str], wanted: dict) -> tuple[str, list[str]] | None:
    """這一次要開的項目裡,開了也還是不能用的那一項(它要的另外幾項關著)與要先開的幾項;沒有 → None。
    畫面只送改過的項目,所以沒動到的「連帶關掉」不會被擋。"""
    for key, allowed in wanted.items():
        if allowed:
            because = blocked_by(after, key)
            if because:
                return key, because
    return None
