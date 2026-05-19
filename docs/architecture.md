# 架構與程式碼地圖

> 看程式碼前先看這份。配合 `data-model.md`(欄位)、`decisions.md`(為何這樣設計)、`ui-patterns.md`(UI 規約)。

## 高層結構

```
┌─────────────────────────────────────────┐
│  React SPA (Vite dev:5173)               │
│  - pages/        路由頁面                  │
│  - components/   共用元件(ComboBox 等)    │
│  - api/          fetch + types + hooks    │
└─────────────────┬───────────────────────┘
                  │ /api/v1/*  (Vite proxy)
┌─────────────────▼───────────────────────┐
│  Django REST API (runserver:8000)        │
│  - viewsets:    HTTP 入口、權限、tenant 注入 │
│  - serializers: 進/出資料形狀              │
│  - services.py: 業務副作用(原子,純函式)    │
│  - models.py:   ORM + 簡單欄位邏輯         │
└─────────────────┬───────────────────────┘
                  │ psycopg 3
┌─────────────────▼───────────────────────┐
│  PostgreSQL 16 + pg_trgm 模糊搜尋         │
└─────────────────────────────────────────┘
```

## 後端 app 分工

| App | 負責 | 核心 model |
|---|---|---|
| `apps.core` | 抽象基類、共用 filter | `TenantOwnedModel`、`TrigramSearchFilter` |
| `apps.tenants` | 租戶 + 系統設定主檔 | `Tenant`、`InvoiceType`、`InvoiceTrack`、`PaymentMethod` |
| `apps.catalog` | 商品主檔 | `Product`、`Category` |
| `apps.inventory` | 倉庫 + 序號 + 異動軌跡 | `Warehouse`、`ProductSerial`、`StockMovement` |
| `apps.parties` | 對外角色 | `Supplier`、`Customer`、`SalesPerson`、`Carrier`、`TelecomPlan`、`SimCard` |
| `apps.purchasing` | 進貨單 + 進貨單別 | `PurchaseOrder`、`PurchaseOrderItem`、`PurchaseOrderCategory` |
| `apps.sales` | 銷貨單 + 序號 + 付款 | `SalesOrder`、`SalesOrderItem`、`SalesOrderItemSerial`、`SalesOrderPayment` |

## 後端關鍵抽象

### TenantOwnedModel(`apps/core/models.py`)

所有業務 model 繼承。提供:
- `tenant` FK
- `tenant_id` 隱含欄位
- `objects.for_tenant(tenant)` queryset filter

ViewSet 一律寫:
```python
def get_queryset(self):
    return MyModel.objects.for_tenant(self.request.tenant)
```

`request.tenant` 由 middleware 注入(MVP 寫死 `DEFAULT_TENANT_ID=1`)。

### TrigramSearchFilter(`apps/core/filters.py`)

繼承 DRF SearchFilter:
1. 先 icontains(子字串)
2. 若 0 結果 + query ≥ 3 字 + PG → fallback 用 `TrigramWordSimilarity`
3. 相似度 ≥ 0.35 才收

設定在 `REST_FRAMEWORK.DEFAULT_FILTER_BACKENDS`,全域生效。

### services.py(每個 app)

業務動作分離出 viewset。viewset 只負責 HTTP / serializer / tenant 注入;真正會動到多張表的邏輯放 services:

```python
# apps/purchasing/services.py
def commit_purchase_order(po):           # 過帳(寫序號、寫異動、算加權平均)
def void_purchase_order(po):             # 作廢

# apps/sales/services.py
def commit_sales_order(so):              # 過帳 + 取發票號 + 驗證付款
def void_sales_order(so):                # 序號退回、SIM 卡退回

# apps/tenants/services.py
def assign_invoice_no(tenant, code):     # 字軌 SELECT FOR UPDATE 取下一張
def peek_next_invoice_no(tenant, code):  # 預覽不取
```

所有 service 內部都用 `with transaction.atomic():`。失敗丟 `*Error` 例外,viewset 轉成 HTTP 400。

## 前端關鍵抽象

### `api/client.ts`

base `/api/v1`,封裝 fetch,失敗丟 `ApiHttpError` 帶 status + body。

### `api/hooks.ts`

每個資源都有:
- `useXxx()` — 查列表(回 array)
- `useXxx(id)` — 查單筆
- `useSaveXxx()` — 建立或更新(POST / PATCH 自動切)
- `useVoidXxx()` — 作廢 action

TanStack Query 的 `queryKey` 慣例:`["resource-name", ...params]`。Mutation 在 `onSuccess` invalidate 對應 key。

### `api/search.ts`

每個可搜尋資源一個 `searchXxx(query, opts)` 函式,給 ComboBox 用。回傳 `ComboOption<T>[]`,`payload` 帶完整實體(避免 round-trip)。

### `ComboBox`(`components/ComboBox.tsx`)

通用搜尋下拉。Server-side 搜尋(debounce 200ms),鍵盤 / 滑鼠 / 貼上都支援。
**主要用法**:`<ComboBox<Product> fetchOptions={searchProducts} selectedOption={opt} onChange={...} />`

### 三種頁面版型

詳見 `ui-patterns.md`,核心慣例:
- **錄入頁**(EntryPage)= 上 Toolbar + 中 Header form + 明細表 + 右側欄(可選) + 下 Footer
- **Master-Detail** = 左列表 + 右詳情,主檔維護用
- **報表頁** = 上 filter + 中表格 + 下總計(尚未實作)

### 自動草稿

`PurchaseEntryPage` / `SalesEntryPage` 使用 sessionStorage 持久化新單草稿:
- mount 時 lazy 讀草稿,所有 useState 從草稿載入
- 每次 state 變動 debounce 250ms 寫回 sessionStorage
- 儲存成功 → `clearDraft()` 清空
- 工具列有「清空草稿」鈕

## 資料異動軌跡

序號每次狀態變動寫一筆 `StockMovement`:

| MovementType | 觸發 |
|---|---|
| `purchase_in` | 進貨單建單,新建 `ProductSerial(in_stock)` |
| `sale_out` | 銷貨單建單,序號 → `sold` |
| `return_in` | 銷貨作廢,序號 → `in_stock` |
| `void` | 進貨作廢,序號 → `void` |
| `transfer_out` / `transfer_in` | 調撥(尚未實作) |
| `adjust` | 盤點調整(尚未實作) |

## 列印

- **銷貨收據 / 發票** `/sales/:id/print/receipt` 或 `invoice`,80mm 熱感佈局,`window.print()` 自動觸發
- **進貨標籤** `/purchases/:id/print/labels`,50×30mm 一張一頁,Code128 條碼(`jsbarcode`)
- CSS `@page` 設定紙張尺寸,瀏覽器列印對話框選對應印表機即可
