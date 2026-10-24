# MP POS 控制項盤點：主檔與共用表單

- 基準：2026-10-25 唯讀核對本機 `/Users/tsairunghuang/MP_POS系統`，`git rev-parse --short HEAD` = `ebf7e0e`。
- 方法：逐檔掃描本範圍按鈕、欄位、分頁／選擇控制、事件處理、停用／進行中狀態與對應 CSS；重要項目閱讀上下文。本報告是原始碼證據，沒有啟動應用、登入網站、讀資料庫、發網路請求或執行資料操作，驗收均尚待執行。
- 本次只寫本檔。以目前源碼重新判定，未將舊版缺陷照抄為現況。
- 優先序：P1 = 控制會執行錯誤行為或讓人誤認結果；P2 = 可辨識性、鍵盤、狀態與一致性；P3 = 樣式整理或低頻不實提示。

## 建議先定的控制角色

| 角色 | 使用方式 | 不應混用 |
|---|---|---|
| 主要動作 | 同一操作區的儲存、建立、查詢；藍底，內容寬度 | 不拿來表達已選的資料值 |
| 次要動作 | 取消、返回、下載範本、重試 | 不假裝取消已送到伺服器的寫入 |
| 危險／兩段確認 | 刪除、會覆寫內容的套用；第一次黃底＋明確再按提示 | 不能只有換文字卻維持一般／藍色狀態 |
| 頁內分頁 | 切同一頁的內容面板；tablist/tab/tabpanel | 不同於將儲存進資料的商品性質 |
| 單選欄位 | 商品性質、倉別、庫存記法；有群組名稱的 radio／radiogroup | 不用只有 `.active` 的按鈕讓人猜目前值 |
| 篩選 | 來源類別、合約狀態；可看出已套用條件 | 不等同主動提交動作 |
| 勾選／即時開關 | 勾選可待儲存；即時開關需有進行中、成功／失敗狀態 | 同一外觀不能有的立即生效、有的還要儲存卻未說明 |
| 圖示動作 | 共用 IconButton，包含尺寸、鍵盤焦點與「動作＋對象」名稱 | 不各頁自己寫 16px 的 ×、透明 padding:0 |
| 狀態標籤 | 顯示已停用、銷退等，不可點 | 不與動作膠囊共用 pointer/hover CSS |

## 可執行 findings

### MC-01｜P1｜表格／卡片快捷鍵會吃到裡面控制項的按鍵

- 證據：[MasterDetail.tsx:118](/Users/tsairunghuang/MP_POS系統/frontend/src/components/master-detail/MasterDetail.tsx:118) 的列 `onKeyDown` 不區分事件來自列本身還是子元素，攔截上下、Enter、空白。
- 實際受影響：[TelecomPlansPage.tsx:255](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/telecom-plans/TelecomPlansPage.tsx:255) 的列勾選、[295](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/telecom-plans/TelecomPlansPage.tsx:295) 的佣金輸入及 [356](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/telecom-plans/TelecomPlansPage.tsx:356) 的啟用勾選只阻擋 click 冒泡。鍵盤空白被父列 preventDefault、改開詳細；佣金 Enter 觸發 blur 後仍冒泡開詳細，上下鍵也會離開欄位。
- 同型問題：[ProductTypesPage.tsx:525](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/products/ProductTypesPage.tsx:525) 外層卡片的 Enter／空白會接到內層刪除鈕事件。
- 建議角色：列是「開啟記錄」，列內 checkbox/input/button 各自保有原生操作。列快捷鍵只處理自己的焦點事件或排除互動後代；產品類型可用獨立編輯連結與刪除鈕，避免互動巢狀。
- 驗收：非空電信清單至少三列；Tab 到第二列勾選按空白只能改勾選，不開詳細；佣金欄 Enter 只送該欄、上下鍵不跳列；列本身仍可上下移動、Enter 開啟。產品類型刪除鈕按 Enter 只進入該筆確認，不能同時開編輯。

### MC-02｜P1｜送出中保留可用的「取消／上一步」，但請求沒有被取消

