"""把一家公司的資料與附件匯出成一包(還沒加密的 zip)。

三件事不能含糊:

1. **整家公司**:這家公司旗下所有門市的資料一起出,不看畫面上現在選哪一家店。
2. **同一個時間點**:整個匯出在一個 REPEATABLE READ 唯讀交易裡完成。一般的
   `atomic()` 是 READ COMMITTED,每一句查詢看到的是「當下」,匯出途中有人開單
   就會出現單頭在、明細不在,或庫存跟單據對不起來。
3. **附件要真的在**:資料表裡只存檔名,檔案本體要一起打包並驗證;少一個就整個
   備份失敗、把缺的列出來,不出一份「看起來成功」的殘缺備份。
"""
import datetime
import hashlib
import json
import zipfile
from contextlib import contextmanager

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.storage import default_storage
from django.core.serializers.json import DjangoJSONEncoder
from django.db import connection, models, transaction
from django.db.migrations.recorder import MigrationRecorder
from django.utils import timezone

from . import registry
from .registry import FILE_FIELDS, FORMAT_VERSION, label_of


class ExportError(Exception):
    """備份產生不出來(原因會顯示給管理員)。"""


@contextmanager
def snapshot():
    """同一個時間點的唯讀視圖。必須是最外層交易,隔離等級才設得進去。"""
    if connection.in_atomic_block:
        raise ExportError("備份匯出必須自己開交易,不能包在別的交易裡")
    with transaction.atomic():
        if connection.vendor == "postgresql":
            with connection.cursor() as cur:
                cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        yield


def schema_state() -> dict:
    """這套系統目前套用了哪些 migration:{app: [全部已套用的 migration 名稱]}。

    還原時要「完全一樣」才放行。只記每個 app 最後一支不夠:沒有資料表的 app
    (例如 core)會被漏掉,兩條平行的 migration 分支也可能最後一支同名、內容不同。
    """
    from django.apps import apps as django_apps

    wanted = {
        cfg.label for cfg in django_apps.get_app_configs() if cfg.name.startswith("apps.")
    } | {label.split(".")[0] for label in registry.REGISTRY}
    state: dict[str, list] = {}
    for app, name in MigrationRecorder.Migration.objects.order_by("app", "name").values_list(
        "app", "name"
    ):
        if app in wanted:
            state.setdefault(app, []).append(name)
    return state


