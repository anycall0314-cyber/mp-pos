---
name: pos-distill
description: 競品 POS 行為蒸餾。在授權範圍內觀察第三方 POS（例如歐睿）的畫面、欄位、操作行為與跨模組資料關係，整理成有證據、分清「已觀察事實 / 合理推論 / 尚待驗證」的 Markdown，再對照 MP POS 實際程式與資料模型，產出借鏡分類（A/B/C/D）、可開發的改善規格與 POS Integration Blueprint。owner 說「蒸餾 / 拆解 / 研究競品 POS」「看歐睿（或別家）怎麼做」「把某系統的某功能整理成欄位字典或規格」「拿競品跟我們的 POS 比」時使用。全程不改 MP POS 程式、資料庫結構與營運資料。
---

# pos-distill：競品 POS 行為蒸餾

把競品「怎麼做」轉成 MP POS「該怎麼改」的依據。**目標不是複製競品**：不搬畫面、文案、圖示、程式或資料；
只取操作邏輯、欄位設計、商業規則與資料關係，再依 MP POS 既有決策重新設計。

開工前必讀：
- 本檔全部（鐵則與安全限制每一步都適用）
- `references/conventions.md`：編號、三種標記、信心等級、個資遮罩、A/B/C/D 判準
- `references/module-catalog.md`：模組代碼與每個模組必問的問題
- `docs/pos-distill/_baseline/` 裡最新一份 MP POS 架構基準

---

## 一、怎麼叫

```
/pos-distill <系統代號> <動作> [模組代碼或主題]
```

| 動作 | 做什麼 | 對應階段 |
|---|---|---|
| `開檔` | 第一次研究這個系統：建資料夾、寫系統概況與授權範圍 | 0 |
| `基準` | 重新盤點 MP POS 架構（程式有新提交時） | 0 |
| `蒸餾 <模組>` | 單一模組的畫面、欄位、行為、跨模組影響 | 1 → 4 |
| `授權 <模組>` | 需要寫入測試時，產生授權申請單給 owner | 3 |
| `推導` | 跨模組整理競品的資料架構推論 | 5 |
| `比較 <模組 / 全部>` | 對照 MP POS 程式，逐項分 A/B/C/D | 6 |
| `規格 <主題>` | 把 A/B/C 的項目寫成可開發規格 | 7 |
| `藍圖` | 更新 POS Integration Blueprint | 8 |
| `狀態` | 只讀，回報這個系統蒸餾到哪裡 | — |

- 系統代號用小寫英數（例：`ored`）。沒給系統或模組就問一句，不猜。
- 一次只做一個模組；做完一段就存檔，不要累積在對話裡。

## 二、檔案放哪裡

Skill 本身（定義，不放資料）：
```
.claude/skills/pos-distill/
  SKILL.md
  references/conventions.md        編號、標記、信心、遮罩、A/B/C/D 判準
  references/module-catalog.md     模組代碼與必問清單
  templates/                       所有輸出的範本
```

輸出（資料，依系統 → 模組分類）：
```
docs/pos-distill/
  README.md                         總覽與各系統進度
  POS_Integration_Blueprint.md      整合藍圖（跨系統共用一份）
  .gitignore                        原始截圖錄影不進 git
  _baseline/MP_POS_架構基準_<日期>.md
  <系統代號>/
    00_系統概況.md                  授權範圍、帳號角色、版本、名詞對照、變更紀錄
    field-dictionary.md             統一欄位字典（全系統一份）
    relations.md                    統一互動關係（全系統一份）
    modules/<NN>-<模組代碼>.md      每個模組：畫面、流程、狀態、例外、跨模組矩陣
    architecture-inference.md       競品架構推導
    comparison.md                   與 MP POS 比較（A/B/C/D）
    open-questions.md               所有【待驗證】的總表
    specs/SPEC-<NNN>-<主題>.md      改善規格
    auth/AUTH-<NNN>.md              寫入測試授權申請與結果
    evidence/index.md               證據索引
    evidence/captures/              遮罩過的文字擷取（進 git）
    evidence/media/                 截圖、錄影原檔（不進 git）
```

