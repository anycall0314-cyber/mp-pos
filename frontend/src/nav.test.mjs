// 導覽設定的規則。跑法:npm test(Node 22.6 以上,直接讀 .ts)。
import assert from "node:assert/strict";
import test from "node:test";

import {
  matchForUser,
  matchNav,
  NAV_MODULES,
  searchNav,
  visibleModules,
} from "./nav.ts";

const admin = visibleModules({ role: "tenant_admin" });
const clerk = visibleModules({ role: "tenant_user" });
const platform = visibleModules({ role: "platform_admin" });
const pagesOf = (mods) =>
  mods.flatMap((m) => [...m.tabs, ...(m.tools?.items ?? [])]);

// 改版前側邊欄的 32 個入口:一條都不能從新導覽消失
const LEGACY = [
  "/home", "/sales", "/purchases", "/inventory", "/repairs", "/telecom/billing",
  "/reports/business-daily", "/products", "/secondhand-acquisition", "/customers",
  "/members", "/suppliers", "/sales-persons", "/brand-series", "/product-types",
  "/conditions", "/part-templates", "/telecom-plans", "/sim-cards", "/repairs/items",
  "/intake", "/inventory/alerts", "/transfers", "/reports/sales-daily",
  "/reports/explore", "/reports/parts-usage", "/expenses", "/cash-adjustments",
  "/settings", "/settings/backup", "/settings/legacy", "/settings/ledger",
];

test("改版前的 32 個入口在新導覽都找得到", () => {
  const have = new Set(pagesOf(admin).map((p) => p.to));
  assert.equal(LEGACY.length, 32);
  for (const to of LEGACY) assert.ok(have.has(to), `少了 ${to}`);
});

test("同一個網址不會掛在兩個地方", () => {
  const all = pagesOf(NAV_MODULES).map((p) => p.to);
  assert.equal(new Set(all).size, all.length);
});

test("每個入口點下去就是它的第一個分頁", () => {
  for (const m of NAV_MODULES) assert.equal(m.to, m.tabs[0].to, m.label);
});

test("側邊欄的入口名稱一律 4 個字", () => {
  for (const m of NAV_MODULES) assert.equal([...m.label].length, 4, m.label);
});

test("側邊欄:9 個主要入口 + 底部的系統設定", () => {
  assert.equal(admin.filter((m) => !m.bottom).length, 9);
  assert.deepEqual(admin.filter((m) => m.bottom).map((m) => m.key), ["settings"]);
});

test("目前這一頁只有一個:取網址對得上、而且最長的那一頁", () => {
  const at = (path) => matchNav(path, admin)?.page.to;
  assert.equal(at("/settings"), "/settings");
  assert.equal(at("/settings/ledger"), "/settings/ledger");
  assert.equal(at("/repairs"), "/repairs");
  assert.equal(at("/repairs/items"), "/repairs/items");
  assert.equal(at("/repairs/12"), "/repairs");
  assert.equal(at("/inventory/alerts"), "/inventory/alerts");
  assert.equal(at("/sales/new"), "/sales");
  assert.equal(at("/sales/returns/new"), "/sales");
  assert.equal(at("/sales-persons"), "/sales-persons");
  assert.equal(at("/purchases/5"), "/purchases");
  assert.equal(at("/transfers/12"), "/transfers");
  assert.equal(at("/reports/business-daily"), "/reports/business-daily");
  assert.equal(matchNav("/no-such-page", admin), null);
});

test("網址屬於哪個入口", () => {
  const mod = (path) => matchNav(path, admin)?.module.key;
  assert.equal(mod("/transfers"), "stock");
  assert.equal(mod("/secondhand-acquisition"), "purchasing");
  assert.equal(mod("/expenses"), "cash");
  assert.equal(mod("/reports/explore"), "reports");
  assert.equal(mod("/part-templates"), "repairs");
  assert.equal(mod("/settings/backup"), "settings");
});

test("只給管理員的頁面,店員的導覽裡沒有", () => {
  const tos = pagesOf(clerk).map((p) => p.to);
  for (const to of ["/settings/backup", "/settings/legacy", "/settings/ledger"]) {
    assert.ok(!tos.includes(to), to);
  }
  assert.ok(tos.includes("/settings"));
});

test("店員直接打管理員頁面的網址:導覽什麼都不亮(不退回去標成業務設定)", () => {
  const who = { role: "tenant_user" };
  assert.equal(matchForUser("/settings/ledger", who), null);
  assert.equal(matchForUser("/settings/backup", who), null);
  assert.equal(matchForUser("/settings", who)?.page.to, "/settings");
  assert.equal(matchForUser("/platform/admin", who), null);
  // 管理員照常
  assert.equal(
    matchForUser("/settings/ledger", { role: "tenant_admin" })?.page.to,
    "/settings/ledger",
  );
});

test("平台管理只有平台管理員看得到", () => {
  assert.ok(!admin.some((m) => m.key === "platform"));
  assert.ok(platform.some((m) => m.key === "platform"));
});

test("功能搜尋:打舊名字找得到新入口", () => {
  const first = (q) => searchNav(q, admin)[0]?.page.to;
  assert.equal(first("建立商品"), "/products");
  assert.equal(first("自由組合"), "/reports/explore");
  assert.equal(first("待確認入庫"), "/intake");
  assert.equal(first("中古入庫"), "/secondhand-acquisition");
  assert.equal(first("方案管理"), "/telecom-plans");
  assert.equal(first("卡片管理"), "/sim-cards");
  assert.equal(first("發票"), "/settings");
  assert.equal(first("首頁"), "/home");
  assert.equal(searchNav("建立商品", admin)[0].via, "建立商品");
  assert.deepEqual(searchNav("   ", admin), []);
  assert.deepEqual(searchNav("沒有這個功能", admin), []);
});

test("功能搜尋:找不到別人看不到的頁面", () => {
  assert.equal(searchNav("備份", clerk).length, 0);
  assert.equal(searchNav("備份", admin)[0].page.to, "/settings/backup");
});

test("功能搜尋:打「入庫」先到進貨單,不是中古收購", () => {
  // 入口叫「進貨入庫」→ 排它的預設頁;舊名字「中古入庫」「待確認入庫」排後面
  const hits = searchNav("入庫", admin).map((h) => h.page.to);
  assert.equal(hits[0], "/purchases");
  assert.ok(hits.includes("/secondhand-acquisition"));
  assert.ok(hits.includes("/intake"));
});

test("營業日報不在名字帶「報表」的入口底下", () => {
  const daily = matchNav("/reports/business-daily", admin);
  assert.equal(daily.module.key, "cash");
  for (const m of NAV_MODULES) {
    if (m.key !== "cash") assert.ok(!m.label.includes("報表"), m.label);
  }
});

test("功能搜尋:名稱開頭對上的排前面", () => {
  const hits = searchNav("銷貨", admin).map((h) => h.page.to);
  assert.equal(hits[0], "/sales");
  assert.ok(hits.includes("/reports/sales-daily"));
});
