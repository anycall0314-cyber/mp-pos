"""舊 → 新對照:列候選、確認、撤銷。

規則(見 docs/資料底層與自然語言報表_規劃.md 第 3 節):
- 電話、名稱、代碼只拿來**列候選**,不自動對照;要人確認才算數。
- 一個舊代號同時只對到一個新對象;要改,先撤銷再確認,兩次都記在 LegacyMappingLog。
- 對照的對象必須是同一家公司的;跨公司一律擋。
- 原文不改,對照只是另一層。
"""
from __future__ import annotations

import hashlib

from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

from .importer import phone_digits
from .models import (
    LegacyMappingLog,
    LegacyMember,
    LegacyProductMap,
    LegacySalespersonMap,
    LegacyStoreMap,
    MapMethod,
    MapStatus,
)

MIN_PHONE_DIGITS = 8


class MappingError(Exception):
    """對照不能這樣做(原因可以直接給人看)。"""


def _user(user):
    return user if getattr(user, "is_authenticated", False) else None


# ─────────────────────────── 會員 ───────────────────────────
def member_candidates(legacy_member):
    """這個舊會員可能是哪幾位 MP 會員(只列出來,不對照)。"""
    from apps.parties.models import Member

    out, seen = [], set()
    digits = legacy_member.phone_digits
    qs = Member.objects.filter(tenant=legacy_member.tenant)
    if len(digits) >= MIN_PHONE_DIGITS:
        for m in qs.exclude(phone=""):
            if phone_digits(m.phone) == digits:
                out.append((m, MapMethod.PHONE))
                seen.add(m.pk)
    name = legacy_member.name_raw.strip()
    if name:
        for m in qs.filter(name=name).exclude(pk__in=seen):
            out.append((m, MapMethod.NAME))
    return out


def legacy_candidates(member):
    """這位 MP 會員可能對應哪幾個還沒對照的舊會員(電話或姓名相同)。"""
    digits = phone_digits(member.phone)
    base = LegacyMember.objects.filter(tenant=member.tenant, status=MapStatus.UNMAPPED)
    out = []
    if len(digits) >= MIN_PHONE_DIGITS:
        out += [(lm, MapMethod.PHONE) for lm in base.filter(phone_digits=digits)]
    name = member.name.strip()
    if name:
        seen = {lm.pk for lm, _ in out}
        out += [
            (lm, MapMethod.NAME)
            for lm in base.exclude(pk__in=seen).filter(name_raw__contains=name)
            if lm.name_raw.strip() == name
        ]
    return out


@transaction.atomic
def link_member(legacy_member, member, user, method=MapMethod.MANUAL, note=""):
    lm = LegacyMember.objects.select_for_update().get(pk=legacy_member.pk)
    if member.tenant_id != lm.tenant_id:
        raise MappingError("不能對照到別家公司的會員")
    if lm.status == MapStatus.CONFIRMED:
        if lm.member_id == member.pk:
            return lm
        raise MappingError("這個舊會員已經對照到另一位會員,要改請先撤銷")
    lm.member = member
    lm.status = MapStatus.CONFIRMED
    lm.method = method
    lm.confirmed_by = _user(user)
    lm.confirmed_at = timezone.now()
    lm.save(update_fields=["member", "status", "method", "confirmed_by", "confirmed_at",
                           "updated_at"])
    _log(lm.tenant, LegacyMappingLog.Kind.MEMBER, lm.source_system, lm.source_member_id,
         LegacyMappingLog.Action.CONFIRM, method, None, member.pk,
         f"{member.code} {member.name}", user, note)
    return lm


@transaction.atomic
def unlink_member(legacy_member, user, note=""):
    lm = LegacyMember.objects.select_for_update().get(pk=legacy_member.pk)
    if lm.status != MapStatus.CONFIRMED:
        raise MappingError("這個舊會員還沒有對照")
    old = lm.member_id
    lm.member = None
    lm.status = MapStatus.UNMAPPED
    lm.method = ""
    lm.confirmed_by = None
    lm.confirmed_at = None
    lm.save(update_fields=["member", "status", "method", "confirmed_by", "confirmed_at",
                           "updated_at"])
    _log(lm.tenant, LegacyMappingLog.Kind.MEMBER, lm.source_system, lm.source_member_id,
         LegacyMappingLog.Action.REVOKE, "", old, None, "", user, note)
    return lm


@transaction.atomic
def create_member_from_legacy(legacy_member, user):
    """用舊會員的姓名、電話在 MP 建一位會員並對照。同公司已經有同電話的會員就不建
    (那很可能是同一個人,應該用「對照」而不是再建一位)。"""
    from apps.parties.models import Member

    lm = LegacyMember.objects.select_for_update().get(pk=legacy_member.pk)
    if lm.status == MapStatus.CONFIRMED:
        raise MappingError("這個舊會員已經對照過了")
    # 兩個同電話的舊會員同時按「建立會員」:先拿「公司 + 電話」這把鎖,再查有沒有同電話的人
    if lm.phone_digits and connection.vendor == "postgresql":
        key = int.from_bytes(hashlib.sha256(
            f"mppos-member-phone:{lm.tenant_id}:{lm.phone_digits}".encode()
        ).digest()[:8], "big", signed=True)
        with connection.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s)", [key])
    # 防重複要比「任何非空電話完全相同」,不受列候選時 8 碼門檻的限制
    same_phone = []
    if lm.phone_digits:
        same_phone = [
            m for m in Member.objects.filter(tenant=lm.tenant).exclude(phone="")
            if phone_digits(m.phone) == lm.phone_digits
        ]
    if same_phone:
        raise MappingError(
            "已經有同電話的會員:" + "、".join(f"{m.code} {m.name}" for m in same_phone[:5])
            + ",請改用對照"
        )
    name = lm.name_raw.strip() or lm.display_id
    member = Member(tenant=lm.tenant, name=name[:120], phone=lm.phone_raw.strip()[:40],
                    note=f"由舊 POS 會員 {lm.display_id} 建立"[:200])
    member.save()
    return link_member(lm, member, user, method=MapMethod.CREATED), member


