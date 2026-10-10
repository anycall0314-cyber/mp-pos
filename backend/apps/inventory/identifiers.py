"""一台設備的兩個碼:IMEI 與 SN。可以兩個都有,也可以只有一個。

`ProductSerial.serial_no` 是主碼(有 IMEI 用 IMEI,沒有才用 SN):標籤、單據、既有畫面都照舊讀它。
兩個碼各存一列在 `ProductSerialIdentifier`。同一家公司裡,一個碼只能屬於一台
(比對前去掉空白 / 破折號 / 點、轉大寫),所以刷 IMEI 或刷 SN 找到的都是同一台。

規則:

- **每一個會新增設備的入口都要走 `create_serial()`**,不要直接 `ProductSerial.objects.create()`。
  直接建的那一台沒有登記碼,別台就可以再用同一個碼(`test_identifiers.py` 掃全專案把關)。
- 用碼找設備一律走 `find_serial_ids()`:完全相同才算,不做模糊比對。
- 事後補登 / 修改走 `set_codes()`:會鎖住那一台、留下修改紀錄(`ProductSerialCodeChange`)。
- **作廢的設備不佔碼**(進貨單作廢時 `release_codes()`):它的碼可以再給新的設備用,用碼找設備也不會找到它;
  作廢的那一筆留著 `serial_no` 當紀錄(序號清單用關鍵字還是查得到,狀態是作廢)。
"""
from django.db import IntegrityError, transaction
from django.db.models import Q

from apps.identity.normalize import normalize_serial

from .models import ProductSerial, ProductSerialCodeChange, ProductSerialIdentifier

Kind = ProductSerialIdentifier.Kind
MAX_LEN = 80
# 這一台「是哪一台」的碼。IMEI2 / EID(拍照入庫才會有)是附帶的,不算在 IMEI / SN 兩格裡。
MAIN_KINDS = (Kind.IMEI, Kind.SN, Kind.PRIMARY_SERIAL)


class IdentifierError(ValueError):
    """碼有問題;訊息是給使用者看的白話。"""


class IdentifierDenied(IdentifierError):
    """這個人不能改這一台(不是碼本身有問題)。"""


def luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def looks_like_imei(code) -> bool:
    """15 碼數字而且檢查碼正確。只用來猜「沒講是哪一種」的碼該放哪一格,不拿來擋人。"""
    nv = normalize_serial(code)
    return len(nv) == 15 and nv.isascii() and nv.isdigit() and luhn_ok(nv)


def split_codes(imei="", sn="", code=""):
    """入口給的碼 → (IMEI, SN)。

    code 是「沒講是哪一種」的單一個碼(舊格式、匯入、拍照入庫):像 IMEI 就當 IMEI,否則當 SN。
    有明講 imei / sn 時照講的放,不改判(檢查碼不對只在畫面提醒,這裡照收)。
    """
    imei, sn, code = (str(v or "").strip() for v in (imei, sn, code))
    if code and not imei and not sn:
        if looks_like_imei(code):
            imei = code
        else:
            sn = code
    if not imei and not sn:
        raise IdentifierError("IMEI 與 SN 至少要填一個")
    for label, value in (("IMEI", imei), ("SN", sn)):
        if not value:
            continue
        if len(value) > MAX_LEN:
            raise IdentifierError(f"{label} 太長(最多 {MAX_LEN} 個字)")
        if not normalize_serial(value):
            raise IdentifierError(f"{label}「{value}」不是有效的碼")
    if imei and sn and normalize_serial(imei) == normalize_serial(sn):
        raise IdentifierError(f"IMEI 與 SN 不能是同一個碼:{imei}")
    return imei, sn


def main_code(imei, sn):
    """主碼:有 IMEI 用 IMEI,沒有才用 SN。"""
    return imei or sn


