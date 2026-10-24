// 銷貨日報在畫面這一側:條件、打了商品的字之後列哪幾行、合計(算法跟改之前一樣)、銷退、匯出。跑法:npm test。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  DAILY_CSV_HEAD, customerText, dailyQuery, dailyTable, dailyTotals, daysAgo, itemGrossProfit, itemStaffProfit, orderPaidAmount,
  narrowedBy, netTotals, serialList, shownOrders, splitOrders, truncatedText,
} from "./salesDaily.ts";
import { toCsv } from "./stockReports.ts";

const filter = { from: "2026-10-12", to: "2026-10-12", warehouse: "", sales_person: "", customer: "", member: "", search: "" };

const line = (over = {}) => ({
  id: 1, line_no: 1, product: 9, product_sku: "PH-000001", product_name: "iPhone 15 128GB 黑",
  product_counts_margin: true, product_warehouse_type: "product", serials: [], qty: 1,
  unit_price: "25000.00", amount: "25000.00", untaxed_amount: "23809.52", cost_at_post: "20000.00",
  staff_cost: "21000.00", matched: true, ...over,
});
const order = (over = {}) => ({
  id: 1, no: "SO-000001", doc_date: "2026-10-12", is_void: false, warehouse_code: "w1", warehouse_name: "湳雅店",
  sales_person_name: "小陳", customer_name: "直客", member_name: null, items: [line()], ...over,
});
/** 銷退:伺服器給的就是負的(單價不變)。 */
const back = (it) => ({
  ...it, qty: -it.qty, amount: String(-Number(it.amount)), untaxed_amount: String(-Number(it.untaxed_amount)),
  cost_at_post: String(-Number(it.cost_at_post)), staff_cost: String(-Number(it.staff_cost)),
});

test("網址:空的條件不送,商品的字去掉前後空白", () => {
  assert.equal(dailyQuery(filter), "from=2026-10-12&to=2026-10-12");
  assert.equal(
    dailyQuery({ ...filter, warehouse: 8, sales_person: 3, customer: 5, member: 7, search: " 17 pro " }),
    "from=2026-10-12&to=2026-10-12&warehouse=8&sales_person=3&customer=5&member=7&search=17+pro",
  );
  assert.equal(dailyQuery({ ...filter, search: "   " }), "from=2026-10-12&to=2026-10-12");
});

test("今天與幾天前用這台電腦的日期,不是世界時間", () => {
  const early = new Date(2026, 9, 1, 7, 30);          // 台灣 10/1 早上 = 世界時間 9/30
  assert.equal(daysAgo(0, early), "2026-10-01");
  assert.equal(daysAgo(6, early), "2026-09-25");
  assert.equal(daysAgo(1, new Date(2026, 0, 1, 12, 0)), "2025-12-31");
});

test("打了商品的字:只留對得上的行;一行都沒有的單不列;勾整張單就全部留", () => {
  const two = order({ items: [line({ id: 1 }), line({ id: 2, product_name: "皮套", matched: false })] });
  const none = order({ id: 2, no: "SO-000002", items: [line({ id: 3, matched: false })] });
  const all = order({ id: 3, no: "SO-000003" });
  const shown = shownOrders([two, none, all], false);
  assert.deepEqual(shown.map((o) => [o.no, o.items.map((i) => i.id)]), [["SO-000001", [1]], ["SO-000003", [1]]]);
  assert.equal(shown[1], all);                          // 整張都對得上的那一張原樣回來
  assert.equal(two.items.length, 2);                    // 不改到原本的資料
  assert.deepEqual(shownOrders([two, none, all], true), [two, none, all]);
  assert.deepEqual(shownOrders([], false), []);
});

test("正常單與作廢單分開", () => {
  const a = order();
  const v = order({ id: 2, no: "SO-000002", is_void: true });
  assert.deepEqual(splitOrders([a, v, a]), { active: [a, a], voided: [v] });
});

test("每一行的毛利:未稅 − 成本;業務員毛利用業務員成本;不計毛利的行是 0", () => {
  assert.equal(Math.round(itemGrossProfit(line()) * 100) / 100, 3809.52);
  assert.equal(Math.round(itemStaffProfit(line()) * 100) / 100, 2809.52);
  const buyback = line({ product_counts_margin: false, amount: "-8000.00", untaxed_amount: "-8000.00", cost_at_post: "0" });
  assert.equal(itemGrossProfit(buyback), 0);
  assert.equal(itemStaffProfit(buyback), 0);
  assert.equal(serialList(line({ serials: [{ serial_no: "A1" }, { serial_no: "B2" }] })), "A1 / B2");
  assert.equal(serialList(line()), "");
});

