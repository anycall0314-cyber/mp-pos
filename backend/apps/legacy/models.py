"""舊系統資料:十年會員消費歷史、舊→新對照、(之後)庫存搬家。

三個原則(見 docs/資料底層與自然語言報表_規劃.md):

1. **原文不改**。舊會員編號的空白 / Tab / 前導零、店名、品號、品名、帶正負號的數量
   與金額、空白單價(存 NULL,不補零)都照來源保存;擷取快照與報表列另存全文,
   可以用 SHA-256 重新核對。
2. **對照是另一層**。舊店名 / 舊品號 / 舊業務員 / 舊會員要對到 MP 的門市 / 商品 /
   業務員 / 會員,由人確認;每一筆決定記在 `LegacyMappingLog`。查詢時透過對照表
   串起來(`store_map` / `product_map` / `salesperson_map` 是不佔欄位的關聯),
   所以改對照不必改動明細。對不到的歸「未對照」。
3. **只供查詢**。這裡的資料不是 MP 的交易:不觸發過帳、庫存、收款、發票、點數或
   通知,也不參與「上次成交價」。金額是來源報表值,不等於實收或營收。

金額單位一律是「分」(TWD 百分之一)的整數;原始額與淨額(依單別正負)分開。
所有表都帶 tenant,而且都登記在公司備份(apps/backup/registry.py)。
"""
from django.conf import settings
from django.db import models

from apps.core.models import TenantOwnedModel

# 單別 → 對「累計淨額」的正負。由來源報表的會員累計核實;不認得的單別一律擋下匯入,
# 不照字首或正負去猜。
NET_SIGN = {
    "E01": 1, "E11": 1, "E12": 1, "E13": 1,
    "F01": -1, "F11": -1, "F13": -1, "FS11": -1,
}


class MapStatus(models.TextChoices):
    UNMAPPED = "unmapped", "未對照"
    CONFIRMED = "confirmed", "已確認"


class MapMethod(models.TextChoices):
    PHONE = "phone", "電話相同"
    NAME = "name", "名稱相同"
    CODE = "code", "代碼相同"
    MATCH = "match", "叫法比對"
    MANUAL = "manual", "手動指定"
    CREATED = "created", "用舊資料建立"


def _who(name):
    return models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+", verbose_name=name,
    )


class HistoryImportBatch(TenantOwnedModel):
    """一次匯入(對應封存檔裡的一個來源批次 / 期間)。"""

    class Status(models.TextChoices):
        RUNNING = "running", "匯入中"
        DONE = "done", "已完成"
        ROLLED_BACK = "rolled_back", "已撤回"

    source_system = models.CharField("來源系統", max_length=40)
    report = models.CharField("來源報表", max_length=20)
    period_start = models.DateField("期間起")
    period_end = models.DateField("期間迄")
    # 封存裡這一批實際匯入內容(import payload)的 SHA-256:同一批不會被匯兩次
    content_sha256 = models.CharField("匯入內容雜湊", max_length=64)
    archive_sha256 = models.CharField("封存資料庫雜湊", max_length=64)
    archive_batch_id = models.PositiveIntegerField("封存批次編號")
    source_file = models.CharField("來源檔", max_length=300)
    source_scope_raw = models.TextField("查詢範圍原文")
    archive_schema_version = models.PositiveSmallIntegerField("封存結構版本")
    normalized_schema_version = models.PositiveSmallIntegerField("標準化格式版本")
    status = models.CharField(
        "狀態", max_length=20, choices=Status.choices, default=Status.RUNNING
    )
    result = models.JSONField("結果", default=dict, blank=True)
    imported_by = _who("匯入者")
    finished_at = models.DateTimeField("完成時間", null=True, blank=True)
    rolled_back_at = models.DateTimeField("撤回時間", null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "content_sha256"], name="uniq_history_batch_content",
            ),
        ]
        ordering = ["-id"]
        verbose_name = "舊 POS 匯入批次"
        verbose_name_plural = "舊 POS 匯入批次"