# ─────────────────────────── 店別 / 品號 / 業務員 ───────────────────────────
_MAPS = {
    LegacyMappingLog.Kind.STORE: (LegacyStoreMap, "store_name_raw", "warehouse"),
    LegacyMappingLog.Kind.PRODUCT: (LegacyProductMap, "product_code_raw", "product"),
    LegacyMappingLog.Kind.SALESPERSON: (LegacySalespersonMap, "salesperson_raw", "sales_person"),
}


def _label(target):
    for attr in ("sku", "code"):
        if getattr(target, attr, ""):
            return f"{getattr(target, attr)} {getattr(target, 'name', '')}".strip()[:200]
    return str(target)[:200]


@transaction.atomic
def confirm_map(kind, mapping, target, user, method=MapMethod.MANUAL, note=""):
    model, key_field, target_field = _MAPS[kind]
    row = model.objects.select_for_update().get(pk=mapping.pk)
    if target.tenant_id != row.tenant_id:
        raise MappingError("不能對照到別家公司的資料")
    if row.status == MapStatus.CONFIRMED:
        if getattr(row, f"{target_field}_id") == target.pk:
            return row
        raise MappingError("已經對照到別的對象,要改請先撤銷")
    setattr(row, target_field, target)
    row.status = MapStatus.CONFIRMED
    row.method = method
    row.confirmed_by = _user(user)
    row.confirmed_at = timezone.now()
    row.save()
    _log(row.tenant, kind, row.source_system, getattr(row, key_field),
         LegacyMappingLog.Action.CONFIRM, method, None, target.pk, _label(target), user, note)
    return row


@transaction.atomic
def revoke_map(kind, mapping, user, note=""):
    model, key_field, target_field = _MAPS[kind]
    row = model.objects.select_for_update().get(pk=mapping.pk)
    if row.status != MapStatus.CONFIRMED:
        raise MappingError("還沒有對照")
    old = getattr(row, f"{target_field}_id")
    setattr(row, target_field, None)
    row.status = MapStatus.UNMAPPED
    row.method = ""
    row.confirmed_by = None
    row.confirmed_at = None
    row.save()
    _log(row.tenant, kind, row.source_system, getattr(row, key_field),
         LegacyMappingLog.Action.REVOKE, "", old, None, "", user, note)
    return row


def store_candidates(store_map):
    """店名完全相同(去頭尾空白)的門市。"""
    from apps.inventory.models import Warehouse

    name = store_map.store_name_raw.strip()
    return list(Warehouse.objects.filter(tenant=store_map.tenant, name=name))


def product_candidates(product_map, limit=5):
    """舊品號可能是哪個商品:代碼完全相同(條碼 / 品號)優先,再用品名做叫法比對。
    只列候選。"""
    from apps.catalog.models import Product
    from apps.identity.product_match import find_candidates

    tenant = product_map.tenant
    code = product_map.product_code_raw.strip()
    out, seen = [], set()
    if code:
        for p in Product.objects.filter(tenant=tenant).filter(Q(barcode=code) | Q(sku=code))[:limit]:
            out.append((p, MapMethod.CODE, "代碼相同"))
            seen.add(p.pk)
    name = product_map.product_name_seen.strip()
    if name and len(out) < limit:
        result = find_candidates(tenant, name, limit=limit)
        ids = [c.product_id for c in result.candidates if c.product_id not in seen]
        products = Product.objects.filter(tenant=tenant).in_bulk(ids)
        for c in result.candidates:
            p = products.get(c.product_id)
            if p is None:
                continue
            out.append((p, MapMethod.MATCH, "、".join(c.reasons) or c.level))
            seen.add(p.pk)
            if len(out) >= limit:
                break
    return out


def salesperson_candidates(sp_map):
    """代號或姓名完全相同的業務員。"""
    from apps.parties.models import SalesPerson

    raw = sp_map.salesperson_raw.strip()
    if not raw:
        return []
    return list(
        SalesPerson.objects.filter(tenant=sp_map.tenant).filter(Q(code=raw) | Q(name=raw))[:5]
    )


def _log(tenant, kind, source_system, key, action, method, old, new, label, user, note):
    LegacyMappingLog.objects.create(
        tenant=tenant, kind=kind, source_system=source_system, key_raw=key[:300],
        action=action, method=method or "", old_target_id=old, new_target_id=new,
        target_label=label[:200], by=_user(user), note=(note or "")[:300],
    )
