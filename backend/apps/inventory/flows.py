"""庫存異動的唯一解讀:每一筆異動算哪一類、動到哪家門市的數量、進銷存表算在哪一欄。

進銷存表與異動查詢都只讀這裡(同一筆異動不會在兩張表上算成兩種)。方向跟每日對帳
(`ledger/checks.py` 的「配件庫存 = 進出異動加總」)同一套:寫了目的門市的加、寫了來源門市的減;
調撥的兩筆都寫了來源與目的(當路線說明),派發只扣來源、確認才加到目的。

異動只會多一筆、不會改:作廢是另外一筆反方向的異動。所以進銷存表把作廢**沖回原本那一欄**
(進貨單作廢 → 進貨減回去),記在作廢那一天;異動查詢裡作廢各自一列、寫明是哪一種作廢。
"""
from django.db.models import Q

from .models import StockMovement

T = StockMovement.MovementType

# 進銷存表的欄(順序 = 畫面上的順序)。名稱一律兩個字。
COLUMNS = ("purchase", "sale", "sale_return", "transfer_in", "transfer_out", "usage", "vendor", "adjust")
COLUMN_LABELS = {
    "purchase": "進貨", "sale": "銷貨", "sale_return": "銷退",
    "transfer_in": "調入", "transfer_out": "調出", "usage": "領用", "vendor": "換貨", "adjust": "調整",
}
# 這一欄的數字對庫存是加還是減:期末 = 期初 + Σ(欄 × 這個方向)
SIGN = {
    "purchase": 1, "sale": -1, "sale_return": 1,
    "transfer_in": 1, "transfer_out": -1, "usage": -1, "vendor": 1, "adjust": 1,
}

# 異動查詢的「類別」(順序 = 選單的順序)。名稱一律四個字。
KIND_LABELS = {
    "purchase": "進貨入庫",
    "trade_in": "收購入庫",
    "sale": "銷貨出庫",
    "parts_sale": "零件調貨",
    "sale_return": "銷退入庫",
    "transfer_out": "調撥出庫",
    "transfer_in": "調撥入庫",
    "usage": "維修領用",
    "usage_back": "零件歸還",
    "adjust": "庫存調整",
    "purchase_void": "進貨作廢",
    "sale_void": "銷貨作廢",
    "return_void": "銷退作廢",
    "transfer_void": "調撥作廢",
    # 送廠商換貨 / 已換貨 / 取消:不寫門市、不動數量(那一台一直掛在原門市),只是序號履歷上的紀錄
    "vendor_exchange": "廠商換貨",
    # 銷退退回來的「已退」確認可以賣:不寫門市、不動數量(一直在原門市),只是紀錄
    "return_release": "退回可賣",
}

# 作廢那一筆是哪一種單的作廢、零件歸還是哪一種單:看來源單據
_VOID_KIND = {
    "purchase_order": "purchase_void",
    "sales_return": "return_void",
    "transfer_order": "transfer_void",
}
_REOPEN = "repair_order_reopen"
_SALES_ORDER = "sales_order"


def kind_of(movement_type: str, ref_doc_type: str) -> str:
    """這一筆異動在異動查詢上叫什麼(`KIND_LABELS` 的代碼)。不認得的一律歸「庫存調整」。"""
    if movement_type == T.PURCHASE_IN:
        return "purchase"
    if movement_type == T.TRADE_IN:
        return "trade_in"
    if movement_type == T.SALE_OUT:
        return "sale"
    if movement_type == T.PARTS_TRANSFER:
        return "parts_sale"
    if movement_type == T.RETURN_IN:
        # 銷貨單作廢也是寫「退貨入庫」:來源單據是銷貨單的那一種是作廢,其餘是銷退
        return "sale_void" if ref_doc_type == _SALES_ORDER else "sale_return"
    if movement_type == T.TRANSFER_OUT:
        return "transfer_out"
    if movement_type == T.TRANSFER_IN:
        return "transfer_in"
    if movement_type == T.REPAIR_USAGE:
        return "usage"
    if movement_type == T.ADJUST:
        return "usage_back" if ref_doc_type == _REOPEN else "adjust"
    if movement_type == T.VOID:
        return _VOID_KIND.get(ref_doc_type, "adjust")
    if movement_type == T.VENDOR_EXCHANGE:
        return "vendor_exchange"
    if movement_type == T.RETURN_RELEASE:
        return "return_release"
    return "adjust"


