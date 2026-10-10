"""查詢單 → 結果。

查詢單是唯一的入口(報表畫面與自然語言都一樣):

    {
      "measures": ["net_sales", "gross_profit"],
      "dimensions": ["warehouse", "date"],        # 最多 3 個
      "period": {"from": "2026-09-01", "to": "2026-09-30", "grain": "month"},
                # 或 {"preset": "last_month"}:相對今天(台灣時間)算,存起來的報表每次打開都是最新的
      "filters": {"warehouse": [1, 2], "condition": [false]},
      "compare": "previous" | "last_year" | null,  # 有日期角度時不能用
      "sort": "-net_sales",                        # 指標或角度;前面加 - 是由大到小
      "limit": 500
    }

這裡只做四件事:照 catalog.py 驗證、每張事實表各查一次(一律限定公司)、照角度合併、算出衍生指標與合計。
沒有任何地方接受資料庫指令或欄位名稱:指標與角度都只能是定義裡有的代號。
"""
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from django.apps import apps as django_apps
from django.db.models import DateField, Max, Q
from django.db.models.functions import Trunc

from .catalog import (
    DIMENSIONS,
    FACTS,
    GRAINS,
    GROUPS,
    MEASURES,
    Base,
    base_keys,
    group_of,
    may_see,
    supported_dims,
)

MAX_DIMENSIONS = 3
MAX_MEASURES = 12
MAX_ROWS = 2000
DEFAULT_ROWS = 500
MAX_DAYS = 366 * 20
MAX_FILTER_VALUES = 200
ZERO = Decimal("0")
CENT = Decimal("0.01")


class QueryError(Exception):
    """查詢單有問題;訊息是給使用者看的白話。"""


@dataclass
class Query:
    measures: list
    dimensions: list
    start: date
    end: date
    grain: str = "month"
    filters: dict = field(default_factory=dict)
    compare: str = ""
    sort: str = ""
    limit: int = DEFAULT_ROWS
    preset: str = ""


# ── 解析與驗證 ──────────────────────────────────────────────────────────────
def _label(key):
    item = MEASURES.get(key) or DIMENSIONS.get(key)
    return item.label if item else str(key)


def _as_date(value, what):
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise QueryError(f"{what}的格式要是 YYYY-MM-DD")


PRESETS = {
    "today": "今天", "yesterday": "昨天", "last_7_days": "近 7 天", "last_30_days": "近 30 天",
    "this_month": "本月", "last_month": "上月", "this_quarter": "本季",
    "this_year": "今年", "last_year": "去年",
    # 往後看的期間:給「日期是未來」的指標用(門號合約哪個月到期)。銷貨那些指標選了只會是空的
    "next_3_months": "未來 3 個月", "next_12_months": "未來 12 個月",
}


