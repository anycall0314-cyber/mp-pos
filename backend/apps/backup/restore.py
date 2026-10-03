"""把公司備份還原回去。

流程:**開包驗證 → 預檢(不改任何正式資料)→ 管理員確認 → 上維護鎖 →
安全備份 → 在一個交易裡整批取代 → 驗證 → 提交**。

幾個不能退讓的原則:

- 還原單位是整家公司(全部門市一起),不做單店回溯 —— 商品、成本、調撥是跨店
  共用的,只回溯一家店會讓帳對不起來。
- **照搬帳本,不重播交易**:備份裡的庫存餘額、異動、付款、成本快照原樣寫回,
  不呼叫進貨 / 銷貨的過帳程式。重播會讓庫存、現金、發票再發生一次。
- **不採信檔案裡的數字 id**:每一列都給新的主鍵,外鍵照對照表換過去;寫到
  哪一家公司由「誰在還原」決定,不看檔案自己怎麼說。
- 資料取代與「工作標成完成」在同一個資料庫交易裡:看到「已完成」就表示資料
  整批換好了;沒看到就表示一筆都沒動。不會有半套。
- 只能往前的號碼(客戶 / 單據流水、發票字軌)取「現況」與「備份」較大者。
"""
import hashlib
import json
import os
import stat
import time
import uuid
import zipfile
from datetime import datetime, timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.base import File
from django.core.files.storage import default_storage
from django.db import OperationalError, connection, models, transaction
from django.db.models import Count, Max
from django.utils import timezone

from . import container, jobs, keys, registry
from .export import dump_json, schema_fingerprint, schema_state
from .models import BackupJob, RestoreJob, TenantMaintenance, audit
from .registry import (
    DOC_NUMBERED,
    FILE_FIELDS,
    FORMAT_VERSION,
    HIGH_WATER,
    TENANT_HIGH_WATER,
    label_of,
)

PRECHECK_TTL = timedelta(minutes=30)
RESTORE_LEASE = timedelta(minutes=30)
CLAIM_GRACE = timedelta(minutes=2)   # worker 接手之後,多久內不判定它「沒在跑」
LOCK_TIMEOUT_SECONDS = 60   # 取代資料時,等別的交易放手最多幾秒;等不到就不還原
CLEANUP_LOCK_TIMEOUT_SECONDS = 10   # 清舊附件時等別的交易放手最多幾秒;等不到就先不清
MAX_ROW_BYTES = 8 * 1024 * 1024     # 備份裡單一列的大小上限
# 會整個讀進記憶體的東西要另外設上限(整包的上限是幾 GB,不能拿來當這幾樣的上限):
MAX_MANIFEST_BYTES = 64 * 1024 * 1024       # manifest.json(每個附件一筆,十萬個約 20MB)
MAX_ACCOUNTS_BYTES = 8 * 1024 * 1024        # accounts.json
MAX_ZIP_DIRECTORY_BYTES = 64 * 1024 * 1024  # 壓縮檔的目錄(zipfile 開檔時整個讀進來)
MAX_ZIP_ENTRIES = 300_000
BATCH = 1000


class RestoreError(Exception):
    """還原無法進行(原因會顯示給管理員)。資料沒有被改動。"""


