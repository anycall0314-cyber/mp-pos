// 發票明細在畫面這一側:條件怎麼變成網址、標題底下那一排、銷退那一格、匯出。跑法:npm test。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  choiceLabel,
  INVOICE_HEAD,
  invoiceQuery,
  invoiceTable,
  lastPeriod,
  madeAtText,
  returnedText,
  summaryCards,
  summaryQuery,
  summaryTable,
} from "./invoiceList.ts";
import { toCsv } from "./csv.ts";
import { PAGE_SIZE } from "./stockReports.ts";

const filter = { from: "2026-09-01", to: "2026-10-31", by: "", warehouse: "", form: "", state: "", search: "" };
const states = [{ key: "ok", label: "正常" }, { key: "void", label: "作廢" }, { key: "check", label: "待查" }];
const row = {
  id: 1, date: "2026-09-05", invoice_no: "QA10000001", form: "電子發票", buyer_tax_id: "04567890",
  doc: { kind: "sale", id: 7, no: "SO-000007" }, store: "民生店", customer: "直客", tax_method: "應稅內含",
  subtotal: "1114.00", tax: "56.00", total: "1170.00", state: "ok", void_date: null, returned: "0.00", return_date: null,
};

test("網址:空的條件不送;看畫面用頁碼,匯出要全部", () => {
  assert.equal(invoiceQuery(filter, 1), `from=2026-09-01&to=2026-10-31&page=1&page_size=${PAGE_SIZE}`);
  assert.equal(
    invoiceQuery({ ...filter, by: "return", warehouse: 8, form: "hand_tri", state: "check", search: " QA1000 " }, "export"),
    "from=2026-09-01&to=2026-10-31&by=return&warehouse=8&form=hand_tri&state=check&search=QA1000&export=1",
  );
  assert.ok(invoiceQuery({ ...filter, by: "void" }, 1).includes("&by=void&"));       // 照作廢日(2026-10-12)
  assert.ok(!invoiceQuery({ ...filter, search: "  " }, 2).includes("search"));
});

test("選項的字是伺服器給的;清單還沒到就先照代碼", () => {
  assert.equal(choiceLabel(states, "check"), "待查");
  assert.equal(choiceLabel(undefined, "check"), "check");
  assert.equal(choiceLabel(states, "gone"), "gone");
});

test("銷退那一格:沒有退是空的,有退寫金額", () => {
  assert.equal(returnedText({ returned: "0.00" }), "");
  assert.equal(returnedText({ returned: "1560.00" }), "1,560");
});

test("標題底下那一排:金額是正常那幾張的面額;銷退、作廢、待查各自一格", () => {
  const totals = {
    ok_count: 4, void_count: 2, check_count: 1, subtotal: "3844.00", tax: "56.00", total: "3900.00",
    check_total: "390.00", void_total: "1170.00", returned: "1560.00",
  };
  assert.deepEqual(summaryCards(totals, states), [
    { label: "正常", value: "4 張" },
    { label: "未稅", value: "3,844" },
    { label: "稅額", value: "56" },
    { label: "含稅", value: "3,900" },
    { label: "銷退", value: "1,560" },
    { label: "作廢", value: "2 張 1,170" },                // 作廢那幾張的面額(會計列作廢清單要金額)
    { label: "待查", value: "1 張 390" },
  ]);
  assert.equal(summaryCards({ ...totals, check_count: 0, check_total: "0.00" }, states)[6].value, "0 張");
  assert.equal(summaryCards({ ...totals, void_count: 0, void_total: "0.00" }, states)[5].value, "0 張");
  // 作廢的金額不能拿成待查的(兩格各是各的)
  assert.equal(summaryCards({ ...totals, void_total: "999.00" }, states)[5].value, "2 張 999");
  assert.equal(summaryCards({ ...totals, void_total: "999.00" }, states)[6].value, "1 張 390");
  assert.deepEqual([...new Set(summaryCards(totals, states).map((c) => c.label.length))], [2]);       // 一排的字數一樣
});

