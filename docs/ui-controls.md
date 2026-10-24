# 全站控制項規範

> 本檔是 `ui-patterns.md` 的控制項專章。新增頁面、改造既有控制項與共用元件時都依本檔判斷；尺寸與行為只能在共用層定義。現有畫面尚未全部遷移，不把規範發布當成程式已完成。遷移順序見 [修改計劃與驗收](MP_POS_全站控制項統一_修改計劃與驗收_2026-10-25.md)。

## 1. 先決定用途，再選外觀

| 用途 | 使用方式 | 選取／狀態表現 | 不適用 |
|---|---|---|---|
| 執行動作 | 共用 Button；保留既有 `.btn`／`.wb-btn` 相容入口 | 主動作淡色:藍字＋淡藍細框＋很淡的藍底(`--primary-*`);新增、查詢、複製、匯出、返回等一般動作:跟頁面同底、深色字、細框;低頻輔助動作用文字型 | 不能用 `primary` 表示選取;不用鮮藍實心白字 |
| 換頁／換工作區 | 路由用 NavLink；同頁工作區用 Tabs | 文字＋底線，當前項目有語意狀態 | 不用一排「儲存鈕」大小的藍底方塊 |
| 少量互斥條件／值 | 2–4 個且名稱短時用 SegmentedControl；長名稱或更多選項用 Select | 單選;沒選的透明、選中中性淺底(`--ctl-selected`)＋字重,不借表格選取色 | 不用 switch；不能同時有兩個選取項 |
| 選擇工作對象 | 有欄名的 Select；大量資料沿用 ComboBox；少量且高頻時可用具欄名的標準單選列 | 門市、分類、廠商分欄標示；狀態另外顯示，保留原選取與草稿規則 | 不把「未開通」寫成按鈕動作，也不把廠商分類當商品分類 |
| 多個可同時套用條件 | Checkbox | 每項獨立勾選，可複選 | 不強制互斥，例如返修與逾期可並存 |
| 即時啟用／停用設定 | Switch 或共用的即時儲存 Checkbox；要顯示成功／失敗 | checked 來自確認資料與受控狀態；存檔中鎖定，失敗回復或明示未存 | 不用於分頁、查詢模式、需按儲存才生效的表單值 |
| 表單布林值 | Checkbox，跟表單一起儲存 | 明確屬於表單草稿 | 不因換成 switch 就改為即時存檔 |
| 顯示狀態 | StatusBadge／純文字 | 小範圍底色＋文字，不能點 | 不套 Button、不可冒充 disabled Button |
| 圖示動作 | IconButton | 圖示、可存取名稱、可見焦點；必要時附提示 | 不能只有 `×`／箭頭／眼睛而沒有動作名稱 |
| 展開／收合 | DisclosureButton／原生 details-summary | `aria-expanded`＋對應內容 | 不用 checkbox 的勾選外觀代替展開狀態 |
| 清單列／商品候選 | 可鍵盤操作的選擇列、既有 ComboBox option | 列選取、焦點、資料狀態分開 | 不把整列重新做成主動作按鈕，不攔截列內輸入框鍵盤事件 |

每一個主要工作區至多一個強調主動作；對話框打開後，以目前作用中的區域為準。查詢、匯出、返回、進入建單(例:「建立維修單」)通常為一般／文字動作。不得為了符合數量限制把不同業務動作合併。**淡色(2026-10-25 owner)**:主要動作靠位置、字重與藍字找到,不靠鮮藍實心;最終交易提交(結帳等)也先用同一個淡色主動作,特定掃碼 / 結帳要更強要列具名例外與樣張,不全面改回實心。

## 2. 尺寸、顏色與排版

只使用 `styles.css` 的共用變數。以下是目標規格；新增 token、元件後才逐頁套用，不直接把全站 `--control-height` 改小。

