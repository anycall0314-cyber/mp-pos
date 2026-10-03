"""把核對過的封存匯入 MP(或只試算)。

- **預設只試算**:全部核對一遍、算出會新增 / 換版 / 不變多少,不寫任何東西。
- 寫入必須明確指定公司;封存裡有「來源差異」時還要明確選 `reconciled_only`
  (只匯已核對的部分,差異那幾筆另存待核),不會默默把整包當成沒問題。
- 每位會員一個資料庫交易:那位會員的快照、單據、明細、版本要嘛全部寫進去,要嘛全部不寫。
  中斷後重跑會從頭比對,已經寫進去而且內容相同的直接略過(不會重複)。
- 同一張單(同公司、來源、舊會員、店別、單別、單號、日期)再出現時:內容相同 → 不變;
  內容不同而且是比較新的擷取 → 整張換成新內容,舊內容留在版本紀錄;比較舊的擷取 →
  只留成歷史版本,不換掉目前的。
- 一批可以整批撤回(`rollback_batch`):只動這一批帶進來的東西,不碰 MP 原生交易,
  也不動人已經確認過的對照。
- 匯入不會觸發銷貨過帳、庫存、收款、發票、點數或通知。
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field

from django.db import connection, transaction
from django.utils import timezone

from .archive import (
    ITEM_COLUMNS,
    SOURCE_SYSTEM,
    Archive,
    ArchiveError,
    Totals,
    money_minor,
    parse_time,
    version_prints,
)
from .models import (
    HistoryImportBatch,
    LegacyDocument,
    LegacyDocumentVersion,
    LegacyItem,
    LegacyMember,
    LegacyMemberListSnapshot,
    LegacyProductMap,
    LegacySalespersonMap,
    LegacySourceException,
    LegacySourceSnapshot,
    LegacyStoreMap,
    MapStatus,
)


class ImportBlocked(Exception):
    """不能寫入(原因可以直接給人看)。資料沒有任何變動。"""


def phone_digits(text: str) -> str:
    return re.sub(r"\D", "", text or "")


@dataclass
class Effect:
    members_new: int = 0
    members_updated: int = 0
    members_unchanged: int = 0
    documents_new: int = 0
    documents_replaced: int = 0
    documents_unchanged: int = 0
    documents_older_capture: int = 0
    items_written: int = 0
    versions_added: int = 0
    exceptions_new: int = 0

    def as_dict(self):
        return dict(self.__dict__)


@dataclass
class BatchReport:
    archive_batch_id: int
    period: tuple
    totals: Totals = field(default_factory=Totals)
    effect: Effect = field(default_factory=Effect)
    mapping: dict = field(default_factory=dict)
    overlap_legacy_purchases: int = 0
    excluded_exceptions: list = field(default_factory=list)
    batch_id: int | None = None

    def as_dict(self):
        return {
            "archive_batch_id": self.archive_batch_id,
            "period": [str(self.period[0]), str(self.period[1])],
            "totals": self.totals.as_dict(),
            "effect": self.effect.as_dict(),
            "mapping": self.mapping,
            "overlap_legacy_purchases": self.overlap_legacy_purchases,
            "excluded_exceptions": self.excluded_exceptions,
            "batch_id": self.batch_id,
        }


def _item_values(row) -> dict:
    return {name: row[name] for name in ITEM_COLUMNS}


class _State:
    """這家公司目前已經有的東西(只讀一次,之後在記憶體比對)。"""

    def __init__(self, tenant, source_system):
        from apps.parties.models import Member
        from apps.sales.models import LegacyPurchase

        self.members = {
            m.source_member_id: m for m in LegacyMember.objects.filter(
                tenant=tenant, source_system=source_system
            )
        }
        self.documents = {
            (d.legacy_member_id, d.store_name_raw, d.document_type_raw,
             d.document_number_raw, d.document_date): d
            for d in LegacyDocument.objects.filter(tenant=tenant, source_system=source_system)
            .only(
                "id", "legacy_member_id", "store_name_raw", "document_type_raw",
                "document_number_raw", "document_date", "content_sha256", "last_captured_at",
            )
        }
        self.mp_phones: dict[str, list] = defaultdict(list)
        for pk, phone in Member.objects.filter(tenant=tenant).values_list("id", "phone"):
            digits = phone_digits(phone)
            if len(digits) >= 8:
                self.mp_phones[digits].append(pk)
        # 試算時,前面幾批「會新建」的舊會員:後面的批次要把他們當成已存在
        self.predicted_members: set[str] = set()
        # 寫入時:封存批次編號 → MP 這邊的匯入批次
        self.batches: dict[int, HistoryImportBatch] = {}
        self.started_at = None
        self.legacy_purchase_keys = set(
            LegacyPurchase.objects.filter(tenant=tenant).exclude(source_no="")
            .values_list("source_no", "doc_date")
        )


def run(tenant, root, *, period=None, write=False, reconciled_only=False,
        user=None, log=lambda msg: None) -> dict:
    """試算(write=False)或寫入。一律整份封存(全部批次)一起核對、一起寫。回傳完整報告。"""
    with Archive(root, period=period) as archive:
        chosen = list(archive.batches)
        blocked = []
        if write:
            from apps.backup.jobs import in_maintenance

            if in_maintenance(tenant):
                blocked.append("這家公司正在還原或維護中,不能匯入")
        if blocked:
            raise ImportBlocked(";".join(blocked))

        with _import_lock(tenant, write):
            # 第一輪:全部批次都核對完(並試算),合計也對上封存的核對值,才准寫。
            # 不能邊核對邊寫:第二批有問題時,第一批已經寫進去了。
            state = _State(tenant, chosen[0].source_system)
            reports = []
            for info in chosen:
                log(f"核對批次 {info.archive_batch_id}({info.period_start}~{info.period_end})")
                reports.append(
                    _run_batch(tenant, archive, info, state, write=False, user=user, log=log)
                )
            report = _summarize(archive, reports, write, reconciled_only, tenant)
            # 待核要不要明確同意,看「實際核對出來」的待核數,不信封存自己寫的數字
            pending = report["totals"]["exception_members"]
            if write and pending and not reconciled_only:
                raise ImportBlocked(
                    f"封存有 {pending} 位會員的來源金額對不上(待核)。"
                    "要寫入請明確選「只匯已核對的部分」(reconciled_only),待核的會另外保存、不併入總額。"
                )
            if write:
                # 先記時間、再載入現況、再確認這段期間沒有還原:載入到一半被還原的話會被擋下
                started_at = timezone.now()
                state = _State(tenant, chosen[0].source_system)
                state.started_at = started_at
                with transaction.atomic():
                    _guard_against_restore(tenant, started_at)
                reports = []
                for info in chosen:
                    log(f"寫入批次 {info.archive_batch_id}")
                    reports.append(
                        _run_batch(tenant, archive, info, state, write=True, user=user, log=log)
                    )
                report = _summarize(archive, reports, write, reconciled_only, tenant)
        for b in report["batches"]:
            b["mapping"].pop("_member_keys", None)
        return report


def _summarize(archive, reports, write, reconciled_only, tenant):
    report = {
        "tenant": tenant.code,
        "write": write,
        "reconciled_only": reconciled_only,
        "archive_root": str(archive.root),
        "archive_sha256": archive.database_sha256,
        "covered_period": list(archive.covered_period),
        "batches": [r.as_dict() for r in reports],
    }
    total = Totals()
    for r in reports:
        for key, value in r.totals.as_dict().items():
            if isinstance(value, int):
                setattr(total, key, getattr(total, key) + value)
    report["totals"] = total.as_dict()
    # 合計要等於 manifest 的核對值(一律整份封存)
    if True:
        expected = archive.expected_totals()
        got = total.as_dict()
        # 會員:兩批共有的人在合計裡會算兩次,這裡比的是「精確編號聯集」
        got_members = len({k for r in reports for k in r.mapping.get("_member_keys", [])})
        mismatches = []
        for key, want in expected.items():
            have = got_members if key == "members" else got.get(key)
            if want is None:
                mismatches.append(f"{key}:manifest 沒有這個核對值")
            elif have != want:
                mismatches.append(f"{key}:封存 {want},實際 {have}")
        if archive.unresolved_exceptions != got["exception_members"]:
            mismatches.append(
                f"待核會員數:封存標示 {archive.unresolved_exceptions},實際 {got['exception_members']}"
            )
        captured = archive.expected_captured()
        have_captured = {
            "documents": got["documents"] + got["exception_documents"],
            "items": got["items"] + got["exception_items"],
            "raw_amount_minor": got["raw_amount_minor"] + got["exception_raw_amount_minor"],
            "net_amount_minor": got["net_amount_minor"] + got["exception_net_amount_minor"],
        }
        for key, want in captured.items():
            if want is None:
                mismatches.append(f"全部擷取 {key}:manifest 沒有這個核對值")
            elif have_captured[key] != want:
                mismatches.append(f"全部擷取 {key}:封存 {want},實際 {have_captured[key]}")
        report["expected"] = expected
        report["mismatches"] = mismatches
        if mismatches:
            raise ArchiveError("筆數或金額跟封存的核對值不一致:" + ";".join(mismatches))
    return report


def _guard_against_restore(tenant, since):
    """在目前的交易裡確認:公司沒有在還原,而且從 `since` 之後沒有被還原過。

    先對公司那一列上「新增資料時本來就會上的」共享鎖:還原正在取代資料時會等它做完;
    還原做完之後,這裡記著的會員 / 單據編號都已經換掉了,不能接著寫 —— 停下來重跑。
    """
    from apps.backup.jobs import in_maintenance
    from apps.backup.models import RestoreJob

    if connection.vendor == "postgresql":
        with connection.cursor() as cur:
            cur.execute("SELECT 1 FROM tenants_tenant WHERE id = %s FOR KEY SHARE", [tenant.pk])
    if in_maintenance(tenant):
        raise ImportBlocked("這家公司正在還原或維護中,匯入已停止;還原結束後請重新執行")
    from django.db.models import Q

    if since is not None and RestoreJob.objects.filter(
        Q(updated_at__gte=since) | Q(confirmed_at__gte=since) | Q(finished_at__gte=since),
        tenant=tenant,
        status__in=[RestoreJob.Status.QUEUED, RestoreJob.Status.RUNNING, RestoreJob.Status.DONE],
    ).exists():
        raise ImportBlocked("這家公司在匯入途中被還原過,匯入已停止;請重新執行(已寫的會自動略過)")


def _fit(model, field_name, value, what):
    field = model._meta.get_field(field_name)
    if value is None:
        if not field.null:
            raise ArchiveError(f"{what}是空的")
        return
    if isinstance(value, str):
        if field.max_length and len(value) > field.max_length:
            raise ArchiveError(f"{what}太長({len(value)} 字,上限 {field.max_length})")
    elif isinstance(value, int) and not isinstance(value, bool):
        from django.db import models as m

        if isinstance(field, m.PositiveSmallIntegerField):
            low, high = 0, 2 ** 15 - 1
        elif isinstance(field, m.PositiveBigIntegerField):
            low, high = 0, 2 ** 63 - 1
        elif isinstance(field, m.PositiveIntegerField):
            low, high = 0, 2 ** 31 - 1
        elif isinstance(field, m.SmallIntegerField):
            low, high = -(2 ** 15), 2 ** 15 - 1
        elif isinstance(field, m.BigIntegerField):
            low, high = -(2 ** 63), 2 ** 63 - 1
        else:
            low, high = -(2 ** 31), 2 ** 31 - 1
        if not low <= value <= high:
            raise ArchiveError(f"{what}超出範圍")
    else:
        raise ArchiveError(f"{what}的格式不對")


def _check_member(m):
    if m["source_system"] != SOURCE_SYSTEM:
        raise ArchiveError(f"會員 {m['source_member_id']!r} 的來源系統不對")
    _fit(LegacyMember, "source_member_id", m["source_member_id"], "會員編號")
    _fit(LegacyMember, "source_member_id_raw", m["source_member_id_raw"], "會員編號原文")
    _fit(LegacyMember, "name_raw", m["name_raw"], "會員姓名")
    _fit(LegacyMember, "phone_raw", m["phone_raw"], "會員電話")
    _fit(LegacyMember, "phone_digits", phone_digits(m["phone_raw"]), "會員電話數字")
    money_minor(m["list_amount_raw"])
    _fit(LegacyMemberListSnapshot, "source_file", m["list_source_file"], "清單來源檔名")
    _fit(LegacyMemberListSnapshot, "list_amount_raw", m["list_amount_raw"], "清單累計原文")
    parse_time(m["last_captured_at"])


def _check_document_fields(d, items):
    """寫進資料庫之前,先確定每一個值都放得下(不能寫到一半才被資料庫擋下)。"""
    _fit(LegacyDocument, "store_name_raw", d["store_name_raw"], "店別")
    _fit(LegacyDocument, "document_type_raw", d["document_type_raw"], "單別")
    _fit(LegacyDocument, "document_number_raw", d["document_number_raw"], "單號")
    _fit(LegacyDocument, "report_amount_minor", d["report_amount_minor"], "單據金額")
    try:
        _date(d["document_date"])
    except (TypeError, ValueError):
        raise ArchiveError(f"單據 {d['document_number_raw']} 的日期讀不出來")
    parse_time(d["last_captured_at"])
    for item in items:
        if not isinstance(item["item_ordinal"], int) or item["item_ordinal"] < 1:
            raise ArchiveError(f"單據 {d['document_number_raw']} 的明細順序不對")
        for name in ITEM_COLUMNS:
            if name in ("item_ordinal", "net_sign"):
                continue
            _fit(LegacyItem, name, item[name], f"單據 {d['document_number_raw']} 的{name}")


@contextmanager
def _import_lock(tenant, write):
    """同一家公司同時只能有一個匯入在寫(PostgreSQL session 層級 advisory lock)。"""
    if not write or connection.vendor != "postgresql":
        yield
        return
    key = int.from_bytes(
        hashlib.sha256(f"mppos-legacy-import:{tenant.pk}".encode()).digest()[:8], "big",
        signed=True,
    )
    with connection.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(%s)", [key])
        if not cur.fetchone()[0]:
            raise ImportBlocked("這家公司已經有另一個匯入正在進行")
    try:
        yield
    finally:
        with connection.cursor() as cur:
            cur.execute("SELECT pg_advisory_unlock(%s)", [key])


def _ensure_maps(tenant, source_system, documents, items_by_doc):
    stores = {d["store_name_raw"] for docs in documents.values() for d in docs}
    codes: dict[str, str] = {}
    seen_at: dict[str, object] = {}
    people = set()
    for docs in documents.values():
        for d in docs:
            when = parse_time(d["last_captured_at"])
            for r in items_by_doc[d["id"]]:
                code = r["product_code_raw"]
                if code not in seen_at or when >= seen_at[code]:
                    codes[code], seen_at[code] = r["product_name_raw"], when
                people.add(r["salesperson_raw"])
    LegacyStoreMap.objects.bulk_create(
        [LegacyStoreMap(tenant=tenant, source_system=source_system, store_name_raw=s)
         for s in stores],
        ignore_conflicts=True,
    )
    LegacyProductMap.objects.bulk_create(
        [LegacyProductMap(tenant=tenant, source_system=source_system, product_code_raw=c,
                          product_name_seen=n[:500], product_name_seen_at=seen_at[c])
         for c, n in codes.items()],
        ignore_conflicts=True,
    )
    # 已經有的:只有這一批的擷取比較新,才換成這一批看到的品名(不動人確認過的對照)
    stale = [
        m for m in LegacyProductMap.objects.filter(
            tenant=tenant, source_system=source_system, product_code_raw__in=list(codes)
        )
        if m.product_name_seen_at is None or seen_at[m.product_code_raw] > m.product_name_seen_at
    ]
    for m in stale:
        m.product_name_seen = codes[m.product_code_raw][:500]
        m.product_name_seen_at = seen_at[m.product_code_raw]
    LegacyProductMap.objects.bulk_update(
        stale, ["product_name_seen", "product_name_seen_at"], batch_size=1000
    )
    LegacySalespersonMap.objects.bulk_create(
        [LegacySalespersonMap(tenant=tenant, source_system=source_system, salesperson_raw=p)
         for p in people],
        ignore_conflicts=True,
    )


def _mapping_summary(tenant, source_system, documents, items_by_doc, members, state):
    stores = {d["store_name_raw"] for docs in documents.values() for d in docs}
    codes = {r["product_code_raw"] for rows in items_by_doc.values() for r in rows}
    people = {r["salesperson_raw"] for rows in items_by_doc.values() for r in rows}

    def mapped(model, field_name, keys):
        return model.objects.filter(
            tenant=tenant, source_system=source_system, status=MapStatus.CONFIRMED,
            **{f"{field_name}__in": keys},
        ).count()

    linked = single = multiple = none = 0
    keys = []
    for m in members:
        keys.append(m["source_member_id"])
        existing = state.members.get(m["source_member_id"])
        if existing is not None and existing.status == MapStatus.CONFIRMED:
            linked += 1
            continue
        hits = state.mp_phones.get(phone_digits(m["phone_raw"]), [])
        if len(hits) == 1:
            single += 1
        elif hits:
            multiple += 1
        else:
            none += 1
    return {
        "members_linked": linked,
        "members_phone_single_candidate": single,
        "members_phone_multiple_candidates": multiple,
        "members_no_candidate": none,
        "stores": len(stores), "stores_mapped": mapped(LegacyStoreMap, "store_name_raw", stores),
        "product_codes": len(codes),
        "product_codes_mapped": mapped(LegacyProductMap, "product_code_raw", codes),
        "salespersons": len(people),
        "salespersons_mapped": mapped(LegacySalespersonMap, "salesperson_raw", people),
        "_member_keys": keys,
    }


def _run_batch(tenant, archive, info, state, *, write, user, log) -> BatchReport:
    report = BatchReport(info.archive_batch_id, (info.period_start, info.period_end))
    t = report.totals
    batch_id = info.archive_batch_id
    members = list(archive.members(batch_id))
    snapshots = archive.snapshots(batch_id)
    documents = archive.documents(batch_id)
    doc_ids = [d["id"] for docs in documents.values() for d in docs]
    items_by_doc = archive.items(doc_ids)
    versions_by_doc = archive.versions(doc_ids)
    exceptions = archive.exceptions(batch_id)

    # ── 先把整批核對完,有任何問題就在寫入前停下 ──
    if set(snapshots) != {m["id"] for m in members}:
        raise ArchiveError(f"批次 {batch_id} 的會員清單跟明細快照對不起來")
    _fit(HistoryImportBatch, "source_file", info.source_file, "來源檔名")
    for m in members:
        snap = snapshots[m["id"]]
        archive.check_snapshot(snap)
        parse_time(snap["captured_at"])
        _check_member(m)
    for docs in documents.values():
        for d in docs:
            if d["snapshot_member_id"] != d["member_id"]:
                raise ArchiveError(f"單據 {d['document_number_raw']} 掛在別的會員的快照上")
            # 新舊判斷靠擷取時間:單據記的時間必須就是它那份快照的時間,不能兩套說法
            if parse_time(d["last_captured_at"]) != parse_time(d["snapshot_captured_at"]):
                raise ArchiveError(
                    f"單據 {d['document_number_raw']} 的擷取時間跟它的快照時間不一致"
                )
            _check_document_fields(d, items_by_doc.get(d["id"], []))
    types = Counter()
    for docs in documents.values():
        for d in docs:
            items = items_by_doc.get(d["id"], [])
            archive.check_document(d, items, versions_by_doc.get(d["id"], []))
            types[d["document_type_raw"]] += 1
            t.documents += 1
            t.items += len(items)
            t.raw_amount_minor += sum(i["amount_minor"] for i in items)
            t.net_amount_minor += sum(i["amount_minor"] * i["net_sign"] for i in items)
            t.negative_amount_items += sum(1 for i in items if i["amount_minor"] < 0)
            t.null_unit_price_items += sum(1 for i in items if i["unit_price_minor"] is None)
    t.document_types = dict(types)
    t.members = len(members)
    t.snapshots = len(snapshots)
    # 每位會員:這一批的明細淨額 vs 會員清單上的累計原文,自己重算一次。
    # 對得上的不能被標成待核;對不上的一定要在待核裡,而且待核記的清單金額要等於清單原文。
    for m in members:
        listed = money_minor(m["list_amount_raw"])
        net = sum(
            i["amount_minor"] * i["net_sign"]
            for d in documents.get(m["id"], []) for i in items_by_doc.get(d["id"], [])
        )
        e = exceptions.get(m["id"])
        if e is None and net != listed:
            raise ArchiveError(
                f"會員 {m['source_member_id'].strip()} 在批次 {batch_id} 的明細淨額跟清單累計對不上,"
                "卻沒有被標成待核"
            )
        if e is not None and (net != 0 or e["list_amount_minor"] != listed
                              or e["detail_net_amount_minor"] == listed):
            raise ArchiveError(
                f"會員 {m['source_member_id'].strip()} 的待核紀錄跟清單原文 / 明細對不起來"
            )
    for member_id, e in exceptions.items():
        if member_id in documents:
            raise ArchiveError("待核會員同時出現在已核對的單據裡,封存不一致")
        if member_id not in snapshots:
            raise ArchiveError("待核會員不在這一批的會員清單裡")
        for name in ("reason", "list_amount_minor", "detail_net_amount_minor",
                     "detail_raw_amount_minor", "difference_minor", "line_count", "document_count"):
            _fit(LegacySourceException, name, e[name], f"待核的{name}")
        archive.check_exception(e, member_id, batch_id)
        t.exception_members += 1
        t.exception_documents += e["document_count"]
        t.exception_items += e["line_count"]
        t.exception_raw_amount_minor += e["detail_raw_amount_minor"]
        t.exception_net_amount_minor += e["detail_net_amount_minor"]
        t.exception_list_amount_minor += e["list_amount_minor"]
        t.exception_difference_minor += e["difference_minor"]
        member = next(m for m in members if m["id"] == member_id)
        report.excluded_exceptions.append({
            "source_member_id": member["source_member_id"],
            "documents": e["document_count"], "items": e["line_count"],
            "list_amount_minor": e["list_amount_minor"],
            "detail_net_amount_minor": e["detail_net_amount_minor"],
            "difference_minor": e["difference_minor"],
        })
    # 每一批自己的核對值:已核對的會員數 / 明細數
    expected = archive.q(
        "SELECT member_count, line_count FROM import_batches WHERE id = ?", batch_id
    ).fetchone()
    batch_lines = archive.batch_version_lines(batch_id)
    if (len(members) - len(exceptions), batch_lines) != (
        expected["member_count"], expected["line_count"]
    ):
        raise ArchiveError(
            f"批次 {batch_id} 的會員 / 明細數跟封存記錄不符:"
            f"封存 {expected['member_count']} / {expected['line_count']},"
            f"實際 {len(members) - len(exceptions)} / {batch_lines}"
        )

    # 跟這一批的匯入內容檔(獨立的另一份來源)逐筆比對:同樣的會員、同樣的報表列,一筆不多一筆不少。
    # 寫入那一輪不再比一次:第一輪已經對同一份封存(雜湊驗過,不會變)比過了。
    if not write:
        _cross_check_payload(archive, info, members, exceptions)

    report.mapping = _mapping_summary(
        tenant, info.source_system, documents, items_by_doc, members, state
    )
    # 既有的「舊系統消費紀錄」(CSV 匯入的那種)裡,有沒有看起來是同一張單的:只列出來,不自動處理
    old_keys = {(no, str(when)) for no, when in state.legacy_purchase_keys}
    report.overlap_legacy_purchases = sum(
        1 for docs in documents.values() for d in docs
        if (d["document_number_raw"], d["document_date"]) in old_keys
    )

    # ── 試算:只推算會發生什麼 ──
    if not write:
        _predict(report, members, documents, items_by_doc, state)
        return report

    with transaction.atomic():
        _guard_against_restore(tenant, state.started_at)
        batch = _open_batch(tenant, archive, info, user)
        _ensure_maps(tenant, info.source_system, documents, items_by_doc)
    state.batches[info.archive_batch_id] = batch
    report.batch_id = batch.pk
    for n, m in enumerate(members, 1):
        _write_member(
            tenant, batch, info, m, snapshots[m["id"]], documents.get(m["id"], []),
            items_by_doc, versions_by_doc, exceptions.get(m["id"]), state, report.effect,
        )
        if n % 2000 == 0:
            log(f"  已處理 {n}/{len(members)} 位會員")
    with transaction.atomic():
        _guard_against_restore(tenant, state.started_at)
        batch.status = HistoryImportBatch.Status.DONE
        batch.finished_at = timezone.now()
        batch.result = {
            "totals": report.totals.as_dict(), "effect": report.effect.as_dict(),
            "excluded_exceptions": report.excluded_exceptions,
        }
        batch.save(update_fields=["status", "finished_at", "result", "updated_at"])
    return report


def _cross_check_payload(archive, info, members, exceptions):
    batch_id = info.archive_batch_id
    payload_prints, payload_members = archive.payload_fingerprints(info)
    db_prints = Counter()
    for (member_source_id, rows_json) in archive.q(
        "SELECT m.source_member_id, v.rows_json FROM document_versions v "
        "JOIN source_snapshots s ON s.id = v.snapshot_id "
        "JOIN legacy_members m ON m.id = s.member_id WHERE s.import_batch_id = ?",
        batch_id,
    ):
        db_prints.update(version_prints(member_source_id, rows_json))
    if payload_prints != db_prints:
        raise ArchiveError(
            f"批次 {batch_id} 的資料庫內容跟匯入內容檔不一致"
            f"(匯入內容檔 {sum(payload_prints.values())} 筆,資料庫 {sum(db_prints.values())} 筆)"
        )
    reconciled_ids = Counter(
        m["source_member_id"] for m in members if m["id"] not in exceptions
    )
    if payload_members != reconciled_ids:
        raise ArchiveError(f"批次 {batch_id} 的已核對會員跟匯入內容檔不一致")
    del payload_prints, db_prints


def _predict(report, members, documents, items_by_doc, state):
    e = report.effect
    for m in members:
        existing = state.members.get(m["source_member_id"])
        if existing is None and m["source_member_id"] in state.predicted_members:
            e.members_unchanged += 1
        elif existing is None:
            e.members_new += 1
            state.predicted_members.add(m["source_member_id"])
        elif parse_time(m["last_captured_at"]) > existing.last_captured_at:
            e.members_updated += 1
        else:
            e.members_unchanged += 1
        for d in documents.get(m["id"], []):
            current = state.documents.get(
                (existing.pk if existing else None, d["store_name_raw"], d["document_type_raw"],
                 d["document_number_raw"], _date(d["document_date"]))
            ) if existing else None
            captured = parse_time(d["last_captured_at"])
            if current is None:
                e.documents_new += 1
                e.items_written += len(items_by_doc[d["id"]])
            elif current.content_sha256 == d["content_sha256"]:
                e.documents_unchanged += 1
            elif captured == current.last_captured_at:
                raise ArchiveError(
                    f"單據 {d['document_number_raw']} 在同一個擷取時間有兩種不同內容,不能判斷哪個對"
                )
            elif captured > current.last_captured_at:
                e.documents_replaced += 1
                e.items_written += len(items_by_doc[d["id"]])
            else:
                e.documents_older_capture += 1


def _date(text):
    from datetime import date

    return date.fromisoformat(text)


def _open_batch(tenant, archive, info, user):
    batch, created = HistoryImportBatch.objects.get_or_create(
        tenant=tenant, content_sha256=info.content_sha256,
        defaults=dict(
            source_system=info.source_system, report=info.report,
            period_start=info.period_start, period_end=info.period_end,
            archive_sha256=archive.database_sha256, archive_batch_id=info.archive_batch_id,
            source_file=info.source_file, source_scope_raw=info.source_scope_raw,
            archive_schema_version=int(archive.metadata["archive_schema_version"]),
            normalized_schema_version=int(archive.metadata["normalized_schema_version"]),
            imported_by=user if getattr(user, "is_authenticated", False) else None,
        ),
    )
    if not created and batch.status != HistoryImportBatch.Status.RUNNING:
        batch.status = HistoryImportBatch.Status.RUNNING
        batch.rolled_back_at = None
        batch.save(update_fields=["status", "rolled_back_at", "updated_at"])
    return batch


@transaction.atomic
def _write_member(tenant, batch, info, m, snap, docs, items_by_doc, versions_by_doc,
                  exception, state, effect):
    _guard_against_restore(tenant, state.started_at)
    captured = parse_time(m["last_captured_at"])
    member = state.members.get(m["source_member_id"])
    fields = dict(
        source_member_id_raw=m["source_member_id_raw"], name_raw=m["name_raw"],
        phone_raw=m["phone_raw"], phone_digits=phone_digits(m["phone_raw"]),
        last_captured_at=captured,
    )
    if member is None:
        member = LegacyMember.objects.create(
            tenant=tenant, source_system=info.source_system,
            source_member_id=m["source_member_id"], first_batch=batch, **fields,
        )
        state.members[member.source_member_id] = member
        effect.members_new += 1
    elif captured > member.last_captured_at:
        for k, v in fields.items():
            setattr(member, k, v)
        member.save(update_fields=[*fields, "updated_at"])
        effect.members_updated += 1
    else:
        effect.members_unchanged += 1

    LegacyMemberListSnapshot.objects.get_or_create(
        tenant=tenant, batch=batch, legacy_member=member,
        defaults=dict(source_file=m["list_source_file"], list_amount_raw=m["list_amount_raw"],
                      raw_json=m["list_raw_json"]),
    )
    snapshot, _ = LegacySourceSnapshot.objects.get_or_create(
        tenant=tenant, batch=batch, legacy_member=member,
        defaults=dict(source_url=snap["source_url"], captured_at=parse_time(snap["captured_at"]),
                      raw_sha256=snap["raw_sha256"], raw_json=snap["raw_json"]),
    )
    if snapshot.raw_sha256 != snap["raw_sha256"]:
        raise ArchiveError("同一批、同一會員的快照內容跟上次匯入的不一樣")

    if exception is not None:
        _, created = LegacySourceException.objects.get_or_create(
            tenant=tenant, batch=batch, legacy_member=member,
            defaults=dict(
                snapshot=snapshot, reason=exception["reason"],
                list_amount_minor=exception["list_amount_minor"],
                detail_net_amount_minor=exception["detail_net_amount_minor"],
                detail_raw_amount_minor=exception["detail_raw_amount_minor"],
                difference_minor=exception["difference_minor"],
                line_count=exception["line_count"], document_count=exception["document_count"],
                rows_json=exception["rows_json"], validation_error=exception["validation_error"],
            ),
        )
        effect.exceptions_new += int(created)

    for d in docs:
        _write_document(tenant, batch, info, member, snapshot, d, items_by_doc[d["id"]],
                        versions_by_doc.get(d["id"], []), state, effect)


def _write_document(tenant, batch, info, member, snapshot, d, items, versions, state, effect):
    key = (member.pk, d["store_name_raw"], d["document_type_raw"], d["document_number_raw"],
           _date(d["document_date"]))
    captured = parse_time(d["last_captured_at"])
    net = sum(i["amount_minor"] * i["net_sign"] for i in items)
    doc = state.documents.get(key)
    if doc is None:
        doc = LegacyDocument.objects.create(
            tenant=tenant, source_system=info.source_system, legacy_member=member,
            store_name_raw=d["store_name_raw"], document_type_raw=d["document_type_raw"],
            document_number_raw=d["document_number_raw"], document_date=key[4],
            content_sha256=d["content_sha256"], snapshot=snapshot,
            report_amount_minor=d["report_amount_minor"], net_amount_minor=net,
            item_count=len(items), last_captured_at=captured, first_batch=batch,
        )
        state.documents[key] = doc
        _write_items(tenant, info, doc, items)
        effect.documents_new += 1
        effect.items_written += len(items)
    elif doc.content_sha256 == d["content_sha256"]:
        effect.documents_unchanged += 1
        if captured > doc.last_captured_at:
            # 內容沒變,但這次是比較新的擷取:單據改以這一次為準(明細不用動),
            # 跟舊會員的「最後擷取時間」一致
            LegacyDocumentVersion.objects.filter(
                document=doc, snapshot_id=doc.snapshot_id
            ).update(superseded_at=timezone.now())
            doc.snapshot = snapshot
            doc.last_captured_at = captured
            doc.save(update_fields=["snapshot", "last_captured_at", "updated_at"])
    elif captured > doc.last_captured_at:
        # 內容不同、而且是比較新的擷取:整張換掉,換之前把目前的明細存進它那一版
        doc = LegacyDocument.objects.select_for_update().get(pk=doc.pk)
        current = LegacyDocumentVersion.objects.filter(
            document=doc, snapshot_id=doc.snapshot_id
        ).first()
        if current is not None:
            current.items_json = json.dumps(
                list(doc.items.order_by("item_ordinal").values(*ITEM_COLUMNS)),
                ensure_ascii=False,
            )
            current.superseded_at = timezone.now()
            current.save(update_fields=["items_json", "superseded_at", "updated_at"])
        doc.items.all().delete()
        _write_items(tenant, info, doc, items)
        doc.content_sha256 = d["content_sha256"]
        doc.snapshot = snapshot
        doc.report_amount_minor = d["report_amount_minor"]
        doc.net_amount_minor = net
        doc.item_count = len(items)
        doc.last_captured_at = captured
        doc.save()
        state.documents[key] = doc
        effect.documents_replaced += 1
        effect.items_written += len(items)
    elif captured == doc.last_captured_at:
        raise ArchiveError(
            f"單據 {doc.document_number_raw} 在同一個擷取時間有兩種不同內容,不能判斷哪個對"
        )
    else:
        effect.documents_older_capture += 1

    # 這張單在封存裡每一次擷取到的內容都留成版本,各掛在自己那一批的快照上。
    # 封存只替「目前那一版」存了逐筆明細,其他版本只有報表列原文。
    for v in versions:
        if v["import_batch_id"] == info.archive_batch_id:
            v_batch, v_snapshot = batch, snapshot
        else:
            v_batch = state.batches.get(v["import_batch_id"])
            if v_batch is None:      # 那一批這次沒有匯
                continue
            v_snapshot = LegacySourceSnapshot.objects.filter(
                batch=v_batch, legacy_member=member
            ).first()
            if v_snapshot is None:
                continue
        is_current = v["snapshot_id"] == d["snapshot_id"] and doc.snapshot_id == v_snapshot.pk
        # 目前那一版的明細就在明細表裡;不是目前版的(例如之後才匯進來的較舊擷取),
        # 把封存給的明細存進版本,撤回目前版時才退得回來
        keep_items = (
            "" if is_current or v["snapshot_id"] != d["snapshot_id"]
            else json.dumps([_item_values(r) for r in items], ensure_ascii=False)
        )
        _, created = LegacyDocumentVersion.objects.get_or_create(
            document=doc, snapshot=v_snapshot,
            defaults=dict(
                tenant=tenant, batch=v_batch, content_sha256=v["content_sha256"],
                rows_json=v["rows_json"], items_json=keep_items,
                superseded_at=None if is_current else timezone.now(),
            ),
        )
        effect.versions_added += int(created)


def _write_items(tenant, info, doc, items):
    LegacyItem.objects.bulk_create([
        LegacyItem(tenant=tenant, source_system=info.source_system, document=doc,
                   **_item_values(r))
        for r in items
    ])


# ─────────────────────────── 撤回 ───────────────────────────
class RollbackBlocked(Exception):
    """不能撤回(原因可以直接給人看)。資料沒有任何變動。"""


def rollback_batch(batch, user=None) -> dict:
    """撤回一批(見 _rollback)。跟匯入共用同一把鎖:撤回時不會有匯入同時在寫。"""
    with _import_lock(batch.tenant, True):
        return _rollback(batch, user)


@transaction.atomic
def _rollback(batch, user=None) -> dict:
    """撤回一批:只動這一批帶進來的東西。

    - 這一批新建、而且沒有別批版本的單據 → 刪掉(含明細與版本)。
    - 這一批把某張單換成新內容 → 換回上一版(用上一版保存的明細),刪掉這一批的版本。
    - 這一批的快照、清單快照、待核紀錄 → 刪掉。
    - 這一批新建的舊會員:還有別批的資料、或已經被人確認對照的,留著;否則刪掉。
    - 對照表(店別 / 品號 / 業務員)不動:那是人的決定,而且可能也被別批用到。
    """
    batch = HistoryImportBatch.objects.select_for_update().get(pk=batch.pk)
    if batch.status == HistoryImportBatch.Status.ROLLED_BACK:
        raise RollbackBlocked("這一批已經撤回過了")
    tenant = batch.tenant
    try:
        _guard_against_restore(tenant, None)
    except ImportBlocked as exc:
        raise RollbackBlocked(str(exc))
    counts = Counter()
    # 先鎖住這一批碰過的舊會員:撤回進行中,網頁上「確認對照」會等撤回做完;
    # 不然可能剛被確認對照的舊會員,在下面被當成沒人用而刪掉
    list(
        LegacyMember.objects.filter(
            pk__in=LegacySourceSnapshot.objects.filter(batch=batch).values("legacy_member_id")
        ).select_for_update().order_by("pk").values_list("pk", flat=True)
    )
    batch_snapshots = set(
        LegacySourceSnapshot.objects.filter(batch=batch).values_list("id", flat=True)
    )
    touched_ids = LegacyDocumentVersion.objects.filter(batch=batch).values("document_id")
    touched = LegacyDocument.objects.filter(tenant=tenant, pk__in=touched_ids)
    touched_codes = set(
        LegacyItem.objects.filter(document__in=touched).values_list("product_code_raw", flat=True)
    )
    from .archive import COL

    for rows_json in LegacyDocumentVersion.objects.filter(batch=batch).values_list(
        "rows_json", flat=True
    ):
        touched_codes.update(row[COL["code"]] for row in json.loads(rows_json))
    for doc in touched.select_for_update().order_by("pk"):
        if doc.snapshot_id not in batch_snapshots:
            counts["versions_removed"] += doc.versions.filter(batch=batch).delete()[0]
            if doc.first_batch_id == batch.pk:
                doc.first_batch_id = doc.versions.order_by("id").first().batch_id
                doc.save(update_fields=["first_batch", "updated_at"])
            continue
        same = (
            doc.versions.exclude(batch=batch).filter(content_sha256=doc.content_sha256)
            .select_related("snapshot").order_by("-snapshot__captured_at", "-id").first()
        )
        if same is not None:
            # 別批也擷取到一模一樣的內容:明細不用動,改成以那一次擷取為準
            doc.snapshot_id = same.snapshot_id
            doc.last_captured_at = same.snapshot.captured_at
            doc.first_batch_id = doc.versions.exclude(batch=batch).order_by("id").first().batch_id
            doc.save()
            same.superseded_at = None
            same.save(update_fields=["superseded_at", "updated_at"])
            counts["versions_removed"] += doc.versions.filter(batch=batch).delete()[0]
            counts["documents_restored"] += 1
            continue
        previous = (
            doc.versions.exclude(batch=batch).exclude(items_json="")
            .order_by("-snapshot__captured_at", "-id").first()
        )
        if previous is None:
            if doc.versions.exclude(batch=batch).exists():
                raise RollbackBlocked(
                    f"單據 {doc.document_number_raw} 的上一版沒有保存明細,無法換回;請聯絡維護人員"
                )
            doc.delete()
            counts["documents_removed"] += 1
            continue
        rows = json.loads(previous.items_json)
        doc.items.all().delete()
        LegacyItem.objects.bulk_create([
            LegacyItem(tenant=tenant, source_system=doc.source_system, document=doc, **r)
            for r in rows
        ])
        doc.content_sha256 = previous.content_sha256
        doc.snapshot_id = previous.snapshot_id
        doc.report_amount_minor = sum(r["amount_minor"] for r in rows)
        doc.net_amount_minor = sum(r["amount_minor"] * r["net_sign"] for r in rows)
        doc.item_count = len(rows)
        doc.last_captured_at = previous.snapshot.captured_at
        doc.first_batch_id = doc.versions.exclude(batch=batch).order_by("id").first().batch_id
        doc.save()
        previous.superseded_at = None
        previous.items_json = ""
        previous.save(update_fields=["superseded_at", "items_json", "updated_at"])
        counts["versions_removed"] += doc.versions.filter(batch=batch).delete()[0]
        counts["documents_restored"] += 1

    counts["exceptions_removed"] = LegacySourceException.objects.filter(batch=batch).delete()[0]
    LegacyDocumentVersion.objects.filter(batch=batch).delete()
    counts["snapshots_removed"] = LegacySourceSnapshot.objects.filter(batch=batch).delete()[0]
    counts["list_snapshots_removed"] = (
        LegacyMemberListSnapshot.objects.filter(batch=batch).delete()[0]
    )
    orphans = LegacyMember.objects.filter(
        tenant=tenant, first_batch=batch, status=MapStatus.UNMAPPED,
        source_snapshots__isnull=True, documents__isnull=True,
    )
    counts["members_removed"] = orphans.delete()[0]
    # 留下來的舊會員改掛到還在的最早一批
    for member in LegacyMember.objects.filter(tenant=tenant, first_batch=batch):
        other = (
            LegacySourceSnapshot.objects.filter(legacy_member=member)
            .exclude(batch=batch).order_by("batch_id").first()
        )
        if other is None:
            raise RollbackBlocked(
                f"舊會員 {member.display_id} 已經被確認對照,但只有這一批的資料;"
                "請先撤銷對照再撤回這一批"
            )
        member.first_batch_id = other.batch_id
        member.save(update_fields=["first_batch", "updated_at"])
    # 品號對照的「最近看到的品名」照剩下的資料重算(人確認的對照不動)
    for pm in LegacyProductMap.objects.filter(
        tenant=tenant, source_system=batch.source_system, product_code_raw__in=touched_codes
    ):
        latest = (
            LegacyItem.objects.filter(
                tenant=tenant, source_system=pm.source_system, product_code_raw=pm.product_code_raw
            ).select_related("document").order_by("-document__last_captured_at", "-id").first()
        )
        if latest is not None:
            pm.product_name_seen = latest.product_name_raw[:500]
            pm.product_name_seen_at = latest.document.last_captured_at
        else:
            pm.product_name_seen = ""
            pm.product_name_seen_at = None
        pm.save(update_fields=["product_name_seen", "product_name_seen_at", "updated_at"])
    batch.status = HistoryImportBatch.Status.ROLLED_BACK
    batch.rolled_back_at = timezone.now()
    batch.result = {**batch.result, "rollback": dict(counts),
                    "rolled_back_by": getattr(user, "username", "")}
    batch.save(update_fields=["status", "rolled_back_at", "result", "updated_at"])
    return dict(counts)
