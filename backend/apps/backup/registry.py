"""公司備份的資料清單:每一張表都要明確分類。

不能只掃「有 tenant 欄位的表」:那樣新增一張表、或某張表歸屬方式不一樣時,
會被靜默漏掉,而「漏備份」要到還原那天才會發現。這裡反過來 —— 每一張表都
要在下面登記,**沒登記的表存在時,備份直接拒絕執行**(`check_registry`)。
新增 model 之後跑測試就會被擋下來,提醒你來這裡決定它算哪一類。
"""
from dataclasses import dataclass

from django.apps import apps
from django.db import models

FORMAT_VERSION = 1

COMPANY = "company"    # 公司資料:依公司匯出、還原時整批取代
ACCOUNT = "account"    # 帳號:不整列匯出,只留「誰是誰」的對照;還原時另外處理
TENANT = "tenant"      # 公司本身那一列(設定與各種流水號)
EXCLUDED = "excluded"  # 不進公司備份


@dataclass(frozen=True)
class Entry:
    kind: str
    note: str = ""


def _company(*labels):
    return {label: Entry(COMPANY) for label in labels}


REGISTRY: dict[str, Entry] = {
    "tenants.Tenant": Entry(TENANT, "公司設定、保固天數、客戶 / 會員 / 單據流水號"),
    **_company(
        # 系統設定主檔
        "tenants.InvoiceType", "tenants.InvoiceTrack", "tenants.PaymentMethod",
        "tenants.DocNumberFloor",
        # 往來對象
        "parties.Supplier", "parties.Customer", "parties.Member",
        "parties.SalesPerson", "parties.Carrier", "parties.TelecomPlan",
        "parties.SimCard",
        # 商品
        "catalog.Category", "catalog.Brand", "catalog.ProductType",
        "catalog.PhoneSeries", "catalog.PhoneModel", "catalog.Condition",
        "catalog.Product", "catalog.ProductRelation", "catalog.SupplierProduct",
        "catalog.PartTemplate", "catalog.PartTemplateItem",
        # 門市與庫存(零庫存、停用的商品也在 Product 裡;帳本與成本快照不可重算)
        "inventory.Warehouse", "inventory.ProductSerial",
        "inventory.ProductSerialIdentifier", "inventory.ProductSerialCodeChange",
        "inventory.StockBalance", "inventory.StockMovement",
        # 單據
        "purchasing.PurchaseOrderCategory", "purchasing.PurchaseOrder",
        "purchasing.PurchaseOrderItem",
        "sales.SalesOrder", "sales.SalesOrderItem", "sales.SalesOrderItemSerial",
        "sales.SalesOrderPayment", "sales.SalesReturn", "sales.SalesReturnItem",
        "sales.SalesReturnItemSerial", "sales.LegacyPurchase",
        "transfers.TransferOrder", "transfers.TransferOrderItem",
        "transfers.TransferOrderItemSerial",
        "cash.PettyExpense", "cash.CashAdjustment", "cash.PhoneBillCollection",
        "repairs.RepairItem", "repairs.RepairItemModel", "repairs.RepairItemPart",
        "repairs.RepairOrder", "repairs.RepairOrderPart",
        # 商品識別與待確認入庫(含進貨單原圖)
        "identity.ProductAlias", "identity.ProductDistinctDecision",
        "identity.IntakeBatch", "identity.IntakeItem",
        "identity.IntakeReceivedUnit", "identity.IntakeUnitIdentifier",
        "identity.IntakeDocument",
        # 指令助理紀錄、需求訊號
        "assistant.CommandLog",
        "signals.MarketSignal", "signals.SubjectAlias", "signals.DemandAlert",
        # 舊系統資料:十年會員消費(含原始快照與版本)、舊→新對照
        "legacy.HistoryImportBatch", "legacy.LegacyStoreMap", "legacy.LegacyProductMap",
        "legacy.LegacySalespersonMap", "legacy.LegacyMember", "legacy.LegacyMappingLog",
        "legacy.LegacyMemberListSnapshot", "legacy.LegacySourceSnapshot",
        "legacy.LegacyDocument", "legacy.LegacyDocumentVersion", "legacy.LegacyItem",
        "legacy.LegacySourceException",
        # 每日庫存快照:過去的庫存事後算不回來,一定要備份
        "ledger.StockSnapshot", "ledger.StockSnapshotDay",
        # 存起來的報表(查詢單)
        "analytics.SavedReport",
        # 商品照片(掛在商品上的;檔案一起打包)
        "photos.ProductPhoto",
    ),
    "auth.User": Entry(ACCOUNT, "只留帳號名稱等對照資訊;不含密碼"),
    "tenants.UserProfile": Entry(ACCOUNT, "角色、預設門市、鎖倉;還原時依對照處理"),
    "auth.Group": Entry(EXCLUDED, "平台層級權限,不屬於任何公司"),
    "auth.Permission": Entry(EXCLUDED, "平台層級權限,不屬於任何公司"),
    "authtoken.Token": Entry(EXCLUDED, "登入憑證;舊 token 不能因為還原重新生效"),
    "authtoken.TokenProxy": Entry(EXCLUDED, "同上(同一張表)"),
    "admin.LogEntry": Entry(EXCLUDED, "Django 後台操作紀錄,平台層級"),
    "contenttypes.ContentType": Entry(EXCLUDED, "框架內部"),
    "sessions.Session": Entry(EXCLUDED, "登入 session,不可還原"),
    "backup.BackupKey": Entry(EXCLUDED, "復原憑證不放進它自己加密的備份"),
    "backup.BackupJob": Entry(EXCLUDED, "備份工作紀錄留在原地,不隨資料回溯"),
    "backup.DownloadTicket": Entry(EXCLUDED, "一次性下載票券,用完即廢"),
    "backup.RestoreJob": Entry(EXCLUDED, "還原工作紀錄留在原地"),
    "backup.TenantMaintenance": Entry(EXCLUDED, "維護鎖是伺服器當下狀態"),
    "backup.BackupAuditLog": Entry(EXCLUDED, "操作紀錄留在原地,不隨資料回溯"),
    "ledger.LedgerCheckRun": Entry(EXCLUDED, "對帳紀錄是當時資料的檢查結果,留在原地"),
    "core.IdempotencyKey": Entry(EXCLUDED, "建單鑰匙只留幾天,記的是單號;還原後照樣對得回來"),
    "photos.PhotoDraft": Entry(EXCLUDED, "新增 / 編輯商品時的照片作業,暫存;存檔後照片已經在 ProductPhoto"),
    "photos.PhotoUpload": Entry(EXCLUDED, "還沒隨商品存檔的暫存照片"),
}

