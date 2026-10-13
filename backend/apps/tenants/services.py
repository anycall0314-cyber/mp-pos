"""發票字軌:取號、跳號。

**一條字軌是一間門市的**(owner 2026-10-13:三聯式收銀機發票是號碼已經印在紙上的整捲紙,每間門市的發票機各有一捲)。
取號只看「這間門市的」與「全公司共用的」(`warehouse` 空的;分門市之前建的舊字軌),自己門市的先用。
別間門市的字軌不會拿 —— 拿了系統的號碼就跟那一捲紙對不起來。

「下一張」只有兩種改法:開單取號(一次加一)、跳號(`jump_invoice_track`,留紀錄)。
"""
from datetime import date

from django.db import connection, transaction
from django.db.models import F, Q
from django.db.models.functions import Length
from django.utils import timezone

from . import invoice_periods
from .models import InvoiceTrack, InvoiceTrackJump, InvoiceType


class InvoiceTrackError(Exception):
    pass


# 「這家公司正在新增 / 修改字軌」的鎖(資料庫的諮詢鎖,兩個數字那一種:第一個是固定的類別、第二個是公司)。
TRACK_SETUP_LOCK = 20261013


def lock_track_setup(tenant):
    """新增、修改字軌之前先拿(要在交易裡;交易結束自己放掉):同一家公司一次只有一個人在動字軌的設定。
    「號碼跟別條字軌重不重疊」是先查再寫,兩個人同時新增重疊的兩條時各自都查不到對方 —— 排隊就看得到了。
    順序:**先拿這一把、才鎖字軌那一列**。開單取號與跳號不拿這一把(它們只鎖字軌那一列),不會互相卡死。"""
    with connection.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s, %s)", [TRACK_SETUP_LOCK, tenant.pk])


def _store_tracks(tenant, invoice_type, warehouse_id):
    """這間門市這種發票的字軌(啟用的):自己門市的 + 全公司共用的。
    沒有給門市 → 只有共用的(不知道是哪一間門市,不能拿某一間門市那一捲紙的號碼)。"""
    mine = Q(warehouse__isnull=True)
    if warehouse_id is not None:
        mine |= Q(warehouse_id=warehouse_id)
    return InvoiceTrack.objects.for_tenant(tenant).filter(mine, invoice_type=invoice_type, is_active=True)


def _usable_tracks(tenant, invoice_type, warehouse_id, day: date):
    """`day` 這一天這間門市這種發票可以用的字軌,照取號的順序:
    自己門市的先、共用的後;同一邊有登記期別的先、沒登記的(舊字軌)後;再照建立的先後。
    只有 `day` 那一期的、與沒有登記期別的舊字軌 —— 別期的不拿(上一期的號碼換期之後不能再開)。
    取號與預覽都用這一份,順序才會一樣;取號時整批上鎖也是照這個順序。"""
    period = invoice_periods.start_of(day)
    return (
        _store_tracks(tenant, invoice_type, warehouse_id)
        .filter(Q(period_start__isnull=True) | Q(period_start=period))
        .order_by(F("warehouse_id").asc(nulls_last=True), F("period_start").asc(nulls_last=True), "id")
    )


def _invoice_type(tenant, code):
    if not code or code == "none":
        return None
    return InvoiceType.objects.for_tenant(tenant).filter(code=code).first()


def peek_next_track(tenant, invoice_type_code: str, warehouse_id=None, day: date | None = None):
    """下一張會從哪一條字軌取(不上鎖、不取號);沒有可用的回 None。"""
    invoice_type = _invoice_type(tenant, invoice_type_code)
    if invoice_type is None:
        return None
    day = day or timezone.localdate()
    for track in _usable_tracks(tenant, invoice_type, warehouse_id, day).select_related("warehouse"):
        if not track.is_depleted:
            return track
    return None


def peek_next_invoice_no(tenant, invoice_type_code: str, warehouse_id=None, day: date | None = None):
    """非鎖定預覽下一張發票號碼。"""
    track = peek_next_track(tenant, invoice_type_code, warehouse_id, day)
    return track.format_number(track.next_number) if track else None


def why_no_track(tenant, invoice_type, warehouse_id, day: date) -> str:
    """取不到號的原因(給人看的一句):這一期的用完了,還是這一期根本還沒設定。"""
    period = invoice_periods.label(invoice_periods.start_of(day))
    if _usable_tracks(tenant, invoice_type, warehouse_id, day).exists():
        return f"{period} 的字軌用完了"
    return f"{period} 的字軌還沒設定"


def no_track_reason(tenant, invoice_type_code: str, warehouse_id=None, day: date | None = None) -> str:
    """開單頁用:這種發票現在取不到號的原因;不用取號的(免用、沒有這種類型)回空字串。"""
    invoice_type = _invoice_type(tenant, invoice_type_code)
    if invoice_type is None:
        return ""
    return why_no_track(tenant, invoice_type, warehouse_id, day or timezone.localdate())


