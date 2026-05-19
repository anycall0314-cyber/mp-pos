# 通訊行 POS 路線圖

> 目標：取代舊系統「歐睿手機玩家 / 歐睿創意POS」。後台（IE-only）已死、前台查詢還活著。新系統重做整套，但分階段交付。
>
> 對齊舊系統業界實務的功能對照表見 [legacy-pos-functions.md](legacy-pos-functions.md)。
> 各 model 欄位細節見 [data-model.md](data-model.md)。
> 設計決策紀錄見 [decisions.md](decisions.md)。

## 整體分階段

| Phase | 主題 | 對應舊系統模組 | 範圍 |
|-------|------|----------------|------|
| 0 | 專案骨幹 | — | 已完成（scaffold + 商品/類別/序號 model + 商品 API + 前端商品頁） |
| 1 | 通訊行進銷存核心 (MVP) | 庫存管理 + 訂單 + 採購 + 調撥 + 部分基本資料 | 進行中 |
| 2 | SIM 卡 + 上線佣金 | SIM 卡管理 + 上線專案 + 佣金對帳 | 之後 |
| 3 | 維修 + 應收應付 + 發票 | 維修系統 + 財務報表（應收/應付/發票/沖帳） | 之後 |
| 4 | 中古機 + 管銷 + 進階報表 | 大量中古 + 管銷費用 + 營業分析 | 之後 |
| 5 | SaaS 化 | — | 啟用多租戶 UI / 訂閱 / 平台後台 |

---

## Phase 0 — 專案骨幹（已完成）

**已交付**：
- monorepo 結構：`backend/` Django 5.1 + DRF + SQLite (dev) / Postgres (prod-ready)，`frontend/` React 18 + Vite + TypeScript + TanStack Query/Table + React Router
- 三層角色架構：Platform Admin（Django admin）/ Tenant Admin / Tenant User（共用 React app）
- Tenant 預留：所有業務表帶 `tenant_id`，MVP 寫死 `DEFAULT_TENANT_ID=1`，middleware 自動掛 `request.tenant`
- 已實作 model（含 admin、serializer、API）：
  - `tenants.Tenant`
  - `inventory.Warehouse / ProductSerial / StockMovement`
  - `catalog.Category / Product`（含 SKU 自動產生 `{類別}-{6位流水}` + 加權平均成本欄位）
  - `parties.Supplier / Customer`
  - `purchasing.PurchaseOrder / PurchaseOrderItem`（**無過帳邏輯**）
- 前端：`MasterDetail` 通用元件、商品頁串真實 API、5 個業務頁路由佔位
- 介面中文化：所有 model verbose_name、app verbose_name

---

## Phase 1 — 通訊行進銷存核心 (MVP)

**目標**：取代舊系統的「採購進貨 / 庫存 / 訂單銷貨 / 調撥」核心動線，業務員與老闆能完整跑進銷存。

### 1.1 進貨單過帳 service（接續 Phase 0）

- 為 `PurchaseOrder` 加 `post()` service：landed cost 攤提 + 加權平均重算 + 批次建 `ProductSerial` + 寫 `StockMovement`
- `PurchaseOrder.status`：`draft → posted` 轉換
- API endpoint：`POST /api/v1/purchase-orders/{id}/post/`
- Admin custom action：「過帳」按鈕

### 1.2 銷貨單 + 銷退單

- `sales.SalesOrder / SalesOrderItem` model：
  - 單頭：no、customer (nullable，散客)、warehouse、doc_date、tax_method、subtotal、tax_amount、total、created_by、status
  - 明細：so、line_no、product、qty、unit_price、amount、**serial (FK ProductSerial)**、**sim_card_no / msisdn / telecom_plan_code / commission / activation_date**（電信欄位先放欄位 schema，UI 隱藏）
- 過帳邏輯：銷貨成本 = `Product.weighted_avg_cost × qty`；序號狀態 → `sold` + `sold_at`；寫 `StockMovement`
- `sales.SalesReturn / SalesReturnItem`：退貨單；序號狀態 → `returned`
- 對應舊系統：訂單 - 銷貨作業 (ACNI002) + 訂單 - 銷退作業

### 1.3 調撥單（兩步式）

- `transfers.TransferOrder / TransferOrderItem`：
  - 兩步式：`建立 → 確認`（這條跟其他單據不同；舊系統明確分兩個 admin 動作）
  - 建立時序號狀態 → `in_transit`、寫 `StockMovement(TRANSFER_OUT)`
  - 確認時序號狀態 → `in_stock` + `warehouse=目的倉`、寫 `StockMovement(TRANSFER_IN)`
- 對應舊系統：調撥 - 調撥建立作業 + 調撥確認作業

