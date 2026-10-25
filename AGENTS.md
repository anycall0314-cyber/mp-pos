# MP POS · 通訊行進銷存

> Claude 與 Codex 都讀這一份(`CLAUDE.md` 只有一行 `@AGENTS.md`)。**上限 30KB,只放規則與索引**;細節一律在 `docs/規則/` 與 `docs/`。2026-10-24 以前那一份 25 萬 bytes 的原文在 `docs/development/archive/CLAUDE_md_完整_2026-10-24.md`。

## 一句話介紹

3C / 通訊行進銷存系統,取代舊系統「歐睿手機玩家 + 歐睿創意 POS」。後端 Django 5.1.4 + DRF + PostgreSQL 16(psycopg 3);前端 React 18 + Vite 5 + TypeScript 5 + TanStack Query + React Router;搜尋 pg_trgm GIN + 自製 `TrigramWordSimilarity` SearchFilter;條碼 jsbarcode(Code128 SVG)。MVP 單租戶,多租戶架構已就緒(`tenant_id` 全表帶,API 走 `for_tenant`)。

## 開發流程(改程式之前先讀)

照 `docs/development/README.md`:**想法 → 待辦 → 目前任務 → 施工 → 測試 → 複審 → 提交**。

- **只有 `docs/development/CURRENT_TASK.md` 裡的那一件才是現在要做的**;新想法記 `IDEAS.md`、技術債記 `BACKLOG.md`,不動程式、不插隊(例外:掉資料、資料嚴重錯誤、資安、現有功能壞掉、目前任務做不下去)。做好了在等 owner 的在 `WAITING.md`,一件一行。
- **動到哪個主題,先整份讀它的規則檔**(下面「主題索引」),不憑印象;商業邏輯不確定就問 owner,不猜。
- **複審(2026-10-24 起第三版,全文在 README「複審怎麼做」)**:只有改到「**怎麼算、怎麼寫**」才找外部複審 —— 金額 / 稅 / 成本 / 佣金的算法、庫存加減與序號狀態、現金收支入帳、付款結帳、權限判斷、資料庫變更、鎖與同時操作;Codex 首輪(`high`)、有 P0 / P1 才第二輪、最多兩輪、只擋 P0 / P1。**只顯示金額或庫存數字的畫面、報表版面、清單、查詢、匯入預覽、建檔流程、文字、排版 = 一般**:自己對 diff + 測試全過就交付。**紅隊只在「新模組第一次設計」跑一次**,日常任務不跑、實作後不跑。任何一輪超過 15 分鐘沒結論就停。
- **做完回報 5 行**:做了什麼 / 改了哪些主要檔 / 資料庫 / 測試 / 風險或沒做的。提交後寫 `COMPLETED.md`,一筆 10 行內。
- **一批一個新對話**(做完提交就開新的,不在同一個對話連做十幾批)。只改呈現的批次,驗收 = 測試(含守門)+ 型別檢查 + 改到那一頁一張截圖;完整的角色 × 狀態 × 主題矩陣整個專案收尾才跑一次。**超過 100KB 的資料檔(`inventory.json`、`controls.csv` 這類)不整份打開**,用 grep 查。
- 做完有新規則:改 `docs/規則/` 對應檔(沒有就新開一檔、索引加一行)。**介面 / 版面 / 文字的小修不寫進這裡、也不寫規則檔**;有新的版型規則才寫 `docs/ui-patterns.md`。

## 全站硬規則(每一件任務都適用)

