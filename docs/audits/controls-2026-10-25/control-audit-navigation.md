# 控制項盤點：導覽、報表、設定、管理、手機與列印

日期：2026-10-25。唯讀核對 HEAD ebf7e0e；本文件是原始碼審查，沒有操作正式／測試資料、沒有瀏覽器實測，也未修改產品程式。現有工作目錄包含其他人的文件變更，本次未碰觸。舊版全站 UI 稽核不作為目前缺陷證據。

範圍：34 個 React 頁面／shell 元件，另看 App、nav、共用控制項、相關樣式／測試及公開報價 HTML 模板。前端實際沒有 dashboard、analytics、mobile、print 這四個目錄；對應為 home、reports/ExploreReportPage、photos/PhonePhotoPage + inventory/PhoneCountPage，以及分散的列印頁。

優先定義：P1 = 控制狀態可能讓操作人誤判資料已完成或放棄未確認操作；P2 = 明確操作、鍵盤／輔助名稱、回饋問題；P3 = 外觀與文字一致性。P1 必須另列功能修正，不混進「只改 CSS／元件皮膚」批次。

## 需要先處理的控制狀態

### N01 · P1 · 平台管理的啟用開關可能呈現未成功儲存的結果

- 證據：[PlatformTenantsTab.tsx:92](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/platform-admin/PlatformTenantsTab.tsx:92) 名稱 onBlur 直接 mutate；同檔 :103 的啟用 checkbox 使用 defaultChecked 後直接 mutate。[PlatformUsersTab.tsx:220](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/platform-admin/PlatformUsersTab.tsx:220)、[PlatformWarehousesTab.tsx:144](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/platform-admin/PlatformWarehousesTab.tsx:144) 也是同一路徑。這些格子沒有顯示存檔中／沒存成，沒有個別重試。
- [api/hooks.ts:1679](/Users/tsairunghuang/MP_POS系統/frontend/src/api/hooks.ts:1679)、:1750、:1791 的對應 mutation 只有 onSuccess invalidation，沒有失敗回復或回饋；[main.tsx:11](/Users/tsairunghuang/MP_POS系統/frontend/src/main.tsx:11) 也沒有全域 mutation error 處理。可從源碼確定：失敗時 uncontrolled checkbox 保留使用者切換後的外觀，可能讓管理員以為已停用帳號／公司／門市。
- 建議：沿用現有 useCellSaves 的每格 saving/saved/failed 與原值／草稿分離；啟用操作明示對象名稱及失敗狀態，重試要重送同一個意圖。不要改帳號權限、啟用政策或新增 API 行為。
- 驗收：模擬 PATCH 403、500、斷線，各別測帳號／公司／門市啟用；畫面不能只留下已切換外觀，必須標「沒存成」並能重試；重新載入呈現伺服器值；送出中快速連點不得誤示已完成。既有建立抽屜的 pending 狀態不能退化。

### N02 · P1 · 手機盤點「結束」未處理尚未確認／排隊中的動作

- 證據：[PhoneCountPage.tsx:81](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/inventory/PhoneCountPage.tsx:81) pending 保存未知結果，:157–185 保留斷線動作，:202 重送沿用同一 op；但 [:298](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/inventory/PhoneCountPage.tsx:298) finish 不檢查 pending、busy 或 queue，任何例外也會 setProblem(gone:true)，而 :337 的「結束」一直可按。
- 後端交叉核對：[stockcount_phone.py:290](/Users/tsairunghuang/MP_POS系統/backend/apps/inventory/stockcount_phone.py:290) finish 結束配對，[:135](/Users/tsairunghuang/MP_POS系統/backend/apps/inventory/stockcount_phone.py:135) 後續動作會被判 gone。因此存在尚未確認的掃碼被結束畫面遮住、無法沿原配對重送的路徑；這是來源推導，尚未實機重現。
- 建議：有排隊／送出／未知結果時阻擋正常結束並指向重送，處理完才結束；區分已結束與一般網路失敗，後者保留操作畫面。若要新增「明確放棄未確認動作」，須另決策，不能設計者擅自加入。
- 驗收：掃碼正在送出、第一次失敗自動重送中、重送仍失敗、pending 後新增一筆四種情境按結束，不得跳到完成頁或遺失重送入口；確認結束失敗可再試；正常結束只結束手機配對，不提交整張盤點單；既有 op 與順序規則不改。

