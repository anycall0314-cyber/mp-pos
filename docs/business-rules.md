# 業務規則速查表

> 把「做什麼會發生什麼」集中一份。改規則時要同步更新這份文件。

## 課稅與金額計算

| 課稅別 | unit_price 含義 | subtotal(未稅) | tax | total(含稅) |
|---|---|---|---|---|
| `taxable_included` 應稅內含 | 含稅單價 | `gross / 1.05` | `total - subtotal` | `gross` |
| `taxable_excluded` 應稅外加 | 未稅單價 | `gross` | `gross × 0.05` | `subtotal + tax` |
| `tax_free` 免稅 | 同未稅 | `gross` | 0 | `gross` |
| `zero_tax` 零稅 | 同未稅 | `gross` | 0 | `gross` |

`gross` = sum(明細 `billed_qty × unit_price`)。

## 進貨單 commit_purchase_order

1. 驗證每筆明細的 `serial_numbers` 數量 = `qty`(虛擬商品 `requires_serial=False` 例外,序號需留空)
2. 同單序號 / 全系統序號不重複
3. `unit_landed_cost` = 未稅單價(含稅單時 = `unit_price / 1.05`)
4. 為實體商品建 `ProductSerial(status=in_stock)`、寫 `StockMovement(purchase_in)`
5. 更新 `Product.weighted_avg_cost`(未稅成本):
   ```
   new_avg = (current_stock × current_avg + batch_qty × unit_landed_cost) / (current_stock + batch_qty)
   ```
   贈品(`billed_qty < qty`)的稀釋效果由 `unit_landed_cost = (net × billed_qty) / qty` 表達
6. 寫單頭 `subtotal / tax_amount / total_cost`

## 進貨單 void_purchase_order

- 拒絕作廢條件:**該單建立的任一序號狀態 ≠ in_stock**(已賣 / 已調撥 / 已 RMA)
- 通過後:
  1. 所有序號 → `status=void`、`warehouse=None`
  2. 寫 `StockMovement(void)`
  3. 重算受影響商品的 `weighted_avg_cost`(以剩餘 in_stock 序號的 `purchase_unit_cost` 平均)
  4. `PurchaseOrder.is_void = True`

## 銷貨單 commit_sales_order

1. 驗證明細:
   - 虛擬商品:不可帶序號
   - `requires_serial=True`:`item.serials.count() == qty`,每個序號需 `in_stock` + 屬於 `product` + 在 `so.warehouse`
   - 非虛擬非序號(配件 MVP):未支援,擋下
   - 整單序號不重複
2. 屬性檢查:
   - 商品 `allows_telecom_line=False` → 不可填 SIM / 門號 / 方案 / 上線日
   - 商品 `allows_commission=False` → commission 必須為 0
   - 方案 `kind ∈ {new, portin}` → 必填 SIM 卡;`kind=renewal` → 不可填 SIM
   - SIM 卡 `vendor` 必須等於方案 `carrier`,狀態必須 `in_stock`
3. 驗證付款金額:`sum(payments.amount) == total`,total > 0 時不可為空
4. 算稅 → `subtotal / tax_amount / total`
5. 若 `invoice_form` 已指定且 `invoice_no` 為空 → 從 `InvoiceTrack` 自動取號(`assign_invoice_no` 用 `SELECT FOR UPDATE` 序列化),`invoice_date` 帶今天
6. 對每個 `SalesOrderItemSerial`:`serial.status=sold`, `sold_at=now`, `warehouse=None`,寫 `StockMovement(sale_out)`
7. SIM 卡:`status=issued`, `issued_at=now`
8. `item.cost_at_post`:
   - 虛擬商品 = 0
   - 實體商品 = sum(各 serial 的 `purchase_unit_cost`)

## 銷貨單 void_sales_order

- 不檢查條件(總是可作廢)
- 對每個 `SalesOrderItemSerial`:
  - `serial.status=in_stock`、`warehouse=so.warehouse`、`sold_at=None`
  - 寫 `StockMovement(return_in)`