1. **金額**:單據金額存整數元、四捨五入;算法只有 `apps/core/money.py` 與 `frontend/src/lib/money.ts` 各一份;顯示 `money()`、輸入 `<MoneyInput>`,不自己 `Math.round` / `toLocaleString`(`money.test.mjs` 會掃);**成本不收整數**(算到分)。報表未稅讀明細存好的 `untaxed_amount` / `tax_amount`,不再除 1.05;加總不用 `int()`。
2. **儲存即生效**:單據沒有過帳 / 未過帳,POST 成功就生效;取消用作廢(`is_void=True`)。
3. **先鎖再檢查、再改**(`apps/inventory/locking.py`):會動庫存或序號狀態的動作都在交易內 —— `lock_document()` 鎖單據自己並重讀 → `lock_stock_rows()` 照 **商品 → 序號 → SIM 卡 → 庫存餘額** 的順序鎖 → 鎖完才檢查在不在庫、夠不夠扣,才改;改數量一律 `locked_balance()`。
4. **庫存以序號為單位**:`ProductSerial` 一台一筆;新增設備一律 `inventory/identifiers.py::create_serial()`、用碼找設備 `find_serial_ids()`(測試掃全專案)。成本走全公司加權平均,中古機每隻獨立成本。
5. **只認自己公司**:所有序列化器掛 `TenantScopedRelatedFieldsMixin`(測試掃全部);外鍵篩選走 `TenantDjangoFilterBackend`;API 只回 JSON;有門市鎖的 viewset 覆寫 `perform_create` 要自己呼叫 `check_create_warehouse()`;service 再 `same_company()` 核對一次。
6. **權限擋在伺服器**:員工帳號權限只有 `apps/tenants/abilities.py` 一份,端點最前面 `abilities.require(...)`,畫面 `useCan()` 只收按鈕;只給管理員的欄位用 `ManagerOnlyFieldsMixin`;固定報表每加一張要列進 `abilities.ALSO_NEEDS`。
7. **同一份建單只成立一次**:新的建單端點把 `IdempotentCreateMixin` 放繼承清單最前面、填 `idempotency_scope`;工作台 4xx = 沒成立、斷線 / 5xx = 鎖住只能同一把鑰匙再送。
8. **清單怎麼拿**:伺服器 `apps/core/pagination.py::Paging`(預設 50、最多 500、要求少於 50 照給 50);畫面讀清單只走 `api/hooks.ts` 的 `listAll` / `firstPage` / `topPage` / `listSome`,**不可以拿第一頁當全部**(`listAll.test.mjs` 會掃)。
9. **匯出**:寫檔只有 `frontend/src/lib/csv.ts` + `components/downloadCsv.ts` 一份;超過上限不給檔(`exportIfComplete`);頁面不自己組 CSV(`reportExports.test.mjs` 會掃)。
10. **報表只有一套定義**:`apps/analytics/catalog.py`;新報表 = 加指標或角度,不寫新查詢;新事實表一定要有 `warehouse` 角度(有測試);鎖門市的帳號所有報表只算自己門市。
11. **導覽唯一設定 `frontend/src/nav.ts`**:新頁面要掛進去、入口名稱 4 個字、改名把舊名留 `aliases`(`nav.test.mjs` 會檢查);有分頁列的頁不再多一排大標題。
12. **公司備份逐張登記**(`apps/backup/registry.py`):新 model 沒登記 → 備份拒絕執行、測試紅;不備份卻指到公司資料的表登記 `CLEARED_ON_RESTORE`;單號下限、字軌高水位照 registry 的規則。
13. **會動庫存的新單據**要在 `apps/inventory/flows.py` 加一類、決定進銷存表算哪一欄、補測試。
14. **用過的商品不能改**「需追蹤序號 / 中古機 / 虛擬商品」(`catalog/usage.py`,擋在 `Product.save`);新增商品的每一個入口都要過 `identity/dedup.py::guard_new_product()`。
15. **全站用語**:客人叫「會員」、通路同業叫「來源」(沒有 = 直客)、進貨對象叫「廠商」、店叫「門市」;只改畫面上的字,資料與欄位名稱不動。
16. **閒置登出**只在 `frontend/src/lib/idleLogout.ts`(2 小時);別的元件不要在事件上用 `stopImmediatePropagation`(測試會擋)。
17. **舊 POS 的資料**:正式站在 owner 明講「可以導入資料了」之前不放任何舊資料;`import_legacy_*` / `bring_in_legacy_*` 只在本機與測試站跑,要對正式站跑任何一支都要先問。
18. **自動產生的代碼**(`sku` / `code` / `no`、類別 / 品牌 / 系列 / 品況的代碼)前端不顯示也不輸入;只有品號例外(商品詳情顯示)。
19. 不開 Django admin 給使用者(只當 dev fallback;後台不能新增 / 刪除設備);單一 React app 用角色控制(platform_admin / tenant_admin / tenant_user)。
20. 畫面規則寫在 `frontend/src/lib/*.ts`、同名 `.test.mjs` 測;後端每一條規則只有一份,放在規則檔寫的那個模組。

