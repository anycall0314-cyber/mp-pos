"""門號合約到期的名單與聯絡紀錄(規則在 `contracts.py`)。

GET  /telecom-contracts/                 名單 + 各狀態幾筆
POST /telecom-contracts/<編號>/follow-up/ 標「已聯絡 / 不續約」、寫備註、取消標記

門市範圍跟報表一樣(`report_warehouse_id`):鎖倉的店員只看得到、只改得到自己門市賣出去的;沒鎖倉的可以帶 ?warehouse= 篩選。
"""
from datetime import date

from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.dates import add_months
from apps.core.warehouse_scoping import report_warehouse_id

from . import contracts as rules

PAGE = 100
MAX_PAGE = 500
TABS = ("pending", "contacted", "declined", "renewed")


def _who(user) -> str:
    """誰標的:有業務員主檔就用那個名字,沒有才用帳號。"""
    if user is None:
        return ""
    try:
        return user.sales_person.name
    except Exception:
        return user.get_username()


def _row(it, today) -> dict:
    so, plan = it.so, it.telecom_plan
    # 已續約的不用再看聯絡紀錄;其他的有紀錄就帶(待聯絡的可能只有備註、沒有狀態)
    follow = None if it.state == rules.RENEWED else getattr(it, "follow_up", None)
    return {
        "id": it.id,
        "msisdn": it.msisdn,
        "contract_end": it.contract_end.isoformat(),
        # 負的 = 已經過期幾天
        "days_left": (it.contract_end - today).days,
        "activation_date": it.activation_date.isoformat() if it.activation_date else None,
        "contract_months": it.contract_months,
        "plan_name": plan.name,
        "plan_kind": plan.kind,
        "plan_kind_label": plan.get_kind_display(),
        "carrier_name": plan.carrier.name,
        "so_id": so.id,
        "so_no": so.no,
        "doc_date": so.doc_date.isoformat(),
        "warehouse_name": so.warehouse.name,
        "sales_person_name": so.sales_person.name if so.sales_person_id else "",
        # 散客的單可以沒有客戶
        "customer_name": so.customer.name if so.customer_id else "",
        "customer_phone": (so.customer.phone or "") if so.customer_id else "",
        "member_name": so.member.name if so.member_id else "",
        "member_phone": (so.member.phone or "") if so.member_id else "",
        "state": it.state,
        "follow": None if follow is None else {
            "status": follow.status,
            "note": follow.note,
            "by": _who(follow.updated_by),
            "at": follow.updated_at.isoformat(),
        },
    }


def _key(raw):
    """翻頁的游標「到期日,明細編號」→ (日期, 編號)。格式不對丟 ValueError。"""
    day, _, pk = raw.partition(",")
    return date.fromisoformat(day), int(pk)


def _beyond(key, ascending):
    """排在這一列後面的(ascending:到期日更晚,同一天就編號更大;否則反過來)。"""
    day, pk = key
    if ascending:
        return Q(contract_end__gt=day) | Q(contract_end=day, pk__gt=pk)
    return Q(contract_end__lt=day) | Q(contract_end=day, pk__lt=pk)


def _scoped(request):
    """這個人看得到的合約(公司 + 門市範圍)。"""
    qs = rules.contracts(request.tenant)
    wid = report_warehouse_id(request)
    if wid is not None:
        qs = qs.filter(so__warehouse_id=wid)
    return qs, wid