- 證據：[SimCardForm.tsx:144](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/sim-cards/SimCardForm.tsx:144)、[TelecomPlanForm.tsx:162](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/telecom-plans/TelecomPlanForm.tsx:162)：只有儲存鈕 disabled；取消、Drawer 的 ×／Escape／遮罩仍會關閉；submit 成功後仍執行 onClose。
- 同樣存在於 [BulkCreatePartsModal.tsx:532](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/products/BulkCreatePartsModal.tsx:532) 的取消／上一步、[ProductExpanderModal.tsx:774](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/products/ProductExpanderModal.tsx:774)、[BulkEditProductsModal.tsx:577](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/products/BulkEditProductsModal.tsx:577)、[BrandSeriesImportModal.tsx:284](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/products/BrandSeriesImportModal.tsx:284)。這些關閉動作不是伺服器寫入取消。
- 建議角色：送出期間固定為「處理中」，鎖住會關閉、重設或改換這次操作的控制；完成或明確失敗才恢復。若產品刻意允許背景送出，關閉須明說「背景繼續」，並留結果回報，不能叫取消。
- 驗收：用本機 fixture／攔截回應延遲3秒，不用真資料；送出後測取消、×、Esc、遮罩、上一步，不能離開成另一份可編表單。成功只回報一次；500或斷線保留輸入與可見錯誤；按恢復後的取消才離開。不要宣稱按鈕停用等於後端冪等已驗證。
- 可沿用：[ProductForm.tsx:893](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/products/ProductForm.tsx:893) 已用 lockBackdrop 與 `frozen={peeking || busy}`；[DeviceLibraryStep.tsx:119](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/products/DeviceLibraryStep.tsx:119) 建立中也鎖取消，應保留。

### MC-03｜P2｜Drawer 與自製彈窗的焦點及名稱規則不完整

- 證據：[Drawer.tsx:28](/Users/tsairunghuang/MP_POS系統/frontend/src/components/Drawer.tsx:28) 只有 Escape 監聽；[43](/Users/tsairunghuang/MP_POS系統/frontend/src/components/Drawer.tsx:43) 使用 aside，沒有 dialog 名稱、開啟時移入焦點、Tab 範圍或關閉後回觸發鈕。`frozen` 只讓抽屜自身 inert，不能取代背景頁隔離。
- [BrandSeriesImportModal.tsx:93](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/products/BrandSeriesImportModal.tsx:93)、[ProductExpanderModal.tsx:393](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/products/ProductExpanderModal.tsx:393)、[BulkAddTelecomPlansModal.tsx:228](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/telecom-plans/BulkAddTelecomPlansModal.tsx:228) 有 dialog/aria-modal，但標題未用 aria-labelledby 連結，未見焦點邊界與回復處理；[ProductImportModal.tsx:116](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/products/ProductImportModal.tsx:116) 另有一套。
- 建議角色：統一受控 Dialog/Drawer 容器，具名稱、初始焦點、焦點範圍、回復焦點及 busy/dirty 關閉策略。使用者選的「整頁商品建檔」仍是頁面，不要因此改回彈窗。
- 驗收：純鍵盤從新增／批次工具開啟；讀屏可辨識標題；Tab與Shift+Tab不跑到背景儲存／導覽；關閉回到原按鈕；疊加照片面板只操作最上層。busy/dirty 的關閉條件遵守各流程，不因補 Escape 而繞過保護。

### MC-04｜P2｜搜尋選擇器的名稱、展開狀態及清除操作不完整

