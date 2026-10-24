# 交易與工作台按鈕／控制項唯讀盤點

- 檢查日期：2026-10-25；實際 checkout：`/Users/tsairunghuang/MP_POS系統`；`git rev-parse --short HEAD` = `ebf7e0e`。
- 本次只讀源碼及規則、寫本報告；未改程式、未執行正式交易、未跑瀏覽器或裝置驗收、未重跑測試。下文「確認」限源碼結構，不代表正式站狀態或操作缺陷已實機重現。
- 工作目錄另有既存文件修改及未追蹤文件，本次未碰觸。行號依上述 checkout，後續實作前須重對。
- 已對照 `AGENTS.md`、`docs/development/CURRENT_TASK.md` 及近期 `docs/decisions.md`。批發與廠商 API 仍暫停；本報告記錄其控制項差異，**不等於建議插隊施工或啟用**。[目前工作範圍](/Users/tsairunghuang/MP_POS系統/docs/development/CURRENT_TASK.md:5)

## 結論與優先順序

交易核心已大量共用 `btn`／`wb-btn`、`ArmButton`、`MoneyInput`／`QtyInput`，無須重做一套按鈕。剩餘工作主要是把「動作、選取、展開、狀態」四種控制分清楚，再補鍵盤、名稱及送出中的回饋。

| 項目 | 級別 | 建議類型 | 排程 |
|---|---|---|---|
| T01 批發自製第二次確認未套共同時間保護 | P1（啟用前） | 確認行為一致性 | 批發恢復／對外啟用前必處理；目前暫停範圍 |
| T02 付款、電信商、門市選取只有顏色狀態 | P2 | 選擇控制語意 | 優先處理營運中的銷貨、代收、庫存查詢 |
| T03 掃碼候選缺少讀屏語意、預覽無鍵盤入口 | P2 | 複合輸入控制 | 共用元件，需保護掃碼行為 |
| T04 「更多」宣告 menu，未完成 menu 鍵盤契約 | P2 | 選單／焦點 | 共用元件 |
| T05 pending 與作廢外觀有殘留分支 | P2 | 動作生命週期 | 先修維修設定，再統一共用回饋 |
| T06 圖示關閉及商品勾選缺可辨識名稱 | P2 | 可及名稱 | 小範圍修正，補指定頁驗收 |
| T07 批次勾選未呈現部分選取 | P2 | checkbox 三態 | 盤點先做；批發暫緩 |
| T08 明細列及展開鈕搶用 primary | P3 | 視覺層級 | 附於對應頁優化，不做全站機械取代 |

## T01：批發的自製確認沒有 4 秒到期、500ms 雙擊排除

**實證**：[TradeUnitList.tsx:47](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/trade/TradeUnitList.tsx:47) 的 `asking` 只有字串；[99](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/trade/TradeUnitList.tsx:99) 下架、[115](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/trade/TradeUnitList.tsx:115) 刪價目，第二次呼叫只看字串相同便執行。`save` 同樣在 [83](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/trade/TradeUnitList.tsx:83) 自行判斷。沒有時間戳、到期計時或同步執行鎖；按鈕以 `run.isPending` 鎖住已開始的請求。相同模式也見 [TradeGoodsTab.tsx:53](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/trade/TradeGoodsTab.tsx:53) 的批次開放／收回／改價。

**觸發與影響**：看見「下架」後滑鼠雙擊，兩次 click 可以分別走第一、第二階段；或第一次點完過很久，再點仍沿用確認狀態。這與明定「4 秒內再次按、半秒內第二下不算」不同。[規則來源](/Users/tsairunghuang/MP_POS系統/docs/decisions.md:3299) 源碼可確認缺保護，**本次未對實際批發資料試點，也不宣稱已有錯誤交易**。

**建議**：恢復此模組時改走共用確認狀態；確認綁定動作＋當次目標與計畫，數量／價格／篩選／門市改變即取消。保留 `unitNeedsConfirm`／`goodsNeedsConfirm` 的業務門檻，不擅自擴大每項設定都須按兩次。確認中的視覺使用 `armed` 琥珀，不把 `danger` 當成「選中／確認中」。