def upcoming_period_gap(tenant, invoice_type_code: str, warehouse_id=None, day: date | None = None) -> str:
    """快換期了、下一期的字軌還沒設定 → 下一期的名稱(例 `115年11-12月`);不用提醒 → 空字串。

    只有現在在用的那一條有登記期別才提醒(沒登記期別的舊字軌不分期,換期照樣能用)。
    下一期只要這間門市(或全公司共用)有一條啟用的就算設定了。"""
    day = day or timezone.localdate()
    if invoice_periods.days_left(day) >= invoice_periods.REMIND_DAYS:
        return ""
    track = peek_next_track(tenant, invoice_type_code, warehouse_id, day)
    if track is None or track.period_start is None:
        return ""
    coming = invoice_periods.next_start(invoice_periods.start_of(day))
    if _store_tracks(tenant, track.invoice_type, warehouse_id).filter(period_start=coming).exists():
        return ""
    return invoice_periods.label(coming)


def assign_invoice_no(tenant, invoice_type_code: str, warehouse_id=None, day: date | None = None) -> str:
    """以 row-level lock 原子地取出下一張發票號碼,並把 next_number 遞增。

    `day` = 發票日期(沒給就是今天):只取那一期的字軌。
    取不到字軌時拋 InvoiceTrackError(call site 自行決定是否要擋下單)。
    """
    if not invoice_type_code or invoice_type_code == "none":
        raise InvoiceTrackError("發票類型為「免用」或未指定,不取號")
    day = day or timezone.localdate()

    with transaction.atomic():
        try:
            invoice_type = InvoiceType.objects.for_tenant(tenant).get(
                code=invoice_type_code
            )
        except InvoiceType.DoesNotExist:
            raise InvoiceTrackError(
                f"找不到發票類型 {invoice_type_code}"
            )
        # SELECT ... FOR UPDATE,序列化避免兩張單拿到同一號(只鎖字軌那一列,不鎖門市)
        qs = _usable_tracks(tenant, invoice_type, warehouse_id, day).select_for_update(of=("self",))
        for track in qs:
            if track.next_number <= track.range_end:
                num = track.next_number
                track.next_number = num + 1
                track.floor_number = max(track.floor_number, num + 1)       # 開出去過的號碼:之後不能再跳回來
                track.save(update_fields=["next_number", "floor_number"])
                return track.format_number(num)
        raise InvoiceTrackError(
            f"{invoice_type.name}:{why_no_track(tenant, invoice_type, warehouse_id, day)},請到系統設定新增字軌"
        )


def issued_numbers(track, start=None, end=None):
    """這條字軌的號碼裡,已經寫在銷貨單上的那幾號 → `{號碼: 銷貨單號}`(作廢的單也算:作廢的發票號碼不能再開給別人)。

    看的是銷貨單上的字(自己打號碼的也算),不是「下一張」:跳號、刪字軌、改字軌都靠它擋重複。
    號碼在 Python 裡比:單上的發票號碼是人可以打的字,資料庫的字串排序不保證跟數字一樣。
    """
    from apps.sales.models import SalesOrder

    lo = track.range_start if start is None else max(start, track.range_start)
    hi = track.range_end if end is None else min(end, track.range_end)
    prefix = track.prefix.upper()
    rows = (
        SalesOrder.objects.filter(tenant_id=track.tenant_id, invoice_no__istartswith=prefix)
        .annotate(size=Length("invoice_no"))
        .filter(size=len(prefix) + 8)
        .values_list("invoice_no", "no")
    )
    found = {}
    for invoice_no, doc_no in rows:
        digits = invoice_no[len(prefix):]
        if invoice_no[: len(prefix)].upper() != prefix or not (digits.isascii() and digits.isdigit()):
            continue
        number = int(digits)
        if lo <= number <= hi:
            found[number] = doc_no
    return found


def track_in_use(track) -> bool:
    """開過發票、或跳過號的字軌:不能刪,字軌兩碼 / 起號 / 類型也不能改(改了就認不出哪幾號開過)。
    開過 = 系統開出去過(`floor_number`;那張單後來不在了也算),或有銷貨單寫著這條字軌的號碼(自己打的也算)。"""
    return track.floor_number > 0 or track.jumps.exists() or bool(issued_numbers(track))


