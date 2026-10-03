"""讀「舊 POS 十年會員消費封存」(歐睿 ST004)並核對它。只讀,不改封存檔。

封存的格式由擷取端定義(封存結構第 3 版、標準化格式第 2 版);這裡只接受這個版本,
其他版本一律拒絕,不猜欄位。核對項目:

- 資料庫檔的 SHA-256 等於 manifest 記的值;每一批的匯入內容檔 SHA-256 等於
  `import_batches.content_sha256`(也等於 manifest 記的值)。
- 封存版本、來源系統、涵蓋期間等於呼叫端要求的。
- 單別正負規則等於這裡寫死的 `NET_SIGN`;資料裡每一張單的單別都要認得,
  每一列的正負都要等於規則。
- 每一份擷取快照的全文雜湊、每一張單據版本的內容雜湊都重新算一次。
- 每一張單的明細筆數、金額合計跟它目前那一版的報表列一致。
- 全部的筆數與金額等於 manifest 的核對值。

任何一項不對就丟 `ArchiveError`,不會寫入任何東西。
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .models import NET_SIGN

ARCHIVE_SCHEMA_VERSION = 3
NORMALIZED_SCHEMA_VERSION = 2
SOURCE_SYSTEM = "Ored legacy POS"
REPORT = "ST004"


class ArchiveError(Exception):
    """封存檔不能用(原因可以直接給人看)。"""


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def compact(value) -> str:
    """跟封存工具同一種 JSON 寫法(算內容雜湊用)。"""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def document_content_sha256(rows) -> str:
    """封存工具算單據內容雜湊的方式:每一列去掉第一欄(報表序號)後的 JSON。"""
    return hashlib.sha256(compact([row[1:] for row in rows]).encode()).hexdigest()


def parse_time(text: str) -> datetime:
    value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ArchiveError(f"擷取時間沒有時區:{text}")
    return value


# 報表明細 16 欄(來源欄名:序號、單別、單號、品號、品名、數量、單價、金額、金額(未稅)、
# 點數、店別、日期、業務員、客戶名稱、備註-單身備註、促銷方案)在報表列原文裡的位置
COL = {
    "seq": 0, "type": 1, "number": 2, "code": 3, "name": 4, "qty": 5, "price": 6,
    "amount": 7, "ex_tax": 8, "points": 9, "store": 10, "date": 11, "salesperson": 12,
    "customer": 13, "remarks": 14, "promotion": 15,
}
ROW_WIDTH = 16


def money_minor(raw) -> int:
    """跟封存工具同一種換算:去掉千分位與「元」,乘 100 必須是整數。"""
    try:
        value = Decimal(str(raw).strip().replace(",", "").replace("元", ""))
    except InvalidOperation:
        raise ArchiveError(f"金額讀不出來:{raw!r}")
    cents = value * 100
    if not value.is_finite() or cents != cents.to_integral_value():
        raise ArchiveError(f"金額不是到分的整數:{raw!r}")
    return int(cents)


def row_document_key(row) -> tuple:
    """報表列 → (店別, 單別, 單號, 日期 YYYY-MM-DD)。日期必須正好是 8 位數字的合法日期。"""
    d = row[COL["date"]]
    if not (isinstance(d, str) and len(d) == 8 and d.isdigit()):
        raise ArchiveError(f"報表列的日期格式不對:{d!r}")
    iso = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
    try:
        date.fromisoformat(iso)
    except ValueError:
        raise ArchiveError(f"報表列的日期不存在:{d!r}")
    return (row[COL["store"]], row[COL["type"]], row[COL["number"]], iso)


ITEM_COLUMNS = (
    "item_ordinal", "report_sequence_raw", "product_code_raw", "product_name_raw",
    "quantity_decimal", "quantity_raw", "unit_price_minor", "amount_minor",
    "amount_ex_tax_minor", "points_raw", "salesperson_raw", "customer_name_raw",
    "remarks_raw", "promotion_raw", "source_row_json", "net_sign",
)


@dataclass
class BatchInfo:
    archive_batch_id: int
    content_sha256: str
    source_system: str
    report: str
    period_start: date
    period_end: date
    source_file: str
    source_scope_raw: str


@dataclass
class Totals:
    members: int = 0
    snapshots: int = 0
    documents: int = 0
    items: int = 0
    raw_amount_minor: int = 0
    net_amount_minor: int = 0
    exception_members: int = 0
    exception_documents: int = 0
    exception_items: int = 0
    exception_raw_amount_minor: int = 0
    exception_net_amount_minor: int = 0
    exception_list_amount_minor: int = 0
    exception_difference_minor: int = 0
    negative_amount_items: int = 0
    null_unit_price_items: int = 0
    document_types: dict = field(default_factory=dict)

    def as_dict(self):
        return dict(self.__dict__)


class Archive:
    """一份打開、核對過的封存。用完要 close()。"""

    def __init__(self, root, *, period=None):
        self.root = Path(root)
        manifest_path = self.root / "manifest.json"
        if not manifest_path.is_file():
            raise ArchiveError(f"找不到 manifest.json:{manifest_path}")
        try:
            self.manifest = json.loads(manifest_path.read_text())
        except ValueError as exc:
            raise ArchiveError(f"manifest.json 讀不出來:{exc}")
        db_file = self.root / self.manifest.get("database_file", "")
        if not db_file.is_file():
            raise ArchiveError(f"找不到封存資料庫:{db_file}")
        self.database_sha256 = sha256_file(db_file)
        if self.database_sha256 != self.manifest.get("database_sha256"):
            raise ArchiveError("封存資料庫的雜湊跟 manifest 不一樣(檔案可能被改過或不完整)")
        # 唯讀 + immutable:不會在旁邊產生任何暫存檔,也不會改到封存
        self.db = sqlite3.connect(f"file:{db_file}?mode=ro&immutable=1", uri=True)
        self.db.row_factory = sqlite3.Row
        try:
            self._check_metadata(period)
            self.batches = self._load_batches()
        except Exception:
            self.close()
            raise

    def close(self):
        db = getattr(self, "db", None)
        if db is not None:
            db.close()
            self.db = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ── 基本檢查 ──
    def q(self, sql, *args):
        return self.db.execute(sql, args)

    def _check_metadata(self, period):
        meta = {r["key"]: r["value"] for r in self.q("SELECT key, value FROM archive_metadata")}
        self.metadata = meta
        if meta.get("archive_schema_version") != str(ARCHIVE_SCHEMA_VERSION):
            raise ArchiveError(
                f"封存結構版本是 {meta.get('archive_schema_version')},這個匯入程式只接受 "
                f"{ARCHIVE_SCHEMA_VERSION}"
            )
        if meta.get("normalized_schema_version") != str(NORMALIZED_SCHEMA_VERSION):
            raise ArchiveError(
                f"標準化格式版本是 {meta.get('normalized_schema_version')},只接受 "
                f"{NORMALIZED_SCHEMA_VERSION}"
            )
        if meta.get("source_system") != SOURCE_SYSTEM:
            raise ArchiveError(f"來源系統不是 {SOURCE_SYSTEM}:{meta.get('source_system')}")
        if meta.get("capture_complete") != "true":
            raise ArchiveError("封存標示「擷取未完成」,不能匯入")
        try:
            rule = json.loads(meta.get("net_sign_rule", ""))
        except ValueError:
            raise ArchiveError("封存的單別正負規則讀不出來")
        if rule != NET_SIGN:
            raise ArchiveError(
                f"封存的單別正負規則跟系統不一致:封存 {rule},系統 {NET_SIGN}"
            )
        covered = (meta.get("covered_period_start"), meta.get("covered_period_end"))
        self.covered_period = covered
        if period is not None and tuple(str(x) for x in period) != covered:
            raise ArchiveError(
                f"指定的期間 {period[0]}~{period[1]} 跟封存涵蓋的 {covered[0]}~{covered[1]} 不一樣"
            )

    def _load_batches(self):
        entries = self.manifest.get("source_archives", [])
        if not isinstance(entries, list) or not all(isinstance(x, dict) for x in entries):
            raise ArchiveError("manifest 的批次清單格式不對")
        listed = {s.get("import_batch_id"): s for s in entries}
        if len(listed) != len(entries):
            raise ArchiveError("manifest 的批次清單有重複的批次編號")
        batches = []
        for r in self.q(
            "SELECT id, content_sha256, source_system, report, period_start, period_end, "
            "source_file, source_scope_json FROM import_batches ORDER BY id"
        ):
            entry = listed.get(r["id"])
            if entry is None:
                raise ArchiveError(f"manifest 沒有列出封存批次 {r['id']}")
            payload = self.root / r["source_file"]
            if not payload.is_file():
                raise ArchiveError(f"找不到批次 {r['id']} 的匯入內容檔:{r['source_file']}")
            digest = sha256_file(payload)
            if digest != r["content_sha256"] or digest != entry.get("import_payload_sha256"):
                raise ArchiveError(f"批次 {r['id']} 的匯入內容檔雜湊不符(檔案可能被改過)")
            if r["source_system"] != SOURCE_SYSTEM or r["report"] != REPORT:
                raise ArchiveError(f"批次 {r['id']} 的來源不是 {SOURCE_SYSTEM} {REPORT}")
            if entry.get("import_payload_file") != r["source_file"]:
                raise ArchiveError(f"manifest 記的批次 {r['id']} 匯入內容檔跟封存資料庫不一致")
            if list(entry.get("period") or []) != [r["period_start"], r["period_end"]]:
                raise ArchiveError(f"manifest 記的批次 {r['id']} 期間跟封存資料庫不一致")
            batches.append(BatchInfo(
                archive_batch_id=r["id"], content_sha256=r["content_sha256"],
                source_system=r["source_system"], report=r["report"],
                period_start=date.fromisoformat(r["period_start"]),
                period_end=date.fromisoformat(r["period_end"]),
                source_file=r["source_file"], source_scope_raw=r["source_scope_json"],
            ))
        if not batches:
            raise ArchiveError("封存裡沒有任何批次")
        if set(listed) != {b.archive_batch_id for b in batches}:
            raise ArchiveError("manifest 列的批次跟封存資料庫的批次不一致")
        # 同一份封存裡同一張單有好幾個版本(在不同批被擷取到不同內容):封存只替最新那一版
        # 存了逐筆明細,其他版本要怎麼排、哪一版生效,這一版的匯入程式不猜 —— 直接拒絕,
        # 請把不同時間的擷取分成不同的封存匯入(補抓本來就是另一份封存)。
        multi = self.q(
            "SELECT count(*) FROM (SELECT document_id FROM document_versions "
            "GROUP BY document_id HAVING count(*) > 1)"
        ).fetchone()[0]
        if multi:
            raise ArchiveError(
                f"封存裡有 {multi} 張單在同一份封存內有多個版本,這個匯入程式不處理;"
                "請把不同時間的擷取分成不同的封存匯入"
            )
        return batches

    # ── 逐批讀取 ──
    def members(self, batch_id):
        """這一批有出現的會員(會員清單那一列 + 會員本身),依封存會員編號排序。"""
        return self.q(
            "SELECT m.id, m.source_system, m.source_member_id, m.source_member_id_raw, m.name_raw, "
            "m.phone_raw, m.last_captured_at, l.source_file AS list_source_file, l.list_amount_raw, "
            "l.raw_json AS list_raw_json "
            "FROM member_list_snapshots l JOIN legacy_members m ON m.id = l.member_id "
            "WHERE l.import_batch_id = ? ORDER BY m.id",
            batch_id,
        )

    def snapshots(self, batch_id):
        return {
            r["member_id"]: r for r in self.q(
                "SELECT id, member_id, source_url, captured_at, raw_sha256, raw_json "
                "FROM source_snapshots WHERE import_batch_id = ?",
                batch_id,
            )
        }

    def documents(self, batch_id):
        """目前依據的快照屬於這一批的單據:{封存會員 id: [單據...]}。"""
        out: dict[int, list] = {}
        for r in self.q(
            "SELECT d.id, d.member_id, d.store_name_raw, d.document_type_raw, "
            "d.document_number_raw, d.document_date, d.content_sha256, d.snapshot_id, "
            "d.report_amount_minor, d.last_captured_at, s.member_id AS snapshot_member_id, "
            "s.captured_at AS snapshot_captured_at "
            "FROM legacy_documents d JOIN source_snapshots s ON s.id = d.snapshot_id "
            "WHERE s.import_batch_id = ? ORDER BY d.member_id, d.id",
            batch_id,
        ):
            out.setdefault(r["member_id"], []).append(r)
        return out

    def items(self, document_ids):
        out: dict[int, list] = {}
        ids = list(document_ids)
        for start in range(0, len(ids), 900):
            chunk = ids[start:start + 900]
            marks = ",".join("?" * len(chunk))
            for r in self.q(
                f"SELECT document_id, {', '.join(ITEM_COLUMNS)} FROM legacy_items "
                f"WHERE document_id IN ({marks}) ORDER BY document_id, item_ordinal",
                *chunk,
            ):
                out.setdefault(r["document_id"], []).append(r)
        return out

    def versions(self, document_ids):
        out: dict[int, list] = {}
        ids = list(document_ids)
        for start in range(0, len(ids), 900):
            chunk = ids[start:start + 900]
            marks = ",".join("?" * len(chunk))
            for r in self.q(
                f"SELECT v.document_id, v.snapshot_id, v.content_sha256, v.rows_json, "
                f"s.import_batch_id, s.member_id FROM document_versions v "
                f"JOIN source_snapshots s ON s.id = v.snapshot_id "
                f"WHERE v.document_id IN ({marks}) ORDER BY v.document_id, v.id",
                *chunk,
            ):
                out.setdefault(r["document_id"], []).append(r)
        return out

    def batch_version_lines(self, batch_id) -> int:
        """這一批自己擷取到的報表列總數(每張單在這一批的那一版)。
        等於封存記的這一批已核對明細數;同一張單在別批也有版本時,各批各算各的。"""
        total = 0
        for (rows_json,) in self.q(
            "SELECT v.rows_json FROM document_versions v "
            "JOIN source_snapshots s ON s.id = v.snapshot_id WHERE s.import_batch_id = ?",
            batch_id,
        ):
            total += len(json.loads(rows_json))
        return total

    def exceptions(self, batch_id):
        return {
            r["member_id"]: r for r in self.q(
                "SELECT e.member_id, e.snapshot_id, s.member_id AS snapshot_member_id, "
                "s.import_batch_id AS snapshot_batch, reason, list_amount_minor, "
                "detail_net_amount_minor, detail_raw_amount_minor, difference_minor, "
                "line_count, document_count, rows_json, validation_error "
                "FROM source_amount_exceptions e JOIN source_snapshots s ON s.id = e.snapshot_id "
                "WHERE e.import_batch_id = ?",
                batch_id,
            )
        }

    # ── 單筆核對 ──
    @staticmethod
    def check_snapshot(snap):
        if hashlib.sha256(snap["raw_json"].encode()).hexdigest() != snap["raw_sha256"]:
            raise ArchiveError(f"擷取快照 {snap['id']} 的全文雜湊不符")

    @staticmethod
    def check_row(item, row, doc):
        """一筆明細的每一個標準化欄位,都要跟報表列原文對得上(單頭也是)。"""
        n = doc["document_number_raw"]
        if not isinstance(row, list) or len(row) != ROW_WIDTH or not all(isinstance(c, str) for c in row):
            raise ArchiveError(f"單據 {n} 的報表列格式不對")
        if row_document_key(row) != (
            doc["store_name_raw"], doc["document_type_raw"], doc["document_number_raw"],
            doc["document_date"],
        ):
            raise ArchiveError(f"單據 {n} 的單頭(店別 / 單別 / 單號 / 日期)跟報表列不一致")
        same = (
            row[COL["seq"]] == item["report_sequence_raw"]
            and row[COL["code"]] == item["product_code_raw"]
            and row[COL["name"]] == item["product_name_raw"]
            and row[COL["qty"]] == item["quantity_raw"]
            and row[COL["points"]] == item["points_raw"]
            and row[COL["salesperson"]] == item["salesperson_raw"]
            and row[COL["customer"]] == item["customer_name_raw"]
            and row[COL["remarks"]] == item["remarks_raw"]
            and row[COL["promotion"]] == item["promotion_raw"]
            and money_minor(row[COL["amount"]]) == item["amount_minor"]
            and money_minor(row[COL["ex_tax"]]) == item["amount_ex_tax_minor"]
        )
        price = row[COL["price"]].strip()
        same = same and (
            item["unit_price_minor"] is None if price == ""
            else item["unit_price_minor"] == money_minor(price)
        )
        try:
            same = same and Decimal(item["quantity_decimal"]) == Decimal(
                row[COL["qty"]].strip().replace(",", "")
            )
        except InvalidOperation:
            same = False
        if not same:
            raise ArchiveError(f"單據 {n} 第 {item['item_ordinal']} 筆的欄位跟報表列原文不一致")

    @staticmethod
    def check_document(doc, items, versions):
        kind = doc["document_type_raw"]
        if kind not in NET_SIGN:
            raise ArchiveError(f"不認得的單別「{kind}」(單號 {doc['document_number_raw']}),不能匯入")
        for v in versions:
            if v["member_id"] != doc["member_id"]:
                raise ArchiveError(f"單據 {doc['document_number_raw']} 的版本掛在別的會員的快照上")
        if not items:
            raise ArchiveError(f"單據 {doc['document_number_raw']} 沒有任何明細")
        current = [v for v in versions if v["snapshot_id"] == doc["snapshot_id"]]
        if len(current) != 1:
            raise ArchiveError(f"單據 {doc['document_number_raw']} 找不到目前那一版的報表列")
        for v in versions:
            rows = json.loads(v["rows_json"])
            if document_content_sha256(rows) != v["content_sha256"]:
                raise ArchiveError(f"單據 {doc['document_number_raw']} 的版本內容雜湊不符")
        rows = json.loads(current[0]["rows_json"])
        if current[0]["content_sha256"] != doc["content_sha256"]:
            raise ArchiveError(f"單據 {doc['document_number_raw']} 的內容雜湊跟目前版本不一致")
        if len(rows) != len(items):
            raise ArchiveError(f"單據 {doc['document_number_raw']} 的明細筆數跟報表列不一致")
        if [i["item_ordinal"] for i in items] != list(range(1, len(items) + 1)):
            raise ArchiveError(f"單據 {doc['document_number_raw']} 的明細順序不連續")
        for item, row in zip(items, rows):
            if json.loads(item["source_row_json"]) != row:
                raise ArchiveError(f"單據 {doc['document_number_raw']} 的明細跟報表列原文不一致")
            Archive.check_row(item, row, doc)
            if item["net_sign"] != NET_SIGN[kind]:
                raise ArchiveError(f"單據 {doc['document_number_raw']} 的明細正負跟單別規則不符")
        if sum(i["amount_minor"] for i in items) != doc["report_amount_minor"]:
            raise ArchiveError(f"單據 {doc['document_number_raw']} 的明細金額合計跟單據不一致")

    @staticmethod
    def check_exception(e, member_id, batch_id):
        """待核紀錄:原始列也要能讀、單別要認得,金額 / 筆數 / 單據數 / 差額都重算。"""
        if e["snapshot_member_id"] != member_id or e["snapshot_batch"] != batch_id:
            raise ArchiveError("待核紀錄掛在別的會員或別一批的快照上")
        try:
            rows = json.loads(e["rows_json"])
        except ValueError:
            raise ArchiveError("待核紀錄的原始列讀不出來")
        if not isinstance(rows, list) or len(rows) != e["line_count"]:
            raise ArchiveError("待核紀錄的原始列筆數跟記錄不符")
        raw = net = 0
        docs = set()
        for row in rows:
            if not isinstance(row, list) or len(row) != ROW_WIDTH:
                raise ArchiveError("待核紀錄的原始列格式不對")
            kind = row[COL["type"]]
            if kind not in NET_SIGN:
                raise ArchiveError(f"待核紀錄有不認得的單別「{kind}」")
            amount = money_minor(row[COL["amount"]])
            raw += amount
            net += amount * NET_SIGN[kind]
            docs.add(row_document_key(row))
        if (raw, net, len(docs)) != (
            e["detail_raw_amount_minor"], e["detail_net_amount_minor"], e["document_count"]
        ):
            raise ArchiveError("待核紀錄的明細金額或單據數跟原始列重算的不一致")
        if e["difference_minor"] != e["detail_net_amount_minor"] - e["list_amount_minor"]:
            raise ArchiveError("待核紀錄的差額不等於「明細淨額 − 清單累計」")
        return rows

    def payload_fingerprints(self, info):
        """這一批的匯入內容檔(獨立於資料庫的另一份來源)裡,每一筆明細的指紋與合計。

        匯入內容檔是這一批「已核對的子集」:每一筆明細有標準化欄位與報表列原文。
        拿它跟資料庫裡這一批的版本逐筆比,可以抓到資料庫被改、或金額被放錯批的情況。
        """
        bad = f"批次 {info.archive_batch_id} 的匯入內容檔格式不對"
        try:
            data = json.loads((self.root / info.source_file).read_bytes())
        except ValueError:
            raise ArchiveError(bad)
        if not isinstance(data, dict):
            raise ArchiveError(bad)
        if data.get("source_system") != SOURCE_SYSTEM or data.get("report") != REPORT:
            raise ArchiveError(f"批次 {info.archive_batch_id} 的匯入內容檔來源不對")
        if data.get("schema_version") != NORMALIZED_SCHEMA_VERSION:
            raise ArchiveError(
                f"批次 {info.archive_batch_id} 的匯入內容檔格式版本是 {data.get('schema_version')},"
                f"只接受 {NORMALIZED_SCHEMA_VERSION}"
            )
        scope = data.get("scope")
        if not isinstance(scope, dict) or (
            scope.get("sale_date_from"), scope.get("sale_date_to")
        ) != (str(info.period_start), str(info.period_end)):
            raise ArchiveError(f"批次 {info.archive_batch_id} 的匯入內容檔期間跟封存記錄不一致")
        lines = data.get("lines")
        members = data.get("members")
        if not isinstance(lines, list) or not isinstance(members, list):
            raise ArchiveError(bad)
        if not all(isinstance(x, dict) for x in lines) or not all(isinstance(x, dict) for x in members):
            raise ArchiveError(bad)
        prints = Counter()
        for line in lines:
            row = line.get("source_row_raw")
            if not isinstance(row, list) or len(row) != ROW_WIDTH:
                raise ArchiveError(f"批次 {info.archive_batch_id} 的匯入內容檔有格式不對的列")
            prints[_line_print(line.get("source_member_id"), row)] += 1
        member_ids = Counter(m.get("source_member_id") for m in members)
        return prints, member_ids

    def expected_totals(self) -> dict:
        """manifest 的核對值(全部批次合計)。"""
        c, a = self.manifest.get("counts", {}), self.manifest.get("amounts", {})
        return {
            "members": c.get("members"),
            "snapshots": c.get("source_snapshots"),
            "documents": c.get("trusted_documents"),
            "items": c.get("trusted_items"),
            "raw_amount_minor": a.get("trusted_raw_amount_minor"),
            "net_amount_minor": a.get("trusted_net_amount_minor"),
            "exception_members": c.get("unresolved_source_member_count"),
            "exception_documents": c.get("exception_documents"),
            "exception_items": c.get("exception_items"),
        }

    def expected_captured(self) -> dict:
        """manifest 的「全部擷取」核對值(已核對 + 待核)。"""
        c, a = self.manifest.get("counts", {}), self.manifest.get("amounts", {})
        return {
            "documents": c.get("captured_documents"),
            "items": c.get("captured_items"),
            "raw_amount_minor": a.get("captured_raw_amount_minor"),
            "net_amount_minor": a.get("captured_net_amount_minor"),
        }

    @property
    def unresolved_exceptions(self) -> int:
        return int(self.metadata.get("unresolved_source_member_count", "0") or 0)


def _line_print(member_id, row) -> str:
    """一筆明細的指紋:哪位會員(精確編號)+ 報表列原文。"""
    return hashlib.sha256(compact([member_id, row]).encode()).hexdigest()


def version_prints(member_id, rows_json) -> list:
    return [_line_print(member_id, row) for row in json.loads(rows_json)]
