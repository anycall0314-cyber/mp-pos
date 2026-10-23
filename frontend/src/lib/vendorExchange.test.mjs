// 瑕疵設備送廠商換貨(owner 2026-10-21「瑕疵部分照你的方法做，回來了名字改為已換貨」)。跑法:npm test。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  backAtCounter,
  codesText,
  cutText,
  defaultStore,
  EXCHANGE_TABS,
  focusAfterLook,
  qtyText,
  resultText,
  supplierGroups,
} from "./vendorExchange.ts";

const read = (p) => readFileSync(new URL(p, import.meta.url), "utf8");
const row = (over) => ({
  kind: "serial", status: "done", status_label: "已換貨", swapped: false, back_imei: "", back_sn: "",
  qty: 1, back_qty: 1, ...over,
});

test("結果怎麼寫:同一台、換成另一台、標錯了", () => {
  assert.equal(resultText(row({})), "已換貨,同一台");
  assert.equal(resultText(row({ swapped: true, back_imei: "356000000000044" })), "已換貨,換成 356000000000044");
  assert.equal(resultText(row({ status: "cancelled", status_label: "取消" })), "標錯了");
  assert.equal(codesText("", ""), "—");
  assert.equal(codesText("356", "SN1"), "356 / SN1");
});

test("配件:結果、數量那一格", () => {
  const acc = (over) => row({ kind: "product", qty: 5, back_qty: 5, ...over });
  assert.equal(resultText(acc({})), "已換貨 5 個");
  assert.equal(resultText(acc({ status: "unreturned", back_qty: 2 })), "不換了,回來 2 個、少 3 個");
  assert.equal(qtyText(acc({ status: "pending", back_qty: 2 })), "5(已回 2)");
  assert.equal(qtyText(acc({ status: "pending", back_qty: 0 })), "5");
  assert.equal(qtyText(acc({ status: "unreturned", back_qty: 2 })), "5");
});

test("廠商選單:進過的排前面,其他的還選得到;預設門市挑有貨的", () => {
  const hints = [{ id: 8, name: "第二家", last: "2026-10-21" }, { id: 7, name: "甲", last: "2026-10-01" }];
  const all = [{ id: 7, name: "甲" }, { id: 8, name: "第二家" }, { id: 9, name: "丙" }];
  const g = supplierGroups(hints, all);
  assert.deepEqual(g.hinted.map((s) => s.id), [8, 7]);
  assert.deepEqual(g.others.map((s) => s.id), [9]);
  assert.equal(defaultStore([{ id: 1, qty: 0 }, { id: 2, qty: 3 }]), 2);
  assert.equal(defaultStore([{ id: 1, qty: 0 }]), 1);
  assert.equal(defaultStore([]), "");
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
  assert.match(page, /label="不換了"/);
  assert.match(read("../nav.ts"), /\{ to: "\/inventory\/vendor-exchanges", label: "廠商換貨"/);
  assert.match(read("../App.tsx"), /<Route path="\/inventory\/vendor-exchanges" element=\{<VendorExchangesPage \/>\} \/>/);
});

test("已換貨:設備一定要刷回來的那一台(紅隊:不刷就按,換了新機帳上還是舊序號);配件填數量", () => {
  const page = read("../pages/inventory/VendorExchangesPage.tsx");
  assert.match(page, /if \(row\.kind === "serial" && !value\) return;/);
  assert.match(page, /const body = row\.kind === "serial" \? \{ code: value \} : value \? \{ qty: Number\(value\) \} : \{\};/);
  assert.match(page, /path: `\$\{row\.id\}\/done\/`, body \}/);
  assert.match(page, /placeholder=\{r\.kind === "serial" \? "刷回來的那一台" : String\(r\.qty - r\.back_qty\)\}/);
  assert.equal(page.match(/\/done\//g).length, 1, "沒有別的地方不帶碼就按已換貨");
});

test("送廠商:廠商一定要選(紅隊);不換了只給管理員、只有配件;回來過就不能標錯了", () => {
  const page = read("../pages/inventory/VendorExchangesPage.tsx");
  assert.match(page, /const ready =\s*!!found &&\s*supplier !== "" &&/);
  assert.match(page, /\{manager && r\.kind === "product" && \(/);
  assert.match(page, /\{r\.back_qty === 0 && \(/);
  // 刷到的先問伺服器是哪一台 / 哪一個配件、進過的廠商
  assert.match(page, /const hit = await lookupVendorExchange\(c\);/);
  assert.match(page, /setSupplier\(hit\.default_supplier \?\? ""\);/);
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
  assert.match(page, /\{shown === "vendor" && \(/);
  // 分頁:有換貨中的才出現(誰都看得到)
  assert.match(read("./stockCount.ts"), /\["vendor", d\.vendor_rows\?\.length \?\? 0, \(d\.vendor_rows\?\.length \?\? 0\) > 0\]/);
  assert.match(page, /<th>換貨中的序號<\/th>/);
  // 盤的人也看得到(不是只有管理員)
  assert.doesNotMatch(page, /detail\.manager && \(detail\.vendor_rows/);
});

test("刷到之後游標去哪裡:設備有廠商留在刷碼格(再按 Enter 送、刷下一台蓋掉),沒廠商去選廠商,配件去數量", () => {
  const serial = (over) => ({ kind: "serial", sendable: true, default_supplier: 3, ...over });
  assert.equal(focusAfterLook(serial({})), "code");
  assert.equal(focusAfterLook(serial({ default_supplier: null })), "supplier");
  assert.equal(focusAfterLook(serial({ sendable: false, default_supplier: null })), "code");
  assert.equal(focusAfterLook({ kind: "product", default_supplier: 3 }), "qty");
  const page = read("../pages/inventory/VendorExchangesPage.tsx");
  // 瑕疵狀況不搶游標(B7:第二台的碼曾寫進第一台的瑕疵狀況)
  assert.doesNotMatch(page, /ref=\{found\.kind === "serial" \? nextRef/);
  assert.match(page, /if \(found\?\.kind === "serial" && ready\) void send\(\);\s*else void look\(\);/);
});