## 分頁、篩選與選單

### N03 · P2 · 頁內分頁有三套視覺與不完整的鍵盤語意

- 證據：[SettingsPage.tsx:285](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/settings/SettingsPage.tsx:285) 用 role=tablist/tab + aria-selected，但沒有 tabIndex 管理、方向鍵、aria-controls／tabpanel 對應；[:301](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/settings/SettingsPage.tsx:301) 是 hidden 保留面板。[LegacyMappingPage.tsx:60](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/legacy/LegacyMappingPage.tsx:60)、[PlatformAdminPage.tsx:25](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/platform-admin/PlatformAdminPage.tsx:25) 則直接使用一般 btn primary，沒有選中語意。
- 樣式：[styles.css:1985](/Users/tsairunghuang/MP_POS系統/frontend/src/styles.css:1985) 小分頁 36px；[:463](/Users/tsairunghuang/MP_POS系統/frontend/src/styles.css:463) 一般按鈕 44px；[:6622](/Users/tsairunghuang/MP_POS系統/frontend/src/styles.css:6622) legacy-tabs 又定 gap。規範 [ui-patterns.md:335](/Users/tsairunghuang/MP_POS系統/docs/ui-patterns.md:335) 已要求小分頁一致，目前 legacy/platform 未納入。
- 建議：頁內工作分頁共用 Tabs；頁面路由仍用 Link + aria-current，不把兩者混成開關。若改成底線頁籤，須把「選中藍底」現行規範一併更新為使用者新提案，不能宣稱目前程式違反底線設計。
- 驗收：頁籤只有一個 Tab 停點、方向鍵移動、Home/End、Enter/Space 與面板關聯正確；設定頁切換保留未存資料與「還沒儲存」；legacy 管理員限制和對照確認不變；平台分頁換裝不得新增 API 請求或放寬權限。

### N04 · P2 · shell 選單與搜尋有鍵盤操作，焦點／輔助狀態尚未收完整

- 證據：[ModuleBar.tsx:25](/Users/tsairunghuang/MP_POS系統/frontend/src/components/shell/ModuleBar.tsx:25) Esc 只 setOpen(false)；[:103](/Users/tsairunghuang/MP_POS系統/frontend/src/components/shell/ModuleBar.tsx:103) 宣告 menu/menuitem，但開啟不聚焦、沒有方向鍵與關閉後焦點回到觸發按鈕。焦點位於將卸載的選項時按 Esc，沒有程式指定回復位置。
- [NavSearch.tsx:71](/Users/tsairunghuang/MP_POS系統/frontend/src/components/shell/NavSearch.tsx:71) 已有方向鍵／Enter／Esc／輸入法防誤觸，但 [:98](/Users/tsairunghuang/MP_POS系統/frontend/src/components/shell/NavSearch.tsx:98) input 未連結 listbox、沒有 aria-expanded／aria-activedescendant；options 亦無可被引用的 id。
- 建議：具名設定選單選擇「完整 menu 模式」或「一般 disclosure + links」，不要只放 ARIA 名稱卻缺對應操作；搜尋補齊 combobox 關聯，沿用目前移回工作台掃碼框的功能。
- 驗收：只用鍵盤開啟、選取、Esc、Tab、瀏覽器回上一頁，焦點不掉到 body；讀螢幕能得知搜尋展開狀態及目前候選；中文選字 Enter 不導頁；同頁搜尋跳轉後仍回正確掃碼框。

### N05 · P2 · 報表查詢條件的草稿提示未完全一致

- 已有良好基準：[ReportRangeBar.tsx:32](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/reports/ReportRangeBar.tsx:32) rangeReady + draftPending，:76/:91 switchApplied，:111「還沒查詢」；自訂分析 [:532](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/reports/ExploreReportPage.tsx:532) 摘要也有「尚未重查」。不能把前一輪已修的固定報表日期問題重列為現況。
- 缺口：[PartsUsageReportPage.tsx:59](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/reports/PartsUsageReportPage.tsx:59) 日期草稿 + applied，但 :83 查詢無日期有效性判斷、沒有草稿提示；[RepairMonthlyPage.tsx:124](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/reports/RepairMonthlyPage.tsx:124)、[InvoiceListPage.tsx:232](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/reports/InvoiceListPage.tsx:232)、[SalesDailyReport.tsx:347](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/reports/SalesDailyReport.tsx:347) 有查詢按鈕及區間驗證，但未採固定報表的 pending 文案；發票保留 AppliedFilters，這不是「完全沒有摘要」。
- 建議：對有「查詢」的報表提供同一套 draft/pending 控制樣式；缺日期或起日大於迄日時同時給原因，不只灰掉。不可把所有篩選改為即時查詢；PeriodQuick 已有一按即查決策，應保留。
- 驗收：改日期／門市後未查詢能辨別表格仍屬舊條件；套用後提示消失；快捷期間直接查；匯出只用表格已套用條件；零件耗用無效區間不送請求。來源中的期間／稅／門市範圍不可被 UI 合併改算。

