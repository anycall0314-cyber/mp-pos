# MP POS · 通訊行進銷存

> Codex 每次對話自動讀這個檔案。維護原則:**精簡、最新、有用**。深入內容散到 `docs/`。

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
- **導覽結構(6 群)**:報表 / 庫存 / 銷貨 / 門號 / 維修 / 設定。商品與類別合併在「庫存 → 建立商品」一頁;客戶管理在「銷貨」群組底下(個人/同業/企業/其他分頁切換);會員是獨立主檔(`/members`),也在「銷貨」群組;未實作的功能保留 placeholder 顯示「(尚未實作)」

## 業務規則速查

| 主題 | 重點 |
|---|---|
| 課稅別 | 應稅內含 / 應稅外加 / 免稅 / 零稅;含稅金額 ÷ 1.05 = 未稅 |
| 進貨成本 | `unit_landed_cost` = 未稅單價(含稅單會自動除 1.05);贈品由 `billed_qty < qty` 表示,平均成本被稀釋 |
| 發票自動取號 | 銷貨單儲存時,依 `invoice_form` 從 `InvoiceTrack` 字軌 `SELECT FOR UPDATE` 取下一張號碼,寫入 `invoice_no` |
| 結帳 | 銷貨單 N 筆 `SalesOrderPayment`(現金/匯款/非現金),`sum(amount) == total` 才能存 |
| 序號生命週期 | 進貨建單 → in_stock;銷貨 → sold;銷貨作廢 → 回 in_stock;進貨作廢 → void(須全部還在 in_stock 才能作廢)。**作廢的設備不佔碼**:作廢時把它登記的 IMEI / SN 釋放(`release_codes()`),同樣的碼可以重新入庫(打錯整張作廢重開);作廢的那一筆留著 `serial_no` 當紀錄,`serial_no` 的唯一限制不算作廢的,用碼找設備(`find_serial_ids` / `?code=`)也不會找到它。釋放時如果還有一台「沒作廢、主碼去掉符號後相同、卻沒登記這個碼」的設備(舊資料),碼改登記給它(先鎖住那一台再判斷)。Django 後台不能新增 / 刪除設備,狀態與序號唯讀 |
| 預設值連動 | 發票類型 = 免用 → 課稅別自動切免稅;選商品 → 進貨單帶上次進價 / 銷貨單帶 list_price |
| 中古機 | `Product.is_secondhand=True`;`ProductSerial` 逐隻記 `condition_grade` (S/A/B/C/D)、`custom_unit_price`、`battery_health`、`condition_note`;銷貨選機自動帶 `custom_unit_price` |
| 中古機類別連動 | `Category.is_secondhand_default=True` 時,該類別下所有 product `is_secondhand` 自動帶 True(`Product.save` override)。類別 default 由 False → True 儲存時,cascade 把底下所有商品 `is_secondhand/requires_serial` 設 True、`is_virtual` 設 False;反向(True → False)不 cascade,避免誤改既有資料。前端 ProductsPage 的類別新增/編輯 form 多一個「中古機類別」勾選 |
| 個人收購 | 「中古入庫」頁的「個人收購」tab(`SecondhandPersonalEntry`);走 `acquire_secondhand_from_member` service:同 transaction 建中古機序號 + 對應銷貨單(虛擬商品「收購二手」、`untaxed`、total 負數代表現金流出);service 依該會員 phone/name 自動找 / 建一筆 individual `Customer` 作 SO.customer,SO.member 記會員;serial 反向掛 `acquired_from_member`(指 Member)+ `acquired_via_sales_order` |
| 舊系統消費紀錄 | `LegacyPurchase`(sales app)輕量表,只記「member / product / qty / unit_price / doc_date / source_no」;CSV 經 `manage.py import_legacy_purchases` 灌入;不還原成 SalesOrder。MembersPage 與現役單合併排序顯示(舊資料加「舊」徽章),`last-price` API 兩邊都查、取較新 |
| 舊資料匯入指令 | `manage.py import_legacy_inventory`(catalog)= 商品 / 序號 / 庫存;`manage.py import_legacy_members`(parties)= 會員主檔,phone 為 dedup 鍵,`--update-existing` 可同 phone 更新;`manage.py import_legacy_purchases`(sales)= 會員消費紀錄。所有 import 預設 dry-run,加 `--confirm` 才寫入。CSV 樣本放 `docs/legacy-*-sample.csv` |
| 上次成交價自動帶 | `GET /api/v1/sales-orders/last-price/?member=X&product=Y`:跨 `SalesOrderItem`(未作廢、unit_price>0)+ `LegacyPurchase`(unit_price>0)取最近;銷貨建單時新增明細自動帶價,並在單價下顯示「前次 $XXX (日期)」 |
| 銷退單 | `SalesReturn`(SR-{6位})必指定一張原 `SalesOrder`,**只能整張退**(2026-10-04 起):畫面只送原單 / 退款方式 / 是否作廢原發票 / 備註,明細由後端照原單每一行、全部數量、每一台序號帶入(`items` 唯讀)。每行的金額 / 未稅 / 稅額 / 成本與單頭的小計 / 稅額 / 總額**全部照抄原單**(不重算),銷退跟原銷貨單完全對沖。一張銷貨單同時只能有一張有效銷退(退過不能再退,作廢銷退後才能重退);收購單(總額為負)不能退。有有效銷退的銷貨單不能作廢(要先作廢銷退);建立銷退、作廢銷退、作廢銷貨都先鎖原銷貨單那一列。退款方式必須為原單付款方式之一(原單總額 0、沒有付款時不用填)。退回門市 / 客戶 / 會員都唯讀、一律跟原單一樣(鎖倉店員不能退別家門市的銷貨)。存檔時先鎖原銷貨單再檢查。提交時序號 `sold → returned`、warehouse 回退回倉、配件 `StockBalance.qty +=`;`void_original_invoice=True` 時把 `SalesOrder.invoice_voided` 標 True(冪等)。`GET /sales-returns/returnable/?sales_order=X` 回原單每行 + `returned_by`(已被哪張銷退退過)+ `is_buyback` 供畫面用。`POST /sales-returns/{id}/void/` 作廢銷退單會把序號退回 `sold`、配件再扣回去;退回來的機器已經不是「已退」狀態(被轉回在庫 / 再賣 / 調走)就不能作廢。畫面的原銷貨單用搜尋挑(`searchSalesOrdersForReturn`),不載整頁清單。舊資料裡的部分退貨照舊保留 |
| 序號退回後續處理 | 銷退完成的序號狀態 = `returned`(已隔離),不會出現在「可銷貨」清單;需店員手動轉回 `in_stock` 才能再賣(避免有瑕疵的退貨機被誤再賣) |
| 廠商收購中古 | 「中古入庫」頁的「廠商收購」tab,內嵌 `PurchaseEntryPage mode="secondhand-vendor"`;走一般進貨單流程但商品搜尋限定 `is_secondhand=true`;進貨側欄多 4 欄(成色/售價/電池/備註)+「套用到下面所有」按鈕;儲存後不離頁,bump remount key 重置表單 + 顯示成功訊息 |
| 一般進貨單擋下中古機 | `PurchaseEntryPage` 預設 `mode="regular"`,商品 ComboBox / PickerModal / BatchPasteModal 都帶 `is_secondhand=false`;新增進貨單時挑不到中古品。檢視 / 作廢既有中古進貨單仍走 `/purchases/:id` |
| 中古機履歷 | `GET /api/v1/serials/{id}/history/` 回傳:收購來源 (購進 or 個人收購)、所有銷貨/退貨、StockMovement 軌跡 |
| 客戶識別 | `Customer.code` 系統自動產生 (C-{5 位流水},Tenant 持有 next_customer_seq);前端不顯示也不輸入。`phone` 選填(同行/企業可不填);`lookup?phone=` 多筆回最舊。客戶表只放「歸屬」類型(個人/同業/企業/其他),不再帶會員身分 |
| 會員主檔(獨立) | `Member` 是獨立 model(M-{5 位流水},Tenant 持有 next_member_seq);欄位姓名/電話/身分證/生日/地址/備註/啟用;前端 `/members` MembersPage CRUD;`searchMembers` / `lookupMember` 走 `/members/` API |
| 銷貨單客戶/會員雙欄位 | `SalesOrder.member` FK→`Member`(獨立主檔),ComboBox 吃電話/姓名/身分證,選填。`SalesOrder.customer` FK→`Customer`,**必填**(這筆生意的歸屬)。**不互斥**——同行帶會員來開門號 → customer=同行、member=該會員;會員 walk-in → customer=該會員對應的個人 Customer、member=該會員 |
| 店頭雜支 | `PettyExpense` 記每家門市的零星支出(房租/水電/餐飲/雜物/其他);自動單號 `EX-{5位}`;`payment_method` FK 預設現金。Phase 1 純記錄,Phase 2 將連動 `Warehouse.cash_balance` |
| 代收話費 | `PhoneBillCollection`(cash app)記店家代收客戶繳的電信費;單號 `PB-{5位}`;欄位 carrier/phone_no/amount/id_no/handled_by(全必填)+ member 選填(輸入電話自動 lookupMember,找不到可現場新增會員或略過)。**儲存即生效、現金收入**,進入營業日報「收入區 → 代收話費」與現金櫃流水「代收話費」格(算正向加入今日結餘)。**不開發票**(代收性質),只有 80mm 熱感收據:**店家抬頭(門市名/地址/電話)** + 單號/日期/電信/完整電話/隱碼身分證/金額。身分證隱碼規則 `頭3 + ***...*** + 末1`(`pages/phone-bills/mask.ts`)。作廢用 `POST /phone-bills/{id}/void/` |
| 列印頁不渲染導覽 | App.tsx 偵測 `location.pathname` 命中 `/print/`、`/receipt`、`/labels` 就跳過 topbar 與 focusMode banner,避免列印時帶到 MP POS 導覽列 |
| 維修單手機解鎖 | `RepairOrder.unlock_method`(none / password / pattern)必填;密碼存明文於 `unlock_password`、圖形鎖存「1-5-9-6-3」格式於 `unlock_pattern`;**列印收據自動隱藏**這兩欄,僅維修人員可在後台查看 |
| 維修單返修 | `RepairOrder.is_return_visit` 勾選後跳「歷史維修」modal 依客戶 phone 查 `/repair-orders/history-by-phone/`;`previous_repair_order` FK 自己 + `tenant.repair_warranty_days`(SettingsPage 可調,預設 90 天)即時推算保固狀態;`warranty_info` serializer 動態回傳 status / days_since_complete;Banner 在維修單頁頂顯示綠色「保固有效」或橘色「已超出」;`RepairsPage` 加「僅看返修」filter 與標籤 |
| 維修收據列印 | `/print/repair-receipt/:id` A4 直式一式兩聯(客戶收執聯 + 門市存根聯)中間虛線分隔,印門市抬頭/單號/客戶/機型/故障描述/預估報價/八條注意事項條款/簽名區;**手機解鎖密碼欄不列印**;「儲存並列印收據」按鈕儲存後自動 open new tab + auto window.print() |
| 租戶設定 | `GET/PATCH /tenant-settings/` 回租戶層級設定(目前只有 `repair_warranty_days`);PATCH 限 tenant_admin / platform_admin |
| 門市資訊 | `Warehouse` 加 `address` / `phone` 欄位;在 SettingsPage「門市」區塊 inline 編輯(blur 即存)。代碼/名稱仍鎖死,只能改地址/電話/啟用。資料用於收據抬頭 |
| 登入 / RBAC | DRF Token auth(`Authorization: Token xxx`),`/auth/login` `/auth/me` `/auth/logout`。`UserProfile`(tenants app)綁定 User 1:1,記錄 `role` / `tenant` / `default_warehouse` / `is_warehouse_locked`。三種角色:**platform_admin**(跨所有 tenant,只用 `/platform/*` 後台)、**tenant_admin**(自家 tenant 全權限、不鎖倉、看所有報表)、**tenant_user**(鎖在 default_warehouse、只看 / 只能操作自己倉)。`TenantMiddleware` 從 `request.user.profile.tenant` 解析 tenant |
| 倉別鎖定機制 | `apps.core.warehouse_scoping.WarehouseScopedMixin` 套在所有業務 viewset(Sales / SalesReturn / Purchase / PettyExpense / CashAdjustment / PhoneBillCollection),依 `is_warehouse_locked` 自動 filter queryset + 建單時驗證 warehouse。Transfer 用 `TransferWarehouseScopedMixin`(from OR to 是自己倉就算自己的單,建單時 from 必須是自己倉,confirm action 要求 to 是自己倉)。`business_daily_report` API 直接擋非自己倉的請求 |
| 經手人預設 | 前端 `useDefaultHandledBy()` hook 從 `request.user.sales_person`(`SalesPerson.user` OneToOne)取當前登入者的業務員,form 開啟時自動帶到 handled_by。Drawer 表單(雜支/現金調整/代收話費)+ 銷貨 entry page(sales_person)都有套 |
| 平台後台 | `/platform/tenants/` / `/platform/users/` / `/platform/warehouses/` CRUD,permission `IsPlatformAdmin`。前端 PlatformAdminPage(/platform/admin,3 tabs)只有 platform_admin 看得到 nav 入口。建用戶時可勾「同步建立業務員主檔」+ 指定 sales_person_code,一鍵建好 User + UserProfile + SalesPerson |
| 進貨付款方式 | `PurchaseOrder.payment_method` FK to PaymentMethod (選填);cash 將從店頭備用金扣、transfer/non_cash 不動店頭。Phase 1 只記錄欄位 |
| 配件庫存 | 非序號商品(`requires_serial=False`、非 virtual)走 `StockBalance(product, warehouse)`,進貨累計、銷貨扣減、調撥搬移;`Product.weighted_avg_cost` 跨倉聚合 |
| 配件不足擋下 | 銷貨單若該倉 balance 不足,`commit_sales_order` 拋錯 400,不允許負庫存 |
| 調撥 | `TransferOrder` 兩階段:`dispatched`(來源倉派發,序號 → in_transit、配件 balance 扣掉)→ `confirmed`(目的倉確認,序號 → in_stock 在目的倉、目的倉 balance 加上)。`unit_cost_at_dispatch` 在派發時快照來源倉成本,確認時用以重算目的倉加權平均(避免後續異動干擾)。`void` 智能回滾,依當下狀態決定 |
| 標籤條碼優先序 | 有序號 → IMEI;否則 有原廠條碼(`Product.barcode`)→ 用原廠條碼;都沒有 → fallback SKU。bar code 下方顯示可讀值方便對照 |
| 銷貨商品搜尋 | `searchProductsForSales` 支援 品名 / 品號 / 條碼 / IMEI 任一;打 IMEI 命中時 matched_serial 也預掛該行,且該倉只有 1 隻在庫時自動掛唯一序號(中古機同步帶 custom_unit_price)|
| 銷貨可選清單 | `?sales_pickable=true` 過濾:庫存 > 0 OR `is_virtual=True`(虛擬商品永遠可選,實體 0 庫存擋下)|
| IMEI 搜尋安全閥 | ProductViewSet.`get_search_fields` 動態化:**只有純數字 6 碼以上才把 `serials__serial_no` 加進 search_fields**,避免「18 pro 256」誤命中含 18 的 IMEI |
| 搜尋權重(中文 vs 英數)| `get_search_fields` 偵測查詢字串是否含中日韓漢字(U+4E00–U+9FFF):**含中文 → 只搜描述欄 `name/spec/category__name`**(不碰品號/條碼/IMEI,避免「中古 11」被 SKU `AA-000011` 誤帶出);**純英數 → 搜完整代碼欄位**(sku/name/spec/barcode/category),純數字 6 碼以上才再加 IMEI |
| 商品叫法比對 | `apps/identity/product_match.py`:品名與查詢走同一支 `parse_features()`,拆成型號 / 顏色 / 其他詞再比(`exact` / `covers` / `related`)。進貨搜尋、`?search=`、待確認入庫、新增查重**共用**。特徵比對只出候選;`existing` 只來自條碼 / 廠商料號 / 已確認別名 / 品號。`GET /products/resolve/?q=` 回候選 + 符合原因 + 差異,零庫存與停用都列 |
| 別名:已確認 vs 關鍵字 | `ProductAlias.verified=True` 才能自動對應且同範圍唯一(通用別名另有 `uniq_alias_generic`);`False` 是搜尋關鍵字,可多筆。籠統 / 只是品名一部分 / 同時符合多款的叫法自動降為關鍵字。已確認的叫法命中時會重看有沒有別款也符合。改指、停用限管理員;`POST /identity/aliases/remember/` 記住叫法 |
| 停用商品 | 搜尋與候選看得到(標「已停用」),**選用不會恢復**。恢復限 tenant_admin / platform_admin:`POST /products/{id}/restore/` 或待確認入庫帶 `restore=true` |
| 新增商品防重複 | `apps/identity/dedup.py` `guard_new_product()`:所有建新品入口都過。條碼 / 已確認叫法相同 → 409 硬擋;特徵相似 → 409,帶 `distinct_reason`(寫哪裡不同)才放行,存 `ProductDistinctDecision`。批次每列各自說明,匯入列進略過。新增入口要建 Product 一定要呼叫它 |
| 公司備份 | `apps/backup/`:一次備份 = 一家公司全部門市 + 附件,加密成 `.mppos-backup`。只有該公司的 tenant_admin 能用(店員與平台管理員都不行)。背景 worker `manage.py run_backup_worker` 執行;狀態在 `BackupJob`。要進備份的表在 `registry.py` **逐張登記**,新增 model 沒登記 → 備份拒絕執行、測試會紅。帶檔案的欄位登記在 `FILE_FIELDS`。備份檔放 `BACKUP_ROOT`(不在 media 底下)。格式與操作見 `docs/備份與還原_格式與操作手冊.md` |
| 復原憑證 | `BackupKey`:每家公司一組 `MP-XXXX-…`,管理員抄下保管;伺服器存 `SECRET_KEY` 包過的密文。不寫進日誌 / 備份 / 操作紀錄 |
| 還原 | 整家公司為單位:上傳 → 預檢(不改資料)→ 輸入「還原」確認(**當下就上維護鎖**)→ 等寬限時間 → 安全備份 → 一個交易內:`FOR UPDATE` 鎖公司那一列(擋住所有新增)→ 再比一次資料指紋 → 整批取代(新主鍵、外鍵重對、不重播交易)→ 逐列核對 → 解鎖。版本(全部 migration)要完全相同。單據的經手帳號用 `UserProfile.account_uuid` 對人(不看帳號名稱、不看數字 id)。新環境復原走指令 `restore_company_backup` |
| 公司維護鎖 | `TenantMaintenance.active` 時,該公司所有 API 回 503(`apps/backup/auth.py`,掛在全域的登入驗證上;`/auth/`、`/backup/` 例外)。**只擋網頁**,管理指令不經過它。鎖看的是「請求實際會落在哪一家公司」(`tenants/middleware.py` 的 `effective_tenant_id`,規則要跟 `_resolve_tenant_from_request` 一致:沒有公司的帳號不帶 `?tenant=` 會落到預設公司)。Django 管理後台由 `AdminMaintenanceGuard` 處理:任何公司在還原時只能看。平台後台(`/platform/*`)不帶 `?tenant=`,另外靠 `BlocksCompanyUnderMaintenance` 照實際要改的那一筆擋;新增會改某家公司資料的平台端點要掛它。還原被中斷時不自動解鎖;「中斷」看的是有沒有行程還握著工作的 advisory lock,不是看時間 |
| 單號下限 | 進貨 / 銷貨 / 銷退 / 調撥單號 = `last_doc_seq()`(`apps/core/numbering.py`):最後一張單的流水與 `DocNumberFloor` 取大者。還原到舊備份時把已用過的最大號記進下限,不重用給過客人的號碼 |
| 舊系統資料(歐睿) | `apps/legacy/`:十年會員消費封存匯入(`manage.py import_legacy_history`,預設試算、寫入要 `--confirm`,有來源差異要 `--reconciled-only`,可 `--rollback`)。**原文不改**(編號空白 / Tab / 前導零、空白單價存 NULL、帶正負號金額),金額以「分」整數存,原始額與淨額(單別正負 `NET_SIGN`)分開。舊店名 / 品號 / 業務員 / 會員 → MP 門市 / 商品 / 業務員 / 會員的**對照由人確認**(`LegacyStoreMap` / `LegacyProductMap` / `LegacySalespersonMap` / `LegacyMember.member`,決定記在 `LegacyMappingLog`);明細透過 `store_map` / `product_map` / `salesperson_map`(不佔欄位的 ForeignObject)串到對照,改對照不改明細。只供查詢,不過帳、不參與上次成交價。品號對照與之後的庫存搬家共用。手冊 `docs/舊POS十年會員歷史_匯入與對照手冊.md` |
| 每行未稅 / 沖回成本 | 銷貨明細存檔當下存死 `untaxed_amount` / `tax_amount`(`split_tax_by_line`:零頭補在金額最大那一行,整單加總 = 單頭;單頭算不起來不硬塞)。銷退(只能整張退)每行的金額 / 未稅 / 稅額 / `cost_at_post`(沖回成本)與單頭**全部照抄原單**,不重算。「序號取那幾台成本、配件按比例、最後一次拿餘數」只用在 migration 0016 回填舊的部分退資料。**報表要未稅金額一律讀這兩欄,不要再除 1.05** |
| 先鎖再檢查、再改 | `apps/inventory/locking.py`,銷貨 / 銷退 / 進貨 / 調撥 / 維修共用。**每一個會改庫存或序號狀態的動作都照這三步、而且都在交易內**:(1) `lock_document()` 鎖單據自己那一列並重讀,才判斷是不是已作廢 / 已確認 / 已完工;(2) `lock_stock_rows()` 照固定順序鎖這張單會動到的東西:商品(要改加權平均成本時)→ 序號 → SIM 卡 → 庫存餘額(照門市、商品編號);(3) 鎖完才檢查在不在庫、夠不夠扣,才改。不這樣做:同一支 IMEI 會被兩張單各賣一次、庫存會少算一次、同一張單會被確認 / 作廢兩次、明細順序相反的兩張單會死結。商品 / 序號 / SIM 卡用 `no_key=True`(不擋別張單新增指向它的列)。改數量一律經 `locked_balance()`,不要直接 `StockBalance.objects.get()` 再加減 |
| 維修單與庫存 | 只有 `complete` / `reopen` 會動庫存,其他入口不能繞過:`status` 唯讀(只能走 `set-status` / `complete` / `reopen`);已完工或已作廢的單不能修改、不能換狀態;已作廢不能完工;已完工要先重開(歸還零件)才能作廢;維修單不能刪除只能作廢。這些判斷都在鎖住單據之後才做(`services.py` 的 `set_repair_status` / `void_repair_order` / `ensure_editable`)。缺料也能完工(帳可能落後現場):領用照實記全部數量(`repair_usage`),帳上不夠的差額另記一筆 `adjust` 入庫(`ref_doc_type="repair_order_shortage"`),庫存數量 = 異動加總。重開歸還的是**異動紀錄裡實際領出去、還沒還的**(`_outstanding_usage`),還到當初領料的門市,不看單上現在寫的門市 / 零件 |
| 每日庫存快照與對帳 | `apps/ledger/`:每天過了 `LEDGER_DAILY_AT`(預設 23:30)由備份背景程式順便做:拍 `StockSnapshot`(門市 × 商品 × 狀態:在庫 / 退回待處理 / 維修中 / 調撥中,調撥中記在目的門市)→ 跑 `checks.py` 存 `LedgerCheckRun`。只拍今天,漏拍不補。對帳只講出來不自動修。配件庫存對異動時**調撥派發只扣來源、確認才加目的**(兩筆都寫了來源與目的當路線)。手動:`manage.py run_daily_ledger --now [--tenant X --again]`。頁面「設定 → 每日對帳」(公司管理員) |
| 報表只有一套定義(自由組合) | `apps/analytics/`:`catalog.py` 是**指標與角度的唯一定義**(事實表:銷貨 / 銷退 / 進貨 / 收款 / 退款 / 庫存快照 / 舊 POS;指標 = 直接加總的 `Base` + 由別的指標算出來的 `Derived`)。報表畫面與之後的自然語言都只能送**查詢單**(`engine.py`:指標 × 分組最多 3 個 × 期間 × 條件 × 比較),後端照定義驗證,指標不能用那個角度切就回白話錯誤、不默默給 0;沒有任何入口接受資料庫指令或欄位名稱。**新的報表需求 = 加指標或加角度,不是寫新的報表頁、新的查詢**。「銷售」類指標只算計入毛利的明細(收購二手另外一欄),所以 銷售額 − 成本 = 毛利 是同一批明細。庫存是「期間內最後一次快照」,不跨日加總;「最後一次是哪一天」看 `StockSnapshotDay`(那天有沒有拍過),**不是看明細**:賣到 0 的東西沒有明細,看明細會退回去報最後一次有貨的數量。舊 POS 的門市 / 商品 / 業務員走對照表,沒對到的歸「未對照」;舊系統的「未稅額」欄位語意不一致,不採用。合計另外算(不受筆數上限影響,單數不重複算)。存起來的報表(`SavedReport`)條件存**代碼**不存編號(還原備份後編號會換),打開時換回現在的編號,找不到的講出來。付款方式可選的代碼 = 現在的主檔 + 單據上用過的(主檔已刪的顯示「代碼(已刪除)」):刪掉用過的付款方式,歷史的錢照樣篩得到。報表權限目前不鎖(店員也看得到全公司與毛利);要鎖時填 `Base.roles` / `Derived.roles`。API:`analytics/catalog/`、`query/`、`options/`、`reports/` |
| 設備兩個碼(IMEI / SN) | 一台設備可以登記 IMEI、SN 兩個碼,可以都有、也可以只有一個。`ProductSerial.serial_no` 是**主碼**(有 IMEI 用 IMEI,沒有才用 SN),標籤 / 單據 / 既有畫面照舊讀它;兩個碼各存一列在 `ProductSerialIdentifier`(拍照入庫另外可能有 IMEI2 / EID)。**同一家公司裡一個碼只屬於一台**(IMEI、SN 一起比,比對前去空白 / 破折號 / 點、轉大寫),所以銷貨 / 調撥 / 查庫存刷哪一個碼都是同一台。規則集中在 `apps/inventory/identifiers.py`:**新增設備一律走 `create_serial()`**(進貨、個人收購、舊資料匯入都是;直接 `ProductSerial.objects.create()` 那一台沒登記碼,別台就能再用同一個碼,`test_identifiers.py` 掃全專案把關);用碼找設備走 `find_serial_ids()`(完全相同才算;不找作廢的)。比對一律比**去掉符號後的值**:登記的碼比 `ProductSerialIdentifier.normalized_value`,主碼比 `ProductSerial.serial_key`(`serial_no` 正規化後的值,`save()` 自動算;**改主碼要走 `save()`,不要 `queryset.update(serial_no=…)`**),所以沒登記到識別碼表的舊設備(碼去掉符號後跟別台相同的那種)一樣找得到、擋得住。進貨的 `serial_numbers` 每台是 `{"imei", "sn", …}`;舊格式(純字串、或沒有 `imei` 鍵的 `{"sn"}`)= 沒講是哪一種,15 碼數字且檢查碼正確的放 IMEI、其餘放 SN。有明講就照放,**IMEI 檢查碼不對只在畫面提醒、不擋**。進貨頁刷條碼的分格在 `frontend/src/lib/deviceCodes.ts` 的 `routeCodes`(`npm test` 有測試):盒上有 IMEI、IMEI2、SN 好幾個條碼,**光看碼分不出「下一台的 IMEI」還是「同一台的 IMEI2」**,所以序號側欄有「每台刷 IMEI 與 SN」開關(記在瀏覽器):關 = 一個碼一台;開 = 先補齊這一台,這一台已有 IMEI、還缺 SN 時再刷到 IMEI 不放並提示(多半是 IMEI2)。刷錯格會還原原本的碼;Enter 與 Tab 結尾的條碼槍都走同一套。批次貼上是一個序號一台,個數與數量不一致會擋。搜尋:`/serials/?search=` 比對每一個碼(可打末幾碼),有碼對得上就不走相似度比對 —— 這是給下拉挑序號用的「包含」比對,**刷條碼自動掛序號一律用 `/serials/?code=`(完全相同)**,否則同商品另一台的碼剛好包含這串字時會掛錯實機。銷貨掃碼先 `findDevicesByCode()`:對到兩台以上(舊資料的碼撞在一起)擋下不加、那一台不在這個出貨倉或不是在庫就講出它在哪,只有剛好一台、在庫、在這個倉才自動掛;「只對到一部分」的只在下拉裡由人挑,掃碼不自動掛;`/products/?search=` 對登記的碼只收**完全相同**的(不會像「18 pro 256」那樣誤中別台 IMEI;純數字 6 碼以上比對主碼一部分是原本就有的);庫存查詢頁(`stock-matrix`)原本完全不比對序號,現在收完全相同的碼,純數字 6 碼以上再比對碼的一部分。事後補登 / 修改:`POST /serials/{id}/codes/`(`set_codes()`)——店員只能補空的那一格,已登記的碼只有管理員能改,作廢的設備不能改,鎖倉帳號只能動自己門市的(已售出的 = 自己門市賣出去的;調撥中的只有管理員能動;「在不在他的門市」在鎖住那一台之後才判斷,走 `set_codes(check=…)`);每次改動留一筆 `ProductSerialCodeChange`(只增不改)。拍照入庫照登記時講的種類把 IMEI / SN 交給進貨(不重新猜、主碼一樣 IMEI 優先,不看哪個被標成主識別碼;碼沿用它原本的做法存去掉空白後的值)。既有設備由 migration 0012(主碼補登記)、0013(有 IMEI 的主碼換成 IMEI)、0014(補 `serial_key`、作廢的釋放碼、在用沒登記的補登記)補齊。每日對帳多一項「序號:每一台的碼都有登記」。雙卡機第二組 IMEI 的一般入庫不做(owner 2026-10-04 決定;拍照入庫原本就會存的 IMEI2 照舊) |
| 整張調撥 | 進貨單頁「整張調撥」→ 調撥單頁(`/transfers/new?from_po=編號`)自動帶好那張進貨單還留在進貨門市的全部商品與序號,選目的倉就能派發;之後照一般調撥(派發 → 目的倉確認)。內容來自 `GET /purchase-orders/{id}/transferable/`(只讀):序號商品只列「這張單進來、還在進貨門市、在庫」的那幾台,已賣 / 已調走 / 已退的列在 `gone` 並在畫面講出來;配件數量 = 這張單進的數量,但不超過進貨門市現有庫存(配件不分批);同商品多行併成一行;虛擬商品不列;作廢的進貨單回 400。它只是帶出建議內容,**真正能不能調由調撥存檔時鎖住庫存再檢查** |
| 關聯欄位只認自己公司 | `apps/core/tenant_fields.py` 的 `TenantScopedRelatedFieldsMixin`:序列化器(含巢狀明細)的外鍵欄位限縮到 `request.tenant`,猜到別家編號會被欄位本身擋下。**所有 app 的 serializers.py 每一個序列化器都要掛**(平台後台 `tenants/platform_views.py` 例外,它本來就跨公司);`apps/core/test_tenant_fields.py` 會掃全部序列化器,漏掛就紅。用原始編號的輸入(ListField / DictField,例如維修的 `parts_input`)mixin 管不到,要自己對公司驗證。service 另外再核對一次(`same_company()`:銷貨、銷退、進貨、調撥、維修完工)。有門市鎖的 viewset 覆寫 `perform_create` 時**要自己呼叫 `check_create_warehouse()`**(同一支測試會檢查),否則鎖倉店員能在別家門市建單 |
| 不靠送編號也不能看到別家 | API 只回 JSON(`DEFAULT_RENDERER_CLASSES`):DRF 的 API 瀏覽頁(`?format=api`)會把篩選與表單下拉整張表列出來,**不可再打開**。外鍵篩選(`?customer=` …)走 `apps/core/tenant_filters.py` 的 `TenantDjangoFilterBackend`,別家編號跟不存在的編號一樣回 400。指向帳號表的 `created_by` 一律唯讀(由 view 設定)。沒綁公司的帳號只有 platform_admin / superuser 能用 `?tenant=` / `X-Tenant-ID` 指定公司(`tenants/middleware.py` 的 `may_switch_company`),其他沒綁公司的帳號在登入驗證就 403 |