- 證據：[ComboBox.tsx:247](/Users/tsairunghuang/MP_POS系統/frontend/src/components/ComboBox.tsx:247) 是普通 text input，未有 combobox、aria-expanded、aria-controls、aria-activedescendant；選項雖有 listbox/option，沒有與輸入框連起來。[275](/Users/tsairunghuang/MP_POS系統/frontend/src/components/ComboBox.tsx:275) 清除 × 是 `tabIndex={-1}`，沒有對等鍵盤清除動作。
- [PhoneModelPicker.tsx:155](/Users/tsairunghuang/MP_POS系統/frontend/src/components/PhoneModelPicker.tsx:155) 同樣未連結輸入與選項。[Field.tsx:26](/Users/tsairunghuang/MP_POS系統/frontend/src/components/Field.tsx:26) 刻意排除 combobox，所以外包 Field 不能補上其欄名。SourcePicker 的名稱目前主要靠 placeholder。
- 建議角色：共用有名稱的 Combobox API，接受 id/aria-labelledby/aria-describedby；選項有穩定 id，宣告展開與目前候選。清除鈕加入鍵盤可達途徑，名稱包含欄位（例如「清除相容機型」），並保留有值後 Enter 下一行、IME輸入與完全相同才選取規則。
- 驗收：在兩個選擇器同時存在的非空表單，用鍵盤／讀屏可分清「類別」「廠商／來源」「機型」；上下鍵朗讀目前候選；停用候選不會選到；可清空非必填關聯；慢查詢不會選到上次結果；中文選字 Enter 不提交。

### MC-05｜P2｜一般欄位的欄名規則只在部分表單落地

- 證據：[MembersPage.tsx:290](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/members/MembersPage.tsx:290) 使用 dt/dd 放姓名、電話、會員類型等 input/select，沒有 label/id/aria-labelledby；來源 [CustomersPage.tsx:372](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/customers/CustomersPage.tsx:372)、廠商 [SuppliersPage.tsx:337](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/suppliers/SuppliersPage.tsx:337)、業務員 [SalesPersonsPage.tsx:228](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/sales-persons/SalesPersonsPage.tsx:228) 同型。表格內電信佣金與列勾選也缺「欄名＋記錄」可辨識名稱。
- 建議角色：單格原生欄位沿用已存在的 Field 或明確 label；表格控制使用「某方案的業務員佣金／選取某方案」名稱。不是把唯讀歷史的 dl 都改為表單。
- 驗收：點欄名移到對應輸入；讀屏可分清會員姓名與電話、電信每列兩種佣金；必填及錯誤與該欄關聯。個人／公司切換後不殘留錯誤欄名，不能靠 placeholder 當唯一名稱。
- 已正確：[Field.tsx:13](/Users/tsairunghuang/MP_POS系統/frontend/src/components/Field.tsx:13) 已為唯一原生輸入綁欄名與錯誤，不要重做另一套。

### MC-06｜P2｜真分頁、篩選和表單單選混用外觀及 `.active` 狀態

- 來源分類：[CustomersPage.tsx:254](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/customers/CustomersPage.tsx:254)；商品主面板與基本／別名：[ProductsPage.tsx:470](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/products/ProductsPage.tsx:470)、[808](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/products/ProductsPage.tsx:808)；商品類別值：[KindPicker.tsx:12](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/products/KindPicker.tsx:12)。三種角色都叫 tab-switcher，主要只靠 class active。
- 商品倉別／性質：[ProductForm.tsx:1502](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/products/ProductForm.tsx:1502) 使用 pf-tab；匯入庫存記法 [ProductImportModal.tsx:137](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/products/ProductImportModal.tsx:137) 亦然；共用明細 [MasterDetail.tsx:149](/Users/tsairunghuang/MP_POS系統/frontend/src/components/master-detail/MasterDetail.tsx:149) 是底線 tabs；合約頁 [ContractsPage.tsx:346](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/telecom/ContractsPage.tsx:346) 是圓膠囊 wb-chip。
- 樣式證據：[styles.css:1540](/Users/tsairunghuang/MP_POS系統/frontend/src/styles.css:1540)、[1993](/Users/tsairunghuang/MP_POS系統/frontend/src/styles.css:1993)、[3731](/Users/tsairunghuang/MP_POS系統/frontend/src/styles.css:3731)、[7063](/Users/tsairunghuang/MP_POS系統/frontend/src/styles.css:7063)。高度、padding、邊框、選中樣式分散。
- 建議角色：先分成 Tabs、FilterChoice、SegmentedRadio 再共用尺寸／色彩 tokens；真分頁補 tab/tabpanel 與 aria-selected；表單單選補群組名稱與 checked；篩選補已選狀態。不要單純所有控制加 role=tab。
- 驗收：盲看 DOM／讀屏可知道是在切面板、篩選資料還是改待存值；每組只有一個 selected/checked；鍵盤依對應角色切換；淺／深色與390/1440px尺寸一致且不壓掉文字。合約頁重按目前分類會重抓的現有規則應保留，不應在統一樣式時默默改掉。

