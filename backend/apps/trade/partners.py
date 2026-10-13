"""往來的同行(買家)。平台上的經銷商互相競爭:**不提供「所有經銷商的名單」給人挑**。

兩條路會多一個往來對象:
1. 賣家發一個一次性的往來代碼(`invite`),自己傳給同行;同行在叫貨頁輸入(`join`)→ 核准的往來對象,看得到全新機與配件的價錢。
2. 賣家把中古機開成「平台販售」:平台上沒有往來的同行也訂得到中古機,第一次下單時自動多一筆「平台同行」(`ensure`),賣家之後可以核准或不往來。
"""
import hashlib
import secrets
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.tenants.models import Tenant

from .base import TradeError, setting_of
from .models import TradeInvite, TradePartner, TradeSetting

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"      # 沒有 0 O 1 I:用講的、用打的都不會弄錯
CODE_LENGTH = 8
INVITE_DAYS = 7
TERMS = ("月結", "匯款", "貨到付款", "現金")


def find(seller, buyer: Tenant):
    return TradePartner.objects.filter(tenant=seller, buyer_uuid=buyer.backup_uuid).first()


def view_as(seller, buyer: Tenant) -> TradePartner:
    """這個買家在這個賣家眼中是誰(只是看商品用:沒有往來過的回一個沒存檔的「平台同行」,不因為有人看就多一筆資料)。"""
    return find(seller, buyer) or TradePartner(
        tenant=seller, kind=TradePartner.Kind.PLATFORM, buyer_uuid=buyer.backup_uuid, name=buyer.name[:120],
        status=TradePartner.Status.GUEST, percent=100, terms=setting_of(seller).default_terms)


def ensure(seller, buyer: Tenant) -> TradePartner:
    """下單要有一筆存檔的往來對象:沒有就建「平台同行」。名稱跟著對方公司現在的名字。"""
    found = find(seller, buyer)
    if found is None:
        setting = setting_of(seller)
        try:
            with transaction.atomic():
                return TradePartner.objects.create(
                    tenant=seller, kind=TradePartner.Kind.PLATFORM, buyer_uuid=buyer.backup_uuid, name=buyer.name[:120],
                    status=TradePartner.Status.GUEST, percent=setting.default_percent, terms=setting.default_terms)
        except IntegrityError:
            found = find(seller, buyer)
    return found


def can_see(setting: TradeSetting, partner: TradePartner) -> tuple[bool, bool]:
    """這個同行看不看得到 (中古機, 按數量賣的商品)。沒開放、不往來 = 都看不到。"""
    if not setting.is_open or partner.status == TradePartner.Status.BLOCKED:
        return False, False
    approved = partner.status == TradePartner.Status.APPROVED
    return approved or setting.units_to_all, approved


def sellers_for(buyer: Tenant) -> list[Tenant]:
    """這家公司(當買家)看得到哪幾家在批發。自己不算。"""
    mine = {p.tenant_id: p for p in TradePartner.objects.filter(buyer_uuid=buyer.backup_uuid)}
    out = []
    for setting in TradeSetting.objects.filter(is_open=True).exclude(tenant=buyer).select_related("tenant").order_by("tenant_id"):
        if not setting.tenant.is_active:
            continue
        partner = mine.get(setting.tenant_id) or TradePartner(status=TradePartner.Status.GUEST)
        if any(can_see(setting, partner)):
            out.append(setting.tenant)
    return out


def _hash(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def clean_percent(value) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 200:
        raise TradeError("折數要是 1 到 200 的整數(門市價的百分之幾)")
    return value


def clean_terms(value) -> str:
    if value not in TERMS:
        raise TradeError("付款方式只能是 " + " / ".join(TERMS))
    return value


def invite(seller, user, *, percent=None, terms=None):
    """發一個往來代碼。回 (紀錄, 代碼本身);代碼只在這一次回給畫面,之後查不到。"""
    setting = setting_of(seller)
    percent = clean_percent(setting.default_percent if percent is None else percent)
    terms = clean_terms(setting.default_terms if terms is None else terms)
    for _ in range(5):
        code = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))
        try:
            with transaction.atomic():
                return TradeInvite.objects.create(
                    tenant=seller, code_hash=_hash(code), hint=code[:2], percent=percent, terms=terms,
                    expires_at=timezone.now() + timedelta(days=INVITE_DAYS), created_by=user), code
        except IntegrityError:
            continue
    raise TradeError("代碼產生不出來,請再試一次")


def join(buyer: Tenant, code) -> TradePartner:
    """買家輸入往來代碼 → 變成那個賣家核准的往來對象(原本被設成不往來的也會恢復:代碼是賣家自己發的)。"""
    code = "".join(code.split()).upper() if isinstance(code, str) else ""
    wrong = TradeError("代碼不對或已經過期,請跟對方再要一個")
    if len(code) != CODE_LENGTH:
        raise wrong
    with transaction.atomic():
        found = TradeInvite.objects.select_for_update().filter(code_hash=_hash(code)).select_related("tenant").first()
        if found is None or found.used_at is not None or found.expires_at <= timezone.now():
            raise wrong
        seller = found.tenant
        if seller.id == buyer.id:
            raise TradeError("這是自己公司發的代碼")
        partner = ensure(seller, buyer)
        partner.status, partner.percent, partner.terms, partner.name = TradePartner.Status.APPROVED, found.percent, found.terms, buyer.name[:120]
        partner.save(update_fields=["status", "percent", "terms", "name", "updated_at"])
        found.used_at, found.partner = timezone.now(), partner
        found.save(update_fields=["used_at", "partner", "updated_at"])
    return partner


def change(partner: TradePartner, user, data: dict) -> TradePartner:
    fields = ["updated_by", "updated_at"]
    if "status" in data:
        if data["status"] not in TradePartner.Status.values:
            raise TradeError("往來的狀態不對")
        partner.status = data["status"]
        fields.append("status")
    if "percent" in data:
        partner.percent = clean_percent(data["percent"])
        fields.append("percent")
    if "terms" in data:
        partner.terms = clean_terms(data["terms"])
        fields.append("terms")
    if "note" in data:
        partner.note = data["note"].strip()[:200] if isinstance(data["note"], str) else ""
        fields.append("note")
    if "contact" in data:
        partner.contact = data["contact"].strip()[:120] if isinstance(data["contact"], str) else ""
        fields.append("contact")
    partner.updated_by = user
    partner.save(update_fields=fields)
    return partner