def schema_fingerprint(state: dict) -> str:
    raw = json.dumps(state, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()[:16]


def _user_fk_fields(model):
    User = get_user_model()
    return [
        f for f in model._meta.concrete_fields
        if isinstance(f, (models.ForeignKey, models.OneToOneField))
        and f.related_model is User
    ]


class _Encoder(DjangoJSONEncoder):
    """跟 Django 內建的差一點:時間保留到微秒。

    內建的會把時間截到毫秒,還原回去的建立時間就跟原本差了一點點,
    也沒辦法逐列核對「還原後跟備份一模一樣」。
    """

    def default(self, o):
        if isinstance(o, datetime.datetime):
            return o.isoformat()
        return super().default(o)


def dump_json(obj) -> bytes:
    return json.dumps(obj, cls=_Encoder, ensure_ascii=False,
                      separators=(",", ":"), sort_keys=True).encode("utf-8")


_dump = dump_json


def export_company(tenant, zip_path, backup_id) -> dict:
    """匯出到 zip_path(明文,呼叫端負責加密與刪除)。回傳 manifest。"""
    registry.check_registry()
    from apps.inventory.models import Warehouse
    from apps.tenants.models import Tenant, UserProfile

    User = get_user_model()
    tables: dict[str, int] = {}
    attachments: list[dict] = []
    missing: list[str] = []

    with snapshot(), zipfile.ZipFile(
        zip_path, "w", zipfile.ZIP_DEFLATED, allowZip64=True
    ) as zf:
        snapshot_at = timezone.now()
        # 重新讀一次:要拿快照裡的值,不是呼叫端手上那個可能已經舊了的物件
        company = Tenant.objects.get(pk=tenant.pk)
        warehouses = list(
            Warehouse.objects.filter(tenant=company).order_by("id")
            .values("code", "name", "is_active")
        )
        # 這家公司自己的帳號。單據上的經手帳號如果不是這家公司的人(平台管理員
        # 代操作、或歷史資料綁錯),**不把那個帳號帶進備份** —— 那一欄寫成空的。
        # 別人的帳號名稱不該出現在這家公司的備份裡。
        profiles = {
            p["user_id"]: p for p in UserProfile.objects.filter(tenant=company).values(
                "user_id", "role", "default_warehouse_id", "is_warehouse_locked",
                "account_uuid", "denied_abilities",
            )
        }

        for model in registry.ordered_company_models():
            label = label_of(model)
            fields = [f for f in model._meta.concrete_fields if f.name != "tenant"]
            attnames = [f.attname for f in fields]
            user_cols = [f.attname for f in _user_fk_fields(model)]
            file_cols = FILE_FIELDS.get(label, [])
            count = 0
            with zf.open(f"data/{label}.jsonl", "w", force_zip64=True) as out:
                rows = (
                    model._base_manager.filter(tenant=company).order_by("pk")
                    .values(*attnames).iterator(chunk_size=2000)
                )
                for row in rows:
                    for col in user_cols:
                        if row[col] is not None and row[col] not in profiles:
                            row[col] = None
                    out.write(_dump(row) + b"\n")
                    count += 1
                    for col in file_cols:
                        if row[col]:
                            attachments.append({
                                "table": label, "pk": row["id"], "field": col,
                                "name": row[col],
                                "expected": row.get("content_hash") or "",
                            })
            tables[label] = count

        # 附件:跟資料同一批清單,逐檔複製並驗證
        for index, att in enumerate(attachments):
            att["index"] = index
            name = att["name"]
            if not default_storage.exists(name):
                missing.append(f"{att['table']} #{att['pk']}:{name}")
                continue
            digest, size = hashlib.sha256(), 0
            with default_storage.open(name, "rb") as src, zf.open(
                f"files/{index}", "w", force_zip64=True
            ) as out:
                for block in iter(lambda: src.read(1024 * 1024), b""):
                    out.write(block)
                    digest.update(block)
                    size += len(block)
            att["size"], att["sha256"] = size, digest.hexdigest()
            expected = att.pop("expected")
            if expected and expected != att["sha256"]:
                missing.append(f"{att['table']} #{att['pk']}:{name}(內容跟上傳時不一樣)")
        if missing:
            raise ExportError(
                "有附件遺失或內容不符,無法產生完整備份:\n" + "\n".join(missing[:20])
                + (f"\n…共 {len(missing)} 個" if len(missing) > 20 else "")
            )
        for att in attachments:
            att.pop("expected", None)

        # 帳號對照:只有這家公司的帳號。不含密碼、不含 token。
        accounts = []
        for u in User.objects.filter(id__in=list(profiles)).order_by("id").values(
            "id", "username", "first_name", "last_name", "is_active"
        ):
            p = profiles[u["id"]]
            accounts.append({
                **u,
                "in_company": True,
                # 認人用這個:名稱會改、會被別人拿去用;數字 id 換一台伺服器就不同
                "uuid": str(p["account_uuid"]),
                "role": p["role"],
                "default_warehouse_id": p["default_warehouse_id"],
                "is_warehouse_locked": p["is_warehouse_locked"],
                # 這個帳號被關掉的權限項目:搬到新環境還原時要跟著回來(不然大家變回全開)
                "denied_abilities": [k for k in (p["denied_abilities"] or []) if isinstance(k, str)],
            })
        zf.writestr("accounts.json", _dump(accounts))

        state = schema_state()
        manifest = {
            "format": FORMAT_VERSION,
            "backup_id": str(backup_id),
            "snapshot_at": snapshot_at.isoformat(),
            "timezone": settings.TIME_ZONE,
            "schema": state,
            "schema_fingerprint": schema_fingerprint(state),
            "company": {
                "uuid": str(company.backup_uuid),
                "name": company.name,
                "code": company.code,
                "settings": {k: getattr(company, k) for k in registry.TENANT_SETTINGS},
                "counters": {k: getattr(company, k) for k in registry.TENANT_HIGH_WATER},
            },
            "warehouses": warehouses,
            "classification": {label: e.kind for label, e in registry.REGISTRY.items()},
            "tables": tables,
            "accounts": len(accounts),
            "attachments": attachments,
        }
        zf.writestr("manifest.json", _dump(manifest))
    return manifest
