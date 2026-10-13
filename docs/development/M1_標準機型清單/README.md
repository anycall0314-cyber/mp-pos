# M1 標準機型清單 · 草稿的工作檔

owner 2026-10-14:手機、平板、穿戴的型號由平台統一制定;名稱「照一般的寫法」;參考查價系統裡創宇的機型與規格;
要開一個資料池,共享給底下每一家經銷商。任務的範圍與分步在 `../CURRENT_TASK.md`「M1 標準機型清單」。

| 檔 | 是什麼 |
|---|---|
| `hub_by_model.json` | 2026-10-14 從查價系統(`~/phone-buyback-hub`,正式庫在 mini)唯讀匯出:724 個機型的品牌、名稱、類型、每一種規格(容量、RAM、平板 WiFi / 插卡)。只有名稱與規格,沒有價格 |
| `curate.py` | 把上面那一份整理成一般寫法的標準名稱(統一大小寫與空白、補品牌字、標出特別版、把放錯類的平板改回來),再跟 POS 現有的標準型錄(168 個)合併 |
| `standard_draft.json` | 產出的草稿:760 個機型(手機 683、平板 63、手錶 14) |

給 owner 看的可搜尋頁面:https://claude.ai/artifact/MoNKjuQjUc93byoiB6QGqE (私人的,只有他開得到)。

重抓查價系統的資料(唯讀;每天 16:00 排程在跑的時候不要動):

```
ssh mini 'sqlite3 -readonly /Volumes/Data/phone-buyback-hub/hub.db -json "select m.brand, m.canonical_name as name, m.form_factor as form, v.storage_label as storage, v.ram_gb as ram, v.connectivity as conn from device_models m left join device_variants v on v.model_id = m.id order by m.brand, m.canonical_name, v.storage_gb, v.ram_gb"'
```
再整理成 `{"品牌|名稱": {"form": "phone|tablet", "variants": [[容量, RAM, 網路], …]}}`。

**這些都還是草稿**:沒有進 `backend/apps/catalog/data/`、沒有寫進任何資料庫。
