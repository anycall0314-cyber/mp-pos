"""手機走動盤點(owner 2026-10-15「盤點要有手機可以配對掃，方便走動盤點」)。

owner 定的三件:電腦的盤點單按「手機盤點」產生 QR Code、手機一掃就能盤、**不用登入**(跟商品照片同一套 `photos.services`);
**配件每刷一個 +1**(好幾個人同時盤同一張,數字加在一起);**用手機相機掃**(藍牙掃描槍接手機也可以,當成打字)。

- 一個 QR Code 一支手機:綁第一支掃到的手機(手機自己產生的識別,只存雜湊);要幾支就按幾次。憑證只存雜湊、放在網址 `#` 後面。
  3 分鐘沒人掃失效;手機 30 分鐘沒動作、或連上超過 12 小時就結束;盤點單送出 / 作廢、電腦按「結束」也結束。
  手機那一頁開著每 10 秒回報一次(`seen_at`);30 秒沒回報,電腦上顯示「斷線」、不算在「已配對 N 台」(全站檢視 V06b)。
- 憑證只能對**這一張盤點單**刷碼、看自己刷了什麼與那個品項大家合起來數到幾個 —— **看不到帳上數量**(盲盤),不能送出、核准、作廢。
- 發 QR Code 要寫稱呼(紅隊:出事問得到人);手機刷的每一下記在 `StockCountTap`(稱呼、時間、從幾個變幾個)。
- 刷到的碼:配件的品號 / 條碼(含已確認的條碼別名)→ 那個配件 +1;機器(序號、舊系統清單上的那一台)→ 記那一台(`stockcount.scan`);
  都不是:畫面在「配件」模式 → 記成「沒對到的碼」(`stockcount.tally_unknown`,電腦上處理好才能送出);「手機」模式 → 當成一台手機記(第一次入庫)。
- 「這一堆幾個」= 把最後那一下的 +1 改成 +N;「收回這一下」= 那一下減回去。加減不會互相蓋掉,別支手機同時在刷不擋;
  **那一下之後電腦整格換過數字就不動**(換掉的數已經定了),請他到電腦上改。
- 每一個動作:先鎖盤點單,再鎖配對那一列、核對還是同一次配對(電腦結束、換手機之後,舊手機晚到的請求不能寫進來)。
"""
from __future__ import annotations

import hashlib
import re
import secrets
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.catalog.models import Product

from . import stockcount
from .identifiers import find_serial_ids
from .models import StockCount, StockCountOp, StockCountPhone, StockCountScan, StockCountTap, StockCountUnknown

S = StockCount.Status
T = StockCountTap.Kind
PAIR_TTL = timedelta(minutes=3)        # QR Code 多久沒人掃就失效
DEVICE_IDLE = timedelta(minutes=30)    # 手機多久沒刷就結束(走動盤點會停下來數一堆)
DEVICE_MAX = timedelta(hours=12)       # 一次配對最長多久
DEVICE_LOST = timedelta(seconds=30)    # 手機那一頁每 10 秒回報一次;多久沒回報算斷線(只是顯示,手機回來照樣能刷)
MAX_ACTIVE = 10                        # 一張盤點單同時最多幾支手機
MAX_TAPS = 20000                       # 一次配對最多刷幾下(擋拿到憑證一直灌)
MAX_PILE = 9999                        # 「這一堆幾個」最多
RECENT = 30                            # 手機上列最近幾下


class PhoneError(Exception):
    """做不了。訊息直接給手機或電腦看;`code` 讓手機知道要不要請人重新掃 QR Code。"""

    def __init__(self, message, code="refused"):
        super().__init__(message)
        self.code = code


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def status_of(phone: StockCountPhone, now=None) -> str:
    """waiting 等手機掃 / expired QR 過期了沒人掃 / connected 手機連著 / lost 最近沒回報(關掉了、斷線)/ idle 太久沒刷 / ended 結束了。"""
    now = now or timezone.now()
    if phone.ended_at or phone.count.status != S.COUNTING:
        return "ended"
    if not phone.device_hash:
        return "waiting" if now <= phone.pair_expires_at else "expired"
    if phone.paired_at and now - phone.paired_at > DEVICE_MAX:
        return "idle"
    if phone.device_active_at and now - phone.device_active_at > DEVICE_IDLE:
        return "idle"
    if phone.seen_at and now - phone.seen_at > DEVICE_LOST:
        return "lost"
    return "connected"