**驗收**：假資料、攔截請求下驗 0ms／200ms／500ms 以上／4 秒過期；切換目標後須重按；送出慢回應時只一個請求；失敗保留原工作內容。這項是批發啟用前的 P1，**不是宣告目前門市營運被 P1 阻擋**。

## T02：把選擇控制與一般動作分清楚

**實證**：銷貨付款方式 [SalesWorkbenchPage.tsx:2778](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/sales/SalesWorkbenchPage.tsx:2778)、代收電信業者 [PhoneBillForm.tsx:402](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/phone-bills/PhoneBillForm.tsx:402)、庫存查詢多門市 [InventoryQueryPage.tsx:542](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/inventory/InventoryQueryPage.tsx:542)，都是 button 加 `.on` 表示選取，未提供 `aria-pressed` 或 radio／checkbox 選取語意。批發也大量使用 `vo-chip active`：[TradeUnitList.tsx:154](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/trade/TradeUnitList.tsx:154)、[TradeGoodsTab.tsx:90](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/trade/TradeGoodsTab.tsx:90)。

**場景**：視覺上知道哪種付款被選，但讀屏只能聽到一排普通按鈕，單選／複選也不明確。

**建議**：維持現有緊湊 chip 外觀，單選付款／電信商採具群組名稱的 radio 語意；多門市採具狀態的多選 chip／checkbox。若繼續用 button，至少暴露 pressed 狀態及群組名稱。**不要把表單草稿選項改成暗示立即寫入的 switch**。銷貨「拆帳／不拆」[2762](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/sales/SalesWorkbenchPage.tsx:2762) 另補展開／模式狀態，保留既有付款金額切換規則。

補充：廠商頁已有 `role=tab`／`aria-selected`，但 [VendorOrdersPage.tsx:186](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/vendor-orders/VendorOrdersPage.tsx:186) 的類別與廠商列未見 tab 鍵盤游標／關聯面板；應先決定它是篩選單選還是真正頁籤，再完成對應語意，不只加 role。

**驗收**：僅鍵盤可完成單選及多選；讀屏能說出群組、名稱、目前值；滑鼠與觸控原本一步選擇的速度不變；選付款不送出、不計成一次交易。批發部分維持後排。

## T03：掃碼候選與「查看」需補鍵盤、讀屏，不改掃碼引擎

**實證**：[ScanBox.tsx:562](/Users/tsairunghuang/MP_POS系統/frontend/src/components/workbench/ScanBox.tsx:562) **已有**上下鍵、Enter、Tab 槍尾碼、Escape、輸入法組字處理。缺口在 [603](/Users/tsairunghuang/MP_POS系統/frontend/src/components/workbench/ScanBox.tsx:603) input 未宣告 combobox／展開／所控清單／作用中候選，[629](/Users/tsairunghuang/MP_POS系統/frontend/src/components/workbench/ScanBox.tsx:629) 候選是一般 div。預覽 [642](/Users/tsairunghuang/MP_POS系統/frontend/src/components/workbench/ScanBox.tsx:642) 為 `tabIndex=-1`＋`onMouseDown`，鍵盤處理未提供對應查看入口。

**場景**：店員可用上下鍵選商品，但輔助技術不知道目前候選；只用鍵盤無法直接呼叫每列的查看功能。

**建議**：補齊共用 combobox/listbox 與 active descendant；另外設計明確可鍵盤啟動的查看入口，查看與「加入」保持分離。不要直接拿掉 `tabIndex=-1` 或新增會搶焦點的 popup，先處理既有 150ms blur 關閉與條碼槍焦點需求。

**驗收**：一般打字、注音選字、連刷、慢速藍牙槍、Enter／Tab 槍尾碼、上下鍵選候選、查看後返回均測；查看不可加入商品，返回保留搜尋與候選；任何 Enter 都不可變成付款／入庫提交。僅以新增 ARIA 的靜態測試不能宣告掃碼驗收完成。