## 必懂的設計決策(完整 ADR 在 `docs/decisions.md`;原文在各規則檔)

- **客戶來源與會員**:Customer = 來源(通路 / 同業),Member = 人或公司;新銷貨先帶公司預設來源,選會員帶會員的來源,手選不回寫會員。→ `docs/規則/會員與來源.md`
- **廠商收貨與整單作廢**:本次實付運費收貨人明填(沒付填 0);貨到付款 `cash_paid` = 貨款 + 本次運費;商品售出或動用後不能整單作廢。→ `docs/規則/開單與結帳.md`
- **成本走全公司加權平均(不分倉)**:避免店員挑低成本機賣;中古機每隻獨立 `purchase_unit_cost`。→ `docs/規則/庫存與序號.md`
- **計入現金 / 計入毛利雙旗標**(`counts_cash` / `counts_margin`):收購二手「算現金流出但不汙染毛利」、手機回補「只算毛利不收錢」。→ `docs/規則/報表.md`
- **四種頁面版型**:錄入頁 / Master-Detail / 報表頁 / 工作台(掃一下加一行、不開彈窗;條碼槍連續做的單據一律工作台);進貨與銷貨拆清單頁 + 開單頁。→ `docs/ui-patterns.md`、`docs/規則/導覽與版型.md`
- **導覽**:側邊欄「今日總覽 + 8 個業務入口」,同入口其他頁在上方分頁(`ModuleBar`),低頻設定收進具名選單。→ `docs/規則/導覽與版型.md`

## 業務規則一句話(先知道有這一條;怎麼做看規則檔)

- **銷退只能整張退**;一張銷貨單同時只有一張有效銷退;有有效銷退的銷貨單不能作廢(先作廢銷退);退款方式要是原單的付款方式之一;收購單(總額為負)不能退。
- **序號狀態** in_stock / sold / void / returned / rma / in_transit / lost:銷退 → `returned`(已退、不能賣,在原銷貨單的門市),按「確認可賣」才回在庫;作廢的設備釋放它的碼;已退、換貨中都算進平均成本。
- **進貨成本**:`unit_landed_cost` 是未稅單價(含稅單 ÷ 1.05);`billed_qty` 空 = 等於數量、**0 是明講的 0**(整行贈品)、不能大於數量。
- **發票字軌一條 = 一間門市、一期**;取不到號結帳被擋;「下一張」只有新增時能填,之後只能跳號(不能跳到開過的號碼前面)。
- **門號**:新辦、攜碼要卡號,續約只要門號與方案;有方案的行一定有門號、數量 1;門號商品一定要有方案、且鎖在一家電信(伺服器都擋);合約從起算日算,綁約月數存檔當下從方案抄到明細,到期名單只讀明細存好的到期日。
- **逐台定價的商品**(中古機、已拆封)開單數量鎖 1、不併列;中古機每隻自己的成本與售價。中古機一律追蹤序號、不能虛擬(DB 限制);「中古機類別」會連動底下商品。
- **個人收購** = 虛擬商品「收購二手」的負數銷貨單(`untaxed`),來源一律直客、`member` 記賣機的人;營業日報列「收購現金支出」。
- **雜支、現金調整、代收話費**:儲存即生效、存好不能修改(PUT / PATCH 405)、不能刪除只能作廢(DELETE 405);代收話費不開發票、只印 80mm 收據。
- **維修**:只有 complete / reopen 會動庫存;已完工要先重開才能作廢;不能刪除;實付 > 0 要先選收款方式才能完成;維修毛利只有 `repairs/services.py::money_of` 一份。
- **調撥兩階段**:派發(序號 in_transit、來源扣)→ 目的門市確認(序號在目的門市在庫、目的加);`unit_cost_at_dispatch` 派發時快照。配件不允許負庫存。
- **庫存不足**只有 `inventory/views.py::alert_rows` 一份(今日總覽、庫存查詢、庫存警示三處同一套)。
- **商品搜尋**:含中文只搜品名 / 規格 / 類別;純英數才搜品號 / 條碼;純數字 6 碼以上才比 IMEI;刷條碼自動掛序號一律用 `/serials/?code=`(完全相同)。
- **鎖在門市的帳號**(tenant_user)只看、只動自己門市的單,所有報表只算自己門市;經手人預設登入者的業務員(`useDefaultHandledBy`)。
- **列印頁**(`/print/`、`/receipt`、`/labels`)與**手機頁**(`/m/photo` 拍照、`/m/count` 盤點)不套外框;手機頁不登入,憑證只存雜湊、3 分鐘沒掃失效、綁第一支掃到的手機。
- **正式站部署**要 owner 明確授權;資料庫變更上之前先備份。

