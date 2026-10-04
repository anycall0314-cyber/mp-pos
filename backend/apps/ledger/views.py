"""每日對帳結果(只限這家公司自己的管理員,跟備份同一套權限)。"""
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.backup.views import IsCompanyAdmin

from .checks import last_restore_at
from .models import LedgerCheckRun, StockSnapshotDay
from .snapshot import snapshot_totals

HISTORY_DAYS = 30


def _run_data(run, restored, with_results=False):
    data = {
        "id": run.id,
        "business_date": run.business_date,
        "finished_at": run.finished_at,
        "ok": run.ok,
        "problem_count": run.problem_count,
        # 這筆對帳之後公司被還原過:結果是還原前的資料,不能當作現在的狀態
        "before_restore": restored is not None and run.started_at < restored,
    }
    if with_results:
        data["results"] = run.results
    return data


@api_view(["GET"])
@permission_classes([IsCompanyAdmin])
def checks(request):
    tenant = request.user.profile.tenant
    runs = list(LedgerCheckRun.objects.filter(tenant=tenant).order_by("-id")[:HISTORY_DAYS])
    latest = runs[0] if runs else None
    restored = last_restore_at(tenant)
    snap_day = (
        StockSnapshotDay.objects.filter(tenant=tenant).order_by("-business_date")
        .values_list("business_date", flat=True).first()
    )
    snap = None
    if snap_day:
        totals = snapshot_totals(tenant, snap_day)
        snap = {"business_date": snap_day, "qty": totals["qty"] or 0,
                "cost_value": totals["value"] or 0}
    return Response({
        "latest": _run_data(latest, restored, with_results=True) if latest else None,
        "history": [_run_data(r, restored) for r in runs],
        "snapshot": snap,
    })
