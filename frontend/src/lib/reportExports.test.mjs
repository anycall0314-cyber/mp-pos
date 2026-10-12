// 各張報表「匯出」的內容,以及全站共用的那一份寫法(lib/csv.ts)。跑法:npm test。
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import test from "node:test";

import { CSV_BOM, csvCell, toCsv } from "./csv.ts";
import {
  collectPages, commissionTable, contractTable, exportFileName, exportIfComplete, exportNumber, fixedReportTable,
  stockMatrixTable, tooManyToExport,
} from "./reportExports.ts";

test("一格:長數字與開頭是 0 的號碼寫成文字,其餘照原樣", () => {
  assert.equal(csvCell("356789012345678"), '"=""356789012345678"""');     // IMEI:不然會變成 3.56E+14
  assert.equal(csvCell("0912345678"), '"=""0912345678"""');               // 手機號碼:不然開頭的 0 會不見
  assert.equal(csvCell("035550000"), '"=""035550000"""');                 // 市話
  assert.equal(csvCell("00123"), '"=""00123"""');
  assert.equal(csvCell("0"), "0");                                        // 單獨一個 0 是數字
  assert.equal(csvCell(0), "0");
  assert.equal(csvCell("0.5"), "0.5");
  assert.equal(csvCell("912345678"), "912345678");                        // 沒有開頭的 0、不到 12 位:試算表不會動
  assert.equal(csvCell("25000"), "25000");
  assert.equal(csvCell("-18320"), "-18320");
  assert.equal(csvCell("09-1234"), "09-1234");                            // 不是純數字,試算表本來就當文字
  assert.equal(csvCell("王小明, 先生"), '"王小明, 先生"');
  assert.equal(csvCell('9H "滿版"'), '"9H ""滿版"""');
  assert.equal(csvCell("a\r\nb"), '"a\r\nb"');
  assert.equal(csvCell(null), "");
  assert.equal(csvCell(undefined), "");
  assert.equal(toCsv([["門號", "金額"], ["0912345678", 300]]), '門號,金額\r\n"=""0912345678""",300');
  assert.equal(CSV_BOM, "﻿");
});

test("檔裡的數字:金額是整數、不加千分位;比率是百分比;沒有值留空白(不寫成 0)", () => {
  assert.equal(exportNumber("12345.67"), "12346");
  assert.equal(exportNumber("-18320.00"), "-18320");
  assert.equal(exportNumber(0), "0");
  assert.equal(exportNumber(7, "int"), 7);
  assert.equal(exportNumber("0.2238", "pct"), "22.4%");
  assert.equal(exportNumber(null), "");
  assert.equal(exportNumber(undefined, "int"), "");
  assert.equal(exportNumber(""), "");
});

const fixed = {
  columns: {
    dimensions: [{ key: "sales_person", label: "業務員" }],
    measures: [
      { key: "sales_orders", label: "銷貨單數", format: "int" },
      { key: "net_sales", label: "淨銷售額", format: "money" },
      { key: "net_company_commission", label: "公司佣金", format: "money" },
    ],
  },
  rows: [
    { dims: [{ label: "小陳" }], values: { sales_orders: 3, net_sales: "26151.40", net_company_commission: null } },
    { dims: [{ label: "(未指定)" }], values: { sales_orders: 1, net_sales: "-500.00", net_company_commission: "300.00" } },
  ],
  totals: { sales_orders: 4, net_sales: "25651.40", net_company_commission: "300.00" },
};

test("彙總報表:欄位照伺服器給的,最後一列是合計", () => {
  assert.deepEqual(fixedReportTable(fixed), [
    ["業務員", "銷貨單數", "淨銷售額", "公司佣金"],
    ["小陳", 3, "26151", ""],
    ["(未指定)", 1, "-500", "300"],
    ["合計", 4, "25651", "300"],
  ]);
  // 店員的資料裡沒有只給管理員的那一欄:檔裡也沒有
  const clerk = { ...fixed, columns: { ...fixed.columns, measures: fixed.columns.measures.slice(0, 2) } };
  assert.deepEqual(fixedReportTable(clerk)[0], ["業務員", "銷貨單數", "淨銷售額"]);
  assert.ok(fixedReportTable(clerk).every((row) => row.length === 3));
  assert.deepEqual(fixedReportTable({ ...fixed, rows: [] }).length, 2);
});

