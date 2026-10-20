"""發票明細:有發票號碼的銷貨單,一張發票一列。只讀。

owner 2026-10-12(取舊歐睿報表的優點;舊 FI012 開立發票表):發票的類型、號碼、日期、統編、金額銷貨單上本來就有記,
但沒有一張表逐張列出來 —— 要對這一期開了哪些、哪幾張作廢,只能到銷貨單清單一張一張看。

只列單上記的,不新定稅務規則(沒有折讓單、不分應稅 / 零稅率小計、不跟財政部的平台核對):
- 一列 = 一張有發票號碼的銷貨單(免用發票、沒有號碼的不列)。日期看發票日期,沒有填(自己打號碼的)看單據日期。
- 狀態(動手前紅隊第 3 條):
  - 作廢 = 銷貨單整張作廢;或銷退時勾了「作廢原發票」而且那張銷退還在(銷退只能整張退,退的金額 = 發票金額)。
  - **待查** = 標了「原發票已作廢」,但退的金額跟發票金額對不起來 —— 實際上就是那張銷退後來又作廢了
    (作廢銷退不會把發票的記號拿掉,`services.void_sales_return`):貨沒有退、發票卻記成作廢。不默默算、也不默默不算,單獨列。
  - 其餘 = 正常(有銷退但沒有作廢原發票的也是:發票還在,實務上要另外開折讓)。
- 合計(紅隊第 2 條):金額只算正常的那幾張的**發票面額**(沒有扣銷退);作廢幾張、待查幾張與金額、銷退合計各自一格。
- 「日期」可以改成照銷退日(紅隊第 1 條):列出這段期間有銷退的發票(不管是哪一期開的)、「銷退」那一欄是這段期間退的。
  上一期開的發票這一期才退,照發票日看這一期的表上不會有它。
- **作廢日**(owner 2026-10-12「作廢要日期」):銷貨單作廢 = 作廢那一刻的日期(`SalesOrder.voided_at`,系統記的;有這一欄之前就作廢的舊單是空的);
  銷退時作廢原發票 = 那張銷退的日期。待查的沒有(記成作廢,但那張銷退已經不在了)。
  「日期」可以改成照作廢日:列出這段期間作廢的發票(不管是哪一期開的)—— 上一期開、這一期才作廢的在這裡找;沒有記到作廢日的舊單只在「照發票日」看得到。
  **報表怎麼算沒有變**:作廢的單照舊整張不算、算在原本開單那一天。
- 要有「發票明細」那一項;鎖在門市的帳號只看自己門市。

**開立發票彙總表**(`summary`;owner 2026-10-20:「我每個單數月，要傳發票開立明細彙總表excel給會計師報帳」)——
照舊歐睿給會計師的那一份(FI012 的彙總)排,讓會計師不用重新看懂:
- 上段「開立」:期間內(看發票日)有發票號碼的銷貨單,**同一天 × 門市 × 發票類型 × 字軌一列**,號碼寫當天第一張 ~ 最後一張。
  **作廢的單也算**(號碼用掉了;舊系統也是開了又退的算在當天),在下段扣回去。
- 下段「作廢與退回」一張一列、負數:期間內(看退的那一天)沒作廢的銷退 —— 作廢原發票的「退貨作廢」、沒有的「退貨折讓」;
  期間內(看作廢的那一天;沒記到作廢時間的舊單看發票日)作廢的銷貨單「銷貨作廢」。
  **一張發票只會扣一次**:有有效銷退的銷貨單不能作廢(要先作廢銷退),作廢了的銷退不列。
- 金額 = 發票面額(單上的未稅、稅額、含稅;不收錢的那幾行本來就不在裡面),不是實收。總計 = 上段 + 下段(下段是負的)。
- 條件只看期間、門市、發票類型(頁面上的狀態、搜尋、日期看哪一個不套)。
"""
from decimal import Decimal

from django.db.models import Case, CharField, Count, DateField, DecimalField, F, OuterRef, Q, Subquery, Sum, Value, When
from django.db.models.functions import Coalesce, TruncDate
from rest_framework.decorators import api_view
from rest_framework.response import Response

from apps.core.warehouse_scoping import report_warehouse_id
from apps.inventory import reports as stock_reports
from apps.inventory.report_views import listing
from apps.tenants import abilities
from apps.tenants.models import InvoiceType

from .models import SalesOrder, SalesReturn