## 程式碼定位

```
inventory-3c/
├── backend/                    Django 後端
│   └── apps/
│       ├── core/               TenantOwnedModel + TrigramSearchFilter
│       ├── tenants/            Tenant + UserProfile + 平台後台 + auth(login/me/logout)+ 系統設定主檔(InvoiceType / InvoiceTrack / PaymentMethod)
│       ├── catalog/            Product / Category
│       ├── identity/           ProductAlias 別名庫 + 叫法比對(product_match)+ 新增防重複關卡(dedup)+ IntakeBatch/IntakeItem 待確認入庫
│       ├── inventory/          Warehouse / ProductSerial / StockMovement
│       ├── parties/            Supplier / Customer / Member / SalesPerson / Carrier / TelecomPlan / SimCard
│       ├── purchasing/         PurchaseOrder + commit/void service
│       ├── sales/              SalesOrder + commit/void/payment service + SalesReturn(銷退單)+ LegacyPurchase(舊系統匯入紀錄)
│       ├── transfers/          TransferOrder + commit/void service
│       ├── cash/               PettyExpense 雜支單 + CashAdjustment 現金調整 + PhoneBillCollection 代收話費 + 營業日報 service
│       ├── backup/             公司備份與還原(registry / container 加密 / export / jobs / restore)+ 維護鎖
│       ├── legacy/             舊系統資料:十年會員消費封存(archive / importer)+ 舊→新對照(mapping)+ 查詢 API
│       ├── ledger/             帳本健檢:每日庫存快照(snapshot)+ 每日對帳(checks)+ 收店後自動執行(daily)
│       └── analytics/          報表語意層:指標與角度的唯一定義(catalog)+ 查詢單引擎(engine)+ 存起來的報表(saved)
│
└── frontend/
    └── src/
        ├── api/                client.ts + hooks.ts + search.ts(searchProductsForSales 等) + types.ts
        ├── components/         ComboBox(支援 onEnterAfterValue / autoFocus / IME 偵測)/ Drawer / Field / Toolbar / Banner
        ├── pages/
        │   ├── products/        ProductsPage(合併商品 + 類別管理,左側兩段:商品搜尋 / 類別拖拉排序)+ ProductForm + ProductExpanderModal(型號展開,軸標籤可自訂)+ BulkAddProductsModal
        │   ├── purchases/       PurchasesPage + PurchaseEntryPage(規格獨立欄、Enter 跳下一筆)+ PurchaseLabelsPrintPage(條碼優先序 IMEI > 原廠 > SKU)+ PurchaseBatchPasteModal(模糊比對預覽)+ PurchaseProductPickerModal(勾選多商品入庫)
        │   ├── sales/           SalesPage(tabs:銷貨單 / 銷退單)+ SalesEntryPage(IMEI 自動掛序號 / 單一在庫自動掛 / 中文 IME 安全)+ SalesPrintPage + SalesReturnEntryPage(搜尋原單 → 整張退,明細唯讀)
        │   ├── customers/       CustomersPage(客戶管理;tabs:全部/個人/同業/企業/其他;Detail 下半顯示該客戶銷售紀錄)
        │   ├── members/         MembersPage(會員獨立主檔;欄位姓名/電話/身分證/生日/地址/備註;Detail 下半顯示該會員銷售紀錄)
        │   ├── reports/         SalesDailyReport(銷貨日報,按單分組純表格 + 作廢區塊 + CSV 匯出;收購二手不計毛利) + ExploreReportPage(自由組合:挑指標 × 分組 × 條件 × 期間 × 比較,可存成我的報表)
        │   ├── settings/        SettingsPage(發票類型 / 字軌 / 付款方式)
        │   ├── sim-cards/       SimCardsPage + SimCardForm
        │   ├── telecom-plans/   TelecomPlansPage + TelecomPlanForm
        │   ├── secondhand-acquisition/  SecondhandAcquisitionPage(hub:tabs 切換)+ SecondhandPersonalEntry(個人收購表單;廠商收購直接內嵌 PurchaseEntryPage)
        │   ├── inventory/       InventoryQueryPage(庫存矩陣:多倉勾選 + 每倉一欄 + 點數字看序號明細 + 欄位排序)+ CategoriesPage(舊獨立頁,nav 已隱藏但路由仍在)
        │   ├── transfers/       TransfersPage + TransferEntryPage(倉間調撥)
        │   ├── cash/            PettyExpensesPage 店頭雜支(列表 + Drawer 新增,連續模式)+ CashAdjustmentsPage
        │   ├── phone-bills/     PhoneBillsPage 代收話費(列表 + Drawer 兩步確認 + 電話會員 lookup)+ PhoneBillReceiptPage 80mm 熱感收據
        │   ├── login/           LoginPage(帳號密碼登入頁)
        │   └── platform-admin/  PlatformAdminPage(經銷商 / 用戶 / 倉別 三 tabs)+ 各 Tab 元件,只有 platform_admin 看得到
        ├── auth/                AuthContext + useAuth / useCurrentUser / useDefaultWarehouse / useDefaultHandledBy
        ├── App.tsx              路由與導覽(NAV_GROUPS 6 群:報表/庫存/銷貨/門號/維修/設定 + platform_admin 多看到「平台」群)
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

## 何時更新 AGENTS.md

當下列任一發生:
1. 加新模組(新增 `apps/` 或 `pages/` 目錄)→ 更新「程式碼定位」
2. 業務規則改變(課稅、結帳、序號生命週期)→ 更新「業務規則速查」
3. 設計決策被推翻或新增 → 在 `docs/decisions.md` 加 ADR + 摘要到這裡

別把這裡塞滿,**精準 + 最新**比完整重要。深入內容寫到 `docs/`。
