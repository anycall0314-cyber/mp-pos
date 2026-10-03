"""舊 POS 歷史與對照的 API。

- 會員頁看舊紀錄:登入的這家公司使用者都可以,但只看得到「已確認對照到這位會員」的舊會員;
  總額與筆數由後端照完整篩選條件計算,不是加總畫面上那一頁。
- 對照、待核、原始證據(快照全文、報表列原文、來源網址):只有公司管理員。
- 全部都只看自己公司的資料;別家公司的編號猜中了也只會得到「找不到」。
"""
from datetime import date

from django.db.models import Count, F, Max, OuterRef, Q, Subquery, Sum
from django.db.models.functions import Coalesce
from rest_framework import permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


from . import mapping
from .models import (
    HistoryImportBatch,
    LegacyDocument,
    LegacyItem,
    LegacyMappingLog,
    LegacyMember,
    LegacyProductMap,
    LegacySalespersonMap,
    LegacySourceException,
    LegacyStoreMap,
    MapStatus,
)



class Paging(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200


def _is_company_admin(request) -> bool:
    """這家公司自己的管理員。平台管理員不算:平台角色不能從一般網址看別家公司的
    舊會員個資、原始證據或改對照(要代管得另外走平台後台)。"""
    user = request.user
    if not user or not user.is_authenticated:
        return False
    profile = getattr(user, "profile", None)
    tenant = _tenant(request)
    return bool(
        profile and profile.role == "tenant_admin" and tenant is not None
        and profile.tenant_id == tenant.pk
    )


class IsCompanyAdmin(permissions.BasePermission):
    message = "需要公司管理員權限"

    def has_permission(self, request, view):
        return _is_company_admin(request)


def _tenant(request):
    return getattr(request, "tenant", None)


def _bad(message, code=status.HTTP_400_BAD_REQUEST):
    return Response({"detail": str(message)}, status=code)


def _date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return False


def _money(minor):
    return {"minor": minor, "display": _money_text(minor)} if minor is not None else None


def _money_text(minor):
    sign = "-" if minor < 0 else ""
    whole, cents = divmod(abs(minor), 100)
    return f"{sign}{whole:,}" + (f".{cents:02d}" if cents else "")


# ─────────────────────────── 會員頁:舊紀錄 ───────────────────────────
def _member(request, value):
    from apps.parties.models import Member

    if not str(value or "").isdigit():
        return None
    return Member.objects.filter(tenant=_tenant(request), pk=int(value)).first()


def _doc_row(d):
    return {
        "id": d.id,
        "source": "舊 POS",
        "document_date": d.document_date,
        "store": d.store_name_raw.strip(),
        "document_type": d.document_type_raw,
        "document_number": d.document_number_raw,
        "item_count": d.item_count,
        "amount": _money(d.report_amount_minor),
        "net_amount": _money(d.net_amount_minor),
        "legacy_member": d.legacy_member.display_id,
    }


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def history(request):
    """某位會員的舊 POS 單據(分頁)+ 完整篩選範圍的合計 + 待核提示。"""
    member = _member(request, request.query_params.get("member"))
    if member is None:
        return _bad("找不到這位會員", status.HTTP_404_NOT_FOUND)
    linked = LegacyMember.objects.filter(
        tenant=_tenant(request), member=member, status=MapStatus.CONFIRMED
    )
    docs = LegacyDocument.objects.filter(
        tenant=_tenant(request), legacy_member__in=linked
    ).select_related("legacy_member")
    p = request.query_params
    start, end = _date(p.get("date_from")), _date(p.get("date_to"))
    if start is False or end is False:
        return _bad("日期格式要 YYYY-MM-DD")
    if start:
        docs = docs.filter(document_date__gte=start)
    if end:
        docs = docs.filter(document_date__lte=end)
    if p.get("store"):
        docs = docs.filter(store_name_raw__contains=p["store"].strip())
    if p.get("doc_type"):
        docs = docs.filter(document_type_raw=p["doc_type"].strip())
    if p.get("doc_no"):
        docs = docs.filter(document_number_raw__contains=p["doc_no"].strip())
    docs = docs.order_by("-document_date", "-id")

    totals = docs.aggregate(
        documents=Count("id"), items=Coalesce(Sum("item_count"), 0),
        raw=Coalesce(Sum("report_amount_minor"), 0), net=Coalesce(Sum("net_amount_minor"), 0),
    )
    # 待核是以「人」為單位的提示(那位會員有來源差異),不跟著日期 / 店別篩選變
    pending = LegacySourceException.objects.filter(
        tenant=_tenant(request), legacy_member__in=linked,
        status=LegacySourceException.Status.OPEN,
    ).aggregate(
        count=Count("id"), documents=Coalesce(Sum("document_count"), 0),
        items=Coalesce(Sum("line_count"), 0),
    )
    pager = Paging()
    page = pager.paginate_queryset(docs, request)
    response = pager.get_paginated_response([_doc_row(d) for d in page])
    response.data["summary"] = {
        # 已核對的舊紀錄;待核的另外列,不併進這裡
        "documents": totals["documents"], "items": totals["items"],
        "amount": _money(totals["raw"]), "net_amount": _money(totals["net"]),
        "linked_legacy_members": [lm.display_id for lm in linked],
    }
    response.data["pending"] = pending
    return response


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def history_document(request, pk):
    """一張舊單的全部明細(含負數、零元)。原始列原文只給管理員。

    一般使用者要帶 `member`(正在看的那位會員),而且這張單的舊會員必須已經確認對照到
    那位會員;不能拿單據編號去翻別人的舊單。管理員可以看任何一張(對照時要用)。
    """
    admin = _is_company_admin(request)
    qs = LegacyDocument.objects.filter(tenant=_tenant(request), pk=pk)
    if not admin:
        member = _member(request, request.query_params.get("member"))
        if member is None:
            return _bad("找不到這張單", status.HTTP_404_NOT_FOUND)
        qs = qs.filter(
            legacy_member__status=MapStatus.CONFIRMED, legacy_member__member=member
        )
    doc = qs.select_related("legacy_member").first()
    if doc is None:
        return _bad("找不到這張單", status.HTTP_404_NOT_FOUND)
    items = []
    for i in doc.items.order_by("item_ordinal"):
        row = {
            "ordinal": i.item_ordinal,
            "product_code": i.product_code_raw.strip(),
            "product_name": i.product_name_raw,
            "quantity": i.quantity_decimal,
            "unit_price": _money(i.unit_price_minor),
            "amount": _money(i.amount_minor),
            "net_amount": _money(i.amount_minor * i.net_sign),
            "salesperson": i.salesperson_raw.strip(),
            "customer_name": i.customer_name_raw.strip(),
            "remarks": i.remarks_raw.strip(),
            "promotion": i.promotion_raw.strip(),
            "points": i.points_raw.strip(),
        }
        if admin:
            row["source_row"] = i.source_row_json
        items.append(row)
    data = _doc_row(doc)
    data["items"] = items
    return Response(data)


# ─────────────────────────── 管理員:舊會員對照 ───────────────────────────
def _legacy_member_row(lm, with_totals=None):
    row = {
        "id": lm.id,
        "source_member_id": lm.display_id,
        "source_member_id_exact": lm.source_member_id,
        "name": lm.name_raw.strip(),
        "phone": lm.phone_raw.strip(),
        "status": lm.status,
        "member": (
            {"id": lm.member_id, "code": lm.member.code, "name": lm.member.name}
            if lm.member_id else None
        ),
        "method": lm.method,
        "confirmed_at": lm.confirmed_at,
    }
    if with_totals is not None:
        row.update(with_totals)
    return row


@api_view(["GET"])
@permission_classes([IsCompanyAdmin])
def legacy_members(request):
    p = request.query_params
    qs = LegacyMember.objects.filter(tenant=_tenant(request)).select_related("member")
    if p.get("status") in (MapStatus.UNMAPPED, MapStatus.CONFIRMED):
        qs = qs.filter(status=p["status"])
    q = (p.get("q") or "").strip()
    if q:
        digits = "".join(ch for ch in q if ch.isdigit())
        cond = Q(source_member_id__contains=q) | Q(name_raw__contains=q)
        if len(digits) >= 4:
            cond |= Q(phone_digits__contains=digits)
        qs = qs.filter(cond)
    qs = qs.annotate(
        doc_count=Count("documents", distinct=True),
        net=Coalesce(Sum("documents__net_amount_minor"), 0),
        last_date=Max("documents__document_date"),
    ).order_by(F("last_date").desc(nulls_last=True), "id")
    pager = Paging()
    page = pager.paginate_queryset(qs, request)
    response = pager.get_paginated_response([
        _legacy_member_row(lm, {"documents": lm.doc_count, "net_amount": _money(lm.net),
                                "last_date": lm.last_date})
        for lm in page
    ])
    base = LegacyMember.objects.filter(tenant=_tenant(request))
    response.data["summary"] = {
        "total": base.count(),
        "confirmed": base.filter(status=MapStatus.CONFIRMED).count(),
        "unmapped": base.filter(status=MapStatus.UNMAPPED).count(),
        "open_exceptions": LegacySourceException.objects.filter(
            tenant=_tenant(request), status=LegacySourceException.Status.OPEN
        ).count(),
    }
    return response


def _own_legacy_member(request, pk):
    return (
        LegacyMember.objects.filter(tenant=_tenant(request), pk=pk)
        .select_related("member").first()
    )


@api_view(["GET"])
@permission_classes([IsCompanyAdmin])
def legacy_member_detail(request, pk):
    lm = _own_legacy_member(request, pk)
    if lm is None:
        return _bad("找不到這個舊會員", status.HTTP_404_NOT_FOUND)
    data = _legacy_member_row(lm)
    data["candidates"] = [
        {"id": m.id, "code": m.code, "name": m.name, "phone": m.phone, "reason": how.label}
        for m, how in mapping.member_candidates(lm)
    ]
    data["periods"] = [
        {"batch": s.batch_id, "period": [s.batch.period_start, s.batch.period_end],
         "captured_at": s.captured_at}
        for s in lm.source_snapshots.select_related("batch").order_by("batch_id")
    ]
    data["exceptions"] = [_exception_row(e) for e in lm.source_exceptions.all()]
    data["log"] = [
        {"at": x.created_at, "action": x.get_action_display(), "label": x.target_label,
         "by": x.by.get_username() if x.by else "", "note": x.note}
        for x in LegacyMappingLog.objects.filter(
            tenant=lm.tenant, kind=LegacyMappingLog.Kind.MEMBER,
            source_system=lm.source_system, key_raw=lm.source_member_id[:300],
        ).select_related("by")[:20]
    ]
    return Response(data)


@api_view(["GET"])
@permission_classes([IsCompanyAdmin])
def legacy_member_evidence(request, pk):
    """原始證據:各期間的明細頁全文與雜湊、清單列原文、來源網址。只給管理員。"""
    lm = _own_legacy_member(request, pk)
    if lm is None:
        return _bad("找不到這個舊會員", status.HTTP_404_NOT_FOUND)
    return Response({
        "source_member_id_exact": lm.source_member_id,
        "source_member_id_raw": lm.source_member_id_raw,
        "snapshots": [
            {"batch": s.batch_id, "source_url": s.source_url, "captured_at": s.captured_at,
             "raw_sha256": s.raw_sha256, "raw_json": s.raw_json}
            for s in lm.source_snapshots.order_by("batch_id")
        ],
        "list_snapshots": [
            {"batch": s.batch_id, "list_amount_raw": s.list_amount_raw, "raw_json": s.raw_json}
            for s in lm.list_snapshots.order_by("batch_id")
        ],
        "exceptions": [
            {**_exception_row(e), "rows_json": e.rows_json, "validation_error": e.validation_error}
            for e in lm.source_exceptions.all()
        ],
    })


def _member_action(request, pk, action):
    from apps.parties.models import Member

    lm = _own_legacy_member(request, pk)
    if lm is None:
        return _bad("找不到這個舊會員", status.HTTP_404_NOT_FOUND)
    note = str(request.data.get("note", ""))[:300]
    try:
        if action == "link":
            target = Member.objects.filter(
                tenant=_tenant(request), pk=request.data.get("member") or 0
            ).first()
            if target is None:
                return _bad("找不到要對照的會員")
            method = request.data.get("method") or "manual"
            if method not in ("phone", "name", "manual"):
                method = "manual"
            lm = mapping.link_member(lm, target, request.user, method=method, note=note)
        elif action == "unlink":
            lm = mapping.unlink_member(lm, request.user, note=note)
        else:
            lm, _ = mapping.create_member_from_legacy(lm, request.user)
    except mapping.MappingError as exc:
        return _bad(exc, status.HTTP_409_CONFLICT)
    lm = _own_legacy_member(request, lm.pk)
    return Response(_legacy_member_row(lm))


@api_view(["POST"])
@permission_classes([IsCompanyAdmin])
def legacy_member_link(request, pk):
    return _member_action(request, pk, "link")


@api_view(["POST"])
@permission_classes([IsCompanyAdmin])
def legacy_member_unlink(request, pk):
    return _member_action(request, pk, "unlink")


@api_view(["POST"])
@permission_classes([IsCompanyAdmin])
def legacy_member_create_member(request, pk):
    return _member_action(request, pk, "create")


@api_view(["GET"])
@permission_classes([IsCompanyAdmin])
def candidates_for_member(request):
    """這位 MP 會員可能對應的舊會員(還沒對照的;電話或姓名相同)。"""
    member = _member(request, request.query_params.get("member"))
    if member is None:
        return _bad("找不到這位會員", status.HTTP_404_NOT_FOUND)
    out = []
    for lm, how in mapping.legacy_candidates(member):
        agg = lm.documents.aggregate(n=Count("id"), net=Coalesce(Sum("net_amount_minor"), 0))
        out.append(_legacy_member_row(lm, {
            "reason": how.label, "documents": agg["n"], "net_amount": _money(agg["net"]),
        }))
    return Response({"results": out})


# ─────────────────────────── 管理員:待核 ───────────────────────────
def _exception_row(e):
    return {
        "id": e.id,
        "batch": e.batch_id,
        "legacy_member": e.legacy_member.display_id,
        "reason": e.reason,
        "list_amount": _money(e.list_amount_minor),
        "detail_net_amount": _money(e.detail_net_amount_minor),
        "detail_amount": _money(e.detail_raw_amount_minor),
        "difference": _money(e.difference_minor),
        "documents": e.document_count,
        "items": e.line_count,
        "status": e.status,
        "resolved_at": e.resolved_at,
        "resolved_by": e.resolved_by.get_username() if e.resolved_by_id else "",
        "resolution_note": e.resolution_note,
        "resolution_evidence": e.resolution_evidence,
    }


@api_view(["GET"])
@permission_classes([IsCompanyAdmin])
def exceptions(request):
    rows = LegacySourceException.objects.filter(tenant=_tenant(request)).select_related(
        "legacy_member"
    )
    return Response({"results": [
        {**_exception_row(e), "rows_json": e.rows_json, "validation_error": e.validation_error}
        for e in rows
    ]})


@api_view(["POST"])
@permission_classes([IsCompanyAdmin])
def exception_resolve(request, pk):
    """結案:要有新的來源證據與理由。原始數字不改。兩個人同時按,只會有一個成功。"""
    from django.db import transaction

    note, evidence = request.data.get("note"), request.data.get("evidence")
    if not isinstance(note, str) or not isinstance(evidence, str):
        return _bad("結案要寫理由,並附上新的來源證據")
    note, evidence = note.strip(), evidence.strip()
    if not note or not evidence:
        return _bad("結案要寫理由,並附上新的來源證據")
    with transaction.atomic():
        e = (
            LegacySourceException.objects.select_for_update()
            .filter(tenant=_tenant(request), pk=pk).first()
        )
        if e is None:
            return _bad("找不到這筆待核", status.HTTP_404_NOT_FOUND)
        if e.status == LegacySourceException.Status.RESOLVED:
            return _bad("這筆已經處理過了", status.HTTP_409_CONFLICT)
        return _resolve(e, request, note, evidence)


def _resolve(e, request, note, evidence):
    from django.utils import timezone

    e.status = LegacySourceException.Status.RESOLVED
    e.resolved_by = request.user
    e.resolved_at = timezone.now()
    e.resolution_note = note[:2000]
    e.resolution_evidence = evidence[:20000]
    e.save(update_fields=["status", "resolved_by", "resolved_at", "resolution_note",
                          "resolution_evidence", "updated_at"])
    return Response(_exception_row(e))


# ─────────────────────────── 管理員:店別 / 品號 / 業務員對照 ───────────────────────────
_KINDS = {
    "stores": (LegacyMappingLog.Kind.STORE, LegacyStoreMap, "store_name_raw", "warehouse"),
    "products": (LegacyMappingLog.Kind.PRODUCT, LegacyProductMap, "product_code_raw", "product"),
    "salespersons": (
        LegacyMappingLog.Kind.SALESPERSON, LegacySalespersonMap, "salesperson_raw", "sales_person",
    ),
}


def _usage(kind_model, key_field, tenant):
    """每一個舊代號在明細裡出現幾筆、淨額多少(給人判斷先處理哪些)。"""
    if key_field == "store_name_raw":
        base = LegacyDocument.objects.filter(
            tenant=tenant, source_system=OuterRef("source_system"),
            store_name_raw=OuterRef("store_name_raw"),
        )
        return (
            Subquery(base.values("store_name_raw").annotate(c=Sum("item_count")).values("c")[:1]),
            Subquery(base.values("store_name_raw").annotate(s=Sum("net_amount_minor")).values("s")[:1]),
        )
    base = LegacyItem.objects.filter(
        tenant=tenant, source_system=OuterRef("source_system"),
        **{key_field: OuterRef(key_field)},
    ).values(key_field)
    return (
        Subquery(base.annotate(c=Count("id")).values("c")[:1]),
        Subquery(base.annotate(s=Sum(F("amount_minor") * F("net_sign"))).values("s")[:1]),
    )


def _map_row(kind, row, target_field):
    target = getattr(row, target_field)
    key_field = _KINDS[kind][2]
    out = {
        "id": row.id,
        "key": getattr(row, key_field).strip(),
        "key_exact": getattr(row, key_field),
        "status": row.status,
        "method": row.method,
        "target": (
            {"id": target.pk, "label": mapping._label(target)} if target is not None else None
        ),
        "confirmed_at": row.confirmed_at,
    }
    if kind == "products":
        out["name_seen"] = row.product_name_seen
    if hasattr(row, "usage_items"):          # 清單才有(各舊代號用了幾筆、多少錢)
        out["items"] = row.usage_items or 0
        out["net_amount"] = _money(row.usage_net or 0)
    return out


@api_view(["GET"])
@permission_classes([IsCompanyAdmin])
def maps(request, kind):
    if kind not in _KINDS:
        return _bad("沒有這種對照", status.HTTP_404_NOT_FOUND)
    _, model, key_field, target_field = _KINDS[kind]
    tenant = _tenant(request)
    qs = model.objects.filter(tenant=tenant).select_related(target_field)
    p = request.query_params
    if p.get("status") in (MapStatus.UNMAPPED, MapStatus.CONFIRMED):
        qs = qs.filter(status=p["status"])
    q = (p.get("q") or "").strip()
    if q:
        cond = Q(**{f"{key_field}__contains": q})
        if kind == "products":
            cond |= Q(product_name_seen__contains=q)
        qs = qs.filter(cond)
    items, net = _usage(model, key_field, tenant)
    qs = qs.annotate(usage_items=items, usage_net=net).order_by(
        F("usage_items").desc(nulls_last=True), "id"
    )
    pager = Paging()
    page = pager.paginate_queryset(qs, request)
    response = pager.get_paginated_response([_map_row(kind, r, target_field) for r in page])
    base = model.objects.filter(tenant=tenant)
    response.data["summary"] = {
        "total": base.count(),
        "confirmed": base.filter(status=MapStatus.CONFIRMED).count(),
        "unmapped": base.filter(status=MapStatus.UNMAPPED).count(),
    }
    return response


def _own_map(request, kind, pk):
    _, model, _, target_field = _KINDS[kind]
    return model.objects.filter(tenant=_tenant(request), pk=pk).select_related(target_field).first()


@api_view(["GET"])
@permission_classes([IsCompanyAdmin])
def map_candidates(request, kind, pk):
    if kind not in _KINDS:
        return _bad("沒有這種對照", status.HTTP_404_NOT_FOUND)
    row = _own_map(request, kind, pk)
    if row is None:
        return _bad("找不到這筆對照", status.HTTP_404_NOT_FOUND)
    if kind == "stores":
        found = [(w, "名稱相同") for w in mapping.store_candidates(row)]
    elif kind == "salespersons":
        found = [(s, "代號或姓名相同") for s in mapping.salesperson_candidates(row)]
    else:
        found = [(p, reason) for p, _, reason in mapping.product_candidates(row)]
    return Response({"results": [
        {"id": t.pk, "label": mapping._label(t), "reason": reason} for t, reason in found
    ]})


def _target(request, kind):
    from apps.catalog.models import Product
    from apps.inventory.models import Warehouse
    from apps.parties.models import SalesPerson

    model = {"stores": Warehouse, "products": Product, "salespersons": SalesPerson}[kind]
    return model.objects.filter(
        tenant=_tenant(request), pk=request.data.get("target") or 0
    ).first()


@api_view(["POST"])
@permission_classes([IsCompanyAdmin])
def map_confirm(request, kind, pk):
    if kind not in _KINDS:
        return _bad("沒有這種對照", status.HTTP_404_NOT_FOUND)
    row = _own_map(request, kind, pk)
    if row is None:
        return _bad("找不到這筆對照", status.HTTP_404_NOT_FOUND)
    target = _target(request, kind)
    if target is None:
        return _bad("找不到要對照的對象")
    method = request.data.get("method") or "manual"
    if method not in ("code", "name", "match", "manual"):
        method = "manual"
    try:
        row = mapping.confirm_map(_KINDS[kind][0], row, target, request.user, method=method,
                                  note=str(request.data.get("note", ""))[:300])
    except mapping.MappingError as exc:
        return _bad(exc, status.HTTP_409_CONFLICT)
    return Response(_map_row(kind, _own_map(request, kind, row.pk), _KINDS[kind][3]))


@api_view(["POST"])
@permission_classes([IsCompanyAdmin])
def map_revoke(request, kind, pk):
    if kind not in _KINDS:
        return _bad("沒有這種對照", status.HTTP_404_NOT_FOUND)
    row = _own_map(request, kind, pk)
    if row is None:
        return _bad("找不到這筆對照", status.HTTP_404_NOT_FOUND)
    try:
        row = mapping.revoke_map(_KINDS[kind][0], row, request.user,
                                 note=str(request.data.get("note", ""))[:300])
    except mapping.MappingError as exc:
        return _bad(exc, status.HTTP_409_CONFLICT)
    return Response(_map_row(kind, _own_map(request, kind, row.pk), _KINDS[kind][3]))


@api_view(["GET"])
@permission_classes([IsCompanyAdmin])
def batches(request):
    rows = HistoryImportBatch.objects.filter(tenant=_tenant(request))
    return Response({"results": [
        {"id": b.id, "period": [b.period_start, b.period_end], "status": b.status,
         "status_label": b.get_status_display(), "finished_at": b.finished_at,
         "rolled_back_at": b.rolled_back_at,
         "totals": (b.result or {}).get("totals", {}),
         "excluded_exceptions": (b.result or {}).get("excluded_exceptions", [])}
        for b in rows
    ]})