# ─────────────────────────── 對照 ───────────────────────────
class _Mapping(TenantOwnedModel):
    """對照的共同欄位:目前對到誰、狀態、怎麼對的、誰確認的。歷次決定在 LegacyMappingLog。"""

    source_system = models.CharField("來源系統", max_length=40)
    status = models.CharField(
        "狀態", max_length=20, choices=MapStatus.choices, default=MapStatus.UNMAPPED
    )
    method = models.CharField("對照方式", max_length=20, choices=MapMethod.choices, blank=True)
    confirmed_by = _who("確認人")
    confirmed_at = models.DateTimeField("確認時間", null=True, blank=True)

    class Meta:
        abstract = True


class LegacyStoreMap(_Mapping):
    """舊店名原文 → 門市。"""

    store_name_raw = models.CharField("舊店名原文", max_length=60)
    warehouse = models.ForeignKey(
        "inventory.Warehouse", on_delete=models.PROTECT, null=True, blank=True,
        related_name="+", verbose_name="門市",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "source_system", "store_name_raw"],
                name="uniq_legacy_store_map",
            ),
        ]
        ordering = ["store_name_raw"]
        verbose_name = "舊店別對照"
        verbose_name_plural = "舊店別對照"


class LegacyProductMap(_Mapping):
    """舊品號 → 商品。十年歷史與庫存搬家共用同一張。"""

    product_code_raw = models.CharField("舊品號原文", max_length=60)
    # 同一個舊品號在不同年份可能用過不同品名;這裡留最近看到的一個給人辨認
    product_name_seen = models.CharField("最近看到的舊品名", max_length=500, blank=True)
    product_name_seen_at = models.DateTimeField("看到這個品名的擷取時間", null=True, blank=True)
    product = models.ForeignKey(
        "catalog.Product", on_delete=models.PROTECT, null=True, blank=True,
        related_name="+", verbose_name="商品",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "source_system", "product_code_raw"],
                name="uniq_legacy_product_map",
            ),
        ]
        ordering = ["product_code_raw"]
        verbose_name = "舊品號對照"
        verbose_name_plural = "舊品號對照"


class LegacySalespersonMap(_Mapping):
    """舊業務員原文 → 業務員。"""

    salesperson_raw = models.CharField("舊業務員原文", max_length=60)
    sales_person = models.ForeignKey(
        "parties.SalesPerson", on_delete=models.PROTECT, null=True, blank=True,
        related_name="+", verbose_name="業務員",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "source_system", "salesperson_raw"],
                name="uniq_legacy_salesperson_map",
            ),
        ]
        ordering = ["salesperson_raw"]
        verbose_name = "舊業務員對照"
        verbose_name_plural = "舊業務員對照"


class LegacyMember(_Mapping):
    """舊系統的一個會員編號,同時也是它對到哪一位 MP 會員的對照。

    精確編號(含空白 / Tab / 前導零)才是身分,顯示時才去頭尾空白。不同編號就算姓名、
    電話一樣也是兩筆。一個舊編號只對到一位 MP 會員;一位 MP 會員可以有好幾個舊編號。
    """

    source_member_id = models.CharField("會員編號(精確)", max_length=64)
    source_member_id_raw = models.CharField("會員編號(連結原文)", max_length=300)
    name_raw = models.CharField("姓名原文", max_length=120, blank=True)
    phone_raw = models.CharField("電話原文", max_length=60, blank=True)
    # 只拿來找候選(去掉非數字);不是身分
    phone_digits = models.CharField("電話數字", max_length=40, blank=True, db_index=True)
    last_captured_at = models.DateTimeField("最後擷取時間")
    first_batch = models.ForeignKey(
        HistoryImportBatch, on_delete=models.PROTECT, related_name="+",
        verbose_name="首次匯入批次",
    )
    member = models.ForeignKey(
        "parties.Member", on_delete=models.PROTECT, null=True, blank=True,
        related_name="legacy_members", verbose_name="MP 會員",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "source_system", "source_member_id"],
                name="uniq_legacy_member_source_id",
            ),
            models.CheckConstraint(
                check=(
                    models.Q(status=MapStatus.UNMAPPED, member__isnull=True)
                    | models.Q(status=MapStatus.CONFIRMED, member__isnull=False)
                ),
                name="legacy_member_link_consistent",
            ),
        ]
        ordering = ["id"]
        verbose_name = "舊 POS 會員"
        verbose_name_plural = "舊 POS 會員"

    @property
    def display_id(self) -> str:
        return self.source_member_id.strip()

    def __str__(self) -> str:
        return f"{self.display_id} {self.name_raw.strip()}"