# ─────────────────────────── 開包與驗證 ───────────────────────────
class Package:
    """解開並驗證過結構的備份。用完要 close()(會刪掉暫存的明文)。"""

    def __init__(self, enc_path, secret, *, plain_path=None):
        """`plain_path` 有給 = 直接開一份已經解密的 zip(不會刪它);備份剛做完時
        用同一套檢查驗自己,不必再解密一次。"""
        self._owns_plain = plain_path is None
        if plain_path is not None:
            self.plain = plain_path
        else:
            root = jobs.backup_root()
            self.plain = root / "staging" / f"{os.urandom(8).hex()}.zip"
            try:
                container.decrypt_file(
                    enc_path, self.plain, secret, max_bytes=settings.BACKUP_MAX_UNPACKED_BYTES
                )
            except container.ContainerError as exc:
                raise RestoreError(str(exc))
        try:
            _check_zip_directory(self.plain)
            self.zf = zipfile.ZipFile(self.plain)
            self._check_structure()
            self.manifest = json.loads(self._read_small("manifest.json", MAX_MANIFEST_BYTES))
            self.accounts = json.loads(self._read_small("accounts.json", MAX_ACCOUNTS_BYTES))
            self._check_manifest()
        except RestoreError:
            self.close()
            raise
        except Exception as exc:  # noqa: BLE001 - 內容再怪都要落成「拒絕」,不能是 500
            self.close()
            raise RestoreError(f"備份檔內容無法讀取:{type(exc).__name__}")

    def close(self):
        zf = getattr(self, "zf", None)
        if zf is not None:
            zf.close()
        if not self._owns_plain:
            return
        try:
            os.remove(self.plain)
        except OSError:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _read_small(self, name, limit) -> bytes:
        """整個讀進記憶體之前先看它宣告的大小。zipfile 最多只會讀到宣告的大小,
        所以這個上限擋得住「壓縮後很小、解開幾 GB」的檔。"""
        if self.zf.getinfo(name).file_size > limit:
            raise RestoreError(f"備份檔內容異常({name} 過大)")
        return self.zf.read(name)

    def _check_structure(self):
        """只接受我們自己會產生的那幾種檔名。不照檔名解壓到磁碟,所以路徑穿越
        本來就沒有落點;這裡仍然把不認得的內容整包拒絕。"""
        allowed_tables = {label_of(m) for m in registry.company_models()}
        total, seen = 0, set()
        if len(self.zf.infolist()) > MAX_ZIP_ENTRIES:
            raise RestoreError("備份檔內容異常(項目過多)")
        for info in self.zf.infolist():
            name = info.filename
            if name in seen:
                raise RestoreError("備份檔內容異常(重複的項目)")
            seen.add(name)
            if stat.S_ISLNK(info.external_attr >> 16):
                raise RestoreError("備份檔內容異常(含有連結)")
            if name.startswith(("/", "\\")) or ".." in name.split("/") or "\\" in name:
                raise RestoreError("備份檔內容異常(不合法的路徑)")
            if name in ("manifest.json", "accounts.json"):
                pass
            elif name.startswith("data/") and name.endswith(".jsonl"):
                if name[5:-6] not in allowed_tables:
                    raise RestoreError(f"備份檔含有這個版本不認得的資料:{name[5:-6]}")
            elif name.startswith("files/") and name[6:].isdigit():
                pass
            else:
                raise RestoreError(f"備份檔含有不允許的內容:{name}")
            total += info.file_size
            if total > settings.BACKUP_MAX_UNPACKED_BYTES:
                raise RestoreError("備份檔解開後超過允許的大小")
        if "manifest.json" not in seen or "accounts.json" not in seen:
            raise RestoreError("備份檔不完整(缺少清單)")

    def _check_manifest(self):
        """清單與帳號對照的每一個欄位都要是預期的形狀。

        後面的程式會直接拿這些值去用(建公司、對門市、開附件),形狀不對的檔案
        要在這裡就拒絕,不能等到已經鎖了公司、做完安全備份才出錯。
        """
        m = self.manifest
        _need(isinstance(m, dict), "清單")
        if m.get("format") != FORMAT_VERSION:
            raise RestoreError(f"不支援這個備份格式版本({m.get('format')})")
        current = schema_state()
        theirs = m.get("schema")
        _need(
            isinstance(theirs, dict) and all(
                isinstance(k, str) and isinstance(v, list)
                and all(isinstance(x, str) for x in v)
                for k, v in theirs.items()
            ),
            "版本資訊",
        )
        # 指紋要真的是從那份版本清單算出來的,而且整份清單要跟這台系統一模一樣
        if (
            m.get("schema_fingerprint") != schema_fingerprint(theirs)
            or theirs != current
        ):
            diff = sorted(
                app for app in set(current) | set(theirs)
                if current.get(app) != theirs.get(app)
            )
            raise RestoreError(
                "這份備份是在不同版本的系統產生的,這個版本無法還原"
                f"(資料結構不同的部分:{'、'.join(diff[:8]) or '版本指紋'})。"
                "請用產生備份時的系統版本還原,或聯絡維護人員。"
            )
        kinds = {label: e.kind for label, e in registry.REGISTRY.items()}
        if m.get("classification") != kinds:
            raise RestoreError("備份檔的資料分類跟這個版本不一致,無法還原")

        labels = {label_of(x) for x in registry.company_models()}
        tables = m.get("tables")
        _need(
            isinstance(tables, dict) and set(tables) == labels
            and all(_is_int(v) and v >= 0 for v in tables.values()),
            "各表筆數",
        )
        names = set(self.zf.namelist())
        for label in labels:
            if f"data/{label}.jsonl" not in names:
                raise RestoreError(f"備份檔不完整(缺少 {label})")

        from apps.tenants.models import Tenant

        company = m.get("company")
        _need(isinstance(company, dict), "公司")
        try:
            uuid.UUID(str(company.get("uuid")))
        except ValueError:
            raise RestoreError("備份檔的清單內容不正確(公司識別碼)")
        _need(isinstance(company.get("name"), str) and company["name"].strip(), "公司名稱")
        _need(isinstance(company.get("code"), str), "公司代碼")
        settings_ = company.get("settings")
        _need(
            isinstance(settings_, dict) and set(settings_) == set(registry.TENANT_SETTINGS),
            "公司設定",
        )
        for key, value in settings_.items():
            try:
                Tenant._meta.get_field(key).clean(value, None)
            except Exception:  # noqa: BLE001
                raise RestoreError(f"備份檔的清單內容不正確(公司設定 {key})")
        counters = company.get("counters")
        _need(
            isinstance(counters, dict) and set(counters) == set(TENANT_HIGH_WATER)
            and all(_is_int(v) and 0 < v < 2**31 for v in counters.values()),
            "公司流水號",
        )

        try:
            datetime.fromisoformat(m.get("snapshot_at"))
        except (TypeError, ValueError):
            raise RestoreError("備份檔的清單內容不正確(備份時間)")
        warehouses = m.get("warehouses")
        _need(
            isinstance(warehouses, list) and all(
                isinstance(w, dict) and isinstance(w.get("code"), str)
                and isinstance(w.get("name"), str) for w in warehouses
            ),
            "門市清單",
        )

        atts = m.get("attachments")
        _need(isinstance(atts, list), "附件清單")
        seen = set()
        for i, att in enumerate(atts):
            _need(
                isinstance(att, dict) and att.get("index") == i and _is_int(att.get("pk"))
                and att.get("field") in FILE_FIELDS.get(att.get("table"), [])
                and isinstance(att.get("name"), str)
                and _is_int(att.get("size")) and att["size"] >= 0
                and isinstance(att.get("sha256"), str) and len(att["sha256"]) == 64,
                "附件清單",
            )
            key = (att["table"], att["pk"], att["field"])
            _need(key not in seen, "附件清單重複")
            seen.add(key)
        # 附件檔要跟清單一對一:多一個、少一個都不收
        if {n for n in names if n.startswith("files/")} != {f"files/{i}" for i in range(len(atts))}:
            raise RestoreError("備份檔的附件跟清單對不起來")

        accounts = self.accounts
        _need(isinstance(accounts, list), "帳號對照")
        ids, uuids = set(), set()
        for acc in accounts:
            try:
                key = str(uuid.UUID(acc["uuid"])) if isinstance(acc, dict) else None
            except (KeyError, TypeError, ValueError, AttributeError):
                key = None
            # 識別碼要是標準寫法、而且不重複:對帳號就靠它
            _need(key is not None and key == acc["uuid"] and key not in uuids, "帳號對照")
            uuids.add(key)
            _need(
                isinstance(acc, dict) and _is_int(acc.get("id")) and acc["id"] not in ids
                and isinstance(acc.get("username"), str) and 0 < len(acc["username"]) <= 150
                and isinstance(acc.get("first_name"), str) and len(acc["first_name"]) <= 150
                and isinstance(acc.get("last_name"), str) and len(acc["last_name"]) <= 150
                and isinstance(acc.get("is_active"), bool)
                and isinstance(acc.get("in_company"), bool)
                and acc.get("role") in ("tenant_admin", "tenant_user")
                and (acc.get("default_warehouse_id") is None
                     or _is_int(acc["default_warehouse_id"]))
                and isinstance(acc.get("is_warehouse_locked"), bool),
                "帳號對照",
            )
            ids.add(acc["id"])
        _need(m.get("accounts") == len(accounts), "帳號數")

    def rows(self, label):
        with self.zf.open(f"data/{label}.jsonl") as f:
            while True:
                # 一次最多讀這麼長:一列塞幾 GB 的檔案不能把記憶體吃光
                line = f.readline(MAX_ROW_BYTES + 1)
                if not line:
                    break
                if len(line) > MAX_ROW_BYTES:
                    raise RestoreError(f"備份檔內容異常(單筆資料過大):{label}")
                if line.strip():
                    try:
                        row = json.loads(line)
                    except ValueError:
                        raise RestoreError(f"備份檔內容無法讀取:{label}")
                    if not isinstance(row, dict):
                        raise RestoreError(f"備份檔內容異常:{label}")
                    yield row

    def open_file(self, index):
        return self.zf.open(f"files/{index}")


def _check_zip_directory(path):
    """打開壓縮檔之前,先看它的目錄有多大、有幾個項目。

    zipfile 一開檔就會把整份目錄讀進記憶體;目錄大小寫在檔尾。這裡用的是 zipfile
    自己找檔尾的那一支(兩邊看到的一定一樣),超過上限就不開。
    """
    find_end = getattr(zipfile, "_EndRecData", None)
    if find_end is None:        # 這個 Python 版本沒有那支:退回開檔後再數項目
        return
    with open(path, "rb") as f:
        end = find_end(f)
    if not end:
        raise RestoreError("備份檔內容無法讀取:BadZipFile")
    if end[5] > MAX_ZIP_DIRECTORY_BYTES or end[4] > MAX_ZIP_ENTRIES:
        raise RestoreError("備份檔內容異常(項目過多)")


def _need(ok, what):
    if not ok:
        raise RestoreError(f"備份檔的清單內容不正確({what})")


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _safe_file_name(name) -> bool:
    """附件在儲存區裡的相對路徑。絕對路徑、往上跳、反斜線、控制字元都不收。"""
    if not isinstance(name, str) or not name or len(name) > 400:
        return False
    if name.startswith("/") or "\\" in name or any(ord(c) < 32 for c in name):
        return False
    parts = name.split("/")
    return all(part not in ("", ".", "..") for part in parts)


def _field_problem(f, raw):
    """這個值能不能原樣寫進這個欄位。可以回 None,不行回原因。"""
    try:
        value = f.to_python(raw)
    except Exception:  # noqa: BLE001
        return "格式不對"
    if value is None:
        return None if f.null else "不可以是空的"
    if isinstance(f, (models.CharField, models.TextField)) and not isinstance(raw, str):
        return "格式不對"
    if getattr(f, "max_length", None) and isinstance(value, str) and len(value) > f.max_length:
        return "太長"
    if f.choices and value != "" and value not in {k for k, _ in f.flatchoices}:
        return "不在允許的選項裡"
    return None


def _unique_sets(model):
    """這張表「不可以重複」的欄位組合(只收無條件的;有條件的交給資料庫在交易裡擋)。"""
    out = []
    for f in model._meta.concrete_fields:
        if f.unique and not f.primary_key:
            out.append((f.attname,))
    by_name = {f.name: f for f in model._meta.concrete_fields}
    groups = [tuple(g) for g in model._meta.unique_together]
    groups += [
        tuple(c.fields) for c in model._meta.constraints
        if isinstance(c, models.UniqueConstraint) and c.fields and c.condition is None
    ]
    for group in groups:
        # 同一家公司裡比,所以公司那一欄拿掉
        cols = tuple(by_name[n].attname for n in group if n != "tenant" and n in by_name)
        if cols:
            out.append(cols)
    return out