OK, VOID, CHECK = "ok", "void", "check"
STATES = {OK: "正常", VOID: "作廢", CHECK: "待查"}
BY_INVOICE, BY_RETURN, BY_VOID = "invoice", "return", "void"
BY = {BY_INVOICE: "發票日", BY_RETURN: "銷退日", BY_VOID: "作廢日"}

_MONEY = DecimalField(max_digits=18, decimal_places=2)
_ZERO = Value(Decimal("0"), output_field=_MONEY)
_CENT = Decimal("0.01")


def _money(value):
    """跟其他報表同一種寫法:兩位小數的字串。"""
    return str(Decimal(value or 0).quantize(_CENT))


def _returns(tenant, start=None, end=None):
    """這張銷貨單沒作廢的銷退。給了期間就只看那一段退的。"""
    qs = SalesReturn.objects.filter(tenant=tenant, original_so=OuterRef("pk"), is_void=False)
    if start is not None:
        qs = qs.filter(doc_date__gte=start, doc_date__lte=end)
    return qs.order_by()


def _returned(tenant, start=None, end=None):
    """退了多少(含稅)。"""
    total = _returns(tenant, start, end).values("original_so").annotate(v=Sum("total")).values("v")
    return Coalesce(Subquery(total, output_field=_MONEY), _ZERO)


def invoices(tenant, *, start, end, by=BY_INVOICE, warehouse_id=None, invoice_form="", state="", search=""):
    """照條件列發票(照號碼排)。by = 期間看發票日、銷退日還是作廢日。"""
    if by not in BY:
        raise stock_reports.ReportError("日期只能照發票日、銷退日或作廢日")
    if state and state not in STATES:
        raise stock_reports.ReportError("沒有這種狀態")
    qs = SalesOrder.objects.filter(tenant=tenant).exclude(invoice_no="").annotate(
        day=Coalesce("invoice_date", "doc_date"),
        returned_all=_returned(tenant),
        return_date=Subquery(_returns(tenant).order_by("-doc_date", "-id").values("doc_date")[:1]),
    )
    if by == BY_RETURN:
        in_period = SalesReturn.objects.filter(
            tenant=tenant, is_void=False, doc_date__gte=start, doc_date__lte=end).order_by()
        qs = qs.filter(pk__in=in_period.values("original_so_id")).annotate(returned=_returned(tenant, start, end))
    elif by == BY_INVOICE:
        qs = qs.filter(day__gte=start, day__lte=end).annotate(returned=F("returned_all"))
    else:
        qs = qs.annotate(returned=F("returned_all"))
    qs = qs.annotate(state=Case(
        When(is_void=True, then=Value(VOID)),
        When(invoice_voided=True, returned_all=F("total"), then=Value(VOID)),
        When(invoice_voided=True, then=Value(CHECK)),
        default=Value(OK), output_field=CharField(),
    )).annotate(void_date=Case(
        # 銷貨單作廢:作廢那一刻在這裡的日期(系統的時區;半夜十二點多作廢的算當天,不是世界時間的前一天)
        When(is_void=True, then=TruncDate("voided_at")),
        # 銷退時作廢原發票:那張銷退的日期
        When(state=VOID, then=F("return_date")),
        default=None, output_field=DateField(),
    ))
    if by == BY_VOID:       # 這段期間作廢的(不管哪一期開的);沒有記到作廢日的、待查的不在這裡
        qs = qs.filter(state=VOID, void_date__gte=start, void_date__lte=end)
    if warehouse_id is not None:
        qs = qs.filter(warehouse_id=warehouse_id)
    if invoice_form:
        qs = qs.filter(invoice_form=invoice_form)
    if state:
        qs = qs.filter(state=state)
    for word in stock_reports.words(search):        # 發票號碼 / 統編 / 銷貨單號,每一段都要有
        qs = qs.filter(Q(invoice_no__icontains=word) | Q(buyer_tax_id__icontains=word) | Q(no__icontains=word))
    return qs.select_related("warehouse", "customer").order_by("invoice_no", "id")