## 主題索引(改到哪個主題,先整份讀那一檔;都在 `docs/規則/`)

| 規則檔 | 裡面有 |
|---|---|
| `金額與稅.md` | 課稅別、金額一律整數元、每行未稅 / 沖回成本、進貨成本 |
| `開單與結帳.md` | 建單只成立一次、結帳、預設值連動、上次成交價、來源 / 會員雙欄位、銷貨商品搜尋與可選清單、逐台定價一列一台、手機回補、銷退單、一般進貨擋中古機、進貨付款方式、建好品號 → 進貨、進貨時當場建、廠商收貨與整單作廢 |
| `門號與電信.md` | 門號合約日期、合約到期名單與提醒、兩個佣金、門號商品鎖電信商、方案只有管理員能改 |
| `發票.md` | 發票自動取號(字軌 / 跳號 / 換期)、發票機 WP-103 測試頁、發票明細與彙總 |
| `庫存與序號.md` | 庫存不足、序號生命週期、序號退回後續、設備兩個碼(IMEI / SN)、序號防呆、配件庫存與不足擋下、調撥與整張調撥、先鎖再檢查、每日快照與對帳、庫存三張、庫存查詢搜尋(語彙表)、廠商換貨、中古機履歷 |
| `盤點.md` | 盤點作業(手機走動盤點、第一次盤點入庫) |
| `中古機.md` | 中古機、逐台記機況、商品品況、中古機類別連動、個人收購、廠商收購(Excel 匯入) |
| `商品建檔.md` | 預設與用詞、先找一次、防重複、表單順序與分頁、從型號庫選、建議售價、匯入表格與批次修改、用過的不能改屬性、記住條碼、款式碼、類別代碼、停用商品、拖拉排序、商品照片、供應商商品對照 |
| `機型與比對.md` | 機型主檔、相容關係、配件 → 機型比對、哪些類別掛機型、AI 只出建議、商品叫法比對、別名、IMEI 搜尋安全閥、搜尋權重 |
| `平台型號庫.md` | M1 型號庫、展開品號、類別 → 品牌 → 型號、每天自動新增新機、配件跨型號共用、新 iPad 算代數 |
| `會員與來源.md` | 客戶識別、會員主檔、舊系統消費紀錄、全站用語、客戶來源與會員 |
| `維修.md` | 手機解鎖、返修、收據列印、快速收件、維修單與庫存、維修毛利與月報、租戶設定 |
| `現金與日報.md` | 店頭雜支、代收話費、維修收款與營業日報、現金調整方向、打烊實點 |
| `帳號與權限.md` | 登入 / RBAC、員工帳號權限、密碼與收回、單一位置登入、閒置登出、倉別鎖定、經手人預設、平台後台、門市資訊、只認自己公司 |
| `廠商叫貨.md` | 多廠商與平台名單、膜總裁 B2B 叫貨與到貨入庫、品名連連看、半自動廠商、只給指定公司、kcimos 價目與自動送單 |
| `批發.md` | 經銷商之間互相買賣(賣家 / 買家 / 對外金鑰) |
| `標籤與列印.md` | 商品標籤(Argox 45 × 25 兩聯)、列印頁不渲染導覽 |
| `報表.md` | 報表只有一套定義、匯出、清單怎麼拿、銷貨日報與進貨明細、商品業務員成本、今日總覽、計入現金 / 毛利旗標 |
| `備份與還原.md` | 公司備份、復原憑證、還原、公司維護鎖、單號下限 |
| `舊系統資料.md` | 舊資料匯入指令、舊系統資料(歐睿)帶進來的範圍 |
| `導覽與版型.md` | 導覽結構、四種頁面版型、唯一前端、單一 React app |
| `程式碼定位.md` | 完整的目錄說明(每個 app、每個 pages / components 資料夾放什麼) |

## 程式碼定位(精簡版;完整在 `docs/規則/程式碼定位.md`)

