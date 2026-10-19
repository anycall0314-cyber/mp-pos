"""舊 → 新對照:列候選、確認、撤銷。

規則(見 docs/資料底層與自然語言報表_規劃.md 第 3 節):
- 電話、名稱、代碼只拿來**列候選**,不自動對照;要人確認才算數。
- 一個舊代號同時只對到一個新對象;要改,先撤銷再確認,兩次都記在 LegacyMappingLog。
- 對照的對象必須是同一家公司的;跨公司一律擋。
- 原文不改,對照只是另一層。
"""
from __future__ import annotations

import hashlib
import re

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
_PLAIN_PHONE = re.compile(r"[\d\-\s()]+")


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
    member = _member_from(lm)
    return link_member(lm, member, user, method=MapMethod.CREATED), member


def _member_from(lm, how="", tidy_phone=False):
    """用舊會員的姓名、電話建一位 MP 會員(還沒對照)。

    `tidy_phone`:電話只是多了連字號 / 空白 / 括號的話,存成只有數字的(`0912-345-678` → `0912345678`)——
    會員是用電話找的,店員打的是數字;裡面還有別的字(`0912345678 太太`)就照原文,不猜。舊資料那一邊的原文不動。
    """
    from apps.parties.models import Member

    name = lm.name_raw.strip() or lm.display_id
    note = f"由舊 POS 會員 {lm.display_id} 建立" + (f"({how})" if how else "")
    phone = lm.phone_raw.strip()
    if tidy_phone and _PLAIN_PHONE.fullmatch(phone):
        phone = lm.phone_digits
    member = Member(tenant=lm.tenant, name=name[:120], phone=phone[:40], note=note[:200])
    member.save()
    return member


# ─────────────────────────── 會員:整批帶進來 ───────────────────────────
# owner 2026-10-09:「會員電話與消費記錄一起進去…新的消費記錄開始做,舊的看快照,統一都可以用會員電話查詢」。
# 不帶的話每個客人進來都要重問電話、重建會員。上面那些「一位一位、由人確認」的規則照舊,這裡是另一條路。
BULK_NOTE = "整批帶入"


def bring_in_members(tenant, user=None, *, since=None, require_phone=False, write=False, chunk=500):
    """還沒對照的舊會員,**一位建一位 MP 會員並對照**(一對一,不靠電話猜誰跟誰是同一個人、不合併)。

    例外只有一種:MP 裡已經有一位會員**電話與姓名都一樣**、只有一位、而且還沒對照到任何舊會員 → 對照到那一位,不另外建
    (已經在新系統建過的客人不要變成兩位)。同一支電話的好幾個舊會員各建各的。

    `since` = 只帶那一天之後還有消費的;`require_phone` = 只帶有電話的。`write=False` 是試算:不寫任何東西,
    回的數字跟真的跑一樣。可以重跑(已經對照的不動)。回 {created, linked, no_phone, left}。
    """
    from apps.parties.models import Member

    unmapped = LegacyMember.objects.filter(tenant=tenant, status=MapStatus.UNMAPPED)
    todo = unmapped
    if since is not None:
        from .models import LegacyDocument

        todo = todo.filter(pk__in=LegacyDocument.objects.filter(
            tenant=tenant, document_date__gte=since).values("legacy_member_id"))
    if require_phone:
        todo = todo.exclude(phone_digits="")
    ids = list(todo.order_by("pk").values_list("pk", flat=True))
    # MP 裡每一組(電話數字, 姓名)有哪幾位會員;已經對照到舊會員的那幾位
    taken = set(LegacyMember.objects.filter(tenant=tenant, member__isnull=False)
                .values_list("member_id", flat=True))
    same_key: dict = {}
    for m in Member.objects.filter(tenant=tenant).exclude(phone="").order_by("pk"):
        digits = phone_digits(m.phone)
        if digits:
            same_key.setdefault((digits, m.name.strip()), []).append(m.pk)
    out = {"created": 0, "linked": 0, "no_phone": 0, "left": unmapped.count() - len(ids)}
    for start in range(0, len(ids), chunk):
        with transaction.atomic():
            rows = (LegacyMember.objects.select_for_update()
                    .filter(pk__in=ids[start:start + chunk], status=MapStatus.UNMAPPED).order_by("pk"))
            for lm in rows:
                same = same_key.get((lm.phone_digits, lm.name_raw.strip()), []) if lm.phone_digits else []
                # 全公司同電話同姓名的**只有一位**、而且那一位還沒對照過,才連過去。
                # 有兩位以上就不猜 —— 就算其中一位已經對照到別的舊會員、看起來「只剩一位」也一樣
                if len(same) == 1 and same[0] not in taken:
                    target = same[0]
                    # 用掉這一位(試算也要記,數字才跟真的跑一樣);下一個同電話同姓名的舊會員另外建
                    taken.add(target)
                    out["linked"] += 1
                    if write:
                        link_member(lm, Member.objects.get(pk=target), user,
                                    method=MapMethod.PHONE, note=BULK_NOTE)
                    continue
                out["created"] += 1
                out["no_phone"] += 0 if lm.phone_digits else 1
                if write:
                    link_member(lm, _member_from(lm, BULK_NOTE, tidy_phone=True), user,
                                method=MapMethod.CREATED, note=BULK_NOTE)
    return out