def totals(queryset):
    """照同樣的條件全部加起來(不是只有這一頁)。金額是正常那幾張的發票面額,沒有扣銷退。"""
    normal = Q(state=OK)
    # 加總的名字不能跟欄位同名(同一次加總裡後面的會把它當成前一個加總的結果)
    got = queryset.order_by().aggregate(
        n_ok=Count("id", filter=normal),
        n_void=Count("id", filter=Q(state=VOID)),
        n_check=Count("id", filter=Q(state=CHECK)),
        s_subtotal=Sum("subtotal", filter=normal),
        s_tax=Sum("tax_amount", filter=normal),
        s_total=Sum("total", filter=normal),
        s_check=Sum("total", filter=Q(state=CHECK)),
        s_void=Sum("total", filter=Q(state=VOID)),
        s_returned=Sum("returned", filter=normal),
    )
    money = {"subtotal": "s_subtotal", "tax": "s_tax", "total": "s_total", "check_total": "s_check",
             "void_total": "s_void", "returned": "s_returned"}
    return {
        "ok_count": got["n_ok"], "void_count": got["n_void"], "check_count": got["n_check"],
        **{key: _money(got[name]) for key, name in money.items()},
    }


def rows_for(tenant):
    names = dict(InvoiceType.objects.filter(tenant=tenant).values_list("code", "name"))

    def rows(page):
        return [{
            "id": so.id,
            "date": so.day,
            "invoice_no": so.invoice_no,
            "form": names.get(so.invoice_form, so.invoice_form),
            "buyer_tax_id": so.buyer_tax_id,
            "doc": {"kind": "sale", "id": so.id, "no": so.no},
            "store": so.warehouse.name if so.warehouse_id else "",
            # 跟銷貨單清單同一個規則:這張單記的來源名稱,舊單沒有就是客戶
            "customer": so.source_name or (so.customer.name if so.customer_id else ""),
            "tax_method": so.get_tax_method_display(),
            "subtotal": _money(so.subtotal),
            "tax": _money(so.tax_amount),
            "total": _money(so.total),
            "state": so.state,
            "void_date": so.void_date,
            "returned": _money(so.returned),
            "return_date": so.return_date,
        } for so in page]

    return rows


def _choices(labels):
    return [{"key": key, "label": label} for key, label in labels.items()]


# ---- 開立發票彙總表 ----

SALE_VOID, RETURN_VOID, RETURN_KEEP = "sale_void", "return_void", "return_keep"
REVERSALS = {SALE_VOID: "銷貨作廢", RETURN_VOID: "退貨作廢", RETURN_KEEP: "退貨折讓"}


def _sums(rows):
    keys = ("subtotal", "tax", "total")
    return {k: _money(sum((r[k] for r in rows), Decimal("0"))) for k in keys}