### MC-07｜P2｜兩段確認已換字，卻未套共用黃色 armed 狀態

- 規格：[styles.css:495](/Users/tsairunghuang/MP_POS系統/frontend/src/styles.css:495) 宣告一律黃色；但品牌刪除 [BrandSeriesPage.tsx:430](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/products/BrandSeriesPage.tsx:430)、系列刪除 [639](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/products/BrandSeriesPage.tsx:639)、品況刪除 [ConditionsPage.tsx:359](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/products/ConditionsPage.tsx:359) 仍固定 `btn danger`。
- 電信批次上／下架 [TelecomPlansPage.tsx:466](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/telecom-plans/TelecomPlansPage.tsx:466)、商品批次修改 [BulkEditProductsModal.tsx:580](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/products/BulkEditProductsModal.tsx:580)、範本套用 [PartTemplatesPage.tsx:539](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/products/PartTemplatesPage.tsx:539) 同樣只換字；產品類型雖有 `icon-btn armed`，共用黃色 selector 只涵蓋 btn/wb-btn。
- 建議角色：獨立動作用 ArmButton；保留 useArm 的地方統一輸出 armed class／狀態，包含圖示與選擇型動作，不改原確認key與寫入算法。
- 驗收：每類至少一筆，第一次字＋顏色／非色彩提示一致；0.5秒內第二下不執行，4秒後復原，換對象不能承接前一筆確認；執行中有一致 busy 提示且不可連送；深淺主題均辨識。

### MC-08｜P2｜勾選與開關的儲存時機、鎖定狀態混用

- 品況 [ConditionsPage.tsx:180](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/products/ConditionsPage.tsx:180)、產品類型 [ProductTypesPage.tsx:417](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/products/ProductTypesPage.tsx:417)、範本 [PartTemplatesPage.tsx:606](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/products/PartTemplatesPage.tsx:606) 的滑動開關只改表單，要儲存才生效；電信列表 [TelecomPlansPage.tsx:356](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/telecom-plans/TelecomPlansPage.tsx:356) 普通 checkbox 反而即時送出。
- [ConditionsPage.tsx:208](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/products/ConditionsPage.tsx:208) 可鎖定「逐台記機況」，但 [styles.css:5858](/Users/tsairunghuang/MP_POS系統/frontend/src/styles.css:5858) 的 toggle-track 沒 disabled 對應樣式；只有提示文字，外觀仍像可操作的藍色開關。
- 建議角色：待存表單統一 checkbox／明確待儲存提示；即時持久化的 switch 有 busy/saved/failed；鎖定控制視覺、cursor、讀屏狀態與可見原因一致。保留中古必開的商業規則。
- 驗收：同樣「啟用」可清楚分辨要不要再儲存；即時切換延遲與失敗時不把畫面假裝成成功；鎖定逐台機況的狀態與理由在滑鼠、觸控、鍵盤下均可辨識，不能被鍵盤關掉。

### MC-09｜P2｜圖示控制各頁自寫，名稱與點擊範圍不一致

- [BulkEditProductsModal.tsx:534](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/products/BulkEditProductsModal.tsx:534)、[ProductExpanderModal.tsx:566](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/products/ProductExpanderModal.tsx:566) 的 × 以 inline style 設透明、0 padding、16px文字，只有泛稱 title「移除」。
- [NewPhoneModelWizardPage.tsx:96](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/products/NewPhoneModelWizardPage.tsx:96)、[PartTemplatesPage.tsx:209](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/products/PartTemplatesPage.tsx:209) 名稱已包含值，但仍複製 inline 樣式；範本刪除列 [794](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/products/PartTemplatesPage.tsx:794) 名稱只叫「刪除」。[styles.css:5958](/Users/tsairunghuang/MP_POS系統/frontend/src/styles.css:5958) icon-btn 固定28×28，與一般44px控制不同。
- 建議角色：共用 compact IconButton，桌機視覺可小，但點擊區、focus、disabled、danger、armed 都有標準；名稱「移除 iPhone 16」「刪除螢幕零件」等動作＋對象。欄距用容器 gap，避免每頁 inline padding/color。
- 驗收：含三個以上 chips/明細的表單，讀屏能區分每個 ×；鍵盤逐一可達、焦點清楚；手機不誤按相鄰 chip；disabled/armed 不只改 title；不得因此把整組 chips 撐成巨型按鈕。