建新檔一律從 `templates/` 複製再填，欄位順序與表頭不改，方便日後跨系統合併比較：

| 範本 | 產生的檔案 |
|---|---|
| `system-overview.md` | `<系統>/00_系統概況.md` |
| `field-dictionary.md` | `<系統>/field-dictionary.md` |
| `relations.md` | `<系統>/relations.md` |
| `module.md` | `<系統>/modules/<NN>-<代碼>.md` |
| `architecture-inference.md` | `<系統>/architecture-inference.md` |
| `comparison.md` | `<系統>/comparison.md` |
| `open-questions.md` | `<系統>/open-questions.md` |
| `evidence-index.md` | `<系統>/evidence/index.md` |
| `write-test-authorization.md` | `<系統>/auth/AUTH-<NNN>.md` |
| `improvement-spec.md` | `<系統>/specs/SPEC-<NNN>-<主題>.md` |
| `baseline.md` | `_baseline/MP_POS_架構基準_<日期>.md` |
| `integration-blueprint.md` | 只在 `POS_Integration_Blueprint.md` 不見時重建用 |

做完一個階段，同步更新 `00_系統概況.md` 的模組進度與 `docs/pos-distill/README.md` 的各系統進度。

## 三、鐵則（每一步都適用）

1. **三種標記，不可混用**。每一條結論都要標：
   - `【事實】` 親眼在畫面或操作結果看到的，必附證據編號（EV-…）。
   - `【推論】` 由事實推出來的，必寫「依據哪幾條事實 + 怎麼推的」。
   - `【待驗證】` 猜測或還沒查證的，必寫「要怎麼驗證」，並列進 `open-questions.md`。
   **推論不得寫成事實**。競品的資料庫結構、程式邏輯、內部計算永遠看不到，只能是【推論】，除非有廠商正式文件。
   推論升級成事實，要補上驗證用的證據，並在檔案的變更紀錄寫一行。
2. **每條重要結論都有證據**：來源頁面、操作步驟、截圖或錄影索引、驗證結果、信心（高 / 中 / 低）。格式見 `references/conventions.md`。
3. **只記欄位，不記客人**。個資遮罩規則見 `references/conventions.md`，有疑慮就不記。
4. **不複製**：不抄競品的畫面版型、按鈕文案、說明文字、圖示與報表樣式到 MP POS；比較與規格只描述「規則與資料關係」。
5. **對 owner 回報要短**：白話、直接講結果與要他決定的事，細節寫進檔案。不用 emoji。用繁體中文。

## 四、安全限制

### A. MP POS 這一側：只讀

- 可以：讀檔、搜尋、`git status / log / show / diff / blame`。
- 不可以：
  - 寫入 `docs/pos-distill/` 以外的任何檔案（包含 `AGENTS.md`、`CLAUDE.md`、`docs/decisions.md`、`docs/development/` 的 IDEAS / BACKLOG / CURRENT_TASK）。
  - `git add / commit / stash / checkout / reset / pull` 等任何會改工作區或歷史的指令。
  - 執行 `manage.py`（含 migrate、shell、測試）、`npm install / run`、`deploy.sh`、`push.sh`、`*.command`。
  - 開或連任何資料庫（`db.sqlite3`、PostgreSQL）、正式站或測試站的 API；讀 `.env` 的內容。
- 開工時記下 `git status --porcelain` 與 `HEAD`；收工時再比一次，確認除了 `docs/pos-distill/` 沒有任何變化。
  有別的變化（例如 owner 同時在改）只回報，不還原、不碰。
- 規格寫好後要進開發流程，由 owner 明講，再另外照 `docs/development/README.md` 處理；本 Skill 不代寫。

### B. 競品那一側：只在授權範圍內

開工前，`00_系統概況.md` 的「授權範圍」必須填好並經 owner 確認：用誰的帳號、什麼角色、可看哪些門市與模組、
使用條款或合約有沒有禁止事項。範圍外的一律不碰；條款看起來禁止這類研究就停下來問 owner。

