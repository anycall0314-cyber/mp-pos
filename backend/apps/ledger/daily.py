"""每天收店後自動做一次:拍庫存快照 → 對帳。

備份背景程式(run_backup_worker,已常駐)每分鐘呼叫一次 `run_due()`;
過了 LEDGER_DAILY_AT(預設 23:30,台灣時間)而今天還沒做的公司才會做,
所以重複呼叫不會重複做。手動要立刻做:`manage.py run_daily_ledger --now`。
"""
from datetime import time

from django.conf import settings
from django.utils import timezone

from apps.tenants.models import Tenant

from .checks import run_checks
from .snapshot import CompanyBusy, PastBusinessDay, take_snapshot


DEFAULT_AT = time(23, 30)


def daily_time() -> time:
    """設定寫錯(不是 HH:MM)就用 23:30,不讓背景程式因為設定掛掉。"""
    try:
        hh, mm = str(getattr(settings, "LEDGER_DAILY_AT", "23:30")).split(":")
        return time(int(hh), int(mm))
    except (TypeError, ValueError):
        return DEFAULT_AT


def run_for(tenant, now=None, log=lambda msg: None, day=None):
    """今天還沒拍就拍;今天還沒對帳(或對帳之後公司被還原過)就對。
    「有沒有做過」在公司的每日鎖裡面才判斷,兩個程序同時跑也只會做一次。
    做完(或今天本來就做過)回傳 True;公司在還原、或已過了午夜而沒做回傳 False。"""
    try:
        rows = take_snapshot(tenant, now, only_if_missing=True, expect_day=day)
        if rows is not None:
            log(f"{tenant.code}:庫存快照 {rows} 列")
        run = run_checks(tenant, now, only_if_needed=True, expect_day=day)
        if run is not None:
            log(f"{tenant.code}:對帳 " + ("全部一致" if run.ok else f"{run.problem_count} 項不一致"))
        return True
    except CompanyBusy as exc:
        log(f"{tenant.code}:{exc},今天先跳過,下一次再試")
    except PastBusinessDay as exc:
        log(f"{tenant.code}:{exc}")
    return False


def run_due(now=None, force=False, log=lambda msg: None, tenants=None):
    """到時間了就對每一家啟用中的公司(或指定的公司)做一次今天的快照與對帳。

    還沒到時間回傳 None;否則回傳沒做成的公司代碼清單(空的 = 全部做完)。
    沒有指定 now 時,每家公司輪到時才看時間(公司多、跨過午夜也不會把日期記錯)。
    """
    start = now or timezone.now()
    if not force and timezone.localtime(start).time() < daily_time():
        return None
    day = timezone.localtime(start).date()
    if tenants is None:
        tenants = Tenant.objects.filter(is_active=True).order_by("pk")
    failed = []
    for tenant in tenants:
        try:
            if not run_for(tenant, now, log, day=day):
                failed.append(tenant.code)
        except Exception as exc:  # 一家出錯不擋其他家,也不能讓背景程式掛掉
            log(f"{tenant.code}:每日對帳失敗 {type(exc).__name__}: {exc}")
            failed.append(tenant.code)
    return failed