test("完整才存檔:超過上限就不存、回要講的話;沒超過才存", () => {
  const saved = [];
  const save = (name, table) => saved.push([name, table]);
  let built = 0;
  const table = () => { built += 1; return [["品號"], ["A"]]; };
  // 201 個商品、只拿到 200 列:不存,而且連表都不排
  const refused = exportIfComplete({ count: 200, truncated: true }, "商品排行.csv", table, save);
  assert.equal(refused, "超過 200 列,沒有匯出(不給只有一部分的檔)。請把條件縮小再匯出一次");
  assert.deepEqual([saved.length, built], [0, 0]);
  // 完整的:存一次
  assert.equal(exportIfComplete({ count: 2, truncated: false }, "商品排行.csv", table, save), "");
  assert.deepEqual(saved, [["商品排行.csv", [["品號"], ["A"]]]]);
  assert.equal(exportIfComplete({ count: 2 }, "x.csv", table, save), "");      // 伺服器沒講有沒有截短 = 沒有
  assert.equal(saved.length, 2);
});

test("超過上限不給檔:有這句話就不匯出", () => {
  assert.equal(tooManyToExport(20000, true), "超過 20000 列,沒有匯出(不給只有一部分的檔)。請把條件縮小再匯出一次");
  assert.equal(tooManyToExport(20000, false), "");
  assert.equal(tooManyToExport(12, undefined), "");
});

test("檔名:報表名稱、門市、期間;沒選門市寫全部門市;這張表沒有門市這個條件就不寫", () => {
  assert.equal(exportFileName("業績彙總", { store: "湳雅店", from: "2026-09-01", to: "2026-09-30" }), "業績彙總_湳雅店_2026-09-01_2026-09-30.csv");
  assert.equal(exportFileName("業績彙總", { store: "", from: "2026-09-01", to: "2026-09-30" }), "業績彙總_全部門市_2026-09-01_2026-09-30.csv");
  assert.equal(exportFileName("業績彙總", { store: null, from: "2026-09-01", to: "2026-09-30" }), "業績彙總_全部門市_2026-09-01_2026-09-30.csv");
  // 同一天匯出兩家店:檔名不一樣(不會互相蓋掉、分得出來)
  assert.notEqual(
    exportFileName("業績彙總", { store: "湳雅店", from: "2026-09-01", to: "2026-09-30" }),
    exportFileName("業績彙總", { store: "民生店", from: "2026-09-01", to: "2026-09-30" }),
  );
  assert.equal(exportFileName("庫存查詢", { day: "2026-10-12" }), "庫存查詢_2026-10-12.csv");
  assert.equal(exportFileName("序號查詢", { store: "民生店", day: "2026-10-12" }), "序號查詢_民生店_2026-10-12.csv");
  assert.equal(exportFileName("合約到期_待聯絡", { store: "", day: "2026-10-12" }), "合約到期_待聯絡_全部門市_2026-10-12.csv");
  assert.equal(exportFileName("進銷存表", { store: "A/B 店:一", from: "2026-10-01", to: "2026-10-12" }), "進銷存表_A-B-店-一_2026-10-01_2026-10-12.csv");
  assert.equal(exportFileName("報表"), "報表.csv");
});

const commission = {
  manager: true,
  rows: [
    { kind: "sale", date: "2026-10-09", doc_id: 9, doc_no: "SO-000009", warehouse: "湳雅店", msisdn: "0912345678",
      carrier: "中華", plan: "5G 1399", sales_person: "小陳", commission: "2000.00", company_commission: "5000.00" },
    { kind: "return", date: "2026-10-10", doc_id: 3, doc_no: "SR-000003", warehouse: "湳雅店", msisdn: "0912345678",
      carrier: "中華", plan: "5G 1399", sales_person: "小陳", commission: "-2000.00", company_commission: null },
  ],
  totals: { commission: "0.00", company_commission: "5000.00" },
};

