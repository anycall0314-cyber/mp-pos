"""維修月報:期間內完工的維修單 —— 合計、每個人分到多少、逐筆。只讀。

owner 2026-10-12(取舊歐睿報表的優點;舊 MNT015 維修單月報表)。先定了一件事:**「工資是分業績的」**——
工資、內部結算價只是收件人與技師之間怎麼分,不是公司付出去的錢。所以維修毛利全系統只有一份算法(`services.money_of`):
自修 / 內轉 = 客戶實付 − 零件成本;委外給外廠 = 客戶實付 − 委外實際費用。這一頁、維修單清單、開單頁都是這個數字。

- 只算**已完成、沒作廢**的維修單;期間看**完工那一天**(店裡的時區)。還沒完工的在維修單清單看。
- 合計:件數、客戶實付、零件成本、委外費用、毛利(每一張、合計都是 實付 − 零件成本 − 委外費用 = 毛利)。
- 人員:每個人收件幾件、維修幾件、分到多少(個人毛利分解 `services.compute_personal_margin`);全部的人加起來 = 合計的毛利。
  自修而且沒有另外的技師 = 收件人自己修(收件、維修各算一件)。沒有填收件人的歸「(未指定)」。
- 要有「維修月報」那一項;鎖在門市的帳號只看自己門市收件的維修單。
- 維修收的錢沒有進營業日報(維修單上沒有記客人怎麼付錢);這一頁的「客戶實付」是單上記的數字。
"""
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response

from apps.core.warehouse_scoping import report_warehouse_id
from apps.inventory import reports as stock_reports
from apps.inventory.report_views import listing
from apps.tenants import abilities

from .models import RepairOrder
from .services import IN_HOUSE, VENDOR, WAYS, compute_personal_margin, money_of

NOBODY = "(未指定)"
_CENT = Decimal("0.01")
_ZERO = Decimal("0")


def _money(value) -> str:
    """跟其他報表同一種寫法:兩位小數的字串。"""
    return str(Decimal(value or 0).quantize(_CENT))


def completed(tenant, *, start, end, warehouse_id=None, way=""):
    """期間內完工、沒作廢的維修單(照完工的先後),每一張帶著算好的錢。way = 只看哪一種修法。"""
    if way and way not in WAYS:
        raise stock_reports.ReportError("沒有這種方式")
    orders = RepairOrder.objects.filter(
        tenant=tenant, is_void=False, status=RepairOrder.Status.COMPLETED,
        completed_at__gte=stock_reports.day_start(start),
        completed_at__lt=stock_reports.day_start(end + timedelta(days=1)),
    )
    if warehouse_id is not None:
        orders = orders.filter(warehouse_id=warehouse_id)
    orders = (orders.select_related("warehouse", "sales_person", "technician")
              .prefetch_related("parts__part_product").order_by("completed_at", "id"))
    out = []
    for order in orders:
        money = money_of(order)
        if way and money["way"] != way:
            continue
        out.append((order, money, compute_personal_margin(order)))
    return out


def _row(order, money):
    return {
        "id": order.id,
        "date": timezone.localtime(order.completed_at).date(),
        "doc": {"kind": "repair", "id": order.id, "no": order.no},
        "store": order.warehouse.name if order.warehouse_id else "",
        "model": order.host_model_name,
        "way": money["way"],
        "receiver": order.sales_person.name if order.sales_person_id else "",
        # 沒有另外的技師 = 收件人自己修(自修);委外給外廠的沒有技師
        "technician": order.technician.name if order.technician_id else "",
        "paid": _money(money["paid"]),
        "parts": _money(money["parts"]),
        "outside": _money(money["outside"]),
        "margin": _money(money["margin"]),
    }


def totals(found):
    return {
        "count": len(found),
        **{key: _money(sum((money[key] for _, money, _ in found), _ZERO))
           for key in ("paid", "parts", "outside", "margin")},
    }


def people(found):
    """每個人:收件幾件、維修幾件、分到多少。分到最多的在前面。"""
    table = {}

    def entry(person):
        key = person.id if person else None
        return table.setdefault(key, {
            "id": key, "name": person.name if person else NOBODY, "received": 0, "repaired": 0, "amount": _ZERO})

    for order, money, split in found:
        receiver = entry(order.sales_person)
        receiver["received"] += 1
        receiver["amount"] += split["sales_person_amount"]
        another = order.technician if order.technician_id and order.technician_id != order.sales_person_id else None
        if another:                                   # 另有技師(自修分工、內轉)
            worker = entry(another)
            worker["repaired"] += 1
            worker["amount"] += split["technician_amount"]
        elif money["way"] == IN_HOUSE:                # 收件人自己修
            receiver["repaired"] += 1
    rows = sorted(table.values(), key=lambda r: (-r["amount"], r["name"], r["id"] or 0))
    return [{**r, "amount": _money(r["amount"])} for r in rows]


@api_view(["GET"])
def repair_monthly_report(request):
    """維修月報。?from= &to=(完工日)&warehouse= &way=in_house|vendor|transfer &page= &export=1"""
    abilities.require(request.user, abilities.REPORT_REPAIRS)
    p = request.query_params
    try:
        start, end = stock_reports.parse_range(p)
        found = completed(request.tenant, start=start, end=end, warehouse_id=report_warehouse_id(request),
                          way=(p.get("way") or "").strip())
    except stock_reports.ReportError as exc:
        return Response({"detail": str(exc)}, status=400)
    return listing(request, [_row(order, money) for order, money, _ in found], lambda page: page, {
        "from": start.isoformat(), "to": end.isoformat(),
        "totals": totals(found),
        "people": people(found),
        # 下拉的選項與字由伺服器給(畫面不自己寫死)
        "choices": {"way": [{"key": key, "label": label} for key, label in WAYS.items()]},
    })