# 帶檔案的欄位:{表: [欄位]}。只存路徑不算備份,檔案本體要一起打包。
FILE_FIELDS: dict[str, list[str]] = {
    "identity.IntakeDocument": ["image"],
    "photos.ProductPhoto": ["image", "thumb"],
}

# 不備份、卻指到公司資料的暫存表(例:商品照片編輯到一半的作業,指到商品)。
# **還原時先整批清掉這家公司的這些列**(連它們自己的暫存檔):不清的話,舊資料刪掉之後它們指到不存在的列
# (還原做不完),或是還原之後還能拿舊的作業去改還原回來的資料。
# {表: [這張表自己的檔案欄位]};順序 = 刪除順序(先刪指著別人的)。
# 新的暫存表只要指到公司資料就要登記在這裡,check_registry() 會擋。
CLEARED_ON_RESTORE: dict[str, list[str]] = {
    "photos.PhotoUpload": ["image", "thumb"],
    "photos.PhotoDraft": [],
}

# 流水號 / 字軌這類「只能往前、不能倒退」的欄位。
# 還原到較早的備份時取「現況」與「備份」較大者,避免重用已經給出去的號碼。
# {表: (用哪些欄位認出是同一筆, [只能往前的欄位])}
HIGH_WATER: dict[str, tuple[tuple[str, ...], list[str]]] = {
    "catalog.Category": (("code",), ["next_sku_seq"]),
    "parties.Carrier": (("code",), ["next_plan_seq"]),
    "tenants.InvoiceTrack": (("prefix", "range_start"), ["next_number"]),
    "tenants.DocNumberFloor": (("prefix",), ["floor"]),
}
TENANT_HIGH_WATER = [
    "next_supplier_seq", "next_customer_seq", "next_member_seq", "next_style_seq",
    "next_expense_seq", "next_cash_adj_seq", "next_phone_bill_seq", "next_repair_seq",
]
# 公司那一列要帶走的設定欄位(流水號另外用 TENANT_HIGH_WATER)
TENANT_SETTINGS = ["name", "repair_warranty_days"]

# 單號靠「最後一張單 + 1」取號的單據:{表: 字首}。還原前把已用過的最大號記進
# DocNumberFloor。
DOC_NUMBERED = {
    "purchasing.PurchaseOrder": "PO",
    "sales.SalesOrder": "SO",
    "sales.SalesReturn": "SR",
    "transfers.TransferOrder": "TR",
}

USER_LABEL = "auth.User"
TENANT_LABEL = "tenants.Tenant"


class RegistryError(Exception):
    """資料清單不完整或不一致。備份 / 還原在這種狀態下拒絕執行。"""


def label_of(model) -> str:
    return model._meta.label


def company_models():
    return [apps.get_model(label) for label, e in REGISTRY.items() if e.kind == COMPANY]


