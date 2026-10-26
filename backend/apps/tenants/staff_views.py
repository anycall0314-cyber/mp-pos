"""員工帳號(系統設定 → 員工帳號)。只有公司管理員 / 平台管理員能看、能改。

這裡管:
- 身份別(owner 2026-10-27):店長、門市、行政…自己增刪,每一個身份別一組勾選;還有人在用的刪不掉。
- 店員帳號:新增(名字、帳號、密碼、門市、身份別;同時建一位同名的業務員)、改名字 / 門市 / 鎖門市 / 身份別、
  這個帳號自己的例外(多開 / 多關;清單與判斷在 abilities.py)、重設密碼、停用 / 啟用(owner 2026-10-19)。
- 「管理者」= 公司管理員帳號:固定全開,這裡不能改;管理員帳號照舊在平台管理。
"""
import re

from django.contrib.auth import get_user_model
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.core.exceptions import ValidationError
from django.db import transaction
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.inventory.models import Warehouse
from apps.parties.models import SalesPerson

from . import abilities
from .auth_views import password_problem, set_password_and_sign_out
from .models import StaffRole, UserProfile
from .permissions import is_tenant_admin

NAME_MAX = 30
ROLE_NAME_MAX = 20


def _row(profile) -> dict:
    user = profile.user
    sales_person = getattr(user, "sales_person", None)
    store = profile.default_warehouse
    role = profile.staff_role
    editable = profile.role == UserProfile.Role.TENANT_USER
    return {
        "id": user.id,
        "username": user.username,
        "name": (sales_person.name if sales_person else "") or f"{user.last_name}{user.first_name}",
        "role": profile.role,
        "role_label": profile.get_role_display(),
        "staff_role": {"id": role.id, "name": role.name} if role and editable else None,
        "warehouse": f"{store.code} {store.name}" if store else "",
        "warehouse_id": store.id if store else None,
        "warehouse_locked": profile.is_warehouse_locked,
        "is_active": user.is_active,
        # 管理員永遠全開、不能在這裡關
        "editable": editable,
        # 實際能不能做(連帶關掉的也算關)
        "abilities": abilities.for_user(user),
        # 自己開或關(身份別 + 例外,不算連帶的):帳號頁的勾選照這個畫
        "own": abilities.own(abilities.switched_off(profile)) if editable else abilities.for_user(user),
        "exceptions": abilities.exceptions(profile) if editable else [],
    }


def _role_row(role, count: int) -> dict:
    return {
        "id": role.id,
        "name": role.name,
        "abilities": abilities.own(abilities.role_off(role)),
        "accounts": count,
    }


def _company_accounts(tenant):
    return (
        UserProfile.objects.filter(tenant=tenant)
        .select_related("user", "user__sales_person", "default_warehouse", "staff_role")
        .order_by("role", "user__username")
    )


def _company_roles(tenant) -> list[dict]:
    roles = list(StaffRole.objects.filter(tenant=tenant).order_by("id"))
    counts: dict[int, int] = {}
    for role_id in UserProfile.objects.filter(
        tenant=tenant, role=UserProfile.Role.TENANT_USER, staff_role__isnull=False,
    ).values_list("staff_role_id", flat=True):
        counts[role_id] = counts.get(role_id, 0) + 1
    return [_role_row(r, counts.get(r.id, 0)) for r in roles]


def next_username(tenant) -> str:
    """建議的帳號名稱:公司代碼 + 下一個流水號(歐睿的慣例,例 JB005)。帳號全系統不能重複,所以看所有帳號。"""
    code = (tenant.code or "").strip()
    if not code:
        return ""
    pattern = re.compile(rf"^{re.escape(code)}(\d+)$", re.IGNORECASE)
    numbers, width = [], 3
    for name in get_user_model().objects.filter(username__istartswith=code).values_list("username", flat=True):
        m = pattern.match(name)
        if m:
            numbers.append(int(m.group(1)))
            width = max(width, len(m.group(1)))
    return f"{code}{str(max(numbers, default=0) + 1).zfill(width)}"


def _forbidden(text: str):
    return Response({"detail": text}, status=status.HTTP_403_FORBIDDEN)


def _bad(text: str):
    return Response({"detail": text}, status=status.HTTP_400_BAD_REQUEST)


def _abilities_problem(wanted) -> str:
    if not isinstance(wanted, dict):
        return "權限的格式不對"
    if any(not isinstance(k, str) or k not in abilities.KEYS for k in wanted):
        return "沒有這個權限項目"
    if any(not isinstance(v, bool) for v in wanted.values()):
        return "每一項只能是可以 / 不可以"
    return ""


def _blocked_text(found) -> str:
    key, because = found
    names = "、".join(abilities.LABELS[k] for k in because)
    return f"「{abilities.LABELS[key]}」要先開:{names}"


