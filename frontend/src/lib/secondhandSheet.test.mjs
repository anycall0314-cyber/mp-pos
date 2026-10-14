// 中古機大量進貨的 Excel:預覽之後哪幾台能加、怎麼併成明細。跑法:npm test。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { costIn, entryOf, groupForPurchase, productOf, readyRows, sheetCounts, sheetHeader } from "./secondhandSheet.ts";

const P13 = { id: 7, name: "中古 iPhone 13 Pro 256GB 白" };
const P12 = { id: 8, name: "中古 iPhone 12 128GB 黑" };
const products = new Map([[7, P13]]);
const row = (n, extra = {}) => ({
  row: n, name: "中古 iPhone 13 Pro 256GB 白", imei: `35113556627${String(n).padStart(4, "0")}`, sn: "", grade: "B",
  battery: 85, cost: 15500, price: 18900, note: "", problems: [], product: 7, ...extra,
});

test("品號:伺服器對到的照用;對不到的要人替那個品名挑(沒挑就不能加)", () => {
  const rows = [row(2), row(3, { name: "IP12 128", product: null }), row(4, { problems: ["已經在系統裡"] })];
  assert.equal(productOf(rows[0], products, {}), P13);
  assert.equal(productOf(rows[1], products, {}), null);
  assert.equal(productOf(rows[1], products, { "IP12 128": P12 }), P12);
  assert.deepEqual(readyRows(rows, products, {}).map((r) => r.row), [2]);
  assert.deepEqual(readyRows(rows, products, { "IP12 128": P12 }).map((r) => r.row), [2, 3]);   // 有問題的那一台怎樣都不能加
  assert.deepEqual(sheetCounts(rows, products, {}), { ready: 1, bad: 1, unpicked: 1 });
});

test("一台的機況:成本放那一台自己的;售價 0 / 空的不送、電池 0 照送", () => {
  assert.deepEqual(entryOf(row(2, { note: "框掉漆" })),
    { imei: "351135566270002", sn: "", grade: "B", cost: "15500", price: "18900", battery: "85", note: "框掉漆" });
  assert.deepEqual(entryOf(row(3, { grade: "", battery: 0, price: 0, cost: 0, imei: "", sn: "SN1" })),
    { imei: "", sn: "SN1", cost: "0", battery: "0" });
});

test("同一個品號併成一行,照第一次出現的順序", () => {
  const rows = [row(2), row(3, { name: "IP12 128", product: null }), row(4), row(5, { problems: ["x"] })];
  const groups = groupForPurchase(rows, products, { "IP12 128": P12 });
  assert.deepEqual(groups.map((g) => [g.product.id, g.entries.map((e) => e.imei)]),
    [[7, ["351135566270002", "351135566270004"]], [8, ["351135566270003"]]]);
});

test("預覽第一行寫進哪家店、哪家廠商、課稅別;含稅單的成本是除 1.05 之後的", () => {
  assert.equal(sheetHeader("湳雅店", "W 中古", "應稅內含"), "湳雅店 · W 中古 · 應稅內含");
  assert.equal(sheetHeader("", "", "未稅"), "未選門市 · 未選廠商 · 未稅");
  assert.equal(costIn(10500, "taxable_included"), 10000);
  assert.deepEqual([costIn(10500, "untaxed"), costIn(10500, "taxable_excluded"), costIn(null, "untaxed")], [10500, 10500, 0]);
});

test("頁面:只在廠商收購那一頁有;要先選廠商與門市才能選檔;對不到的品名不先帶(要人自己挑)", () => {
  const page = readFileSync(new URL("../pages/purchases/PurchaseWorkbenchPage.tsx", import.meta.url), "utf8");
  const button = page.indexOf('setTool(tool === "sheet" ? null : "sheet")');
  assert.ok(button > 0 && page.lastIndexOf("{isSecondhandVendor && (", button) > page.lastIndexOf("批次貼上", button), "按鈕只在廠商收購");
  const panel = readFileSync(new URL("../pages/purchases/SecondhandSheetImport.tsx", import.meta.url), "utf8");
  assert.ok(panel.includes("disabled={!ready"), "沒選廠商、門市不能選檔");
  assert.ok(panel.includes("secondhandOnly: true"), "挑品號只列中古機");
  assert.ok(!panel.includes("resolveProducts"), "不用相似比對先帶品號");
  // 複審 P0:換了廠商,讀過的整份作廢、晚回來的不要;加入時再對一次是不是同一家廠商讀的
  assert.match(panel, /useEffect\(\(\) => \{\s*asked\.current \+= 1;\s*setPreview\(null\);[\s\S]*?\}, \[supplier\]\);/);
  assert.equal((panel.match(/if \(ticket !== asked\.current\) return;/g) ?? []).length, 2);
  assert.ok(panel.includes("if (!preview || readFor !== supplier) return;"));
  assert.ok(page.includes("serials: g.entries })),\n      false,"), "匯入的不因為那一行的單價不一樣被擋");
});
