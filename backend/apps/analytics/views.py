"""報表語意層的 API。一律只看自己公司。

查詢只接受「查詢單」(見 engine.py),沒有任何入口可以送資料庫指令或欄位名稱。

員工帳號的權限(owner 2026-10-10,第三批):
- 自訂分析這一組(清單、條件、查詢、存起來的報表)要有「自訂分析」;固定的報表一張一個勾。
- **鎖在門市的帳號只算自己門市**,不管查詢單怎麼寫(引擎強制,見 `engine.run(only_warehouse=…)`)。
  2026-10-04 定的「報表暫時不依門市上鎖」到這裡為止。
"""
from django.db import IntegrityError, transaction
from django.db.models import Q
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from apps.core.warehouse_scoping import locked_warehouse_id, report_warehouse_id
from apps.tenants import abilities
from apps.tenants.permissions import is_tenant_admin

from . import engine, presets, saved
from .models import SavedReport


def _bad(message, code=status.HTTP_400_BAD_REQUEST):
    return Response({"detail": str(message)}, status=code)


@api_view(["GET"])
def catalog(request):
    abilities.require(request.user, abilities.REPORT_EXPLORE)
    return Response(engine.describe(request.user))


@api_view(["GET"])
def options(request):
    abilities.require(request.user, abilities.REPORT_EXPLORE)
    try:
        return Response({"results": engine.options(
            request.tenant, request.query_params.get("dimension"), request.query_params.get("q", ""))})
    except engine.QueryError as exc:
        return _bad(exc)


@api_view(["POST"])
def query(request):
    abilities.require(request.user, abilities.REPORT_EXPLORE)
    try:
        return Response(engine.run(
            request.tenant, request.data, request.user,
            only_warehouse=locked_warehouse_id(request.user)))
    except engine.QueryError as exc:
        return _bad(exc)


@api_view(["GET"])
def preset(request, key):
    """固定的報表:?from= ?to=(必填)?warehouse=(沒鎖門市的才有用)?by=(商品排行:商品 / 品類 / 品牌)"""
    report = presets.REPORTS.get(key)
    if report is None:
        return _bad("沒有這張報表", status.HTTP_404_NOT_FOUND)
    abilities.require(request.user, report.ability)
    params = request.query_params
    try:
        return Response(presets.run(
            report, request.tenant, request.user,
            start=params.get("from"), end=params.get("to"), by=params.get("by") or "",
            warehouse=report_warehouse_id(request),
            only_warehouse=locked_warehouse_id(request.user)))
    except engine.QueryError as exc:
        return _bad(exc)


def _visible(request):
    """自己存的 + 全公司共用的;管理員另外看得到「建立者已經不在」的。"""
    cond = Q(owner=request.user) | Q(shared=True)
    if is_tenant_admin(request.user):
        cond |= Q(owner__isnull=True)
    return SavedReport.objects.filter(tenant=request.tenant).filter(cond).select_related("owner")


def _may_edit(report, user):
    """共用的與沒有建立者的只有管理員可以改 / 刪(當初共用它的人後來不是管理員了也不行);
    私下存的只有自己可以。"""
    if report.shared or report.owner_id is None:
        return is_tenant_admin(user)
    return report.owner_id == user.id


def _report_data(report, request):
    user = request.user
    spec, missing, error = saved.from_stored(request.tenant, report.spec, user)
    return {
        "id": report.id,
        "name": report.name,
        "spec": spec,
        "filters": [] if error else engine.filter_labels(request.tenant, spec, user),
        "missing": missing,       # 哪些條件裡有已經不存在的資料(已從條件拿掉)
        "error": error,           # 整份不能用的原因(空 = 可以用)
        "shared": report.shared,
        "mine": report.owner_id == user.id,
        "owner": report.owner.get_username() if report.owner else "",
        "editable": _may_edit(report, user),
        "updated_at": report.updated_at,
    }


def _clean(request, partial=False):
    """驗證存報表送來的內容;回傳要寫入的欄位。"""
    data, out = request.data if isinstance(request.data, dict) else {}, {}
    if "name" in data or not partial:
        name = data.get("name")
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 60:
            raise engine.QueryError("名稱要 1 到 60 個字")
        out["name"] = name.strip()
    if "spec" in data or not partial:
        # 存進去的一定是合法、整理過的查詢單(不認得的欄位不留)
        out["spec"] = saved.to_stored(
            request.tenant, engine.normalize(request.tenant, data.get("spec"), request.user))
    if "shared" in data:
        if not isinstance(data["shared"], bool):
            raise engine.QueryError("共用只能是 是 / 否")
        if data["shared"] and not is_tenant_admin(request.user):
            raise engine.QueryError("只有管理員可以設成全公司共用")
        out["shared"] = data["shared"]
    return out


@api_view(["GET", "POST"])
def reports(request):
    abilities.require(request.user, abilities.REPORT_EXPLORE)
    if request.method == "GET":
        return Response({"results": [_report_data(r, request) for r in _visible(request)]})
    try:
        fields = _clean(request)
        owned = SavedReport.objects.filter(tenant=request.tenant, owner=request.user).count()
        if owned >= saved.MAX_PER_USER:
            raise engine.QueryError(f"存太多了(最多 {saved.MAX_PER_USER} 份),先刪掉用不到的")
        with transaction.atomic():
            report = SavedReport.objects.create(tenant=request.tenant, owner=request.user, **fields)
    except engine.QueryError as exc:
        return _bad(exc)
    except IntegrityError:
        return _bad("已經有同名的報表")
    return Response(_report_data(report, request), status=status.HTTP_201_CREATED)


@api_view(["PATCH", "DELETE"])
def report_detail(request, pk):
    abilities.require(request.user, abilities.REPORT_EXPLORE)
    report = _visible(request).filter(pk=pk).first()
    if report is None:
        return _bad("找不到這份報表", status.HTTP_404_NOT_FOUND)
    if not _may_edit(report, request.user):
        return _bad("這份報表是別人存的,不能改", status.HTTP_403_FORBIDDEN)
    if request.method == "DELETE":
        report.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    try:
        fields = _clean(request, partial=True)
        for key, value in fields.items():
            setattr(report, key, value)
        with transaction.atomic():
            report.save()
    except engine.QueryError as exc:
        return _bad(exc)
    except IntegrityError:
        return _bad("已經有同名的報表")
    return Response(_report_data(report, request))
