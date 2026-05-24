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
- **成本走加權平均(全公司,不分倉)**:`Product.weighted_avg_cost` 跨倉聚合;**目的是避免「店員挑低成本機賣→虛幻獎金」**。庫存查詢的單倉視窗不顯示「該倉成本」,只顯示在庫數。中古機例外:每隻獨立 `purchase_unit_cost`,賣出時用該隻自己的成本(因為每台是獨立商品)
- **計入現金 / 計入毛利雙旗標**:`Product.counts_cash` / `counts_margin`。收購二手虛擬商品 `counts_cash=True, counts_margin=False`,讓收購單在報表上「算現金流出但不汙染毛利」
- **三種頁面版型**:錄入頁(進銷/調撥)、Master-Detail(主檔)、報表頁
- **唯一前端**:不開 Django admin 給使用者用,Django admin 只當 dev fallback
- **單一 React app + 角色控制**:Platform Admin / Tenant Admin / Tenant User 共用 SPA(MVP 還沒實作登入)
- **導覽結構(6 群)**:報表 / 庫存 / 銷貨 / 門號 / 維修 / 設定。商品與類別合併在「庫存 → 建立商品」一頁;客戶管理在「銷貨」群組底下(會員為其中一個 tab,個人/同業/企業/其他分頁切換);未實作的功能保留 placeholder 顯示「(尚未實作)」

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
| 中古機類別連動 | `Category.is_secondhand_default=True` 時,該類別下所有 product `is_secondhand` 自動帶 True(`Product.save` override)。類別 default 由 False → True 儲存時,cascade 把底下所有商品 `is_secondhand/requires_serial` 設 True、`is_virtual` 設 False;反向(True → False)不 cascade,避免誤改既有資料。前端 ProductsPage 的類別新增/編輯 form 多一個「中古機類別」勾選 |
| 個人收購 | 「中古入庫」頁的「個人收購」tab(`SecondhandPersonalEntry`);走 `acquire_secondhand_from_member` service:同 transaction 建中古機序號 + 對應銷貨單(虛擬商品「收購二手」、`tax_free`、total 負數代表現金流出);serial 反向掛 `acquired_from_member` + `acquired_via_sales_order` |
| 廠商收購中古 | 「中古入庫」頁的「廠商收購」tab,內嵌 `PurchaseEntryPage mode="secondhand-vendor"`;走一般進貨單流程但商品搜尋限定 `is_secondhand=true`;進貨側欄多 4 欄(成色/售價/電池/備註)+「套用到下面所有」按鈕;儲存後不離頁,bump remount key 重置表單 + 顯示成功訊息 |
| 一般進貨單擋下中古機 | `PurchaseEntryPage` 預設 `mode="regular"`,商品 ComboBox / PickerModal / BatchPasteModal 都帶 `is_secondhand=false`;新增進貨單時挑不到中古品。檢視 / 作廢既有中古進貨單仍走 `/purchases/:id` |
| 中古機履歷 | `GET /api/v1/serials/{id}/history/` 回傳:收購來源 (購進 or 個人收購)、所有銷貨/退貨、StockMovement 軌跡 |
| 客戶識別 | `Customer.code` 系統自動產生 (C-{5 位流水},Tenant 持有 next_customer_seq);前端不顯示也不輸入。`phone` 改選填(同行/企業可不填);`lookup?phone=` 多筆優先 is_member |
| 銷貨單客戶/會員雙欄位 | `SalesOrder.member` = **主體(人)**,Customer 表 is_member=true 的子集,ComboBox 吃電話/姓名/統編,選填。`SalesOrder.customer` = **這筆生意的歸屬**,ComboBox 涵蓋所有 Customer(含個人散客),**必填**。**不互斥**——同行帶他的個人客戶來開門號 → customer=同行、member=該個人;會員 walk-in → customer=該人自己、member=該人 |
| 店頭雜支 | `PettyExpense` 記每家門市的零星支出(房租/水電/餐飲/雜物/其他);自動單號 `EX-{5位}`;`payment_method` FK 預設現金。Phase 1 純記錄,Phase 2 將連動 `Warehouse.cash_balance` |
| 進貨付款方式 | `PurchaseOrder.payment_method` FK to PaymentMethod (選填);cash 將從店頭備用金扣、transfer/non_cash 不動店頭。Phase 1 只記錄欄位 |
| 配件庫存 | 非序號商品(`requires_serial=False`、非 virtual)走 `StockBalance(product, warehouse)`,進貨累計、銷貨扣減、調撥搬移;`Product.weighted_avg_cost` 跨倉聚合 |
| 配件不足擋下 | 銷貨單若該倉 balance 不足,`commit_sales_order` 拋錯 400,不允許負庫存 |
| 調撥 | `TransferOrder` 兩階段:`dispatched`(來源倉派發,序號 → in_transit、配件 balance 扣掉)→ `confirmed`(目的倉確認,序號 → in_stock 在目的倉、目的倉 balance 加上)。`unit_cost_at_dispatch` 在派發時快照來源倉成本,確認時用以重算目的倉加權平均(避免後續異動干擾)。`void` 智能回滾,依當下狀態決定 |
| 標籤條碼優先序 | 有序號 → IMEI;否則 有原廠條碼(`Product.barcode`)→ 用原廠條碼;都沒有 → fallback SKU。bar code 下方顯示可讀值方便對照 |
| 銷貨商品搜尋 | `searchProductsForSales` 支援 品名 / 品號 / 條碼 / IMEI 任一;打 IMEI 命中時 matched_serial 也預掛該行,且該倉只有 1 隻在庫時自動掛唯一序號(中古機同步帶 custom_unit_price)|
| 銷貨可選清單 | `?sales_pickable=true` 過濾:庫存 > 0 OR `is_virtual=True`(虛擬商品永遠可選,實體 0 庫存擋下)|
| IMEI 搜尋安全閥 | ProductViewSet.`get_search_fields` 動態化:**只有純數字 6 碼以上才把 `serials__serial_no` 加進 search_fields**,避免「18 pro 256」誤命中含 18 的 IMEI |
| 搜尋權重(中文 vs 英數)| `get_search_fields` 偵測查詢字串是否含中日韓漢字(U+4E00–U+9FFF):**含中文 → 只搜描述欄 `name/spec/category__name`**(不碰品號/條碼/IMEI,避免「中古 11」被 SKU `AA-000011` 誤帶出);**純英數 → 搜完整代碼欄位**(sku/name/spec/barcode/category),純數字 6 碼以上才再加 IMEI |

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
│       ├── sales/              SalesOrder + commit/void/payment service
│       ├── transfers/          TransferOrder + commit/void service
│       └── cash/               PettyExpense 雜支單(之後放 CashAdjustment 與現金櫃服務)
│
└── frontend/
    └── src/
        ├── api/                client.ts + hooks.ts + search.ts(searchProductsForSales 等) + types.ts
        ├── components/         ComboBox(支援 onEnterAfterValue / autoFocus / IME 偵測)/ Drawer / Field / Toolbar / Banner
        ├── pages/
        │   ├── products/        ProductsPage(合併商品 + 類別管理,左側兩段:商品搜尋 / 類別拖拉排序)+ ProductForm + ProductExpanderModal(型號展開,軸標籤可自訂)+ BulkAddProductsModal
        │   ├── purchases/       PurchasesPage + PurchaseEntryPage(規格獨立欄、Enter 跳下一筆)+ PurchaseLabelsPrintPage(條碼優先序 IMEI > 原廠 > SKU)+ PurchaseBatchPasteModal(模糊比對預覽)+ PurchaseProductPickerModal(勾選多商品入庫)
        │   ├── sales/           SalesPage + SalesEntryPage(IMEI 自動掛序號 / 單一在庫自動掛 / 中文 IME 安全)+ SalesPrintPage
        │   ├── customers/       CustomersPage(客戶管理;tabs:全部/個人/同業/企業/其他/會員;Detail 下半顯示該客戶銷售紀錄。/members 已 redirect 到 /customers?tab=member)
        │   ├── reports/         SalesDailyReport(銷貨日報,按單分組純表格 + 作廢區塊 + CSV 匯出;收購二手不計毛利)
        │   ├── settings/        SettingsPage(發票類型 / 字軌 / 付款方式)
        │   ├── sim-cards/       SimCardsPage + SimCardForm
        │   ├── telecom-plans/   TelecomPlansPage + TelecomPlanForm
        │   ├── secondhand-acquisition/  SecondhandAcquisitionPage(hub:tabs 切換)+ SecondhandPersonalEntry(個人收購表單;廠商收購直接內嵌 PurchaseEntryPage)
        │   ├── inventory/       InventoryQueryPage(庫存矩陣:多倉勾選 + 每倉一欄 + 點數字看序號明細 + 欄位排序)+ CategoriesPage(舊獨立頁,nav 已隱藏但路由仍在)
        │   ├── transfers/       TransfersPage + TransferEntryPage(倉間調撥)
        │   └── cash/            PettyExpensesPage 店頭雜支(列表 + Drawer 新增,連續模式)
        ├── App.tsx              路由與導覽(NAV_GROUPS 6 群:報表/庫存/銷貨/門號/維修/設定)
        └── styles.css           全站 CSS,暗色主題
```

後端新加的 endpoint:
- `GET /api/v1/products/stock-matrix/?warehouse_ids=1,2,3` — 庫存矩陣,給庫存查詢頁多倉欄位用
- `GET /api/v1/sales-orders/?...` filterset 加 `sales_person`(報表用)

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
