// 盤點在畫面這一側:每一格怎麼寫、核准時送什麼。跑法:npm test。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  amountCards, approveBody, assignProduct, countedQty, extraText, missingText, movedHint, newEditOf, newGroups, newResult,
  oldStoresText, plainAmount, progressText, scopeText, signed,
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
  assert.deepEqual(approveBody(detail, {}, {}), { lines: {}, missing: {}, extras: {} });
  assert.deepEqual(
    approveBody(detail, { 5: { adjust: " -1 ", skipped: false, reason: " 找到一個 " }, 6: { adjust: "", skipped: true, reason: "" } },
      { 4: { skipped: true, reason: "送修中" } }),
    { lines: { 5: { adjust_qty: -1, skipped: false, reason: "找到一個" }, 6: { skipped: true, reason: "" } },
      missing: { 4: { skipped: true, reason: "送修中" } }, extras: {} });
  assert.deepEqual(approveBody(detail, { 5: { adjust: "+3", skipped: false, reason: "" } }, {}).lines[5], { adjust_qty: 3, skipped: false, reason: "" });
  for (const bad of ["1.5", "abc", "--1", "1e3"]) {
    assert.deepEqual(approveBody(detail, { 6: { adjust: bad, skipped: false, reason: "" } }, {}), { error: "「保護貼」的調整量要是整數" });
  }
  // 不在這張單上的編號不會被送出去
  assert.deepEqual(approveBody(detail, { 99: { adjust: "1", skipped: false, reason: "" } }, { 99: { skipped: true, reason: "" } }), { lines: {}, missing: {}, extras: {} });
});

const A17 = { id: 31, sku: "PH-000031", name: "Galaxy A17 6/128 黑", unit: false };
const USED = { id: 32, sku: "SC-000001", name: "中古 iPhone 13 Pro 256GB", unit: true };
const newRow = (id, extra = {}) => ({
  id, code: `35600000000001${id}`, old_code: "0004A176001W3", old_name: "手機/三星-A17 6/128逆襲黑", group: "手機/三星-A17 6/128逆襲黑",
  old_cost: "7050.00", old_price: "8990.00", product: null, unit_cost: null, unit_price: null, skipped: false, reason: "", added: false, ...extra,
});

test("第一次入庫:沒動過的那一台帶舊系統的成本與售價、先帶出來的品號;金額整數不帶 .00", () => {
  assert.deepEqual(newEditOf(newRow(1), {}), { product: null, cost: "7050", price: "8990", skipped: false, reason: "" });
  assert.deepEqual(newEditOf(newRow(2, { product: A17, old_cost: "95.24", old_price: null }), {}),
    { product: A17, cost: "95.24", price: "", skipped: false, reason: "" });
  assert.deepEqual([plainAmount("7050.00"), plainAmount("95.20"), plainAmount(null)], ["7050", "95.20", ""]);
});

test("第一次入庫:照舊品名分組、照出現的順序;舊系統沒有的另外一組", () => {
  const rows = [newRow(1), newRow(2, { group: "中古/IP13P/256G" }), newRow(3), newRow(4, { group: "" })];
  assert.deepEqual(newGroups(rows).map((g) => [g.label, g.rows.map((r) => r.id)]),
    [["手機/三星-A17 6/128逆襲黑", [1, 3]], ["中古/IP13P/256G", [2]], ["舊系統沒有", [4]]]);
});

test("第一次入庫:勾著的換成同一個品號;不是逐台記售價的品號售價清掉;沒勾的不動", () => {
  const rows = [newRow(1), newRow(2), newRow(3)];
  let edits = assignProduct(rows, new Set([1, 2]), USED, {});
  assert.deepEqual([edits[1].product, edits[1].price, edits[3]], [USED, "8990", undefined]);
  edits = assignProduct(rows, new Set([2]), A17, { ...edits, 2: { ...edits[2], skipped: true } });
  assert.deepEqual([edits[2].product, edits[2].price, edits[2].skipped, edits[1].product], [A17, "", false, USED]);
});

