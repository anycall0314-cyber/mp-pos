"""測試用:造一份「舊 POS 十年封存」(跟真的封存同一個結構第 3 版),內容全是假的。

用法:
    b = ArchiveBuilder(tmp_dir)
    older = b.batch("2016-10-03", "2021-10-02")
    m = b.member("00          ", "王小明", "0912345678")
    b.period(older, m, [doc("湳雅店", "E11", "1060213005", "2017-02-13", [line(...), ...])])
    root = b.finish()          # 回傳封存根目錄(有 manifest.json)

金額用「元」寫,寫進封存時換成分。`list_amount` 不給就等於明細淨額(核對相符);
給一個不一樣的值就成為「來源差異」,放進 source_amount_exceptions 而不是已核對區。
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from apps.legacy.archive import compact, document_content_sha256
from apps.legacy.models import NET_SIGN

SCHEMA = Path(__file__).with_name("archive_schema_v3.sql")


@dataclass
class Line:
    code: str
    name: str
    qty: str
    price: str          # 原文;"" 代表空白單價
    amount: int         # 元,可以是負數
    salesperson: str = "S01"
    customer: str = ""
    remarks: str = ""
    promotion: str = ""


@dataclass
class Doc:
    store: str
    kind: str
    number: str
    date: str
    lines: list
    captured_at: str = "2026-10-03T10:00:00.000Z"


def line(code="P001", name="9H/IP15PM/透", qty="1", price="390", amount=390, **kw):
    return Line(code, name, qty, price, amount, **kw)


def doc(store="湳雅店", kind="E11", number="1060213005", date="2017-02-13", lines=None,
        captured_at="2026-10-03T10:00:00.000Z"):
    return Doc(store, kind, number, date, lines or [line()], captured_at)


@dataclass
class _Period:
    batch: int
    member: int
    docs: list
    list_amount: int | None
    captured_at: str


@dataclass
class _Member:
    source_id: str
    name: str
    phone: str
    captured_at: str = "2026-10-03T10:00:00.000Z"


@dataclass
class ArchiveBuilder:
    root: Path
    batches: list = field(default_factory=list)
    members: list = field(default_factory=list)
    periods: list = field(default_factory=list)
    net_sign: dict = field(default_factory=lambda: dict(NET_SIGN))

    def __post_init__(self):
        self.root = Path(self.root)

    def batch(self, start, end):
        self.batches.append((start, end))
        return len(self.batches)

    def member(self, source_id, name="測試會員", phone="0912000000",
               captured_at="2026-10-03T10:00:00.000Z"):
        self.members.append(_Member(source_id, name, phone, captured_at))
        return len(self.members)

    def period(self, batch, member, docs, list_amount=None, captured_at="2026-10-03T10:00:00.000Z"):
        self.periods.append(_Period(batch, member, docs, list_amount, captured_at))

    # ── 寫出 ──
    @staticmethod
    def row(seq, d: Doc, ln: Line):
        # 跟真實報表同一個欄序:序號、單別、單號、品號、品名、數量、單價、金額、金額(未稅)、
        # 點數、店別、日期、業務員、客戶名稱、備註、促銷方案
        return [
            f"{seq:02d}", d.kind, d.number, ln.code, ln.name, ln.qty, ln.price, str(ln.amount),
            str(ln.amount), "0", d.store, d.date.replace("-", ""), ln.salesperson, ln.customer,
            ln.remarks, ln.promotion,
        ]

    def finish(self, *, schema_version="3", tamper=None):
        db_path = self.root / "database" / "ored-history.sqlite"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        if db_path.exists():
            db_path.unlink()
        db = sqlite3.connect(db_path)
        db.executescript(SCHEMA.read_text())
        totals = dict(members=0, snapshots=0, documents=0, items=0, raw=0, net=0,
                      ex_members=0, ex_docs=0, ex_items=0)
        manifest_batches = []
        payload_lines: dict = {n: [] for n in range(1, len(self.batches) + 1)}
        for n, (start, end) in enumerate(self.batches, 1):
            payload = self.root / "import-payloads" / f"batch-{n}" / "normalized-records.json"
            reconciled = [p for p in self.periods if p.batch == n and not self._is_exception(p)]
            lines = sum(len(d.lines) for p in reconciled for d in p.docs)
            db.execute(
                "INSERT INTO import_batches(id,content_sha256,source_system,report,period_start,"
                "period_end,source_file,source_scope_json,member_count,line_count,imported_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (n, f"pending-{n}", "Ored legacy POS", "ST004", start, end,
                 str(payload.relative_to(self.root)), json.dumps({"store": "全公司"}),
                 len(reconciled), lines, "2026-10-03T19:00:00+00:00"),
            )
        for n, m in enumerate(self.members, 1):
            db.execute(
                "INSERT INTO legacy_members(id,source_system,source_member_id,source_member_id_raw,"
                "name_raw,phone_raw,last_captured_at) VALUES(?,?,?,?,?,?,?)",
                (n, "Ored legacy POS", m.source_id, m.source_id, m.name, m.phone, m.captured_at),
            )
        totals["members"] = len({p.member for p in self.periods})
        doc_ids: dict = {}
        for p in self.periods:
            raw_json = json.dumps({"member": p.member, "batch": p.batch, "docs": len(p.docs)})
            snap = db.execute(
                "INSERT INTO source_snapshots(import_batch_id,member_id,source_url,captured_at,"
                "raw_sha256,raw_json) VALUES(?,?,?,?,?,?)",
                (p.batch, p.member, f"http://example.invalid/{p.member}", p.captured_at,
                 hashlib.sha256(raw_json.encode()).hexdigest(), raw_json),
            ).lastrowid
            totals["snapshots"] += 1
            detail_net = sum(ln.amount * NET_SIGN.get(d.kind, 1) for d in p.docs for ln in d.lines)
            detail_raw = sum(ln.amount for d in p.docs for ln in d.lines)
            list_amount = detail_net if p.list_amount is None else p.list_amount
            db.execute(
                "INSERT INTO member_list_snapshots(import_batch_id,member_id,source_file,"
                "list_amount_raw,raw_json) VALUES(?,?,?,?,?)",
                (p.batch, p.member, f"list-{p.batch}.json", f"{list_amount}.00",
                 json.dumps({"member": p.member, "amount": list_amount})),
            )
            if self._is_exception(p):
                rows = [self.row(i + 1, d, ln) for d in p.docs for i, ln in enumerate(d.lines)]
                db.execute(
                    "INSERT INTO source_amount_exceptions(import_batch_id,member_id,snapshot_id,"
                    "reason,list_amount_minor,detail_net_amount_minor,detail_raw_amount_minor,"
                    "difference_minor,line_count,document_count,rows_json,validation_error) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (p.batch, p.member, snap, "source_member_amount_mismatch", list_amount * 100,
                     detail_net * 100, detail_raw * 100, (detail_net - list_amount) * 100,
                     len(rows), len(p.docs), compact(rows),
                     f"Member amount mismatch: detail {detail_net} vs list {list_amount}"),
                )
                totals["ex_members"] += 1
                totals["ex_docs"] += len(p.docs)
                totals["ex_items"] += len(rows)
                totals["ex_raw"] = totals.get("ex_raw", 0) + detail_raw * 100
                totals["ex_net"] = totals.get("ex_net", 0) + detail_net * 100
                continue
            for d in p.docs:
                rows = [self.row(i + 1, d, ln) for i, ln in enumerate(d.lines)]
                source_id = self.members[p.member - 1].source_id
                payload_lines[p.batch] += [
                    {"source_member_id": source_id, "source_row_raw": r} for r in rows
                ]
                content = document_content_sha256(rows)
                key = (p.member, d.store, d.kind, d.number, d.date)
                amount = sum(ln.amount for ln in d.lines) * 100
                existing = doc_ids.get(key)
                if existing is None:
                    doc_id = db.execute(
                        "INSERT INTO legacy_documents(member_id,store_name_raw,document_type_raw,"
                        "document_number_raw,document_date,content_sha256,snapshot_id,"
                        "report_amount_minor,last_captured_at) VALUES(?,?,?,?,?,?,?,?,?)",
                        (p.member, d.store, d.kind, d.number, d.date, content, snap, amount,
                         d.captured_at),
                    ).lastrowid
                    doc_ids[key] = (doc_id, d.captured_at)
                    totals["documents"] += 1
                else:
                    doc_id, seen = existing
                db.execute(
                    "INSERT INTO document_versions(document_id,snapshot_id,content_sha256,rows_json) "
                    "VALUES(?,?,?,?)",
                    (doc_id, snap, content, compact(rows)),
                )
                if existing is not None:
                    if d.captured_at < existing[1]:
                        continue
                    db.execute("DELETE FROM legacy_items WHERE document_id=?", (doc_id,))
                    db.execute(
                        "UPDATE legacy_documents SET content_sha256=?,snapshot_id=?,"
                        "report_amount_minor=?,last_captured_at=? WHERE id=?",
                        (content, snap, amount, d.captured_at, doc_id),
                    )
                    doc_ids[key] = (doc_id, d.captured_at)
                for i, (ln, r) in enumerate(zip(d.lines, rows), 1):
                    db.execute(
                        "INSERT INTO legacy_items(document_id,item_ordinal,report_sequence_raw,"
                        "product_code_raw,product_name_raw,quantity_decimal,quantity_raw,"
                        "unit_price_minor,amount_minor,amount_ex_tax_minor,points_raw,"
                        "salesperson_raw,customer_name_raw,remarks_raw,promotion_raw,"
                        "source_row_json,net_sign) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (doc_id, i, r[0], ln.code, ln.name, ln.qty, ln.qty,
                         int(ln.price) * 100 if ln.price else None, ln.amount * 100,
                         ln.amount * 100, "0", ln.salesperson, ln.customer, ln.remarks,
                         ln.promotion, compact(r), self.net_sign.get(d.kind, 1)),
                    )
        # 已核對區的總數 / 金額(換版過的單只算目前那一版)
        # 每一批的匯入內容檔:已核對的會員與明細(跟真的封存同一個形狀)
        for n, (start, end) in enumerate(self.batches, 1):
            payload = self.root / "import-payloads" / f"batch-{n}" / "normalized-records.json"
            payload.parent.mkdir(parents=True, exist_ok=True)
            reconciled = [p for p in self.periods if p.batch == n and not self._is_exception(p)]
            payload.write_text(json.dumps({
                "schema_version": 2, "source_system": "Ored legacy POS", "report": "ST004",
                "scope": {"sale_date_from": start, "sale_date_to": end},
                "members": [{"source_member_id": self.members[p.member - 1].source_id,
                             "captured_at": p.captured_at} for p in reconciled],
                "lines": payload_lines[n],
            }, ensure_ascii=False))
            digest = hashlib.sha256(payload.read_bytes()).hexdigest()
            db.execute("UPDATE import_batches SET content_sha256=? WHERE id=?", (digest, n))
            manifest_batches.append({
                "import_batch_id": n, "import_payload_file": str(payload.relative_to(self.root)),
                "import_payload_sha256": digest, "period": [start, end],
            })
        cur = db.execute(
            "SELECT count(*), coalesce(sum(amount_minor),0), coalesce(sum(amount_minor*net_sign),0) "
            "FROM legacy_items"
        ).fetchone()
        totals["items"], totals["raw"], totals["net"] = cur
        meta = {
            "source_system": "Ored legacy POS", "archive_status": "test",
            "capture_complete": "true",
            "covered_period_start": self.batches[0][0], "covered_period_end": self.batches[-1][1],
            "archive_schema_version": schema_version, "normalized_schema_version": "2",
            "net_sign_rule": json.dumps(NET_SIGN, separators=(",", ":")),
            "unresolved_source_member_count": str(totals["ex_members"]),
        }
        db.executemany("INSERT INTO archive_metadata(key,value) VALUES(?,?)", meta.items())
        if tamper:
            tamper(db)
        db.commit()
        db.close()
        manifest = {
            "database_file": "database/ored-history.sqlite",
            "database_sha256": hashlib.sha256(db_path.read_bytes()).hexdigest(),
            "source_archives": manifest_batches,
            "counts": {
                "members": totals["members"], "source_snapshots": totals["snapshots"],
                "trusted_documents": totals["documents"], "trusted_items": totals["items"],
                "unresolved_source_member_count": totals["ex_members"],
                "exception_documents": totals["ex_docs"], "exception_items": totals["ex_items"],
                "captured_documents": totals["documents"] + totals["ex_docs"],
                "captured_items": totals["items"] + totals["ex_items"],
            },
            "amounts": {
                "trusted_raw_amount_minor": totals["raw"],
                "trusted_net_amount_minor": totals["net"],
                "captured_raw_amount_minor": totals["raw"] + totals.get("ex_raw", 0),
                "captured_net_amount_minor": totals["net"] + totals.get("ex_net", 0),
            },
        }
        (self.root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False))
        self.manifest = manifest
        return self.root

    def _is_exception(self, p):
        if p.list_amount is None:
            return False
        net = sum(ln.amount * NET_SIGN.get(d.kind, 1) for d in p.docs for ln in d.lines)
        return p.list_amount != net
