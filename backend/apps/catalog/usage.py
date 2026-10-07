"""商品「用過沒有」:決定會影響庫存怎麼算的屬性還能不能改。

三個屬性 —— 需追蹤序號 / 中古機 / 虛擬商品 —— 決定一件商品的庫存怎麼記(一台一筆序號、按數量、還是不記),
中古機另外決定成本怎麼算(每一台自己的成本)。進貨 / 銷貨 / 銷退 / 調撥 / 維修在**作廢、退貨、確認**的時候,
是看商品**現在**的這幾個屬性來決定庫存怎麼加減回去。所以:

    按數量賣出去 → 有人把商品改成「需追蹤序號」→ 作廢那張銷貨單 → 數量加不回去。

規則(owner 2026-10-07):
- **沒用過**的商品,這三個屬性照舊隨便改。
- **用過**的不能改,要講清楚為什麼、怎麼辦(先把那些單作廢、庫存歸零;或停用這個品號另外建一個)。
- 「用過」= 有任何**沒作廢**的單據明細(進貨 / 銷貨 / 銷退 / 調撥 / 維修領料)、還沒過帳也沒取消的待確認入庫、
  沒作廢的序號,或任何門市的庫存數量不是 0。**作廢的單不算** —— 那就是改錯之後的出路。

只擋這三個屬性;品名、規格、條碼、類別(不會連帶變成中古機的)、售價、販售狀態都不受影響。
"""
from __future__ import annotations

from dataclasses import dataclass

STOCK_FLAGS = ("requires_serial", "is_secondhand", "is_virtual")
FLAG_LABELS = {
    "requires_serial": "需追蹤序號",
    "is_secondhand": "中古機",
    "is_virtual": "虛擬商品",
}


def flags_after_save(*, category_secondhand: bool, is_secondhand: bool,
                     requires_serial: bool, is_virtual: bool) -> dict[str, bool]:
    """商品存檔之後這三個屬性實際會是什麼(`Product.save` 就是照這個存的,只有這一份)。

    - 類別是「中古機類別」→ 商品一定是中古機;
    - 中古機一定追蹤序號、不能是虛擬商品。
    """
    secondhand = bool(is_secondhand or category_secondhand)
    return {
        "is_secondhand": secondhand,
        "requires_serial": True if secondhand else bool(requires_serial),
        "is_virtual": False if secondhand else bool(is_virtual),
    }


#: `Model.save()` 可以照位置給的四個參數與它們的預設值(Django 5.1;照位置給是舊寫法,6.0 會拿掉)
_SAVE_DEFAULTS = {"force_insert": False, "force_update": False, "using": None, "update_fields": None}


def save_arguments(args, kwargs):
    """`save(*args, **kwargs)` → `(這一次會寫哪些欄位, 全部換成關鍵字的參數)`;欄位是 None = 全部都寫。

    呼叫的人要拿回傳的那一份參數去呼叫 `super().save(**kwargs)`,兩個原因:
    - `update_fields` 可能是只能看一次的產生器,這裡看過一次就空了,原樣再交給 Django 會變成「一個欄位都不寫」而出錯
      → 整理成 frozenset,往下傳的就是這一份;
    - 這裡判斷的「這次寫哪些欄位」要跟 Django 實際寫的一模一樣。照位置給的參數**照 Django 自己的規則**對回名字
      (`Model._parse_params`):那個位置有給、同名的關鍵字又不是預設值 → 重複給了,`TypeError`;
      關鍵字是預設值(例:`save(False, False, None, ["name"], update_fields=None)`)→ 用照位置給的那一個;
      超過四個 → `TypeError`。有問題的呼叫在這裡就丟錯,不會先跑到後面的檢查。
    """
    if len(args) > len(_SAVE_DEFAULTS):
        raise TypeError(
            f"Model.save() takes from 1 to {len(_SAVE_DEFAULTS) + 1} positional arguments "
            f"but {len(args) + 1} were given"
        )
    named = dict(kwargs)
    for (name, default), value in zip(_SAVE_DEFAULTS.items(), args):
        if named.get(name, default) is not default:
            raise TypeError(f"Model.save() got multiple values for argument '{name}'")
        named[name] = value
    fields = named.get("update_fields")
    if fields is not None:
        fields = named["update_fields"] = frozenset(fields)
    return fields, named


def category_is_secondhand(category_id) -> bool | None:
    """這個類別**現在**是不是「中古機類別」(只讀、不鎖);沒有這一列回 None。"""
    from .models import Category

    if not category_id:
        return None
    return (
        Category.objects.filter(pk=category_id)
        .values_list("is_secondhand_default", flat=True)
        .first()
    )