test("佣金明細:銷退是另外一列;公司佣金那一欄只有管理員的檔裡有;門號是文字", () => {
  const table = commissionTable(commission);
  assert.deepEqual(table, [
    ["日期", "單號", "類別", "門市", "門號", "電信", "方案", "業務員", "業務員佣金", "公司佣金"],
    ["2026-10-09", "SO-000009", "銷貨", "湳雅店", "0912345678", "中華", "5G 1399", "小陳", "2000", "5000"],
    ["2026-10-10", "SR-000003", "銷退", "湳雅店", "0912345678", "中華", "5G 1399", "小陳", "-2000", ""],
    ["合計", "", "", "", "", "", "", "", "0", "5000"],
  ]);
  assert.ok(toCsv(table).includes('"=""0912345678"""'));
  const clerk = commissionTable({ ...commission, manager: false, totals: { commission: "0.00" } });
  assert.ok(!clerk[0].includes("公司佣金"));
  assert.ok(clerk.every((row) => row.length === 9));
  assert.ok(!JSON.stringify(clerk).includes("5000"));
});

test("庫存查詢:各門市一欄、總成本 = 平均成本 × 合計,最後一列合計", () => {
  const stores = [{ id: 8, name: "民生店" }, { id: 9, name: "湳雅店" }];
  const products = [
    { sku: "PH-000001", name: "iPhone 15", spec: "128GB 黑", category_name: "手機", list_price: "25000.00",
      weighted_avg_cost: "20000.50", stock_by_warehouse: { 8: 1, 9: 2 }, stock_total: 3 },
    { sku: "LC-000001", name: "皮套", spec: "", category_name: "皮套", list_price: "390.00",
      weighted_avg_cost: "95.24", stock_by_warehouse: { 9: 10 }, stock_total: 10 },
  ];
  assert.deepEqual(stockMatrixTable(stores, products), [
    ["品號", "品名", "規格", "類別", "民生店", "湳雅店", "合計", "售價", "平均成本", "總成本"],
    ["PH-000001", "iPhone 15", "128GB 黑", "手機", 1, 2, 3, "25000", "20001", "60002"],
    ["LC-000001", "皮套", "", "皮套", 0, 10, 10, "390", "95", "952"],
    // 總成本 60001.5 + 952.4 = 60953.9;平均成本 = 總成本 ÷ 合計(跟畫面最下面那一列一樣)
    ["合計", "", "", "", 1, 12, 13, "", "4689", "60954"],
  ]);
  assert.deepEqual(stockMatrixTable(stores, [])[1], ["合計", "", "", "", 0, 0, 0, "", "", "0"]);
});

test("合約到期:一位客人一列,電話與門號是文字", () => {
  const row = {
    id: 1, msisdn: "0912345678", contract_end: "2026-11-30", days_left: 49, plan_name: "5G 1399", carrier_name: "中華",
    so_no: "SO-000009", warehouse_name: "湳雅店", sales_person_name: "小陳", customer_name: "直客", customer_phone: "",
    member_name: "王小明", member_phone: "0911222333", state: "open", follow: { status: "", note: "沒人接" },
  };
  const table = contractTable([row, { ...row, state: "declined", follow: null, days_left: -3 }]);
  assert.deepEqual(table[0], ["到期日", "剩幾天", "門號", "客戶", "客戶電話", "會員", "會員電話", "電信", "方案", "門市", "業務員", "銷貨單", "狀況", "備註"]);
  assert.deepEqual(table[1], ["2026-11-30", 49, "0912345678", "直客", "", "王小明", "0911222333", "中華", "5G 1399", "湳雅店", "小陳", "SO-000009", "未聯絡", "沒人接"]);
  assert.deepEqual(table[2].slice(12), ["不續約", ""]);
  assert.equal(table[2][1], -3);
  const csv = toCsv(table);
  assert.ok(csv.includes('"=""0912345678"""') && csv.includes('"=""0911222333"""'));
});