def summary(tenant, *, start, end, warehouse_id=None, invoice_form=""):
    """開立發票彙總表(寫法見開頭)。回 issued(上段)、reversed(下段,負數)、totals。"""
    names = dict(InvoiceType.objects.filter(tenant=tenant).values_list("code", "name"))
    base = SalesOrder.objects.filter(tenant=tenant).exclude(invoice_no="")
    if warehouse_id is not None:
        base = base.filter(warehouse_id=warehouse_id)
    if invoice_form:
        base = base.filter(invoice_form=invoice_form)

    groups = {}
    issued = base.annotate(day=Coalesce("invoice_date", "doc_date")).filter(day__gte=start, day__lte=end).values(
        "day", "warehouse_id", "warehouse__name", "invoice_form", "invoice_no", "subtotal", "tax_amount", "total")
    for so in issued:
        number = so["invoice_no"].strip().upper()
        key = (so["day"], so["warehouse_id"], so["invoice_form"], number[:2])
        g = groups.setdefault(key, {
            "_wh": so["warehouse_id"] or 0, "date": so["day"], "store": so["warehouse__name"] or "", "form": names.get(so["invoice_form"], so["invoice_form"]),
            "numbers": [], "subtotal": Decimal("0"), "tax": Decimal("0"), "total": Decimal("0")})
        g["numbers"].append(number)
        g["subtotal"] += so["subtotal"]
        g["tax"] += so["tax_amount"]
        g["total"] += so["total"]
    upper = []
    for g in groups.values():
        numbers = sorted(g.pop("numbers"))
        upper.append({**g, "first": numbers[0], "last": numbers[-1], "count": len(numbers)})
    upper.sort(key=lambda r: (r["date"], r["_wh"], r["form"], r["first"]))       # 同一天照門市(編號)排

    lower = []
    returns = SalesReturn.objects.filter(
        tenant=tenant, is_void=False, doc_date__gte=start, doc_date__lte=end, original_so__in=base.values("pk"),
    ).values("doc_date", "original_so__warehouse_id", "original_so__warehouse__name", "original_so__invoice_form", "original_so__invoice_no",
             "void_original_invoice", "subtotal", "tax_amount", "total")
    for sr in returns:
        lower.append({
            "_wh": sr["original_so__warehouse_id"] or 0, "date": sr["doc_date"], "store": sr["original_so__warehouse__name"] or "",
            "form": names.get(sr["original_so__invoice_form"], sr["original_so__invoice_form"]),
            "invoice_no": sr["original_so__invoice_no"].strip().upper(),
            "kind": RETURN_VOID if sr["void_original_invoice"] else RETURN_KEEP,
            "subtotal": -sr["subtotal"], "tax": -sr["tax_amount"], "total": -sr["total"]})
    # 作廢那一刻在這裡的日期(跟發票明細的作廢日同一個算法);沒記到作廢時間的舊單看發票日(上段也在那一天)
    voided = base.filter(is_void=True).annotate(
        day=Coalesce(TruncDate("voided_at"), "invoice_date", "doc_date", output_field=DateField()),
    ).filter(day__gte=start, day__lte=end).values(
        "day", "warehouse_id", "warehouse__name", "invoice_form", "invoice_no", "subtotal", "tax_amount", "total")
    for so in voided:
        lower.append({
            "_wh": so["warehouse_id"] or 0, "date": so["day"], "store": so["warehouse__name"] or "", "form": names.get(so["invoice_form"], so["invoice_form"]),
            "invoice_no": so["invoice_no"].strip().upper(), "kind": SALE_VOID,
            "subtotal": -so["subtotal"], "tax": -so["tax_amount"], "total": -so["total"]})
    lower.sort(key=lambda r: (r["date"], r["_wh"], r["invoice_no"]))

    issued_sum, reversed_sum = _sums(upper), _sums(lower)
    def money(row):
        return {**{k: v for k, v in row.items() if k != "_wh"}, **{k: _money(row[k]) for k in ("subtotal", "tax", "total")}}
    return {
        "issued": [money(r) for r in upper],
        "reversed": [money(r) for r in lower],
        "totals": {
            "issued": issued_sum,
            "reversed": reversed_sum,
            "net": {k: _money(Decimal(issued_sum[k]) + Decimal(reversed_sum[k])) for k in issued_sum},
        },
    }


@api_view(["GET"])
def sales_invoice_summary(request):
    """開立發票彙總表。?from= &to= &warehouse= &form=(發票類型代碼)。權限跟發票明細同一項。"""
    abilities.require(request.user, abilities.REPORT_INVOICES)
    p = request.query_params
    try:
        start, end = stock_reports.parse_range(p)
    except stock_reports.ReportError as exc:
        return Response({"detail": str(exc)}, status=400)
    with stock_reports.one_moment():           # 上段與下段要是同一刻的
        got = summary(request.tenant, start=start, end=end, warehouse_id=report_warehouse_id(request),
                      invoice_form=(p.get("form") or "").strip())
    return Response({
        "from": start.isoformat(), "to": end.isoformat(), **got,
        # 下段每一列「說明」的字由伺服器給(畫面不自己寫死)
        "choices": {"kind": _choices(REVERSALS)},
    })


@api_view(["GET"])
def sales_invoice_report(request):
    """發票明細。?from= &to= &by=invoice|return|void &warehouse= &form=(發票類型代碼)&state=ok|void|check &search= &page= &export=1"""
    abilities.require(request.user, abilities.REPORT_INVOICES)
    p = request.query_params
    by = (p.get("by") or BY_INVOICE).strip()
    try:
        start, end = stock_reports.parse_range(p)
        queryset = invoices(
            request.tenant, start=start, end=end, by=by, warehouse_id=report_warehouse_id(request),
            invoice_form=(p.get("form") or "").strip(), state=(p.get("state") or "").strip(),
            search=p.get("search", ""),
        )
    except stock_reports.ReportError as exc:
        return Response({"detail": str(exc)}, status=400)
    with stock_reports.one_moment():           # 這一頁的列與合計要是同一刻的
        return listing(request, queryset, rows_for(request.tenant), {
            "from": start.isoformat(), "to": end.isoformat(), "by": by,
            "totals": totals(queryset),
            # 下拉的選項與字由伺服器給(畫面不自己寫死)
            "choices": {"by": _choices(BY), "state": _choices(STATES)},
        })