def _name(value) -> tuple[str, str]:
    """(名字, 問題)。"""
    if not isinstance(value, str) or not value.strip():
        return "", "名字要填"
    name = value.strip()
    if len(name) > NAME_MAX:
        return "", f"名字最多 {NAME_MAX} 個字"
    return name, ""


def _store(tenant, value) -> tuple[Warehouse | None, str]:
    """(門市, 問題)。空的 = 不指定門市。"""
    if value in (None, ""):
        return None, ""
    if isinstance(value, bool) or not isinstance(value, int):
        return None, "門市的格式不對"
    store = Warehouse.objects.filter(tenant=tenant, pk=value, is_active=True).first()
    return store, "" if store else "找不到這間門市"


def _locked_role(tenant, value) -> tuple[StaffRole | None, str]:
    """(身份別, 問題)。鎖住那一列:同時有人在刪它時,刪的那邊看得到這個帳號、刪不掉。"""
    if isinstance(value, bool) or not isinstance(value, int):
        return None, "身份別的格式不對"
    role = StaffRole.objects.select_for_update().filter(tenant=tenant, pk=value).first()
    return role, "" if role else "找不到這個身份別"


def _set_name(user, name: str) -> None:
    user.first_name, user.last_name = name[:150], ""
    user.save(update_fields=["first_name", "last_name"])
    sales_person = getattr(user, "sales_person", None)
    if sales_person is not None and sales_person.name != name:
        sales_person.name = name
        sales_person.save(update_fields=["name", "updated_at"])


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def staff_accounts(request):
    if request.method == "POST":
        return _create_account(request)
    if not is_tenant_admin(request.user):
        return _forbidden("只有管理員可以看員工帳號的權限")
    return Response({
        "abilities": abilities.catalog(),
        "accounts": [_row(p) for p in _company_accounts(request.tenant)],
        "roles": _company_roles(request.tenant),
        "next_username": next_username(request.tenant),
    })


def _create_account(request):
    """新增店員帳號:`{username, name, password, warehouse, warehouse_locked, staff_role, abilities?}`。
    `abilities` 是跟身份別不一樣的項目(例外)。同時建一位同名的業務員(代號 = 帳號),開單的經手人才選得到他、登入後預設帶他。"""
    if not is_tenant_admin(request.user):
        return _forbidden("只有管理員可以新增員工帳號")
    data = request.data if isinstance(request.data, dict) else {}
    tenant = request.tenant
    username = data.get("username")
    if not isinstance(username, str) or not username.strip():
        return _bad("帳號要填")
    username = username.strip()
    if len(username) > 20:
        return _bad("帳號最多 20 個字")
    try:
        UnicodeUsernameValidator()(username)
    except ValidationError:
        return _bad("帳號只能用英文、數字和 @ . + - _")
    name, problem = _name(data.get("name"))
    if problem:
        return _bad(problem)
    problem = password_problem(data.get("password"))
    if problem:
        return _bad(problem)
    locked = data.get("warehouse_locked", False)
    if not isinstance(locked, bool):
        return _bad("鎖門市只能是要 / 不要")
    store, problem = _store(tenant, data.get("warehouse"))
    if problem:
        return _bad(problem)
    if locked and store is None:
        return _bad("鎖在門市要先選門市")
    wanted = data.get("abilities", {})
    problem = _abilities_problem(wanted)
    if problem:
        return _bad(problem)
    User = get_user_model()
    with transaction.atomic():
        role = None
        if data.get("staff_role") is not None:
            role, problem = _locked_role(tenant, data.get("staff_role"))
            if problem:
                return _bad(problem)
        elif StaffRole.objects.filter(tenant=tenant).exists():
            return _bad("要選身份別")
        # 帳號全系統不能重複;大小寫不同也當成同一個(登入時打錯大小寫會進到別人的帳號)
        if User.objects.filter(username__iexact=username).exists():
            return _bad(f"帳號 {username} 已經有人用了")
        if SalesPerson.objects.filter(tenant=tenant, code__iexact=username[:20]).exists():
            return _bad(f"業務員代號 {username} 已經有人用了,換一個帳號")
        user = User.objects.create_user(username=username, password=data["password"], first_name=name)
        profile = UserProfile(
            user=user, tenant_id=tenant.pk, role=UserProfile.Role.TENANT_USER,
            default_warehouse=store, is_warehouse_locked=locked, staff_role=role, denied_abilities=[],
        )
        if wanted:
            profile.denied_abilities = abilities.change(profile, wanted)
            found = abilities.turned_on_but_blocked(abilities.switched_off(profile), wanted)
            if found:
                transaction.set_rollback(True)
                return _bad(_blocked_text(found))
        profile.save()
        SalesPerson.objects.create(tenant_id=tenant.pk, code=username[:20], name=name, user=user)
    profile = _company_accounts(tenant).get(user=user)
    return Response(_row(profile), status=status.HTTP_201_CREATED)