test("合計跟改之前同一個算法:商品與零件分開,不計毛利的行只算金額", () => {
  const orders = [
    order({ items: [
      line(),
      line({ id: 2, qty: 2, amount: "780.00", untaxed_amount: "780.00", cost_at_post: "200.00", staff_cost: "200.00" }),
      line({ id: 3, product_counts_margin: false, amount: "-8000.00", untaxed_amount: "-8000.00", cost_at_post: "0", staff_cost: "0" }),
    ] }),
    order({ id: 2, items: [
      line({ id: 4, product_warehouse_type: "parts", amount: "500.00", untaxed_amount: "500.00", cost_at_post: "300.00", staff_cost: "300.00" }),
    ] }),
  ];
  const t = dailyTotals(orders);
  assert.equal(t.lines, 3);
  assert.equal(t.amountIncl, 25000 + 780 - 8000);
  assert.equal(t.cost, 20200);
  assert.equal(Math.round(t.profit * 100) / 100, 3809.52 + 580);
  assert.equal(Math.round(t.staffProfit * 100) / 100, 2809.52 + 580);
  assert.deepEqual([t.partsLines, t.partsAmount, t.partsCost, t.partsProfit, t.partsStaffProfit], [1, 500, 300, 200, 200]);
  assert.deepEqual(dailyTotals([]), {
    lines: 0, amountIncl: 0, cost: 0, profit: 0, staffProfit: 0,
    partsLines: 0, partsAmount: 0, partsCost: 0, partsProfit: 0, partsStaffProfit: 0,
  });
});

test("手機回補:客人不用付,金額合計不含它;毛利與業務員毛利含它", () => {
  const backfill = line({ id: 5, counts_cash: false, amount: "1000.00", untaxed_amount: "1000.00", cost_at_post: "0", staff_cost: "0" });
  const t = dailyTotals([order({ items: [line(), backfill] })]);
  assert.equal(t.amountIncl, 25000);                                    // 收到的錢對得上
  assert.equal(Math.round(t.profit * 100) / 100, 3809.52 + 1000);
  assert.equal(Math.round(t.staffProfit * 100) / 100, 2809.52 + 1000);
  assert.equal(orderPaidAmount(order({ items: [line(), backfill] })), 25000);   // 手機寬度那張卡片的含稅金額
  assert.equal(orderPaidAmount(order({ items: [line(), backfill].map(back) })), -25000);
});

test("銷退:每一行是負的,剛好把原單那一行沖掉;扣掉銷退的那一組是相加", () => {
  const sold = order();
  const returned = order({ id: 9, no: "SR-000001", original_so: 1, original_so_no: "SO-000001", items: sold.items.map(back) });
  const s = dailyTotals([sold]);
  const r = dailyTotals([returned]);
  assert.equal(r.amountIncl, -25000);
  assert.ok(r.profit < 0 && r.staffProfit < 0);
  const net = netTotals(s, r);
  assert.equal(net.amount, 0);
  assert.equal(Math.round(net.profit * 100), 0);
  assert.equal(Math.round(net.staffProfit * 100), 0);
  // 賣兩張、退一張:剩下的就是沒退的那一張
  const other = order({ id: 2, no: "SO-000002", items: [line({ id: 5, amount: "780.00", untaxed_amount: "780.00", cost_at_post: "200.00", staff_cost: "260.00" })] });
  const both = netTotals(dailyTotals([sold, other]), r);
  assert.equal(both.amount, 780);
  assert.equal(Math.round(both.profit * 100) / 100, 580);
  assert.equal(Math.round(both.staffProfit * 100) / 100, 520);
  // 沒有銷退:跟原本那幾格一樣
  assert.deepEqual(netTotals(s, dailyTotals([])), { amount: s.amountIncl, profit: s.profit, staffProfit: s.staffProfit });
  // 零件的銷退不混進商品那幾格(另外一排)
  const parts = order({ id: 10, items: [back(line({ product_warehouse_type: "parts", amount: "500.00", untaxed_amount: "500.00", cost_at_post: "300.00", staff_cost: "300.00" }))] });
  const withParts = dailyTotals([returned, parts]);
  assert.deepEqual([withParts.amountIncl, withParts.partsAmount, withParts.partsProfit], [-25000, -500, -200]);
});