**可以（被動觀察，不用另外授權）**
- 在 owner 已登入的瀏覽器裡，用一般使用者介面查詢、開明細、切分頁、篩選、排序、展開。
- 讀頁面文字與欄位屬性（只讀 DOM：標籤、輸入型別、必填、長度、選項清單）。JavaScript 只能查詢 DOM，
  不能送出表單、改欄位值、發網路請求、讀 cookie / localStorage / token。
- 看畫面自己發出的網路請求，只記「路徑與欄位名稱」，不記值。

**不可以（任何情況）**
- 猜網址進沒有權限的頁面；改網址或參數去看別家門市、別家公司或別人的資料。
- 重放、改造網路請求；直接呼叫畫面背後的 API；列舉編號；大量爬取或匯出資料。
- 讀取或保存登入憑證；繞過登入、驗證碼、權限或任何限制；反組譯、下載或保存競品程式碼。
- 遇到登入過期、驗證碼、權限不足：停下來告訴 owner，不嘗試繞過。

**寫入測試（新增、修改、刪除、作廢、送出表單、結帳、匯入、改設定、會取號或列印正式單據；
在沒確認過「不會自動儲存」的畫面上改任何欄位值，也算寫入）**
1. 先用 `templates/write-test-authorization.md` 產生 `auth/AUTH-<NNN>.md`：目的、逐步操作、用哪筆測試資料、
   預期影響哪些模組、怎麼復原、復原後會留下什麼。
2. 把重點用三五行告訴 owner，等他回覆「同意 AUTH-NNN」（原話記進申請單）。沒有明確同意就不做。
3. 只做申請單上寫的步驟，多一步都要重新申請。測試資料只用 owner 指定或核可的（品名、會員都要明顯標示為測試）。
4. 做完把前後狀態、證據、有沒有復原寫回申請單。

**就算 owner 同意也不做**（除非競品有獨立的測試環境，而且 owner 書面確認是那個環境）：
開立會上傳財政部的電子發票、電信門號開通或異動、真實金流扣款或退款、發簡訊或 LINE 給真實客人、
刪除歷史交易、改其他員工帳號的權限。這些改用「觀察既有單據」或「問 owner 實務經驗」，結論標【待驗證】或【推論】。

### C. 用什麼工具觀察

- 瀏覽器：用 owner 已登入競品的那個瀏覽器（預設 Claude in Chrome；先讀它的 skill）。開新分頁做，不動 owner 正在用的分頁。
- 頁面文字：`get_page_text` / `read_page`，遮罩後存 `evidence/captures/<EV>.md`。
- 欄位屬性：`javascript_tool` 只做查詢（`querySelectorAll` 讀 label、type、required、maxlength、pattern、option），不改值、不送出、不發請求。
- 畫面自己發出的請求：`read_network_requests`，只記路徑與欄位名稱。
- 錄影：`gif_creator`，檔名以 EV 編號開頭，放 `evidence/media/`。
- 會觸發瀏覽器確認視窗的按鈕（刪除、作廢）本來就屬於寫入，沒有授權不按。
- MP POS 程式：讀檔與搜尋工具；`git` 只用唯讀指令。

## 五、流程

### 階段 0：準備

1. 讀 `docs/pos-distill/_baseline/` 最新一份。比對它記的 commit 與目前 `HEAD`：
   - 一樣 → 直接用。
   - 不一樣 → 用 `git log --stat <基準commit>..HEAD` 看改了哪些 app，只補盤點有變的部分，
     寫一份新的 `MP_POS_架構基準_<今天>.md`（從 `templates/baseline.md` 開始，未變的部分可以沿用並註明）。
2. 第一次研究這個系統：建 `<系統代號>/`，從範本建 `00_系統概況.md`、`field-dictionary.md`、`relations.md`、
   `architecture-inference.md`、`comparison.md`、`open-questions.md`、`evidence/index.md`。