def _member_is_used(member, legacy_member) -> bool:
    """這位會員有沒有被用過:任何一張表指到他就算。`legacy_member` 自己那一筆對照不算
    (那就是正要解除的);**別的**舊會員也對照到他的話算(人事後另外連的,刪了他那一筆會斷掉)。"""
    for rel in member._meta.related_objects:
        rows = rel.related_model._base_manager.filter(**{rel.field.name: member})
        if rel.related_model is LegacyMember:
            rows = rows.exclude(pk=legacy_member.pk)
        if rows.exists():
            return True
    return False


def take_back_members(tenant, user=None, *, write=False, chunk=500):
    """把整批帶入的收回去。只動「最新的一筆對照紀錄是整批帶入、而且現在還對照著那一位」的舊會員
    (人事後解除、改連、或解除之後又自己連回同一位的,都是人做的對照,不收):

    - 那位會員是整批帶入時**新建**的,而且在新系統沒有被用過 → 解除對照、刪掉那位會員;
    - 新建的但**已經被用過**(開過單、收過話費…,或人事後又把別的舊會員連到他)→ 不動(留著對照,舊紀錄還看得到);
    - 當時是連到**原本就有**的會員 → 只解除對照,不刪人。
    回 {removed, unlinked, kept}。
    """
    from apps.parties.models import Member

    # 每個舊會員**最新的**那一筆對照紀錄。要最新的:整批帶入之後人解除、又自己連回同一位,
    # 現在這個對照是人做的,不能因為以前有過一筆「整批帶入」就收掉
    latest = {}
    for system, key, action, note, target in LegacyMappingLog.objects.filter(
        tenant=tenant, kind=LegacyMappingLog.Kind.MEMBER,
    ).order_by("pk").values_list("source_system", "key_raw", "action", "note", "new_target_id"):
        latest[(system, key)] = (action, note, target)
    ids = [
        pk for pk, system, key, member_id in LegacyMember.objects.filter(
            tenant=tenant, status=MapStatus.CONFIRMED,
        ).order_by("pk").values_list("pk", "source_system", "source_member_id", "member_id")
        if latest.get((system, key)) == (LegacyMappingLog.Action.CONFIRM, BULK_NOTE, member_id)
    ]
    out = {"removed": 0, "unlinked": 0, "kept": 0}
    for start in range(0, len(ids), chunk):
        with transaction.atomic():
            rows = (LegacyMember.objects.select_for_update()
                    .filter(pk__in=ids[start:start + chunk], status=MapStatus.CONFIRMED).order_by("pk"))
            for lm in rows:
                member = Member.objects.select_for_update().get(pk=lm.member_id)
                created_here = lm.method == MapMethod.CREATED
                if created_here and _member_is_used(member, lm):
                    out["kept"] += 1
                    continue
                out["removed" if created_here else "unlinked"] += 1
                if write:
                    unlink_member(lm, user, note=f"收回{BULK_NOTE}")
                    if created_here:
                        member.delete()
    return out


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