test("要翻頁的清單:每一頁都抓、照順序接起來;超過上限就停下來講", async () => {
  const pages = { 1: { rows: ["a", "b"], next: 2 }, 2: { rows: ["c"], next: 3 }, 3: { rows: ["d"], next: null } };
  const asked = [];
  const fetchPage = async (at) => { asked.push(at); return pages[at]; };
  assert.deepEqual(await collectPages(1, fetchPage), { rows: ["a", "b", "c", "d"], truncated: false });
  assert.deepEqual(asked, [1, 2, 3]);
  const cut = await collectPages(1, fetchPage, 2);
  assert.deepEqual(cut, { rows: ["a", "b", "c"], truncated: true });
  assert.ok(tooManyToExport(cut.rows.length, cut.truncated).startsWith("超過 3 列,沒有匯出"));
  // 游標是空字串(= 最前面)也要抓第一頁
  assert.deepEqual(await collectPages("", async (at) => ({ rows: [at], next: at === "" ? "x" : null })), { rows: ["", "x"], truncated: false });
  // 中間有一頁失敗:整個失敗,不給只有一半的檔
  await assert.rejects(collectPages(1, async (at) => { if (at === 2) throw new Error("斷線"); return pages[at]; }), /斷線/);
});

test("全站的匯出都走同一份寫法:頁面裡不自己組檔、不自己處理逗號引號", () => {
  const root = new URL("../", import.meta.url);
  const files = [];
  const walk = (dir) => {
    for (const name of readdirSync(dir)) {
      const full = new URL(name + (statSync(new URL(name, dir)).isDirectory() ? "/" : ""), dir);
      if (full.pathname.endsWith("/")) walk(full);
      else if (/\.tsx?$/.test(name)) files.push(full);
    }
  };
  walk(new URL("pages/", root));
  walk(new URL("components/", root));
  // 這三個不是報表的匯出,是「下載匯入用的範本」(給人填了再匯回來,格式要照匯入那一邊讀的,不能包成文字)
  const templates = [
    "pages/purchases/PurchaseBatchPasteModal.tsx",
    "pages/products/BrandSeriesImportModal.tsx",
    "pages/products/BulkAddProductsModal.tsx",
  ];
  const own = [];
  for (const file of files) {
    const text = readFileSync(file, "utf8");
    const name = decodeURIComponent(file.pathname).split("/src/")[1];
    if (name === "components/downloadCsv.ts" || templates.includes(name)) continue;
    if (/text\/csv/.test(text)) own.push(name);
  }
  assert.deepEqual(own, [], "這幾個檔自己組了 CSV(長數字與開頭是 0 的號碼不會被保護):改用 components/downloadCsv");
});

test("七張報表都有「匯出」", () => {
  const read = (p) => readFileSync(new URL(`../${p}`, import.meta.url), "utf8");
  for (const [path, builder] of [
    ["pages/reports/FixedReportPage.tsx", "fixedReportTable(all)"],
    ["pages/reports/CommissionLinesPage.tsx", "commissionTable(data)"],
    ["pages/inventory/InventoryQueryPage.tsx", "stockMatrixTable(stores, got.rows)"],
    ["pages/telecom/ContractsPage.tsx", "contractTable(got.rows)"],
  ]) {
    const text = read(path);
    assert.ok(text.includes(builder), `${path} 沒有用 ${builder}`);
    assert.ok(/>\s*匯出\s*</.test(text), `${path} 沒有「匯出」`);
  }
  // 業績彙總 / 商品排行 / 每日彙總:匯出的是另外跟伺服器要的全部的列,不是畫面上那一份(商品排行畫面只列前 200 名)
  const fixedPage = read("pages/reports/FixedReportPage.tsx");
  assert.ok(fixedPage.includes("await fetchFixedReportAll(report.key, applied)"));
  assert.ok(!fixedPage.includes("fixedReportTable(data)"));
  assert.ok(read("api/hooks.ts").includes("rangeQuery(range)}&export=1"));
  // 要翻頁的兩張:匯出抓的是每一頁,不是畫面上那一頁的資料
  assert.ok(read("pages/inventory/InventoryQueryPage.tsx").includes("collectPages<StockMatrixProduct, number>("));
  assert.ok(read("pages/telecom/ContractsPage.tsx").includes("collectPages<ContractRow, string>("));
});

