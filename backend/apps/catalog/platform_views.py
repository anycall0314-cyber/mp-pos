"""平台管理 → 型號庫(M1-D):型號庫自動更新的狀況、等人按的那幾支。**只有平台管理員能看、能按。** 規則在 `device_watch.py`。

- `GET  platform/device-watch/`:上一次檢查(什麼時候、成功沒有、讀不到的原因)、最近 7 次、待確認 / 等資料的清單、最近 30 天自動加的、
  幾點檢查、哪幾家公司勾了「新機自動建品號」。
- `POST platform/device-candidates/<編號>/` `{action: add | same | dismiss, name?, uid?}`:加入(可以改型號名稱)/ 就是那一支 / 不收。
- `GET  platform/devices/?q=`:找型號庫的型號(最多 20 支)。
- `GET  platform/device-shares/`:配件共用的每一條;`POST` `{device, same_as, screen, body}` 設 / 改一條(新勾的格當下套到每一家,
  回加到幾家、幾個配件);`DELETE platform/device-shares/<編號>/` 取消(之後不再加,已經加上的不收回)。規則在 `device_share.py`。
"""
from datetime import timedelta

from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.tenants.models import Tenant
from apps.tenants.permissions import IsPlatformAdmin

from django.db.models import Q

from . import device_share, device_watch
from .models import DeviceCandidate, DeviceModel, DeviceShare, DeviceWatchRun

PLATFORM_ONLY = [IsAuthenticated, IsPlatformAdmin]
RECENT_DAYS = 30
CATEGORY_LABELS = dict(DeviceModel.Category.choices)


def _run(r: DeviceWatchRun) -> dict:
    return {"day": r.day.isoformat(), "finished_at": r.finished_at, "ok": r.ok, "counts": r.counts, "notes": r.notes}


def _candidate(c: DeviceCandidate) -> dict:
    d = c.data or {}
    return {
        "id": c.id, "status": c.status, "status_label": c.get_status_display(), "reason": c.reason,
        "list_name": c.list_name, "url": c.url, "checked_at": c.checked_at, "created_at": c.created_at,
        "category": d.get("category") or "", "category_label": CATEGORY_LABELS.get(d.get("category") or "", ""), "brand": d.get("brand") or d.get("raw_brand") or "", "name": d.get("name") or "",
        "launched": d.get("launched") or "", "capacities": d.get("capacities") or [], "colors": d.get("colors") or [],
        "connectivity": d.get("connectivity") or [], "near": d.get("near") or [],
        "can_add": bool(d.get("name") and d.get("category")) and not device_watch.missing(d, timezone.localdate()),
    }


@api_view(["GET"])
@permission_classes(PLATFORM_ONLY)
def watch(request):
    runs = list(DeviceWatchRun.objects.order_by("-day")[:7])
    open_rows = DeviceCandidate.objects.filter(status__in=device_watch.OPEN).order_by("status", "-id")[:200]
    since = timezone.now() - timedelta(days=RECENT_DAYS)
    added = [{"uid": d.uid, "category": d.category, "category_label": CATEGORY_LABELS.get(d.category, ""), "brand": d.brand, "name": d.name, "launched": d.launched,
              "created_at": d.created_at, "colors": (d.data or {}).get("colors") or [],
              "capacities": (d.data or {}).get("capacities") or [], "sources": (d.data or {}).get("sources") or []}
             for d in DeviceModel.objects.filter(data__origin=device_watch.ORIGIN, created_at__gte=since).order_by("-created_at")[:100]]
    at = device_watch.watch_time()
    return Response({
        "at": at.strftime("%H:%M") if at else "",
        "last": _run(runs[0]) if runs else None,
        "runs": [_run(r) for r in runs],
        "candidates": [_candidate(c) for c in open_rows],
        "added": added,
        "auto_tenants": list(Tenant.objects.filter(is_active=True, auto_device_models=True).order_by("pk").values_list("code", flat=True)),
        "catalog_count": DeviceModel.objects.filter(is_active=True).count(),
    })


@api_view(["POST"])
@permission_classes(PLATFORM_ONLY)
def candidate(request, pk):
    data = request.data if isinstance(request.data, dict) else {}
    action = data.get("action")
    name = data.get("name") if isinstance(data.get("name"), str) else ""
    uid = data.get("uid") if isinstance(data.get("uid"), str) else ""
    try:
        result = device_watch.decide(pk, action, request.user, name=name, uid=uid)
    except device_watch.DecideError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(result)


def _device_row(d: DeviceModel | None, uid: str = "") -> dict:
    if d is None:
        return {"uid": uid, "brand": "", "name": uid, "category": "", "category_label": "", "launched": ""}
    return {"uid": d.uid, "brand": d.brand, "name": d.name, "category": d.category,
            "category_label": CATEGORY_LABELS.get(d.category, ""), "launched": d.launched}


@api_view(["GET"])
@permission_classes(PLATFORM_ONLY)
def devices(request):
    q = (request.query_params.get("q") or "").strip()
    rows = DeviceModel.objects.filter(is_active=True)
    for word in q.split()[:6]:
        rows = rows.filter(Q(name__icontains=word) | Q(brand__icontains=word))
    rows = rows.order_by("category", "brand", "-launched", "name")[:20] if q else []
    return Response({"devices": [_device_row(d) for d in rows]})


def _share_row(rule: DeviceShare, by_uid: dict) -> dict:
    return {"id": rule.id, "device": _device_row(by_uid.get(rule.device_uid), rule.device_uid),
            "same_as": _device_row(by_uid.get(rule.same_as_uid), rule.same_as_uid),
            "screen": rule.screen, "body": rule.body, "created_at": rule.created_at,
            "created_by": rule.created_by.get_username() if rule.created_by_id else ""}


def _share_rows(rules) -> list[dict]:
    rules = list(rules)
    uids = {u for r in rules for u in (r.device_uid, r.same_as_uid)}
    by_uid = {d.uid: d for d in DeviceModel.objects.filter(uid__in=uids)}
    return [_share_row(r, by_uid) for r in rules]


@api_view(["GET", "POST"])
@permission_classes(PLATFORM_ONLY)
def shares(request):
    if request.method == "GET":
        return Response({"rules": _share_rows(DeviceShare.objects.select_related("created_by").order_by("-id")[:500])})
    data = request.data if isinstance(request.data, dict) else {}
    text = lambda k: data.get(k) if isinstance(data.get(k), str) else ""  # noqa: E731
    try:
        result = device_share.set_rule(text("device"), text("same_as"), screen=data.get("screen") is True,
                                       body=data.get("body") is True, user=request.user)
    except device_share.ShareError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    [row] = _share_rows([result["rule"]])
    return Response({"rule": row, "tenants": result["tenants"], "products": result["products"]})


@api_view(["DELETE"])
@permission_classes(PLATFORM_ONLY)
def share(request, pk):
    try:
        device_share.remove_rule(pk)
    except device_share.ShareError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)
    return Response(status=status.HTTP_204_NO_CONTENT)
