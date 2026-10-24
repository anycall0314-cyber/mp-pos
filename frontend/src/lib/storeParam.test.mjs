// 首頁選的門市帶到待辦 / 注意那幾張清單(全站檢視 R06)。跑法:npm test。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { noticeGroups, todoGroups } from "./homeTodo.ts";
import { STORE_PARAM, storeCheck, storeIdFrom, withStore } from "./storeParam.ts";

const STORES = [
  { id: 1, name: "湳雅店", is_active: true },
  { id: 2, name: "民生店", is_active: true },
  { id: 3, name: "舊店", is_active: false },
];

test("網址上的門市:正整數才算;門市清單回來前先照網址查,回來後沒有 / 停用的不認", () => {
  assert.equal(STORE_PARAM, "warehouse");
  assert.equal(storeIdFrom("2"), 2);
  for (const bad of [null, "", "abc", "0", "-1", "1.5", "2x"]) assert.equal(storeIdFrom(bad), null, String(bad));
  assert.deepEqual(storeCheck(null, STORES), { id: null, name: "", state: "none" });
  assert.deepEqual(storeCheck(2, undefined), { id: 2, name: "", state: "pending" });
  assert.deepEqual(storeCheck(2, STORES), { id: 2, name: "民生店", state: "ok" });
  assert.deepEqual(storeCheck(999, STORES), { id: null, name: "", state: "gone" });
  assert.deepEqual(storeCheck(3, STORES), { id: null, name: "", state: "gone" });
});

test("鎖在門市的帳號(照帳號鎖店的頁):網址寫別家當沒帶,寫自己那家照常", () => {
  assert.deepEqual(storeCheck(2, STORES, 1), { id: null, name: "", state: "gone" });
  assert.deepEqual(storeCheck(1, STORES, 1), { id: 1, name: "湳雅店", state: "ok" });
  assert.deepEqual(storeCheck(2, undefined, 1).state, "gone"); // 不用等門市清單
});

test("首頁的連結:全公司不帶;選了一家整組帶過去;已經有條件的接在後面", () => {
  assert.equal(withStore("/inventory/alerts", null), "/inventory/alerts");
  assert.equal(withStore("/inventory/alerts", 2), "/inventory/alerts?warehouse=2");
  assert.equal(withStore("/repairs?overdue=1", 2), "/repairs?overdue=1&warehouse=2");
});

const SUMMARY = {
  returns_pending: 1,
  contracts_pending: 2,
  intake_open: 1,
  counts_pending: 1,
  transfers_pending: { count: 1, items: [{ id: 6, no: "TR-6", from_name: "民生店", to_name: "湳雅店", days: 0 }] },
  low_stock: { count: 1, items: [{ id: 9, name: "皮套", qty: 0 }] },
  repair_alerts: {
    overdue_repairs: { count: 1, items: [] },
    overdue_external: { count: 1, items: [] },
    pickup: { count: 2, items: [{ id: 5, no: "R-5", customer_name: "王", host_model_name: "X", ready_days: 1 }] },
  },
};
const BOSS = { role: "tenant_admin", abilities: null };

test("待辦 / 注意整組的連結帶著那一家;單筆照舊開那一筆;匯入待確認不帶(那一頁沒有門市條件)", () => {
  const todo = Object.fromEntries(todoGroups(SUMMARY, BOSS, 2).map((g) => [g.key, g]));
  assert.equal(todo.transfers.to, "/transfers?pending=1&warehouse=2");
  assert.equal(todo.pickup.to, "/repairs?status=ready_pickup&warehouse=2");
  assert.equal(todo.returns.to, "/serials?status=returned&warehouse=2");
  assert.equal(todo.counts.to, "/inventory/stocktake?status=submitted&warehouse=2");
  assert.equal(todo.intake.to, "/intake");
  assert.equal(todo.transfers.items[0].to, "/transfers/6");
  assert.equal(todo.pickup.items[0].to, "/repairs/5");
  const notice = Object.fromEntries(noticeGroups(SUMMARY, BOSS, 2).map((g) => [g.key, g]));
  assert.equal(notice.overdue.to, "/repairs?overdue=1&warehouse=2");
  assert.equal(notice.external.to, "/repairs?overdue=external&warehouse=2");
  assert.equal(notice.contracts.to, "/telecom/expiries?warehouse=2");
  assert.equal(notice.low.to, "/inventory/alerts?warehouse=2");
  assert.equal(notice.low.items[0].to, "/inventory/alerts?warehouse=2");
  // 全公司:跟以前一樣
  const all = Object.fromEntries(todoGroups(SUMMARY, BOSS).map((g) => [g.key, g]));
  assert.equal(all.transfers.to, "/transfers?pending=1");
  assert.equal(noticeGroups(SUMMARY, BOSS, null).find((g) => g.key === "low").to, "/inventory/alerts");
});

const read = (p) => readFileSync(new URL(p, import.meta.url), "utf8");

test("目的頁真的照那一家查(不是只改網址)", () => {
  const home = read("../pages/home/HomePage.tsx");
  assert.match(home, /const linkStore = locked \? \(user\?\.profile\?\.default_warehouse_id \?\? null\) : store;/);
  assert.match(home, /todoGroups\(summary\.data, who, linkStore\)/);
  assert.match(home, /noticeGroups\(summary\.data, who, linkStore\)/);
  const transfers = read("../pages/transfers/TransferWorkbenchPage.tsx");
  assert.equal(transfers.match(/to_warehouse: toStore\.id/g)?.length, 2); // 清單與待入庫的張數
  assert.match(read("../pages/repairs/RepairsPage.tsx"), /warehouse: store\.id,/);
  assert.match(read("../pages/inventory/InventoryAlertsPage.tsx"), /useInventoryAlerts\(store\.id\)/);
  assert.match(read("../pages/inventory/StockCountsPage.tsx"), /listStore\.id === null \|\| c\.warehouse\.id === listStore\.id/);
  const serials = read("../pages/inventory/SerialListPage.tsx");
  assert.match(serials, /useStoreParam\(\{ lockable: false \}\)/);
  assert.match(serials, /warehouse: startStore \?\? "",/);
  assert.match(read("../pages/telecom/ContractsPage.tsx"), /useState<number \| "">\(startStore \?\? ""\)/);
  const hooks = read("../api/hooks.ts");
  assert.match(hooks, /if \(params\?\.to_warehouse\) qs\.set\("to_warehouse", String\(params\.to_warehouse\)\);/);
  assert.match(hooks, /if \(params\?\.warehouse\) q\.set\("warehouse", String\(params\.warehouse\)\);/);
  assert.match(hooks, /queryKey: \["inventory-alerts", warehouse \?\? null\]/);
});
