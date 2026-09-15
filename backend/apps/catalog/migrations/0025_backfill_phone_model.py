"""把既有資料接上機型主檔。

**只回填有結構化證據的商品** —— 也就是 `series` 有填的(新框架那條路)。

為什麼不全部回填:沒填 series 的商品會退回「用 regex 解析品名」那條路,
在匯入的舊資料上那條路會把「三合一」「圓形支架」「單包邊條」這類配件
也解析成機型。實測整批跑下來會生出 2703 筆機型,其中絕大多數是垃圾。
主檔一旦被垃圾灌滿就沒人敢用,不如只收乾淨的。

沒回填到的商品維持 `phone_model=NULL`,`phone_model_name` / `phone_model_key`
會照舊退回原本算出來的字串,**行為完全不變**。之後要把剩下的收進來,
走人工確認的流程,不要在 migration 裡猜。

安全性:
- 只新增關聯,不改任何既有欄位的值(host_model_key 原樣保留)。
- 可重複執行:以 (tenant, match_key) 查既有的。
"""
import re

from django.db import migrations
from django.utils.text import slugify


def _model_key_for(product, series_name):
    """複製 compute_phone_model_name 的邏輯,但只用 migration 拿得到的欄位。

    不 import apps.catalog.phone_model:migration 要能在未來的程式碼版本下重跑,
    直接依賴會漂移的業務函式不安全。regex 那條退路也一併複製。
    """
    if product.series_id and series_name:
        parts = [series_name]
        if product.generation:
            parts.append(str(product.generation))
        if product.model_suffix:
            parts.append(product.model_suffix)
        out = parts[0]
        for p in parts[1:]:
            if not p:
                continue
            out += p if p[0] in "+/" else " " + p
        return out.strip()
    return _extract_from_name(product.name or "")


_CAPACITY_RE = re.compile(r"\s*(?:\d+\s*/\s*)*\d+\s*(?:G|GB|TB)\b", re.IGNORECASE)
_EMPTY_PARENS_RE = re.compile(r"[\(\[（［]\s*[\)\]）］]")
_COLOR_RE = re.compile(
    r"\s*(?:"
    r"(?:[一-鿿]{1,3})?[黑白金銀灰藍紅綠紫粉橙黃青棕褐]+色?"
    r"|Black|White|Gold|Silver|Grey|Gray|Blue|Red|Green|Purple"
    r"|Pink|Orange|Yellow|Bronze|Midnight|Starlight|Graphite|Sierra"
    r")\s*$",
    re.IGNORECASE,
)
_SECONDHAND_RE = re.compile(r"\s*\(?\s*中古\s*\)?\s*$")


def _extract_from_name(name):
    s = name or ""
    for _ in range(3):
        before = s
        s = _SECONDHAND_RE.sub("", s)
        s = _COLOR_RE.sub("", s)
        s = _CAPACITY_RE.sub("", s)
        s = _EMPTY_PARENS_RE.sub("", s)
        s = s.strip(" -·、,,")
        if s == before:
            break
    return s.strip()


