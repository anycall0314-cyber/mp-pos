# MP POS · 通訊行進銷存

> Codex 每次對話自動讀這個檔案。維護原則:**精簡、最新、有用**。深入內容散到 `docs/`。

## 一句話介紹

3C / 通訊行進銷存系統,後端 Django + DRF + PostgreSQL,前端 React + Vite + TypeScript。
取代舊系統「歐睿手機玩家 + 歐睿創意 POS」。MVP 單租戶,多租戶架構已就緒(`tenant_id` 全表帶,API 走 `for_tenant`)。

## 開發流程(改程式之前先讀)

2026-10-06 起照 `docs/development/README.md`:**想法 → 待辦 → 目前任務 → 施工 → 測試 → 複審 → 提交**。

- **只有 `docs/development/CURRENT_TASK.md` 裡的那一件才是現在要做的**;同一時間只有一件,它寫了可以改 / 不可以改的範圍。
- 新想法、順便想到的改進 → 記進 `docs/development/IDEAS.md`,**不動程式**;`BACKLOG.md` 裡的也不代表可以做。
- 做到一半冒出新需求不插隊(例外:會掉資料、資料嚴重錯誤、資安、現有功能壞掉、目前任務做不下去)。
- 發現技術債先記在 `BACKLOG.md`,不順手改;不做不相干的重構。商業邏輯不確定就問 owner,不猜。
- 做完回報:完成內容 / 改了哪些檔 / 資料庫 / 測試 / 風險 / 沒動的地方 / 建議下一件;提交後寫進 `COMPLETED.md`。

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
- **四種頁面版型**:錄入頁(維修單、銷退單)、Master-Detail(主檔)、報表頁、**工作台**(調撥、庫存查詢、進貨、銷貨;2026-10-05 起,owner 習慣的「掃一下加一行、不開彈出視窗」)。拿條碼槍連續做的單據一律走工作台。進貨與銷貨明細多,拆成**清單頁 + 開單頁**(`/sales/new`、`/purchases/new`:**商品明細優先** —— 交易對象與倉庫常駐、其餘單據資訊收進右邊的抽屜、掃碼框在明細上方、總額與唯一的主要按鈕固定在最下面、明細吃掉剩下的高度;字不縮、列高約 48px,1370×656 看得到 8 列)。細節見 `docs/ui-patterns.md`
- **唯一前端**:不開 Django admin 給使用者用,Django admin 只當 dev fallback
- **單一 React app + 角色控制**:Platform Admin / Tenant Admin / Tenant User 共用 SPA(MVP 還沒實作登入)
- **導覽結構**(2026-10-06 改版,唯一的一份設定在 `frontend/src/nav.ts`):側邊欄只有「今日總覽 + 8 個業務入口」,系統設定固定在最下面;**入口名稱一律 4 個字**(owner 要求字數一致)。點入口直接進它的預設頁;同一個入口的其他頁在頁面上方的分頁切換(`components/shell/ModuleBar`),低頻的設定頁收在分頁列右邊的具名選單(商品設定 / 作業設定)。路由一條都沒改,舊網址照用;改名的頁面把舊名字留在 `aliases`,側邊欄上面的功能搜尋(Ctrl / Cmd + K)打舊名字找得到。「目前這一頁」取網址對得上且最長的那一頁(`matchNav`),同一層只會有一個。新增頁面要掛進 `nav.ts`(`nav.test.mjs` 會檢查改版前的 32 個入口都還在、名稱字數、管理員頁面)。開單頁(`isWorkspacePath`:`/sales/new`、`/purchases/new`、`/sales/returns/new`)不放頁面上方那一排分頁,頁首有「返回列表」

## 業務規則速查

