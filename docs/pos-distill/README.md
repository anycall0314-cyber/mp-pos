# 競品 POS 蒸餾（pos-distill）

把第三方 POS 的操作邏輯、欄位設計、商業規則與資料關係整理成有證據的文件，
再轉成 MP POS 的改善規格。**目的是改善自己的架構，不是複製競品。**

- 怎麼做：`.claude/skills/pos-distill/SKILL.md`
- 整合藍圖：`POS_Integration_Blueprint.md`
- MP POS 架構基準：`_baseline/`
- Skill 複審：`_review/`（2026-10-17 Codex 唯讀複審通過，結果在 `codex-review-result.md`）

## 怎麼用（對 Claude 說）

| 想做的事 | 指令 |
|---|---|
| 開始研究一個新系統 | `/pos-distill ored 開檔` |
| 蒸餾一個模組 | `/pos-distill ored 蒸餾 SAL` |
| 需要實際存檔測試 | `/pos-distill ored 授權 SAL`（會先給你一張授權申請，你回「同意 AUTH-001」才做） |
| 推導競品的資料架構 | `/pos-distill ored 推導` |
| 跟 MP POS 比較 | `/pos-distill ored 比較 SAL` |
| 寫改善規格 | `/pos-distill ored 規格 <主題>` |
| 更新整合藍圖 | `/pos-distill ored 藍圖` |
| 看進度 | `/pos-distill ored 狀態` |
| MP POS 程式有大改之後 | `/pos-distill ored 基準` |

模組代碼：PRD 商品、STK 庫存序號、PUR 進貨、SAL 銷貨、RTN 銷退、TRF 調撥、MBR 會員、TEL 門號佣金、
RPR 維修、USD 中古、CSH 現金、ARP 應收應付、IVC 發票、RPT 報表、ACL 權限、CFG 設定、TNT 多公司、B2B 批發叫貨。

## 文件怎麼讀

每一條結論都有標記：
- 【事實】親眼看到，附證據編號
- 【推論】從事實推出來的，寫了依據
- 【待驗證】還沒查證，列在該系統的 `open-questions.md`

比較結果分四類：A 直接借鏡、B 重新設計、C 讓各家公司自己設定、D 不採用。

## 各系統進度

| 系統 | 代號 | 開始日期 | 已完成模組 | 規格數 | 備註 |
|---|---|---|---|---|---|
| 聯歐通訊聯盟內部管理系統（立穎所用） | lw | 2026-10-17 | PRD、STK、PUR、TRF、TEL、ARP、RPT、B2B（唯讀第一輪完成；比較 27 項） | 4 | 唯讀；授權範圍待 owner 補確認 |

## 注意

- 這個資料夾以外的 MP POS 檔案，蒸餾期間一律不改。
- `*/evidence/media/` 的截圖錄影不進 git（可能有個資）；需要保存請另外備份。
- 規格是提案；要開工請照 `docs/development/README.md`。