class LegacyMappingLog(TenantOwnedModel):
    """每一次對照決定(確認、撤銷、用舊資料建立)。對照表只放「現在」,歷程在這裡。"""

    class Kind(models.TextChoices):
        MEMBER = "member", "會員"
        STORE = "store", "店別"
        PRODUCT = "product", "品號"
        SALESPERSON = "salesperson", "業務員"

    class Action(models.TextChoices):
        CONFIRM = "confirm", "確認"
        REVOKE = "revoke", "撤銷"

    kind = models.CharField("對照種類", max_length=20, choices=Kind.choices)
    source_system = models.CharField("來源系統", max_length=40)
    key_raw = models.CharField("舊代號原文", max_length=300)
    action = models.CharField("動作", max_length=20, choices=Action.choices)
    method = models.CharField("對照方式", max_length=20, choices=MapMethod.choices, blank=True)
    old_target_id = models.BigIntegerField("原本對到", null=True, blank=True)
    new_target_id = models.BigIntegerField("改成對到", null=True, blank=True)
    target_label = models.CharField("對象名稱", max_length=200, blank=True)
    by = _who("操作人")
    note = models.CharField("說明", max_length=300, blank=True)

    class Meta:
        ordering = ["-id"]
        verbose_name = "舊系統對照紀錄"
        verbose_name_plural = "舊系統對照紀錄"


# ─────────────────────────── 來源快照 ───────────────────────────
class LegacyMemberListSnapshot(TenantOwnedModel):
    """某一批的會員清單那一列(含當期累計金額原文)。"""

    batch = models.ForeignKey(
        HistoryImportBatch, on_delete=models.PROTECT, related_name="+", verbose_name="批次"
    )
    legacy_member = models.ForeignKey(
        LegacyMember, on_delete=models.CASCADE, related_name="list_snapshots",
        verbose_name="舊 POS 會員",
    )
    source_file = models.CharField("來源檔", max_length=300)
    list_amount_raw = models.CharField("清單累計原文", max_length=40)
    raw_json = models.TextField("清單列原文")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["batch", "legacy_member"], name="uniq_history_list_snapshot",
            ),
        ]
        verbose_name = "舊 POS 會員清單快照"
        verbose_name_plural = "舊 POS 會員清單快照"


class LegacySourceSnapshot(TenantOwnedModel):
    """某一批、某會員的完整消費明細頁(擷取當下的全文)。raw_sha256 可重新核對。"""

    batch = models.ForeignKey(
        HistoryImportBatch, on_delete=models.PROTECT, related_name="+", verbose_name="批次"
    )
    legacy_member = models.ForeignKey(
        LegacyMember, on_delete=models.CASCADE, related_name="source_snapshots",
        verbose_name="舊 POS 會員",
    )
    source_url = models.TextField("來源網址")
    captured_at = models.DateTimeField("擷取時間")
    raw_sha256 = models.CharField("全文雜湊", max_length=64)
    raw_json = models.TextField("明細頁全文")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["batch", "legacy_member"], name="uniq_history_source_snapshot",
            ),
        ]
        verbose_name = "舊 POS 明細快照"
        verbose_name_plural = "舊 POS 明細快照"