def lock_category(category_id) -> bool | None:
    """鎖住這個類別那一列(到交易結束),回它**現在**是不是「中古機類別」;沒有這一列回 None。要在交易裡呼叫。

    只有兩件事拿這把鎖:把類別改成中古機類別(會連帶改底下所有商品)、把既有商品**移進**這個類別。
    不鎖的話:甲檢查完「底下沒有用過的商品」正要連帶改,乙剛好把一個用過的商品移進來 —— 甲那一下就把它改掉了。
    鎖到之後重讀類別現在的設定(不看記憶體裡那一份:它可能是對方提交之前讀的)。
    **沒有換類別的商品存檔不拿這把鎖**(只改售價、品名…):每一次存檔都拿的話,兩批各含好幾個類別的批次修改
    會照不同的順序各拿各的類別,互相等到死結。
    **順序固定:先類別、後商品**(跟 `Category.save` 連帶改底下商品同一個方向)。一個交易要把好幾個商品移進
    同一個類別(批次修改),要在動任何商品之前先拿好這把鎖,不能改到一半才拿。
    用 NO KEY 的鎖:不擋別人新增指到這個類別的商品,只擋另一個也要拿這把鎖的。
    """
    from .models import Category

    if not category_id:
        return None
    return (
        Category.objects.select_for_update(no_key=True)
        .filter(pk=category_id)
        .values_list("is_secondhand_default", flat=True)
        .first()
    )


@dataclass(frozen=True)
class Usage:
    """一個商品被用過的地方(每一項一句話,例:「2 張進貨單」「庫存 5 件」)。空的 = 沒用過。"""

    reasons: tuple[str, ...] = ()
    #: 裡面有沒有單據(進貨 / 銷貨 / 銷退 / 調撥 / 維修 / 待確認入庫)。只有庫存或序號(舊資料匯入的)就沒有單可以作廢
    has_documents: bool = False

    @property
    def locked(self) -> bool:
        return bool(self.reasons)

    @property
    def way_out(self) -> str:
        """改錯了怎麼辦。有單:把單作廢、庫存歸零就可以改;沒有單(匯入的庫存):只能停用、另外建。"""
        if self.has_documents:
            return "先把這些單作廢、庫存歸零再改,或停用這個品號另外建一個"
        return "停用這個品號,另外建一個對的"

    @property
    def text(self) -> str:
        return "、".join(self.reasons)


def _sources(products):
    """[(哪一種, 指到這些商品而且還算數的紀錄)]。`products` 可以是一個商品、一串編號或一個查詢。

    每一種都只算**還算數**的:作廢的單、已取消 / 已過帳的待確認入庫(過帳的那一張算在進貨單)、作廢的序號、數量 0 的庫存都不算。
    """
    from apps.identity.models import IntakeBatch, IntakeItem
    from apps.inventory.models import ProductSerial, StockBalance
    from apps.purchasing.models import PurchaseOrderItem
    from apps.repairs.models import RepairOrderPart
    from apps.sales.models import SalesOrderItem, SalesReturnItem
    from apps.transfers.models import TransferOrderItem

    pending = (IntakeBatch.Status.OPEN, IntakeBatch.Status.RESOLVED)
    return [
        ("purchase", PurchaseOrderItem.objects.filter(product__in=products, po__is_void=False), "po_id", "product_id"),
        ("sale", SalesOrderItem.objects.filter(product__in=products, so__is_void=False), "so_id", "product_id"),
        ("return", SalesReturnItem.objects.filter(product__in=products, sr__is_void=False), "sr_id", "product_id"),
        ("transfer", TransferOrderItem.objects.filter(product__in=products, to__is_void=False), "to_id", "product_id"),
        ("repair", RepairOrderPart.objects.filter(part_product__in=products, repair_order__is_void=False),
         "repair_order_id", "part_product_id"),
        ("intake", IntakeItem.objects.filter(matched_product__in=products, batch__status__in=pending),
         "id", "matched_product_id"),
        ("serial", ProductSerial.objects.filter(product__in=products).exclude(status=ProductSerial.Status.VOID),
         "id", "product_id"),
        ("stock", StockBalance.objects.filter(product__in=products).exclude(qty=0), "id", "product_id"),
    ]


_PHRASES = {
    "purchase": "{n} 張進貨單",
    "sale": "{n} 張銷貨單",
    "return": "{n} 張銷退單",
    "transfer": "{n} 張調撥單",
    "repair": "{n} 張維修單",
    "intake": "{n} 筆待確認入庫",
    "serial": "{n} 台序號",
}


def product_usage(product) -> Usage:
    """這個商品用過沒有、用在哪裡。"""
    from django.db.models import Sum

    reasons: list[str] = []
    documents = False
    for kind, rows, doc, _ in _sources([product.pk]):
        if kind == "stock":
            # 庫存講件數(各門市加起來)。數量不會是負的(資料庫有擋),所以加起來是 0 就是真的沒有
            total = rows.aggregate(n=Sum("qty"))["n"] or 0
            if total:
                reasons.append(f"庫存 {total} 件")
            continue
        n = rows.values(doc).distinct().count()
        if n:
            reasons.append(_PHRASES[kind].format(n=n))
            documents = documents or kind != "serial"
    return Usage(tuple(reasons), documents)


