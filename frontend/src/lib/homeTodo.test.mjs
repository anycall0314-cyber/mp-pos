// 今日總覽的快捷與待辦(2026-10-23,UI 改善計劃 6.1)。跑法:npm test。
import assert from "node:assert/strict";
import test from "node:test";

import { noticeGroups, pickStore, quickActions, QUICK_ACTIONS, todoGroups } from "./homeTodo.ts";

const clerk = { role: "tenant_user", abilities: {} };
const boss = { role: "tenant_admin", abilities: {} };

const summary = {
  returns_pending: 2,
  contracts_pending: 0,
  intake_open: 1,
  counts_pending: 3,
  transfers_pending: {
    count: 5,
    items: [1, 2, 3, 4].map((i) => ({ id: i, no: `TR-00000${i}`, from_name: "民生店", to_name: "湳雅店", days: i - 1 })),
  },
  low_stock: { count: 12, items: [{ id: 9, name: "皮套", qty: 1 }] },
  repair_alerts: {
    overdue_repairs: { count: 0, items: [] },
    overdue_external: { count: 1, items: [{ id: 7, no: "R-7", customer_name: "王", vendor_name: "外廠", overdue_days: 2 }] },
    pickup: { count: 2, items: [{ id: 5, no: "R-5", customer_name: "", host_model_name: "iPhone 15", ready_days: 0 }] },
  },
};

test("快捷:名字是動作、字數一樣;看不到那一頁的收起來", () => {
  assert.equal(new Set(QUICK_ACTIONS.map((a) => a.label.length)).size, 1);
  assert.deepEqual(quickActions(clerk).map((a) => a.label), ["開銷貨單", "代收話費", "查詢庫存", "維修收件"]);
  for (const a of QUICK_ACTIONS) assert.ok(!a.label.endsWith("作業"), a.label);   // 不跟側邊欄同名
});

test("待辦:數字 0 的不列、明細最多三筆、每一組點了帶條件", () => {
  const g = todoGroups(summary, clerk);
  assert.deepEqual(g.map((x) => x.key), ["transfers", "pickup", "returns", "intake"]);
  assert.equal(g[0].items.length, 3);
  assert.equal(g[0].to, "/transfers?pending=1");
  assert.equal(g[0].items[0].sub, undefined);           // 今天才寄的不寫天數
  assert.equal(g[0].items[1].sub, "1 天");
  assert.equal(g[0].items[0].title, "TR-000001 · 民生店 → 湳雅店");
  assert.equal(g[1].to, "/repairs?status=ready_pickup");
  assert.equal(g[1].items[0].title, "R-5 · iPhone 15");  // 沒有會員名字寫單號
  assert.equal(g[2].to, "/serials?status=returned");
  assert.equal(new Set(g.map((x) => x.label.length)).size, 1);
});

test("盤點待核准只給管理員;關掉進貨入庫的看不到匯入待確認", () => {
  assert.equal(todoGroups(summary, boss).find((x) => x.key === "counts")?.to, "/inventory/stocktake?status=submitted");
  assert.ok(!todoGroups(summary, clerk).some((x) => x.key === "counts"));
  const noPurchase = { role: "tenant_user", abilities: { purchase: false } };
  assert.ok(!todoGroups(summary, noPurchase).some((x) => x.key === "intake"));
});

test("注意:跟待辦分開,0 的不列", () => {
  const g = noticeGroups(summary, clerk);
  assert.deepEqual(g.map((x) => x.key), ["external", "low"]);
  assert.equal(g[0].items[0].sub, "逾期 2 天");
  assert.equal(g[0].to, "/repairs?overdue=external");
  const noVendor = noticeGroups({ repair_alerts: { overdue_external: { count: 1, items: [{ id: 1, no: "R-1", customer_name: "", vendor_name: "", overdue_days: 1 }] } } }, clerk);
  assert.equal(noVendor[0].items[0].title, "R-1");                // 沒填廠商不留「R-1 · 」
  assert.equal(new Set(noticeGroups({ ...summary, contracts_pending: 1, repair_alerts: { ...summary.repair_alerts, overdue_repairs: { count: 1, items: [] } } }, clerk).map((x) => x.label.length)).size, 1);
});

test("還沒拿到資料:什麼都不列", () => {
  assert.deepEqual(todoGroups(undefined, clerk), []);
  assert.deepEqual(noticeGroups(undefined, clerk), []);
});

test("首頁選的門市:看不懂、已經沒有的當成全公司", () => {
  assert.equal(pickStore("3", [1, 3]), 3);
  assert.equal(pickStore("2", [1, 3]), null);
  assert.equal(pickStore("abc", [1, 3]), null);
  assert.equal(pickStore(null, [1, 3]), null);
  assert.equal(pickStore("1.5", [1, 3]), null);
});
