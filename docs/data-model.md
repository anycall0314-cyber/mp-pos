# 完整資料模型規格

> 對應 [roadmap.md](roadmap.md) 的 Phase 0~4。Phase 0/1 model 在 `backend/apps/` 下實作；Phase 2+ 為設計藍圖，尚未實作。
>
> 所有業務 model 都自帶 `tenant_id`（從 `apps.core.TenantOwnedModel` 繼承），未列出。
> 所有 model 都自帶 `created_at` / `updated_at`，未列出。
> `Decimal(14, 2)` = 最大 12 位整數 + 2 位小數，金額用。

## 目錄

- [Phase 0 — 已實作](#phase-0--已實作)
- [Phase 1 — MVP 進銷存核心](#phase-1--mvp-進銷存核心)
- [Phase 2 — SIM 卡與佣金](#phase-2--sim-卡與佣金)
- [Phase 3 — 維修 + 應收應付 + 發票](#phase-3--維修--應收應付--發票)
- [Phase 4 — 中古機 + 管銷 + 報表](#phase-4--中古機--管銷--報表)

---

## Phase 0 — 已實作

### `tenants.Tenant`

| 欄位 | 型別 | 說明 |
|------|------|------|
| name | CharField(120) | 名稱 |
| code | SlugField(40) unique | 代碼 |
| is_active | bool | 啟用 |

### `inventory.Warehouse`

| 欄位 | 型別 | 說明 |
|------|------|------|
| code | SlugField(40) | 倉庫代碼 |
| name | CharField(120) | 倉庫名稱 |
| is_active | bool | 啟用 |

**約束**：`(tenant, code)` unique。

### `catalog.Category`

| 欄位 | 型別 | 說明 |
|------|------|------|
| code | SlugField(8) | 類別代碼,也是 SKU 前綴 |
| name | CharField(80) | 類別名稱 |
| sort_order | uint | 排序 |
| is_active | bool | 啟用 |
| next_sku_seq | uint | 下一流水號（每次發 SKU +1） |

**約束**：`(tenant, code)` unique、`(tenant, name)` unique。
**方法**：`issue_next_sku()` 原子地取下一個 SKU `{code}-{6位流水}`。

### `catalog.Product`

| 欄位 | 型別 | 說明 |
|------|------|------|
| sku | CharField(60) editable=False | 系統自動產生 |
| name | CharField(200) | 品名（建議含規格） |
| spec | CharField(200) | 規格描述 |
| barcode | CharField(80) | 條碼 |
| category | FK Category PROTECT | 類別 |
| weighted_avg_cost | Decimal(14,2) | 當下加權平均成本 |
| list_price | Decimal(14,2) | 建議零售價 |
| requires_serial | bool | 是否逐台追蹤序號（手機=True, 配件=False） |
| allows_telecom_line | bool | 是否能綁門號合約（露出 SIM/門號/方案/上線日 欄位） |
| allows_commission | bool | 是否能填業務員佣金 |
| is_active | bool | 啟用 |

**約束**：`(tenant, sku)` unique、`(tenant, name)` unique。
**邏輯**：`save()` 時若無 sku 則從 category 取下一個。
**屬性旗標**：銷貨單明細根據 product 的三個旗標決定能填哪些欄位:
- `requires_serial=False`:純數量出貨,不綁序號（MVP 限制只支援 True,Phase 1.3 開放）
- `allows_telecom_line=False`:銷貨明細若填 `sim_card_no` / `msisdn` / `telecom_plan_code` / `activation_date` 過帳時擋下
- `allows_commission=False`:銷貨明細若填 `commission > 0` 過帳時擋下

### `inventory.ProductSerial`

| 欄位 | 型別 | 說明 |
|------|------|------|
| product | FK Product PROTECT | 商品 |
| serial_no | CharField(80) | IMEI / SN |
| warehouse | FK Warehouse PROTECT nullable | 所在倉庫 |
| status | choices | `in_stock` / `in_transit` / `sold` / `returned` / `rma` / `void`（Phase 1 再加 `borrowed` / `defective`） |
| purchase_unit_cost | Decimal(14,2) | landed cost 攤提後的真實單台成本 |
| purchase_order_item | FK PurchaseOrderItem PROTECT nullable | 來源進貨明細 |
| received_at | DateTime nullable | 進貨時間 |
| sold_at | DateTime nullable | 銷售時間 |

**約束**：`(tenant, serial_no)` unique。

### `inventory.StockMovement`

| 欄位 | 型別 | 說明 |
|------|------|------|
| serial | FK ProductSerial PROTECT | 異動序號 |
| movement_type | choices | `purchase_in` / `sale_out` / `transfer_out` / `transfer_in` / `return_in` / `adjust` / `void`（Phase 1 加 `borrow_out` / `borrow_in` / `defect`） |
| from_warehouse | FK Warehouse nullable | 來源倉 |
| to_warehouse | FK Warehouse nullable | 目的倉 |
| ref_doc_type | CharField(40) | 來源單據類型字串 |
| ref_doc_id | BigInteger nullable | 來源單據 ID |
| note | CharField(200) | 備註 |

### `parties.Supplier`

code(20), name(120), contact(60), phone(40), tax_id(20), address(200), note(200), is_active。
**約束**：`(tenant, code)` unique。

### `parties.Customer`

code(20), name(120), phone(40), tax_id(20), address(200), note(200), is_active。
**約束**：`(tenant, code)` unique。

### `purchasing.PurchaseOrder`

| 欄位 | 型別 | 說明 |
|------|------|------|
| no | CharField(30) editable=False | 系統自動產生 `PO-{6位流水}` |
| supplier | FK Supplier PROTECT | 供應商 |
| warehouse | FK Warehouse PROTECT | 入庫倉 |
| doc_date | Date | 單據日期 |
| extra_cost_total | Decimal(14,2) | 附加費用合計（運費/關稅/保險） |
| note | CharField(200) | 備註 |
| created_by | FK User PROTECT nullable | 作業者 |
| status | choices | `draft` / `posted` / `void` |
| posted_at | DateTime nullable | 過帳時間 |
| subtotal | Decimal(14,2) editable=False | 貨款小計（過帳後寫入） |
| total_cost | Decimal(14,2) editable=False | 含費用總額（過帳後寫入） |

### `purchasing.PurchaseOrderItem`

| 欄位 | 型別 | 說明 |
|------|------|------|
| po | FK PurchaseOrder CASCADE | 進貨單 |
| line_no | uint | 行號 |
| product | FK Product PROTECT | 商品 |
| qty | uint | 數量 |
| unit_price | Decimal(14,2) | 單價 |
| amount | Decimal(14,2) editable=False | 系統計算 = qty × unit_price |
| serial_numbers | JSONField list[str] | 逐台 IMEI / SN（過帳時建 ProductSerial） |
| allocated_extra_cost | Decimal(14,2) editable=False | 分攤附加費（過帳寫入） |
| unit_landed_cost | Decimal(14,2) editable=False | 攤提後單台成本（過帳寫入） |

---

## Phase 1 — MVP 進銷存核心

### `sales.SalesOrder` — 銷貨單

| 欄位 | 型別 | 說明 |
|------|------|------|
| no | CharField(30) editable=False | 系統自動產生 `SO-{6位流水}` |
| customer | FK Customer PROTECT nullable | 客戶（散客可不填） |
| warehouse | FK Warehouse PROTECT | 出貨倉 |
| doc_date | Date | 單據日期 |
| sales_type | choices | `sale` / `rental` / `online` 等（對齊舊系統的「銷貨單別」如 E11） |
| tax_method | choices | `taxable_included` / `taxable_excluded` / `tax_free` / `zero_tax` |
| subtotal | Decimal(14,2) editable=False | 未稅金額 |
| tax_amount | Decimal(14,2) editable=False | 稅額 |
| total | Decimal(14,2) editable=False | 應收總額 |
| invoice_no | CharField(20) | 發票號碼（先放欄位，Phase 3 接電子發票） |
| note | CharField(200) | 備註 |
| sales_person | FK User PROTECT nullable | 業務員（業績歸屬） |
| created_by | FK User PROTECT nullable | 作業者 |
| status | choices | `draft` / `posted` / `void` |
| posted_at | DateTime nullable | 過帳時間 |

### `sales.SalesOrderItem` — 銷貨明細（含電信欄位）

| 欄位 | 型別 | 說明 |
|------|------|------|
| so | FK SalesOrder CASCADE | 銷貨單 |
| line_no | uint | 行號 |
| product | FK Product PROTECT | 商品 |
| qty | uint | 數量 |
| unit_price | Decimal(14,2) | 單價 |
| amount | Decimal(14,2) editable=False | 系統計算 |
| serial | FK ProductSerial PROTECT nullable | 出貨序號（MVP 一行對一台,要多台拆多行） |
| cost_at_post | Decimal(14,2) editable=False | 過帳當下加權平均成本（保留歷史） |
| sim_card | FK SimCard PROTECT nullable | 綁定的 SIM 卡（Phase 2） |
| msisdn | CharField(20) | 門號（先放欄位） |
| telecom_plan_code | CharField(20) | 促銷方案代碼（先放欄位） |
| commission | Decimal(14,2) | 業務員佣金（Phase 2 自動帶入） |
| activation_date | Date nullable | 上線日 |
| note | CharField(200) | 備註 |

### `sales.SalesReturn / SalesReturnItem` — 銷退單

結構同 SalesOrder 但 ref 到原銷貨單；過帳時序號狀態 → `returned`。

### `transfers.TransferOrder` — 調撥單

| 欄位 | 型別 | 說明 |
|------|------|------|
| no | CharField(30) editable=False | `TR-{6位流水}` |
| from_warehouse | FK Warehouse PROTECT | 來源倉 |
| to_warehouse | FK Warehouse PROTECT | 目的倉 |
| doc_date | Date | 單據日期 |
| note | CharField(200) | 備註 |
| created_by | FK User PROTECT nullable | 作業者 |
| status | choices | `draft` / `in_transit` / `received` / `void` |
| dispatched_at | DateTime nullable | 出庫時間 |
| received_at | DateTime nullable | 入庫時間 |

### `transfers.TransferOrderItem` — 調撥明細

| 欄位 | 型別 | 說明 |
|------|------|------|
| tr | FK TransferOrder CASCADE | 調撥單 |
| line_no | uint | 行號 |
| serial | FK ProductSerial PROTECT | 要調的序號 |

### `inventory.BorrowOrder / BorrowOrderItem` — 借出單（MM027）

- `BorrowOrder`：no、borrower_name、borrow_purpose（送修/示範/其他）、warehouse、expected_return_date、actual_return_date、status (`active` / `returned`)、created_by
- `BorrowOrderItem`：bo、line_no、serial（FK ProductSerial）
- 借出時序號 → `borrowed`、歸還時 → `in_stock`

### `inventory.SerialMaintenanceLog` — IMEI 狀態維護記錄（MM028/29）

| 欄位 | 型別 | 說明 |
|------|------|------|
| serial | FK ProductSerial PROTECT | 異動序號 |
| changed_by | FK User PROTECT | 操作者 |
| old_status | choices | 改前 |
| new_status | choices | 改後 |
| reason | CharField(200) | 異動原因 |

### `inventory.DefectReport` — IMEI 新品不良（MM021）

| 欄位 | 型別 | 說明 |
|------|------|------|
| serial | FK ProductSerial PROTECT | 不良序號 |
| reported_by | FK User PROTECT | 通報者 |
| symptom | CharField(200) | 故障說明 |
| handled_action | choices | `return_to_supplier` / `repair` / `void` |
| handled_at | DateTime nullable | 處理時間 |

---

## Phase 2 — SIM 卡與佣金

### `telecom.Carrier` — 電信商

| 欄位 | 型別 | 說明 |
|------|------|------|
| code | SlugField(10) | 代碼 (CHT/FET/TWM/APT/TStar) |
| name | CharField(40) | 名稱（中華電信、遠傳…） |
| contact | CharField(80) | 聯絡資訊 |
| is_active | bool | 啟用 |

### `telecom.TelecomPlan` — 促銷方案

| 欄位 | 型別 | 說明 |
|------|------|------|
| carrier | FK Carrier PROTECT | 電信商 |
| code | CharField(20) | 方案代碼 |
| name | CharField(120) | 方案名稱 |
| monthly_fee | Decimal(10,2) | 月租 |
| contract_years | uint | 合約年限 |
| commission | Decimal(10,2) | 預估佣金 |
| effective_from | Date | 生效日 |
| effective_to | Date nullable | 失效日 |
| is_active | bool | 啟用 |

**約束**：`(tenant, carrier, code)` unique。

### `telecom.SimCard` — 單張 SIM 卡

| 欄位 | 型別 | 說明 |
|------|------|------|
| carrier | FK Carrier PROTECT | 電信商 |
| iccid | CharField(25) | ICC ID |
| msisdn | CharField(20) blank | 門號 |
| warehouse | FK Warehouse nullable | 所在倉 |
| status | choices | `in_stock` / `activated` / `returned` / `lost` |
| received_at | DateTime nullable | 進卡時間 |
| activated_at | DateTime nullable | 開通時間 |

**約束**：`(tenant, iccid)` unique。

### `telecom.SimCardBatch` — 批卡作業

batch_no、carrier、batch_type (`out` / `return`)、customer (FK Customer)、created_by、note。

### `telecom.LineActivation` — 門號上線

| 欄位 | 型別 | 說明 |
|------|------|------|
| no | CharField(30) | `ACT-{6位流水}` |
| sim_card | FK SimCard PROTECT | SIM 卡 |
| plan | FK TelecomPlan PROTECT | 方案 |
| customer | FK Customer PROTECT | 客戶 |
| sales_order_item | FK SalesOrderItem PROTECT nullable | 對應的銷貨明細 |
| activation_date | Date | 上線日 |
| contract_end_date | Date | 合約到期 |
| commission_estimated | Decimal(10,2) | 預估佣金 |
| commission_actual | Decimal(10,2) nullable | 實收佣金（對帳後寫入） |
| status | choices | `active` / `expired` / `cancelled` |

### `telecom.CommissionStatement / CommissionEntry` — 佣金對帳

- Statement：no、carrier、month、total_estimated、total_actual、status (`pending` / `reconciled`)
- Entry：statement、line_activation、estimated、actual、note

---

## Phase 3 — 維修 + 應收應付 + 發票

### 維修

- `repair.Brand`：code、name
- `repair.ProductModelRef`：brand、code、name（這個獨立於 catalog.Product;舊系統「廠牌/型號」是維修專屬主檔）
- `repair.RepairCenter`：code、name、contact、address
- `repair.SparePart`：code、name、cost、price
- `repair.Symptom`：code、name
- `repair.Resolution`：code、name

### `repair.RepairOrder` — 維修單

| 欄位 | 型別 | 說明 |
|------|------|------|
| no | CharField(30) | `RP-{6位流水}` |
| customer | FK Customer | 客戶 |
| brand | FK Brand | 廠牌 |
| product_model | FK ProductModelRef | 型號 |
| imei | CharField(80) | 送修 IMEI（可能不在系統內） |
| symptom | FK Symptom | 故障 |
| received_at | DateTime | 收件時間 |
| repair_center | FK RepairCenter nullable | 送修中心 |
| resolution | FK Resolution nullable | 處理方式 |
| quote_amount | Decimal(10,2) nullable | 報價 |
| customer_approved | bool nullable | 客戶確認 |
| closed_at | DateTime nullable | 結案時間 |
| status | choices | `received` / `sent_out` / `quoted` / `approved` / `done` / `cancelled` |

### 應收應付

- `finance.Receivable`：so / customer / amount / due_date / paid_amount / status (`open` / `partial` / `closed`)
- `finance.ReceivablePayment`：receivable / paid_at / amount / method / note
- `finance.Payable`：po / supplier / amount / due_date / paid_amount / status
- `finance.PayablePayment`：payable / paid_at / amount / method / note

### 發票

- `finance.InvoiceBook`：track_code（字軌如 ZY）、start_no、end_no、issued_count、is_active
- `finance.Invoice`：no、book、so、buyer_tax_id、issue_date、subtotal、tax_amount、total、void

### 訂金 + 沖帳

- `finance.DepositReceipt`：no、customer、amount、related_so nullable
- `finance.OffsetEntry`：sweep 應收/應付的關聯（多對多）

---

## Phase 4 — 中古機 + 管銷 + 報表

### 中古機

- `used.UsedDeviceIntake`：no、seller_customer、device_imei、purchase_price、condition_grade、status
- `used.UsedDevice`：intake、imei、brand、model、condition、appraised_price、resell_price、status（`pending_review` / `available` / `sold` / `void`）
- `used.UsedSale`：sales_order_item、used_device

### 管銷費用

- `expense.ExpenseCategory`：code、name（水電 / 租金 / 紙箱 / 行銷 / 雜支）
- `expense.ExpenseItem`：category、code、name
- `expense.Expense`：no、item、warehouse、amount、occurred_at、paid_by、note、attached_receipt

### 員工與權限

- `employee.Employee`：user (OneToOne)、employee_no、warehouse、role、phone、hire_date、leave_date
- `auth.ReportPermission`：role、report_code（如 SA040）、can_view
- `auth.ShiftHandover`：no、warehouse、shift_date、open_by、close_by、cash_open、cash_close、note

### 進階報表（不需新 model,皆由既有資料計算）

| 報表 | 主要查詢 |
|------|---------|
| SA040 毛利彙總 | SalesOrderItem 群組 by 多維度,calc 毛利=amount−cost_at_post |
| SA046 銷退貨排行 | SalesOrderItem 群組 by 多維度,排序 |
| SA033 / SA076 營業日報表 | SalesOrder by doc_date |
| FI001 存量金額 | ProductSerial(status=in_stock) sum purchase_unit_cost |

---

## 命名與約定

- 所有單號：英文前綴 + `-` + 6 位流水（PO / SO / TR / RP / ACT...）
- 所有金額欄位：`Decimal(14, 2)`
- 所有 FK 預設 `on_delete=PROTECT`，刪除主檔不會級聯（明細用 `CASCADE`）
- 所有狀態用 `models.TextChoices`，labels 用繁體中文
- 所有 model 加 `verbose_name` / `verbose_name_plural` 繁體中文
- 業務動作（過帳 / 確認 / 沖帳）走 service 層（`apps/{app}/services.py`），不寫進 `save()`
- 所有「狀態變更」動作必須留 audit log（誰、何時、改前後值）