def _non_relational(model):
    """逐列核對用的欄位:扣掉主鍵、外鍵、公司、檔案路徑(這些還原後會換新值)。"""
    files = set(FILE_FIELDS.get(label_of(model), []))
    return [
        f for f in model._meta.concrete_fields
        if not f.primary_key and f.name != "tenant" and f.name not in files
        and not isinstance(f, (models.ForeignKey, models.OneToOneField))
    ]


def _row_digest(model, row) -> bytes:
    """一列資料的指紋。備份裡的列與資料庫讀回來的列用同一種算法,才比得起來。"""
    values = {f.attname: f.to_python(row[f.attname]) for f in _non_relational(model)}
    return hashlib.sha256(dump_json(values)).digest()


def _table_digest(digests) -> str:
    h = hashlib.sha256()
    for d in sorted(digests):
        h.update(d)
    return h.hexdigest()


def target_fingerprint(tenant) -> str:
    """目標公司目前資料的指紋。預檢與確認之間有人動過資料,指紋就會變。"""
    parts = []
    for model in registry.ordered_company_models():
        qs = model._base_manager.filter(tenant=tenant)
        agg = qs.aggregate(n=Count("pk"), top=Max("pk"))
        stamp = ""
        if any(f.name == "updated_at" for f in model._meta.concrete_fields):
            stamp = str(qs.aggregate(t=Max("updated_at"))["t"] or "")
        parts.append(f"{label_of(model)}:{agg['n']}:{agg['top']}:{stamp}")
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def _account_map(tenant, accounts):
    """備份裡的帳號 id → 這台伺服器上的帳號 id。對不回來的回 None。

    只認「現在還在這家公司、而且帳號識別碼相同」的帳號。不看帳號名稱:備份之後
    原本的人可能改了名、那個名稱又被另一個人拿去用,照名稱對會把舊單據的經手人
    掛到別人頭上。別家公司的帳號、已經離開這家公司的帳號,一律對不回來(留空)。
    """
    from apps.tenants.models import UserProfile

    mine = {
        str(key): user_id for key, user_id in
        UserProfile.objects.filter(tenant=tenant).values_list("account_uuid", "user_id")
    }
    mapping, unmapped = {}, []
    for acc in accounts:
        target = mine.get(acc["uuid"])
        mapping[acc["id"]] = target
        if target is None:
            unmapped.append(acc["username"])
    return mapping, unmapped


def validate(tenant, pkg, mode) -> dict:
    """預檢。只讀不寫。回傳報告;`problems` 非空就不能還原。"""
    m = pkg.manifest
    problems, warnings = [], []
    if mode == RestoreJob.Mode.ROLLBACK and m["company"]["uuid"] != str(tenant.backup_uuid):
        problems.append(
            f"這份備份是「{m['company']['name']}」的,不是這家公司的,不能用來回溯"
        )

    order = registry.ordered_company_models()
    known_pks: dict[str, set] = {}
    counts: dict[str, int] = {}
    User = get_user_model()
    account_ids = {a["id"] for a in pkg.accounts}
    listed_files = {(a["table"], a["pk"], a["field"]): a for a in m["attachments"]}
    used_files = set()

    # 第一輪:欄位齊不齊、每個值寫不寫得進去、筆數對不對、收集每張表有哪些主鍵
    for model in order:
        label = label_of(model)
        fields = [f for f in model._meta.concrete_fields if f.name != "tenant"]
        expected = {f.attname for f in fields}
        file_cols = set(FILE_FIELDS.get(label, []))
        uniques = [(cols, set()) for cols in _unique_sets(model)]
        pks, n = set(), 0
        for row in pkg.rows(label):
            n += 1
            if set(row) != expected:
                problems.append(f"{label}:欄位跟這個版本不一致")
                break
            if not _is_int(row["id"]) or row["id"] in pks:
                problems.append(f"{label}:備份裡有重複或不合法的資料編號")
                break
            pks.add(row["id"])
            bad = None
            for f in fields:
                raw = row[f.attname]
                if f.primary_key:
                    continue
                if isinstance(f, (models.ForeignKey, models.OneToOneField)):
                    if raw is None:
                        # 經手帳號那一類欄位:帳號對不回來時本來就會留空
                        if not f.null and f.related_model is not User:
                            bad = f"{f.name} 不可以是空的"
                    elif not _is_int(raw):
                        bad = f"{f.name} 格式不對"
                elif f.name in file_cols:
                    if raw in ("", None):
                        if raw is None and not f.null:
                            bad = f"{f.name} 不可以是空的"
                    elif not _safe_file_name(raw) or len(raw) > (f.max_length or 100):
                        bad = f"{f.name} 的檔案路徑不合法"
                    elif listed_files.get((label, row["id"], f.name), {}).get("name") != raw:
                        bad = f"{f.name} 的附件不在備份清單裡"
                    else:
                        used_files.add((label, row["id"], f.name))
                else:
                    why = _field_problem(f, raw)
                    if why:
                        bad = f"{f.name} {why}"
                if bad:
                    break
            if not bad:
                for cols, seen in uniques:
                    try:
                        key = tuple(row[c] for c in cols)
                        if None in key:
                            continue        # 空值不算重複(資料庫也是這樣算)
                        if key in seen:
                            bad = "、".join(cols) + " 重複"
                            break
                        seen.add(key)
                    except TypeError:
                        bad = "、".join(cols) + " 格式不對"
                        break
            if bad:
                problems.append(f"{label}:有一筆資料的內容不合法({bad})")
                break
        known_pks[label] = pks
        counts[label] = n
        if n != m["tables"].get(label):
            problems.append(f"{label}:筆數跟備份清單不符(檔案可能被改過)")
    if not problems and used_files != set(listed_files):
        problems.append("備份清單裡有附件沒有對應的資料")

    # 第二輪:每一個外鍵都要指到備份裡真的有的那一列
    if not problems:
        for model in order:
            label = label_of(model)
            fks = [
                (f.attname, label_of(f.related_model), f.related_model is User)
                for f in model._meta.concrete_fields
                if isinstance(f, (models.ForeignKey, models.OneToOneField))
                and f.name != "tenant"
            ]
            bad = False
            for row in pkg.rows(label):
                for attname, target, is_user in fks:
                    value = row[attname]
                    if value is None:
                        continue
                    ok = value in account_ids if is_user else value in known_pks.get(target, ())
                    if not ok:
                        problems.append(f"{label}:有資料指到備份裡不存在的 {target}")
                        bad = True
                        break
                if bad:
                    break

    # 附件:清單上每一個都要在,大小與雜湊要對
    for att in m.get("attachments", []):
        try:
            digest, size = hashlib.sha256(), 0
            with pkg.open_file(att["index"]) as f:
                for block in iter(lambda: f.read(1024 * 1024), b""):
                    digest.update(block)
                    size += len(block)
            if size != att["size"] or digest.hexdigest() != att["sha256"]:
                problems.append(f"附件內容不符:{att['name']}")
        except KeyError:
            problems.append(f"附件遺失:{att['name']}")

    mapping, unmapped = _account_map(tenant, pkg.accounts)
    current = _current_state(tenant)
    if mode == RestoreJob.Mode.ROLLBACK:
        if unmapped:
            warnings.append(
                "備份裡這些帳號現在不在這家公司,相關單據的經手帳號會留空:"
                + "、".join(sorted(set(unmapped))[:10])
            )
        backup_codes = {w["code"] for w in m["warehouses"]}
        lost = [
            f"{p['username']}({p['warehouse_code']})" for p in current["profiles"]
            if p["warehouse_code"] and p["warehouse_code"] not in backup_codes
        ]
        if lost:
            warnings.append(
                "這些帳號目前綁的門市不在備份裡,還原後會沒有門市可用,要管理員重新指定:"
                + "、".join(lost[:10])
            )
        for prefix, seq in current["doc_seq"].items():
            if seq:
                warnings.append(f"{prefix} 單號已經用到 {seq:06d},還原後的新單會接著往下編,不重用")
        if current["invoice_tracks"]:
            warnings.append("發票字軌的下一張號碼只會往前:取現在與備份較大的那個")

    return {
        "ok": not problems,
        "problems": problems,
        "warnings": warnings,
        "source": {
            "company": m["company"]["name"],
            "company_code": m["company"]["code"],
            "company_uuid": m["company"]["uuid"],
            "snapshot_at": m["snapshot_at"],
            "warehouses": [w["name"] for w in m["warehouses"]],
            "rows": sum(counts.values()),
            "tables": counts,
            "attachments": len(m.get("attachments", [])),
            "accounts": len(pkg.accounts),
        },
        "target": {
            "company": tenant.name,
            "rows": sum(current["counts"].values()),
            "tables": current["counts"],
            "warehouses": current["warehouses"],
        },
    }