test("第一次入庫核准送的:有品號的入、沒品號或勾不入的送不入;成本一定要、售價只送逐台記的", () => {
  const detail = { line_rows: [], missing_rows: [], new_rows: [newRow(1, { product: A17 }), newRow(2), newRow(3, { product: USED })] };
  assert.deepEqual(approveBody(detail, {}, {}, { 3: { product: USED, cost: "15,500", price: "18900", skipped: false, reason: "" } }).extras, {
    1: { product: 31, unit_cost: "7050", reason: "" },
    2: { skipped: true, reason: "" },
    3: { product: 32, unit_cost: "15500", unit_price: "18900", reason: "" },
  });
  const skip = approveBody(detail, {}, {}, { 1: { product: A17, cost: "7050", price: "", skipped: true, reason: " 樣品 " } });
  assert.deepEqual(skip.extras[1], { skipped: true, reason: "樣品" });
  for (const bad of ["", "abc", "-1", "1.234"]) {
    assert.deepEqual(approveBody(detail, {}, {}, { 1: { product: A17, cost: bad, price: "", skipped: false, reason: "" } }),
      { error: `${detail.new_rows[0].code} 的成本要填(沒有就填 0)` }, bad);
  }
  assert.deepEqual(approveBody(detail, {}, {}, { 3: { product: USED, cost: "1", price: "x", skipped: false, reason: "" } }),
    { error: `${detail.new_rows[2].code} 的售價要是數字` });
  assert.deepEqual([newResult({ added: true, skipped: false }), newResult({ added: false, skipped: true })], ["已入", "不入"]);
});

test("還沒入庫那一行:各家舊店幾台", () => {
  assert.equal(oldStoresText({ stores: [{ store: "湳雅店", count: 3 }, { store: "民生店", count: 1 }] }), "湳雅店 3　民生店 1");
  const page = readFileSync(new URL("../pages/inventory/StockCountsPage.tsx", import.meta.url), "utf8");
  assert.ok(page.includes("useOldUnitsLeft(manager)"), "只有管理員發這個請求");
});

test("數量那一格:0 以上的整數才算", () => {
  assert.deepEqual([countedQty("8"), countedQty(" 0 "), countedQty("12")], [8, 0, 12]);
  for (const bad of ["", "-1", "1.5", "abc", "12345678"]) assert.equal(countedQty(bad), null, bad);
});

test("頁面:帳上數量只照伺服器給的畫(沒給就沒有那幾欄)、核准要按兩下、要有這一項權限才進得來", () => {
  const page = readFileSync(new URL("../pages/inventory/StockCountPage.tsx", import.meta.url), "utf8");
  assert.ok(page.includes("detail.manager"), "管理員才有的那幾欄要看伺服器說是不是管理員");
  assert.match(page, /<ArmButton[^>]*label="核准"/);
  assert.ok(page.includes("approveBody(detail, lineEdits, missingEdits, newEdits)"));
  assert.ok(page.includes("o.payload?.requires_serial"), "指定的品號只列一台一個碼的商品");
  assert.ok(page.includes("phones_done: phonesDone"), "送出時要帶「手機全部刷完了」");
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(app, /path="\/inventory\/stocktake"\s+element=\{\s*<NeedsAbility ability="stock_count" doing="盤點">\s*<StockCountsPage \/>/);
  assert.match(app, /path="\/inventory\/stocktake\/:id"\s+element=\{\s*<NeedsAbility ability="stock_count" doing="盤點">\s*<StockCountPage \/>/);
  assert.ok(!app.includes('<Placeholder title="盤點作業" />'));
  const hooks = readFileSync(new URL("../api/hooks.ts", import.meta.url), "utf8");
  assert.ok(hooks.includes('api<{ results: CountSummary[] }>("/stock-counts/")'));
  assert.ok(hooks.includes("`/stock-counts/${id}/${path}`"));
});