# ── 電腦 ─────────────────────────────────────────────────────
def start(count, user, label) -> tuple[StockCountPhone, str]:
    """產生一張 QR Code(一支手機)。回 (那一次配對, 憑證本身 —— 只在這一刻看得到)。"""
    label = str(label or "").strip()
    if not label:
        raise PhoneError("請寫這支手機是誰在用(例:小王、櫃2)")
    if len(label) > 20:
        raise PhoneError("稱呼最多 20 個字")
    token = secrets.token_urlsafe(32)
    now = timezone.now()
    with transaction.atomic():
        try:
            stockcount._locked(count, S.COUNTING)
        except stockcount.CountError as exc:
            raise PhoneError(str(exc)) from None
        live = [p for p in count.phones.filter(ended_at__isnull=True) if status_of(p, now) in ("waiting", "connected", "lost")]
        if len(live) >= MAX_ACTIVE:
            raise PhoneError(f"一張盤點單同時最多 {MAX_ACTIVE} 支手機,先結束用不到的")
        phone = StockCountPhone.objects.create(
            tenant=count.tenant, count=count, label=label, pair_hash=_hash(token),
            pair_expires_at=now + PAIR_TTL, created_by=user if getattr(user, "is_authenticated", False) else None)
    return phone, token


def end(count, phone_id) -> None:
    """電腦按「結束」:那支手機不能再刷。"""
    StockCountPhone.objects.filter(count=count, pk=phone_id, ended_at__isnull=True).update(ended_at=timezone.now())


# ── 手機 ─────────────────────────────────────────────────────
def session(token: str, device: str, claim=False) -> StockCountPhone:
    """手機拿 QR Code 的憑證進來。claim = 掃碼那一下(可以綁手機)。回那一次配對(含盤點單)。"""
    token, device = (token or "").strip(), (device or "").strip()
    if not token or not device or len(device) > 128:
        raise PhoneError("要再盤,請在電腦按「手機盤點」再掃一次", "gone")
    now = timezone.now()
    with transaction.atomic():
        # 只鎖配對這一列(複審 P1:連帶鎖到盤點單的話,刷碼那邊是「先盤點單、後配對」,兩邊會互等卡死)
        phone = (StockCountPhone.objects.select_for_update(of=("self",)).select_related("count", "count__warehouse")
                 .filter(pair_hash=_hash(token)).first())
        if phone is None or phone.ended_at:
            raise PhoneError("這支手機的盤點已經結束。要再盤,請在電腦按「手機盤點」再掃一次", "gone")
        if phone.count.status != S.COUNTING:
            raise PhoneError(f"這張盤點單已經「{phone.count.get_status_display()}」,不能再刷", "gone")
        if not phone.device_hash:
            if not claim:
                raise PhoneError("請重新掃描 QR Code", "gone")
            if now > phone.pair_expires_at:
                raise PhoneError("QR Code 過期了,請在電腦再按一次「手機盤點」", "expired")
            phone.device_hash, phone.paired_at, phone.device_active_at, phone.seen_at = _hash(device), now, now, now
            phone.save(update_fields=["device_hash", "paired_at", "device_active_at", "seen_at", "updated_at"])
            return phone
        if phone.device_hash != _hash(device):
            raise PhoneError("這個 QR Code 已經有另一支手機在用。要換手機,請在電腦再按一次「手機盤點」", "taken")
        if status_of(phone, now) == "idle":
            raise PhoneError("太久沒有刷,已經結束。請在電腦再按一次「手機盤點」", "expired")
        phone.seen_at = now
        phone.save(update_fields=["seen_at"])
        return phone


def _still(phone_pk: int, device: str) -> StockCountPhone:
    """盤點單已經鎖住之後,再鎖配對那一列、核對還是同一次配對、記一次動作。"""
    phone = StockCountPhone.objects.select_for_update().filter(pk=phone_pk).first()
    if phone is None or phone.ended_at or phone.device_hash != _hash(device):
        raise PhoneError("這支手機的盤點已經結束。要再盤,請在電腦按「手機盤點」再掃一次", "gone")
    if status_of(phone) == "idle":
        raise PhoneError("太久沒有刷,已經結束。請在電腦再按一次「手機盤點」", "expired")
    phone.device_active_at = phone.seen_at = timezone.now()
    phone.save(update_fields=["device_active_at", "seen_at", "updated_at"])
    return phone