def _current_state(tenant) -> dict:
    """目標公司現況裡,還原時要保留 / 對照的東西。"""
    from apps.inventory.models import Warehouse
    from apps.tenants.models import InvoiceTrack, UserProfile

    counts = {
        label_of(m): m._base_manager.filter(tenant=tenant).count()
        for m in registry.ordered_company_models()
    }
    doc_seq = {}
    for label, prefix in DOC_NUMBERED.items():
        from django.apps import apps

        doc_seq[prefix] = _max_doc_seq(apps.get_model(label), tenant)
    return {
        "counts": counts,
        "warehouses": list(
            Warehouse.objects.filter(tenant=tenant).order_by("id").values_list("name", flat=True)
        ),
        "profiles": [
            {"user_id": uid, "username": name, "warehouse_code": code or ""}
            for uid, name, code in UserProfile.objects.filter(tenant=tenant).values_list(
                "user_id", "user__username", "default_warehouse__code"
            )
        ],
        "doc_seq": doc_seq,
        "invoice_tracks": InvoiceTrack.objects.filter(tenant=tenant).count(),
    }


def _max_doc_seq(model, tenant) -> int:
    top = 0
    for no in model._base_manager.filter(tenant=tenant).values_list("no", flat=True):
        try:
            top = max(top, int(str(no).split("-")[-1]))
        except (ValueError, IndexError):
            continue
    return top


# ─────────────────────────── 預檢 / 確認 ───────────────────────────
def stage_upload(tenant, uploaded, user, credential="", mode=RestoreJob.Mode.ROLLBACK):
    """收下上傳的備份檔、放進隔離的暫存區、跑預檢。回傳 RestoreJob。

    預檢不改任何正式資料;通不過的檔案會留下一筆「預檢未通過」的紀錄並刪掉暫存檔。
    """
    root = jobs.backup_root()
    size = getattr(uploaded, "size", None)
    if size is not None and size > settings.BACKUP_MAX_UPLOAD_BYTES:
        raise RestoreError("檔案超過可上傳的大小上限")
    name = f"staging/{os.urandom(12).hex()}.upload"
    path = root / name
    digest, written = hashlib.sha256(), 0
    requester = user if getattr(user, "is_authenticated", False) else None
    try:
        with open(path, "wb") as out:
            for block in uploaded.chunks():
                written += len(block)
                if written > settings.BACKUP_MAX_UPLOAD_BYTES:
                    raise RestoreError("檔案超過可上傳的大小上限")
                out.write(block)
                digest.update(block)
        os.chmod(path, 0o600)
    except RestoreError:
        _remove(path)
        raise
    except Exception as exc:  # noqa: BLE001
        # 磁碟滿了、上傳到一半斷線:半個檔不能留在暫存區,也要留一筆「沒收成」的紀錄
        _remove(path)
        job = RestoreJob.objects.create(
            tenant=tenant, mode=mode, staged_file="", file_sha256="",
            requested_by=requester, status=RestoreJob.Status.REJECTED,
            target_fingerprint="",
            report={
                "ok": False, "warnings": [],
                "problems": [f"檔案沒有完整收到,請再上傳一次({type(exc).__name__})"],
            },
        )
        audit(tenant, user, "restore.prechecked", ok=False, restore_job=job,
              problems=job.report["problems"])
        return job

    job = RestoreJob(
        tenant=tenant, mode=mode, staged_file=name, file_sha256=digest.hexdigest(),
        requested_by=requester,
        expires_at=timezone.now() + PRECHECK_TTL,
    )
    try:
        current = keys.get_secret(tenant)
        secret = keys.parse_secret(credential) if credential else current
        if secret is None:
            raise RestoreError("請輸入這份備份的復原憑證")
        with Package(path, secret) as pkg:
            job.report = validate(tenant, pkg, mode)
            usable = job.report["ok"]
        if usable and secret != current:
            if current is None:
                # 伺服器上沒有(或讀不出)憑證:這份檔確定是這家公司的、用輸入的憑證
                # 打得開,才把它登記起來。伺服器上留有舊憑證的指紋時,輸入的要是
                # 同一組(register_key 會擋),不會被另一組悄悄換掉。
                keys.register_key(tenant, credential, user)
            else:
                # 這份備份是用「另一組」憑證加密的。**不能**因此把伺服器上的憑證換掉:
                # 那會讓之後的備份改用這一組加密,管理員手上抄的那組就打不開了
                # (上傳別家公司的檔 + 它的憑證也會走到這裡之前就被擋掉)。
                # 改成把暫存檔用伺服器現有的憑證重新封裝,後面的執行照常用伺服器那組。
                rewrapped = root / (name + ".rewrap")
                plain = root / (name + ".plain")
                try:
                    container.decrypt_file(
                        path, plain, secret, max_bytes=settings.BACKUP_MAX_UNPACKED_BYTES
                    )
                    job.file_sha256 = container.encrypt_file(
                        plain, rewrapped, current, key_fingerprint=keys.fingerprint(current)
                    )
                    os.replace(rewrapped, path)
                    os.chmod(path, 0o600)
                finally:
                    _remove(plain)
                    _remove(rewrapped)
    except (RestoreError, keys.KeyError_, container.ContainerError) as exc:
        job.report = {"ok": False, "problems": [str(exc)], "warnings": []}
    except Exception as exc:  # noqa: BLE001
        # 檔案內容再怪,也只能是「這份檔不能用」:留一筆紀錄、刪掉暫存檔,
        # 不能變成伺服器錯誤、也不能把檔案留在暫存區。
        job.report = {
            "ok": False, "warnings": [],
            "problems": [f"備份檔內容無法讀取({type(exc).__name__})"],
        }
    job.target_fingerprint = target_fingerprint(tenant)
    job.status = (
        RestoreJob.Status.PRECHECKED if job.report.get("ok") else RestoreJob.Status.REJECTED
    )
    if job.status == RestoreJob.Status.REJECTED:
        _remove(path)
        job.staged_file = ""
    job.save()
    audit(tenant, user, "restore.prechecked", ok=bool(job.report.get("ok")),
          restore_job=job, problems=job.report.get("problems", [])[:5])
    return job


def confirm(job, user):
    """管理員確認要還原。確認綁定「這份檔、這家公司、這次預檢」;過期或資料變了要重來。

    **確認的當下就上維護鎖**(跟狀態改成排隊中是同一個交易)。等 worker 接手才
    上鎖的話,這段空檔(幾秒到幾分鐘)店裡照常開單,那些單隨後會被還原吃掉。
    """
    from apps.tenants.models import Tenant

    with transaction.atomic():
        # 同公司的確認一個一個來。no_key:不必等正在開單的交易(那由執行時的鎖處理)
        Tenant.objects.select_for_update(no_key=True).get(pk=job.tenant_id)
        job = RestoreJob.objects.select_for_update().get(pk=job.pk)
        if job.status != RestoreJob.Status.PRECHECKED:
            raise RestoreError("這次還原不是待確認的狀態")
        problem = ""
        if job.expires_at and job.expires_at < timezone.now():
            problem = "預檢已經過期,請重新上傳備份檔"
        elif RestoreJob.objects.filter(
            tenant=job.tenant, status__in=[RestoreJob.Status.QUEUED, RestoreJob.Status.RUNNING]
        ).exclude(pk=job.pk).exists() or jobs.in_maintenance(job.tenant):
            raise RestoreError("這家公司已經有一個還原正在進行")
        elif target_fingerprint(job.tenant) != job.target_fingerprint:
            problem = "預檢之後公司資料有變動,請重新上傳備份檔再確認一次"
        if not problem:
            job.status = RestoreJob.Status.QUEUED
            job.confirmed_by = user if getattr(user, "is_authenticated", False) else None
            job.confirmed_at = timezone.now()
            job.save(update_fields=["status", "confirmed_by", "confirmed_at", "updated_at"])
            lock(job.tenant, job, "資料還原中")
    if problem:
        cancel(job, user, reason=problem)
        raise RestoreError(problem)
    audit(job.tenant, user, "restore.confirmed", restore_job=job)
    return job