test("每一張會被截短的報表,存檔都走「完整才存檔」那一支,頁面不自己直接存", () => {
  const read = (p) => readFileSync(new URL(`../${p}`, import.meta.url), "utf8");
  for (const path of [
    "pages/reports/FixedReportPage.tsx", "pages/reports/CommissionLinesPage.tsx", "pages/reports/SalesDailyReport.tsx",
    "pages/reports/ExploreReportPage.tsx", "pages/inventory/InventoryQueryPage.tsx", "pages/inventory/StockFlowPage.tsx",
    "pages/inventory/StockMovesPage.tsx", "pages/inventory/SerialListPage.tsx", "pages/purchases/PurchaseLinesPage.tsx",
    "pages/telecom/ContractsPage.tsx",
  ]) {
    const text = read(path);
    assert.ok(text.includes("exportIfComplete("), `${path}:匯出要走 exportIfComplete`);
    // 存檔的那一支只能當成參數交給 exportIfComplete,不能在頁面裡直接呼叫(那樣就繞過「超過上限不給檔」)
    assert.ok(!/downloadCsv\(/.test(text), `${path}:不能直接呼叫 downloadCsv(`);
  }
  for (const path of ["pages/inventory/StockFlowPage.tsx", "pages/reports/CommissionLinesPage.tsx"]) {
    assert.ok(read(path).includes("|| !!tooMany}"), `${path}:超過上限時「匯出」不能按`);
  }
  // 交進去的「有沒有被截短」要是伺服器 / 抓頁的那一支講的,不能寫死
  for (const [path, wired] of [
    ["pages/reports/FixedReportPage.tsx", "truncated: all.truncated"],
    ["pages/reports/CommissionLinesPage.tsx", "truncated: data.truncated"],
    ["pages/reports/SalesDailyReport.tsx", "truncated: data?.truncated"],
    ["pages/reports/ExploreReportPage.tsx", "truncated: result.truncated"],
    ["pages/inventory/InventoryQueryPage.tsx", "truncated: got.truncated"],
    ["pages/inventory/StockFlowPage.tsx", "truncated: data.truncated"],
    ["pages/telecom/ContractsPage.tsx", "truncated: got.truncated"],
    ["pages/inventory/StockMovesPage.tsx", "exportIfComplete(all,"],
    ["pages/inventory/SerialListPage.tsx", "exportIfComplete(\n          all,"],
    ["pages/purchases/PurchaseLinesPage.tsx", "exportIfComplete(all,"],
  ]) {
    assert.ok(read(path).includes(wired), `${path}:沒有把 ${wired} 交給 exportIfComplete`);
  }
  // 合約到期:名單還不是現在要的那一份(剛打字還沒查)時不能匯出
  assert.ok(read("pages/telecom/ContractsPage.tsx").includes("|| listQ.isError || stale}"));
});

test("合約到期的整份客人名單只有管理員能匯出", () => {
  const text = readFileSync(new URL("../pages/telecom/ContractsPage.tsx", import.meta.url), "utf8");
  assert.ok(text.includes("const mayExport = isManager(useCurrentUser()?.profile?.role);"));
  assert.ok(/\{mayExport && \(\s*<button[\s\S]{0,200}匯出/.test(text));
});

test("檔名都帶門市(有門市這個條件的那幾張)", () => {
  const read = (p) => readFileSync(new URL(`../${p}`, import.meta.url), "utf8");
  for (const path of [
    "pages/reports/FixedReportPage.tsx", "pages/reports/CommissionLinesPage.tsx", "pages/reports/SalesDailyReport.tsx",
    "pages/inventory/StockFlowPage.tsx", "pages/inventory/StockMovesPage.tsx", "pages/inventory/SerialListPage.tsx",
    "pages/purchases/PurchaseLinesPage.tsx", "pages/telecom/ContractsPage.tsx",
  ]) {
    assert.ok(/exportFileName\([^)]*\{\s*store:/.test(read(path)), `${path} 的檔名沒有門市`);
  }
});