| 主題 | 重點 |
|---|---|
| 課稅別 | 應稅內含 / 應稅外加 / 免稅 / 零稅;含稅金額 ÷ 1.05 = 未稅 |
| 金額一律整數元 | 2026-10-06 起,**單據上的金額(明細金額、未稅小計、稅額、含稅總額)存檔就是整數元、四捨五入**(剛好一半進位,負數往離 0 遠的那一邊)。規則只有一份:後端 `apps/core/money.py`(`round_money` / `money_int` / `money_text`),前端 `frontend/src/lib/money.ts`(`money()` 顯示、`intStr()` 輸入框與送出、`roundInt()`、`splitTax()` 試算,跟後端 `_calc_tax` 同一套算法)。含稅:未稅 = 加總 ÷ 1.05 四捨五入,稅額 = 總額 − 未稅;外加:稅額 = 加總 × 5% 四捨五入(以前算到分,110 外加的總額是 115.50,畫面只收整數,這種單存不進去)。**成本不收整數**(落地成本、加權平均、`cost_at_post` 照舊算到分,只在畫面顯示成整數;95.24 的線材收成 95 進 1000 條會差 240 元)。**以前存的單不改寫**:每日對帳用 `matches_tax_rule()`,新舊兩種算法符合一種就算一致;`split_tax_by_line` 也認得舊單。畫面不要自己 `Math.round` / `Number(x).toLocaleString()`(`money.test.mjs` 會掃全專案),金額輸入框用 `components/MoneyInput`(小數點打不進去、貼上小數會四捨五入、沒有上下箭頭);報表加總不要用 `int()`(無條件捨去)。營業日報:個人收購付出去的現金(現金付款是負的銷貨單)列在「收購現金支出」,當天的結餘 = 隔天的期初。賣出速度(件 / 日)、比率不是金額,照舊有小數 |
| 同一份建單只成立一次 | 進貨單、銷貨單的建單端點認得 `Idempotency-Key`(`apps/core/idempotency.py` 的 `IdempotentCreateMixin`,紀錄在 `core.IdempotencyKey`):畫面每開一張新單自己產生一把鑰匙,送出時帶著;連線中斷不知道有沒有成立時拿同一把再送 —— 已經成立就回那一張(HTTP 200、`Idempotent-Replay: true`),不會開第二張、不會收兩次錢。第一次被擋(4xx)鑰匙不會留下,改一改用同一把再送是一次新的建單。鑰匙記的是單號(還原備份後編號會換、單號不會),只留 7 天,不進公司備份。沒帶鑰匙的請求跟以前一樣。工作台的送出規則:4xx = 沒成立;斷線 / 5xx = 不知道 → 整張單鎖住,只能「再送一次」(同一把鑰匙)或「取消」。**鑰匙、「送出去了還不知道結果」、付款方式都跟著草稿存**(sessionStorage):重新整理或切到別頁再回來還是同一把、而且鎖著;放棄之後不給復原(放回來再送會用新鑰匙)。同一把鑰匙送回來的是已作廢的單 → 講出來、明細留著、換新鑰匙。新的建單端點要防重複就把 mixin 放在繼承清單最前面、填 `idempotency_scope`(調撥與個人收購還沒接) |
| 門號合約日期 | 銷貨明細(`SalesOrderItem`)記門號合約:**新辦、攜碼才要卡號;續約只要門號與方案**;有方案的那一行一定要有門號、數量只能是 1;門號商品(虛擬、可以填門號)一定要有方案 —— 這幾條伺服器都擋,不只畫面擋。**合約一律從「起算日」算**(存在 `activation_date`):新辦 = **單據日期,由伺服器存檔時決定、不看送來的值**;攜碼 = 人填的**合約生效日**;續約 = **續約日**(預設開單當天:遠傳、台哥大當天續約;**中華電信等手機到貨才續約,先入帳、續約日往後** —— 開單時可以往後填,**存了之後在銷貨單清單那一行按「改日期」也能改**,`POST /sales-orders/{id}/contract-dates/`,只動日期與合約到期日,不動金額 / 庫存 / 佣金;作廢的單、新辦不能改)。**綁約月數存檔當下從方案抄到明細上**(`contract_months`);`contract_end`(合約到期日)= 起算日 + 那個月數(`apps/core/dates.py` 的 `add_months`,前端試算 `lib/dates.ts` 同一套;沒有起算日就是空的、不猜;唯讀、有索引)。**方案主檔之後改月數,已經開出去的合約不跟著變,事後改日期也是用當初抄下來的月數重算**。作廢時清掉 `contract_end`。之後的「合約快到期」統計與提醒直接查這一欄。`prev_contract_end`(原合約到期日)是續約選填的記錄,不拿來算新約(不是續約填了會被擋)。畫面上攜碼沒填生效日不能結帳(伺服器不強制:舊單沒有)。migration 0017 把以前的門號明細補上月數,沒作廢、有起算日的補上到期日 |
| 門號合約到期(名單與提醒) | 規則只有 `apps/sales/contracts.py` 一份,名單、今日總覽的筆數、自由組合報表都從 `contracts(tenant)` 出發,**只讀**銷貨明細上存好的合約到期日,不動銷貨單。**一筆合約 = 一行有方案、有到期日的銷貨明細**;作廢的單、**被退掉的那一行**不算(現在一律整張退;舊資料只退其中幾行的,只有被退的那幾行不算 —— 看 `SalesReturnItem.original_item`,不是看整張單有沒有銷退)。**同一個門號(去掉符號後相同,`Digits("msisdn")`,有函式索引)在另一張單上有起算日更晚的合約 = 這一筆「已續約」**,不用人標;同一張單上重複的門號不互相算續約;**起算日同一天的另一張單也不算**(打重複沒作廢、或同一個門號兩份不同月數的合約:兩筆都留著提醒,不拿「誰比較後面建的」當續約);去掉符號後不到 6 位數字的門號(舊資料的「-」「無」)不拿來比(不然會全部互相蓋成已續約、名單變空的)。續約 / 攜碼沒填起算日的單沒有到期日,不算合約,也不會把舊的那一筆蓋成已續約(寧可多提醒)。沒續的看聯絡紀錄 `ContractFollowUp`(一筆合約最多一筆:狀態 已聯絡 / 不續約 / **空的** + 一句備註 + 誰記的;進公司備份):**狀態空的 = 只記了備註(打了沒人接),這一筆仍然是還沒處理**;狀態與備註都空的 = 紀錄拿掉。**待聯絡 = 還沒處理,而且到期日 ≤ 今天 + `Tenant.contract_remind_months`**(預設 3,系統設定可改 1~24;已經過期沒續的一直留著)。畫面「電信作業 → 合約到期」(`/telecom/expiries`,`pages/telecom/ContractsPage.tsx`):待聯絡 / 已聯絡 / 不續約 / 已續約四個分頁,每一筆有三顆位置固定的按鈕(未聯絡 / 已聯絡 / 不續約,現在的狀況那一顆亮著不能按 —— 標完同一個位置還是同一顆,連點不會按到旁邊)、可以存備註,標錯按「未聯絡」改回來(備註留著);今日總覽「需要注意」顯示幾筆待聯絡。**這一頁最怕標錯人**:畫面上的名單不是現在要的那一份時(剛換分頁 / 篩選 / 翻頁、搜尋的字還沒查)整份鎖住;**標完的那一列留在原地**(變淡、顯示現在的狀況),不抽掉讓下面的往上跳,展開的那一列標完也不自己收起來;換分頁 / 篩選 / 翻頁或再點一次同一個分頁(會重抓)才放掉,而且留著的那一份只屬於那一次名單(`epoch`),條件換過再換回來不會被搬出來蓋住新抓的;**名單不留快取、不在背後自己重抓**(`useContracts` 的 `gcTime: 0`):換回看過的條件一定重新抓,人正要按的時候列不會自己跳;每一列打到一半的備註各自留著(收起來、看別列都還在,按那一列的按鈕會一起存;送出之後又補打的字不會被清掉)。端點 `GET /telecom-contracts/`(門市、電信業者是範圍,分頁上的數字跟著走;搜尋不影響數字;`?months=` / `?until=` 看多遠;**翻頁用游標不用頁碼**:`?after=到期日,編號`(接在這一列後面)/ `?before=`(排在這一列前面),回 `has_more` / `has_prev`;名單上的人被標掉(自己、別的店員同時)就離開分頁、後面的往前遞補,用頁碼或第幾筆翻下一頁會跳過遞補上來的人,接在畫面最後一列後面拿就不會;翻過去是空的回最前面。畫面那一側的規則(哪一列排在後面、還有沒有下一頁、留在原地的那一份、備註草稿)在 `frontend/src/lib/contractList.ts`,有測試)、`POST /telecom-contracts/{明細編號}/follow-up/`(回這一筆現在的樣子)。鎖倉店員只看得到、只標得到自己門市賣出去的(`report_warehouse_id`)。統計在自由組合:指標「到期門號數」(事實表「門號合約」,日期 = 合約到期日;含已續約的,要分開看用「合約處理狀況」這個角度),角度有電信業者 / 方案種類 / 合約處理狀況 / 門市 / 業務員;期間多了「未來 3 個月 / 未來 12 個月」。只管用這套系統賣出去的門號(上線前的舊客戶沒有資料);不推通知 |
| 商品照片(圖片備註) | `apps/photos/`。**照片先放在「這一次編輯」上(`PhotoDraft` 照片作業 + `PhotoUpload` 暫存),商品存檔的同一個交易才掛到商品(`ProductPhoto`)**:新增商品還沒有品號就能先加;取消、存檔失敗都不動商品原本的照片。畫面把定下來的清單隨商品一起送(`photos: {draft, seen, items}`,順序 = 顯示順序,商品原本有、清單沒列的 = 移除;沒帶 `photos` = 照片不動;**`seen` = 開表單時看到哪幾張,跟商品現在的照片不一樣就整筆退回**:別人剛加的那一張這張表單沒看過,不能被當成移除),`apply_to_product()` 套用;同一份作業重送(品名相同)回同一個商品、不建第二個品號;品名不同就是另一張表單拿到同一份作業,擋下。**新增商品開的作業(沒綁商品)只能用在這一次新建的商品上,編輯既有商品只收「為這個商品開的」作業**(`apply_to_product(created=…)`):新增時加的照片不能被拿去蓋掉別的商品的照片。一個商品最多 10 張、單檔 20MB、6400 萬畫素;存 JPEG 大圖 + 縮圖(轉正、去 EXIF;HEIC 靠 `pillow-heif`),上傳前瀏覽器先縮(`lib/imageShrink.ts`)。**手機拍照不用登入**:電腦按「用手機拍照片」產生 QR Code(憑證只存雜湊、3 分鐘沒掃失效、放在網址 `#` 後面),手機開 `/m/photo`;憑證只能「對這一份作業傳照片」,綁第一支掃到的手機(別支連不進來),閒置 10 分鐘 / 最長 60 分鐘結束;電腦存檔、取消、重新產生之後舊手機傳不進來,遲到的照片不會掛到下一筆商品。手機的每一個動作先驗憑證、鎖住作業之後**再核對一次還是不是同一次配對**(`pair_of` / `_same_pair` / `still_paired`):舊手機還在路上的請求不能寫進來、不能結束新手機的配對。每張照片有自己的識別:重試不會變兩張,取消過的不會因為上傳晚到又出現;**處理圖片的那一兩秒整段握著作業的鎖**(`add_upload`:登記 → 處理 → 落檔同一個交易),同一張的另一次傳、取消、重新配對、存檔都得等它做完,不會交錯(同一份作業一次只處理一張);手機只能動手機自己傳的那幾張;一份作業最多記 80 筆(含取消、失敗的)。整份取消 / 存好之後沒放進清單的暫存檔當下就刪。電腦開始儲存先 `freeze`(不收新照片,手機顯示「電腦正在儲存」),失敗 `unfreeze`。照片檔走 `/api/v1/photo-file/<簽章>/`(`<img>` 帶不了登入憑證,網址帶簽章、7 天有效);**其餘照片端點一律 `never_cache`** —— 手機問狀態的網址每次配對都一樣,瀏覽器預設會把 410 永久記住,不擋的話看過一次「已結束」之後每次新配對都拿到舊的回應(前端 `phoneCall` 也帶 `cache: "no-store"`)。舊作業與暫存檔不另外排程清:有人開新的照片作業時順手 `cleanup()`(指令 `cleanup_photo_drafts` 可手動跑)。`ProductPhoto` 進公司備份(檔案一起),暫存的兩張表不進 —— 但它們指到商品,**還原時要先清掉**(`registry.CLEARED_ON_RESTORE`;不清的話刪商品會被外鍵擋住、還原做不完。之後新的「不備份卻指到公司資料」的表都要登記在那裡,`check_registry()` 會擋)。商品清單 / 搜尋 / 庫存查詢帶 `photo_count`、`photo_thumb`(主圖縮圖)。**點品名看照片與規格**(`components/photos/`:`ProductPhotoPanel`、`PhotoName`、`usePhotoPeek`):商品管理(清單小縮圖 + 詳情照片列)、庫存查詢、進貨 / 銷貨的明細品名都能點,只是看、不會加進單據;搜尋下拉有照片的那一筆多一顆「照片 N」(`ScanBox` 的 `peek` / `onPeek`),看完按「使用此商品」才加入、按「返回繼續找」回到原本的搜尋。開單頁的縮圖 32px、不撐高明細列。改用既有商品(防重複的「就是這個」)時,這次加的照片丟掉、不會自動掛過去。新增商品的草稿:照片那一份(哪一份作業、順序、說明、主圖)放在表單草稿的 `photo_draft` 裡、跟欄位同一筆一起存(分開記會湊出「這一頁的欄位 + 那一頁的照片」)。畫面那一側的狀態在 `usePhotoDraft`:表單元件一直掛著(關掉只是藏起來),所以每一次編輯有自己的編號(`gen`),上一次編輯晚到的回應一律丟掉;商品原本的照片沒載入成功就不能加、不能存照片(不然原本的會被當成移除)。看照片的面板開著時背後停用、游標在面板本身(條碼槍刷進來不會多加一行)。規格的 D 階段(依分類瀏覽照片、新增前相似候選帶照片)還沒做 |
| 進貨成本 | `unit_landed_cost` = 未稅單價(含稅單會自動除 1.05);贈品由 `billed_qty < qty` 表示,平均成本被稀釋。`billed_qty` 沒填(null)= 等於進貨數量;**0 是明講的 0**(整行贈品,金額與成本都是 0;以前 0 被當成沒填、改回全數計價);不能大於進貨數量 |
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
| 廠商收購中古 | 「中古收購」頁的「廠商收購」tab,內嵌 `PurchaseWorkbenchPage mode="secondhand-vendor"`(進貨的工作台);走一般進貨單流程但商品搜尋限定 `is_secondhand=true`;每一台在那一行底下多成色 / 成本 / 售價 / 電池 / 備註 +「套到下面」;存完不離頁 |
| 一般進貨單擋下中古機 | `PurchaseWorkbenchPage` 預設 `mode="regular"`,掃碼框 / 勾選商品 / 批次貼上都帶 `is_secondhand=false`;新增進貨單時挑不到中古品(刷到中古機的品號會講「請到中古收購進」,不會當成序號放進格子)。檢視 / 作廢既有中古進貨單走 `/purchases/:id`(進貨單清單頁展開那一張) |
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
| 商品標籤(條碼列印機) | Argox OS-2130D(熱感 203 dpi、一公釐 8 個點、最寬 72 mm),標籤紙 **50 × 30 mm**;**用瀏覽器列印**(每台電腦裝原廠驅動、設一次紙張),不直接對印表機下指令。安裝與設定見 `docs/條碼列印機_安裝與設定.md`。**要印什麼的規則只有後端 `apps/inventory/labels.py` 一份**(唯讀端點 `GET /labels/?po=` / `?serials=1,2,3` / `?product=&copies=`,三種擇一;只看得到自己公司的;門市不另外鎖,跟序號清單一樣):條碼內容 = 有序號印主碼(有 IMEI 是 IMEI,沒有才是 SN)→ 沒有序號印原廠條碼 → 都沒有印品號;售價 = 逐台定價的商品(中古機、已拆封)印那一台自己的售價,沒有才印建議售價,沒有價錢(0)不印;成色只有逐台記機況的才印;進貨單號與日期 = 那一台當初進貨的單,個人收購進來的印收購那一張單,配件補印不印(不猜);作廢的進貨單、作廢的設備不能印;進貨單的配件一行一筆、張數 = 進貨數量(上限 500),序號商品每一台一張(一張單超過 300 台不給印,請分批);**那一行是不是逐台印,看的是這一行底下有沒有設備,不是商品現在的「需追蹤序號」**(進貨之後改過設定,舊單的每一台還是各印各的碼);虛擬商品不印;個別售價是 0 或負的 = 沒填(跟銷貨開單帶價同一條規則,`> 0` 才用);序號頭尾的空白不算碼的一部分。回應另外帶 `notes`(要講給人知道的事:哪一行少印了幾台、哪一行的張數被壓到上限),列印頁會顯示。編號 / 張數只收一般的數字(全形、太長的回 400)。**畫面只負責排版與畫條碼**(`pages/labels/LabelPrintPage.tsx`、`components/labels/LabelTile.tsx`):**條碼的每一條線是印表機的整數個點**(`lib/labels.ts` 的 `layoutBars`:一個單位 3 點,放不下用 2 點,兩邊各留 10 個單位空白;編碼用 jsbarcode、畫自己畫)——把條碼圖拉寬貼滿標籤的話線寬不是整數點,熱感印出來是糊的、槍刷不到;2 點還放不下:原廠條碼改印品號的條碼(`printableCode`),序號不能換、只印文字(那個碼印大一點、可以折行),列印頁上面會講。**條碼跟下面的字一定是同一個字串**:頭尾空白在 `printableCode` 去一次、兩邊都用它;碼中間連續的空白照原樣印(樣式用 `white-space: pre`,預設會把兩個空白併成一個);`code128Bits` 給什麼編什麼、不偷偷修,有換行 / Tab / 全形字就不編。標籤尺寸只寫在 `lib/labels.ts` 的 `LABEL` 與 `.label-*` 樣式(還不是每家公司的設定);字用 mm、純黑(熱感沒有灰)。紙張尺寸用**有名字的頁面**(`@page label` + `page: label`):全站樣式裡別的列印頁各有沒有名字的 `@page`,會互相蓋掉(最後一條是 A4)。每一張的高度是 29.5 mm(比紙矮一點:驅動回報的可印高度常比紙小,剛好 30 mm 會每張多吐一張空白);換頁寫在「第二張起每一張之前」。入口:進貨單清單「列印標籤」(`/purchases/:id/print/labels`)、庫存查詢展開列的「標籤」(某一台)與「列印標籤」(配件、打張數)、個人收購存完的「列印標籤」、系統設定「列印測試標籤」(`/labels/print?test=1`:一張四邊有框線看有沒有被切、一張真的樣子);列印頁上面可以改配件的張數(0 = 不印;一筆最多 500、整批超過 1000 張不畫也不印);這一頁自己捲(`.label-page`,外層版面不能捲),上面那一排第一行固定是張數 / 列印 / 關閉,配件再多行也看得到;載入之後內容固定,不在背後重抓。**自己跳列印視窗只在資料第一次到的那一刻決定一次**(`shouldAutoPrint`:100 張以內、沒有提醒、沒有 `auto=0`);那一刻沒跳,之後提醒消失、張數改小都不會突然自己印;人自己按「列印」會取消還在等的那一次(不會印兩份)。被擋下來的請求(4xx)馬上顯示原因與「重試 / 關閉」,不重試;還沒拿到資料時顯示載入中或網路沒回應,不會說成「沒有東西要印」。開列印頁一律走 `components/labels/openLabelPrint` / `openPurchaseLabels`(新分頁被瀏覽器擋掉會講)。配件補印不管按 Enter 還是按「列印」,印的都是框裡現在看到的數字(範圍外不送);個人收購的按鈕寫著是哪一台(序末 5 碼)。**實機(印出來的位置、條碼刷不刷得到)只能由 owner 在接印表機的那台電腦驗** |
| 銷貨商品搜尋 | `searchProductsForSales` 支援 品名 / 品號 / 條碼 / IMEI 任一;打 IMEI 命中時 matched_serial 也預掛該行,且該倉只有 1 隻在庫時自動掛唯一序號(中古機同步帶 custom_unit_price)|
| 銷貨可選清單 | `?sales_pickable=true` 過濾:庫存 > 0 OR `is_virtual=True`(虛擬商品永遠可選,實體 0 庫存擋下)|
| IMEI 搜尋安全閥 | ProductViewSet.`get_search_fields` 動態化:**只有純數字 6 碼以上才把 `serials__serial_no` 加進 search_fields**,避免「18 pro 256」誤命中含 18 的 IMEI |
| 搜尋權重(中文 vs 英數)| `get_search_fields` 偵測查詢字串是否含中日韓漢字(U+4E00–U+9FFF):**含中文 → 只搜描述欄 `name/spec/category__name`**(不碰品號/條碼/IMEI,避免「中古 11」被 SKU `AA-000011` 誤帶出);**純英數 → 搜完整代碼欄位**(sku/name/spec/barcode/category),純數字 6 碼以上才再加 IMEI |
| 商品叫法比對 | `apps/identity/product_match.py`:品名與查詢走同一支 `parse_features()`,拆成型號 / 顏色 / 其他詞再比(`exact` / `covers` / `related`)。進貨搜尋、`?search=`、待確認入庫、新增查重**共用**。特徵比對只出候選;`existing` 只來自條碼 / 廠商料號 / 已確認別名 / 品號。`GET /products/resolve/?q=` 回候選 + 符合原因 + 差異,零庫存與停用都列 |
| 別名:已確認 vs 關鍵字 | `ProductAlias.verified=True` 才能自動對應且同範圍唯一(通用別名另有 `uniq_alias_generic`);`False` 是搜尋關鍵字,可多筆。籠統 / 只是品名一部分 / 同時符合多款的叫法自動降為關鍵字。已確認的叫法命中時會重看有沒有別款也符合。改指、停用限管理員;`POST /identity/aliases/remember/` 記住叫法 |
| 停用商品 | 搜尋與候選看得到(標「已停用」),**選用不會恢復**。恢復限 tenant_admin / platform_admin:`POST /products/{id}/restore/` 或待確認入庫帶 `restore=true` |
| 新增商品防重複 | `apps/identity/dedup.py` `guard_new_product()`:所有建新品入口都過。條碼 / 已確認叫法相同 → 409 硬擋;特徵相似 → 409,帶 `distinct_reason`(寫哪裡不同)才放行,存 `ProductDistinctDecision`。批次每列各自說明,匯入列進略過。新增入口要建 Product 一定要呼叫它 |
| 新增商品的預設與用詞 | 2026-10-06 起(依 owner 交的診斷 `docs/MP-POS-商品主檔學習成本診斷與改善方向.md` 的階段 A)。**同一種商品從哪個入口建,預設都一樣**:規則在 `frontend/src/lib/productDefaults.ts`(有測試)——主機(手機 / 平板)逐件記序號,機型配件、通用配件按數量,**維修零件(零件倉)一律按數量**(`defaultRequiresSerial`);一般「新增商品」與「新增配件 / 型號展開」都用它。一般表單換商品性質或倉別時「需追蹤序號」跟著換,**除非**在編輯既有商品(可能已經有庫存)、人自己動過那一格、或被定住(虛擬商品一定不追、中古機一定追);這幾個動作都是 `lib/productDefaults` 裡吃整份表單狀態的函式(`withNature` / `withWarehouse` / `withPin` / `withSerialByHand`),測試是整段操作(含存草稿再載回來);商品性質底下顯示「庫存:逐件記序號 / 按數量」。**一般表單新增時選「主機」不直接建**:顯示「新增手機型號 / 留在這裡建立」,沒按後者之前不能存(`phoneNeedsWizard`;只管商品倉,切到零件倉不擋)——手機 / 平板走「新增手機型號」才有容量、顏色、品況的結構;那一頁要求至少一個容量、一個顏色,沒有這些之分的機種(老人機、手錶)才留在一般表單建。編輯既有的主機不受影響。**「新增手機型號」的品況只預選「全新」**(`defaultConditionIds`:啟用中、不是中古、也不用逐台記機況的第一個;找不到就都不勾),不再全部勾起來。**用詞各只有一個意思**:全新 / 已拆封 / 中古機那一邊叫「品況」(主檔頁是「商品品況」,以前叫「商品狀態」,舊名字留在 `nav.ts` 的 `aliases`);主力現貨 / 即將換代 / 停產下架 / 清倉處理那一邊叫「販售狀態」(`lifecycle_status`)。畫面上不寫 SKU、placeholder、wizard、欄位名稱,寫「品項」「這一頁」。「中古機」的勾選在看得到的「屬性」裡(以前收在「會計處理」)。勾「虛擬商品 / 中古機」會把那一格定住(虛擬不追、中古一定追),取消時回到該回的地方(`requiresSerialAfterUnpin`),不停在被連動改掉的值上。**表單自己要記的三件事放在表單狀態裡、跟著草稿存、不送到後端**:`serial_touched`(人動過序號沒有)、`serial_before_pin`(勾虛擬 / 中古之前的值)、`phone_here`(按過「留在這裡建立」,離開主機就收回)—— 放在元件自己的記憶裡的話,存草稿再載回來就沒了,只能用猜的、會猜錯;舊草稿沒有這幾欄時的補法在 `serialMemoryFromDraft`。「新增配件 / 型號展開」的「人動過」也存在它的草稿裡。批次貼上的預設、七個入口的收斂、先找再建、舊資料整理是階段 B / C / D(`BACKLOG.md`) |
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
│       ├── inventory/          Warehouse / ProductSerial / StockMovement + 商品標籤要印什麼(labels / label_views)
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
        │   ├── shell/          外框:Sidebar(側邊欄)/ ModuleBar(頁面上方的分頁與設定選單)/ NavSearch(功能搜尋)
        │   └── workbench/      工作台版型的零件:ScanBox(掃碼框,條碼排隊處理;沒加進去的碼怎麼記在 `lib/scanMissed.ts`,有測試)/ toast(訊息條,可帶復原)/ ArmButton(兩段式按鈕)/ MoreMenu(開單頁頁首的「更多」)/ QtyInput(打到一半不會被改掉的數量框)/ errors
        ├── pages/
        │   ├── products/        ProductsPage(合併商品 + 類別管理,左側兩段:商品搜尋 / 類別拖拉排序)+ ProductForm + ProductExpanderModal(型號展開,軸標籤可自訂)+ BulkAddProductsModal
        │   ├── purchases/       PurchaseListPage(進貨單清單:點一列展開、列印標籤 / 整張調撥 / 作廢;`/purchases/編號` 展開那一張)+ PurchaseWorkbenchPage(開單頁 `/purchases/new`:商品明細優先;序號格子 SerialSlots / serials.ts)+ PurchaseBatchPasteModal(批次貼上,模糊比對預覽)+ PurchaseProductPickerModal(勾選商品);後兩個在工作台裡是放在頁面裡的面板(`inline`),不是彈出視窗
        │   ├── sales/           SalesListPage(銷貨單清單:點一列展開、列印 / 整張銷退 / 作廢;`/sales/編號` 展開那一張)+ SalesWorkbenchPage(開單頁 `/sales/new`:商品明細優先;單據資訊、結帳、新增客戶 / 會員在右邊的抽屜;門號欄位接在商品正下方)+ SalesPage(只剩銷退單清單 `SalesReturnsPage`,`/sales/returns`)+ SalesPrintPage + SalesReturnEntryPage(搜尋原單 → 整張退,明細唯讀;`?so=編號` 直接帶好原單)
        │   ├── customers/       CustomersPage(客戶管理;tabs:全部/個人/同業/企業/其他;Detail 下半顯示該客戶銷售紀錄)
        │   ├── members/         MembersPage(會員獨立主檔;欄位姓名/電話/身分證/生日/地址/備註;Detail 下半顯示該會員銷售紀錄)
        │   ├── reports/         SalesDailyReport(銷貨日報,按單分組純表格 + 作廢區塊 + CSV 匯出;收購二手不計毛利) + ExploreReportPage(自由組合:挑指標 × 分組 × 條件 × 期間 × 比較,可存成我的報表)
        │   ├── settings/        SettingsPage(發票類型 / 字軌 / 付款方式)
        │   ├── sim-cards/       SimCardsPage + SimCardForm
        │   ├── telecom-plans/   TelecomPlansPage + TelecomPlanForm
        │   ├── secondhand-acquisition/  SecondhandAcquisitionPage(hub:tabs 切換)+ SecondhandPersonalEntry(個人收購表單;廠商收購直接內嵌 PurchaseWorkbenchPage)
        │   ├── inventory/       InventoryQueryPage(工作台版型:每家分店一欄 + 點一列就地展開每台序號 + 常用類別 + 欄位排序)+ CategoriesPage(舊獨立頁,nav 已隱藏但路由仍在)
        │   ├── labels/          LabelPrintPage(商品標籤列印頁 50 × 30 mm:進貨單整張 / 幾台 / 配件幾張 / 測試標籤;不套外框)
        │   ├── transfers/       TransferWorkbenchPage(工作台版型:新增、最近調撥、待入庫都在同一頁;`/transfers/編號` 展開那一張)
        │   ├── cash/            PettyExpensesPage 店頭雜支(列表 + Drawer 新增,連續模式)+ CashAdjustmentsPage
        │   ├── phone-bills/     PhoneBillsPage 代收話費(列表 + Drawer 兩步確認 + 電話會員 lookup)+ PhoneBillReceiptPage 80mm 熱感收據
        │   ├── login/           LoginPage(帳號密碼登入頁)
        │   └── platform-admin/  PlatformAdminPage(經銷商 / 用戶 / 倉別 三 tabs)+ 各 Tab 元件,只有 platform_admin 看得到
        ├── auth/                AuthContext + useAuth / useCurrentUser / useDefaultWarehouse / useDefaultHandledBy
        ├── nav.ts               導覽的唯一設定(入口、分頁、設定選單、舊名字)+ matchNav / searchNav / visibleModules;nav.test.mjs
        ├── App.tsx              路由與外框(側邊欄 Sidebar、頁面上方的分頁 ModuleBar 都在 components/shell/)
        └── styles.css           全站 CSS(暗色為預設、日間可切)。最上面是字級與尺寸的變數(正文 16 / 次要 14 / 區塊標題 18 / 頁標題 24 / 控制項 44px),畫面樣式一律用變數、不寫死 px;列印頁的樣式例外。同一段還有跟主題走的狀態文字色(`--warn-text` / `--success-text` / `--danger-text` / `--info-text`:夜間亮色、日間深色),寫警示 / 成功 / 錯誤的字一律用變數