@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def staff_account(request, pk: int):
    """改店員帳號:`name`、`warehouse`、`warehouse_locked`、`staff_role`、`abilities`(`{項目: 可不可以}`)都可以只送一部分。

    `abilities` 跟身份別一樣的項目回到身份別(不記),不一樣的記成例外。換身份別 = 例外清掉、完全照新身份別;
    同一次送的 `abilities` 再跟新身份別比,記成新的例外。
    """
    if not is_tenant_admin(request.user):
        return _forbidden("只有管理員可以改員工帳號")
    data = request.data if isinstance(request.data, dict) else {}
    fields = {"name", "warehouse", "warehouse_locked", "staff_role", "abilities"} & set(data)
    if not fields:
        return _bad("沒有要改的項目")
    wanted = data.get("abilities", {})
    problem = _abilities_problem(wanted)
    if problem:
        return _bad(problem)
    if fields == {"abilities"} and not wanted:
        return _bad("沒有要改的項目")
    tenant = request.tenant
    name = ""
    if "name" in data:
        name, problem = _name(data["name"])
        if problem:
            return _bad(problem)
    store = None
    if "warehouse" in data:
        store, problem = _store(tenant, data["warehouse"])
        if problem:
            return _bad(problem)
    if "warehouse_locked" in data and not isinstance(data["warehouse_locked"], bool):
        return _bad("鎖門市只能是要 / 不要")
    with transaction.atomic():
        # 連點兩項會有兩個請求同時進來:鎖住這個帳號再改,後到的看得到先到的結果(不然會互相蓋掉)
        profile = (
            UserProfile.objects.select_for_update()
            .select_related("user").filter(tenant=tenant, user_id=pk).first()
        )
        if profile is None:
            return Response({"detail": "找不到這個帳號"}, status=status.HTTP_404_NOT_FOUND)
        if profile.role != UserProfile.Role.TENANT_USER:
            return _bad("管理員帳號永遠全開,不能在這裡改")
        changed = []
        if "staff_role" in data:
            if data["staff_role"] is None:
                return _bad("要選身份別")
            role, problem = _locked_role(tenant, data["staff_role"])
            if problem:
                return _bad(problem)
            if role.pk != profile.staff_role_id:
                # 換身份別 = 完全照新身份別,例外清掉;要留的例外畫面同一次送在 abilities 裡(下面跟新身份別比)
                profile.denied_abilities = abilities.leftovers(profile.denied_abilities)
                profile.staff_role = role
                changed += ["staff_role", "denied_abilities"]
        if wanted:
            profile.denied_abilities = abilities.change(profile, wanted)
            # 這一次要開的項目,開了也還是不能用(它要的另外幾項關著)→ 不存、講要先開哪幾項(不然那一格會自己彈回去,人不知道為什麼)
            found = abilities.turned_on_but_blocked(abilities.switched_off(profile), wanted)
            if found:
                transaction.set_rollback(True)
                return _bad(_blocked_text(found))
            changed.append("denied_abilities")
        if "warehouse" in data:
            profile.default_warehouse = store
            changed.append("default_warehouse")
        if "warehouse_locked" in data:
            profile.is_warehouse_locked = data["warehouse_locked"]
            changed.append("is_warehouse_locked")
        if profile.is_warehouse_locked and profile.default_warehouse_id is None and (
            {"warehouse", "warehouse_locked"} & fields
        ):
            transaction.set_rollback(True)
            return _bad("鎖在門市要先選門市")
        if changed:
            profile.save(update_fields=sorted(set(changed)) + ["updated_at"])
        if "name" in data:
            _set_name(profile.user, name)
    profile = _company_accounts(tenant).get(pk=profile.pk)
    return Response(_row(profile))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def staff_account_access(request, pk: int):
    """幫自己公司的店員重設密碼(`{"password": ...}`),或停用 / 啟用那個帳號(`{"is_active": false/true}`)。

    重設或停用都會讓那個店員每一台都要重新登入。停用連業務員一起停(開單選不到他),啟用一起開;
    以前的單據、獎金都還在(不刪帳號,單據指著他)。管理員帳號這裡不能動。
    """
    from rest_framework.authtoken.models import Token

    if not is_tenant_admin(request.user):
        return _forbidden("只有管理員可以管員工帳號")
    data = request.data if isinstance(request.data, dict) else {}
    wants_password, wants_active = "password" in data, "is_active" in data
    if wants_password == wants_active:
        return _bad("沒有要改的項目")
    if wants_password:
        problem = password_problem(data["password"])
        if problem:
            return _bad(problem)
    elif not isinstance(data["is_active"], bool):
        return _bad("只能是停用 / 啟用")
    with transaction.atomic():
        profile = (
            UserProfile.objects.select_for_update()
            .select_related("user").filter(tenant=request.tenant, user_id=pk).first()
        )
        if profile is None:
            return Response({"detail": "找不到這個帳號"}, status=status.HTTP_404_NOT_FOUND)
        if profile.role != UserProfile.Role.TENANT_USER:
            return _bad("管理員帳號請找平台")
        user = profile.user
        if wants_password:
            set_password_and_sign_out(user, data["password"])
        else:
            user.is_active = data["is_active"]
            user.save(update_fields=["is_active"])
            if not user.is_active:
                Token.objects.filter(user=user).delete()
            sales_person = getattr(user, "sales_person", None)
            if sales_person is not None and sales_person.is_active != user.is_active:
                sales_person.is_active = user.is_active
                sales_person.save(update_fields=["is_active", "updated_at"])
    profile = _company_accounts(request.tenant).get(pk=profile.pk)
    return Response(_row(profile))