def _load(qs):
    return qs.select_related(
        "so", "so__customer", "so__member", "so__warehouse", "so__sales_person",
        "telecom_plan", "telecom_plan__carrier", "follow_up", "follow_up__updated_by",
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def contract_list(request):
    """?state=pending(預設)| contacted | declined | renewed
    待聯絡看到多遠(擇一;都沒帶 = 今天 + 設定的月數):
      ?months=N(今天起 N 個月內)| ?until=YYYY-MM-DD | ?until=all(不限,還沒處理的全部)
    ?carrier= ?search=(門號 / 姓名 / 電話 / 單號)?page_size=
    翻頁(擇一;都沒帶 = 最前面那一頁):?after=到期日,編號(排在這一列後面的)| ?before=到期日,編號(排在這一列前面的)

    翻頁用「接在哪一列後面」而不是頁碼或第幾筆:名單上的人被標掉(自己標的、別的店員同時標的)就離開這個分頁、
    後面的往前遞補,用頁碼或筆數翻下一頁會剛好跳過遞補上來的人(該打電話的客人就漏掉了)。
    接在畫面最後一列後面拿,前面少了誰都不影響。
    """
    tenant = request.tenant
    today = timezone.localdate()
    scoped, _wid = _scoped(request)
    horizon = rules.remind_until(tenant, today)

    # 下拉選的門市、電信業者是「範圍」:分頁上的數字跟著它們走(選了中華電信,四個分頁都是中華電信的筆數)。
    # 搜尋只是在這個範圍裡找人,不影響數字
    carrier = request.query_params.get("carrier") or ""
    if carrier.isdigit():
        scoped = scoped.filter(telecom_plan__carrier_id=int(carrier))
    counts = scoped.aggregate(
        pending=Count("id", filter=Q(state=rules.OPEN, contract_end__lte=horizon)),
        overdue=Count("id", filter=Q(state=rules.OPEN, contract_end__lt=today)),
        contacted=Count("id", filter=Q(state=rules.CONTACTED)),
        declined=Count("id", filter=Q(state=rules.DECLINED)),
        renewed=Count("id", filter=Q(state=rules.RENEWED)),
    )

    tab = request.query_params.get("state") or "pending"
    if tab not in TABS:
        return Response({"detail": "state 不對"}, status=status.HTTP_400_BAD_REQUEST)
    qs = scoped
    until = None
    if tab == "pending":
        qs = qs.filter(state=rules.OPEN)
        raw = (request.query_params.get("until") or "").strip()
        months = (request.query_params.get("months") or "").strip()
        if raw != "all":
            try:
                if raw:
                    until = date.fromisoformat(raw)
                elif months:
                    # 「今天」以伺服器為準(畫面自己算日期會有時區的問題)
                    until = add_months(today, min(max(int(months), 1), 120))
                else:
                    until = horizon
            except ValueError:
                return Response({"detail": "until / months 的格式不對"}, status=status.HTTP_400_BAD_REQUEST)
            qs = qs.filter(contract_end__lte=until)
    elif tab == "contacted":
        qs = qs.filter(state=rules.CONTACTED)
    elif tab == "declined":
        qs = qs.filter(state=rules.DECLINED)
    else:
        qs = qs.filter(state=rules.RENEWED)

    search = (request.query_params.get("search") or "").strip()
    if search:
        digits = "".join(ch for ch in search if ch.isdigit())
        cond = (
            Q(so__customer__name__icontains=search) | Q(so__member__name__icontains=search)
            | Q(so__no__icontains=search)
        )
        if len(digits) >= 3:
            cond |= (
                Q(msisdn_key__contains=digits) | Q(so__member__phone__contains=digits)
                | Q(so__customer__phone__contains=digits)
            )
        qs = qs.filter(cond)

    try:
        size = max(1, min(int(request.query_params.get("page_size") or PAGE), MAX_PAGE))
    except ValueError:
        size = PAGE
    # 待聯絡、已聯絡:到期日近的在上面;不續約、已續約:新的在上面
    asc = tab in ("pending", "contacted")
    forward = ("contract_end", "id") if asc else ("-contract_end", "-id")
    backward = ("-contract_end", "-id") if asc else ("contract_end", "id")
    after = (request.query_params.get("after") or "").strip()
    before = (request.query_params.get("before") or "").strip()
    try:
        if after:
            page = list(_load(qs.filter(_beyond(_key(after), asc)).order_by(*forward))[:size])
        elif before:
            page = list(_load(qs.filter(_beyond(_key(before), not asc)).order_by(*backward))[:size])
            page.reverse()
        else:
            page = list(_load(qs.order_by(*forward))[:size])
    except ValueError:
        return Response({"detail": "after / before 的格式不對"}, status=status.HTTP_400_BAD_REQUEST)
    total = qs.count()
    if page:
        has_more = qs.filter(_beyond((page[-1].contract_end, page[-1].pk), asc)).exists()
        has_prev = qs.filter(_beyond((page[0].contract_end, page[0].pk), not asc)).exists()
    else:
        # 這一頁是空的,但名單上還有人:他們都在游標的另一邊(「後面」是空的 → 都在前面;反過來一樣)。
        # 要照實講 —— 畫面上可能還留著這一頁剛標完的那幾列,靠這個才有「上一頁 / 下一頁」可以回去找還沒處理的人
        has_more = bool(before) and not after and total > 0
        has_prev = bool(after) and total > 0
    rows = [_row(it, today) for it in page]
    return Response({
        "today": today.isoformat(),
        "remind_months": tenant.contract_remind_months,
        "remind_until": horizon.isoformat(),
        "until": until.isoformat() if until else None,
        "counts": counts,
        "total": total,
        "has_more": has_more,
        "has_prev": has_prev,
        "page_size": size,
        "results": rows,
    })


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def contract_follow_up(request, pk):
    """body: {"status": "contacted" | "declined" | ""(還沒聯絡上 / 回到待聯絡), "note": "一句備註"}
    狀態與備註都空的 = 整筆紀錄拿掉。"""
    wid = report_warehouse_id(request)
    try:
        rules.set_follow_up(
            request.tenant, pk, request.data.get("status"), request.data.get("note"),
            request.user, warehouse_id=wid,
        )
    except rules.ContractError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    it = _load(rules.contracts(request.tenant).filter(pk=pk)).first()
    if it is None:
        # 存好的同時那張單被作廢 / 退掉了:這一筆已經不算合約,講出來讓畫面重抓名單
        return Response({"detail": "這張單剛剛被作廢或退掉了,請重新整理名單"},
                        status=status.HTTP_400_BAD_REQUEST)
    return Response(_row(it, timezone.localdate()))