3. 填授權範圍，請 owner 確認。沒確認不進階段 1。
4. 已有的舊資料（例如歐睿的 `docs/legacy-pos-functions.md`、`docs/migration/ored_ui_relationships_*.json`、
   `docs/MP_POS_歐睿移轉_資料關聯與切換規劃.md`）列進 `00_系統概況.md` 的「既有資料」，
   當作線索而不是事實：要重新觀察過才能標【事實】，引用時註明原檔與日期。

### 階段 1：UI 介面蒸餾（寫進 `modules/<NN>-<代碼>.md` 的第 1 節）

照 `references/module-catalog.md` 這個模組的必問清單，記：
- 功能入口：從哪個選單、幾層、有沒有快捷鍵或其他入口。
- 頁面結構：區塊、版型（清單 / 明細 / 彈出視窗 / 分頁）、主要動作在哪裡。
- 欄位配置：每個欄位給一個欄位編號，詳細寫進 `field-dictionary.md`，這裡只列編號與位置。
- 按鈕、搜尋（能搜哪些欄位、模糊或精確）、篩選、排序、分頁、匯出。
- 視窗：什麼時候跳、跳了會不會遺失已填資料。
- 操作步驟數：完成一件事要點幾下、打幾個字、換幾個畫面（owner 很在意）。
每一項附 EV 編號。

### 階段 2：欄位字典（寫進 `field-dictionary.md`）

每個欄位一列：名稱、用途、資料型態、必填條件、預設值、驗證規則、相依欄位、可能資料來源、標記、信心、證據、MP POS 對應。
- 必填、長度、選項：先看 DOM 屬性，再看實際送出空值的錯誤訊息（後者屬寫入，要授權）。
- 預設值與連動：**改欄位值預設算寫入**。只有在已確認「不會自動儲存、沒有副作用」的畫面
  （例如還沒送出的新增單據草稿），才可以不經授權切換欄位觀察連動；確認方式與 EV 記在
  `00_系統概況.md` 的「已確認不會自動儲存的畫面」。離開欄位就存檔、即時更新、或不確定的畫面，
  一律走寫入測試授權。
- 「可能資料來源」只能是推論或待驗證，除非畫面直接寫明。
- MP POS 對應欄填 `app.Model.field`；沒有就寫「無」。

### 階段 3：行為蒸餾（寫進模組檔第 2–4 節）

- 流程：每一步「使用者做什麼 → 畫面怎麼反應 → 資料狀態前 → 後」。
- 狀態轉換：實體、從哪個狀態、什麼事件、到哪個狀態、條件、副作用。
- 例外：輸入錯、庫存不足、重複序號、權限不足、作廢已被使用的單…系統怎麼反應、擋不擋。
- 「之前 / 之後」的狀態要用唯讀畫面查（例如操作前後各查一次庫存、序號、會員紀錄）。
- 需要真的存檔才看得到的行為 → 走寫入測試授權；沒授權就標【待驗證】並寫驗證方法。

### 階段 4：跨模組分析（寫進模組檔第 5 節與 `relations.md`）

對每個會改資料的操作，逐一檢查這九個面向，填進模組檔的跨模組矩陣：
庫存數量、IMEI / 序號狀態、會員、交易紀錄、成本、毛利、佣金、應收帳款、財務報表。
- 有影響的寫成一條 `REL-<NNN>` 進 `relations.md`：觸發操作 → 影響哪個實體哪個欄位、怎麼影響、什麼時點、作廢時怎麼回。
- 看不到影響 ≠ 沒有影響：寫「未觀察到影響（查了哪個畫面）」，不要寫「沒有影響」。
- 報表數字的影響用「操作前後各看一次同一張報表」來驗證；只看一次的一律【推論】。

### 階段 5：競品架構推導（寫進 `architecture-inference.md`）

- 從欄位字典與關係表，推出競品可能的實體、主鍵與編號規則、實體間關係、計算時點（即時 / 日結 / 月結）、
  成本方法、作廢與刪除的差別、多門市與多公司的切分方式。
