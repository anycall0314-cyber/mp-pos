"""門號合約到期:名單、聯絡紀錄、統計用的資料來源。

一筆門號合約 = 一行有方案、有合約到期日的銷貨明細(到期日在存檔當下算好,見 `services._store_contract_end`)。
這裡**只讀**那些結果,不動銷貨單、不重算日期。規則只有這一份 —— 名單(`contract_views`)、今日總覽的筆數、
自由組合報表(`analytics/catalog.py` 的「門號合約」)都從 `contracts()` 出發:

- 作廢的單、被退掉的那一行(現在一律整張退;舊資料有只退其中幾行的,只有被退的那幾行不算)不算合約。
- 同一個門號(去掉符號後相同)在**另一張單**上有**起算日更晚**的合約 → 這一筆是「已續約」。
  起算日同一天的不算(同一天開了兩張:多半是打重複沒作廢,或一個門號兩份不同月數的合約 ——
  兩筆都留著提醒;拿「誰比較後面建的」當成續約,先到期的那一筆會被蓋掉、漏提醒)。
  同一張單上重複打的同一個門號不互相算續約;門號去掉符號後不到 6 位數字的(舊資料的「-」「無」)不拿來比,
  不然這種單會全部互相蓋成「已續約」、該打電話的客人一個都不出現。
- 沒續的:有聯絡紀錄看紀錄(已聯絡 / 不續約),沒有就是還沒處理。
  聯絡紀錄可以只有備註、沒有狀態(還沒聯絡上,先記「無人接聽」):那一筆仍然是還沒處理。
- 「待聯絡」= 還沒處理,而且到期日在「今天 + 提前幾個月」以內(已經過期還沒續的也算,一直留著)。
"""
from datetime import date

from django.db import transaction
from django.db.models import Case, CharField, Exists, OuterRef, Value, When
from django.db.models.functions import Length
from django.utils import timezone

from apps.core.dates import add_months

from .models import ContractFollowUp, Digits, SalesOrderItem, SalesReturnItem

OPEN, CONTACTED, DECLINED, RENEWED = "open", "contacted", "declined", "renewed"
# 門號去掉符號後至少要有這麼多位數字,才拿來比「是不是同一個門號」
MIN_MSISDN_DIGITS = 6
STATE_LABELS = {OPEN: "還沒處理", CONTACTED: "已聯絡", DECLINED: "不續約", RENEWED: "已續約"}


class ContractError(Exception):
    """不讓做(原因會顯示給使用者)。"""


def _counted(tenant):
    """算得上合約的銷貨明細:有方案、有到期日、單沒作廢、這一行沒被退掉。"""
    returned = SalesReturnItem.objects.filter(original_item_id=OuterRef("pk"), sr__is_void=False)
    return (
        SalesOrderItem.objects.filter(
            tenant=tenant, telecom_plan__isnull=False, contract_end__isnull=False,
            so__is_void=False,
        )
        .annotate(was_returned=Exists(returned))
        .filter(was_returned=False)
    )


def contracts(tenant):
    """這家公司的門號合約,每一筆帶著 `state`(open / contacted / declined / renewed)。"""
    # 另一張單上、同一個門號、起算日更晚的合約(同一天的不算:寧可兩筆都提醒)
    newer = (
        _counted(tenant)
        .annotate(other_key=Digits("msisdn"))
        .filter(other_key=OuterRef("msisdn_key"))
        .annotate(key_len=Length("other_key"))
        .filter(key_len__gte=MIN_MSISDN_DIGITS)
        .exclude(so_id=OuterRef("so_id"))
        .filter(activation_date__gt=OuterRef("activation_date"))
    )
    return (
        _counted(tenant)
        .annotate(msisdn_key=Digits("msisdn"))
        .annotate(renewed=Exists(newer))
        .annotate(
            state=Case(
                When(renewed=True, then=Value(RENEWED)),
                When(follow_up__status=ContractFollowUp.Status.DECLINED, then=Value(DECLINED)),
                When(follow_up__status=ContractFollowUp.Status.CONTACTED, then=Value(CONTACTED)),
                default=Value(OPEN),
                output_field=CharField(),
            )
        )
    )


def remind_until(tenant, today=None) -> date:
    """到期日在這一天(含)以前的,開始出現在待聯絡。"""
    return add_months(today or timezone.localdate(), tenant.contract_remind_months or 0)


def pending(tenant, today=None):
    """待聯絡:還沒處理,而且快到期或已經過期。"""
    return contracts(tenant).filter(state=OPEN, contract_end__lte=remind_until(tenant, today))


def set_follow_up(tenant, item_id, status, note, user, warehouse_id=None):
    """記這一筆聯絡到哪了:status = 已聯絡 / 不續約 / 空的(還沒聯絡上,回到或留在待聯絡);note = 一句備註。

    狀態與備註都空的 = 整筆紀錄拿掉。只有備註、沒有狀態 = 仍然在待聯絡,備註留著。
    warehouse_id 有值 = 只能動這家門市賣出去的(鎖倉店員)。回這一筆現在的聯絡紀錄(拿掉了就是 None)。
    """
    status = (status or "").strip()
    note = (note or "").strip()[:200]
    if status and status not in ContractFollowUp.Status.values:
        raise ContractError("狀態只能是「已聯絡」或「不續約」")
    with transaction.atomic():
        rows = contracts(tenant).filter(pk=item_id)
        if warehouse_id is not None:
            rows = rows.filter(so__warehouse_id=warehouse_id)
        row = rows.first()
        if row is None:
            raise ContractError("找不到這筆門號合約")
        if row.state == RENEWED:
            raise ContractError("這個門號已經續約了,不用再標")
        if not status and not note:
            ContractFollowUp.objects.filter(tenant=tenant, item_id=row.pk).delete()
            return None
        follow, _created = ContractFollowUp.objects.update_or_create(
            tenant=tenant, item_id=row.pk,
            defaults={"status": status, "note": note, "updated_by": user},
        )
        return follow