_OP = re.compile(r"^[A-Za-z0-9_-]{8,40}$")


def _seen_op(count, phone, op) -> bool:
    """這個動作編號做過了嗎(做過 = 這一次是重送,不再做一次);沒做過就記下來。呼叫的人要已經鎖住盤點單。
    複審 P0:刷了、伺服器也記了,回應在路上斷線 → 手機用同一個編號重送,不能多 +1。"""
    op = str(op or "")
    if not _OP.match(op):
        raise PhoneError("請重新整理這一頁再刷")
    if StockCountOp.objects.filter(count=count, phone_ref=phone.pk, op=op).exists():
        return True
    StockCountOp.objects.create(tenant=count.tenant, count=count, phone_ref=phone.pk, op=op)
    return False


def _accessory(tenant, code: str):
    """這個碼是不是某一個商品的品號 / 條碼(含已確認的條碼別名):剛好一個才算。"""
    from apps.identity.models import ProductAlias
    from apps.identity.normalize import alias_key

    ids = set(Product.objects.filter(tenant=tenant, is_active=True).filter(Q(barcode=code) | Q(sku__iexact=code))
              .values_list("pk", flat=True))
    ids |= set(ProductAlias.objects.filter(tenant=tenant, kind=ProductAlias.Kind.BARCODE, is_active=True,
                                           normalized_value=alias_key(code), product__is_active=True)
               .values_list("product_id", flat=True))
    if len(ids) != 1:
        return None
    return Product.objects.get(pk=next(iter(ids)))


def _is_device(tenant, code: str) -> bool:
    """這個碼是某一台機器:系統裡的序號,或舊系統機器清單上的那一台(第一次入庫)。"""
    from apps.legacy import units

    if find_serial_ids(tenant, code):
        return True
    try:
        return units.lookup(tenant, code) is not None
    except units.ModelSticker:
        return True                          # 型號用的舊貼紙:交給 scan() 講要刷 IMEI


def tap(phone: StockCountPhone, device: str, code, mode: str, op) -> StockCountTap | None:
    """刷到一個碼。mode = accessory(配件)/ phone(手機):只決定「系統不認得的碼」記成什麼。op = 這一下的編號(重送回 None)。"""
    code = str(code or "").strip()
    if not code or len(code) > 80:
        raise PhoneError("這不是有效的碼")
    if mode not in ("accessory", "phone"):
        raise PhoneError("模式不對")
    count = phone.count
    try:
        with transaction.atomic():
            stockcount._locked(count, S.COUNTING)
            phone = _still(phone.pk, device)
            if _seen_op(count, phone, op):
                return None
            if StockCountTap.objects.filter(count=count, phone_ref=phone.pk).count() >= MAX_TAPS:
                raise PhoneError(f"這支手機已經刷了 {MAX_TAPS} 下,請在電腦再按一次「手機盤點」換一個 QR Code")
            user = phone.created_by
            product = _accessory(count.tenant, code)
            base = {"tenant": count.tenant, "count": count, "phone_ref": phone.pk, "label": phone.label, "code": code}
            if product is not None and not product.requires_serial:
                line, before, after = stockcount.add_to_line(count, product, 1, user)
                return StockCountTap.objects.create(**base, kind=T.LINE, product=product, line_ref=line.pk, before=before, after=after)
            if product is not None or mode == "phone" or _is_device(count.tenant, code):
                scan = stockcount.scan(count, code, user)
                return StockCountTap.objects.create(**base, kind=T.SCAN, scan=scan)
            row, before, after = stockcount.tally_unknown(count, code, phone.label)
            return StockCountTap.objects.create(**base, kind=T.UNKNOWN, unknown=row, before=before, after=after)
    except stockcount.CountError as exc:
        raise PhoneError(str(exc)) from None


def _last(count, phone_pk):
    return StockCountTap.objects.select_for_update().filter(count=count, phone_ref=phone_pk, undone=False).order_by("-id").first()


def _aimed(last, target):
    """手機按下去時看到的「最後一下」(`target`)要跟伺服器的最後一下一樣(複審第二輪 P0:還沒確定的「收回」被後面刷的超車,
    會收到別的那一下)。沒帶 = 不核對。"""
    if target is not None and (last is None or last.pk != target):
        raise PhoneError("最後一下已經不是那一下了,請看清單再按")


