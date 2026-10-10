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
  // 銷退單有自己的分頁(2026-10-06 起銷貨單清單併進銷貨工作台)
  assert.equal(at("/sales/returns/new"), "/sales/returns");
  assert.equal(at("/sales/returns"), "/sales/returns");
  assert.equal(at("/sales/12"), "/sales");
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
  // 商品管理與建商品用的主檔在「進貨入庫」底下(2026-10-07:建好品號的下一步就是進貨)
  assert.equal(mod("/products"), "purchasing");
  assert.equal(mod("/products/new-phone-model"), "purchasing");
  assert.equal(mod("/conditions"), "purchasing");
  assert.equal(mod("/brand-series"), "purchasing");
  assert.equal(mod("/product-types"), "purchasing");
  assert.equal(mod("/inventory"), "stock");
  assert.equal(mod("/inventory/alerts"), "stock");
  assert.equal(mod("/expenses"), "cash");
  assert.equal(mod("/reports/explore"), "reports");
  assert.equal(mod("/part-templates"), "repairs");
  assert.equal(mod("/settings/backup"), "settings");
});

test("「商品設定」選單跟著商品管理在「進貨入庫」;「商品庫存」只剩看庫存與調撥", () => {
  const byKey = (key) => NAV_MODULES.find((m) => m.key === key);
  assert.equal(byKey("purchasing").tools?.label, "商品設定");
  assert.deepEqual(
    byKey("purchasing").tools.items.map((t) => t.to),
    ["/brand-series", "/product-types", "/conditions"],
  );
  assert.equal(byKey("stock").tools, undefined);
  assert.deepEqual(byKey("stock").tabs.map((t) => t.to), ["/inventory", "/inventory/alerts", "/transfers"]);
  // 店員一樣看得到商品管理;功能搜尋打「商品管理」找得到,而且是在進貨入庫底下
  assert.ok(pagesOf(clerk).some((p) => p.to === "/products"));
  const hit = searchNav("商品管理", clerk)[0];
  assert.equal(hit.page.to, "/products");
  assert.equal(matchNav(hit.page.to, clerk).module.key, "purchasing");
  // 分頁的順序:進貨單之後就是商品管理
  assert.deepEqual(byKey("purchasing").tabs.slice(0, 2).map((t) => t.to), ["/purchases", "/products"]);
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

test("員工帳號的權限:需要的幾項都被關掉的頁面收起來,有一項就看得到", () => {
  const pages = (abilities) =>
    visibleModules({ role: "tenant_user", abilities }).flatMap((m) => [...m.tabs, ...(m.tools?.items ?? [])].map((p) => p.to));
  const all = pages(undefined);
  for (const to of ["/secondhand-acquisition", "/intake", "/reports/business-daily"]) assert.ok(all.includes(to), to);
  assert.deepEqual(pages({}), all); // 沒有講的當成可以
  assert.deepEqual(pages({ purchase: true, secondhand_buy: true, view_business_daily: true }), all);
  // 進貨匯入只看「進貨入庫」
  assert.ok(!pages({ purchase: false }).includes("/intake"));
  // 中古收購:個人收購或廠商收購(走進貨單)有一個就進得來
  assert.ok(pages({ purchase: false }).includes("/secondhand-acquisition"));
  assert.ok(pages({ secondhand_buy: false }).includes("/secondhand-acquisition"));
  assert.ok(!pages({ purchase: false, secondhand_buy: false }).includes("/secondhand-acquisition"));
  // 營業日報
  assert.ok(!pages({ view_business_daily: false }).includes("/reports/business-daily"));
  // 別的頁不受影響
  const off = pages({ purchase: false, secondhand_buy: false, view_business_daily: false, edit_products: false, cash_ops: false });
  for (const to of ["/sales", "/purchases", "/products", "/inventory", "/expenses", "/cash-adjustments"]) assert.ok(off.includes(to), to);
});

test("入口的預設頁被收起來時,點入口去第一個看得到的頁", () => {
  const cash = (abilities) => visibleModules({ role: "tenant_user", abilities }).find((m) => m.tabs.some((p) => p.to === "/expenses"));
  assert.equal(cash(undefined).to, "/reports/business-daily");
  assert.equal(cash({ view_business_daily: false }).to, "/expenses");
  // 管理員頁照舊:店員看不到、管理員看得到
  const settings = (role) => visibleModules({ role }).find((m) => m.key === "settings").tabs.map((p) => p.to);
  assert.ok(!settings("tenant_user").includes("/settings/users"));
  assert.ok(settings("tenant_admin").includes("/settings/users"));
});

