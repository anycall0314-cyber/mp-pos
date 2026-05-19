# 設計決策紀錄

> 採用簡易 ADR 風格。每條決策包含日期、選擇、理由、未採用的替代方案。

## 2026-05-17：唯一日常介面是 React,Django admin 退到背後

**選擇**:所有日常作業介面(CRUD / 過帳 / 查詢 / 設定)都在 React app 完成。Django admin 不刪,但只當 dev 階段測資工具與緊急維運 fallback,不引導使用者使用。

**理由**:使用者不想開兩個入口(Django admin + React)做日常作業。Django admin 雖然開箱即用,但 UX 不夠密集、不能像 Excel,且讓使用者面對兩種完全不同介面風格會混亂。

**對應設計約定**:
- 凡是 Django admin 上能做的事,React app 都必須做出對應 UI
- 包括但不限於:商品/類別/倉庫/供應商/客戶/序號 主檔 CRUD、進貨單與銷貨單錄入與過帳、序號狀態維護、單據作廢
- README 不引導使用者打開 `/admin/`
- Phase 5 SaaS 化時,平台跨租戶後台**也用 React 做**,不用 Django admin

**未採用**:用 Django admin 當 Tenant Admin 介面(欲蓋彌彰、體驗不一致)。

## 2026-05-17:UX 模式 — 三種頁面版型而非單一 Master-Detail

**選擇**：新系統 UI 分三種版型，按頁面用途套用：

| 版型 | 用途 | 對應舊系統 |
|------|------|-----------|
| **錄入頁 (Entry Page)** | 開單據（進貨/銷貨/調撥/維修），鍵盤為主，連續輸入 IMEI 與明細 | 後台 ACNI002 風格 |
| **Master-Detail** | 主檔維護（商品/客戶/供應商/類別），左列表 + 右詳情，鍵鼠混用 | 既有設計 |
| **報表頁 (Report Page)** | 查詢報表，上方篩選列 + 中央結果表 + 底部總計 + 匯出（CSV/Excel/PDF） | 前台 100+ 個編號報表 |

**理由**：原本只設計 Master-Detail 一種版型，無法覆蓋舊系統的兩個真實使用模式。錄入頁與報表頁的需求差異大（鍵盤友善 vs 篩選與匯出），不能用同一個元件硬套。

**對應設計約定**：
- 錄入頁必須支援 Tab 自動跳欄、Enter 提交、ESC 取消、條碼掃描連續輸入、F-key 快捷工具列
- 報表頁必須支援多重篩選、匯出（CSV / Excel）、保留舊系統的 MMxxx 編號（建立 command palette 用編號或關鍵字跳轉）
- 三種版型細節寫在 [ui-patterns.md](ui-patterns.md)

**未採用**：用 Master-Detail 通用元件硬套所有頁面（會讓錄入慢、報表查不到）。

## 2026-05-17：版型 — Master-Detail 雙欄

**選擇**：所有業務頁面採左欄列表 + 右欄詳情的雙欄版型，禁用卡片式瀏覽。

**理由**：使用者明確排斥卡片牆造成的滾動成本，要求單頁瀏覽完。3C 進銷存的列表單元多（型號、序號、單據），雙欄能在不滾動的情況下兼顧檢索與細部編輯。

**未採用**：卡片牆、單一大表格 inline 編輯。

## 2026-05-17：技術棧 — Django + DRF + PostgreSQL / React + Vite + TS

**選擇**：後端 Django 5 + DRF + PostgreSQL；前端 React 18 + Vite + TypeScript；monorepo `backend/` `frontend/`。

**理由**：Django 內建 admin/auth/migration 對「表單多、權限細、報表多」的進銷存生產力高；FastAPI 的 async 強項在這個場景用不到。前端用 React + Vite 是最不挑團隊的搭配。

**未採用**：Next.js（不需要 SSR）、Laravel（PHP 生態的工程習慣不在本專案目標）、FastAPI（admin 要從零做）。

## 2026-05-17：序號層級 — Product / ProductSerial 兩層

**選擇**：商品分 `Product`（SKU 型號）+ `ProductSerial`（單台序號）兩層；庫存以序號為單位。

**理由**：3C 業每台 IMEI/SN 都不同，必須逐台追蹤位置與狀態，才能支援保固、維修、調撥、防竄貨。