def used_product_ids(products) -> set[int]:
    """這一批商品裡用過的那幾個(一次查完,給「整個類別一起改」用;不逐個商品查)。"""
    used: set[int] = set()
    for _, rows, _, product_field in _sources(products):
        used.update(rows.values_list(product_field, flat=True).distinct())
    return used


class StockFlagsLocked(Exception):
    """用過的商品不能改會影響庫存怎麼算的屬性。`str()` 就是給人看的那句話。"""


def locked_message(changed: list[str], usage: Usage) -> str:
    labels = "、".join(f"「{FLAG_LABELS[f]}」" for f in changed)
    return f"{labels}不能改:這個商品已經用過({usage.text})。{usage.way_out}。"


def stored_flags(product, *, lock=False) -> dict | None:
    """資料庫裡這個商品現在的三個屬性與類別(不是記憶體裡那一份:它可能已經被改過了);沒有這一筆回 None。

    `lock=True`:先鎖住這一列(到交易結束)再讀,要在交易裡呼叫。存檔本來就會鎖這一列,這裡只是提早到「讀」之前 ——
    類別改成中古機類別時也是先把底下的商品一列一列鎖住才改(`Category.save`),兩邊排隊:
    不會這一邊讀到改之前的值、等對方改完,又把舊的值寫回去。跟庫存那一套(`lock_stock_rows`)用同一種鎖。
    """
    from .models import Product

    if not product.pk:
        return None
    rows = Product.objects.filter(pk=product.pk)
    if lock:
        rows = rows.select_for_update(no_key=True)
    return rows.values("category_id", *STOCK_FLAGS).first()


def check_stock_flags(product, new_flags: dict[str, bool], written=STOCK_FLAGS, current=None) -> None:
    """商品要存成 `new_flags`(存檔之後實際的值)。用過、而且三個屬性裡有變的 → `StockFlagsLocked`。

    比的是資料庫裡現在的值(`current`;沒給就自己查)。新商品、沒有變的都直接過。
    `written` = 這一次存檔真的會寫進去的那幾個屬性(只存部分欄位時):沒有要寫的,記憶體裡改了什麼都不算變更。
    """
    if not product.pk or not written:
        return
    if current is None:
        current = stored_flags(product)
    if current is None:
        return
    changed = [f for f in STOCK_FLAGS if f in written and bool(current[f]) != bool(new_flags[f])]
    if not changed:
        return
    usage = product_usage(product)
    if usage.locked:
        raise StockFlagsLocked(locked_message(changed, usage))


def cascade_targets(category):
    """類別改成「中古機類別」時會被連帶改到的商品:底下還不是 中古機 + 追蹤序號 + 不是虛擬 的那些。
    本來就是那樣的不用改(不寫它們;但連帶改之前一樣要鎖,見 `lock_category_products`)。"""
    from .models import Product

    return Product.objects.filter(category=category).exclude(
        is_secondhand=True, requires_serial=True, is_virtual=False
    )


def lock_category_products(category) -> None:
    """照編號順序鎖住這個類別底下**全部**的商品(到交易結束)。類別要連帶改底下的商品之前呼叫;要在交易裡、而且已經拿到類別的鎖。

    不能只鎖「現在看起來要改的」:本來就是中古機的那一個,可能正有人在存檔把它改成不是(那一邊鎖著它、還沒提交)。
    不等它的話,這一邊把類別改完提交,它才把「不是中古機」寫進去 —— 類別是中古機類別,底下卻有一個不是。
    全部鎖住 = 等所有正在存檔的做完;之後才看哪些要改、哪些用過(`cascade_targets` / `category_cascade_blockers`)。
    照編號:跟進貨鎖商品(`lock_stock_rows`)、批次修改同一個順序,不會各拿一半互等。
    """
    from .models import Product

    list(
        Product.objects.filter(category=category)
        .order_by("pk")
        .select_for_update(no_key=True)
        .values_list("pk", flat=True)
    )


def category_cascade_blockers(category):
    """類別要改成「中古機類別」:底下會被連帶改到、而且用過的商品(照品號排)。空的 = 可以改。

    連帶會把商品改成 中古機 + 追蹤序號 + 不是虛擬;本來就是那樣的不會被改到,不算。
    """
    from .models import Product

    used = used_product_ids(cascade_targets(category).values("pk"))
    if not used:
        return Product.objects.none()
    return Product.objects.filter(pk__in=used).order_by("sku")


def cascade_message(blockers) -> str:
    total = blockers.count()
    names = "".join(f"「{p.name}」" for p in blockers[:3])
    more = f"等 {total} 個" if total > 3 else f" {total} 個"
    return (
        f"不能勾「中古機類別」:底下{names}{more}商品已經用過,會被一起改成中古機。"
        "先把那幾個商品移到別的類別,或另外開一個中古機類別。"
    )