### 1.4 IMEI 狀態手動維護

- `inventory.SerialMaintenanceLog`：每次手動改 `ProductSerial.status` 都寫一筆 audit（誰改、何時改、改前後值、原因）
- API：`POST /api/v1/serials/{id}/update-status/`，必須帶 reason
- 對應舊系統：MM028 IMEI 狀態修改維護 + MM029 IMEI 狀態修改記錄表

### 1.5 借出單

- `inventory.BorrowOrder / BorrowOrderItem`：客戶送修時借代用機、業務員借樣機
- 序號狀態新增 `borrowed`；借出建立時轉 `borrowed`、歸還時轉回 `in_stock`
- 對應舊系統：MM027 借出單作業

### 1.6 不良品流程

- `inventory.DefectReport`：新機拆封不良通報，序號狀態 → `defective`（新增）；可附報修紀錄
- 對應舊系統：MM021 IMEI 新品不良維護及記錄表

### 1.7 前台查詢頁

| 編號 | 名稱 | 實作 |
|------|------|------|
| MM004 | 商品存量查詢（by SKU） | annotate `stock_qty` 列表 |
| MM007 | 商品存量查詢（by 倉庫） | 倉庫切片視角 |
| MM013 | 庫存明細表 | 序號級列表 |
| MM017 | 庫存異動查詢 | `StockMovement` 列表 + 篩選 |
| MM019 | 商品進銷存表 | 同 SKU 期初/進貨/銷貨/期末 |
| MM020 | IMEI 明細表 | 序號搜尋與生命週期 |
| MM023 | 調撥單明細表 | `TransferOrder` 列表 |
| MM030 | 滯銷品報表 | 在庫但 N 天未售 |

### 1.8 認證與權限

- Django 內建 `User` + `Group`
- 自訂 Permission：`view_*` / `add_*` / `change_*` per model
- DRF `DEFAULT_PERMISSION_CLASSES`：登入才能用 API
- 前端：JWT 或 session login，依角色 filter 導航項

### 1.9 三種頁面版型框架（先做框架,各頁套用）

詳細規格見 [ui-patterns.md](ui-patterns.md)。

- **錄入頁框架 (EntryForm)**：
  - 鍵盤友善：Tab 跳欄、Enter 提交、ESC 取消、F-key 工具列（F2 編輯 / F5 過帳 / F8 刪除 / F10 存檔）
  - 條碼掃描器 input：focus 後可連續掃 IMEI,自動跳下一行
  - 商品快查：輸入 SKU 或品名前綴自動帶資料
  - 適用：進貨單 / 銷貨單 / 調撥單 / 借出單 / 維修單
- **Master-Detail 框架**：已有 `MasterDetail.tsx`,套用於主檔維護
  - 適用：商品 / 類別 / 倉庫 / 供應商 / 客戶
- **報表頁框架 (ReportPage)**：
  - 上方篩選列：日期區間 / 倉庫 / 類別 / 業務員 / 狀態 等可組合多重 filter
  - 中央結果表：可虛擬滾動 + 多欄排序 + 樞紐分組
  - 底部總計列 + 匯出按鈕（CSV / Excel）
  - **Command Palette (Cmd+K)**：保留舊系統 MMxxx 編號習慣,業務員可輸入「MM020」直接跳 IMEI 明細表
  - 適用：所有 MM/SA/FI 編號報表

### 1.10 前端各頁實作

| 頁面 | 套用版型 | 對應舊系統 |
|------|---------|-----------|
| 商品 | Master-Detail | ST015 / ST032 |
| 類別 / 倉庫 / 供應商 / 客戶 | Master-Detail | 基本資料 |
| 進貨單 | EntryForm | 採購-進貨作業 |
| 銷貨單 | EntryForm（含電信欄位） | ACNI002 |
| 調撥單 | EntryForm 兩步式 | 調撥建立 + 確認 |
| 借出單 | EntryForm | MM027 |
| 商品存量查詢 | ReportPage | MM004 / MM007 |
| 庫存明細表 | ReportPage | MM013 |
| 庫存異動查詢 | ReportPage | MM017 |
| 商品進銷存表 | ReportPage | MM019 |
| IMEI 明細表 | ReportPage | MM020 |
| 調撥單明細表 | ReportPage | MM023 |
| 滯銷品報表 | ReportPage | MM030 |

---

## Phase 2 — SIM 卡與上線佣金

**目標**：把通訊行的第二條收入流（賣門號上線拿佣金）整套做出來。對應舊系統 `SIM*` 整組模組。

### 新增 model