**未採用**：純 SKU 數量法（無法支援序號生命週期）。

## 2026-05-17：成本法 — 加權平均（同時保留逐台採購成本）

**選擇**：銷貨成本走加權平均；但每台 `ProductSerial.purchase_unit_cost` 仍記錄 landed cost 攤提後的真實採購成本。

**理由**：使用者明確選擇加權平均（帳務乾淨、業務員無法挑批號）；但保留逐台成本只是多一個欄位的事，未來想切換到「逐台實際成本」或做毛利分析，不用回頭補資料。

**未採用**：純 FIFO（與序號追蹤邏輯衝突）、純逐台實際成本（業務員可挑批號衝績效）。

## 2026-05-17：附加費用 — 按金額比例攤到進貨明細

**選擇**：進貨單的運費/關稅/保險等 `extra_cost_total`，按各明細 `qty * unit_price` 占總金額比例攤到每筆明細。

**理由**：landed cost 標準做法，貼合實際成本。按數量平攤會在貨價落差大時失真。

**未採用**：按數量平攤、不入成本（另記費用帳）。

## 2026-05-17：角色架構 — 三層角色，前端單一 SPA

**選擇**：定義三層角色 Platform Admin（系統提供者）/ Tenant Admin（經銷商老闆）/ Tenant User（店員）。Platform Admin 走 Django `/admin/`；Tenant Admin 與 Tenant User **共用同一個 React app**，靠登入角色決定能看到哪些導航項與按鈕，實際資料邊界由 DRF permission 把關。

**理由**：拆兩個前端 app 會代碼重複、部署複雜度倍增。同 app 切換角色是主流 SaaS 做法，安全邊界落在後端 API 才是正解，前端只是 UX 過濾。

**未採用**：拆兩個 React app（Shopify 風格）、把老闆功能也丟到 Django admin。

## 2026-05-17：多租戶 — 預留但 MVP 不啟用 UI

**選擇**：所有業務表自帶 `tenant_id`、queryset 統一經過 `for_tenant()`、middleware 在 MVP 階段把 `request.tenant` 寫死成 `DEFAULT_TENANT_ID=1`。

**理由**：未來轉 SaaS 不用回頭重寫；當前不暴露在 UI 上以免增加認知負擔。

**未採用**：等需要時再加（過去經驗：補 tenant_id 是高風險重構）。

## 2026-05-18:移除進貨「附加費用」+ 「過帳」改一步、改用課稅別

**選擇**:
- 進貨單 `extra_cost_total` 欄位移除,landed cost 攤提改用「課稅別 + 計價數量」實現
- 銷貨、進貨都加 `tax_method`(應稅內含/外加/免稅/零稅)
- `unit_landed_cost` = 未稅單價(含稅時 = unit_price / 1.05)

**理由**:多數通訊行不單列運費,習慣把附加費用直接攤在單價;改用稅別可以更貼近開發票時填的欄位。

**影響**:現有資料 extra_cost_total 已遺失(都是測試資料,可接受)。

## 2026-05-18:進貨明細加 billed_qty(計價數量),處理贈品

**選擇**:`PurchaseOrderItem` 新增 `billed_qty`,獨立於進貨數量(`qty`)。
- 金額 = `billed_qty × unit_price`
- 單台落地成本 = (未稅 billed_total) / qty → 贈品稀釋平均成本

**理由**:廠商常送贈品/試用品,進貨數量 > 計價數量。舊系統做法一致。

**未採用**:直接打折(無法精準對到原進價);零單價輸入(會破壞 weighted_avg_cost)。

## 2026-05-18:銷貨明細 1 對多序號(SalesOrderItemSerial 中介表)

**選擇**:銷貨明細 `qty` 可 > 1,序號改 M2M(透過 `SalesOrderItemSerial` 中介表),允許「同款手機賣 2 支」一行。

**理由**:同一商品多台是日常情境(賣兩支白機給家庭客)。原本一台一行 → 一行最多 1 序號太僵硬。

**未採用**:單一 FK + 限制 qty=1(逼使用者開多行)。

## 2026-05-18:儲存即生效 + 作廢機制(取代兩步式「過帳」)

**選擇**:
- 進貨、銷貨單 POST 成功就 commit(寫序號、寫加權平均、寫異動)
- 不要可改可刪,要取消用「作廢」action `is_void=True`
- 作廢有規則:進貨作廢需所有序號仍在 in_stock;銷貨作廢把序號退回 in_stock