| 情境 | 目標高度／字級 | 使用條件 |
|---|---|---|
| 一般操作、表單 | `--control-height`：44px；`--font-body`：16px | 沿用現有尺寸 |
| 桌面查詢工具列 | 新增 `--control-height-compact`：40px；文字 16px | 只在精準指標裝置、明確的 compact 容器啟用；觸控恢復至少 44px |
| 掃碼、結帳 | `--control-height-lg`：48px；沿用既有工作台字級 | 不為了統一而縮小 |
| 分頁 | 桌面 36px；文字 16px | 觸控有效目標至少 44×44px；分頁多時用既有窄版下拉策略 |
| 表格列內輔助動作 | `--btn-h-sm`：32px；文字至少 14px | 精準指標限定；觸控有效範圍至少 44×44px，不可互相重疊 |
| 手機專用盤點／拍照 | 至少沿用目前大按鈕尺寸 | 操作位置、單手點擊和相機用途優先，不套桌面 compact |

- 按鈕、輸入框、下拉：6px 圓角；一般邊框 1px。狀態標籤可用 4px。分頁不加圓角按鈕外框。
- 沿用 `--btn-pad-x` 10px，文字自然撐寬；不為中文字數硬訂每顆固定寬度。
- 欄名、操作提示、停用原因至少 14px；12px 只給非操作必要註記。不要複製早期示意中的 13px 欄名到產品。
- 控制項顏色用共用層的 `--ctl-*`(一般:`--ctl-bg` 跟頁面同底、`--ctl-hover`、`--ctl-selected` 中性選取、`--ctl-border`)與 `--primary-*`(主要動作的淡藍字 / 框 / 底);`--accent` 只作當前位置(分頁底線、焦點框)。成功、警告、錯誤走現有語意 token。明暗主題都測；不新增頁面專屬藍、紫色或漸層;不用降低整個元件 opacity 或讓文字變淡來「淡化」。
- 不新增頁面級控制項顏色、圓角、padding、height 的覆寫，也不在 JSX inline style 定義這些外觀。寬度、排列需要變化時放在明確的容器版型；資料驅動的圖表、紙張尺寸另列例外。
- 同一列標籤與輸入框要對齊，控制項容器可換行。390px 和 200% 縮放時，動作不能被裁掉或移到頁面水平捲動以外。
- 不加入按鈕縮放／位移、閃動或長動畫；門市連點和掃碼時位置必須穩定。

## 3. 控制狀態契約

| 狀態 | 必須做到 |
|---|---|
| 預設／hover | 可辨識為可操作；hover 只作輕微底色變化，必要資訊不依賴 hover |
| selected／checked | 使用 `aria-selected`、`aria-current`、`aria-pressed` 或原生 checked，依角色選擇；不能只靠 class 改顏色 |
| focus-visible | 鍵盤焦點清楚可見，與 selected 分開；建議共用 2px outline＋2px offset，實際依明暗主題驗證 |
| disabled | 不能觸發；原生按鈕優先 `disabled`。需要讓人了解原因時，在旁邊或可讀提示寫原因，不能只靠灰字或 title |
| pending | 保留按鈕位置與原有寬度，顯示「儲存中／處理中」；同一寫入動作不可重送。查詢與交易的鎖定範圍由原流程決定 |
| error | 保留輸入和草稿，文字說明失敗，可重試；不能用開關新外觀表示已儲存但實際沒有成功 |
| success | 以確認成功的資料為準；即時存欄位沿用 `InlinePhase` 等既有狀態，不自行發明第三套 |
| armed | 沿用 ArmButton／useArm：4 秒有效、0.5 秒內連擊不算，確認綁定同一動作／同一對象，琥珀色及「再按一次…」文字 |

- 不為了移除藍框寫全域 `outline: none`。滑鼠點擊與鍵盤焦點可以不同；選中頁籤不可偽裝成 focus。
- 更換分頁／門市／廠商／紀錄仍走原草稿保護與記憶規則。未修改時不增加確認。
- 付款、單據完成、庫存、作廢、兩段確認與冪等性不屬於樣式元件的計算責任；元件只接收既有狀態與 callback。
- Switch 失敗不得只顯示 toast 後留下錯誤的 checked；受控狀態必須回復最後確認值，或明確顯示「未儲存」並保留重試。連點與回應先後顛倒都需驗收。

## 4. 鍵盤、名稱與語意