```

後端新加的 endpoint:
- `GET /api/v1/products/stock-matrix/?warehouse_ids=1,2,3` — 庫存矩陣,給庫存查詢頁多倉欄位用
- `GET /api/v1/sales-orders/?...` filterset 加 `sales_person`(報表用)

## 慣例(Convention)

- **後端 service**:每個業務動作(commit / void)寫成 `apps/<app>/services.py` 的純函式,viewset 只負責 HTTP + 包 transaction
- **前端 hook**:所有 API 呼叫包成 `useXxx` / `useSaveXxx` / `useVoidXxx`,放 `api/hooks.ts`
- **搜尋 / 下拉**:萬筆級別都用 `ComboBox` + `api/search.ts` 裡面的 `searchXxx`,**不要**載入整張表
- **自動產生欄位**:`sku` / `code` / `no` 系統產生,前端**不顯示也不輸入**
- **儲存草稿**:`/sales/new` 與 `/purchases/new` 自動 debounce 寫 sessionStorage(離開頁面那一刻再存一次),儲存成功後清空;草稿裡帶著這張單的鑰匙與付款方式
- **migration 涉及資料改動**:在 migration 內寫 `RunPython` 一併處理(例如 billed_qty 預設帶 qty、seed PaymentMethod)
- **不可預測的字串(IMEI、卡號)**:存原值,前端顯示時取末 N 碼
- **金額**:顯示一律 `money()`、輸入框一律 `<MoneyInput>`(都在 `frontend/src/lib/money.ts` / `components/MoneyInput.tsx`);表單載入時把資料庫原本的字串放進 state、不要先收成整數(沒動過的欄位要原樣送回去);看已存的單直接顯示存下來的數字、不重算;後端算金額用 `apps/core/money.py` 的 `round_money()`,不要自己 `quantize`

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