def taken(tenant, codes, exclude_serial_id=None):
    """這些碼裡,哪些已經被這家公司的別台設備用掉(IMEI、SN、主碼一起比)。"""
    keys = {}
    for c in codes:
        c = str(c or "").strip()
        if c:
            keys.setdefault(normalize_serial(c), c)
    if not keys:
        return []
    ids = ProductSerialIdentifier.objects.filter(tenant=tenant, normalized_value__in=list(keys))
    # 主碼也比一次(比 serial_key,去掉符號後的值):識別碼表萬一漏登記
    # (回填時撞在一起沒登記到的舊設備),主碼照樣擋得住,不管它當初寫成 AB-12 還是 A.B_12。
    mains = ProductSerial.objects.filter(
        tenant=tenant, serial_key__in=list(keys),
    ).exclude(status=ProductSerial.Status.VOID)          # 作廢的不佔碼
    if exclude_serial_id is not None:
        ids = ids.exclude(serial_id=exclude_serial_id)
        mains = mains.exclude(pk=exclude_serial_id)
    hit = set(ids.values_list("normalized_value", flat=True))
    hit |= set(mains.values_list("serial_key", flat=True))
    return [keys[k] for k in keys if k in hit]


IN_STORE = (ProductSerial.Status.IN_STOCK, ProductSerial.Status.IN_TRANSIT, ProductSerial.Status.RMA)


def taken_details(tenant, codes) -> dict:
    """這些碼裡,已經被這家公司的設備用掉的那幾個,各是哪一台:{送進來的碼: 那一台設備}。

    給畫面在**輸入的當下**提醒用(進貨的序號格、批次貼上、個人收購),只讀。
    **跟存檔時擋的是同一套比法**(`taken()`):識別碼表(IMEI、SN)加主碼,去掉符號後相同就算;作廢的不佔碼。
    兩台舊設備的碼去掉符號後撞在一起時,回其中編號最小的那一台(要講的只是「這個碼已經有人用了」)。
    """
    keys = {}
    for c in codes:
        c = str(c or "").strip()
        if c:
            keys.setdefault(normalize_serial(c), c)
    keys.pop("", None)
    if not keys:
        return {}
    owner = {}
    mains = (ProductSerial.objects.filter(tenant=tenant, serial_key__in=list(keys))
             .exclude(status=ProductSerial.Status.VOID).order_by("-id"))
    for serial in mains:
        owner[serial.serial_key] = serial.pk
    # 識別碼表的登記排在後面寫(兩邊指到不同台時以它為準:它是每一個碼都有的那一份)
    for key, serial_id in (ProductSerialIdentifier.objects.filter(tenant=tenant, normalized_value__in=list(keys))
                           .order_by("-serial_id").values_list("normalized_value", "serial_id")):
        owner[key] = serial_id
    serials = {s.pk: s for s in ProductSerial.objects.filter(pk__in=set(owner.values()))
               .select_related("product", "warehouse")}
    return {keys[key]: serials[pk] for key, pk in owner.items() if pk in serials}


def _identifier_rows(serial, imei, sn):
    main = main_code(imei, sn)
    return [
        ProductSerialIdentifier(
            tenant_id=serial.tenant_id, serial=serial, kind=kind, value=value,
            normalized_value=normalize_serial(value), is_primary=(value == main),
        )
        for kind, value in ((Kind.IMEI, imei), (Kind.SN, sn)) if value
    ]


def create_serial(*, tenant, product, imei="", sn="", code="", **fields):
    """新增一台設備並登記它的碼。碼已經被別台用掉就丟 IdentifierError。"""
    imei, sn = split_codes(imei, sn, code)
    clash = taken(tenant, [imei, sn])
    if clash:
        raise IdentifierError(f"序號已存在於系統:{', '.join(clash)}")
    try:
        with transaction.atomic():       # 自己一段:撞到唯一限制時外層的交易還能繼續處理錯誤
            serial = ProductSerial.objects.create(
                tenant=tenant, product=product, serial_no=main_code(imei, sn), **fields)
            ProductSerialIdentifier.objects.bulk_create(_identifier_rows(serial, imei, sn))
    except IntegrityError:
        # 檢查之後、寫入之前,別人剛好登記了同一個碼
        raise IdentifierError(f"序號已存在於系統:{main_code(imei, sn)}")
    return serial