def check_registry():
    """清單與實際的資料表對不上就丟 RegistryError,把所有問題一次列出來。"""
    problems = []
    known = set(REGISTRY)
    actual = {label_of(m) for m in apps.get_models()}
    for label in sorted(actual - known):
        problems.append(f"{label}:沒有登記在備份清單(apps/backup/registry.py)")
    for label in sorted(known - actual):
        problems.append(f"{label}:清單裡有,但系統裡沒有這張表")

    for label in CLEARED_ON_RESTORE:
        if REGISTRY.get(label) is None or REGISTRY[label].kind != EXCLUDED:
            problems.append(f"{label}:列在 CLEARED_ON_RESTORE,但不是「不備份」的表")

    for model in apps.get_models():
        label = label_of(model)
        entry = REGISTRY.get(label)
        if entry is not None and entry.kind == EXCLUDED:
            # 不備份的表如果指到公司資料:還原會把那些公司資料刪掉重寫,這張表的列就指到不存在的東西
            points_at = [
                f.name for f in model._meta.get_fields()
                if isinstance(f, (models.ForeignKey, models.OneToOneField))
                and getattr(f, "concrete", False) and f.name != "tenant"
                and getattr(REGISTRY.get(label_of(f.related_model)), "kind", None) == COMPANY
            ]
            if points_at and label not in CLEARED_ON_RESTORE:
                problems.append(
                    f"{label}.{points_at[0]}:不備份的表指到公司資料,"
                    "要登記在 CLEARED_ON_RESTORE(還原時先清掉)"
                )
            if label in CLEARED_ON_RESTORE and not any(
                f.name == "tenant" and getattr(f, "concrete", False)
                for f in model._meta.get_fields()
            ):
                problems.append(f"{label}:列在 CLEARED_ON_RESTORE 卻沒有 tenant 欄位,無法依公司清掉")
        if entry is None or entry.kind != COMPANY:
            continue
        fields = model._meta.get_fields()
        if not any(
            f.name == "tenant" and getattr(f, "concrete", False) for f in fields
        ):
            problems.append(f"{label}:列為公司資料卻沒有 tenant 欄位,無法依公司匯出")
        declared = set(FILE_FIELDS.get(label, []))
        for f in fields:
            if isinstance(f, models.ManyToManyField):
                problems.append(f"{label}.{f.name}:多對多欄位,備份還不會處理")
            if isinstance(f, models.FileField) and f.name not in declared:
                problems.append(f"{label}.{f.name}:檔案欄位沒有登記在 FILE_FIELDS")
            if isinstance(f, (models.ForeignKey, models.OneToOneField)) and f.name != "tenant":
                if label_of(f.related_model) == _user_label() and not f.null:
                    problems.append(
                        f"{label}.{f.name}:指到登入帳號的欄位必須可以留空"
                        "(還原時帳號對不回來就是留空)"
                    )
                target = REGISTRY.get(label_of(f.related_model))
                if target is None:
                    continue  # 上面已經報過「沒有登記」
                if target.kind == EXCLUDED:
                    problems.append(
                        f"{label}.{f.name}:指到不備份的表 {label_of(f.related_model)}"
                    )
                if target.kind == ACCOUNT and label_of(f.related_model) != USER_LABEL:
                    problems.append(f"{label}.{f.name}:只支援指到帳號(auth.User)")
    for label in FILE_FIELDS:
        if REGISTRY.get(label, Entry(EXCLUDED)).kind != COMPANY:
            problems.append(f"{label}:FILE_FIELDS 裡有,但不是公司資料")
    if problems:
        raise RegistryError("備份資料清單有問題:\n- " + "\n- ".join(problems))


def _user_label() -> str:
    from django.contrib.auth import get_user_model

    return label_of(get_user_model())


def _fk_fields(model):
    return [
        f for f in model._meta.concrete_fields
        if isinstance(f, (models.ForeignKey, models.OneToOneField)) and f.name != "tenant"
    ]


def ordered_company_models():
    """公司資料表,排成「被別人指到的在前」。

    只看**必填**的外鍵排順序(必填的一定要先有對象才能寫);可空的外鍵如果
    指到排在後面的表(或指到自己),還原時先留空、全部寫完再補(見 `deferred_fks`)。
    """
    todo = company_models()
    labels = {label_of(m) for m in todo}
    deps = {}
    for m in todo:
        deps[label_of(m)] = {
            label_of(f.related_model) for f in _fk_fields(m)
            if not f.null and label_of(f.related_model) in labels
            and f.related_model is not m
        }
    ordered, placed = [], set()
    by_label = {label_of(m): m for m in todo}
    while len(ordered) < len(todo):
        ready = sorted(
            label for label in by_label
            if label not in placed and deps[label] <= placed
        )
        if not ready:
            stuck = sorted(set(by_label) - placed)
            raise RegistryError("資料表之間有必填外鍵的循環,無法決定還原順序:" + "、".join(stuck))
        for label in ready:
            ordered.append(by_label[label])
            placed.add(label)
    return ordered


def deferred_fks(model, order_index):
    """這張表有哪些可空外鍵要「全部寫完再補」:指到自己、或指到排在後面的表。"""
    out = []
    me = order_index[label_of(model)]
    for f in _fk_fields(model):
        target = label_of(f.related_model)
        if target not in order_index:
            continue
        if order_index[target] >= me:
            out.append(f)
    return out