- 每一條推論編 `INF-<NNN>`，寫依據（FD / REL / EV）、推理、反例（什麼觀察會推翻它）、信心。
- 可以畫 mermaid 圖，但圖的標題要寫「推論」，圖裡每條線都要能對回 INF 或 REL 編號。
- 推不出來的寫進 `open-questions.md`，不要硬補。

### 階段 6：與 MP POS 比較（寫進 `comparison.md`）

- 先讀基準，再讀實際程式（models、services、views、frontend pages）確認現況；MP POS 現況必附 `檔案:行號`。
- 每個比較項 `CMP-<NNN>`：競品做法（附標記與證據）、MP POS 現況、差異、分類、理由、影響範圍、建議下一步。
- 分類依 `references/conventions.md` 的 A/B/C/D 判準；每一項都要對過「MP POS 不可違反的決策」清單（在基準檔）。
- 競品做法本身只有【推論】或【待驗證】的項目，最多分到 B 或「待驗證後再分類」，不能分 A。

### 階段 7：改善方案（寫進 `specs/SPEC-<NNN>-<主題>.md`）

只為 A、B、C 寫規格；D 在比較表寫清楚理由就好。用 `templates/improvement-spec.md`，必填：
來源（CMP / INF / EV 編號）、問題與目標、現況（檔案:行號）、提案、資料模型影響、既有功能相容性、
多租戶隔離、安全與權限、測試案例、驗收條件、不做的事、要 owner 決定的事、複審分流。
- 資料模型影響要寫到「哪個 app、新表或新欄位、要不要 RunPython 補舊資料、備份登記（`apps/backup/registry.py`）
  要歸哪一類、`analytics/catalog.py` 與 `ledger` 要不要跟著改」。
- 多租戶：新業務表一律繼承 `TenantOwnedModel`；序列化器與篩選要套既有的租戶限縮；門市鎖定帳號怎麼看。
- 測試案例至少包含：別家公司看不到、被鎖門市的店員只看得到自己門市、作廢後照既有規則回復
  （分開列「會回到開單前的」與「既有規則刻意不回的」，例如銷退作廢不還原原銷貨單的發票作廢狀態）、
  同一張單送兩次只成立一次、單據金額四捨五入到整數元而成本保留到分（有動到錢的話）。
- 引用其他系統的編號時加系統代號（例：`ored/SPEC-001`、`ored/CMP-003`），避免不同系統的編號撞號。
- 規格是提案，不是施工單。不寫程式碼、不寫 migration 檔。

### 階段 8：POS Integration Blueprint（更新 `docs/pos-distill/POS_Integration_Blueprint.md`）

- 更新「整合對照表」「租戶設定候選」「規格清單與狀態」「整合順序」四節；其他節只在基準變了才改。
- 規格狀態只用：草稿 / 待 owner 決定 / owner 同意（等待排入開發） / 不做。
  「已排入開發」只能由 owner 改，本 Skill 不改成這個狀態。

## 六、完成前自查（每次收工都跑）

- [ ] 每一條結論都有【事實】【推論】【待驗證】其中一個標記；【事實】都有 EV；【推論】都有依據；【待驗證】都有驗證方法並在 `open-questions.md`。
- [ ] 沒有個資值：搜尋自己這次新增的內容，不應出現完整電話、身分證、完整 IMEI、地址、客人全名。
- [ ] 每個新 EV 都在 `evidence/index.md`；媒體檔在 `evidence/media/`，檔名以 EV 編號開頭。
- [ ] 寫入測試都有對應的 AUTH 檔與 owner 原話；沒有授權外的寫入。
- [ ] 比較表的 MP POS 現況都有 `檔案:行號`。
- [ ] `git status --porcelain` 跟開工時比，只多了 `docs/pos-distill/` 底下的檔案。
- [ ] 檔案變更紀錄（各檔最下方）寫了今天做了什麼。

## 七、回報 owner 的格式

最多 8 行：
1. 這次做了哪個系統、哪個模組、哪個階段。
2. 最重要的 1–3 個發現（標記與信心一起寫）。
3. 要 owner 決定或協助的事（授權申請、待驗證問題、分類有疑慮的項目）。
4. 檔案在哪裡（相對路徑）。