def preset_range(name, today=None):
    """相對期間 → (開始, 結束)。today 預設是台灣時間的今天。"""
    from django.utils import timezone

    t = today or timezone.localdate()
    first = t.replace(day=1)
    if name == "today":
        return t, t
    if name == "yesterday":
        return t - timedelta(days=1), t - timedelta(days=1)
    if name == "last_7_days":
        return t - timedelta(days=6), t
    if name == "last_30_days":
        return t - timedelta(days=29), t
    if name == "this_month":
        return first, t
    if name == "last_month":
        end = first - timedelta(days=1)
        return end.replace(day=1), end
    if name == "this_quarter":
        return t.replace(month=(t.month - 1) // 3 * 3 + 1, day=1), t
    if name == "this_year":
        return t.replace(month=1, day=1), t
    if name == "last_year":
        return date(t.year - 1, 1, 1), date(t.year - 1, 12, 31)
    if name in ("next_3_months", "next_12_months"):
        from apps.core.dates import add_months

        return t, add_months(t, 3 if name == "next_3_months" else 12)
    raise QueryError("沒有這個期間")


def parse(spec, user=None) -> Query:
    if not isinstance(spec, dict):
        raise QueryError("查詢單格式不對")
    measures = spec.get("measures") or []
    dimensions = spec.get("dimensions") or []
    if not isinstance(measures, list) or not isinstance(dimensions, list):
        raise QueryError("指標與角度要是清單")
    if not measures:
        raise QueryError("至少要選一個指標")
    if len(measures) > MAX_MEASURES:
        raise QueryError(f"一次最多 {MAX_MEASURES} 個指標")
    if len(dimensions) > MAX_DIMENSIONS:
        raise QueryError(f"一次最多 {MAX_DIMENSIONS} 個角度")
    if len(set(map(str, measures))) != len(measures) or len(set(map(str, dimensions))) != len(dimensions):
        raise QueryError("指標或角度重複了")
    role = getattr(getattr(user, "profile", None), "role", None)
    for m in measures:
        item = MEASURES.get(m) if isinstance(m, str) else None
        if item is None or getattr(item, "hidden", False):
            raise QueryError(f"沒有「{m}」這個指標")
        if not may_see(m, role):
            raise QueryError(f"沒有權限看「{item.label}」")
    for d in dimensions:
        if not isinstance(d, str) or d not in DIMENSIONS:
            raise QueryError(f"沒有「{d}」這個角度")

    period = spec.get("period") or {}
    if not isinstance(period, dict):
        raise QueryError("期間格式不對")
    preset = period.get("preset") or ""
    if preset:
        start, end = preset_range(preset)
    else:
        start, end = _as_date(period.get("from"), "開始日期"), _as_date(period.get("to"), "結束日期")
    if end < start:
        raise QueryError("結束日期不能早於開始日期")
    if (end - start).days > MAX_DAYS:
        raise QueryError("期間太長(最多 20 年)")
    grain = period.get("grain") or "month"
    if not isinstance(grain, str) or grain not in GRAINS:
        raise QueryError("日期單位只能是 日 / 週 / 月 / 季 / 年")

    # 沒給 = 沒有條件;給了但不是物件(空清單、0、空字串也算)就是格式不對,不當成沒有條件
    filters = spec.get("filters")
    if filters is None:
        filters = {}
    if not isinstance(filters, dict):
        raise QueryError("條件格式不對")
    clean = {}
    for key, values in filters.items():
        if key not in DIMENSIONS or key == "date":
            raise QueryError(f"不能用「{key}」當條件")
        if not isinstance(values, list) or not values:
            raise QueryError(f"「{_label(key)}」的條件要是清單,而且不能是空的")
        if len(values) > MAX_FILTER_VALUES:
            raise QueryError(f"「{_label(key)}」的條件太多(最多 {MAX_FILTER_VALUES} 個)")
        clean[key] = values

    # 每個指標用到的每一張事實表,都要支援選到的角度與條件
    for m in measures:
        ok = supported_dims(m)
        for d in [*dimensions, *clean]:
            if d not in ok:
                raise QueryError(f"「{_label(m)}」不能用「{_label(d)}」來分或篩選")

    compare = spec.get("compare") or ""
    if compare not in ("", "previous", "last_year"):
        raise QueryError("比較只能是 上一期 / 去年同期")
    if compare and "date" in dimensions:
        raise QueryError("有日期角度時不能再選比較;把期間拉長就能前後對照")

    sort = spec.get("sort") or ""
    if not isinstance(sort, str) or (sort and sort.lstrip("-") not in [*measures, *dimensions]):
        raise QueryError("排序只能用這次選的指標或角度")
    limit = spec.get("limit")
    if limit is None:
        limit = DEFAULT_ROWS
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_ROWS:
        raise QueryError(f"筆數上限要在 1 到 {MAX_ROWS} 之間")
    return Query(list(measures), list(dimensions), start, end, grain, clean, compare, sort, limit,
                 preset)


# ── 條件值:只認這家公司自己的資料 ───────────────────────────────────────────
def _filter_values(tenant, q: Query):
    """把條件的值驗過、轉成查詢用的型別;回傳 ({角度: 值清單}, 給畫面看的說明)。"""
    values, shown = {}, []
    for key, raw in q.filters.items():
        dim = DIMENSIONS[key]
        if dim.kind == "ref":
            ids, want_none = [], False
            for v in raw:
                if v is None:
                    want_none = True
                elif isinstance(v, int) and not isinstance(v, bool):
                    ids.append(v)
                else:
                    raise QueryError(f"「{dim.label}」的條件要是編號")
            model = django_apps.get_model(dim.model)
            names = dict(model.objects.filter(tenant=tenant, pk__in=ids).values_list("pk", "name"))
            if set(ids) - set(names):
                raise QueryError(f"「{dim.label}」的條件裡有找不到的資料")
            values[key] = [*ids, *([None] if want_none else [])]
            labels = [names[i] for i in ids] + (["未指定 / 未對照"] if want_none else [])
        elif dim.kind == "flag":
            if any(not isinstance(v, bool) for v in raw):
                raise QueryError(f"「{dim.label}」的條件只能是 是 / 否")
            values[key] = list(raw)
            labels = [dim.flag_labels[0] if v else dim.flag_labels[1] for v in raw]
        else:
            if any(not isinstance(v, str) for v in raw):
                raise QueryError(f"「{dim.label}」的條件要是代碼")
            # 只接受列得出來的代碼;清單是空的(公司沒有任何付款方式)就是全部不接受,不是不檢查
            names = dim.labels(tenant)
            if set(raw) - set(names):
                raise QueryError(f"「{dim.label}」的條件裡有不認得的代碼")
            values[key] = list(raw)
            labels = [names.get(v, v) for v in raw]
        shown.append({"dimension": key, "label": dim.label, "values": [
            {"value": v, "label": label} for v, label in zip(values[key], labels)]})
    return values, shown


def filter_labels(tenant, spec, user=None):
    """查詢單裡每個條件的值叫什麼名字(畫面顯示用)。"""
    return _filter_values(tenant, parse(spec, user))[1]


# ── 每張事實表查一次 ────────────────────────────────────────────────────────
def _apply_filters(fact, qs, filters):
    """套條件;這張事實表的固定值(資料來源)不在條件裡時回傳 None(整張不用查)。"""
    for key, wanted in filters.items():
        path = fact.paths[key]
        if path.const:
            if path.const[0] not in wanted:
                return None
            continue
        cond = Q(**{f"{path.value}__in": [v for v in wanted if v is not None]})
        if None in wanted:
            cond |= Q(**{f"{path.value}__isnull": True})
        qs = qs.filter(cond)
    return qs


def _date_label(value, grain):
    if value is None:
        return "(沒有日期)"
    if grain == "year":
        return f"{value.year}"
    if grain == "quarter":
        return f"{value.year}-Q{(value.month - 1) // 3 + 1}"
    if grain == "month":
        return f"{value.year}-{value.month:02d}"
    if grain == "week":
        return f"{value.isoformat()} 週"
    return value.isoformat()


def _fact_rows(tenant, fact, bases, q: Query, start, end, filters, choice_labels):
    """回傳 ({角度值的組合: {"dims": …, "values": {基本指標: 數字}}}, {基本指標: 合計})。"""
    zero = {b.key: ZERO for b in bases}
    qs = fact.queryset(tenant).filter(**{f"{fact.date}__gte": start, f"{fact.date}__lte": end})
    qs = _apply_filters(fact, qs, filters)
    if qs is None:
        return {}, zero
    aggs = {b.key: b.expr() for b in bases}

    def number(b, raw):
        return ZERO if raw is None else Decimal(raw) * b.scale

    with_date = "date" in q.dimensions
    if with_date:
        qs = qs.annotate(_bucket=Trunc(fact.date, q.grain, output_field=DateField()))
    total_qs = qs
    buckets = {}        # as_of + 日期角度:{那一段的開頭: 那一段最後一次記錄的日期}
    if fact.as_of:
        # 不能跨日加總:每一段期間只看最後一次(沒有日期角度就是整段期間的最後一次)。
        # 「最後一次是哪一天」看的是有沒有記錄過那一天,跟條件無關 —— 條件篩完那天沒有明細就是 0,
        # 不可以退回去拿更早那一天的數量。
        days = fact.days(tenant).filter(**{f"{fact.date}__gte": start, f"{fact.date}__lte": end})
        if with_date:
            buckets = dict(
                days.annotate(_bucket=Trunc(fact.date, q.grain, output_field=DateField()))
                .values("_bucket").annotate(_last=Max(fact.date)).order_by()
                .values_list("_bucket", "_last"))
            lasts = list(buckets.values())
            qs = qs.filter(**{f"{fact.date}__in": lasts})
            total_qs = total_qs.filter(**{fact.date: max(lasts)}) if lasts else total_qs.none()
        else:
            last = days.aggregate(_last=Max(fact.date))["_last"]
            qs = total_qs = qs.filter(**{fact.date: last}) if last else qs.none()
    totals = {b.key: number(b, total_qs.aggregate(**aggs)[b.key]) for b in bases}

    fields, readers = [], []
    for key in q.dimensions:
        dim = DIMENSIONS[key]
        if key == "date":
            fields.append("_bucket")
            readers.append(lambda row, k=key: (
                row["_bucket"].isoformat() if row["_bucket"] else None,
                _date_label(row["_bucket"], q.grain)))
            continue
        path = fact.paths[key]
        if path.const:
            readers.append(lambda row, c=path.const: c)
        elif dim.kind == "ref":
            fields += [path.value, path.label]
            readers.append(lambda row, p=path: (
                row[p.value], row[p.label] if row[p.value] is not None else p.none_label))
        elif dim.kind == "flag":
            fields.append(path.value)
            readers.append(lambda row, p=path, d=dim: (
                row[p.value],
                p.none_label if row[p.value] is None
                else (d.flag_labels[0] if row[p.value] else d.flag_labels[1])))
        else:
            fields.append(path.value)
            names = choice_labels.get(key, {})
            readers.append(lambda row, p=path, n=names: (
                row[p.value], p.none_label if row[p.value] in (None, "")
                else n.get(row[p.value], row[p.value])))

    if not q.dimensions:
        return {(): {"dims": [], "values": totals}}, totals
    out = {}
    grouped = qs.values(*fields).annotate(**aggs).order_by() if fields else [qs.aggregate(**aggs)]
    for row in grouped:
        dims = [reader(row) for reader in readers]
        key = tuple(v for v, _ in dims)
        entry = out.setdefault(key, {"dims": dims, "values": dict(zero)})
        for b in bases:
            entry["values"][b.key] += number(b, row[b.key])
    if buckets and q.dimensions == ["date"]:
        # 只按日期看時,有記錄但數量是 0 的那一段也要列出來(寫 0),不要整段不見
        for bucket in buckets:
            key = (bucket.isoformat(),)
            out.setdefault(key, {"dims": [(key[0], _date_label(bucket, q.grain))],
                                 "values": dict(zero)})
    return out, totals


def _evaluate(tenant, q: Query, start, end, filters, choice_labels):
    needed = []
    for m in q.measures:
        for key in base_keys(m):
            if key not in needed:
                needed.append(key)
    by_fact = {}
    for key in needed:
        by_fact.setdefault(MEASURES[key].fact, []).append(MEASURES[key])
    zero = {key: ZERO for key in needed}
    rows, totals = {}, dict(zero)
    for fact_key, bases in by_fact.items():
        part, part_totals = _fact_rows(
            tenant, FACTS[fact_key], bases, q, start, end, filters, choice_labels)
        totals.update(part_totals)
        for key, entry in part.items():
            row = rows.setdefault(key, {"dims": entry["dims"], "values": dict(zero)})
            # 同一個「沒有值」在不同事實表叫法不同(未指定 / 未對照):兩個都寫出來
            for i, (value, label) in enumerate(entry["dims"]):
                if value is None and row["dims"][i][1] != label and label not in row["dims"][i][1]:
                    row["dims"][i] = (None, f"{row['dims'][i][1]} / {label}")
            row["values"].update(entry["values"])
    return rows, totals


# ── 輸出 ────────────────────────────────────────────────────────────────────
def _final(q: Query, base_values):
    out = {}
    for key in q.measures:
        m = MEASURES[key]
        value = base_values[key] if isinstance(m, Base) else m.fn(base_values)
        if value is None:
            out[key] = None
        elif m.fmt == "int":
            out[key] = int(value)
        elif m.fmt == "pct":
            out[key] = str(Decimal(value).quantize(Decimal("0.0001")))
        else:
            out[key] = str(Decimal(value).quantize(CENT))
    return out


def _compare_period(q: Query):
    if q.compare == "previous":
        days = (q.end - q.start).days + 1
        return q.start - timedelta(days=days), q.start - timedelta(days=1)

    def year_back(d):
        try:
            return d.replace(year=d.year - 1)
        except ValueError:              # 2/29
            return d.replace(year=d.year - 1, day=28)
    return year_back(q.start), year_back(q.end)


def run(tenant, spec, user=None, *, only_warehouse=None):
    """only_warehouse = 鎖在門市的帳號那一家的編號:不管查詢單怎麼寫,只算那一家(owner 2026-10-10:業務員看自己門市)。"""
    q = parse(spec, user)
    if only_warehouse is not None:
        for m in q.measures:
            if "warehouse" not in supported_dims(m):
                raise QueryError(f"「{_label(m)}」分不出門市,這個帳號不能看")
        q.filters["warehouse"] = [only_warehouse]
    filters, shown = _filter_values(tenant, q)
    choice_labels = {
        key: DIMENSIONS[key].labels(tenant)
        for key in q.dimensions
        if DIMENSIONS[key].kind == "choice" and DIMENSIONS[key].labels
    }
    rows, totals = _evaluate(tenant, q, q.start, q.end, filters, choice_labels)
    prev_rows, prev_totals, prev_period = {}, None, None
    if q.compare:
        prev_period = _compare_period(q)
        prev_rows, prev_totals = _evaluate(tenant, q, *prev_period, filters, choice_labels)

    result = []
    for key in {**prev_rows, **rows}:       # 上一期有、這一期沒有的也列出來
        current = rows.get(key)
        entry = current or prev_rows[key]
        zero = {k: ZERO for k in entry["values"]}
        item = {
            "dims": [{"value": v, "label": label} for v, label in entry["dims"]],
            "values": _final(q, current["values"] if current else zero),
        }
        if q.compare:
            item["previous"] = _final(q, prev_rows[key]["values"] if key in prev_rows else zero)
        result.append(item)

    def dim_key(item, index):
        d = item["dims"][index]
        text = str(d["value"]) if q.dimensions[index] == "date" else str(d["label"])
        return (d["value"] is None, text)

    def measure_key(item, name):
        v = item["values"][name]
        return (v is None, Decimal(str(v)) if v is not None else ZERO)

    # 先照角度的順序排好當底(穩定排序:之後照指標排,同分的仍然照角度的順序)
    result.sort(key=lambda item: tuple(dim_key(item, i) for i in range(len(q.dimensions))))
    name = q.sort.lstrip("-") or ("" if "date" in q.dimensions else q.measures[0])
    if name:
        descending = q.sort.startswith("-") if q.sort else True
        if name in q.measures:
            key = lambda item: measure_key(item, name)                      # noqa: E731
        else:
            key = lambda item: dim_key(item, q.dimensions.index(name))      # noqa: E731
        result.sort(key=key, reverse=descending)
        if descending:      # 沒有值的一律排最後
            result.sort(key=lambda item: key(item)[0])

    out = {
        "columns": {
            "dimensions": [{"key": d, "label": DIMENSIONS[d].label} for d in q.dimensions],
            "measures": [
                {"key": m, "label": MEASURES[m].label, "format": MEASURES[m].fmt}
                for m in q.measures
            ],
        },
        "rows": result[: q.limit],
        "row_count": len(result),
        "truncated": len(result) > q.limit,
        "totals": _final(q, totals),
        "applied": {
            "period": {"from": q.start.isoformat(), "to": q.end.isoformat()},
            "grain": q.grain if "date" in q.dimensions else None,
            "filters": shown,
            "compare": q.compare or None,
        },
    }
    if q.compare:
        out["totals_previous"] = _final(q, prev_totals)
        out["applied"]["compare_period"] = {
            "from": prev_period[0].isoformat(), "to": prev_period[1].isoformat()}
    return out


def normalize(tenant, spec, user=None):
    """驗過的查詢單,整理成固定的樣子(存報表用:只留認得的欄位,條件的值也對過這家公司)。"""
    q = parse(spec, user)
    _filter_values(tenant, q)
    period = {"preset": q.preset} if q.preset else {"from": q.start.isoformat(), "to": q.end.isoformat()}
    return {
        "measures": q.measures,
        "dimensions": q.dimensions,
        "period": {**period, "grain": q.grain},
        "filters": q.filters,
        "compare": q.compare or None,
        "sort": q.sort,
        "limit": q.limit,
    }


OPTION_ROWS = 200


def options(tenant, dimension, search=""):
    """某個角度有哪些值可以選(條件用);一律只給這家公司自己的。search = 名稱裡要有的字。"""
    dim = DIMENSIONS.get(dimension)
    if dim is None or dim.kind == "date":
        raise QueryError("沒有這個角度")
    if dim.kind == "ref":
        model = django_apps.get_model(dim.model)
        rows = model.objects.filter(tenant=tenant)
        if search:
            rows = rows.filter(name__icontains=str(search)[:50])
        rows = rows.order_by("name", "pk").values_list("pk", "name")[:OPTION_ROWS]
        return [{"value": pk, "label": name} for pk, name in rows]
    if dim.kind == "flag":
        return [{"value": True, "label": dim.flag_labels[0]},
                {"value": False, "label": dim.flag_labels[1]}]
    return [{"value": k, "label": v} for k, v in dim.labels(tenant).items()]


def describe(user=None):
    """給畫面(與之後的自然語言)用的清單:有哪些指標、每個指標能用哪些角度。
    這個人看不到的指標(只給管理員的)不列出來。"""
    role = getattr(getattr(user, "profile", None), "role", None)
    return {
        "measures": [
            {"key": m.key, "label": m.label, "format": m.fmt, "group": group_of(m),
             "dimensions": sorted(supported_dims(m.key))}
            for m in MEASURES.values() if not getattr(m, "hidden", False) and may_see(m.key, role)
        ],
        "dimensions": [
            {"key": d.key, "label": d.label, "kind": d.kind} for d in DIMENSIONS.values()
        ],
        "groups": GROUPS,
        "grains": [{"key": k, "label": v} for k, v in GRAINS.items()],
        "presets": [{"key": k, "label": v} for k, v in PRESETS.items()],
        "limits": {"dimensions": MAX_DIMENSIONS, "measures": MAX_MEASURES, "rows": MAX_ROWS},
    }
