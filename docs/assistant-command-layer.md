# AI 指令層(assistant command layer)

> 設計原則(北極星):**POS 是帳本與規則引擎,AI 是主要操作介面,傳統表單只是檢查與例外處理工具。**
>
> 這份文件定義 `apps.assistant`:一層薄薄的「指令入口」,把自然語言 / 進貨單轉成
> **提案**,人確認後才呼叫既有帳本 service 過帳。配合 [architecture.md](architecture.md)、
> [data-model.md](data-model.md)、[business-rules.md](business-rules.md) 一起看。

## 1. 為什麼這層很薄(不是重寫)

現有架構其實已經替這件事鋪好路,`apps.assistant` 只是接上去:

| 既有設計 | 對指令層的意義 |
|---|---|
| 業務邏輯集中在 `services.py`(`commit_purchase_order` 等,原子、自我驗證) | 指令層只要「組出 payload → 呼叫同一個 service」,不重寫任何規則 |
| `commit_purchase_order` 內建驗證(序號數=數量、序號不重複、序號不得已存在) | 這些驗證就是**防呆網**:LLM 解析錯也進不了帳本 |
| `TrigramSearchFilter` + 逐欄搜尋(pg_trgm) | 「15 pro 256 黑 → SKU」的模糊解析器已存在,resolver 直接沿用 |
| 進貨單「儲存即生效」(`PurchaseOrderViewSet.perform_create` 存檔即 commit) | 帳本不存半成品;**確認的閘門放在指令層**(CommandLog),更貼合「POS=帳本」 |
| 多租戶(`tenant_id` 全表)+ roadmap Phase 5 訂閱 | 指令層天生 per-tenant,直接是未來 SaaS / 代操服務的差異化賣點 |

## 2. 資料流

```
自然語言 / 進貨單文字 / OCR
        │
        ▼   parsers.py(LLMParser 或 DeterministicParser)
   固定動作 Intent(JSON,只能是 intents.py 列的動作)
        │
        ▼   resolvers.py(沿用商品/供應商/倉庫主檔 + 模糊比對)
   對應真實主檔;不確定 → 產「追問」清單
        │
        ▼   services.interpret()
   CommandLog(status = awaiting_confirm|needs_clarification|failed)
        │            ★ 到這裡為止,帳本一個字都沒寫
        ▼   使用者在前端看提案 → 按確認
        ▼   services.confirm() → executor
   PurchaseOrderSerializer + commit_purchase_order()   ← 既有帳本 service
        │
        ▼
   ProductSerial / StockMovement / 加權平均(既有 audit 全自動)
   CommandLog.status = committed,回填 result_doc_type / result_doc_id
```

## 3. 三條鐵律

1. **LLM 只碰輸入。** 解析與消歧義用 AI;所有寫入一律走既有 service,讓既有驗證當防呆網。
2. **先提案、明確確認才過帳。** `interpret` 階段不寫帳本;`confirm` 才寫,且包在
   `transaction.atomic()`——service 一丟例外就整筆回滾(已用測試驗證)。
3. **解析優先用確定性方法。** resolver 先做精準 / icontains 比對,LLM 只在真的需要時介入;
   不確定就追問,或退回傳統 EntryForm 讓人手動收尾。

## 4. 固定動作集合(`intents.py`)

parser 不能自由發揮,只能輸出這裡列的動作。新增動作 = 加一筆 schema + 在
`services.EXECUTORS` 掛一個 executor,其餘(解析、確認、audit、前端)共用。

| action | 狀態 | 對應帳本 service |
|---|---|---|
| `create_purchase_order` | 已實作 | `purchasing.services.commit_purchase_order` |
| `create_sales_order` | 保留(規劃中) | `sales.services.commit_sales_order` |
| `create_transfer` | 保留(規劃中) | `transfers.services` |
| `update_serial_status` | 保留(規劃中) | `inventory`(IMEI 狀態維護 + audit) |
| `query_stock` | 保留(規劃中) | 唯讀查詢,不寫帳 |

「先把一條做到滴水不漏,再往外加」——目前只完整實作進貨單。

## 5. CommandLog 狀態機(`models.py`)

```
              interpret()
                  │
      ┌───────────┼─────────────┐
      ▼           ▼             ▼
 awaiting_    needs_         failed
  confirm    clarification  (解析失敗/不支援動作)
      │           │
 confirm()   (補資訊後重送 interpret)
      │
   ┌──┴───┐
   ▼      ▼
committed  failed(service 擋下,原子回滾)
   ▲
 reject() → rejected
```