# ─────────────────────────── 單據與明細 ───────────────────────────
class LegacyDocument(TenantOwnedModel):
    """一張舊單據。身分 = 公司 + 來源系統 + 舊會員 + 店別 + 單別 + 單號 + 日期。"""

    source_system = models.CharField("來源系統", max_length=40)
    legacy_member = models.ForeignKey(
        LegacyMember, on_delete=models.CASCADE, related_name="documents",
        verbose_name="舊 POS 會員",
    )
    store_name_raw = models.CharField("店別原文", max_length=60)
    document_type_raw = models.CharField("單別", max_length=10)
    document_number_raw = models.CharField("單號", max_length=40)
    document_date = models.DateField("交易日期")
    # 整張單內容的雜湊(同封存的算法):相同代表沒變,不同代表要換一版
    content_sha256 = models.CharField("內容雜湊", max_length=64)
    snapshot = models.ForeignKey(
        LegacySourceSnapshot, on_delete=models.PROTECT, related_name="+",
        verbose_name="目前依據的快照",
    )
    report_amount_minor = models.BigIntegerField("原始金額合計(分)")
    net_amount_minor = models.BigIntegerField("淨額合計(分)")
    item_count = models.PositiveIntegerField("明細筆數")
    last_captured_at = models.DateTimeField("擷取時間")
    first_batch = models.ForeignKey(
        HistoryImportBatch, on_delete=models.PROTECT, related_name="+",
        verbose_name="首次匯入批次",
    )
    # 不佔欄位:查詢時用(公司, 來源系統, 店名原文)串到店別對照
    store_map = models.ForeignObject(
        LegacyStoreMap, on_delete=models.DO_NOTHING, related_name="+",
        from_fields=["tenant", "source_system", "store_name_raw"],
        to_fields=["tenant", "source_system", "store_name_raw"],
        null=True,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "tenant", "source_system", "legacy_member", "store_name_raw",
                    "document_type_raw", "document_number_raw", "document_date",
                ],
                name="uniq_legacy_document_identity",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant", "legacy_member", "-document_date"],
                name="legacy_doc_member_date",
            ),
            models.Index(fields=["tenant", "document_date"], name="legacy_doc_date"),
        ]
        ordering = ["-document_date", "-id"]
        verbose_name = "舊 POS 單據"
        verbose_name_plural = "舊 POS 單據"


class LegacyDocumentVersion(TenantOwnedModel):
    """單據每一次被擷取到的完整內容。換版時舊的留著(superseded_at 有值)。"""

    document = models.ForeignKey(
        LegacyDocument, on_delete=models.CASCADE, related_name="versions",
        verbose_name="單據",
    )
    snapshot = models.ForeignKey(
        LegacySourceSnapshot, on_delete=models.PROTECT, related_name="+",
        verbose_name="快照",
    )
    batch = models.ForeignKey(
        HistoryImportBatch, on_delete=models.PROTECT, related_name="+", verbose_name="批次"
    )
    content_sha256 = models.CharField("內容雜湊", max_length=64)
    rows_json = models.TextField("報表列原文")
    # 這一版的明細(換版 / 撤回時要能整張還原;報表列原文在 rows_json)
    items_json = models.TextField("明細")
    superseded_at = models.DateTimeField("被取代時間", null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["document", "snapshot"], name="uniq_legacy_document_version",
            ),
        ]
        ordering = ["id"]
        verbose_name = "舊 POS 單據版本"
        verbose_name_plural = "舊 POS 單據版本"