### N06 · P2 · 零件耗用讀取失敗仍使用「沒有紀錄」外觀

- 證據：[PartsUsageReportPage.tsx:26](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/reports/PartsUsageReportPage.tsx:26) 只取 data/isLoading；[:119](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/reports/PartsUsageReportPage.tsx:119) 非 loading 且 rows 空即顯示「該區間沒有零件異動紀錄」，沒有 isError 或重試。
- 建議：採首頁／固定報表已有 loading/error/empty/stale 區分，增加同條件重試；不是加新報表能力。
- 驗收：首次請求 500／斷線顯示失敗與重試，不顯示業務零筆；真零筆仍顯示空狀態；重試保留已套用區間；背景失敗若保留舊資料，要標示其時效。

## 控制名稱、保存回饋與語意

### N07 · P2 · 表格直接編輯與管理頁篩選有缺少可存取名稱的控制項

- 證據：[SettingsPage.tsx:484](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/settings/SettingsPage.tsx:484)、:504、:807、:838、:848、:1036，格子只有表頭，input/select/radio 沒有 label／aria-label；平台租戶／門市／用戶直接編輯亦同。表頭不自動成為 input 的可存取名稱。
- [ExploreReportPage.tsx:329](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/reports/ExploreReportPage.tsx:329) 我的報表、:353 期間、:409 加指標、:435 分組、:488 加條件的 select 依靠 option／旁邊 span；:401、:476 的移除都只叫「移除」，缺對象。
- [BackupPage.tsx:480](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/backup/BackupPage.tsx:480) 檔案／憑證、:524 還原確認文字只靠 placeholder。[LegacyMappingPage.tsx:105](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/legacy/LegacyMappingPage.tsx:105) 對照狀態 select 無欄名；:502/:507 的理由／新來源證據也靠 placeholder。
- 建議：表格每個控制名稱包括「列對象 + 欄位」；移除包括指標／條件名；一般表單重用 Field；placeholder 僅提示格式，不能作為唯一名稱。密碼、復原憑證等不可放入 aria-label 或 title 的動態值。
- 驗收：只看 accessibility tree 能辨別「A 店啟用」「應稅內含設為預設」「移除銷售金額指標」；點可見 label 會聚焦；還原確認文字名稱保留，但安全確認與實際確認詞規則不變。

### N08 · P2 · 平台價目表的自動儲存回饋與一般設定不同

- 證據：[PlatformVendorsTab.tsx:121](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/platform-admin/PlatformVendorsTab.tsx:121) 類別即時儲存失敗只有 toast；[:384](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/platform-admin/PlatformVendorsTab.tsx:384) 價目 Cell 在 onSave false 時把輸入還原，沒有每格 pending／failed，使用者剛修的字會消失。
- 這與 [ui-patterns.md:419](/Users/tsairunghuang/MP_POS系統/docs/ui-patterns.md:419)「沒存成時畫面留著剛改的值」不同；一般 SettingsPage 已有 CellMark/useCellSaves 可參照。
- 建議：保留未存草稿、欄旁顯示失敗及重試；一份共享行內儲存狀態即可，勿改價目算法、商品料號或匯入提交規則。
- 驗收：編輯名稱、單位／參考價後斷線，輸入保留且不假稱已存；成功後標示已存；重試不要求重新打字；一格失敗不能誤把整個表格標完成。

### N09 · P2 · 平台「取消」實際是移除配件共用規則

