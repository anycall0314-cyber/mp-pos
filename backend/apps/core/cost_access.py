"""誰看得到實際成本與進價。規則只有這一份。

owner 2026-10-28:「除了管理者以外，其他所有人看的都是業務員成本（沒有設定則為實際成本），
以及業務員毛利（如無設定業務員成本，則為售價-實際成本）」。同一天他選了:
- 進貨單、進貨明細、廠商叫貨單、營業日報裡每一張進貨單的金額:有「進貨入庫」或「廠商叫貨」的人照舊看得到(要打進價),
  其他店員看不到。
- 維修單的零件成本與維修毛利也換成業務員成本。

**擋在伺服器**:看不到的數字根本不在回應裡(畫面藏起來的話,打開瀏覽器的開發工具就看得到)。
帶序號的商品(手機、中古機)還沒有業務員成本的規則(`staff_cost.SERIAL_GOODS_TOO`),業務員成本 = 那一台的實際成本,
所以序號清單、庫存查詢每一台的成本照舊給;打開那個開關之前要先把那幾處換掉(`test_cost_access.py` 會擋)。
"""


def sees_actual_cost(user) -> bool:
    """看得到實際成本、實際毛利:只有管理員(公司管理員、平台管理員)。"""
    from apps.tenants.permissions import is_tenant_admin

    return is_tenant_admin(user)


def sees_purchase_prices(user) -> bool:
    """看得到進價(進貨單、進貨明細、叫貨單、上次進價):管理員,或有「進貨入庫」「廠商叫貨」其中一項的店員。"""
    from apps.tenants import abilities

    if sees_actual_cost(user):
        return True
    if not getattr(user, "is_authenticated", False):
        return False
    return abilities.can(user, abilities.PURCHASE) or abilities.can(user, abilities.VENDOR_ORDER)


def require_purchase_prices(user) -> None:
    from rest_framework.exceptions import PermissionDenied

    if not sees_purchase_prices(user):
        raise PermissionDenied("這個帳號沒有開「進貨入庫」或「廠商叫貨」,看不到進貨的金額")