- Button 預設 `type="button"`；真的送表單才用 `submit`。若包裝元件改預設，須檢查原本仰賴 Enter submit 的表單。
- 換路由用連結；變更目前工作區才用分頁。Tabs 實作 `tablist/tab/tabpanel`、關聯 ID、左右鍵及 Home/End；焦點與選取策略由共用元件固定。禁止正數 tabindex。
- 單選列優先原生 radio，或完整 radiogroup；Checkbox／Switch 必須有綁定欄名及狀態，不能只靠附近文字。
- IconButton 必須有 action name，例如「移除第 2 筆商品」「關閉維修歷史」「清除會員搜尋」；`title` 只補充用途，不代替可存取名稱與觸控可讀性。
- ComboBox、PhoneModelPicker 保留現有伺服器搜尋、選項／新增分離和掃碼比對規則；另補欄位名稱、expanded／controls／active-descendant 等關聯，搜尋與清除可以用鍵盤完成。
- 表格列快捷鍵只在列本身或適合的非輸入區觸發；事件來自 input、select、textarea、button、a、contenteditable 或巢狀互動元件時，不攔截空白、方向鍵、Enter。
- MoreMenu／設定選單需支援開啟、Esc 關閉、選項鍵盤操作、關閉後回觸發點。採原生 disclosure 或完整 menu pattern 擇一，不只掛 ARIA role 而缺對應行為。
- 已有 `Field` 的欄名與錯誤關聯需保留；ComboBox 等被 Field 排除的複合元件，必須自行接收並傳遞欄位 ID／名稱，不能因此沒有 label。

## 5. 共用實作的邊界

現有 `Field`、`Checkbox`、`ComboBox`、`StoreSelect`、`ArmButton`、`useArm`、`AppliedFilters`、`PeriodQuick`、`ModuleBar`、`EyeToggle` 優先沿用。新共用層在 `frontend/src/components/ui/`(2026-10-25 B0 建立,從 `@/components/ui` 拿;展示頁 `/dev/controls` 只在開發模式):`Button`(variant default / primary / danger / text、size md / sm / lg、pending)、`IconButton`(`label` 必填;小標籤裡的 × 用 `className="compact"`,觸控範圍往外放大;危險用 `danger`、兩段確認用 `armed`)、`Tabs` + `TabPanel`(內容沒辦法包 TabPanel 時 `panels={false}`;分頁旁小字 `note`,要處理的 `noteTone="alert"` 紅字、建議看 `"warn"` 黃字)、`SegmentedControl`、`ChoiceGroup`(直接點的選項:單選 radiogroup / `multiple` 多選按下放開;付款方式、電信業者、門市、挑設備;選項可帶小字 `sub`,表單裡的二選一 / 三選一用 `layout="fill"` 等寬排、窄螢幕一個一行、緊湊商品表單小字收起)、`GroupCheckbox`(群組全選,一部分是半選)、`StatusBadge`、`ToolbarField` + `ControlBar`(查詢 / 工作對象工具列,桌面滑鼠 40px、觸控 44px);外觀只在 `styles.css` 的「共用控制項」那一段。即時存的格子用 `hooks/useCellSaves` + `components/CellMark`。抽屜 / 彈窗用 `Drawer` 或 `hooks/useDialogFocus`(名字、打開時游標進來、Tab 不跑到背後、關掉回原按鈕;關閉規則照各流程)。搜尋盒 `ComboBox` 外面沒包 Field 的給 `ariaLabel`;沒打字時按 Delete 清掉已選的。主檔表單用 `<dl>` 排的掛 `hooks/useDlLabels`(dt 欄名綁到 dd 唯一的輸入框)。以下是各元件的邊界:

1. `Button`／`IconButton`：variant、size、pending、disabled、type、名稱；不處理業務 API。
2. `Tabs`／`SegmentedControl`：將換工作區與改條件分開，不能讓一個 tab class 同時代表兩種語意。
3. `SelectField`／輸入控制樣式：和現有 Field 整合；不另造一個會載入全部資料的選擇器。
4. `SwitchField`／即時儲存狀態：共用受控狀態外觀；寫入、權限及成功判斷仍在原 hook。
5. `StatusBadge`：純顯示、不接 onClick；`.pill` 目前同時用於動作和狀態，遷移時分流。

舊 `.btn`／`.wb-btn` 暫作共用 CSS 的相容別名，不能再發展兩套。新元件名稱是計劃，尚未存在時不可直接 import；過渡期使用已存在且用途最接近的共用入口，登記到同一遷移清單，不複製另一套 CSS。