### MC-10｜P3｜動作膠囊與狀態標籤共用 `.pill`，容易跨頁互相覆蓋

- [styles.css:1464](/Users/tsairunghuang/MP_POS系統/frontend/src/styles.css:1464) 定義狀態 pill，之後 [5814](/Users/tsairunghuang/MP_POS系統/frontend/src/styles.css:5814) 同名改成膠囊鈕並加 pointer/hover；範本 [PartTemplatesPage.tsx:542](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/products/PartTemplatesPage.tsx:542) 用於套用、[702](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/products/PartTemplatesPage.tsx:702) 用於加入明細。全域搜尋另確認 [CommissionLinesPage.tsx:123](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/reports/CommissionLinesPage.tsx:123) 用 span.pill.void 顯示不可點的銷退標籤（只核對此共用樣式使用點，未稽核整個報表頁）。
- 建議角色：狀態 Badge 與動作 button 分名；範本套用／加入使用次要動作或明確 quick-action variant，沿用共用 tokens，非互動 Badge 無 pointer/hover。
- 驗收：銷退標籤移上去不呈現可點；範本快捷動作仍可滑鼠／鍵盤觸發；淺深色樣式不互相蓋，armed 提示遵守 MC-07。

### MC-11｜P3｜產品類型仍顯示未實作的拖曳把手

- [ProductTypesPage.tsx:533](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/products/ProductTypesPage.tsx:533) 的 GripIcon 顯示「拖曳調整順序(尚未啟用)」，只有 stopPropagation，沒有拖曳排序。這不是需重做商品類型入口的理由。
- 建議角色：未提供的操作移除把手，排序維持現有明確欄位／動作；若未來實作排序，需同時提供鍵盤替代。
- 驗收：畫面沒有只能看卻不能操作的抓手；既有排序顯示及儲存行為不變。

## 已一致，應保留

1. `.btn` 與 `.wb-btn` 共用主要藍色、一般、danger、small及armed；根據 `--btn-pad-x`、`--btn-radius` 控制，不應再新增另一套按鈕基本樣式。手機專用大按鈕不是這次縮小目標。
2. [EyeToggle.tsx:8](/Users/tsairunghuang/MP_POS系統/frontend/src/components/EyeToggle.tsx:8) 已有動作名稱、title、aria-pressed及隱藏裝飾SVG，保留既定只用眼睛圖示需求。
3. [AppliedFilters.tsx:10](/Users/tsairunghuang/MP_POS系統/frontend/src/components/AppliedFilters.tsx:10) 將不可點條件標籤和「清除條件」按鈕分開；[SamePhonePick.tsx:17](/Users/tsairunghuang/MP_POS系統/frontend/src/components/SamePhonePick.tsx:17) 有群組名稱與原生按鈕。
4. [SimCardsPage.tsx:127](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/sim-cards/SimCardsPage.tsx:127) 狀態 select 有 label；搜尋已接 `onSearch`／受控 `searchValue`，有套用條件與失敗重試。不能再列為「SIM搜尋沒接」。
5. 共用 MasterDetail 已有列方向鍵、單一Tab停點、關閉後回列；應修 MC-01 的事件邊界，保留這些能力，不退回每列一個Tab停點。
6. [ContractsPage.tsx:263](/Users/tsairunghuang/MP_POS系統/frontend/src/pages/telecom/ContractsPage.tsx:263) 狀態動作位置固定、目前狀態 aria-pressed且停用，busy期間禁止再操作；這是有明確狀態語意的可沿用例子。
7. 主檔手機面板／PaneBack、來源與範本及相關主檔草稿保護、商品返回清單狀態已在當前源碼存在。本次沒有把舊審查項目重列；也沒有據此宣稱所有裝置與流程驗收通過。
8. 會員點姓名看獨立唯讀歷史、原頁全寬；明按編輯才開右側是後續決策。商品整頁建檔／編輯、型號庫全規格建立、新增分頁回原頁等決策不可因控制項統一而改掉。來源／會員／廠商語意、金額與庫存算法、權限與資料寫入規則不在本次重設範圍。