def kind_q(kind: str) -> Q:
    """異動查詢照類別篩:跟 `kind_of` 是同一份規則的資料庫寫法(有測試逐一對照)。"""
    known = [T.PURCHASE_IN, T.TRADE_IN, T.SALE_OUT, T.PARTS_TRANSFER, T.RETURN_IN,
             T.TRANSFER_OUT, T.TRANSFER_IN, T.REPAIR_USAGE, T.ADJUST, T.VOID, T.VENDOR_EXCHANGE,
             T.RETURN_RELEASE]
    simple = {
        "purchase": T.PURCHASE_IN, "trade_in": T.TRADE_IN, "sale": T.SALE_OUT,
        "parts_sale": T.PARTS_TRANSFER, "transfer_out": T.TRANSFER_OUT,
        "transfer_in": T.TRANSFER_IN, "usage": T.REPAIR_USAGE,
        "vendor_exchange": T.VENDOR_EXCHANGE,
        "return_release": T.RETURN_RELEASE,
    }
    if kind in simple:
        return Q(movement_type=simple[kind])
    if kind == "sale_void":
        return Q(movement_type=T.RETURN_IN, ref_doc_type=_SALES_ORDER)
    if kind == "sale_return":
        return Q(movement_type=T.RETURN_IN) & ~Q(ref_doc_type=_SALES_ORDER)
    if kind == "usage_back":
        return Q(movement_type=T.ADJUST, ref_doc_type=_REOPEN)
    for ref, name in _VOID_KIND.items():
        if kind == name:
            return Q(movement_type=T.VOID, ref_doc_type=ref)
    if kind == "adjust":
        return (
            (Q(movement_type=T.ADJUST) & ~Q(ref_doc_type=_REOPEN))
            | (Q(movement_type=T.VOID) & ~Q(ref_doc_type__in=list(_VOID_KIND)))
            | ~Q(movement_type__in=known)
        )
    raise KeyError(kind)


def deltas(movement_type: str, from_id, to_id, qty: int) -> list[tuple[int, int]]:
    """這一筆異動讓哪家門市的數量變了多少:[(門市, +數量 或 −數量)]。兩邊都沒寫 = 只是紀錄,不動數量。"""
    out = []
    if to_id and movement_type != T.TRANSFER_OUT:
        out.append((to_id, qty))
    if from_id and movement_type != T.TRANSFER_IN:
        out.append((from_id, -qty))
    return out


def touches_q(warehouse_id) -> Q:
    """動到這家門市數量的異動:`deltas` 的資料庫寫法(有測試逐一對照)。"""
    return (
        (Q(to_warehouse_id=warehouse_id) & ~Q(movement_type=T.TRANSFER_OUT))
        | (Q(from_warehouse_id=warehouse_id) & ~Q(movement_type=T.TRANSFER_IN))
    )


def transit_delta(movement_type: str, ref_doc_type: str, from_id, to_id, qty: int) -> int:
    """這一筆異動讓「調撥途中」(派發了、對方還沒確認,不在任何一家門市)的數量變了多少。

    派發 = 上路;確認 = 到了;還在路上就作廢 = 回到來源門市(那一筆只寫了目的門市 = 來源,沒寫來源)。
    確認過才作廢的是從目的門市拿回來,不經過路上。
    """
    if movement_type == T.TRANSFER_OUT:
        return qty
    if movement_type == T.TRANSFER_IN:
        return -qty
    if movement_type == T.VOID and ref_doc_type == "transfer_order" and to_id and not from_id:
        return -qty
    return 0


def _column(kind: str, delta: int) -> str:
    """這一家門市的這個增減,算在進銷存表的哪一欄。方向不合常理的(例:進貨卻是減)一律歸調整 ——
    不管歸哪一欄,欄的方向都會算回同一個增減,所以每一列的等式一定成立。"""
    up = delta > 0
    if kind in ("purchase", "trade_in"):
        return "purchase" if up else "adjust"
    if kind == "purchase_void":
        return "adjust" if up else "purchase"
    if kind in ("sale", "parts_sale"):
        return "adjust" if up else "sale"
    if kind == "sale_void":
        return "sale" if up else "adjust"
    if kind == "sale_return":
        return "sale_return" if up else "adjust"
    if kind == "return_void":
        return "adjust" if up else "sale_return"
    if kind == "transfer_out":
        return "adjust" if up else "transfer_out"
    if kind == "transfer_in":
        return "transfer_in" if up else "adjust"
    if kind == "transfer_void":
        # 回到來源門市的 = 當初的調出不算了;從目的門市拿走的(確認過才有)= 當初的調入不算了
        return "transfer_out" if up else "transfer_in"
    if kind == "usage":
        return "adjust" if up else "usage"
    if kind == "usage_back":
        return "usage" if up else "adjust"
    if kind == "vendor_exchange":
        # 配件送廠商是減、換回來 / 取消是加(同一欄,跟調整一樣有正有負);設備那幾筆沒寫門市,不會到這裡
        return "vendor"
    return "adjust"


def effects(movement_type: str, ref_doc_type: str, from_id, to_id, qty: int) -> list[tuple[int, str, int]]:
    """進銷存表用:[(門市, 欄, 那一欄要加的數字)]。那一欄的數字 × `SIGN[欄]` = 這家門市數量的增減。"""
    kind = kind_of(movement_type, ref_doc_type)
    out = []
    for warehouse_id, delta in deltas(movement_type, from_id, to_id, qty):
        column = _column(kind, delta)
        out.append((warehouse_id, column, delta * SIGN[column]))
    return out
