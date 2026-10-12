// 盤點在畫面這一側:每一格怎麼寫、核准時送什麼。跑法:npm test。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  amountCards, approveBody, countedQty, extraText, missingText, movedHint, progressText, scopeText, signed,
} from "./stockCount.ts";

const line = { id: 5, product: { id: 9, sku: "LC-0001", name: "皮套" }, counted_qty: 8, counted_at: "", moved_out: 0, moved_in: 0 };

test("範圍:沒挑類別 = 全部", () => {
  assert.equal(scopeText({ categories: [] }), "全部");
  assert.equal(scopeText({ categories: ["皮套", "保護貼"] }), "皮套、保護貼");
});

test("開盤之後有動過才寫:出幾個、進幾個(不寫 0、不寫帳上總數)", () => {
  assert.equal(movedHint({ moved_out: 0, moved_in: 0 }), "");
  assert.equal(movedHint({ moved_out: 2, moved_in: 0 }), "出 2");
  assert.equal(movedHint({ moved_out: 0, moved_in: 5 }), "進 5");
  assert.equal(movedHint({ moved_out: 2, moved_in: 5 }), "出 2 進 5");
});

test("差多少:多的有加號、少的是負的", () => {
  assert.deepEqual([signed(2), signed(-1), signed(0)], ["+2", "-1", "0"]);
});

test("進度:盤了幾樣、刷了幾台;還在盤的才寫還有幾樣沒盤", () => {
  const detail = { line_rows: [line, line], scan_rows: [{}], left: 3, status: "counting" };
  assert.equal(progressText(detail), "配件 2 樣　手機 1 台　未盤 3 樣");
  assert.equal(progressText({ ...detail, status: "submitted" }), "配件 2 樣　手機 1 台");
});

test("管理員那一排金額:配件、手機、合計(字數一樣)", () => {
  const cards = amountCards({ lines: "-200.00", phones: "-20000.00", total: "-20200.00" });
  assert.deepEqual(cards, [
    { label: "配件", value: "-200" }, { label: "手機", value: "-20,000" }, { label: "合計", value: "-20,200" }]);
  assert.deepEqual([...new Set(cards.map((c) => c.label.length))], [2]);
});

test("多出來的:不認得的寫不認得,認得的寫品名與帳上的狀態", () => {
  assert.equal(extraText({ name: "", state: "" }), "不認得");
  assert.equal(extraText({ name: "iPhone 15", state: "已售" }), "iPhone 15 已售");
});

test("少的那一台:核准前看還在不在庫,核准後看有沒有標成盤虧、找回", () => {
  const m = { applied: false, found: false, skipped: false, still_here: true };
  assert.equal(missingText(m, false), "");
  assert.equal(missingText({ ...m, still_here: false }, false), "已不在庫");
  assert.equal(missingText({ ...m, applied: true }, true), "盤虧");
  assert.equal(missingText({ ...m, applied: true, found: true }, true), "已找回");
  assert.equal(missingText({ ...m, skipped: true }, true), "不調");
  assert.equal(missingText({ ...m, still_here: false }, true), "已不在庫");
});

test("核准時送的:沒動過的列不送;調整量空的不送(伺服器照差異調);不是整數就不送、講是哪一個", () => {
  const detail = { line_rows: [line, { ...line, id: 6, product: { ...line.product, name: "保護貼" } }], missing_rows: [{ id: 3 }, { id: 4 }] };
  assert.deepEqual(approveBody(detail, {}, {}), { lines: {}, missing: {} });
  assert.deepEqual(
    approveBody(detail, { 5: { adjust: " -1 ", skipped: false, reason: " 找到一個 " }, 6: { adjust: "", skipped: true, reason: "" } },
      { 4: { skipped: true, reason: "送修中" } }),
    { lines: { 5: { adjust_qty: -1, skipped: false, reason: "找到一個" }, 6: { skipped: true, reason: "" } },
      missing: { 4: { skipped: true, reason: "送修中" } } });
  assert.deepEqual(approveBody(detail, { 5: { adjust: "+3", skipped: false, reason: "" } }, {}).lines[5], { adjust_qty: 3, skipped: false, reason: "" });
  for (const bad of ["1.5", "abc", "--1", "1e3"]) {
    assert.deepEqual(approveBody(detail, { 6: { adjust: bad, skipped: false, reason: "" } }, {}), { error: "「保護貼」的調整量要是整數" });
  }
  // 不在這張單上的編號不會被送出去
  assert.deepEqual(approveBody(detail, { 99: { adjust: "1", skipped: false, reason: "" } }, { 99: { skipped: true, reason: "" } }), { lines: {}, missing: {} });
});

test("數量那一格:0 以上的整數才算", () => {
  assert.deepEqual([countedQty("8"), countedQty(" 0 "), countedQty("12")], [8, 0, 12]);
  for (const bad of ["", "-1", "1.5", "abc", "12345678"]) assert.equal(countedQty(bad), null, bad);
});

test("頁面:帳上數量只照伺服器給的畫(沒給就沒有那幾欄)、核准要按兩下、要有這一項權限才進得來", () => {
  const page = readFileSync(new URL("../pages/inventory/StockCountPage.tsx", import.meta.url), "utf8");
  assert.ok(page.includes("detail.manager"), "管理員才有的那幾欄要看伺服器說是不是管理員");
  assert.match(page, /<ArmButton[^>]*label="核准"/);
  assert.ok(page.includes("approveBody(detail, lineEdits, missingEdits)"));
  assert.ok(page.includes("phones_done: phonesDone"), "送出時要帶「手機全部刷完了」");
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(app, /path="\/inventory\/stocktake"\s+element=\{\s*<NeedsAbility ability="stock_count" doing="盤點">\s*<StockCountsPage \/>/);
  assert.match(app, /path="\/inventory\/stocktake\/:id"\s+element=\{\s*<NeedsAbility ability="stock_count" doing="盤點">\s*<StockCountPage \/>/);
  assert.ok(!app.includes('<Placeholder title="盤點作業" />'));
  const hooks = readFileSync(new URL("../api/hooks.ts", import.meta.url), "utf8");
  assert.ok(hooks.includes('api<{ results: CountSummary[] }>("/stock-counts/")'));
  assert.ok(hooks.includes("`/stock-counts/${id}/${path}`"));
});
