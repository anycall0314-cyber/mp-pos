// 進貨明細在畫面這一側:條件怎麼變成網址、數量那一格、匯出。跑法:npm test。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { purchaseLineQuery, purchaseLineTable, qtyText } from "./purchaseLines.ts";
import { PAGE_SIZE } from "./stockReports.ts";

const filter = { from: "2026-10-01", to: "2026-10-12", warehouse: "", supplier: "", category: "", search: "" };

test("網址:空的條件不送;看畫面用頁碼,匯出要全部", () => {
  assert.equal(purchaseLineQuery(filter, 1), `from=2026-10-01&to=2026-10-12&page=1&page_size=${PAGE_SIZE}`);
  assert.equal(
    purchaseLineQuery({ ...filter, warehouse: 8, supplier: 2, category: 4, search: " 保護貼 " }, "export"),
    "from=2026-10-01&to=2026-10-12&warehouse=8&supplier=2&category=4&search=%E4%BF%9D%E8%AD%B7%E8%B2%BC&export=1",
  );
  assert.ok(!purchaseLineQuery({ ...filter, search: "  " }, 2).includes("search"));
});

test("數量那一格:有贈品的寫出來", () => {
  assert.equal(qtyText({ qty: 12, free_qty: 2 }), "12(贈 2)");
  assert.equal(qtyText({ qty: 3, free_qty: 0 }), "3");
});

test("匯出:一行一列,金額不加千分位", () => {
  const row = {
    id: 1, date: "2026-10-12", doc: { kind: "purchase", id: 7, no: "PO-000007" }, store: "民生店", supplier: "甲二盤",
    product: 3, sku: "LC-000002", name: "9H 保護貼", qty: 12, free_qty: 2, unit_price: "105.00", amount: "1050.00",
    cost: "1000.08", note: "月結",
  };
  assert.deepEqual(purchaseLineTable([row]), [
    ["日期", "單號", "門市", "供應商", "品號", "品名", "數量", "贈品", "單價", "金額", "成本", "備註"],
    ["2026-10-12", "PO-000007", "民生店", "甲二盤", "LC-000002", "9H 保護貼", 12, 2, "105", "1050", "1000", "月結"],
  ]);
  assert.equal(purchaseLineTable([]).length, 1);
});

test("進貨明細掛在進貨入庫底下、名稱四個字、有路由", () => {
  const nav = readFileSync(new URL("../nav.ts", import.meta.url), "utf8");
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.ok(/to: "\/purchases\/lines",\s+label: "進貨明細"/.test(nav));
  // 進貨單之後就是商品管理(owner 定的順序):明細排在後面
  assert.ok(nav.indexOf('to: "/products"') < nav.indexOf('to: "/purchases/lines"'));
  assert.ok(app.includes('path="/purchases/lines" element={<PurchaseLinesPage />}'));
  // 靜態的路徑要排在「/purchases/:id」前面才不會被當成單號
  assert.ok(app.indexOf('path="/purchases/lines"') < app.indexOf('path="/purchases/:id"'));
});
