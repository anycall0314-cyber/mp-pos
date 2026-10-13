"""把叫貨單送進廠商的下單網站(owner 2026-10-13:kcimos「我就是要全自動，因為kcimos叫貨看冗長的品名是地獄體驗」)。

廠商的網站沒有 API,送單是 POS 提供的小幫手(`frontend/public/kcimos-helper.js`)在**人登入過的那個瀏覽器分頁**裡做的:
POS 的網頁不能直接對那個網站送東西(跨網站,瀏覽器不會把那邊的登入帶過去)。**登入是人做的**(用程式過驗證碼不做)。
這裡是 POS 這一側:發一次性的代碼、把這張單要送的內容交給小幫手、記進度、收結果。**這裡不連廠商的網站。**

送出去就是真的訂單、不能自己取消。要守住的(動手前紅隊三條):
1. **不知道有沒有成立,就不能再送**:小幫手在送出之前先說「要送了」(`submitting`);之後沒有回報結果 = 叫貨單「待確認」,
   要人到廠商的訂單查詢看過、選「訂單成立(填訂單編號)」或「沒有成立」,才能再送。
   「沒有成立」要等 `DENY_WAIT_MINUTES`(小幫手可能還在等網站回答);人先選了、小幫手才回報成立的,照網站的回答記(還沒再送的話)。
   還原到較早的備份也不能讓送過的單變回「還沒傳」(`facts_before_restore` / `reapply_after_restore`,還原時呼叫)。
2. **不能下到別的帳號**:廠商網站的帳號編號第一次送單時綁到那家門市(`VendorLink.site_account`),之後不是同一個帳號就不送。
3. **一個帳號只有一台購物車**:同一家門市 × 廠商,同時只能有一張叫貨單在動購物車(`claimed`)或待確認。
   小幫手那邊還會核對購物車跟這張單完全一樣才送、用備註裡的 POS 單號認訂單。

進度:`open`(發了代碼)→ `claimed`(開始動購物車)→ `submitting`(要送了)→ `done` / `failed`;中途放棄、過期 → `dropped`。

**鎖的順序固定:叫貨單 → 門市 × 廠商(`VendorLink`)→ 這一次送單 → 同一家門市別的送單(照編號)。**
會看「這張單現在能不能送」的那幾步(`claim` / `submitting`)與會改叫貨單的那幾步(`done` / `resolve`)都先鎖叫貨單 ——
跟手動的「標記已傳 / 取消」(`manual.mark_sent` / `set_cancelled`,也鎖叫貨單)排隊:不然有人剛手動標了已傳(他已經用 LINE 叫了),
同一瞬間另一個人在小幫手按送出,兩邊都過,廠商那邊就是兩張訂單。只動自己那一筆的(`payload` / `failed` / `release`)只鎖自己。
"""
import hashlib
import re
import secrets
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from . import kcimos, vendors
from .models import Vendor, VendorHandoff, VendorLink, VendorOrder
from .services import VendorError

State = VendorHandoff.State
# 代碼多久有效(從 POS 按「自動送單」到小幫手開始做)
CODE_MINUTES = 15
# 小幫手開始動購物車之後多久沒有下文,就當成那一次放棄了(不再擋同一家門市的別張單;購物車裡留下的東西小幫手下次會看到、停下來)
CLAIM_MINUTES = 10
# 說了「要送了」之後多久之內不給人按「沒有成立」:這段時間小幫手可能還在等廠商的網站回答(它最久等這麼久),
# 訂單查詢上還看不到不代表沒有成立 —— 太早按、再送一次,就是兩張訂單(複審 2026-10-14 第一輪)。「訂單成立」隨時可以按(看到了就是有)
DENY_WAIT_MINUTES = 5
DENIED = "人確認沒有成立"
ORDER_NO = re.compile(r"^[A-Za-z0-9-]{4,40}$")
ACCOUNT = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
MAX_AMOUNT = Decimal("99999999")


class HandoffError(VendorError):
    """小幫手那一側看得到的拒絕(一句話)。"""


USED = "這個代碼已經用過或過期了,請回 POS 重新按「自動送單」"