def jump_invoice_track(tenant, track_id, to_number, *, user=None, reason=""):
    """跳號:把這條字軌的「下一張」改成 `to_number`(= 發票機裡那捲紙的下一張),留一筆紀錄。

    - 往後跳:中間那幾號不開了(卡紙、印壞)。跳到「迄號 + 1」= 這一捲剩下的都不用了。
    - 往回:改打錯的。
    - 兩種都一樣:**新的下一張與它後面的號碼都還沒有寫在任何銷貨單上**才准 —— 不然之後會開出重複的號碼。
    - 另外**不能跳到系統開出去過的號碼前面**(`floor_number`):那張單後來不在了(回到較早的備份)號碼也不能再開,紙已經用掉了。
    先鎖字軌再查(開單取號也鎖同一列、而且鎖到那張單存完):查的時候不會有取到一半的號碼。
    """
    with transaction.atomic():
        track = (
            InvoiceTrack.objects.for_tenant(tenant).select_for_update(of=("self",))
            .filter(pk=track_id).first()
        )
        if track is None:
            raise InvoiceTrackError("找不到這條字軌")
        if not isinstance(to_number, int) or isinstance(to_number, bool):
            raise InvoiceTrackError("下一張要填數字")
        if not track.range_start <= to_number <= track.range_end + 1:
            raise InvoiceTrackError(
                f"下一張要在 {track.format_number(track.range_start)} ~ {track.format_number(track.range_end)} 之間"
            )
        if to_number == track.next_number:
            raise InvoiceTrackError(f"下一張本來就是 {track.format_number(to_number)}")
        taken = issued_numbers(track, start=to_number)
        if taken:
            last = max(taken)
            raise InvoiceTrackError(
                f"{track.format_number(last)} 已經開給銷貨單 {taken[last]},下一張不能排在它前面"
            )
        if to_number < track.floor_number:
            raise InvoiceTrackError(
                f"{track.format_number(track.floor_number - 1)} 已經開過,下一張不能排在它前面"
            )
        jump = InvoiceTrackJump.objects.create(
            tenant=tenant, track=track, from_number=track.next_number, to_number=to_number,
            reason=(reason or "").strip()[:100],
            created_by=user if getattr(user, "is_authenticated", False) else None,
        )
        track.next_number = to_number
        track.save(update_fields=["next_number", "updated_at"])
        return track, jump


# ─────────────────────────────────────────────────────────
# 新經銷商(Tenant)初始 seed:發票類型 + 付款方式
# ─────────────────────────────────────────────────────────

INVOICE_TYPE_SEED = [
    # (code, name, sort_order, is_default)
    ("e_invoice", "電子發票", 10, True),
    ("ev_dup", "電子二聯式", 20, False),
    ("ev_tri", "電子三聯式", 30, False),
    ("hand_dup", "手開二聯", 40, False),
    ("hand_tri", "手開三聯", 50, False),
    ("none", "免用統一發票", 90, False),
]

PAYMENT_METHOD_SEED = [
    # (code, name, kind, sort_order, is_default)
    ("cash", "現金", "cash", 10, True),
    ("card", "信用卡", "non_cash", 20, False),
    ("transfer", "匯款", "transfer", 30, False),
]


CONDITION_SEED = [
    # (code, name, is_secondhand, tracks_unit_condition, sort_order)
    ("brand-new", "全新", False, False, 1),
    ("opened", "已拆封", False, True, 2),
    ("used-warranty", "中古機(保固內)", True, True, 3),
    ("used", "中古機", True, True, 4),
]


def seed_tenant_defaults(tenant):
    """為剛建立的 tenant 補上預設發票類型、付款方式與商品狀態。

    可重複呼叫,既有資料用 get_or_create 不會重複建。
    """
    from apps.catalog.models import Condition

    from .models import InvoiceType, PaymentMethod

    for code, name, sort_order, is_default in INVOICE_TYPE_SEED:
        InvoiceType.objects.get_or_create(
            tenant=tenant,
            code=code,
            defaults={
                "name": name,
                "sort_order": sort_order,
                "is_active": True,
                "is_default": is_default,
            },
        )
    for code, name, kind, sort_order, is_default in PAYMENT_METHOD_SEED:
        PaymentMethod.objects.get_or_create(
            tenant=tenant,
            code=code,
            defaults={
                "name": name,
                "kind": kind,
                "sort_order": sort_order,
                "is_active": True,
                "is_default": is_default,
            },
        )
    # 商品狀態:migration 0019 / 0023 只處理當時已存在的租戶,
    # 之後新建的租戶要靠這裡補,否則「新增手機型號」精靈沒有狀態可選,
    # 手動補的「全新」也會拿到錯的 tracks_unit_condition 預設值。
    for code, name, is_secondhand, tracks_unit, sort_order in CONDITION_SEED:
        if Condition.objects.filter(tenant=tenant, code=code).exists():
            continue
        # 名稱也有唯一鍵。租戶可能自己用別的 code 建了同名的狀態
        # (例:code=custom-new、name=全新),這時直接新增會撞
        # uniq_condition_tenant_name 讓整個補種中斷,略過即可。
        if Condition.objects.filter(tenant=tenant, name=name).exists():
            continue
        Condition.objects.create(
            tenant=tenant,
            code=code,
            name=name,
            is_secondhand=is_secondhand,
            tracks_unit_condition=tracks_unit,
            sort_order=sort_order,
            is_active=True,
        )
