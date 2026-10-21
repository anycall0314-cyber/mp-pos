// 瑕疵設備送廠商換貨(owner 2026-10-21「瑕疵部分照你的方法做，回來了名字改為已換貨」)。跑法:npm test。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { backAtCounter, codesText, cutText, EXCHANGE_TABS, resultText } from "./vendorExchange.ts";

const read = (p) => readFileSync(new URL(p, import.meta.url), "utf8");
const row = (over) => ({
  status: "done", status_label: "已換貨", swapped: false, back_imei: "", back_sn: "", ...over,
});

test("結果怎麼寫:同一台、換成另一台、標錯了", () => {
  assert.equal(resultText(row({})), "已換貨,同一台");
  assert.equal(resultText(row({ swapped: true, back_imei: "356000000000044" })), "已換貨,換成 356000000000044");
  assert.equal(resultText(row({ status: "cancelled", status_label: "取消" })), "標錯了");
  assert.equal(codesText("", ""), "—");
  assert.equal(codesText("356", "SN1"), "356 / SN1");
});

test("處理過的只列最近幾筆時講一句", () => {
  assert.equal(cutText({ results: [{}], count: 1, limit: 200 }), "");
  assert.equal(cutText({ results: [{}], count: 201, limit: 200 }), "只列最近 200 筆");
  assert.equal(cutText(undefined), "");
});

test("開單刷到的:換貨中、而且在這個出貨倉才給「已換貨」", () => {
  assert.equal(backAtCounter({ status: "rma", warehouse: 1 }, 1), true);
  assert.equal(backAtCounter({ status: "rma", warehouse: 2 }, 1), false);   // 別家門市的
  assert.equal(backAtCounter({ status: "in_stock", warehouse: 1 }, 1), false);
  assert.equal(backAtCounter({ status: "sold", warehouse: null }, 1), false);
});

test("分頁與按鈕字數一樣;入口在商品庫存那一排", () => {
  assert.deepEqual(EXCHANGE_TABS.map((t) => t.label.length), [3, 3]);
  const page = read("../pages/inventory/VendorExchangesPage.tsx");
  assert.match(page, />\s*已換貨\s*</);
  assert.match(page, /label="標錯了"/);
  assert.match(read("../nav.ts"), /\{ to: "\/inventory\/vendor-exchanges", label: "廠商換貨"/);
  assert.match(read("../App.tsx"), /<Route path="\/inventory\/vendor-exchanges" element=\{<VendorExchangesPage \/>\} \/>/);
});

test("已換貨一定要刷回來的那一台(紅隊:不刷就按,換了新機帳上還是舊序號)", () => {
  const page = read("../pages/inventory/VendorExchangesPage.tsx");
  assert.match(page, /if \(!backCode\.trim\(\) \|\| run\.isPending\) return;/);
  assert.match(page, /path: `\$\{row\.id\}\/done\/`, body: \{ code: backCode\.trim\(\) \}/);
  assert.match(page, /placeholder="刷回來的那一台"/);
  assert.equal(page.match(/\/done\//g).length, 1, "沒有別的地方不帶碼就按已換貨");
});

test("開單刷到換貨中的那一台:先講、旁邊「已換貨」,按了才加進明細", () => {
  const wb = read("../pages/sales/SalesWorkbenchPage.tsx");
  const scan = wb.slice(wb.indexOf("async function onScan("), wb.indexOf("function removeLine("));
  // 換貨中的那一句要在「不能在這裡賣」之前,不然會被那一句攔走
  assert.ok(scan.indexOf("backAtCounter(device, at)") > 0);
  assert.ok(scan.indexOf("backAtCounter(device, at)") < scan.indexOf('device.status !== "in_stock"'));
  assert.match(scan, /action: \{ label: "已換貨", fn: \(\) => void exchangeBack\(device\.id, code\) \}/);
  assert.match(scan, /return "這一台廠商換貨中";/);
  // 伺服器確認刷的碼是這一台、回到在庫之後,照剛刷的再加一次;「沒加入」那一筆劃掉
  assert.match(scan, /exchange\.mutateAsync\(\{ path: "done-serial\/", body: \{ serial: serialId, code \} \}\)/);
  assert.match(scan, /const verdict = await onScan\(code\);\s*if \(verdict === true\) \{\s*scanApi\.current\?\.added\(code, null\);/);
});

test("盤點單列出這家門市換貨中的(不用刷,但不會從表上消失)", () => {
  const page = read("../pages/inventory/StockCountPage.tsx");
  assert.match(page, /\{\(detail\.vendor_rows\?\.length \?\? 0\) > 0 && \(/);
  assert.match(page, /<th>換貨中的序號<\/th>/);
  // 盤的人也看得到(不是只有管理員)
  assert.doesNotMatch(page, /detail\.manager && \(detail\.vendor_rows/);
});