def cancel(job, user, reason=""):
    """取消還原。還在排隊(worker 還沒接手)的也可以取消,並解除維護鎖。"""
    with transaction.atomic():
        job = RestoreJob.objects.select_for_update().get(pk=job.pk)
        if job.status not in (
            RestoreJob.Status.PRECHECKED, RestoreJob.Status.REJECTED, RestoreJob.Status.QUEUED,
        ):
            raise RestoreError("已經開始的還原不能取消")
        was_queued = job.status == RestoreJob.Status.QUEUED
        staged = job.staged_file
        job.status = RestoreJob.Status.CANCELLED
        job.staged_file = ""
        job.error = reason
        job.save(update_fields=["status", "staged_file", "error", "updated_at"])
        if was_queued:
            unlock(job.tenant)
    if staged:
        _remove(jobs.backup_root() / staged)
    audit(job.tenant, user, "restore.cancelled", restore_job=job, reason=reason)
    return job


def _remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


# ─────────────────────────── 維護鎖 ───────────────────────────
def lock(tenant, job, reason):
    """上維護鎖。已經鎖著就不重設開始時間(等待期要從最早上鎖那一刻算)。"""
    maint, created = TenantMaintenance.objects.get_or_create(
        tenant=tenant,
        defaults={"active": True, "reason": reason, "restore_job": job,
                  "started_at": timezone.now()},
    )
    if not created:
        if not maint.active:
            maint.started_at = timezone.now()
        maint.active, maint.reason, maint.restore_job = True, reason, job
        maint.save()
    return maint


def unlock(tenant):
    TenantMaintenance.objects.filter(tenant=tenant).update(active=False)


def _wait_out_admitted_requests(locked_at) -> None:
    """上鎖之後,等滿一段寬限時間才動手。

    維護鎖是在登入驗證那一步擋的。上鎖前一刻已經通過驗證的請求可能還沒開始寫
    資料庫,這時候誰也看不到它。等滿寬限時間(預設比網頁伺服器的請求逾時長)
    之後,那些請求不是做完了,就是被伺服器逾時砍掉了。
    """
    grace = getattr(settings, "BACKUP_RESTORE_GRACE_SECONDS", 75)
    remaining = (locked_at + timedelta(seconds=grace) - timezone.now()).total_seconds()
    if remaining > 0:
        time.sleep(remaining)


def _take_company(tenant):
    """在取代資料的交易裡,把公司那一列整個鎖住(FOR UPDATE)。這是真正的寫入屏障。

    每一筆公司資料都有一個指到公司的外鍵。PostgreSQL 在新增這種資料時,會對
    被指到的那一列公司上一把共享鎖 —— 跟這裡的排他鎖互斥。所以:

    - 拿到這把鎖 = 所有「正在新增這家公司資料」的交易都已經結束(看得到結果了);
    - 握著這把鎖的期間,任何地方(網頁、管理指令、匯入程式、直接呼叫 service)
      要新增這家公司的資料,都會停下來等還原提交,不會跟還原交錯。

    不靠「看資料庫現在有哪些交易開著」:那會連別家公司的長交易一起等。
    等不到(有交易卡著不放)就放棄這次還原,資料不動。
    """
    from apps.tenants.models import Tenant

    try:
        if connection.vendor == "postgresql":
            with connection.cursor() as cur:
                cur.execute(f"SET LOCAL lock_timeout = '{int(LOCK_TIMEOUT_SECONDS)}s'")
        return Tenant.objects.select_for_update().get(pk=tenant.pk)
    except OperationalError:
        raise RestoreError("系統還有進行中的作業沒有結束,這次先不還原;請稍後再試")


# ─────────────────────────── 執行 ───────────────────────────
def reconcile():
    """worker 每一輪都做的整理:收拾「狀態跟實際對不起來」的東西。

    - 維護鎖還開著、但它對應的還原早就結束了(完成 / 失敗 / 取消):解鎖。
      正常流程解鎖跟結束是同一個交易;這裡是保險。
    - 過期沒人確認的預檢:取消並刪掉暫存檔。
    - 暫存區裡超過一天、沒有任何工作在用的檔:刪掉。
    """
    done = (
        RestoreJob.Status.DONE, RestoreJob.Status.FAILED,
        RestoreJob.Status.CANCELLED, RestoreJob.Status.REJECTED,
    )
    for maint in TenantMaintenance.objects.filter(active=True).select_related("restore_job"):
        if maint.restore_job is None or maint.restore_job.status in done:
            unlock(maint.tenant)
            audit(maint.tenant, None, "restore.lock_reconciled", restore_job=maint.restore_job)
    for job in RestoreJob.objects.filter(
        status=RestoreJob.Status.PRECHECKED, expires_at__lt=timezone.now()
    ):
        try:
            cancel(job, None, reason="預檢已過期")
        except RestoreError:
            pass
    root = jobs.backup_root()
    # 只有還用得到檔案的工作才算「在用」。已經結束的工作就算還記著檔名(例如刪檔
    # 那一刻失敗),那個檔也是孤兒,照樣清。
    in_use = set(
        RestoreJob.objects.filter(status__in=[
            RestoreJob.Status.PRECHECKED, RestoreJob.Status.QUEUED,
            RestoreJob.Status.RUNNING, RestoreJob.Status.NEEDS_ATTENTION,
        ]).exclude(staged_file="").values_list("staged_file", flat=True)
    )
    # 還在跑的工作,它的暫存檔再舊也不能動(資料多的公司可能跑超過一天):
    # 備份的暫存檔名開頭是備份編號;還原解開的明文在 staging/ 底下。
    running_backups = {
        str(i) for i in BackupJob.objects.filter(
            status=BackupJob.Status.RUNNING
        ).values_list("backup_id", flat=True)
    }
    restore_running = RestoreJob.objects.filter(status=RestoreJob.Status.RUNNING).exists()
    cutoff = time.time() - 24 * 3600
    for sub in ("staging", "tmp"):
        for path in (root / sub).iterdir():
            if sub == "tmp" and path.name.split(".")[0] in running_backups:
                continue
            if sub == "staging" and restore_running:
                continue
            try:
                if f"{sub}/{path.name}" not in in_use and path.stat().st_mtime < cutoff:
                    path.unlink()
            except OSError:
                pass


def _is_dead(job) -> bool:
    """執行中的還原是不是其實已經沒有人在跑。

    worker 執行時全程握著這個工作的資料庫鎖,行程一死鎖就自動放掉。所以
    「沒有人握著」= 沒有人在跑。剛接手的那一小段時間(還沒來得及握鎖)不算。
    """
    if job.started_at and job.started_at > timezone.now() - CLAIM_GRACE:
        return False
    return jobs.job_is_abandoned("restore", job.pk)


def claim_next():
    reconcile()
    now = timezone.now()
    with transaction.atomic():
        # 執行到一半 worker 死掉的還原:資料庫交易沒提交,資料沒變;但不自動重跑、
        # 也不自動解鎖,留給管理員看過再決定。
        # 「死掉」的判定見 _is_dead:看的是有沒有行程還握著這個工作,不是看時間。
        # 只看時間的話,跑得久的還原會被誤判成中斷,管理員就可能在它還在跑的時候
        # 解除維護。
        for stale in RestoreJob.objects.select_for_update(skip_locked=True).filter(
            status=RestoreJob.Status.RUNNING
        ):
            if not _is_dead(stale):
                continue
            stale.status = RestoreJob.Status.NEEDS_ATTENTION
            stale.error = (
                "還原在執行途中被中斷。資料庫的變更沒有提交,公司資料維持還原前的狀態。"
                "請管理員確認後解除維護,再重新上傳備份檔。"
            )
            stale.finished_at = now
            stale.save(update_fields=["status", "error", "finished_at", "updated_at"])
            audit(stale.tenant, None, "restore.interrupted", ok=False, restore_job=stale)
        job = (
            RestoreJob.objects.select_for_update(skip_locked=True)
            .filter(status=RestoreJob.Status.QUEUED).order_by("id").first()
        )
        if job is None:
            return None
        job.status = RestoreJob.Status.RUNNING
        job.attempts += 1
        job.started_at = now
        job.lease_until = now + RESTORE_LEASE
        job.save(update_fields=["status", "attempts", "started_at", "lease_until", "updated_at"])
        return job