## T04：「更多」選單需要完整鍵盤／焦點契約

**實證**：[MoreMenu.tsx:44](/Users/tsairunghuang/MP_POS系統/frontend/src/components/workbench/MoreMenu.tsx:44) 宣告 `aria-haspopup=menu`、`aria-expanded`；內容 [55](/Users/tsairunghuang/MP_POS系統/frontend/src/components/workbench/MoreMenu.tsx:55) 為 `role=menu`，children 為各頁一般 button／ArmButton。開啟未將焦點送入，未定義 menuitem／方向鍵，Escape [31](/Users/tsairunghuang/MP_POS系統/frontend/src/components/workbench/MoreMenu.tsx:31) 僅關閉，沒有主動回觸發鈕的焦點管理。

**建議**：若維持真正 menu 就完成整套鍵盤行為；若只是展開幾個普通動作，可改為 disclosure 容器、保留普通 Tab 順序與 expanded／controls。先保留目前「清空草稿等低頻危險操作放更多、離掃碼與提交遠一些」的好設計。

**驗收**：鍵盤開啟、走至各項、Esc 關閉回到觸發鈕；點外部關閉不搶走其他欄位焦點；選單第一項不能因開啟就執行；確認中關閉或換單不保留錯誤的 armed 狀態；銷貨與進貨各實測一次。

## T05：pending、危險態與兩段式回饋仍有分散分支

**實證 A**：[RepairItemsPage.tsx:102](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/repairs/RepairItemsPage.tsx:102) 有 `useArm` 確認、`await del.mutateAsync`，但刪除鈕 [155](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/repairs/RepairItemsPage.tsx:155) 無 `disabled={del.isPending}`、無 armed class、無處理中標示。第二次確認重設後，慢網路期間仍可再次開始一輪確認。這是前端重入窗口，不宣稱後端已產生重複刪除或帳務錯誤。

**實證 B**：[ArmButton.tsx:44](/Users/tsairunghuang/MP_POS系統/frontend/src/components/workbench/ArmButton.tsx:44) 已有同步 `running`、4 秒、500ms、等待 Promise、disabled 防重；但顯示 [77](/Users/tsairunghuang/MP_POS系統/frontend/src/components/workbench/ArmButton.tsx:77) 在 busy 期間仍是「再按一次…」，沒有 busy 文案或 `aria-busy`。可補可選 `pendingLabel`，不另造另一套危險按鈕。

**實證 C**：盤點 [StockCountPage.tsx:412](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/inventory/StockCountPage.tsx:412) 作廢是 `className=btn`；雜支 [PettyExpenseForm.tsx:241](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/cash/PettyExpenseForm.tsx:241)、調撥 [TransferWorkbenchPage.tsx:1087](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/transfers/TransferWorkbenchPage.tsx:1087) 已採 danger。屬同種不可逆動作外觀尚未一致，**不是盤點缺少二次確認**。

**建議與驗收**：維修刪除接共用安全按鈕或等價同步鎖，保留逐筆確認；armed 琥珀、執行中可辨識、不可重入、錯誤可重試、完成才移除列。盤點作廢套 danger，不把「退回」或局部未存草稿移除一律判成危險。用延遲回應驗一次完整生命週期，連點不多送；切換目標不得沿用確認。

另留待批發恢復檢查：[TradeBookTab.tsx:258](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/trade/TradeBookTab.tsx:258) `act()` 回 void，[282](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/trade/TradeBookTab.tsx:282) 的 `onConfirm={async () => act("new")}` 並未回傳真正網路 Promise；雖外層仍有 `run.isPending`，未能使用 ArmButton 的完整等待契約。只列契約不一致，不斷言一定可重送。

## T06：補明確的控制名稱，不靠附近文字猜

