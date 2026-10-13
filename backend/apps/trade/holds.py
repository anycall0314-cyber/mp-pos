"""被同行訂走、還沒出貨的那幾台中古機,門市要賣的時候怎麼辦(紅隊 2026-10-14 第 1 條;owner 定:出貨之前賣家可以抽回)。

`sales.services.commit_sales_order` 鎖到序號之後呼叫 `before_sale`:
- 這張銷貨單裡有被訂走的機器、開單的人沒有明講要抽回 → 整張擋下來(`Held`,帶是哪幾台、哪一張批發單、哪一個同行),畫面讓他選。
- 有明講(`so.trade_release` 裡有那一台)→ 那一行當下取消(同行那邊看得到),然後照常賣。
**擋在過帳這一層**:不管從哪個畫面、哪一支 API 開的銷貨單都一樣,不是只靠畫面提醒。

`after_sale`:賣掉的機器從批發清單下架(之後退回來不會自己回到清單)。
`guard_void`:批發出貨開的銷貨單不能從銷貨單那邊作廢(要從批發單「取消出貨」,兩邊的數字才會一起回去)。
"""
from django.utils import timezone

from .models import TradeOrder, TradeOrderLine, TradeShipment, TradeUnit

RETAIL_REASON = "賣家改賣給現場客人"


def held_lines(tenant, serial_ids, *, lock=False):
    """這幾台裡被訂著的(每一台最多一行)。`lock` = 先把那幾張批發單鎖住再讀(要改它們的人用)。

    **一律先鎖批發單那一列、才動它的明細**(買家取消、賣家不出、出貨都是這個順序):這裡如果先鎖明細,
    跟「買家整張取消」同時來會互相等。序號在呼叫的人手上鎖著,所以鎖單的這段時間不會有人新訂這幾台。
    """
    serial_ids = list(serial_ids)
    if not serial_ids:
        return []
    rows = TradeOrderLine.objects.filter(tenant=tenant, unit_id__in=serial_ids, holding=True)
    if lock:
        order_ids = sorted(set(rows.values_list("order_id", flat=True)))
        list(TradeOrder.objects.select_for_update().filter(pk__in=order_ids).order_by("id").values_list("pk", flat=True))
    return list(rows.select_related("order__partner", "unit").order_by("id"))


def describe(lines) -> list[dict]:
    return [{
        "serial": line.unit_id, "serial_no": line.unit.serial_no, "name": line.name,
        "order_no": line.order.no, "partner": line.order.partner.name,
    } for line in lines]


def before_sale(so, serial_ids, error):
    """`error` = 銷貨那邊的錯誤類別(不直接匯入:銷貨與批發互相用到對方)。"""
    lines = held_lines(so.tenant, serial_ids, lock=True)
    if not lines:
        return
    release = {int(x) for x in (getattr(so, "trade_release", None) or ()) if str(x).isdigit()}
    blocked = [line for line in lines if line.unit_id not in release]
    if blocked:
        first = blocked[0]
        exc = error(
            f"{first.unit.serial_no} 已經被同行「{first.order.partner.name}」訂走({first.order.no})。"
            "要賣給現場客人請選「賣給現場客人」(同行那一台會取消)")
        exc.payload = {"detail": str(exc), "code": "trade_hold", "units": describe(blocked)}
        raise exc
    from . import orders

    for line in lines:
        orders.drop(line.order, line, line.open_qty, reason=RETAIL_REASON)


def after_sale(tenant, serial_ids) -> None:
    serial_ids = list(serial_ids)
    if serial_ids:
        TradeUnit.objects.filter(tenant=tenant, serial_id__in=serial_ids, is_listed=True).update(
            is_listed=False, updated_at=timezone.now())


def guard_void(so, error) -> None:
    if getattr(so, "trade_void_ok", False):
        return
    shipment = TradeShipment.objects.filter(sales_order=so, is_void=False).select_related("order").first()
    if shipment is not None:
        raise error(f"這張是批發單 {shipment.order.no} 出貨開的,請到「批發單」取消那一次出貨")
