# kcimos 下單流程實測(2026-10-13)

> owner 登入之後,我在他的 Chrome 裡**只讀**了快速下單、購物車、結帳、訂單查詢這幾頁的表單與頁面上的程式。
> 經他同意(「可以放」)放了一項商品進購物車、看完結帳頁就刪掉;**沒有送出任何訂單**,看完購物車是空的。
> 這一份沒有帳號、密碼、cookie;訂單內容與收件資料也沒有記。

網站:`http://kcimos.kv.idv.tw`(沒有加密;登入靠 cookie;表單裡沒有防偽造的欄位)。頁面用 jQuery 的 `ajaxSubmit` 把表單送到下面這些路徑。

## 一、放進購物車

`POST /frontend/order/addCart.shtml`(表單 `#form_addCart`)

| 欄位 | 內容 |
|---|---|
| `cart.product_pk` | 商品編號(就是價目表料號 `KCIMOS-<編號>` 後面那一段) |
| `cart.qty` | 數量(頁面只檢查是正整數) |
| `cart.saleQty` | 平常是 `0`(只有寄售的商品頁面上才有另一格) |

回來的是購物車那一小塊的網頁:每一項「分類 品牌 品名 數量 x NT$單價」、一顆「刪除」(帶 `cartPk`)、一顆「訂單結帳」。
已經下架的商品也放得進去(實測放的那一項品名後面寫「(已下架)」)。

- 看購物車:`POST /frontend/order/listCart.shtml`(沒有欄位)。空的時候寫「無購物清單」。
- 刪一項:`POST /frontend/order/deleteCart.shtml`,欄位 `cart.pk` = 那一項的 `cartPk`。(頁面上按刪除會先跳確認視窗。)

## 二、結帳頁

`GET /frontend/order/cart2Order.shtml` —— **只是把購物車變成一張表單,還沒有成立訂單。** 表單 `#form_editOrder`:

| 欄位 | 內容 |
|---|---|
| `order.pk` | `0`(新的訂單) |
| `order.agent_pk` | 這個帳號的編號(頁面帶好的) |
| `orderItemList[n].pk` | `0` |
| `orderItemList[n].product_pk` / `.price` / `.qty` | 每一項的商品編號、單價(頁面帶好的)、數量(可以改) |
| `order.totalAmount` | 未稅合計(頁面的程式算了才填進去,一開始是 0) |
| `order.name` / `order.tel` / `order.cell` / `order.email` / `order.address` | 收件者姓名、電話、手機、信箱、地址。**姓名、電話、信箱、地址會帶這個帳號預設的**;手機是空的。長度上限:電話 / 手機 20、信箱 60、地址 200 |
| `order.memo` | 備註,最多 200 字 |

金額(頁面上算給人看的):合計 = 各項未稅小計相加;稅額 = 合計 × 5% 四捨五入;總金額 = 合計 + 稅額;
**運費:未稅合計不到這個帳號的免運門檻(頁面上的 `noDeliveryFeeAmount`,這個帳號是 3,500)收 85,滿了 0。**

結帳頁也可以刪掉一項:`POST /frontend/order/deleteCart2OrderItem.shtml`,欄位 `cart.pk`。

## 三、送出訂單(**這一步沒有實測**)

按「確認送出」→ `POST /frontend/order/editOrder.shtml`(整張 `#form_editOrder`),回 JSON:`{status, msg, errorCode}`。
- `status` 是真:頁面跳出 `msg`、轉到訂單查詢。
- `status` 是假:跳出 `msg`;`errorCode` 是用逗號分開的幾個編號(頁面拿它去標有問題的那幾行)。
- 送出前頁面只檢查:每一項數量是正整數;寄售的銷售數量不能大於庫存。

不知道的(要真的送一張才知道):`msg` 裡有沒有訂單編號;伺服器會不會自己重算金額;缺貨、下架的項目會回什麼。

## 四、訂單查詢

`POST /frontend/order/listOrder.shtml`,欄位 `condition.oid`(訂單編號)、`condition.beginDT` / `condition.endDT`(時間,格式沒試出來)、
`condition.queryType`(`0` 訂單總表 / `1` 訂單明細)、`condition.isShip`(`-1` 全部 / `1` 是 / `0` 否)。
條件都空 = 全部訂單、新的在前(實測 841 筆,沒有分頁)。

欄位:功能、訂單編號(`SO` + 日期 + 流水,例 `SO20261012773`)、類別、收件者、訂購金額、訂單確認出貨(是 / 否)、預計出貨日、訂單建立日期(到秒)。
每一列開明細:`/frontend/order/initViewOrder_<編號>.shtml`。

## 對 K1b 的意思

- 「放進購物車 → 讀結帳表單 → 送出 → 查單號」四步都是登入之後同一個網站裡的請求,**只要在登入過的那個瀏覽器分頁裡發,就做得到**。
- 從 POS 的網頁直接對 kcimos 發請求做不到:瀏覽器不會把 kcimos 的登入帶過去(跨網站),而且 POS 是加密的、kcimos 不是。所以自動的那一段要在 kcimos 的頁面裡跑。
- 一張叫貨單要送的就是每一行的 `(商品編號, 數量)`,加上收件資料與備註(可以放 POS 的叫貨單號,之後對單用)。
- 送出前可以自己先算一次合計、稅、運費(規則在上面)給人確認。
