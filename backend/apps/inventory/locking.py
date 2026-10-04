"""庫存的「先鎖再檢查、再改」。銷貨、進貨、調撥、維修共用同一套。

為什麼要鎖:庫存數量與序號狀態都是「讀出來 → 判斷 / 加減 → 存回去」。兩張單同一瞬間動同一個
東西時,不先鎖就會各自讀到同一個舊值 —— 同一支 IMEI 被賣兩次、庫存少算一次、同一張單被確認兩次。

規則(每一個會改庫存的動作都要照做,而且都在交易內):

1. 先鎖「單據自己那一列」(`lock_document`),鎖到之後重讀,才判斷它是不是已經作廢 / 已經確認。
2. 再用 `lock_stock_rows` 把這張單會動到的東西一次鎖住,**順序固定**:
   商品 → 序號 → SIM 卡 → 庫存餘額(照門市、商品編號)。
   順序固定,兩張單的明細順序相反時才不會互相等到死結。
3. 鎖完之後才檢查狀態(在不在庫、夠不夠扣),才改。

商品、序號、SIM 卡用的是「不擋外鍵」的鎖(FOR NO KEY UPDATE):別張單只是新增一列指到同一個商品 /
序號時不會被擋住,但兩邊都要「改」它時仍然一次只有一個。
"""
from decimal import Decimal

from .models import ProductSerial, StockBalance


def lock_document(obj):
    """鎖住單據那一列並重讀;回傳同一個物件(欄位已是鎖到之後的值)。找不到回 None。"""
    # 明確把那一列取回來(不用 .exists():上不上鎖不該靠查詢最佳化的隱含行為)
    locked = (
        type(obj).objects.select_for_update().filter(pk=obj.pk)
        .values_list("pk", flat=True).first()
    )
    if locked is None:
        return None
    obj.refresh_from_db()
    return obj


def locked_balance(tenant, product, warehouse, create=False):
    """鎖住「這個門市這個商品」的庫存餘額再讀(沒有這一列時 create=True 會先建)。"""
    if create:
        StockBalance.objects.get_or_create(
            tenant=tenant, product=product, warehouse=warehouse,
            defaults={"qty": 0, "weighted_avg_cost": Decimal("0")},
        )
    return (
        StockBalance.objects.select_for_update()
        .filter(tenant=tenant, product=product, warehouse=warehouse)
        .first()
    )


def lock_stock_rows(tenant, *, products=(), serial_ids=(), sim_ids=(), balances=(), create=False):
    """照固定順序把會動到的東西鎖住。只鎖這家公司自己的列(別家的編號混進來也不會被鎖到;
    那種單之後會被同公司檢查擋下)。

    products   要改加權平均成本的商品(進貨、進貨作廢);鎖完會重讀成本
    serial_ids 會改狀態的序號
    sim_ids    會改狀態的 SIM 卡
    balances   [(商品, 門市), ...] 會加減數量的庫存餘額;create=True 時沒有的先建
    """
    from apps.catalog.models import Product
    from apps.parties.models import SimCard

    products = sorted({p.pk: p for p in products}.values(), key=lambda p: p.pk)
    if products:
        list(Product.objects.select_for_update(no_key=True)
             .filter(tenant=tenant, pk__in=[p.pk for p in products])
             .order_by("pk").values_list("pk", flat=True))
        for p in products:
            p.refresh_from_db(fields=["weighted_avg_cost"])
    serial_ids = sorted(set(serial_ids))
    if serial_ids:
        list(ProductSerial.objects.select_for_update(no_key=True)
             .filter(tenant=tenant, pk__in=serial_ids).order_by("pk").values_list("pk", flat=True))
    sim_ids = sorted(set(sim_ids))
    if sim_ids:
        list(SimCard.objects.select_for_update(no_key=True)
             .filter(tenant=tenant, pk__in=sim_ids).order_by("pk").values_list("pk", flat=True))
    pairs = {
        (w.pk, p.pk): (p, w) for p, w in balances
        if p.tenant_id == tenant.pk and w.tenant_id == tenant.pk
    }
    for key in sorted(pairs):
        product, warehouse = pairs[key]
        locked_balance(tenant, product, warehouse, create=create)