def site_of(vendor) -> dict | None:
    """這家廠商有沒有「下單網站 + 小幫手」。現在只有 kcimos(半自動、代碼對得上)。"""
    if vendor is not None and vendor.protocol == Vendor.Protocol.MANUAL and vendor.code == kcimos.CODE:
        return kcimos.SITE
    return None


def _hash(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _lines(order) -> list[dict]:
    """這張單要放進廠商購物車的每一行。料號認不出網站的商品編號、同一個商品出現兩行 → 這張單不能自動送(不猜)。"""
    out, seen = [], set()
    for item in order.items.all():
        pk = kcimos.site_pk(item.sku)
        if pk is None:
            raise VendorError(f"「{item.name}」的料號({item.sku})對不到廠商網站的商品,這張單不能自動送")
        if pk in seen:
            raise VendorError(f"「{item.name}」在這張單上出現兩次,這張單不能自動送")
        seen.add(pk)
        out.append({
            # 數量放的是**包數**:廠商網站的一件 = POS 的一包(一包幾個是 POS 自己換算庫存用的)
            "pk": pk, "qty": item.packs, "name": item.name, "spec": item.spec_label,
            "shop_name": item.product_name, "shop_sku": item.product_sku,
            "ref_price": None if item.unit_price is None else str(item.unit_price),
        })
    if not out:
        raise VendorError("這張叫貨單沒有明細")
    return out


def pending(order):
    """這張單「待確認」的那一次(沒有就 None)。"""
    return order.handoffs.filter(state=State.SUBMITTING).first()


def status(order, vendor_by_code=None) -> dict:
    """叫貨單在畫面上要知道的:能不能送進廠商網站、是不是待確認、廠商那邊的訂單編號。
    `vendor_by_code` = 列一整頁時先查好的 {代碼: 廠商};待確認看的是已經一起載進來的 `order.handoffs`(不要一張單查一次)。"""
    vendor = vendor_by_code.get(order.provider) if vendor_by_code is not None else vendors.find(order.provider)
    site = site_of(vendor) if order.manual else None
    waiting = next((h for h in order.handoffs.all() if h.state == State.SUBMITTING), None) if site else None
    return {
        "supported": site is not None,
        "label": site["label"] if site else "",
        "pending": waiting is not None,
        "pending_since": waiting.submitting_at if waiting else None,
        # 這個時間之前不能按「沒有成立」(小幫手可能還在送);畫面在那之前寫「送出中」
        "can_deny_at": _can_deny_at(waiting) if waiting else None,
        "external_order_no": order.external_order_no,
        # 寫在廠商那張訂單備註裡的字:待確認時,人到廠商的訂單查詢就是找它
        "memo": memo_of(order) if site else "",
    }


def _can_deny_at(waiting):
    return (waiting.submitting_at or waiting.created_at) + timedelta(minutes=DENY_WAIT_MINUTES)


def _check_sendable(tenant, order) -> dict:
    """這張單現在可以送進廠商網站嗎(可以就回那個網站的資料)。"""
    vendor = vendors.find(order.provider)
    site = site_of(vendor) if order.manual else None
    if site is None:
        raise VendorError("這家廠商不能從這裡直接送單")
    if not vendor.is_active:
        raise VendorError(f"「{vendor.name}」已經停用,不能叫新的貨")
    if not vendors.open_to(vendor, tenant):
        raise VendorError(f"「{vendor.name}」沒有開放給這家公司,不能叫新的貨")
    if order.cancelled_at is not None:
        raise VendorError("這張叫貨單已經取消了")
    if order.sent_at is not None:
        raise VendorError("這張叫貨單已經傳給廠商了")
    if pending(order) is not None:
        raise VendorError("這張單上一次送出還不知道有沒有成立(待確認):請先到廠商的訂單查詢確認,再選「訂單成立」或「沒有成立」")
    if not order.link.opened:
        raise VendorError(f"這家門市還沒有開通{vendor.name}")
    return site


def start(*, tenant, user, order) -> tuple[str, VendorHandoff]:
    """POS 上按「自動送單」:發一組一次性的代碼。回 (要開的網址, 這一次)。代碼只在網址的 # 後面(不會送到廠商的伺服器)。"""
    with transaction.atomic():
        order = VendorOrder.objects.select_for_update(of=("self",)).select_related("link").get(tenant=tenant, pk=order.pk)
        site = _check_sendable(tenant, order)
        _lines(order)
        # 同一張單重新按:之前發的、還沒開始做的代碼作廢(一張單同時只有一組有效的代碼)
        order.handoffs.filter(state=State.OPEN).update(state=State.DROPPED, problem="重新發了代碼", finished_at=timezone.now())
        code = secrets.token_urlsafe(32)
        handoff = VendorHandoff.objects.create(
            tenant=tenant, order=order, code_hash=_hash(code),
            expires_at=timezone.now() + timedelta(minutes=CODE_MINUTES), created_by=user)
    return f"{site['origin']}{site['start']}#mppos={code}", handoff


def _find(code, *, lock=False) -> VendorHandoff:
    if not isinstance(code, str) or not 20 <= len(code) <= 80:
        raise HandoffError("代碼不對,請回 POS 重新按「自動送單」")
    rows = VendorHandoff.objects.select_related("order", "order__link", "order__warehouse", "tenant")
    if lock:
        rows = rows.select_for_update(of=("self",))
    handoff = rows.filter(code_hash=_hash(code)).first()
    if handoff is None:
        raise HandoffError("代碼不對,請回 POS 重新按「自動送單」")
    from apps.backup.jobs import in_maintenance

    if in_maintenance(handoff.tenant):
        raise HandoffError("這家公司正在還原或維護中,等一下再試")
    return handoff


def _locked(code, *, link=False) -> VendorHandoff:
    """照固定的順序鎖好再回這一次送單:叫貨單 →(要的話)門市 × 廠商 → 這一次送單。回來的 `.order`、`.order.link` 是鎖到之後讀的。"""
    peek = _find(code)                       # 不鎖:只是要知道是哪一張單(代碼對到哪張單不會變)
    VendorOrder.objects.select_for_update(of=("self",)).get(pk=peek.order_id)
    if link:
        VendorLink.objects.select_for_update(of=("self",)).get(pk=peek.order.link_id)
    return _find(code, lock=True)


def _expire(handoff) -> None:
    if handoff.state == State.OPEN and handoff.expires_at <= timezone.now():
        handoff.state, handoff.problem, handoff.finished_at = State.DROPPED, "代碼過期", timezone.now()
        handoff.save(update_fields=["state", "problem", "finished_at", "updated_at"])


def payload(code) -> dict:
    """小幫手一開始拿的:這張單要送什麼、收件人、備註要寫什麼、這家門市綁的帳號。只有還沒開始做(`open`)、沒過期的代碼拿得到。"""
    with transaction.atomic():
        handoff = _find(code, lock=True)
        _expire(handoff)
        usable = handoff.state == State.OPEN
    if not usable:          # 在交易外面才丟:過期收掉的那一筆要存得進去
        raise HandoffError(USED)
    with transaction.atomic():
        handoff = _find(code, lock=True)
        if handoff.state != State.OPEN:
            raise HandoffError(USED)
        order = handoff.order
        _check_sendable(handoff.tenant, order)
        # 先講一聲(只看不動):別張單待確認時購物車裡可能還留著它的東西,不要讓人清了才知道這一張不能送
        blocker = _busy_elsewhere(handoff, take_over=True, peek=True)
        if blocker is not None:
            raise HandoffError(_busy_message(blocker))
        return {
            "order_no": order.vendor_order_no,
            "store": order.warehouse.name,
            "lines": _lines(order),
            "recipient": {"name": order.ship_name, "phone": order.ship_phone, "address": order.ship_address},
            # 寫在廠商訂單的備註:之後靠它認哪一張訂單是這張叫貨單(一個帳號可能同時有別的訂單)
            "memo": memo_of(order),
            "account": order.link.site_account,
            "expires_at": handoff.expires_at,
        }


def memo_of(order) -> str:
    return f"MP POS {order.vendor_order_no}"


def _busy_elsewhere(handoff, *, take_over=False, peek=False) -> VendorHandoff | None:
    """同一家門市 × 廠商,有沒有**別張**叫貨單正在動購物車(還新鮮的 `claimed`)或待確認。放太久的 `claimed` 順手收掉。
    `take_over`(開始動購物車時):**同一張單**之前那一次還停在 `claimed` —— 人回 POS 重新按了「自動送單」,
    這一次接手、舊的那一次作廢(舊分頁之後按送出會被擋);不然同一張單要自己等自己十分鐘。
    `peek`:只看、不鎖、不收(小幫手一開始先問一次,免得動了購物車才知道不能送;真正把關的是 `claim`)。"""
    stale = timezone.now() - timedelta(minutes=CLAIM_MINUTES)
    others = (VendorHandoff.objects
              .filter(tenant=handoff.tenant, order__link=handoff.order.link_id, state__in=[State.CLAIMED, State.SUBMITTING])
              .exclude(pk=handoff.pk).select_related("order").order_by("id"))
    if not peek:
        others = others.select_for_update(of=("self",))
    blocker = None
    for other in others:
        if other.state == State.CLAIMED and take_over and other.order_id == handoff.order_id:
            why = "同一張單重新送了"
        elif other.state == State.CLAIMED and other.claimed_at is not None and other.claimed_at < stale:
            why = "放進購物車之後沒有下文"
        else:
            blocker = blocker or other
            continue
        if not peek:
            other.state, other.problem, other.finished_at = State.DROPPED, why, timezone.now()
            other.save(update_fields=["state", "problem", "finished_at", "updated_at"])
    return blocker


def _busy_message(blocker) -> str:
    what = "上一次送出還沒確認有沒有成立" if blocker.state == State.SUBMITTING else "正在送"
    return f"另一張叫貨單({blocker.order.vendor_order_no}){what},等它處理完再送這一張"


def claim(code) -> dict:
    """小幫手要開始動購物車了。同一家門市 × 廠商同時只准一張(一個帳號只有一台購物車)。"""
    with transaction.atomic():
        handoff = _find(code, lock=True)
        _expire(handoff)
        usable = handoff.state == State.OPEN
    if not usable:
        raise HandoffError(USED)
    with transaction.atomic():
        # 連門市 × 廠商那一列一起鎖:兩個分頁同時來,一個一個過
        handoff = _locked(code, link=True)
        if handoff.state != State.OPEN:
            raise HandoffError(USED)
        _check_sendable(handoff.tenant, handoff.order)
        blocker = _busy_elsewhere(handoff, take_over=True)
        if blocker is not None:
            raise HandoffError(_busy_message(blocker))
        handoff.state, handoff.claimed_at = State.CLAIMED, timezone.now()
        handoff.save(update_fields=["state", "claimed_at", "updated_at"])
    return {"ok": True}


def _account(value) -> str:
    if not isinstance(value, str) or not ACCOUNT.match(value.strip()):
        raise HandoffError("讀不到廠商網站的帳號編號,沒有送出")
    return value.strip()


def submitting(code, account, bind=False) -> dict:
    """小幫手說「要送了」(人已經在確認視窗按了送出)。**從這一刻起,沒有回報結果就是待確認。**
    帳號:這家門市還沒綁 → 要人在確認視窗看過那一句、帶 `bind` 才綁;綁過的不是同一個 → 不送。"""
    with transaction.atomic():
        handoff = _locked(code, link=True)
        if handoff.state != State.CLAIMED:
            raise HandoffError("這一次送單已經不在進行中(可能放太久、或被另一張單接手),沒有送出;請回 POS 重新按「自動送單」")
        account = _account(account)
        # 叫貨單是鎖到之後讀的:剛被手動標成已傳 / 取消的,這裡看得到、不送
        _check_sendable(handoff.tenant, handoff.order)
        link = handoff.order.link
        blocker = _busy_elsewhere(handoff)
        if blocker is not None:
            raise HandoffError(f"另一張叫貨單({blocker.order.vendor_order_no})也在送,這一張沒有送出")
        if link.site_account and link.site_account != account:
            raise HandoffError("這個瀏覽器登入的不是這家門市綁定的 kcimos 帳號,沒有送出")
        if not link.site_account:
            if bind is not True:
                raise HandoffError("這家門市還沒有綁 kcimos 帳號,沒有送出")
            link.site_account = account
            link.save(update_fields=["site_account", "updated_at"])
        handoff.state, handoff.submitting_at, handoff.account = State.SUBMITTING, timezone.now(), account
        handoff.save(update_fields=["state", "submitting_at", "account", "updated_at"])
    return {"ok": True}


def _order_no(value) -> str:
    if not isinstance(value, str) or not ORDER_NO.match(value.strip()):
        raise HandoffError("訂單編號的樣子不對(只能是英文、數字、減號)")
    return value.strip()


def _amount(value):
    if value in (None, ""):
        return None
    try:
        amount = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        raise HandoffError("金額不對") from None
    if not amount.is_finite() or amount < 0 or amount > MAX_AMOUNT:
        raise HandoffError("金額不對")
    return amount.quantize(Decimal("0.01"))


def _placed(handoff, order_no, total, shipping, *, sent_by, resolved_by=None) -> None:
    """記成「已成立」:叫貨單標成已傳、記下廠商那邊的訂單編號與金額。同一個訂單編號不會掛到兩張叫貨單上。"""
    order = VendorOrder.objects.select_for_update(of=("self",)).get(pk=handoff.order_id)
    taken = (VendorOrder.objects.filter(tenant=handoff.tenant, provider=order.provider, external_order_no=order_no)
             .exclude(pk=order.pk).first())
    if taken is not None:
        raise HandoffError(f"訂單編號 {order_no} 已經記在另一張叫貨單({taken.vendor_order_no})上了")
    now = timezone.now()
    order.external_order_no = order_no
    if order.sent_at is None:
        order.sent_at, order.sent_how, order.sent_by = now, "site", sent_by
    order.vendor_ordered_at = order.vendor_ordered_at or now
    if total is not None:
        order.total_amount = total
    if shipping is not None:
        order.shipping_fee = shipping
    order.save(update_fields=["external_order_no", "sent_at", "sent_how", "sent_by", "vendor_ordered_at",
                              "total_amount", "shipping_fee", "updated_at"])
    handoff.state, handoff.external_order_no, handoff.finished_at = State.DONE, order_no, now
    handoff.resolved_by = resolved_by
    handoff.save(update_fields=["state", "external_order_no", "finished_at", "resolved_by", "problem", "updated_at"])


def done(code, order_no, total=None, shipping=None, note="") -> dict:
    """小幫手回報:訂單成立了。同一個結果再報一次照樣回成功(回應沒回來、它重報)。`note` = 廠商網站回的那句話(留著對照)。"""
    with transaction.atomic():
        handoff = _locked(code)
        order_no = _order_no(order_no)
        if handoff.state == State.DONE and handoff.external_order_no == order_no:
            return {"ok": True, "order_no": order_no}
        if handoff.state == State.DROPPED and handoff.problem == DENIED:
            # 人先選了「沒有成立」,小幫手才收到廠商網站說成立了:以網站的回答為準 —— 只要這張單還沒有再送出去。
            # 已經再送了(又待確認、或另一次成立了)就沒辦法兩張都記:明講這一張是多出來的,請人聯絡廠商取消
            order = handoff.order
            if order.sent_at is not None or pending(order) is not None:
                raise HandoffError(f"這張叫貨單已經重新送出了,廠商那邊的訂單 {order_no} 是多出來的一張,請聯絡廠商取消")
        elif handoff.state != State.SUBMITTING:
            raise HandoffError("這一次送單不是「待確認」的狀態,沒有記下來;請到 POS 的叫貨單確認")
        handoff.problem = (note if isinstance(note, str) else "")[:300]
        _placed(handoff, order_no, _amount(total), _amount(shipping), sent_by=handoff.created_by,
                resolved_by=handoff.resolved_by)
    return {"ok": True, "order_no": order_no}


def failed(code, message="") -> dict:
    """小幫手回報:廠商的網站明講不行(確定沒有成立)。叫貨單回到可以再送。"""
    with transaction.atomic():
        handoff = _find(code, lock=True)
        if handoff.state == State.FAILED or (handoff.state == State.DROPPED and handoff.problem == DENIED):
            return {"ok": True}            # 已經記成沒有成立了(小幫手重報,或人先選了「沒有成立」)
        if handoff.state != State.SUBMITTING:
            raise HandoffError("這一次送單不是「待確認」的狀態")
        handoff.state, handoff.finished_at = State.FAILED, timezone.now()
        handoff.problem = (message if isinstance(message, str) else "")[:300]
        handoff.save(update_fields=["state", "finished_at", "problem", "updated_at"])
    return {"ok": True}


def release(code, reason="") -> dict:
    """小幫手回報:這一次不送了(人按取消、購物車不是空的、核對不過 —— 都是在說「要送了」之前)。
    已經說「要送了」的不能從這裡收回:那要人確認有沒有成立。
    回 `released`:**這一下**才放掉的 = 到剛才為止購物車還是這一次的,小幫手可以把自己放進去的清掉;
    早就不是它的了(被同一張單重新送的那一次接手、放太久被收掉、過期)回 False —— 購物車現在可能是別的分頁在用,不能清(複審 2026-10-14 第一輪)。"""
    with transaction.atomic():
        handoff = _find(code, lock=True)
        if handoff.state == State.DROPPED:
            return {"ok": True, "released": False}
        if handoff.state not in (State.OPEN, State.CLAIMED):
            raise HandoffError("這一次已經說要送了,不能直接收回;請到 POS 的叫貨單確認有沒有成立")
        mine = handoff.state == State.CLAIMED            # 還沒開始動購物車的(`open`)本來就沒有東西要清
        handoff.state, handoff.finished_at = State.DROPPED, timezone.now()
        handoff.problem = (reason if isinstance(reason, str) else "")[:300]
        handoff.save(update_fields=["state", "finished_at", "problem", "updated_at"])
    return {"ok": True, "released": mine}


def resolve(*, tenant, user, order, placed, order_no="") -> VendorOrder:
    """人把「待確認」確認掉(到廠商的訂單查詢看過之後):已成立 → 填廠商的訂單編號;沒有成立 → 這張單回到可以再送。"""
    if not isinstance(placed, bool):
        raise VendorError("只能是「訂單成立」或「沒有成立」")
    with transaction.atomic():
        VendorOrder.objects.select_for_update(of=("self",)).get(tenant=tenant, pk=order.pk)      # 先叫貨單、後這一次送單
        handoff = (VendorHandoff.objects.select_for_update(of=("self",))
                   .filter(tenant=tenant, order=order, state=State.SUBMITTING).first())
        if handoff is None:
            raise VendorError("這張叫貨單沒有待確認的送出")
        if placed:
            try:
                number = _order_no(order_no)
            except HandoffError:
                raise VendorError("訂單成立要填廠商的訂單編號(英文、數字、減號)") from None
            try:
                _placed(handoff, number, None, None, sent_by=handoff.created_by, resolved_by=user)
            except HandoffError as exc:
                raise VendorError(str(exc)) from None
        else:
            wait = _can_deny_at(handoff) - timezone.now()
            if wait > timedelta(0):
                minutes = int(wait.total_seconds() // 60) + 1
                raise VendorError(f"小幫手可能還在送,{minutes} 分鐘後還沒有結果再確認(到時候先到廠商的訂單查詢看過)")
            handoff.state, handoff.finished_at = State.DROPPED, timezone.now()
            handoff.problem, handoff.resolved_by = DENIED, user
            handoff.save(update_fields=["state", "finished_at", "problem", "resolved_by", "updated_at"])
    return order


# ── 還原備份 ────────────────────────────────────────────────────────────────
def facts_before_restore(tenant) -> dict:
    """還原到較早的備份之前先記下來:哪幾張叫貨單已經在廠商的網站成立了、哪幾張待確認。
    備份可以把 POS 倒回去,**倒不回廠商那邊的訂單** —— 還原之後這幾張單要是變回「還沒傳」,再按一次自動送單就是第二張訂單
    (複審 2026-10-14 第一輪)。跟發票號碼、單號一樣:這種「已經給出去」的事只能往前。"""
    key = ("provider", "vendor_order_no", "request_key")
    placed = list(VendorOrder.objects.filter(tenant=tenant).exclude(external_order_no="")
                  .values(*key, "external_order_no", "sent_at", "vendor_ordered_at", "sent_by_id"))
    waiting = list(VendorHandoff.objects.filter(tenant=tenant, state=State.SUBMITTING)
                   .values(*(f"order__{k}" for k in key), "code_hash", "expires_at", "claimed_at", "submitting_at",
                           "account", "created_by_id"))
    return {"placed": placed, "waiting": waiting}


def reapply_after_restore(tenant, facts) -> int:
    """還原之後把上面記的放回去(只放在備份裡也有的那幾張單上:單號與當初的鑰匙都對得上)。回放回去幾張。
    就地還原不動帳號,所以「誰送的」照原本的編號放(那個帳號不在了就留空)。"""
    from django.contrib.auth import get_user_model

    def find(provider, no, request_key):
        return VendorOrder.objects.filter(tenant=tenant, provider=provider, vendor_order_no=no, request_key=request_key).first()

    def person(pk):
        return pk if pk is not None and get_user_model().objects.filter(pk=pk).exists() else None

    kept, now = 0, timezone.now()
    for row in facts["placed"]:
        order = find(row["provider"], row["vendor_order_no"], row["request_key"])
        if order is None or order.external_order_no:
            continue
        order.external_order_no = row["external_order_no"]
        if order.sent_at is None:
            order.sent_at, order.sent_how, order.sent_by_id = row["sent_at"] or now, "site", person(row.get("sent_by_id"))
        order.vendor_ordered_at = order.vendor_ordered_at or row["vendor_ordered_at"]
        order.save(update_fields=["external_order_no", "sent_at", "sent_how", "sent_by", "vendor_ordered_at", "updated_at"])
        # 備份裡這張單還停在待確認的那一次:已經知道結果了
        order.handoffs.filter(state=State.SUBMITTING).update(
            state=State.DONE, external_order_no=row["external_order_no"], finished_at=now)
        kept += 1
    for row in facts["waiting"]:
        order = find(row["order__provider"], row["order__vendor_order_no"], row["order__request_key"])
        # 備份裡這張單是「還沒傳」還是「手動標了已傳」都要放回去:手動的已傳可以收回,收回之後就能再送(複審第二輪)。
        # 不用放的只有:已經知道在廠商那邊成立了(有編號)、備份裡本來就待確認
        if order is None or order.external_order_no or pending(order) is not None:
            continue
        # 同一組代碼:小幫手要是還在等廠商的網站回答,還原之後它的回報照樣對得到這一筆。
        # 備份是在這一次送到一半時做的話,還原回來的資料裡已經有這一筆(停在前面的進度):接著改它,不另外新增(雜湊是唯一的)
        same = VendorHandoff.objects.filter(code_hash=row.get("code_hash") or "").first()
        if same is not None and (same.tenant_id != tenant.id or same.order_id != order.id):
            same, row = None, {**row, "code_hash": ""}                 # 不該發生;保險起見另外起一筆,不動別人的
        if same is None:
            same = VendorHandoff(tenant=tenant, order=order, code_hash=row.get("code_hash") or _hash(secrets.token_urlsafe(32)),
                                 expires_at=row.get("expires_at") or now, created_by_id=person(row.get("created_by_id")))
        same.state, same.finished_at, same.problem = State.SUBMITTING, None, "還原備份之前就待確認"
        same.claimed_at, same.submitting_at, same.account = row.get("claimed_at"), row["submitting_at"], row["account"]
        same.save()
        kept += 1
    return kept