def run_restore(job) -> RestoreJob:
    """執行一個已確認、已被 claim 的還原。執行期間握著這個工作的鎖。"""
    try:
        with jobs.holding_job("restore", job.pk):
            return _run_restore(job)
    except jobs.BackupError:
        return job


def _still_referenced(name) -> bool:
    """這個附件檔還有沒有任何一列資料(不分公司)指著它。"""
    from django.apps import apps

    return any(
        apps.get_model(label)._base_manager.filter(**{field: name}).exists()
        for label, fields in FILE_FIELDS.items() for field in fields
    )


def _delete_unreferenced(names) -> int:
    """刪掉已經沒有任何資料指著的舊附件。回傳刪了幾個。

    「查有沒有人用」跟「刪檔」之間不能有空檔:別家公司剛好在這中間存了一筆指到
    同一個檔的資料,檔案就被刪掉了。所以先把所有帶附件的表鎖成「暫時不能寫」
    (SHARE ROW EXCLUSIVE:讀照常,寫要等),等正在寫的交易結束,再查、再刪,
    整段在同一個交易裡。鎖的時間只有查幾筆、刪幾個檔那麼長。
    拿不到鎖(有交易卡著)就這次不刪 —— 多留幾個檔只是佔空間。
    """
    from django.apps import apps

    if not names:
        return 0
    deleted = 0
    try:
        with transaction.atomic():
            if connection.vendor == "postgresql":
                with connection.cursor() as cur:
                    cur.execute(
                        f"SET LOCAL lock_timeout = '{int(CLEANUP_LOCK_TIMEOUT_SECONDS)}s'"
                    )
                    for label in sorted(FILE_FIELDS):
                        table = connection.ops.quote_name(apps.get_model(label)._meta.db_table)
                        cur.execute(f"LOCK TABLE {table} IN SHARE ROW EXCLUSIVE MODE")
            for name in names:
                if _still_referenced(name):
                    continue
                try:
                    default_storage.delete(name)
                    deleted += 1
                except OSError:
                    pass
    except OperationalError:
        pass
    return deleted


def _run_restore(job) -> RestoreJob:
    tenant = job.tenant
    root = jobs.backup_root()
    staged = root / job.staged_file
    written_files: list[str] = []
    obsolete_files: list[str] = []
    maint = lock(tenant, job, "資料還原中")       # 確認時已經上鎖;這裡是保險
    try:
        _wait_out_admitted_requests(maint.started_at)
        secret = keys.get_secret(tenant)
        if secret is None:
            raise RestoreError("伺服器上的復原憑證讀不出來,請重新上傳並輸入憑證")
        if container.sha256_file(staged) != job.file_sha256:
            raise RestoreError("暫存的備份檔跟預檢時不一樣,請重新上傳")

        # 還原前先把現況完整備份一份。這份做不出來就不往下做。
        safety, _ = jobs.request_backup(tenant, job.confirmed_by, kind=BackupJob.Kind.SAFETY)
        claimed = BackupJob.objects.filter(pk=safety.pk, status=BackupJob.Status.QUEUED).update(
            status=BackupJob.Status.RUNNING, started_at=timezone.now(),
            lease_until=timezone.now() + jobs.LEASE, attempts=safety.attempts + 1,
        )
        if not claimed:
            raise RestoreError("還原前的安全備份正在被別的程序處理,請稍後再試")
        safety.refresh_from_db()
        safety = jobs.run_backup(safety)
        if safety.status != BackupJob.Status.VERIFIED:
            raise RestoreError("還原前的安全備份沒有成功,已停止還原:" + safety.error[:200])
        RestoreJob.objects.filter(pk=job.pk).update(safety_backup=safety)

        with Package(staged, secret) as pkg:
            report = validate(tenant, pkg, job.mode)
            if not report["ok"]:
                raise RestoreError("還原前再次檢查沒有通過:" + ";".join(report["problems"][:3]))
            with transaction.atomic():
                # 鎖住自己這個工作並確認它還是「執行中」:別人把它標成中斷之後,
                # 這裡就不能再往下寫。
                current = RestoreJob.objects.select_for_update().get(pk=job.pk)
                if current.status != RestoreJob.Status.RUNNING:
                    raise RestoreError("這個還原已經被標成中斷,沒有執行")
                _take_company(tenant)
                # 寫入擋住之後再比一次:從確認到現在,公司資料不該有任何變動
                if target_fingerprint(tenant) != current.target_fingerprint:
                    raise RestoreError("確認之後公司資料有變動,這次沒有還原;請重新上傳檢查")
                result = _apply(tenant, pkg, job.mode, written_files, obsolete_files)
                result.pop("_pk_map", None)
                current.status = RestoreJob.Status.DONE
                current.result = {**result, "warnings": report["warnings"]}
                current.finished_at = timezone.now()
                current.lease_until = None
                current.error = ""
                current.safety_backup = safety
                current.staged_file = ""
                current.save()
                # 解鎖跟「完成」同一個交易:不會出現「資料換好了、鎖卻永遠開著」
                unlock(tenant)
    except Exception as exc:  # noqa: BLE001
        # 走到這裡,資料交易沒有提交(或根本沒開始):公司資料跟還原前一樣。
        for name in written_files:
            try:
                default_storage.delete(name)
            except OSError:
                pass
        with transaction.atomic():
            RestoreJob.objects.filter(pk=job.pk).exclude(
                status=RestoreJob.Status.NEEDS_ATTENTION
            ).update(
                status=RestoreJob.Status.FAILED,
                error=(str(exc) if isinstance(exc, RestoreError) else f"還原失敗:{exc}")[:2000],
                finished_at=timezone.now(), lease_until=None,
                # 失敗的工作不會重跑(要重新上傳),那份上傳檔不用留
                staged_file="",
            )
            job.refresh_from_db()
            if job.status == RestoreJob.Status.FAILED:
                unlock(tenant)
        if job.status == RestoreJob.Status.FAILED:
            _remove(staged)
        audit(tenant, job.confirmed_by, "restore.failed", ok=False, restore_job=job,
              error=job.error[:300])
        return job

    # 提交之後才清:暫存檔,以及已經沒有任何資料指到的舊附件。
    # 這裡被中斷只會多留幾個檔,不影響資料;reconcile 之後會收拾暫存區。
    _remove(staged)
    _delete_unreferenced(obsolete_files)
    job.refresh_from_db()
    audit(tenant, job.confirmed_by, "restore.done", restore_job=job,
          rows=job.result.get("rows"), safety_backup=job.safety_backup_id)
    return job