class LegacyItem(TenantOwnedModel):
    """單據裡的一列。同一張單裡內容完全相同的列也各留一筆。"""

    document = models.ForeignKey(
        LegacyDocument, on_delete=models.CASCADE, related_name="items", verbose_name="單據"
    )
    source_system = models.CharField("來源系統", max_length=40)
    item_ordinal = models.PositiveIntegerField("單內順序")
    report_sequence_raw = models.CharField("報表序號", max_length=20, blank=True)
    product_code_raw = models.CharField("品號原文", max_length=60, blank=True)
    product_name_raw = models.CharField("品名原文", max_length=500, blank=True)
    # 數量照原文保存(帶正負號的十進位文字),不換成整數、不夾成 1
    quantity_decimal = models.CharField("數量", max_length=40)
    quantity_raw = models.CharField("數量原文", max_length=40, blank=True)
    unit_price_minor = models.BigIntegerField("單價(分)", null=True, blank=True)
    amount_minor = models.BigIntegerField("金額(分)")
    amount_ex_tax_minor = models.BigIntegerField("未稅額(分)")
    points_raw = models.CharField("點數原文", max_length=40, blank=True)
    salesperson_raw = models.CharField("業務員原文", max_length=60, blank=True)
    customer_name_raw = models.CharField("客戶名稱原文", max_length=120, blank=True)
    remarks_raw = models.TextField("備註原文", blank=True)
    promotion_raw = models.CharField("促銷方案原文", max_length=200, blank=True)
    source_row_json = models.TextField("報表列原文")
    net_sign = models.SmallIntegerField("淨額正負")
    # 不佔欄位:查詢時串到品號 / 業務員對照
    product_map = models.ForeignObject(
        LegacyProductMap, on_delete=models.DO_NOTHING, related_name="+",
        from_fields=["tenant", "source_system", "product_code_raw"],
        to_fields=["tenant", "source_system", "product_code_raw"],
        null=True,
    )
    salesperson_map = models.ForeignObject(
        LegacySalespersonMap, on_delete=models.DO_NOTHING, related_name="+",
        from_fields=["tenant", "source_system", "salesperson_raw"],
        to_fields=["tenant", "source_system", "salesperson_raw"],
        null=True,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["document", "item_ordinal"], name="uniq_legacy_item_ordinal",
            ),
            models.CheckConstraint(
                check=models.Q(net_sign__in=[-1, 1]), name="legacy_item_net_sign",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant", "source_system", "product_code_raw"],
                name="legacy_item_product_code",
            ),
        ]
        ordering = ["document_id", "item_ordinal"]
        verbose_name = "舊 POS 單據明細"
        verbose_name_plural = "舊 POS 單據明細"

    @property
    def net_amount_minor(self) -> int:
        return self.amount_minor * self.net_sign


class LegacySourceException(TenantOwnedModel):
    """來源報表的會員累計跟完整明細對不上。原文全部留著,不併進已核對的資料。

    要結案必須有新的來源證據、處理人、時間與理由;原始數字不改。
    """

    class Status(models.TextChoices):
        OPEN = "open", "待核"
        RESOLVED = "resolved", "已處理"

    batch = models.ForeignKey(
        HistoryImportBatch, on_delete=models.PROTECT, related_name="+", verbose_name="批次"
    )
    legacy_member = models.ForeignKey(
        LegacyMember, on_delete=models.CASCADE, related_name="source_exceptions",
        verbose_name="舊 POS 會員",
    )
    snapshot = models.ForeignKey(
        LegacySourceSnapshot, on_delete=models.PROTECT, related_name="+",
        verbose_name="快照",
    )
    reason = models.CharField("原因", max_length=60)
    list_amount_minor = models.BigIntegerField("清單累計(分)")
    detail_net_amount_minor = models.BigIntegerField("明細淨額(分)")
    detail_raw_amount_minor = models.BigIntegerField("明細原始額(分)")
    difference_minor = models.BigIntegerField("差額(分)")
    line_count = models.PositiveIntegerField("明細筆數")
    document_count = models.PositiveIntegerField("單據數")
    rows_json = models.TextField("原始列")
    validation_error = models.TextField("核對錯誤")
    status = models.CharField(
        "狀態", max_length=20, choices=Status.choices, default=Status.OPEN
    )
    resolved_by = _who("處理人")
    resolved_at = models.DateTimeField("處理時間", null=True, blank=True)
    resolution_note = models.TextField("處理理由", blank=True)
    resolution_evidence = models.TextField("新的來源證據", blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["batch", "legacy_member"], name="uniq_history_source_exception",
            ),
        ]
        ordering = ["id"]
        verbose_name = "舊 POS 來源差異"
        verbose_name_plural = "舊 POS 來源差異"