def backfill(apps, schema_editor):
    Product = apps.get_model("catalog", "Product")
    PhoneModel = apps.get_model("catalog", "PhoneModel")
    ProductRelation = apps.get_model("catalog", "ProductRelation")
    PhoneSeries = apps.get_model("catalog", "PhoneSeries")

    series_names = dict(PhoneSeries.objects.values_list("id", "name"))

    # 只收「series 有填」的商品:那是新框架建出來的,機型名稱算得準。
    # 沒填 series 的會走 regex 解析品名,在舊匯入資料上會解析出一堆配件名。
    # phone_model__isnull=True:已經有值的不重推。人工指定過的機型不能被
    # 「重跑 migration」覆寫掉(相容關係那邊本來就只處理 NULL,不排除的話
    # 兩邊會分裂:商品被改掛推導出的 A,關係還指著人工指定的 B)。
    hosts = Product.objects.filter(
        accessory_type="none",
        warehouse_type="product",
        series__isnull=False,
        phone_model__isnull=True,
    ).only(
        "id", "tenant_id", "name", "series_id", "generation",
        "model_suffix", "brand_id", "phone_model_id",
    )

    cache = {}          # (tenant_id, match_key) -> PhoneModel
    used_codes = set()  # (tenant_id, code)
    to_link = []

    for p in hosts.iterator(chunk_size=500):
        series_name = series_names.get(p.series_id)
        if not series_name:
            continue
        model_name = _model_key_for(p, series_name)
        if not model_name:
            continue
        match_key = model_name.strip().lower()
        if not match_key:
            continue
        ck = (p.tenant_id, match_key)
        pm = cache.get(ck)
        if pm is None:
            pm = PhoneModel.objects.filter(
                tenant_id=p.tenant_id, match_key=match_key
            ).first()
            if pm is None:
                code = slugify(model_name)[:40] or "model"
                base, n = code, 1
                while (p.tenant_id, code) in used_codes or PhoneModel.objects.filter(
                    tenant_id=p.tenant_id, code=code
                ).exists():
                    n += 1
                    suffix = f"-{n}"
                    code = base[: 40 - len(suffix)] + suffix
                pm = PhoneModel.objects.create(
                    tenant_id=p.tenant_id,
                    code=code,
                    name=model_name,
                    match_key=match_key,
                    brand_id=p.brand_id,
                    series_id=p.series_id,
                    generation=p.generation,
                    model_suffix=p.model_suffix or "",
                    is_active=True,
                )
                used_codes.add((p.tenant_id, code))
            cache[ck] = pm
        if p.phone_model_id != pm.id:
            p.phone_model_id = pm.id
            to_link.append(p)
        if len(to_link) >= 500:
            Product.objects.bulk_update(to_link, ["phone_model"])
            to_link = []
    if to_link:
        Product.objects.bulk_update(to_link, ["phone_model"])

    # 相容關係:用既有的 host_model_key 接上主檔
    rels = ProductRelation.objects.filter(
        host_model__isnull=True
    ).exclude(host_model_key="").only("id", "tenant_id", "host_model_key")
    batch = []
    for r in rels.iterator(chunk_size=500):
        pm = cache.get((r.tenant_id, r.host_model_key))
        if pm is None:
            pm = PhoneModel.objects.filter(
                tenant_id=r.tenant_id, match_key=r.host_model_key
            ).first()
            if pm is None:
                # 這個 key 沒有任何在庫主機 SKU(機型 SKU 已刪光),
                # 仍然要保住相容關係 → 補一筆只有名字的機型
                code = slugify(r.host_model_key)[:40] or "model"
                base, n = code, 1
                while PhoneModel.objects.filter(
                    tenant_id=r.tenant_id, code=code
                ).exists():
                    n += 1
                    suffix = f"-{n}"
                    code = base[: 40 - len(suffix)] + suffix
                pm = PhoneModel.objects.create(
                    tenant_id=r.tenant_id,
                    code=code,
                    name=r.host_model_key,
                    match_key=r.host_model_key,
                    is_active=True,
                )
            cache[(r.tenant_id, r.host_model_key)] = pm
        r.host_model_id = pm.id
        batch.append(r)
        if len(batch) >= 500:
            ProductRelation.objects.bulk_update(batch, ["host_model"])
            batch = []
    if batch:
        ProductRelation.objects.bulk_update(batch, ["host_model"])


def unbackfill(apps, schema_editor):
    """什麼都不做 —— 這是刻意的。

    「反向」聽起來應該把 phone_model / host_model 清回 NULL,但那兩個欄位是
    0024 加的,0024 的反向會把整個欄位移除,本來就不需要先清。而清掉會連
    「人工指定的機型」「人工建立的機型關聯」一起洗掉,再回填只推得出一部分,
    人工命名與人工指定的對應永遠回不來(實測:清完之後所有機型都變成
    「沒人引用」,連使用者自己建的都算進去)。

    另外 0024 的反向要靠 `host_model` 幫「代表 SKU 被刪掉」的關聯找替代品,
    在這裡先清掉會讓退版直接失敗。

    要真的清空,退到 0024 之前讓整張表與兩個欄位一起消失。
    """
    return


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0024_phone_model_master"),
    ]

    operations = [
        migrations.RunPython(backfill, unbackfill),
    ]