- 證據：[PlatformDevicesTab.tsx:309](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/platform-admin/PlatformDevicesTab.tsx:309) drop 執行 remove.mutateAsync；[:381](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/platform-admin/PlatformDevicesTab.tsx:381) 按鈕卻叫「取消」，一次按下立即執行。頁上另有 :348「放棄」編輯；語意容易混淆。
- 建議：具體叫「移除共用規則」，依現有 ArmButton 兩段式規範呈現，保留「已經加上的留著」業務結果。不是刪除商品，不得連帶移除已建立的相容關係。
- 驗收：第一下只進確認狀態，第二下才呼叫現行 remove；失敗規則留在列表且可重試；「放棄編輯」不發出 remove；已套用商品關係保持原語意。

### N10 · P2 · 發票機符號按鈕與列印中控制缺少清楚狀態

- 證據：[InvoicePrinterPage.tsx:146](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/settings/InvoicePrinterPage.tsx:146)、:155 的 −／+ 無 aria-label/title，僅讀出符號；:117 選發票機及 :123 速率未隨 busy 禁用，測試送出期間可修改連線選擇；:139/142 測試按鈕有 disabled，但文字一直不變。
- 建議：補「減少／增加上方空行」名稱；送出期間顯示「傳送中」，使影響該次送出的連線／參數保持明確一致。不要改 serial 協定、紙張格式、字軌跳號或實際送印邏輯。
- 驗收：鍵盤及讀螢幕可辨識兩顆按鈕；列印中不能造成顯示的目標／參數與當次送出目標混淆；恢復後可再調；實體試印驗收需另外執行，原始碼／預覽不算印好。

## 可保留的特殊表面與視覺例外

### N11 · P3 · 畫面列印工具列與紙張樣式應分開統一

- [SalesPrintPage.tsx:149](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/sales/SalesPrintPage.tsx:149)、[PhoneBillReceiptPage.tsx:85](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/phone-bills/PhoneBillReceiptPage.tsx:85) 用原生 button；[styles.css:1270](/Users/tsairunghuang/MP_POS系統/frontend/src/styles.css:1270) 工具列是 3px 圓角／padding 決定高度，而標籤列 [:1206](/Users/tsairunghuang/MP_POS系統/frontend/src/styles.css:1206) 44px、6px 圓角、硬編 20px padding。
- [RepairReceiptPrintPage.tsx:24](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/repairs/RepairReceiptPrintPage.tsx:24) 自動喚起列印，頁內無重印／關閉工具列；這是可改善差異，不是紙張內容缺陷。
- 建議：只把螢幕上的列印／關閉／重試工具列對齊共用 token；紙張的毫米、字級、顏色與版面保留列印例外。若補維修重印工具列，必須 no-print。
- 驗收：畫面可辨識主要列印與次要關閉；取消系統列印後仍能再次列印；列印媒體完全不出工具列；45mm 標籤、80mm 收據、A4 維修雙聯的分頁與實體尺寸不變。

### N12 · P2（狀態）／P3（樣式）· 公開報價頁屬獨立模板，不能漏掉也不應硬塞 React

- 證據：[quote.py:127](/Users/tsairunghuang/MP_POS系統/backend/apps/trade/quote.py:127) 自帶 STYLE，:142 所有 button 40px＋膠囊；:228 展開只改 class/hidden；:237 成色多選、:241 電池單選只改 on class；:344 價格上下限只有 placeholder，無欄名。
- 語意：成色可複選，電池單選可清掉，型號是展開，加入／取消是選取待複製項目；均不能為追求一致畫成同一種單選分頁。
- 建議：抽取可獨立輸出的少量控制 token（字級、圓角、焦點、按壓、最小點擊區），保留獨立 HTML 與對外精簡版面；加 aria-pressed、aria-expanded、價格欄名。不能引入登入 shell，也不能讓公開頁取得內部成本／識別資料。
- 驗收：鍵盤及讀螢幕可得知多選／單選／展開；清除後 ARIA 與顏色同步；加入只改待複製清單，不成立訂單；分享連結失效／停用與價格計算仍過既有後端測試。

### N13 · P3 · 手機大按鈕是合理例外，仍可共享狀態與 token

- [styles.css:7773](/Users/tsairunghuang/MP_POS系統/frontend/src/styles.css:7773) phone-btn 與 [:8407](/Users/tsairunghuang/MP_POS系統/frontend/src/styles.css:8407) pc-btn 都有專用大點擊區；pc-mode :8411 另寫 10px 圓角。不是一律縮成桌面 36px 的理由。
- [PhonePhotoPage.tsx:284](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/photos/PhonePhotoPage.tsx:284) 拍照／相簿有 locked；:318 有逐張上傳狀態、重試；:188 禁止上傳中完成。可保留。完成請求中可補 pending 與重複點擊抑制，但不要把拍完等同電腦已儲存商品。
- 驗收：390px 橫直向大目標不縮小、不遮住待傳／失敗；模式保留 aria-pressed；手機盤點與手機拍照仍是兩種任務，按「結束」不得被抽成不理解任務的通用 handler。