def codes_of(serial):
    """這一台的 IMEI 與 SN(顯示用)。讀 `identifiers`,一次要列很多台時呼叫端先 prefetch。"""
    imei = sn = ""
    # 順序要固定(主碼優先,其次最新登記的),顯示與修改才會指到同一列。
    # 正常一台最多一個 IMEI、一個 SN;同一種有兩個(只可能是舊資料)時顯示最新的那個。
    rows = sorted(serial.identifiers.all(), key=lambda i: (not i.is_primary, -i.pk))
    for idf in rows:
        kind = idf.kind
        if kind == Kind.PRIMARY_SERIAL:
            kind = Kind.IMEI if looks_like_imei(idf.value) else Kind.SN
        if kind == Kind.IMEI and not imei:
            imei = idf.value
        elif kind == Kind.SN and not sn:
            sn = idf.value
    if not imei and not sn:              # 沒登記到(不該發生):至少把主碼講出來
        if looks_like_imei(serial.serial_no):
            imei = serial.serial_no
        else:
            sn = serial.serial_no
    return {"imei": imei, "sn": sn}


def find_serial_ids(tenant, code):
    """刷到的碼是這家公司的哪一台(完全相同才算;通常 0 或 1 台)。作廢的設備不算(它的碼已經釋放)。

    比的是去掉符號後的值:登記的每一個碼(識別碼表)加上主碼(serial_key)。兩台舊設備的碼去掉符號後相同時,
    兩台都會回來 —— 呼叫的人看到不只一台就不能自動挑一台。
    """
    nv = normalize_serial(code)
    if not nv:
        return []
    live = ProductSerial.objects.filter(tenant=tenant).exclude(status=ProductSerial.Status.VOID)
    return sorted(set(
        live.filter(Q(identifiers__normalized_value=nv) | Q(serial_key=nv))
        .values_list("pk", flat=True)))


def _keys_of(serial_ids):
    """這幾台設備佔著哪些碼:{公司: {去掉符號後的碼}}(登記的每一個碼,加上主碼)。"""
    keys = {}
    for tenant_id, key in ProductSerialIdentifier.objects.filter(
            serial_id__in=serial_ids).values_list("tenant_id", "normalized_value"):
        keys.setdefault(tenant_id, set()).add(key)
    for tenant_id, key in ProductSerial.objects.filter(
            pk__in=serial_ids).values_list("tenant_id", "serial_key"):
        if key:
            keys.setdefault(tenant_id, set()).add(key)
    return keys


def twin_ids(serial_ids):
    """這幾台作廢之後,可能要接手它們的碼的設備:同一家公司、沒作廢、主碼去掉符號後跟其中一個碼相同的別台。

    作廢之前要把這些跟要作廢的設備**一起照編號順序鎖住**(交給 lock_stock_rows):兩張作廢單各自的設備
    剛好互為對方的接手者時,先鎖自己的、再鎖對方的會互相等到死結。
    """
    serial_ids = list(serial_ids)
    found = set()
    for tenant_id, keys in _keys_of(serial_ids).items():
        found |= set(
            ProductSerial.objects.filter(tenant_id=tenant_id, serial_key__in=list(keys))
            .exclude(status=ProductSerial.Status.VOID).exclude(pk__in=serial_ids)
            .values_list("pk", flat=True))
    return sorted(found)