test("匯出:一張發票一列,金額不加千分位,狀態寫字,開頭是 0 的統編不會被試算表吃掉", () => {
  const table = invoiceTable(
    [row, { ...row, id: 2, invoice_no: "QA10000004", state: "void", void_date: "2026-10-05", returned: "780.00", return_date: "2026-10-02" }],
    states,
  );
  assert.deepEqual(table[0], INVOICE_HEAD);
  assert.deepEqual(table[1], [
    "2026-09-05", "QA10000001", "電子發票", "04567890", "SO-000007", "民生店", "直客", "應稅內含",
    "1114", "56", "1170", "正常", "", "0", "",
  ]);
  assert.deepEqual(table[2].slice(11), ["作廢", "2026-10-05", "780", "2026-10-02"]);        // 作廢日與銷退日各是各的
  assert.deepEqual(INVOICE_HEAD.slice(11), ["狀態", "作廢日", "銷退", "銷退日"]);
  assert.equal(table.every((line) => line.length === INVOICE_HEAD.length), true);
  assert.ok(toCsv(table).split("\r\n")[1].includes('"=""04567890"""'));
});

test("頁面:選項從伺服器的清單畫、匯出走「完整才存檔」、要有這一項權限才進得來", () => {
  const page = readFileSync(new URL("../pages/reports/InvoiceListPage.tsx", import.meta.url), "utf8");
  assert.ok(page.includes("choices?.by") && page.includes("choices?.state"));
  // 下拉的選項不能自己寫(欄名「銷退日」「作廢日」不算;那是表頭)
  assert.ok(!/<option[^>]*>\s*(正常|作廢|待查|發票日|銷退日|作廢日)\s*</.test(page), "頁面寫死了下拉的選項");
  const code = page.replace(/\/\*[\s\S]*?\*\//g, "").replaceAll("<th>作廢日</th>", "");        // 說明文字與表頭不算
  // 表上有作廢日那一欄,而且排在狀態後面、銷退前面(跟匯出的欄一樣的順序)
  assert.match(page, /<th>狀態<\/th>\s*<th>作廢日<\/th>\s*<th className="num">銷退<\/th>/);
  assert.match(page, /\{choiceLabel\(choices\?\.state, r\.state\)\}<\/td>\s*<td>\{r\.void_date \?\? ""\}<\/td>\s*<td className="num">\{returnedText\(r\)\}/);
  for (const word of ["正常", "作廢", "待查"]) assert.ok(!code.includes(word), `頁面寫死了「${word}」`);
  assert.ok(page.includes("exportIfComplete(all,"));
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(app, /path="\/reports\/invoice-detail"\s+element=\{\s*<NeedsAbility ability="report_invoices" doing="看發票明細">\s*<InvoiceListPage \/>/);
  assert.ok(!app.includes('<Placeholder title="發票明細" />'));
  const hooks = readFileSync(new URL("../api/hooks.ts", import.meta.url), "utf8");
  assert.ok(hooks.includes("`/sales-invoice-report/?${invoiceQuery(filter, page)}`"));
  assert.ok(hooks.includes('`/sales-invoice-report/?${invoiceQuery(filter, "export")}`'));
});

// ---- 開立發票彙總表 ----

test("上期 = 剛結束的那一期(兩個月一期,單數月開始)", () => {
  const at = (y, m, d = 15) => lastPeriod(new Date(y, m - 1, d));
  assert.deepEqual(at(2026, 11, 3), { from: "2026-09-01", to: "2026-10-31" });     // 單數月報上一期
  assert.deepEqual(at(2026, 12), { from: "2026-09-01", to: "2026-10-31" });
  assert.deepEqual(at(2027, 1, 1), { from: "2026-11-01", to: "2026-12-31" });      // 跨年
  assert.deepEqual(at(2027, 2, 28), { from: "2026-11-01", to: "2026-12-31" });
  assert.deepEqual(at(2026, 10, 20), { from: "2026-07-01", to: "2026-08-31" });
  assert.deepEqual(at(2028, 3), { from: "2028-01-01", to: "2028-02-29" });          // 閏年
  assert.deepEqual(at(2027, 5, 1), { from: "2027-03-01", to: "2027-04-30" });
  assert.deepEqual(at(2027, 7, 31), { from: "2027-05-01", to: "2027-06-30" });
});

test("彙總表只帶期間、門市、發票類型", () => {
  assert.equal(summaryQuery({ ...filter, by: "void", state: "ok", search: "QA" }), "from=2026-09-01&to=2026-10-31");
  assert.equal(summaryQuery({ ...filter, warehouse: 3, form: "ev_tri" }), "from=2026-09-01&to=2026-10-31&warehouse=3&form=ev_tri");
});

const summary = {
  from: "2026-09-01",
  to: "2026-10-31",
  issued: [
    { date: "2026-09-05", store: "湳雅店", form: "電子三聯式", first: "KZ13548500", last: "KZ13548503", count: 4,
      subtotal: "2267.00", tax: "113.00", total: "2380.00" },
    { date: "2026-09-06", store: "湳雅店", form: "電子三聯式", first: "KZ13548504", last: "KZ13548504", count: 1,
      subtotal: "86.00", tax: "4.00", total: "90.00" },
  ],
  reversed: [
    { date: "2026-09-20", store: "湳雅店", form: "電子三聯式", invoice_no: "KZ13548502", kind: "return_void",
      subtotal: "-467.00", tax: "-23.00", total: "-490.00" },
  ],
  totals: {
    issued: { subtotal: "2353.00", tax: "117.00", total: "2470.00" },
    reversed: { subtotal: "-467.00", tax: "-23.00", total: "-490.00" },
    net: { subtotal: "1886.00", tax: "94.00", total: "1980.00" },
  },
  choices: { kind: [{ key: "sale_void", label: "銷貨作廢" }, { key: "return_void", label: "退貨作廢" },
    { key: "return_keep", label: "退貨折讓" }] },
};

test("彙總表的檔照舊系統的欄位順序:上段、小計、作廢與退回、小計、總計", () => {
  const table = summaryTable(summary, "湳雅店", "2026/11/03 10:05");
  assert.deepEqual(table, [
    ["開立發票彙總表", "日期：20260901 ~ 20261031", "門市：湳雅店", "製表時間：2026/11/03 10:05"],
    ["序號", "日期", "店別", "發票類別", "發票號碼", "銷貨金額", "銷貨稅額", "銷貨合計"],
    [1, "20260905", "湳雅店", "電子三聯式", "KZ13548500-KZ13548503", "2267", "113", "2380"],
    [2, "20260906", "湳雅店", "電子三聯式", "KZ13548504-KZ13548504", "86", "4", "90"],
    ["金額小計：", "", "", "", "", "2353", "117", "2470"],
    [],
    ["作廢與退回"],
    ["序號", "日期", "店別", "發票類別", "發票號碼", "銷貨金額", "銷貨稅額", "銷貨合計", "說明"],
    [1, "20260920", "湳雅店", "電子三聯式", "KZ13548502-KZ13548502", "-467", "-23", "-490", "退貨作廢"],
    ["金額小計：", "", "", "", "", "-467", "-23", "-490"],
    [],
    ["金額總計：", "", "", "", "", "1886", "94", "1980"],
  ]);
  // 金額那幾欄每一段都對齊在同一欄
  for (const r of table.filter((r) => String(r[0]).startsWith("金額"))) assert.equal(r.length, 8);
  // 沒選門市寫「全部門市」;作廢與退回一列都沒有時,段落照樣在、小計是 0
  const empty = summaryTable({ ...summary, reversed: [], totals: { ...summary.totals, reversed: { subtotal: "0.00", tax: "0.00", total: "0.00" } } }, "", "x");
  assert.equal(empty[0][2], "門市：全部門市");
  assert.deepEqual(empty.slice(5, 9), [[], ["作廢與退回"], ["序號", "日期", "店別", "發票類別", "發票號碼", "銷貨金額", "銷貨稅額", "銷貨合計", "說明"], ["金額小計：", "", "", "", "", "0", "0", "0"]]);
  // 寫成檔:號碼、日期、負數都是原樣
  const csv = toCsv(table);
  assert.ok(csv.includes("1,20260920,湳雅店,電子三聯式,KZ13548502-KZ13548502,-467,-23,-490,退貨作廢"));
});

test("製表時間是這台電腦的時間", () => {
  assert.equal(madeAtText(new Date(2026, 10, 3, 9, 5)), "2026/11/03 09:05");
});

test("頁面:兩顆匯出字數一樣、彙總表走同一套匯出;「上期」跟「本月」並排", () => {
  const page = readFileSync(new URL("../pages/reports/InvoiceListPage.tsx", import.meta.url), "utf8");
  assert.match(page, />\s*匯出明細\s*</);
  assert.match(page, />\s*匯出彙總\s*</);
  assert.match(page, />\s*本月\s*<\/button>\s*<button[\s\S]*?lastPeriod\(\)[\s\S]*?>\s*上期\s*</);
  assert.ok(page.includes("exportIfComplete({ count: rows },"));
  assert.ok(page.includes("summaryTable(got, storeName, madeAtText())"));
  const hooks = readFileSync(new URL("../api/hooks.ts", import.meta.url), "utf8");
  assert.ok(hooks.includes("`/sales-invoice-summary/?${summaryQuery(filter)}`"));
});