## 已可沿用，不必重做

- 路由導覽：Sidebar、ModuleBar 使用 Link/aria-current；多於 3 個分頁在窄螢幕換下拉，沿用現有 nav 權限過濾與 aliases。
- 報表：PeriodQuick 的一按即查、StoreSelect 的原生下拉、ReportRangeBar 的 draft/applied、Explore 的結果摘要／尚未重查；只統一缺口，不能重寫報表語意。
- 設定：SettingsPage 面板 hidden 而非全部卸載、帳號別記憶分頁、未存提醒；CellMark/useCellSaves 保留草稿與重試。StaffAccountsPage 的停用 ArmButton、pending 與結果通知可保留。
- 備份：BackupPage 四步只是進度說明，帶 aria-current=step，不是可跳步 Tabs；檔案檢查、來源／取代範圍、確認文字與維護狀態不可簡化掉。LedgerChecksPage 的展開鈕已有 aria-expanded；Legacy 待核原始資料用 details/summary。
- 登入／密碼：LoginPage 已包 label、autocomplete、輸入／送出 pending；PasswordPage 用 Field 且 submit 有 pending guard。密碼頁可補「儲存中」作為小改善，不需要變更驗證政策。
- 圖示：EyeToggle 有動態 aria-label/title、aria-pressed、SVG aria-hidden，是 icon-only 控制項可沿用的基準；不能以「圖示比較專業」為由把一般動作文字全部拿掉。

## 完整來源覆蓋清單

下列 34 個 TSX 已檢視其控制項宣告、狀態與相關樣式。這是來源覆蓋，不表示逐頁實機、全部角色或所有 API 故障分支已驗證。

| 目錄（均在 /Users/tsairunghuang/MP_POS系統/frontend/src） | 本次覆蓋檔案 | 重點 |
|---|---|---|
| components/shell | ModuleBar.tsx、NavSearch.tsx、Sidebar.tsx | 路由頁籤、具名選單、搜尋鍵盤與焦點 |
| pages/home | HomePage.tsx | 門市、待辦連結、初次／背景失敗重試；已修 stale 區分 |
| pages/reports | BusinessDailyReport.tsx、CommissionLinesPage.tsx、ExploreReportPage.tsx、FixedReportPage.tsx、InvoiceListPage.tsx、PartsUsageReportPage.tsx、RepairMonthlyPage.tsx、ReportRangeBar.tsx、SalesDailyReport.tsx | 日期、查詢、篩選、快捷期間、匯出、條件摘要、展開 |
| pages/settings | InvoicePrinterPage.tsx、SettingsPage.tsx、StaffAccountsPage.tsx、VendorLinksPage.tsx | 分頁、行內存檔、啟用／預設、帳號動作、串接儲存、測試送印 |
| pages/backup | BackupPage.tsx | 憑證、備份、上傳檢查、確認／取消還原、進度 |
| pages/legacy | LegacyMappingPage.tsx | 5 分頁、對照狀態、候選確認、解除、待核結案 |
| pages/ledger | LedgerChecksPage.tsx | 一致項目收合、唯讀結果 |
| pages/platform-admin | PlatformAdminPage.tsx、PlatformDevicesTab.tsx、PlatformTenantsTab.tsx、PlatformUsersTab.tsx、PlatformVendorsTab.tsx、PlatformWarehousesTab.tsx | 5 分頁、建立抽屜、表格編輯、啟用、重設密碼、型號判定、價目預覽／套用 |
| pages/login、pages/account | LoginPage.tsx、PasswordPage.tsx | label、autocomplete、提交／pending、錯誤 |
| pages/photos | PhonePhotoPage.tsx | 拍照／相簿、重試／移除、完成、圖像預覽 |
| pages/inventory（僅手機） | PhoneCountPage.tsx | 模式、相機、輸入／重送、堆數、撤回、結束 |
| pages/labels | LabelPrintPage.tsx | 重試、列印／關閉、測試偏移、張數 |
| pages/sales（僅列印） | SalesPrintPage.tsx | 螢幕列印／關閉工具列 |
| pages/phone-bills（僅列印） | PhoneBillReceiptPage.tsx | 螢幕列印／關閉工具列 |
| pages/repairs（僅列印） | RepairReceiptPrintPage.tsx | 自動列印、沒有頁內重印操作、紙張例外 |