def release_codes(serial_ids):
    """這幾台作廢了:把它們登記的碼拿掉,同樣的碼才能再給新的設備用。
    `serial_no` 不動(留著當紀錄;資料庫的唯一限制不算作廢的)。

    呼叫前要在交易裡,而且已經把這幾台連同 `twin_ids()` 一起鎖住。

    拿掉之後如果某個碼沒有人登記了,而同一家公司還有一台在用的設備主碼就是它(去掉符號後相同),登記要交給那一台
    (舊資料才會有 —— 以前作廢過的碼不能再用,店員只好加個破折號重新入庫;升級時兩筆被當成同一個碼,只登記到其中一筆)。
    不然那一台沒有任何保護:別台可以再用同一個碼。碼還有別台登記著的時候不用交(那一台就是它的主人)。
    """
    serial_ids = list(serial_ids)
    freed = _keys_of(serial_ids)
    ProductSerialIdentifier.objects.filter(serial_id__in=serial_ids).delete()
    heirs = []
    for tenant_id, keys in freed.items():
        # 還登記在別台身上的碼不是空缺
        owned = set(
            ProductSerialIdentifier.objects.filter(tenant_id=tenant_id, normalized_value__in=list(keys))
            .values_list("normalized_value", flat=True))
        candidates = (
            ProductSerial.objects.select_for_update(no_key=True)      # 呼叫的人已經鎖過;這裡拿到的是鎖住之後的現況
            .filter(tenant_id=tenant_id, serial_key__in=list(keys))
            .exclude(status=ProductSerial.Status.VOID).exclude(pk__in=serial_ids)
            .order_by("pk")
        )
        for serial in candidates:
            if serial.serial_key in keys and serial.serial_key not in owned:
                owned.add(serial.serial_key)         # 一個碼只登記給一台(最舊的那台)
                heirs.append(serial)
    ProductSerialIdentifier.objects.bulk_create([
        ProductSerialIdentifier(
            tenant_id=serial.tenant_id, serial=serial, value=serial.serial_no,
            normalized_value=serial.serial_key,
            # 它如果已經有別的碼被標成主識別碼(拍照入庫的舊資料),不要再多一個
            is_primary=not serial.identifiers.filter(is_primary=True).exists(),
            kind=Kind.IMEI if looks_like_imei(serial.serial_no) else Kind.SN,
        ) for serial in heirs
    ])


def _same(a, b):
    return normalize_serial(a) == normalize_serial(b)


def set_codes(serial, *, imei, sn, user=None, may_change=False, check=None):
    """補登或修改一台設備的碼;回傳 (設備, 有沒有改到)。

    may_change=False(店員):只能把空的那一格補上,已經登記的碼不能動。
    may_change=True(管理員):可以改、可以清掉其中一格,但至少要留一個。
    作廢的設備不能改。每一次改動都留一筆 `ProductSerialCodeChange`。

    check(設備):鎖住這一台、重讀之後才呼叫,不准就丟 IdentifierDenied。
    「這個人能不能動這一台」(在不在他的門市)要放在這裡判斷,不能在鎖之前先看。
    """
    new_imei, new_sn = (str(v or "").strip() for v in (imei, sn))
    with transaction.atomic():
        serial = ProductSerial.objects.select_for_update(no_key=True).get(pk=serial.pk)
        if check is not None:
            check(serial)
        if serial.status == ProductSerial.Status.VOID:
            raise IdentifierError("這一台已經作廢,不能改序號")
        old = codes_of(serial)
        if _same(old["imei"], new_imei) and _same(old["sn"], new_sn):
            return serial, False
        if not may_change:
            for label, key, new in (("IMEI", "imei", new_imei), ("SN", "sn", new_sn)):
                if old[key] and not _same(old[key], new):
                    raise IdentifierError(f"已經登記的 {label} 只有管理員能改")
        new_imei, new_sn = split_codes(new_imei, new_sn)
        clash = taken(serial.tenant, [new_imei, new_sn], exclude_serial_id=serial.pk)
        if clash:
            raise IdentifierError(f"序號已經被別台設備用掉:{', '.join(clash)}")
        try:
            with transaction.atomic():
                # 只換掉畫面上那兩個碼(codes_of 顯示的)。這一台如果還登記了別的碼(拍照入庫才可能有:
                # 第二個 SN、IMEI2、EID),那些不是這次改的,不能跟著刪 —— 刪了別台就能再用,紀錄上也看不出來。
                shown = [normalize_serial(v) for v in (old["imei"], old["sn"]) if v]
                serial.identifiers.filter(kind__in=MAIN_KINDS, normalized_value__in=shown).delete()
                ProductSerialIdentifier.objects.bulk_create(
                    _identifier_rows(serial, new_imei, new_sn))
                serial.serial_no = main_code(new_imei, new_sn)
                serial.save(update_fields=["serial_no", "updated_at"])
        except IntegrityError:
            raise IdentifierError(f"序號已經被別台設備用掉:{main_code(new_imei, new_sn)}")
        ProductSerialCodeChange.objects.create(
            tenant_id=serial.tenant_id, serial=serial,
            before_imei=old["imei"], before_sn=old["sn"],
            after_imei=new_imei, after_sn=new_sn,
            changed_by=user.get_username() if user is not None else "",
        )
    return serial, True
