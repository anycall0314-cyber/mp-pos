# MP POS · 通訊行進銷存

> Claude 每次對話自動讀這個檔案。維護原則:**精簡、最新、有用**。深入內容散到 `docs/`。

## 一句話介紹

3C / 通訊行進銷存系統,後端 Django + DRF + PostgreSQL,前端 React + Vite + TypeScript。
取代舊系統「歐睿手機玩家 + 歐睿創意 POS」。MVP 單租戶,多租戶架構已就緒(`tenant_id` 全表帶,API 走 `for_tenant`)。

## 核心 stack

| 層 | 用 |
|---|---|
| Web 後端 | Django 5.1.4 + DRF + PostgreSQL 16 + psycopg 3 |
| Web 前端 | React 18 + Vite 5 + TypeScript 5 + TanStack Query + React Router |
| 搜尋 | pg_trgm GIN index + `TrigramWordSimilarity` 自製 SearchFilter |
| 條碼 | jsbarcode(Code128 SVG) |

## 必懂的設計決策(完整 ADR 在 `docs/decisions.md`)

- **儲存即生效**:單據沒有「過帳/未過帳」中間狀態,POST 成功就生效,要取消用「作廢」(`is_void=True`)
- **庫存以序號為單位**:`ProductSerial` 一台一筆,狀態 in_stock / sold / void / returned / rma / in_transit
- **成本走加權平均**:`Product.weighted_avg_cost`,進貨後重算;**虛擬商品**(`is_virtual=True`)不算成本、不建序號
- **三種頁面版型**:錄入頁(進銷/調撥)、Master-Detail(主檔)、報表頁(尚未做)
- **唯一前端**:不開 Django admin 給使用者用,Django admin 只當 dev fallback
- **單一 React app + 角色控制**:Platform Admin / Tenant Admin / Tenant User 共用 SPA(MVP 還沒實作登入)

## 業務規則速查

| 主題 | 重點 |
|---|---|
| 課稅別 | 應稅內含 / 應稅外加 / 免稅 / 零稅;含稅金額 ÷ 1.05 = 未稅 |
| 進貨成本 | `unit_landed_cost` = 未稅單價(含稅單會自動除 1.05);贈品由 `billed_qty < qty` 表示,平均成本被稀釋 |
| 發票自動取號 | 銷貨單儲存時,依 `invoice_form` 從 `InvoiceTrack` 字軌 `SELECT FOR UPDATE` 取下一張號碼,寫入 `invoice_no` |
| 結帳 | 銷貨單 N 筆 `SalesOrderPayment`(現金/匯款/非現金),`sum(amount) == total` 才能存 |
| 序號生命週期 | 進貨建單 → in_stock;銷貨 → sold;銷貨作廢 → 回 in_stock;進貨作廢 → void(須全部還在 in_stock 才能作廢) |
| 預設值連動 | 發票類型 = 免用 → 課稅別自動切免稅;選商品 → 進貨單帶上次進價 / 銷貨單帶 list_price |
| 中古機 | `Product.is_secondhand=True`;`ProductSerial` 逐隻記 `condition_grade` (S/A/B/C/D)、`custom_unit_price`、`battery_health`、`condition_note`;銷貨選機自動帶 `custom_unit_price` |
| 個人收購 | 走 `acquire_secondhand_from_member` service:同 transaction 建中古機序號 + 對應銷貨單(虛擬商品「收購二手」、`tax_free`、total 負數代表現金流出);serial 反向掛 `acquired_from_member` + `acquired_via_sales_order` |
| 廠商收購中古 | 走一般進貨單;進貨側欄會多 4 欄(成色/售價/電池/備註)+「套用到下面所有」按鈕 |
| 中古機履歷 | `GET /api/v1/serials/{id}/history/` 回傳:收購來源 (購進 or 個人收購)、所有銷貨/退貨、StockMovement 軌跡 |

## 程式碼定位

```
inventory-3c/
├── backend/                    Django 後端
│   └── apps/
│       ├── core/               TenantOwnedModel + TrigramSearchFilter
│       ├── tenants/            Tenant + 系統設定主檔(InvoiceType / InvoiceTrack / PaymentMethod)
│       ├── catalog/            Product / Category
│       ├── inventory/          Warehouse / ProductSerial / StockMovement
│       ├── parties/            Supplier / Customer / SalesPerson / Carrier / TelecomPlan / SimCard
│       ├── purchasing/         PurchaseOrder + commit/void service
│       └── sales/              SalesOrder + commit/void/payment service
│
└── frontend/
    └── src/
        ├── api/                client.ts + hooks.ts + search.ts + types.ts
        ├── components/         ComboBox(server-side 搜尋下拉)/ Drawer / Field / Toolbar / Banner
        ├── pages/
        │   ├── products/        ProductsPage + ProductForm
        │   ├── purchases/       PurchasesPage + PurchaseEntryPage + PurchaseLabelsPrintPage
        │   ├── sales/           SalesPage + SalesEntryPage + SalesPrintPage
        │   ├── members/         MembersPage(會員查詢)
        │   ├── settings/        SettingsPage(發票類型 / 字軌 / 付款方式)
        │   ├── sim-cards/       SimCardsPage + SimCardForm
        │   ├── telecom-plans/   TelecomPlansPage + TelecomPlanForm
        │   └── secondhand-acquisition/  SecondhandAcquisitionPage(個人收購入庫)
        ├── App.tsx              路由與導覽(NAV_GROUPS 結構)
        └── styles.css           全站 CSS,暗色主題
```

## 慣例(Convention)

- **後端 service**:每個業務動作(commit / void)寫成 `apps/<app>/services.py` 的純函式,viewset 只負責 HTTP + 包 transaction
- **前端 hook**:所有 API 呼叫包成 `useXxx` / `useSaveXxx` / `useVoidXxx`,放 `api/hooks.ts`
- **搜尋 / 下拉**:萬筆級別都用 `ComboBox` + `api/search.ts` 裡面的 `searchXxx`,**不要**載入整張表
- **自動產生欄位**:`sku` / `code` / `no` 系統產生,前端**不顯示也不輸入**
- **儲存草稿**:`/sales/new` 與 `/purchases/new` 自動 debounce 寫 sessionStorage,儲存成功後清空
- **migration 涉及資料改動**:在 migration 內寫 `RunPython` 一併處理(例如 billed_qty 預設帶 qty、seed PaymentMethod)
- **不可預測的字串(IMEI、卡號)**:存原值,前端顯示時取末 N 碼

## 使用者偏好

- 繁體中文回應、UI 一律繁中
- **禁用 emoji**(裝飾性符號全面拒絕)
- 偏好先規劃再實作(大改動會先列範圍 / Trade-off 再動工)
- 給「跟 XXX 一樣的模式」這種指示時,參照 `docs/ui-patterns.md` 與既有頁面
- **非工程師**:不直接寫 git,要求 commit / push 才動;不直接改 .env 之類底層設定,問過再改

## 何時更新 CLAUDE.md

當下列任一發生:
1. 加新模組(新增 `apps/` 或 `pages/` 目錄)→ 更新「程式碼定位」
2. 業務規則改變(課稅、結帳、序號生命週期)→ 更新「業務規則速查」
3. 設計決策被推翻或新增 → 在 `docs/decisions.md` 加 ADR + 摘要到這裡

別把這裡塞滿,**精準 + 最新**比完整重要。深入內容寫到 `docs/`。
