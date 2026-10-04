"""存起來的報表:查詢單裡的條件怎麼存。

查詢單在執行時用的是資料編號(門市 3、品類 12)。但編號不是穩定的東西:還原備份之後每一列都換新編號,
搬到新環境更可能撞到別筆資料 —— 照編號存,還原後的報表會查錯對象而且看不出來。
所以存檔時把編號換成那筆資料自己的代碼(門市代碼、品號…),打開時再換回現在的編號。
代碼找不到(那筆資料被刪了)就把那個值拿掉,並且講出來,不要悄悄變成「全部」。
"""
from django.apps import apps as django_apps

from . import engine
from .catalog import DIMENSIONS

MAX_PER_USER = 100
BROKEN = "這份報表的內容壞了,請刪掉重存"


def _refs(dim):
    return django_apps.get_model(dim.model), dim.key_field


def to_stored(tenant, spec):
    """整理過的查詢單(條件是編號)→ 存檔用(條件是代碼)。"""
    filters = {}
    for key, values in spec["filters"].items():
        dim = DIMENSIONS[key]
        if dim.kind != "ref":
            filters[key] = values
            continue
        model, field = _refs(dim)
        ids = [v for v in values if v is not None]
        codes = dict(model.objects.filter(tenant=tenant, pk__in=ids).values_list("pk", field))
        filters[key] = [None if v is None else codes[v] for v in values]
    return {**spec, "filters": filters}


def from_stored(tenant, stored, user=None):
    """存檔用 → 現在可以執行的查詢單。回傳 (查詢單, 少了東西的條件名稱, 整份不能用的原因)。

    存檔的內容不一定是這支程式寫的(舊版本、人工修過、還原回來的備份):形狀不對就當成這一份壞了,
    回原因,不可以讓一份壞的拖垮整張清單,也不可以把看不懂的條件當成「沒有條件」。
    """
    try:
        spec, missing = _convert(tenant, stored)
        return engine.normalize(tenant, spec, user), missing, ""
    except engine.QueryError as exc:          # 例如某個指標後來被拿掉了
        return (stored if isinstance(stored, dict) else {}), [], str(exc)


def _convert(tenant, stored):
    if not isinstance(stored, dict):
        raise engine.QueryError(BROKEN)
    # 沒有這一欄 = 沒有條件;有這一欄但不是物件(空清單、0、空字串、空值也算)= 壞了
    raw = stored.get("filters", {})
    if not isinstance(raw, dict):
        raise engine.QueryError(BROKEN)
    filters, missing = {}, []
    order = list(DIMENSIONS)
    # 資料庫不保留條件的先後,照定義的順序走,講出來的順序才固定
    for key, values in sorted(raw.items(),
                              key=lambda kv: order.index(kv[0]) if kv[0] in order else len(order)):
        if not isinstance(values, list) or not values:     # 先看形狀:角度已經停用的也一樣要驗
            raise engine.QueryError(BROKEN)
        dim = DIMENSIONS.get(key)
        if dim is None:                       # 報表定義改過,這個角度已經沒有了
            missing.append(f"{key}(已停用的條件)")
            continue
        if dim.kind == "choice":
            # 代碼(付款方式…)也可能後來沒有了:跟資料被刪一樣,拿掉那個值並講出來
            if any(not isinstance(v, str) for v in values):
                raise engine.QueryError(BROKEN)
            known = dim.labels(tenant)
            kept = [v for v in values if v in known]
        elif dim.kind == "ref":
            if any(v is not None and not isinstance(v, str) for v in values):
                raise engine.QueryError(BROKEN)
            model, field = _refs(dim)
            codes = [v for v in values if v is not None]
            ids = dict(model.objects.filter(tenant=tenant, **{f"{field}__in": codes})
                       .values_list(field, "pk"))
            kept = [None if v is None else ids[v] for v in values if v is None or v in ids]
        else:                                 # 是 / 否:原樣交給 engine 驗
            filters[key] = values
            continue
        if len(kept) < len(values):
            missing.append(dim.label)
        if kept:
            filters[key] = kept
    return {**stored, "filters": filters}, missing
