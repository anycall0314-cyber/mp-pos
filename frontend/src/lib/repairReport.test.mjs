// 維修月報在畫面這一側:條件怎麼變成網址、標題底下那一排、匯出的檔。跑法:npm test。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { PEOPLE_HEAD, REPAIR_HEAD, repairCards, repairQuery, repairTable, wayLabel } from "./repairReport.ts";
import { PAGE_SIZE } from "./stockReports.ts";

const filter = { from: "2026-09-01", to: "2026-09-30", warehouse: "", way: "" };
const ways = [{ key: "in_house", label: "自修" }, { key: "vendor", label: "委外" }, { key: "transfer", label: "內轉" }];
const row = {
  id: 7, date: "2026-09-06", doc: { kind: "repair", id: 7, no: "RO-000007" }, store: "民生店", model: "iPhone 15",
  way: "in_house", receiver: "王小明", technician: "李師傅", paid: "2000.00", parts: "400.00", outside: "0.00", margin: "1600.00",
};
const people = [
  { id: 1, name: "王小明", received: 4, repaired: 1, amount: "6200.00" },
  { id: 2, name: "李師傅", received: 0, repaired: 2, amount: "2700.00" },
];

test("網址:空的條件不送;看畫面用頁碼,匯出要全部", () => {
  assert.equal(repairQuery(filter, 1), `from=2026-09-01&to=2026-09-30&page=1&page_size=${PAGE_SIZE}`);
  assert.equal(repairQuery({ ...filter, warehouse: 8, way: "transfer" }, "export"),
    "from=2026-09-01&to=2026-09-30&warehouse=8&way=transfer&export=1");
  assert.ok(!repairQuery(filter, 2).includes("way"));
});

test("方式的字是伺服器給的;清單還沒到就先照代碼", () => {
  assert.equal(wayLabel(ways, "transfer"), "內轉");
  assert.equal(wayLabel(undefined, "transfer"), "transfer");
  assert.equal(wayLabel(ways, "gone"), "gone");
});

test("標題底下那一排:件數、實付、成本、委外、毛利(字數一樣)", () => {
  const totals = { count: 5, paid: "15000.00", parts: "1600.00", outside: "3500.00", margin: "9900.00" };
  assert.deepEqual(repairCards(totals), [
    { label: "件數", value: "5" },
    { label: "實付", value: "15,000" },
    { label: "成本", value: "1,600" },
    { label: "委外", value: "3,500" },
    { label: "毛利", value: "9,900" },
  ]);
  assert.deepEqual([...new Set(repairCards(totals).map((c) => c.label.length))], [2]);
  // 成本與委外各是各的(放反了看得出來)
  assert.equal(repairCards({ ...totals, parts: "1.00", outside: "2.00" })[2].value, "1");
  assert.equal(repairCards({ ...totals, parts: "1.00", outside: "2.00" })[3].value, "2");
});

test("匯出:上面是每個人分到多少,空一行,下面是逐筆;金額不加千分位、方式寫字", () => {
  const table = repairTable({ results: [row, { ...row, id: 8, way: "vendor", technician: "", parts: "0.00", outside: "3500.00", margin: "-1500.00" }], people, choices: { way: ways } });
  assert.deepEqual(table[0], PEOPLE_HEAD);
  assert.deepEqual(table[1], ["王小明", 4, 1, "6200"]);
  assert.deepEqual(table[2], ["李師傅", 0, 2, "2700"]);
  assert.deepEqual(table[3], []);
  assert.deepEqual(table[4], REPAIR_HEAD);
  assert.deepEqual(table[5], ["2026-09-06", "RO-000007", "民生店", "iPhone 15", "自修", "王小明", "李師傅", "2000", "400", "0", "1600"]);
  assert.deepEqual(table[6].slice(4), ["委外", "王小明", "", "2000", "0", "3500", "-1500"]);
  assert.equal(table.slice(4).every((line) => line.length === REPAIR_HEAD.length), true);
  assert.deepEqual([...new Set(PEOPLE_HEAD.map((h) => h.length))], [2]);
  // 不是管理員:伺服器照業務員成本算,欄名跟著換(owner 2026-10-28)
  const staff = repairTable({ results: [row], people, choices: { way: ways } }, false);
  assert.deepEqual(staff[4].slice(7), ["實付", "業務員成本", "委外費用", "業務員毛利"]);
});

test("頁面:選項從伺服器的清單畫、匯出走「完整才存檔」、要有這一項權限才進得來", () => {
  const page = readFileSync(new URL("../pages/reports/RepairMonthlyPage.tsx", import.meta.url), "utf8");
  assert.ok(page.includes("data?.choices.way") && page.includes("ways.map((c) =>"));
  const code = page.replace(/\/\*[\s\S]*?\*\//g, "");
  for (const word of ["自修", "內轉"]) assert.ok(!code.includes(word), `頁面寫死了「${word}」`);
  assert.ok(!/<option[^>]*>\s*(自修|委外|內轉)\s*</.test(page), "頁面寫死了下拉的選項");
  assert.ok(page.includes("exportIfComplete(all, exportFileName(\"維修月報\", { store: storeName,"));
  assert.ok(page.includes("repairTable(all, actual)"));
  assert.ok(page.includes("data.people.map((p) =>"), "每個人分到多少要照伺服器給的畫");
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(app, /path="\/reports\/repairs"\s+element=\{\s*<NeedsAbility ability="report_repairs" doing="看維修月報">\s*<RepairMonthlyPage \/>/);
  const hooks = readFileSync(new URL("../api/hooks.ts", import.meta.url), "utf8");
  assert.ok(hooks.includes("`/repair-monthly-report/?${repairQuery(filter, page)}`"));
  assert.ok(hooks.includes('`/repair-monthly-report/?${repairQuery(filter, "export")}`'));
});