後端 `backend/apps/`:`core`(租戶基底、金額、只給管理員的欄位、業務員成本、分頁、冪等)· `tenants`(公司、帳號、權限 abilities、登入、系統設定主檔、平台後台)· `catalog`(商品、類別、品況、機型、型號庫、usage、shop_terms)· `identity`(別名、叫法比對、防重複、待確認入庫)· `inventory`(門市、序號、異動、標籤、flows / reports、盤點、廠商換貨)· `parties`(廠商、來源、會員、業務員、電信、方案、SIM)· `purchasing` · `sales`(銷貨、銷退、合約、佣金、日報、WP-103)· `transfers` · `cash`(雜支、現金調整、代收話費、營業日報)· `repairs` · `backup` · `legacy` · `ledger`(快照與對帳)· `analytics`(報表語意層)· `vendor_orders`(廠商叫貨、kcimos)· `trade`(批發)· `photos`。

前端 `frontend/src/`:`api/`(client、hooks、search、types)· `components/`(ComboBox、Drawer、MoneyInput、shell/、workbench/、labels/、photos/)· `pages/<模組>/` · `lib/`(畫面規則 + 同名測試)· `auth/` · `hooks/` · `nav.ts` · `App.tsx` · `styles.css`(只剩 @import;規則在 `styles/01-base` ~ `26-*.css`,順序 = 層疊順序;按鈕 / 分頁 / 單選列在 `03-controls.css`、日間顏色在 `16-light-theme.css`、頁面自己的在那一頁的檔。字級、尺寸、顏色都用變數;全站按鈕只有 `btn` / `wb-btn` 一套,主要按鈕是淡色(藍字、淡藍細框、淡底;2026-10-25),控制項顏色用 `--ctl-*` / `--primary-*`)。

## 慣例

- 後端 service:每個業務動作(commit / void)是 `apps/<app>/services.py` 的純函式,viewset 只管 HTTP + transaction。
- 前端 hook:API 呼叫包成 `useXxx` / `useSaveXxx` / `useVoidXxx`(`api/hooks.ts`);萬筆級搜尋用 `ComboBox` + `api/search.ts`,不載整張表。
- 草稿:`/sales/new`、`/purchases/new` 自動存 sessionStorage(含鑰匙與付款方式),儲存成功後清空。
- migration 涉及資料改動在 migration 內 `RunPython` 一併處理;改資料表之前確認與舊資料相容。
- 不可預測的字串(IMEI、卡號)存原值,前端顯示末 N 碼。
- 新 model → 登記備份 registry;新頁面 → 掛 `nav.ts`;新序列化器 → 掛租戶欄位 mixin;新會動庫存的單據 → `flows.py`。

## 使用者偏好

- 繁體中文回應、UI 一律繁中;**禁用 emoji**。
- 先規劃再實作(大改動先列範圍 / 取捨再動工);「跟 XXX 一樣的模式」照 `docs/ui-patterns.md` 與既有頁面。
- 新增 / 修改按鈕、分頁、篩選、開關先讀 `docs/ui-controls.md`:依用途用共用元件與 token,不再另造頁面樣式;共用元件在 `@/components/ui`(Button / IconButton / Tabs / SegmentedControl / StatusBadge / ToolbarField);`controlsPolicy.test.mjs` 擋新的違規(現有的在 `controlsBaseline.json`,只能減少),但部署腳本還沒跑測試。
- owner 非工程師:不直接寫 git,要求提交才動;提交就一起推 GitHub;測試站測完審完可以直接部署,**正式站要 owner 明確授權**;不直接改 `.env` 之類底層設定,問過再改。
- 回報要短。文件寫規則、不寫日記:原話、日期、複審第幾輪抓到什麼放 `docs/decisions.md`。

## 何時更新這一份

1. 加新模組 → 「程式碼定位」加一行,`docs/規則/程式碼定位.md` 補完整說明。
2. 業務規則改變 → 改 `docs/規則/` 對應檔;只有「每一件任務都適用」的才加進「全站硬規則」。
3. 設計決策被推翻或新增 → `docs/decisions.md` 加 ADR,這裡一行。
4. **這一份超過 30KB 就先搬東西出去再加**(Codex 預設只讀 AGENTS.md 前 32KB)。