不批次刪除舊 class。每批先列引用、遷移、跑 `cssCoverage.test.mjs`、看實際樣張，再刪除確認沒有使用的規則。該測試只保護 class 存在，不保證視覺和互動正確。

## 6. 新增控制項的必經檢查

以下是每次新增／改動都要遵守的規則。自動守門 `frontend/src/lib/controlsPolicy.test.mjs` 跟著 `npm test` 跑(下一節);它擋得到的有限,其餘照這張清單自己檢查。**部署腳本還沒跑測試**(`ops/deploy-test.sh` / `deploy.sh` 只 build),不能說部署前一定攔得到。

- [ ] 能對應第 1 節的一個用途；已在元件展示頁找到同類範例。
- [ ] 使用共用元件／既有相容入口；沒有新增頁面專屬 Button、Tabs、Switch 或顏色／尺寸覆寫。
- [ ] default、selected、focus、disabled、pending、error 都有合理表現；不適用狀態標記原因。
- [ ] 有可存取名稱；鍵盤可完成，關閉／返回焦點合理。
- [ ] 明暗主題、1366／1024／768／390px、200% 縮放無裁切；觸控尺寸符合規範。
- [ ] 不改 API、權限、計算、草稿、確認、防重送、掃碼、列印與門市限制。
- [ ] 新例外有範圍、原因、負責人、驗收方法與取消時機；不得整頁、整目錄排除。
- [ ] 交付附元件名稱、受影響頁面、截圖／鍵盤驗證、測試結果；不可只寫「已統一」。

## 7. 自動守門的目標

- `controlsPolicy.test.mjs`(已建,規則在 `controlsPolicy.mjs`):TypeScript 語法樹掃 JSX —— 按鈕 / 可點容器的 inline 外觀、沒有名稱的圖示按鈕、舊分頁樣式(`tab-switcher` / `ia-tab` / `pf-tab` / `md-detail-tabs`)、用 `primary` 表示選中、不是按鈕卻可點又沒角色、複製開關;小型 CSS 解析掃 `styles.css` —— 共用層以外改控制項外觀、`:focus` 拿掉焦點框沒有 `:focus-visible` 替代。現有的記在 `controlsBaseline.json`(指紋 = 規則 + 檔案 + 標籤 + class + 字,不看行號),新的變紅;搬掉舊寫法後 `node src/lib/controlsPolicy.mjs --write-baseline`,diff 只能是刪除。
- `controls-style-policy`：檢查共用層外對外觀 token 的覆寫；token、例外與 print/mobile 邊界有明確名單。CSS 必須解析選擇器與宣告，避免把純排版誤判成另造按鈕。
- 以目前盤點建立基線；舊違規只能減少，新違規不能靠重產基線放行。識別用路徑＋控制用途／結構指紋，行號只是定位，不以移動行號洗掉違規。
- 單元／元件行為測試：Tabs 鍵盤、Switch 失敗回復、pending 防重送、IconButton 名稱、表單 submit、列內輸入不被攔截。
- 實際瀏覽器驗收：在展示頁與代表業務頁驗 computed style、焦點、點擊區域與流程；源碼掃描和截圖都不能單獨取代這層。
- 接到現有 `npm test`／型別檢查與建構；如果尚無 CI，就先作本機必跑檢查，再新增正式 CI 工作，不把「寫了一個測試檔」當作每次提交已強制執行。

## 8. 有界線的例外

- 手機盤點／拍照：可以保持大按鈕、相機／掃碼特殊互動；仍須共用色彩、名稱、焦點與 pending 狀態。
- 列印／收據／標籤：紙張內容按 mm 與列印需求；螢幕工具列遵守一般控制項規範。不得把螢幕按鈕印入收據。
- 九宮格解鎖圖形、拖拉排序、圖片預覽：保留專用互動，另驗鍵盤替代與名稱；不為了掃描全綠套錯 Button。
- 後端產生的公開報價 HTML：無法直接用 React 元件，使用相同語意／token 的獨立薄樣式並納入例外登記與樣張；不藉本計劃新增批發功能。
- 第三方內容不直接改內部控制項；先控制自己的入口、邊界及錯誤狀態。
