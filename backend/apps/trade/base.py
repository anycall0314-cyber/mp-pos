"""批發共用的小東西:錯誤、這家公司的批發設定、出貨開銷貨單要用的客戶與付款方式。

**鎖的順序(全模組照這個,跟 `inventory/locking.py` 接得起來)**:
商品 → 序號 → 批發單那一列(與它的明細)→ 庫存餘額。
- 下單(`orders.place`):商品 → 訂的那幾台(序號),然後才新增批發單(新的一列,沒有人在等)。
- 出貨(`shipping.ship`):先鎖這一次要出的序號 → 批發單 → 銷貨過帳(序號已經在手上)→ 庫存餘額。
- 門市銷貨(`sales.services.commit_sales_order`):序號 → `holds.before_sale`(批發單)→ 庫存餘額。
順序相反的話,門市賣一台被訂走的機器與那張批發單出貨同時來,會互相等到死結。
"""
from decimal import Decimal

from django.db import IntegrityError, transaction

from apps.parties.models import Customer
from apps.tenants.models import PaymentMethod

from .models import TradePartner, TradeSetting

CREDIT_CODE = "peer"            # 「同行記帳」付款方式的代碼
CREDIT_NAME = "同行記帳"
ZERO = Decimal("0")


class TradeError(Exception):
    """不讓做 / 沒做成(訊息是給人看的)。`code` 給程式看。"""

    status = 400

    def __init__(self, message: str, code: str = "", status: int | None = None):
        super().__init__(message)
        self.code = code
        if status is not None:
            self.status = status


def setting_of(tenant) -> TradeSetting:
    """這家公司的批發設定(沒有就建一列預設的:沒開放)。"""
    found = TradeSetting.objects.filter(tenant=tenant).first()
    if found is not None:
        return found
    try:
        with transaction.atomic():
            return TradeSetting.objects.create(tenant=tenant)
    except IntegrityError:
        return TradeSetting.objects.get(tenant=tenant)


def credit_method(tenant) -> PaymentMethod:
    """批發出貨開的銷貨單用的付款方式:「同行記帳」(非現金,不進當日現金)。沒有就建。
    **建的時候就是停用的**:門市結帳的付款方式只列啟用的,櫃台不會選到它(選了的話那筆錢不在批發的帳上);
    銷貨過帳、報表都只看代碼,停用的照樣認得。"""
    found = PaymentMethod.objects.filter(tenant=tenant, code=CREDIT_CODE).first()
    if found is not None:
        return found
    try:
        with transaction.atomic():
            return PaymentMethod.objects.create(
                tenant=tenant, code=CREDIT_CODE, name=CREDIT_NAME, kind=PaymentMethod.Kind.NON_CASH, is_active=False,
                sort_order=900, note="批發出貨自動帶的(不用啟用);收到錢在「批發單 → 同行帳」記")
    except IntegrityError:
        return PaymentMethod.objects.get(tenant=tenant, code=CREDIT_CODE)


def customer_for(partner: TradePartner) -> Customer:
    """這個同行的銷貨單記在哪一個客戶底下;沒有就建一筆「同業」。呼叫的人要在交易裡。"""
    locked = TradePartner.objects.select_for_update().get(pk=partner.pk)
    if locked.customer_id:
        return locked.customer
    customer = Customer.objects.create(tenant=locked.tenant, name=locked.name[:120], kind=Customer.Kind.PEER, note="批發的同行")
    locked.customer = customer
    locked.save(update_fields=["customer", "updated_at"])
    partner.customer = customer
    return customer
