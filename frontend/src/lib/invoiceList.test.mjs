// 發票明細在畫面這一側:條件怎麼變成網址、標題底下那一排、銷退那一格、匯出。跑法:npm test。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { choiceLabel, INVOICE_HEAD, invoiceQuery, invoiceTable, returnedText, summaryCards } from "./invoiceList.ts";
import { toCsv } from "./csv.ts";
import { PAGE_SIZE } from "./stockReports.ts";

const filter = { from: "2026-09-01", to: "2026-10-31", by: "", warehouse: "", form: "", state: "", search: "" };
const states = [{ key: "ok", label: "正常" }, { key: "void", label: "作廢" }, { key: "check", label: "待查" }];
const row = {
  id: 1, date: "2026-09-05", invoice_no: "QA10000001", form: "電子發票", buyer_tax_id: "04567890",
  doc: { kind: "sale", id: 7, no: "SO-000007" }, store: "民生店", customer: "直客", tax_method: "應稅內含",
  subtotal: "1114.00", tax: "56.00", total: "1170.00", state: "ok", returned: "0.00", return_date: null,
};

test("網址:空的條件不送;看畫面用頁碼,匯出要全部", () => {
  assert.equal(invoiceQuery(filter, 1), `from=2026-09-01&to=2026-10-31&page=1&page_size=${PAGE_SIZE}`);
  assert.equal(
    invoiceQuery({ ...filter, by: "return", warehouse: 8, form: "hand_tri", state: "check", search: " QA1000 " }, "export"),
    "from=2026-09-01&to=2026-10-31&by=return&warehouse=8&form=hand_tri&state=check&search=QA1000&export=1",
  );
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
    check_total: "390.00", returned: "1560.00",
  };
  assert.deepEqual(summaryCards(totals, states), [
    { label: "正常", value: "4 張" },
    { label: "未稅", value: "3,844" },
    { label: "稅額", value: "56" },
    { label: "含稅", value: "3,900" },
    { label: "銷退", value: "1,560" },
    { label: "作廢", value: "2 張" },
    { label: "待查", value: "1 張 390" },
  ]);
  assert.equal(summaryCards({ ...totals, check_count: 0, check_total: "0.00" }, states)[6].value, "0 張");
  assert.deepEqual([...new Set(summaryCards(totals, states).map((c) => c.label.length))], [2]);       // 一排的字數一樣
});

test("匯出:一張發票一列,金額不加千分位,狀態寫字,開頭是 0 的統編不會被試算表吃掉", () => {
  const table = invoiceTable(
    [row, { ...row, id: 2, invoice_no: "QA10000004", state: "void", returned: "780.00", return_date: "2026-10-02" }],
    states,
  );
  assert.deepEqual(table[0], INVOICE_HEAD);
  assert.deepEqual(table[1], [
    "2026-09-05", "QA10000001", "電子發票", "04567890", "SO-000007", "民生店", "直客", "應稅內含",
    "1114", "56", "1170", "正常", "0", "",
  ]);
  assert.deepEqual(table[2].slice(11), ["作廢", "780", "2026-10-02"]);
  assert.equal(table.every((line) => line.length === INVOICE_HEAD.length), true);
  assert.ok(toCsv(table).split("\r\n")[1].includes('"=""04567890"""'));
});

test("頁面:選項從伺服器的清單畫、匯出走「完整才存檔」、要有這一項權限才進得來", () => {
  const page = readFileSync(new URL("../pages/reports/InvoiceListPage.tsx", import.meta.url), "utf8");
  assert.ok(page.includes("choices?.by") && page.includes("choices?.state"));
  // 下拉的選項不能自己寫(欄名「銷退日」不算;那是表頭)
  assert.ok(!/<option[^>]*>\s*(正常|作廢|待查|發票日|銷退日)\s*</.test(page), "頁面寫死了下拉的選項");
  const code = page.replace(/\/\*[\s\S]*?\*\//g, "");        // 說明文字不算
  for (const word of ["正常", "作廢", "待查"]) assert.ok(!code.includes(word), `頁面寫死了「${word}」`);
  assert.ok(page.includes("exportIfComplete(all,"));
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(app, /path="\/reports\/invoice-detail"\s+element=\{\s*<NeedsAbility ability="report_invoices" doing="看發票明細">\s*<InvoiceListPage \/>/);
  assert.ok(!app.includes('<Placeholder title="發票明細" />'));
  const hooks = readFileSync(new URL("../api/hooks.ts", import.meta.url), "utf8");
  assert.ok(hooks.includes("`/sales-invoice-report/?${invoiceQuery(filter, page)}`"));
  assert.ok(hooks.includes('`/sales-invoice-report/?${invoiceQuery(filter, "export")}`'));
});