**理由**:舊系統「未過帳/已過帳」兩段式造成大量誤操作。一步式 + 作廢更直觀,責任歸屬也清楚。

**未採用**:可編輯模式(難以維持加權平均一致性)。

## 2026-05-18:商品搜尋 — pg_trgm + 自製 TrigramSearchFilter

**選擇**:升級到 PostgreSQL,啟用 pg_trgm 擴充,寫一個自製 SearchFilter:
1. 先試 `icontains`(子字串)
2. 沒結果且 query ≥ 3 字 → fallback 用 `TrigramWordSimilarity`,門檻 0.35
3. 取代 DRF 內建 SearchFilter,全域生效

**理由**:萬筆級別商品要支援打錯字也能找到(「iphne」找到「iPhone 15 Pro」)。icontains 是常態路徑、trgm 是補救路徑,避免短關鍵字誤判。

**未採用**:純 ILIKE(打錯字找不到)、Elasticsearch(殺雞用牛刀)。

## 2026-05-18:前端下拉一律 server-side ComboBox

**選擇**:所有資源選單(商品、客戶、供應商、序號、方案、SIM 卡、業務員、單別)都用 `ComboBox` 元件 + `api/search.ts` 裡的 `searchXxx`。不再一次抓全表用 `<select>`。

**理由**:萬筆規模 `<select>` 不可用。打字 debounce 200ms 拉 ≤ 20 筆。`payload` 帶完整物件避免後續再 round-trip。

## 2026-05-18:銷貨單發票自動取號(InvoiceTrack 字軌)

**選擇**:在「系統設定」維護發票字軌(AB 12345678–887);銷貨單建單時依 `invoice_form` 從字軌 `SELECT FOR UPDATE` 原子地取下一張號碼,使用者不需手動輸入。

**理由**:法定要求發票號碼連續、避免重號;手動輸入容易出錯且無原子保證。

**未採用**:接 e-invoice 平台(複雜度過高,Phase 3 再說)。

## 2026-05-18:付款方式主檔 + N 筆付款拆分

**選擇**:銷貨單支援 N 筆 `SalesOrderPayment`,`sum(amount) == total` 才能存。付款方式從 `PaymentMethod` 主檔(`tenants.PaymentMethod`)讀,使用者可自由新增(LinePay / 街口 / 全支付 / 匯款 / Apple Pay)。

**分類三類**:
- `cash`:現金 — 影響當日營業現金
- `transfer`:匯款 — 不影響當日現金
- `non_cash`:非現金(信用卡、行動支付)— 不影響當日現金

**理由**:通訊行付款通路多元、且需要區分「真現金」做日報。

**未採用**:固定 enum(無法擴充)、單一付款欄位(無法部分現金部分刷卡)。

## 2026-05-18:結帳成功後不關 modal,改顯示成功狀態 + 列印按鈕

**選擇**:確認結帳 → 後端寫單 → modal 切換為「結帳完成」狀態,顯示單號 / 發票號 / 付款明細 + 「列印收據」「列印發票」「完成」按鈕。完成才關閉 + 跳列表。

**理由**:舊流程「儲存 → 跳列表 → 再點進去列印」太多步;一氣呵成更貼合 POS 操作節奏。

## 2026-05-18:新單草稿持久化 sessionStorage

**選擇**:`/sales/new` 與 `/purchases/new` 自動 debounce 寫 sessionStorage,切到其他分頁回來不會丟資料,儲存成功自動清空,工具列有「清空草稿」鈕。

**理由**:使用者抱怨切分頁會掉資料。sessionStorage 範圍剛好(關掉瀏覽器才丟)。

**未採用**:多分頁同時開新單(像 IDE tab,工程量大,後續可再做)。

## 2026-05-18:自動產生內部 code,UI 隱藏

**選擇**:
- 商品 SKU、電信方案 code、PO/SO no、InvoiceType code、PaymentMethod code 全部系統產生
- 前端**不顯示也不輸入**(僅商品 SKU 顯示在 ComboBox 副資訊與標籤列印)
- PaymentMethod 沒填 code → 後端自動產生 `pm_xxxxxx`(6 字元 hex)

**理由**:使用者只認名稱,不該被迫想代碼。