**實證**：維修歷史視窗關閉 [RepairHistoryModal.tsx:34](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/repairs/RepairHistoryModal.tsx:34) 只有 `×`，無 `aria-label`／title；進貨商品選擇 [PurchaseProductPickerModal.tsx:238](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/purchases/PurchaseProductPickerModal.tsx:238)、批次貼上 [PurchaseBatchPasteModal.tsx:441](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/purchases/PurchaseBatchPasteModal.tsx:441) 的逐列 checkbox 未和商品名或列號建立名稱關聯。

**建議**：圖示關閉加「關閉維修歷史」名稱；逐列勾選加「選取＋商品名／輸入第 N 列」可及名稱。多筆同名需有能區別的規格或列號。保持 checkbox，勿換 switch。對照可沿用的做法：收貨 [ReceiveDrawer.tsx:275](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/vendor-orders/ReceiveDrawer.tsx:275) 已明確命名「商品＋這次入庫」。

**驗收**：用可及樹／讀屏檢查名稱唯一可辨；Tab 至逐列勾選不用靠表格位置猜商品；停用品仍不可選；close 仍只關視窗、不清表單。圖示按鈕的最終觸控尺寸另以裝置量測，不因只看文字小便斷言不合格。

## T07：群組全選需呈現部分選取，保留 checkbox 的業務意思

**實證**：盤點新入庫群組 [StockCountPage.tsx:794](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/inventory/StockCountPage.tsx:794) 只算 `all`，群組 checkbox 的 checked=false 同時代表「一筆未選」及「選了一部分」，未設 indeterminate。批發商品 [TradeGoodsTab.tsx:178](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/trade/TradeGoodsTab.tsx:178) 同型；中古機「跟價目」[TradeUnitList.tsx:249](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/trade/TradeUnitList.tsx:249) 也未呈現部分列跟隨。

**建議**：共用三態 checkbox（全不選／部分／全選），搭配現有數量。明示影響「目前群組／目前篩選列」，不悄悄擴及未載入資料。跟價目是勾選待套用規則，不改成即時儲存 switch。

**驗收**：選一筆→群組 mixed；全選→checked；全取消→unchecked；篩選／群組切換不殘留錯範圍；盤點在核准檢視才出現的選取權限不變。此次只改善控制呈現，不增加盲盤階段的帳上數量、缺少品清單、差異或金額。

## T08：primary 用於主要執行，不兼任展開狀態與每列捷徑

**實證**：庫存警示每列 [InventoryAlertsPage.tsx:194](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/inventory/InventoryAlertsPage.tsx:194)「去進貨」、[299](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/inventory/InventoryAlertsPage.tsx:299)「調整售價」都是 primary link。批發 [TradeBookTab.tsx:233](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/trade/TradeBookTab.tsx:233) 展開「記收款／報價頁」時改 primary，卻沒有 expanded／controls。

**建議**：列表列內捷徑採標準次要／文字動作，保留帶商品的 deep link；primary 留給目前任務的主要提交。展開鈕以可見展開符號＋expanded 表示狀態，內層真正儲存才是 primary。不是強制「一頁永遠只能一顆藍鈕」，若獨立工作區各有提交，仍可保留。

**驗收**：10／50 列警示頁比較資訊焦點；仍一步帶正確商品進貨／調價；展開與收起名稱、焦點順序清楚；不得把 navigation link 改成提交動作。這是層級建議，需真畫面比較，源碼不足以證明目前已嚴重干擾。

## 已一致、應保留的地方與不可越界事項

