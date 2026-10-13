"""平台內的同行當廠商:開了批發的經銷商 = 叫貨頁上的一家廠商,接法「平台內」(owner 2026-10-14;賣家那一半在 `apps/trade/`)。

跟全自動的廠商走**同一套**(現問商品、下單、查進度、照對方那張單到貨入庫),差在不用金鑰、不走網路:
`Client` 把每一次「打廠商」改成直接呼叫賣家那一側的 `trade.api.handle` —— 對外的 HTTP 端點呼叫的是同一支,所以兩種接法的資料樣子一模一樣。

- 原本放金鑰的位置,放的是一個只在程式裡流動的標記(`token`:哪一家公司的哪一間門市)。它是伺服器照「這張串接是誰的」組出來的,
  不是使用者輸入的,偽造不了;也不存進資料庫。
- 廠商名單上的那一筆(`Vendor`,接法 `platform`)在賣家開放批發時自動建好(`sync_vendor`);代碼由賣家公司的識別碼算出來,換一台伺服器也一樣。
- 誰看得到這家「廠商」:賣家那邊的規則(`trade.partners.can_see`)——核准的同行,或賣家把中古機開成平台販售。自己看不到自己。
- 沒有金鑰,所以這家門市能不能叫是看管理員「開通」了沒(跟半自動的廠商同一格);輸入往來代碼加入的,每一間門市自動開通。
"""
from dataclasses import dataclass

from django.db import transaction

from apps.inventory.models import Warehouse
from apps.tenants.models import Tenant

from . import standard
from .models import Vendor, VendorCategory, VendorLink

PREFIX = "platform:"
CATEGORY = "同行批發"


class Wrong(Exception):
    """不讓做(訊息是給人看的)。"""


def is_platform(vendor) -> bool:
    return vendor is not None and vendor.protocol == Vendor.Protocol.PLATFORM


def code_for(seller: Tenant) -> str:
    return f"d-{seller.backup_uuid.hex[:12]}"


def sync_vendor(seller: Tenant) -> Vendor | None:
    """照賣家現在的批發設定,把廠商名單上的那一筆建好 / 更新(開著 = 合作中;關掉 = 停用,已經叫的單照樣查得到、入得了庫)。
    從來沒開過的不建。"""
    from apps.trade.base import setting_of

    is_open = setting_of(seller).is_open
    found = Vendor.objects.filter(code=code_for(seller)).first()
    if found is None and not is_open:
        return None
    with transaction.atomic():
        vendor, _ = Vendor.objects.update_or_create(
            code=code_for(seller),
            defaults={"name": seller.name[:40], "protocol": Vendor.Protocol.PLATFORM, "seller": seller,
                      "is_active": is_open and seller.is_active, "sort_order": 500})
        category, _ = VendorCategory.objects.get_or_create(name=CATEGORY, defaults={"sort_order": 500})
        vendor.categories.add(category)
    return vendor


def open_to(vendor: Vendor, tenant) -> bool:
    """這家公司(當買家)看不看得到這個同行。"""
    from apps.trade import partners
    from apps.trade.base import setting_of

    if tenant is None or vendor.seller_id is None or vendor.seller_id == tenant.id:
        return False
    return any(partners.can_see(setting_of(vendor.seller), partners.view_as(vendor.seller, tenant)))


def token(link: VendorLink) -> str:
    return f"{PREFIX}{link.tenant_id}:{link.warehouse_id}"


def _who(key: str):
    """標記 → (買家公司, 門市)。不是這個樣子的一律不認(不會拿別的字串當成哪一家公司)。"""
    parts = key[len(PREFIX):].split(":") if isinstance(key, str) and key.startswith(PREFIX) else []
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        raise standard.Unreachable("平台內的串接不對")
    store = Warehouse.objects.filter(pk=int(parts[1]), tenant_id=int(parts[0])).select_related("tenant").first()
    if store is None:
        raise standard.Unreachable("平台內的串接不對")
    return store.tenant, store


@dataclass(frozen=True)
class Client(standard.Client):
    """跟平台內的一個同行講話:路徑與內容跟對外的一模一樣,只是不出這台伺服器。"""

    seller_id: int = 0

    def _send(self, method: str, path: str, key: str, body: dict | None = None, timeout: float = 15) -> standard.Reply:
        from apps.trade import api, partners

        buyer, store = _who(key)
        seller = Tenant.objects.filter(pk=self.seller_id).first()
        if seller is None or seller.id == buyer.id:
            raise standard.Unreachable(f"找不到{self.name}")
        if _restoring(seller):
            # 賣家的資料還原中(公司維護鎖):這一側進來的請求不經過賣家的登入驗證,要自己擋 —— 當成對方系統暫時連不到
            # (下單 = 不知道有沒有成立,之後同一把鑰匙再送;不會在還原進行中改到賣家的資料)
            return standard.Reply(503, {"ok": False, "error": "對方的資料還原中,請稍後再試"})
        # 下單要有一筆存檔的往來對象:沒有往來過、而且賣家現在看得到他(賣家開著平台販售)→ 這時候才建一筆。
        # 其他的只是看;賣家沒有開放給他的,不會因為他試著下單就在賣家那邊多一筆往來對象
        from apps.trade.base import setting_of

        partner = partners.view_as(seller, buyer)
        if method == "POST" and path == "/orders" and not partner.pk and any(partners.can_see(setting_of(seller), partner)):
            partner = partners.ensure(seller, buyer)
        status, data = api.handle(seller, partner, method, path, body, store=store.name)
        return standard.Reply(status, data)


def _restoring(tenant) -> bool:
    from apps.backup.jobs import in_maintenance

    return in_maintenance(tenant)


def client(vendor: Vendor) -> Client:
    return Client(base="", name=vendor.name, seller_id=vendor.seller_id or 0)


def join(tenant: Tenant, user, code) -> Vendor:
    """買家的管理員輸入同行給的往來代碼:變成對方核准的往來對象,而且**每一間門市自動開通**(收件先帶門市自己的名稱、電話、地址)。"""
    from apps.trade import partners
    from apps.trade.base import TradeError

    try:
        with transaction.atomic():
            partner = partners.join(tenant, code)
            if _restoring(partner.tenant):         # 賣家的資料還原中:不在這時候寫它的往來對象(整段退回,代碼還能用)
                raise Wrong("對方的資料還原中,請稍後再試")
    except TradeError as exc:
        raise Wrong(str(exc)) from None
    vendor = sync_vendor(partner.tenant)
    if vendor is None:
        raise Wrong(f"「{partner.tenant.name}」還沒有開放批發,請對方先開")
    for store in Warehouse.objects.filter(tenant=tenant, is_active=True):
        link, created = VendorLink.objects.get_or_create(
            tenant=tenant, provider=vendor.code, warehouse=store,
            defaults={"opened": True, "payment_method": "月結", "delivery_method": "宅配" if store.address else "自取",
                      "ship_name": store.name[:60], "ship_phone": store.phone[:40], "ship_address": store.address[:200],
                      "updated_by": user})
        if not created and not link.opened:
            link.opened, link.updated_by = True, user
            link.save(update_fields=["opened", "updated_by", "updated_at"])
    return vendor