CommandLog 同時是**稽核紀錄**(原始輸入、解析結果、提案、誰確認、產出哪張單)與
**parser 的訓練 / 回歸素材**。

## 6. 檔案地圖(`backend/apps/assistant/`)

| 檔案 | 負責 |
|---|---|
| `models.py` | `CommandLog`(TenantOwnedModel) |
| `intents.py` | 固定動作集合 + 給 LLM 的 JSON schema |
| `parsers.py` | `DeterministicParser`(規則,離線可跑)/ `LLMParser`(自然語言,預設關閉)/ `get_parser()` |
| `resolvers.py` | `resolve_product / resolve_supplier / resolve_warehouse`(DB 可攜) |
| `services.py` | `interpret()`、`confirm()`、executor registry(重用既有 serializer + service) |
| `serializers.py` `views.py` `urls.py` | REST 入口 |
| `tests.py` | 進貨單 end-to-end spike(4 個測試,全綠) |

## 7. API

```
POST /api/v1/assistant/commands/            { raw_input, source } → 回提案或追問
POST /api/v1/assistant/commands/{id}/confirm/   確認 → 呼叫既有 service 過帳
POST /api/v1/assistant/commands/{id}/reject/    放棄
GET  /api/v1/assistant/commands/            歷史(可 filter status / action)
```

## 8. 進貨單流程(已驗證)

輸入(DeterministicParser 的半結構化格式;LLMParser 吃純自然語言後產出同一份 Intent):

```
#進貨 供應商=大盤商A 倉庫=門市
iPhone 15 Pro 256GB 黑 x2 @35000 序號=356111111111111,356222222222222
```

`tests.py` 已證明(SQLite 隔離 DB,無需 LLM):
- 快樂路徑:過帳後建 2 筆 `ProductSerial(in_stock)` + 2 筆 `StockMovement(purchase_in)`,
  加權平均 = 33,333.33(35,000 含稅還原未稅)。
- 消歧義:「iPhone 15 128GB」對到兩筆 → `needs_clarification`,帳本不動。
- 防呆網:序號數不符 → `commit_purchase_order` 擋下 → `failed` 且整筆回滾(帳本 0 筆)。

## 9. 前端(對齊北極星)

- **主要快速道**:一個指令框(可由 roadmap 1.9 規劃中的 Cmd+K palette 演進而來)。
- **確認卡**:顯示 `proposal.display`(供應商 / 倉 / 逐行商品 / 序號數 / 金額預覽 + 序號不符警示),按鈕=確認 / 修改 / 放棄。
- **例外收尾**:追問或 service 失敗時,把現成的 EntryForm 用提案值預填,讓人手動改完送出。
- 既有 20+ 錄入 / 報表頁 → 降級為「確認 / 後備 / 進階」介面,不必再逐頁打磨到完美。

## 10. LLM 設定與資安

- 預設 `ASSISTANT_LLM_ENABLED=false` → 走 `DeterministicParser`,零外部相依。
- 啟用自然語言:設 `ASSISTANT_LLM_ENABLED=true` + `ASSISTANT_LLM_API_KEY`(見 `base.py`)。
- 送外部模型的資料應**去識別化**(客戶個資、序號可雜湊),或選用不拿資料訓練的服務;建議另開一則 ADR 記這個決策。
- 進貨單 OCR(拍照 / PDF)是最脆弱的一段:先只吃你最常遇到的 1–2 家供應商格式。

## 11. 分期

| 階段 | 範圍 |
|---|---|
| A(現在) | 進貨單指令 end-to-end + CommandLog + 確認卡;在自己店 dogfood |
| B | 加 `query_stock`(唯讀)、`update_serial_status`;LLMParser 上線吃純自然語言;進貨單 OCR |
| C | `create_sales_order` / `create_transfer`;clarification 的互動式補資料回填 |
| D | 建 eval 集(真實台語 / 通訊行行話指令 + 範例進貨單),每次調 prompt 跑回歸 |

## 12. 已知限制 / 待辦

- 目前 clarification 只「回報」不確定項,尚未做「使用者選一個候選 → 自動補回 payload」的回合;Phase C 補。
- resolver 在 SQLite 只用 icontains;PostgreSQL 可再疊 `TrigramSearchFilter` 的相似度處理打錯字。
- `pg_trgm` migration 在 SQLite 會因 `CREATE INDEX ... USING gin` 報錯(既有問題,與本層無關);測試以停用 migration 建表繞過。
- LLMParser 的 provider request/response 形狀依所選服務調整(現為 Anthropic Messages API 範例)。