另看：App.tsx、nav.ts、Toolbar、Field/Checkbox、PeriodQuick、StoreSelect、EyeToggle、useCellSaves、styles.css；平台保存 hooks；手機 finish 相關後端只作生命週期證據；backend/apps/trade/quote.py 的公開 HTML/CSS/JS。未檢視與本批控制項無關的金額／稅／庫存計算。

## UI-only shared guard：現有可接入口與守門缺口

1. [frontend/package.json:6](/Users/tsairunghuang/MP_POS系統/frontend/package.json:6) 已有 npm test = node --test src/、typecheck、build。新增控制契約測試可以放 src/lib/*.test.mjs，自動納入既有 npm test；目前沒有 React DOM／瀏覽器測試套件配置，若要驗焦點及 computed style，需另設小型瀏覽器測試入口，不能把正規表達式檢查當實機證明。
2. [cssCoverage.test.mjs:31](/Users/tsairunghuang/MP_POS系統/frontend/src/lib/cssCoverage.test.mjs:31) 只掃固定 className="…"；:44 只確認 CSS 出現過該 class 名。它守住「規則被整段刪掉」，**守不住** template／動態 classes、active/disabled/focus-visible 狀態是否有效、CSS 內容空了或被覆蓋、computed dimensions、公開 quote.py、ARIA。不要移除既有 guard，也不要擴大例外名單掩蓋缺口。
3. 建議新增一份共用 controls 契約測試：檢查規定元件／token 的必要狀態與可存取名稱，對桌面、手機、列印工具列、公開模板維持具名例外；更深入的 JSX 盤點可用現有 TypeScript parser，避免只靠掃單行文字。測試應驗外部行為，不鎖死某段 JSX 排版。
4. 既有語意驗收入口：[keyboardBind.test.mjs](/Users/tsairunghuang/MP_POS系統/frontend/src/lib/keyboardBind.test.mjs) 延伸 tabs/menu 焦點契約；[settingsTabs.test.mjs:19](/Users/tsairunghuang/MP_POS系統/frontend/src/lib/settingsTabs.test.mjs:19) 與 inlineSave.test.mjs 延伸表格保存失敗／重試；[fixedReports.test.mjs](/Users/tsairunghuang/MP_POS系統/frontend/src/lib/fixedReports.test.mjs)、densityV06.test.mjs、appliedFilters.test.mjs 保護查詢／草稿／匯出；[nav.test.mjs](/Users/tsairunghuang/MP_POS系統/frontend/src/nav.test.mjs) 保護路由與 aliases；adminViews.test.mjs 保護備份步驟與唯讀收合；noBrowserDialogs.test.mjs 保留平台重設密碼的明示例外。
5. 手機 pending／結束問題應進 [phoneCount.test.mjs:50](/Users/tsairunghuang/MP_POS系統/frontend/src/lib/phoneCount.test.mjs:50) 與後端 test_stock_count_phone.py，屬功能測試，不能只做按鈕 disabled 字串檢查。列印改動對應 labels.test.mjs、repairReceipt.test.mjs、serialPrinter.test.mjs；公開報價對應 [backend/apps/trade/test_quote.py](/Users/tsairunghuang/MP_POS系統/backend/apps/trade/test_quote.py)。
6. 本 checkout 未找到 .github/workflows；[ops/deploy-test.sh:37](/Users/tsairunghuang/MP_POS系統/ops/deploy-test.sh:37) 只 npm ci + build，[deploy.sh:34](/Users/tsairunghuang/MP_POS系統/deploy.sh:34) 同樣未跑 npm test。建議把「測試 → 型別／build → 代表頁面狀態檢查」接在部署前獨立 gate，而不是把已通過 build 稱為 UI 驗收。此處只是入口建議，沒有修改或執行部署。

未執行測試：本次只產出盤點文件，沒有程式改動。後續至少人工驗淺／深主題、1366px／1024px、專用手機頁 390px、200% 放大；對焦點、disabled 原因、載入／失敗／空資料分別驗收。大字級與手機大目標保留，紙張尺寸不併入桌面控制 token。