1. **共用安全動作**：`ArmButton` 的雙擊排除、4 秒到期、同步 running、卸載處理與等待 Promise 均保留。[ArmButton.tsx:44](/Users/tsairunghuang/MP_POS系統/frontend/src/components/workbench/ArmButton.tsx:44) 不把所有一般儲存都改成二次確認。
2. **退貨與個人收購區分是刻意的**：整張退總額與按鈕同列，確認綁原單／退款方式／發票；個人收購仍一步儲存、送出中鎖定。[SalesReturnEntryPage.tsx:300](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/sales/SalesReturnEntryPage.tsx:300)、[SecondhandPersonalEntry.tsx:502](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/secondhand-acquisition/SecondhandPersonalEntry.tsx:502)、[決策](/Users/tsairunghuang/MP_POS系統/docs/decisions.md:3385)
3. **雜支／現金調整／代收**：一次存、Enter 不送、保留防重送及 pending；存好不可改，只能依權限作廢再重記。不得因「操作一致」重新加編輯或確認頁。[PettyExpenseForm.tsx:221](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/cash/PettyExpenseForm.tsx:221)、[CashAdjustmentForm.tsx:185](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/cash/CashAdjustmentForm.tsx:185)、[決策](/Users/tsairunghuang/MP_POS系統/docs/decisions.md:3368)
4. **未知送出結果不是普通錯誤**：銷／進工作台的 draft、pending／unsure／frozen 與 request key 保留；收貨「再送一次」只能重送同一份，不能解除鎖定讓使用者改成另一筆。[PurchaseWorkbenchPage.tsx:501](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/purchases/PurchaseWorkbenchPage.tsx:501)、[SalesWorkbenchPage.tsx:520](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/sales/SalesWorkbenchPage.tsx:520)、[ReceiveDrawer.tsx:89](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/vendor-orders/ReceiveDrawer.tsx:89)
5. **收貨數量／序號、運費、貨到付款**：本次純控制規格，不能改預設帶入、費用計算、收貨內容或放寬整單作廢。checkbox「本次收這批序號」不是 switch；普通配件仍是數量。[ReceiveDrawer.tsx:270](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/vendor-orders/ReceiveDrawer.tsx:270)
6. **調撥的入庫與作廢分清楚**：已有兩段按鈕，目的門市確認與作廢權限各自控制。[TransferWorkbenchPage.tsx:1073](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/transfers/TransferWorkbenchPage.tsx:1073) 不把兩階段調撥合成一次。
7. **盤點**：手機已排隊、同 operation 重送、未確定動作不可超車。[PhoneCountPage.tsx:140](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/inventory/PhoneCountPage.tsx:140) 保留「刷完」checkbox 的人為聲明；帳上有未盤配件僅待核准管理員可見、不自動歸零、未知碼先解決才送；這些不能為控制統一而拿掉。[既定盲盤邊界](/Users/tsairunghuang/MP_POS系統/docs/decisions.md:3196)
8. **數量輸入**：`QtyInput` 保留打字中的文字，合法才 commit、離開再處理非法值，避免一邊輸入一邊強改數值。[QtyInput.tsx:16](/Users/tsairunghuang/MP_POS系統/frontend/src/components/workbench/QtyInput.tsx:16)
9. **密度與版型**：owner 已接受桌面 small 32px、tabs 36px，手機頁保留大按鈕；不能為追求一種尺寸把手機盤點等縮小。[按鈕尺寸決策](/Users/tsairunghuang/MP_POS系統/docs/decisions.md:3309) 商品雙欄、會員獨立編輯是後續明確決定，此次不提出回退。[版型決策](/Users/tsairunghuang/MP_POS系統/docs/decisions.md:3377)

## 後續驗收：區分源碼完成與實機完成

| 場景 | 驗收重點 | 證據要求 |
|---|---|---|
| 共用按鈕／選單 | normal／hover／focus-visible／disabled／armed／pending／error；深淺色 | 樣式檢查＋實際鍵盤畫面，不能只用 class 名稱判合格 |
| 銷貨、進貨、調撥 | 刷碼不中斷；更多／查圖返回焦點；明細多行時提交仍可見 | 測試環境 fixture，攔截寫入或隔離資料；對網路請求數量記錄，不操作正式資料 |
| 退款、作廢、核准 | 兩段時間／換單重設／pending 防重 | 可重現互動測試；需真實狀態影響的測試另以隔離資料驗，非本報告已完成 |
| 表單／收貨抽屜 | 鍵盤能到每一欄；底部 CTA 不蓋內容；390px、768px、1366px、200% | 實際 viewport、焦點與截圖；重點讀序號與金額，不只看頁首 |
| 觸控 | small／icon／chip 間距可可靠點按；橫滑表格不誤點提交 | 實測實際 hit area 及手機；不能由 source 字體大小推斷合格或失敗 |
| 盤點 | 操作者與審核者分別看；沒有新增盲盤洩漏；大按鈕／相機／重送仍可用 | 角色＋手機測試；保留 operation 次序與未知結果保護 |