## 覆蓋清單

以下是已掃描控制項並核對相關上下文的檔案；不是對所有業務算法做完整審查。根目錄均為 `/Users/tsairunghuang/MP_POS系統/frontend/src/`。

- `pages/customers/`：CustomersPage.tsx。
- `pages/members/`：MembersPage.tsx、MemberHistoryPage.tsx、LegacyHistorySection.tsx、LegacyLinkCandidates.tsx。
- `pages/suppliers/`：SuppliersPage.tsx。
- `pages/sales-persons/`：SalesPersonsPage.tsx（專案實際目錄，不是 salespeople）。
- `pages/sim-cards/`：SimCardsPage.tsx、SimCardForm.tsx。
- `pages/telecom-plans/`：TelecomPlansPage.tsx、TelecomPlanForm.tsx、BulkAddTelecomPlansModal.tsx。
- `pages/telecom/`：ContractsPage.tsx。
- `pages/products/`：ProductsPage.tsx、ProductForm.tsx、ProductFormPage.tsx、NewPhoneModelWizardPage.tsx、DeviceLibraryStep.tsx、FindFirstPanel.tsx、DuplicatePanel.tsx、KindPicker.tsx、ProductTypesPage.tsx、ConditionsPage.tsx、BrandSeriesPage.tsx、BrandSeriesImportModal.tsx、PartTemplatesPage.tsx、ProductAliasesPanel.tsx、ProductExpanderModal.tsx、ProductImportModal.tsx、BulkCreatePartsModal.tsx、BulkEditProductsModal.tsx、BulkDuplicateRows.tsx。pickActiveProduct.ts無渲染控制項，未列為UI頁。
- `components/`：ComboBox.tsx、PhoneModelPicker.tsx、SourcePicker.tsx、StoreSelect.tsx、Field.tsx、MoneyInput.tsx、Drawer.tsx、EyeToggle.tsx、PaneBack.tsx、AppliedFilters.tsx、PeriodQuick.tsx、SamePhonePick.tsx、Toolbar.tsx。
- `components/master-detail/`：MasterDetail.tsx。
- `components/workbench/`：ArmButton.tsx、useArm.ts、MoreMenu.tsx（確認／具名工具選單共用基礎；不包含工作台其他業務操作）。
- 共用樣式：styles.css 的 btn/wb-btn、tab-switcher/ia-tab、md-detail、pf-tab、wb-chip、pill、toggle-switch、icon-btn及主要表單規則。
- 規範：AGENTS.md、docs/ui-patterns.md相關控制項段落、docs/decisions.md相關後續決策；目前任務文件只作範圍背景，不視為部署驗收證據。

## 建議施工及驗收順序

1. 先修 MC-01／MC-02，使用本機非空fixture驗鍵盤與延遲／失敗回應；不必為統一樣式操作正式資料。
2. 再完成 Dialog、ComboBox、Field 的共用狀態／名稱／焦點契約，逐頁接上。
3. 分清 Tabs／FilterChoice／Radio／Checkbox／Switch 後統一尺寸與色彩；最後收斂圖示、armed、pill與inline視覺樣式。
4. 最小代表組：會員編輯、來源分類、商品多款展開與批次修改、品牌系列、範本、電信方案、SIM卡；每組覆蓋非空／無結果／失敗、一般／管理員能力、淺深色、390及1440px、鍵盤及觸控。表單仍保留未存保護，歷史仍唯讀。