def _role_name(tenant, value, exclude_pk=None) -> tuple[str, str]:
    if not isinstance(value, str) or not value.strip():
        return "", "身份別名稱要填"
    name = value.strip()
    if len(name) > ROLE_NAME_MAX:
        return "", f"身份別名稱最多 {ROLE_NAME_MAX} 個字"
    if name == "管理者":
        return "", "「管理者」是固定的,換一個名稱"
    if StaffRole.objects.filter(tenant=tenant, name=name).exclude(pk=exclude_pk).exists():
        return "", f"已經有「{name}」了"
    return name, ""


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def staff_roles(request):
    """新增身份別:`{name, abilities?, copy_from?}`。照另一個身份別的勾選開始(`copy_from`),再套 `abilities`。"""
    if not is_tenant_admin(request.user):
        return _forbidden("只有管理員可以新增身份別")
    data = request.data if isinstance(request.data, dict) else {}
    tenant = request.tenant
    wanted = data.get("abilities", {})
    problem = _abilities_problem(wanted)
    if problem:
        return _bad(problem)
    with transaction.atomic():
        name, problem = _role_name(tenant, data.get("name"))
        if problem:
            return _bad(problem)
        role = StaffRole(tenant_id=tenant.pk, name=name, denied_abilities=[])
        if data.get("copy_from") is not None:
            source = StaffRole.objects.filter(tenant=tenant, pk=data["copy_from"]).first() if isinstance(
                data["copy_from"], int) and not isinstance(data["copy_from"], bool) else None
            if source is None:
                return _bad("找不到要照的身份別")
            role.denied_abilities = list(source.denied_abilities or [])
        role.denied_abilities = abilities.change_role(role, wanted)
        found = abilities.turned_on_but_blocked(abilities.role_off(role), wanted)
        if found:
            return _bad(_blocked_text(found))
        role.save()
    return Response(_role_row(role, 0), status=status.HTTP_201_CREATED)


@api_view(["PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def staff_role(request, pk: int):
    """改身份別(`{name?, abilities?}`;改勾選,那個身份的人一起變)或刪掉(還有人在用的刪不掉)。"""
    if not is_tenant_admin(request.user):
        return _forbidden("只有管理員可以改身份別")
    tenant = request.tenant
    data = request.data if isinstance(request.data, dict) else {}
    with transaction.atomic():
        # 鎖住這一列:同時改兩次不互相蓋掉;同時有人把帳號換成這個身份別時,刪的這邊等它做完才數人數
        role = StaffRole.objects.select_for_update().filter(tenant=tenant, pk=pk).first()
        if role is None:
            return Response({"detail": "找不到這個身份別"}, status=status.HTTP_404_NOT_FOUND)
        in_use = UserProfile.objects.filter(staff_role=role).count()
        if request.method == "DELETE":
            if in_use:
                return _bad(f"還有 {in_use} 個帳號是「{role.name}」,先把他們換成別的身份別")
            role.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        if not ({"name", "abilities"} & set(data)):
            return _bad("沒有要改的項目")
        wanted = data.get("abilities", {})
        problem = _abilities_problem(wanted)
        if problem:
            return _bad(problem)
        if "name" in data:
            name, problem = _role_name(tenant, data["name"], exclude_pk=role.pk)
            if problem:
                return _bad(problem)
            role.name = name
        if wanted:
            role.denied_abilities = abilities.change_role(role, wanted)
            found = abilities.turned_on_but_blocked(abilities.role_off(role), wanted)
            if found:
                transaction.set_rollback(True)
                return _bad(_blocked_text(found))
        role.save()
    return Response(_role_row(role, in_use))