## 實際覆蓋目錄與深度

以下是**源碼控制項盤點覆蓋**，非每一分支皆操作驗收。逐段檢查表示讀了主要狀態／事件／JSX；搜尋檢查表示定位主要按鈕、checkbox、disabled／aria 使用並對照周邊，不保證全頁其他問題已排除。

| 目錄 | 逐段檢查 | 控制項搜尋／抽查 |
|---|---|---|
| `frontend/src/components/workbench/` | `ArmButton.tsx`、`useArm.ts`、`MoreMenu.tsx`、`ScanBox.tsx`、`QtyInput.tsx` | 未將 `errors.ts`／`toast.tsx` 當完整通知系統稽核 |
| `frontend/src/pages/sales/` | `SalesWorkbenchPage.tsx`、`SalesReturnEntryPage.tsx` 主要交易控制 | `SalesListPage.tsx`、`SalesPage.tsx`；列印頁不含實體列印驗收 |
| `frontend/src/pages/purchases/` | `PurchaseWorkbenchPage.tsx`、`PurchaseProductPickerModal.tsx`、`PurchaseBatchPasteModal.tsx` | `PurchaseListPage.tsx`、`PurchaseLinesPage.tsx`、`SerialSlots.tsx`、`SecondhandSheetImport.tsx` |
| `frontend/src/pages/inventory/` | `InventoryQueryPage.tsx`、`InventoryAlertsPage.tsx`、`StockCountPage.tsx`、`PhoneCountPage.tsx` | `StockCountsPage.tsx`、`SerialListPage.tsx`、`StockFlowPage.tsx`、`StockMovesPage.tsx`、`VendorExchangesPage.tsx`；`CategoriesPage.tsx` 主檔由其他稽核處理 |
| `frontend/src/pages/transfers/` | `TransferWorkbenchPage.tsx` 送出、清單入庫／作廢控制 | 未核算庫存服務 |
| `frontend/src/pages/cash/` | `PettyExpenseForm.tsx`、`CashAdjustmentForm.tsx` | `CashAdjustmentsPage.tsx`、`PettyExpensesPage.tsx` 控制定位；無帳務數值驗收 |
| `frontend/src/pages/phone-bills/` | `PhoneBillForm.tsx` | `PhoneBillsPage.tsx`；收據列印未實機驗 |
| `frontend/src/pages/repairs/` | `RepairItemsPage.tsx`、`RepairHistoryModal.tsx`、`RepairEntryPage.tsx` 主要控制 | `RepairsPage.tsx`、`UnlockPatternInput.tsx`；收據頁不含印表機驗收 |
| `frontend/src/pages/vendor-orders/` | `ReceiveDrawer.tsx`、`ManualReceiveDrawer.tsx`、`VendorOrdersPage.tsx` 選擇控制 | `MappingTab.tsx` 低頻映射未作深度流程測試；保留暫停範圍 |
| `frontend/src/pages/trade/` | `TradeUnitList.tsx`、`TradeGoodsTab.tsx`、`TradeBookTab.tsx` | `TradeOrdersTab.tsx`、`TradeSettingPanel.tsx`、`TradeUnitsTab.tsx`；`TradePage.tsx`／`TradeUnitChanges.tsx` 非本次深讀重點；全部維持後排 |
| `frontend/src/pages/secondhand-acquisition/` | `SecondhandPersonalEntry.tsx` 付款／儲存 | `SecondhandAcquisitionPage.tsx` 頁籤控制 |

本報告沒有找到足夠證據支持「交易頁所有按鈕都要重做」或「所有 checkbox 應改 switch」。建議先處理 T02～T07 的營運頁與共用元件，T08 用真畫面比較；T01 及其他批發差異保留在後續啟用清單。