- `telecom.Carrier`：電信商（中華、台哥大、遠傳、亞太、台星）
- `telecom.TelecomPlan`：促銷方案（代碼、名稱、月租、合約年限、佣金結構）
- `telecom.SimCard`：單張 SIM 卡（ICC ID、MSISDN、carrier、狀態：庫存/已開通/已退卡）
- `telecom.SimCardBatch`：批卡作業（出卡/退卡）
- `telecom.LineActivation`：門號上線（SIM、方案、客戶、上線日、合約到期、預估佣金）
- `telecom.CommissionStatement` / `CommissionEntry`：佣金對帳單與單筆紀錄

### 對應舊系統功能

| 編號 | 名稱 |
|------|------|
| SIM001 / SIM002 | SIM 卡進卡明細 |
| SIM004 / SIM005 | SIM 卡開通明細 |
| SIM012 / SIM013 | 上線專案查詢 |
| SIM015 | 佣金預估表 |
| SIM016 / SIM028 | 門號到期查詢 / 修改 |
| SIM017 / SIM018 | 門號修改 + 記錄表 |
| SIM019 / SIM021 | 佣金對帳單 |
| SIM024 / SIM025 | 批卡作業（出卡/退卡） |
| SIM026 / SIM030 | 促銷方案維護 |
| SIM027 | 卡號異動轉換 |
| SIM031 | 門號開通數量統計 |

---

## Phase 3 — 維修 + 應收應付 + 發票

**目標**：通訊行的第三條（維修）與正規帳務（應收/應付/發票）。

### 維修

- `repair.Brand` / `ProductModel`：廠牌與型號
- `repair.RepairCenter`：維修點（送修中心）
- `repair.SparePart`：送修配件
- `repair.Symptom`：故障情形
- `repair.Resolution`：處理方式
- `repair.RepairOrder` / `RepairQuote`：維修單與報價

對應 `MNT*` 全套。

### 應收應付

- `finance.Receivable` / `ReceivablePayment`：應收帳款 + 收款
- `finance.Payable` / `PayablePayment`：應付帳款 + 付款
- `finance.Invoice` / `InvoiceBook`：發票（含字軌、起號、結號、餘數）
- `finance.DepositReceipt`：訂金
- `finance.OffsetEntry`：沖帳作業

對應 `FI*` 全套（FI011-016, FI020, FI021）。

### 代收電信費

- `finance.UtilityReceipt`：代收電信費紀錄（手續費分潤）

對應 SIM032 代收資費作業 + FI026 代收資費查詢。

---

## Phase 4 — 中古機 + 管銷 + 進階報表

### 中古機

- `used.UsedDeviceIntake`：中古機收購單（客戶賣機進來）
- `used.UsedDevice`：中古機資料（檢測結果、定價、狀態）
- `used.UsedSale`：中古機銷貨

對應「大量中古」分頁。

### 管銷費用

- `expense.ExpenseCategory`：管銷類別（水電、租金、紙箱、行銷等）
- `expense.ExpenseItem`：管銷項目（具體細目）
- `expense.Expense`：單筆支出

對應 FI017 / FI018 / FI019。

### 進階報表

| 編號 | 名稱 |
|------|------|
| SA040 | 毛利彙總表（多維度切片） |
| SA046 | 銷退貨彙總排行榜 |
| SA033 / SA076 | 營業日報表 |
| SA054 | 銷退貨數量統計 |
| FI001 | 存量金額查詢 |
| FI008 | 交班明細表 |

### 員工與權限

- `employee.Employee`（補充 User 之外的人資資料）
- `auth.ReportPermission`：細到「能不能看 SA040」的報表級權限
- `auth.ShiftHandover`：門市交班作業

對應 `SEC*` 全套。

---

## Phase 5 — SaaS 化

- 啟用多租戶：移除 `DEFAULT_TENANT_ID` middleware，改為從 JWT / subdomain 解析 tenant
- 訂閱與計費（Stripe / 綠界）
- 平台後台：跨租戶監控、計費、客戶管理、客服需求單（對應舊系統 SEC019 / SEC020 歐睿需求單）
- 多語、多時區（如果擴及海外）
- 行動裝置 APP（業務員平板用）

---

## 工期估算（粗略）

| Phase | 模組數 | 預估 |
|-------|--------|------|
| 1 | ~15 model + 完整前端 | 2-3 個月 |
| 2 | ~7 model + SIM/佣金 UI | 1-2 個月 |
| 3 | ~15 model + 維修流程 + 發票串接 | 2-3 個月 |
| 4 | ~10 model + 進階報表 | 1-2 個月 |
| 5 | SaaS 化 | 1-2 個月 |

**總計 7-12 個月**（一人全職估算；實際依進度浮動）。