test("有會讓合計變小的條件就要講(期間與門市不算)", () => {
  assert.deepEqual(narrowedBy(filter), []);
  assert.deepEqual(narrowedBy({ ...filter, warehouse: 8 }), []);
  assert.deepEqual(narrowedBy({ ...filter, search: " iphone " }), ["商品"]);
  assert.deepEqual(narrowedBy({ ...filter, search: "   " }), []);
  assert.deepEqual(narrowedBy({ ...filter, sales_person: 3, customer: 5, member: 7, search: "x" }), ["業務員", "來源", "會員", "商品"]);
});

test("客戶那一格:來源在前,會員不是同一個名字才接在後面", () => {
  assert.equal(customerText({ customer_name: "直客", member_name: "王小明" }), "直客 · 王小明");
  assert.equal(customerText({ customer_name: "王小明", member_name: "王小明" }), "王小明");
  assert.equal(customerText({ customer_name: "甲同行", member_name: null }), "甲同行");
  assert.equal(customerText({ customer_name: null, member_name: null }), "直客");
  assert.equal(customerText({ customer_name: null, member_name: "王小明" }), "直客 · 王小明");
});

test("超過上限要講", () => {
  assert.equal(truncatedText({ truncated: true, limit: 2000 }), "超過 2000 張,只列前 2000 張,合計不完整,請縮短期間");
  assert.equal(truncatedText({ truncated: false, limit: 2000 }), "");
});

test("匯出:前 14 欄的內容跟以前一樣(欄名 2026-10-23 照全站用語改:門市、來源),後面多「銷退」「原銷貨單」「會員」;IMEI 是文字", () => {
  assert.deepEqual(DAILY_CSV_HEAD, [
    "日期", "單號", "門市", "業務員", "來源", "商品", "序號", "數量", "單價", "金額", "成本", "毛利", "業務員毛利", "作廢",
    "銷退", "原銷貨單", "會員",
  ]);
  const sold = order({ member_name: "王小明", items: [line({ serials: [{ serial_no: "356789012345678" }] })] });
  const returned = order({ id: 9, no: "SR-000001", original_so_no: "SO-000001", items: sold.items.map(back) });
  const voided = order({ id: 3, no: "SO-000003", is_void: true, customer_name: null, items: [line({ product_counts_margin: false })] });
  const table = dailyTable([sold], [returned], [voided]);
  // 前 14 欄:跟改之前那一頁寫出來的一模一樣(客戶那一欄只有來源「直客」,不接會員)
  assert.deepEqual(table[1].slice(0, 14), [
    "2026-10-12", "SO-000001", "w1 湳雅店", "小陳", "直客", "iPhone 15 128GB 黑", "356789012345678",
    "1", "25000", "25000", "20000", "3810", "2810", "",
  ]);
  assert.deepEqual(table[1].slice(14), ["", "", "王小明"]);
  assert.deepEqual(table[2].slice(7), ["-1", "25000", "-25000", "-20000", "-3810", "-2810", "", "Y", "SO-000001", ""]);
  assert.equal(table[3][4], "直客");                                       // 沒有客戶的舊單
  assert.deepEqual(table[3].slice(10), ["", "", "", "Y", "", "", ""]);     // 不計毛利的行成本與毛利空著;作廢
  assert.equal(table.length, 4);
  assert.ok(table.every((row) => row.length === DAILY_CSV_HEAD.length));
  assert.ok(toCsv(table).includes('"=""356789012345678"""'));
});

test("銷貨日報那一頁用的是新的資料來源、算法在這一個檔", () => {
  const page = readFileSync(new URL("../pages/reports/SalesDailyReport.tsx", import.meta.url), "utf8");
  assert.ok(page.includes("useSalesDaily(applied)"));
  assert.ok(!page.includes("/sales-orders/"), "不能再拿銷貨單清單自己加總(一頁只有 50 張)");
  assert.ok(!page.includes("toISOString"), "日期不能用世界時間");
  assert.ok(page.includes("dailyTotals(activeOrders)"));
  // 日期不對(起日晚於迄日)時不能按查詢:不然請求不會送、畫面卻寫「查無資料」
  assert.ok(page.includes("disabled={!ready}"));
  assert.ok(page.includes("if (!over && !ready) return;"));   // 快速鈕帶自己的起訖日(全站檢視 E10)
  // 舊的那一支(拿銷貨單清單、要求一頁 500 張,伺服器其實只給 50 張)拿掉了,不能再被別的頁面拿去用
  const hooks = readFileSync(new URL("../api/hooks.ts", import.meta.url), "utf8");
  assert.ok(!hooks.includes("useSalesDailyReport"));
  assert.ok(hooks.includes("/sales-daily-report/?"));
});