def pile(phone: StockCountPhone, device: str, n, op, target=None) -> StockCountTap | None:
    """「這一堆幾個」:最後那一下(配件 +1)改成 +n。那個配件之後被別人改過就不動。"""
    if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= MAX_PILE:
        raise PhoneError(f"要是 1 到 {MAX_PILE} 的整數")
    count = phone.count
    try:
        with transaction.atomic():
            stockcount._locked(count, S.COUNTING)
            phone = _still(phone.pk, device)
            if _seen_op(count, phone, op):
                return None
            last = _last(count, phone.pk)
            _aimed(last, target)
            if last is None or last.kind != T.LINE:
                raise PhoneError("最後一下不是配件")
            step = last.after - (last.before or 0)
            if n == step:
                return last
            # 那一下之後電腦整格換過就不動(別的手機也在加不擋)
            stockcount.take_back_line(count, last.product, step - n, last.created_at, phone.created_by, last.line_ref)
            stockcount.add_to_line(count, last.product, n - step, phone.created_by)
            last.after = (last.before or 0) + n
            last.save(update_fields=["after", "updated_at"])
            return last
    except stockcount.CountError as exc:
        raise PhoneError(str(exc)) from None


def undo(phone: StockCountPhone, device: str, op, target=None) -> StockCountTap | None:
    """「收回這一下」:這支手機最後那一下倒回去。之後被別人改過就不動。"""
    count = phone.count
    try:
        with transaction.atomic():
            stockcount._locked(count, S.COUNTING)
            phone = _still(phone.pk, device)
            if _seen_op(count, phone, op):
                return None
            last = _last(count, phone.pk)
            _aimed(last, target)
            if last is None:
                raise PhoneError("沒有可以收回的")
            if last.kind == T.LINE:
                stockcount.put_back_line(count, last.product, last.after - (last.before or 0), last.created_at, phone.created_by,
                                         last.line_ref)
            elif last.kind == T.SCAN:
                if last.scan_id is None or not StockCountScan.objects.filter(pk=last.scan_id, count=count).exists():
                    raise PhoneError("那一台已經被拿掉了")
                stockcount.remove_scan(count, last.scan_id)
            else:
                if last.unknown_id is None:
                    raise PhoneError("那個碼已經處理過了,請到電腦上看")
                stockcount.untally_unknown(count, last.unknown_id)
            last.undone = True
            last.save(update_fields=["undone", "updated_at"])
            return last
    except stockcount.CountError as exc:
        raise PhoneError(str(exc)) from None


def finish(phone: StockCountPhone, device: str) -> None:
    """手機自己按「結束」:只結束它自己那一次配對。"""
    StockCountPhone.objects.filter(pk=phone.pk, device_hash=_hash(device), ended_at__isnull=True).update(ended_at=timezone.now())


def phone_view(phone: StockCountPhone) -> dict:
    """手機看得到的:哪一張單、哪一家門市、自己的稱呼、自己最近刷了什麼與那個品項大家合起來數到幾個。**沒有帳上數量。**"""
    count = phone.count
    taps = list(StockCountTap.objects.filter(count=count, phone_ref=phone.pk)
                .select_related("product", "scan__serial__product").order_by("-id")[:RECENT])
    totals = dict(count.lines.filter(product_id__in=[t.product_id for t in taps if t.product_id])
                  .values_list("product_id", "counted_qty"))
    unknown_times = dict(StockCountUnknown.objects.filter(pk__in=[t.unknown_id for t in taps if t.unknown_id])
                         .values_list("pk", "times"))
    rows = []
    for t in taps:
        row = {"id": t.id, "kind": t.kind, "code": t.code, "undone": t.undone, "at": t.created_at}
        if t.kind == T.LINE:
            row.update(name=t.product.name, step=t.after - (t.before or 0), total=totals.get(t.product_id, 0))
        elif t.kind == T.SCAN:
            s = t.scan
            row.update(name=(s.serial.product.name if s and s.serial_id else (s.old_name if s else "")) or "不認得")
        else:
            row.update(name="沒對到", total=unknown_times.get(t.unknown_id, 0))
        rows.append(row)
    return {"no": count.no, "warehouse": count.warehouse.name, "label": phone.label, "taps": rows}