- SIM 卡:`status=in_stock`、`issued_at=None`
- `SalesOrder.is_void = True`

## 序號狀態機

```
                     進貨單建單
                        ▼
        ┌───────►  in_stock  ◄──────┐
        │              │            │
   作廢進貨            銷貨          銷貨作廢
        │              │            │
        ▼              ▼            │
       void          sold ─────────┘
                       │
                  (永遠停在 sold,
                   除非該銷貨單作廢)
```

調撥、RMA、in_transit 由 Phase 2+ 模組擴充。

## SIM 卡狀態機

```
   in_stock ──銷貨──► issued ──上線開通──► activated
       ▲                │                      │
       │           銷貨作廢                  退回廠商
       │                ▼                      ▼
       └──────── in_stock                  returned
```

## 發票字軌自動取號

`assign_invoice_no(tenant, code)`:
1. `SELECT FOR UPDATE` 鎖定該 tenant + 該 invoice_type + is_active=True 的字軌,依 id ASC 排序
2. 取第一個 `next_number <= range_end` 的字軌
3. 格式化:`{prefix}{next_number:08d}` 如 `AB12345678`
4. `next_number += 1`
5. 寫回
6. 若所有字軌都用完 → 拋 `InvoiceTrackError`

`peek_next_invoice_no` 是非鎖定預覽,給前端 UI 即時顯示「下一張會是 XXX」。

## 加權平均成本

定義:`Product.weighted_avg_cost` = 該商品所有 `status=in_stock` 序號的 `purchase_unit_cost` 平均。

維護時機:
- 進貨單 commit:遞增式更新(舊平均 × 舊 stock + 新批未稅總額)/ 新 stock
- 進貨單作廢:重算(掃所有剩餘 in_stock 序號)
- 銷貨 / 銷貨作廢:**不重算**(售出不改變單台成本,只是把它移出 in_stock 池)

## 商品旗標組合

| `requires_serial` | `is_virtual` | 含義 |
|---|---|---|
| T | F | 序號商品(手機),逐台追蹤 |
| F | T | 虛擬商品(門號專案、成本回補、手續費),不入庫不算成本 |
| F | F | 一般配件(MVP 未實作,銷貨會被擋下) |
| T | T | 不合理,前端 ProductForm 自動互斥(勾虛擬時 requires_serial 強制 false) |

額外旗標:
- `allows_telecom_line`:可在銷貨單填門號 / 方案 / SIM 卡
- `allows_commission`:可填佣金
- `counts_cash` / `counts_margin`:現金 / 毛利分析時是否計入(報表用,目前未串)

## 付款分類(`PaymentMethod.kind`)

| kind | 影響當日現金 | 預設項目 | 適用 |
|---|---|---|---|
| `cash` | ✓ | 現金 | 實體鈔票 |
| `transfer` | ✗ | 匯款 | 銀行轉帳 / ATM,T+1 才入帳 |
| `non_cash` | ✗ | 信用卡 | 刷卡 / LinePay / 街口 / 全支付 / Apple Pay |

之後做日報時:當日現金收入 = sum(payments.amount WHERE kind=cash AND so.doc_date=today AND so.is_void=False)。

## 自動產生欄位

| 模型欄位 | 規則 |
|---|---|
| `Product.sku` | `{category.code}-{6位流水}` 例:`PH-000001` |
| `TelecomPlan.code` | `{carrier.code}-{6位流水}` 例:`CHT-000001` |
| `PurchaseOrder.no` | `PO-{6位流水}` |
| `SalesOrder.no` | `SO-{6位流水}` |
| `SalesOrder.invoice_no` | `{字軌前綴}{8位}` 例:`AB12345678`(從字軌自動取號) |
| `PaymentMethod.code` | 使用者沒填 → `pm_{6字元 hex}` |
| `Category.code` / `Carrier.code` / `Warehouse.code` | 使用者輸入,通常 2~10 字元代碼 |