def _apply(tenant, pkg, mode, written_files, obsolete_files, user_map=None) -> dict:
    """在呼叫端的交易裡,把這家公司的資料整批換成備份的內容。"""
    from django.apps import apps

    from apps.tenants.models import (
        DocNumberFloor, InvoiceTrack, InvoiceType, Tenant, UserProfile,
    )

    User = get_user_model()
    m = pkg.manifest
    order = registry.ordered_company_models()
    order_index = {label_of(x): i for i, x in enumerate(order)}
    rollback = mode == RestoreJob.Mode.ROLLBACK

    # 鎖住公司那一列:同一家公司的兩個還原不會同時進來
    company = Tenant.objects.select_for_update().get(pk=tenant.pk)

    # ── 1. 記下現況裡要保留的:只能往前的號碼、帳號綁的門市、舊附件
    live_counters = {k: getattr(company, k) for k in TENANT_HIGH_WATER}
    live_high = {}
    for label, (key_fields, fields) in HIGH_WATER.items():
        model = apps.get_model(label)
        live_high[label] = {
            tuple(row[k] for k in key_fields): {f: row[f] for f in fields}
            for row in model._base_manager.filter(tenant=company).values(*key_fields, *fields)
        }
    live_doc_seq = {
        prefix: _max_doc_seq(apps.get_model(label), company)
        for label, prefix in DOC_NUMBERED.items()
    }
    live_floor = {
        key[0]: row["floor"] for key, row in live_high["tenants.DocNumberFloor"].items()
    }
    # 備份之後才申請的發票字軌:備份裡沒有,但號碼可能已經開出去了,要留著
    live_tracks = list(
        InvoiceTrack.objects.filter(tenant=company).values(
            "invoice_type__code", "invoice_type__name", "invoice_type__sort_order",
            "period_label", "prefix", "range_start", "range_end", "next_number",
            "is_active", "note",
        )
    ) if rollback else []
    profile_codes = dict(
        UserProfile.objects.filter(tenant=company)
        .values_list("pk", "default_warehouse__code")
    )
    for label, fields in FILE_FIELDS.items():
        for row in apps.get_model(label)._base_manager.filter(tenant=company).values(*fields):
            obsolete_files.extend(v for v in row.values() if v)

    if user_map is None:
        user_map, _ = _account_map(company, pkg.accounts)

    # ── 2. 清掉這家公司現有的資料。帳號的門市先解開(門市等一下會換新的)
    UserProfile.objects.filter(tenant=company).update(default_warehouse=None)
    for model in reversed(order):
        model._base_manager.filter(tenant=company)._raw_delete(model._base_manager.db)

    # ── 3. 照備份寫回去:新的主鍵、外鍵照對照表換
    pk_map: dict[str, dict] = {}
    attachments = {
        (a["table"], a["pk"], a["field"]): a for a in m.get("attachments", [])
    }
    counts, digests = {}, {}
    later = []   # 等全部寫完才補得上的外鍵
    for model in order:
        label = label_of(model)
        fields = [f for f in model._meta.concrete_fields if f.name != "tenant"]
        deferred = {f.attname: f for f in registry.deferred_fks(model, order_index)}
        auto_stamps = [
            f.attname for f in fields
            if isinstance(f, models.DateField) and (f.auto_now or f.auto_now_add)
        ]
        file_cols = FILE_FIELDS.get(label, [])
        mapping: dict = {}
        pk_map[label] = mapping
        row_digests = []
        batch, originals = [], []

        def flush():
            if not batch:
                return
            model._base_manager.bulk_create(batch, batch_size=BATCH)
            if auto_stamps:
                # bulk_create 會把「自動填現在時間」的欄位蓋成現在;改回備份裡的值
                for obj, src in zip(batch, originals):
                    for name in auto_stamps:
                        setattr(obj, name, src[name])
                model._base_manager.bulk_update(batch, auto_stamps, batch_size=BATCH)
            for obj, src in zip(batch, originals):
                mapping[src["id"]] = obj.pk
            batch.clear()
            originals.clear()

        for row in pkg.rows(label):
            row_digests.append(_row_digest(model, row))
            values = {"tenant_id": company.pk}
            pending = {}
            for f in fields:
                raw = row[f.attname]
                if f.primary_key:
                    continue
                if isinstance(f, (models.ForeignKey, models.OneToOneField)):
                    if raw is None:
                        values[f.attname] = None
                    elif f.related_model is User:
                        values[f.attname] = user_map.get(raw)
                    elif f.attname in deferred:
                        values[f.attname] = None
                        pending[f.attname] = (label_of(f.related_model), raw)
                    else:
                        values[f.attname] = pk_map[label_of(f.related_model)][raw]
                elif f.name in file_cols and raw:
                    att = attachments[(label, row["id"], f.name)]
                    with pkg.open_file(att["index"]) as src:
                        saved = default_storage.save(raw, File(src))
                    written_files.append(saved)
                    # 寫完再從儲存區讀回來比一次:磁碟滿、寫到一半這類狀況,
                    # 要在提交前就發現,不能等之後開圖才知道檔案是壞的。
                    digest, size = hashlib.sha256(), 0
                    with default_storage.open(saved, "rb") as back:
                        for block in iter(lambda: back.read(1024 * 1024), b""):
                            digest.update(block)
                            size += len(block)
                    if size != att["size"] or digest.hexdigest() != att["sha256"]:
                        raise RestoreError(f"附件寫回後內容不符:{att['name']}")
                    values[f.attname] = saved
                else:
                    values[f.attname] = f.to_python(raw)
            obj = model(**values)
            parsed = {name: values[name] for name in auto_stamps}
            parsed["id"] = row["id"]
            batch.append(obj)
            originals.append(parsed)
            if pending:
                later.append((model, obj, pending))
            if len(batch) >= BATCH:
                flush()
        flush()
        counts[label] = len(mapping)
        digests[label] = _table_digest(row_digests)

    for model, obj, pending in later:
        for attname, (target, raw) in pending.items():
            setattr(obj, attname, pk_map[target][raw])
        model._base_manager.filter(pk=obj.pk).update(
            **{attname: getattr(obj, attname) for attname in pending}
        )

    # ── 4. 驗證:筆數、逐列內容、外鍵。任何一項不對就丟錯,整個交易回滾。
    #    要在下面「刻意調整號碼」之前做:這裡驗的是「照搬有沒有搬對」。
    for model in order:
        label = label_of(model)
        if counts[label] != m["tables"][label]:
            raise RestoreError(f"還原後筆數不符:{label}")
        cols = [f.attname for f in _non_relational(model)]
        got = _table_digest(
            hashlib.sha256(dump_json(row)).digest()
            for row in model._base_manager.filter(tenant=company).values(*cols).iterator()
        )
        if got != digests[label]:
            raise RestoreError(f"還原後內容跟備份不一致:{label}")
    if connection.vendor == "postgresql":
        with connection.cursor() as cur:
            cur.execute("SET CONSTRAINTS ALL IMMEDIATE")   # 外鍵現在就檢查,不等提交

    # ── 5. 只能往前的號碼:取現況與備份較大者(新環境沒有現況,就是備份的值)
    kept_tracks: list[str] = []
    backup_counters = m["company"]["counters"]
    for k in TENANT_HIGH_WATER:
        value = backup_counters.get(k, 1)
        setattr(company, k, max(value, live_counters[k]) if rollback else value)
    for k in registry.TENANT_SETTINGS:
        if k != "name":
            setattr(company, k, m["company"]["settings"][k])
    company.save()
    if rollback:
        for label, (key_fields, fields) in HIGH_WATER.items():
            model = apps.get_model(label)
            for obj in model._base_manager.filter(tenant=company):
                live = live_high[label].get(tuple(getattr(obj, k) for k in key_fields))
                if not live:
                    continue
                changed = [f for f in fields if live[f] > getattr(obj, f)]
                for f in changed:
                    setattr(obj, f, live[f])
                if changed:
                    model._base_manager.filter(pk=obj.pk).update(
                        **{f: getattr(obj, f) for f in changed}
                    )
        # 單號下限 = 現況最後一張單、現況的下限、備份裡的下限,三者取最大。
        # 現況的下限是之前還原留下來的;備份裡沒有那一筆也不能弄丟。
        for prefix in sorted(set(live_doc_seq) | set(live_floor)):
            seq = max(live_doc_seq.get(prefix, 0), live_floor.get(prefix, 0))
            if not seq:
                continue
            floor, _ = DocNumberFloor.objects.get_or_create(
                tenant=company, prefix=prefix, defaults={"floor": 0}
            )
            if seq > floor.floor:
                DocNumberFloor.objects.filter(pk=floor.pk).update(floor=seq)
        # 備份裡沒有的字軌照現況補回去(連同已經開到第幾號)
        have = set(
            InvoiceTrack.objects.filter(tenant=company).values_list("prefix", "range_start")
        )
        for t in live_tracks:
            if (t["prefix"], t["range_start"]) in have:
                continue
            kind, _ = InvoiceType.objects.get_or_create(
                tenant=company, code=t["invoice_type__code"],
                defaults={
                    "name": t["invoice_type__name"],
                    "sort_order": t["invoice_type__sort_order"],
                    "is_active": True, "is_default": False,
                },
            )
            InvoiceTrack.objects.create(
                tenant=company, invoice_type=kind, period_label=t["period_label"],
                prefix=t["prefix"], range_start=t["range_start"], range_end=t["range_end"],
                next_number=t["next_number"], is_active=t["is_active"], note=t["note"],
            )
            kept_tracks.append(f"{t['prefix']} {t['range_start']}-{t['range_end']}")

    # ── 6. 帳號的門市:用門市代碼對回新的那一筆;對不回來就留空。
    #    留空的帳號如果是鎖倉的,等於沒有門市可用 —— 不會因此變成可以看全部。
    warehouse_by_code = dict(
        apps.get_model("inventory.Warehouse")._base_manager.filter(tenant=company)
        .values_list("code", "pk")
    )
    orphaned = 0
    for pk, code in profile_codes.items():
        if not code:
            continue
        new_id = warehouse_by_code.get(code)
        if new_id is None:
            orphaned += 1
        else:
            UserProfile.objects.filter(pk=pk).update(default_warehouse_id=new_id)

    return {
        "rows": sum(counts.values()),
        "tables": counts,
        "attachments": len(written_files),
        "snapshot_at": m["snapshot_at"],
        "profiles_without_store": orphaned,
        "invoice_tracks_kept": kept_tracks,
        # 還原前各種號碼用到哪裡。留在工作紀錄裡,事後查得到「當時到底開到幾號」。
        "numbers_before": {
            "counters": live_counters,
            "doc_seq": live_doc_seq,
            "doc_floor": live_floor,
            "invoice_tracks": {
                f"{t['prefix']} {t['range_start']}": t["next_number"] for t in live_tracks
            },
        } if rollback else {},
        "_pk_map": pk_map,      # 內部用,呼叫端拿掉再存
    }


