"""對外的同行(不在這套 POS 上的系統)用的金鑰。

- 賣家的管理員建一個「外部同行」→ 發一把金鑰。**原文只在發的那一次回給畫面**,資料庫只存雜湊;弄丟了只能換一把(舊的立刻失效)。
- 金鑰以 `mpk_` 開頭(對方把別的東西貼錯地方時認得出來;這套 POS 當買家時,平台管理員可以把這個開頭設在那家廠商上)。
- 一把金鑰就認得出是哪一家賣家的哪一個同行:對外的網址全平台同一個,不用每家一個。
- 每分鐘最多 `PER_MINUTE` 次(一句更新算;超過回 429)。
- **不進公司備份**:還原到較早的備份之後,備份之後才換掉 / 不往來的舊金鑰不能自己活過來 → 還原會清掉全部金鑰,要重發。
"""
import hashlib
import secrets
from datetime import timedelta

from django.db import transaction
from django.db.models import Case, F, Value, When
from django.utils import timezone

from .base import TradeError, setting_of
from .models import TradeKey, TradePartner
from .partners import clean_percent, clean_terms

PREFIX = "mpk_"
PER_MINUTE = 120


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _new(partner: TradePartner, user) -> str:
    raw = PREFIX + secrets.token_urlsafe(30)
    TradeKey.objects.update_or_create(
        partner=partner,
        defaults={"tenant": partner.tenant, "key_hash": _hash(raw), "hint": raw[:8], "window_start": None,
                  "window_count": 0, "last_used_at": None, "created_by": user})
    return raw


def create_external(seller, user, *, name, contact="", percent=None, terms=None):
    """建一個對外的同行並發金鑰。回 (同行, 金鑰原文)。"""
    name = name.strip() if isinstance(name, str) else ""
    if not name or len(name) > 120:
        raise TradeError("要填對方的名稱(120 個字以內)")
    contact = contact.strip() if isinstance(contact, str) else ""
    if not contact or len(contact) > 120:
        # 單上只有名字認不出是誰、也不知道怎麼聯絡(紅隊 2026-10-14):建的時候就要有
        raise TradeError("要填怎麼聯絡對方(電話或 LINE,120 個字以內)")
    setting = setting_of(seller)
    with transaction.atomic():
        partner = TradePartner.objects.create(
            tenant=seller, kind=TradePartner.Kind.EXTERNAL, name=name, contact=contact,
            status=TradePartner.Status.APPROVED,
            percent=clean_percent(setting.default_percent if percent is None else percent),
            # 外面的對象預設不是月結(錢不經過系統:先收到再出比較保險;賣家可以在那一列改)
            terms=clean_terms("匯款" if terms is None else terms), updated_by=user)
        return partner, _new(partner, user)


def rotate(partner: TradePartner, user) -> str:
    """換一把(舊的立刻失效)。回新的原文。"""
    if partner.kind != TradePartner.Kind.EXTERNAL:
        raise TradeError("平台內的同行不用金鑰")
    with transaction.atomic():
        return _new(partner, user)


def find(raw):
    """這把金鑰是誰的(`TradeKey`,帶著同行與賣家公司);不認得回 None。"""
    if not isinstance(raw, str) or not raw.startswith(PREFIX) or not 20 <= len(raw) <= 200:
        return None
    return TradeKey.objects.filter(key_hash=_hash(raw)).select_related("partner__tenant").first()


def hit(key: TradeKey) -> bool:
    """算一次、回這一次可不可以(每分鐘最多 `PER_MINUTE` 次)。一句更新:兩個請求同時來也不會少算。"""
    now = timezone.now()
    fresh = now - timedelta(minutes=1)
    TradeKey.objects.filter(pk=key.pk).update(
        window_count=Case(When(window_start__gt=fresh, then=F("window_count") + 1), default=Value(1)),
        window_start=Case(When(window_start__gt=fresh, then=F("window_start")), default=Value(now)),
        last_used_at=now)
    return TradeKey.objects.filter(pk=key.pk).values_list("window_count", flat=True).first() <= PER_MINUTE