def release_after_interruption(tenant, user):
    """維護鎖卡住時,管理員確認過、手動解除。

    只有在「確定沒有還原正在跑」的時候才放行:排隊中的要用取消;執行中的要
    確定沒有任何行程還握著那個工作。
    """
    maint = TenantMaintenance.objects.filter(tenant=tenant, active=True).first()
    if maint is None:
        raise RestoreError("目前沒有維護鎖")
    job = maint.restore_job
    if job is not None:
        job.refresh_from_db()
        if job.status == RestoreJob.Status.QUEUED:
            raise RestoreError("還原還在排隊,要中止請按取消")
        if job.status == RestoreJob.Status.RUNNING and not _is_dead(job):
            raise RestoreError("還原還在進行中,不能解除維護")
        if job.status in (RestoreJob.Status.RUNNING, RestoreJob.Status.NEEDS_ATTENTION):
            staged, job.staged_file = job.staged_file, ""
            job.status = RestoreJob.Status.FAILED
            job.save(update_fields=["status", "staged_file", "updated_at"])
            if staged:
                _remove(jobs.backup_root() / staged)     # 要再還原得重新上傳
    unlock(tenant)
    audit(tenant, user, "restore.maintenance_released", restore_job=job)
    return job


# ─────────────────────────── 新環境復原 ───────────────────────────
def _free_username(wanted, code, limit=150) -> str:
    """這台伺服器上沒人用的帳號名稱。原名可用就用原名;撞名就加上公司代碼,
    再撞就加流水。名稱太長時截掉前段,保證放得進欄位。"""
    User = get_user_model()
    if not User.objects.filter(username=wanted).exists():
        return wanted
    n = 1
    while True:
        suffix = f"-{code}" if n == 1 else f"-{code}-{n}"
        candidate = wanted[: limit - len(suffix)] + suffix
        if not User.objects.filter(username=candidate).exists():
            return candidate
        n += 1


def restore_new_company(enc_path, credential, *, code, admin_username, name="",
                        admin_password="", operator=None):
    """原伺服器不能用時:在一台相容的新環境上,憑備份檔 + 復原憑證把公司建回來。

    這是平台維運動作(由主機上的管理指令呼叫),不開放一般網址。

    - 公司用備份裡的識別碼建立;同一個識別碼已經在這台伺服器上就拒絕(那是
      「既有公司回溯」,要走另一條有安全備份的流程,不能從這裡蓋掉)。
    - 先建一個復原管理員;備份裡的店員帳號照角色與門市重建,但**不帶密碼**,
      要管理員逐一重設才能登入。舊的登入 token 不存在於備份,自然不會復活。
    - 發票字軌全部先停用:這台伺服器不知道備份之後原本那邊又開了幾張,
      核對過再由管理員啟用,避免重複開同一個號碼。
    """
    from apps.tenants.models import InvoiceTrack, Tenant, UserProfile

    User = get_user_model()
    secret = keys.parse_secret(credential)
    written_files: list[str] = []
    try:
        with Package(enc_path, secret) as pkg:
            m = pkg.manifest
            if Tenant.objects.filter(backup_uuid=m["company"]["uuid"]).exists():
                raise RestoreError("這家公司已經在這台伺服器上,請改用「既有公司回溯」")
            if Tenant.objects.filter(code=code).exists():
                raise RestoreError(f"公司代碼「{code}」已經有人用了")
            if User.objects.filter(username=admin_username).exists():
                raise RestoreError(f"帳號「{admin_username}」已經存在,請換一個復原管理員帳號")
            with transaction.atomic():
                tenant = Tenant.objects.create(
                    name=name or m["company"]["name"], code=code,
                    backup_uuid=m["company"]["uuid"],
                )
                report = validate(tenant, pkg, RestoreJob.Mode.NEW_ENV)
                if not report["ok"]:
                    raise RestoreError("備份檔檢查沒有通過:" + ";".join(report["problems"][:3]))

                admin = User(username=admin_username)
                if admin_password:
                    admin.set_password(admin_password)
                else:
                    admin.set_unusable_password()
                admin.save()
                UserProfile.objects.create(
                    user=admin, tenant=tenant, role="tenant_admin", is_warehouse_locked=False
                )

                # 備份裡屬於這家公司的帳號:照名字重建,撞名就加上公司代碼
                user_map, renamed, created = {}, {}, []
                for acc in pkg.accounts:
                    if not acc["in_company"]:
                        user_map[acc["id"]] = None
                        continue
                    username = _free_username(acc["username"], code)
                    if username != acc["username"]:
                        renamed[acc["username"]] = username
                    u = User(
                        username=username, first_name=acc["first_name"],
                        last_name=acc["last_name"], is_active=acc["is_active"],
                    )
                    u.set_unusable_password()
                    u.save()
                    user_map[acc["id"]] = u.pk
                    created.append((u, acc))

                result = _apply(
                    tenant, pkg, RestoreJob.Mode.NEW_ENV, written_files, [],
                    user_map=user_map,
                )
                warehouses = result.pop("_pk_map")["inventory.Warehouse"]
                without_store = 0
                for u, acc in created:
                    store = warehouses.get(acc["default_warehouse_id"])
                    if acc["default_warehouse_id"] and store is None:
                        without_store += 1
                    identity = {}
                    if not UserProfile.objects.filter(account_uuid=acc["uuid"]).exists():
                        # 沿用原本的識別碼:之後拿這家公司更早的備份回溯,還認得出是同一個人
                        identity["account_uuid"] = acc["uuid"]
                    UserProfile.objects.create(
                        user=u, tenant=tenant, role=acc["role"] or "tenant_user",
                        default_warehouse_id=store, **identity,
                        # 門市對不回來的一律維持鎖定(= 沒有門市可用),不放寬
                        is_warehouse_locked=acc["is_warehouse_locked"] or store is None
                        if acc["role"] != "tenant_admin" else acc["is_warehouse_locked"],
                    )
                held = InvoiceTrack.objects.filter(tenant=tenant, is_active=True).update(
                    is_active=False
                )
                keys.register_key(tenant, credential, operator)
                result.update({
                    "accounts_created": len(created),
                    "accounts_renamed": renamed,
                    "accounts_without_store": without_store,
                    "invoice_tracks_on_hold": held,
                    "warnings": report["warnings"],
                })
    except Exception:
        for name_ in written_files:
            try:
                default_storage.delete(name_)
            except OSError:
                pass
        raise
    audit(tenant, operator, "restore.new_company", rows=result["rows"],
          admin=admin_username)
    return tenant, result
