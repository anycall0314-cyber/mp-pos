// 庫存三張在畫面這一側:條件怎麼變成網址、每一格怎麼顯示、匯出的檔。跑法:npm test。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  PAGE_SIZE, SERIAL_DEFAULT_STATUSES, SERIAL_STATUS_CHOICES, statusesOf, costText, csvCell, dayOf, docPath, effectLines, flowCell, flowQuery,
  flowTable, fullTime, moveQuery, moveTable, movesOfFlowRow, optionalRangeReady, pageCount, pageSlice, routeText,
  serialFilterReady, serialQuery, serialTable, shortTime, signed, toCsv, truncatedNote, unitCodes,
} from "./stockReports.ts";

const flowFilter = { from: "2026-10-01", to: "2026-10-12", warehouse: "", category: "", search: "", moved: false };
const moveFilter = { from: "2026-10-01", to: "2026-10-12", warehouse: "", kind: "", category: "", search: "", product: "" };
const serialFilter = {
  statuses: SERIAL_DEFAULT_STATUSES, warehouse: "", supplier: "",
  receivedFrom: "", receivedTo: "", soldFrom: "", soldTo: "", search: "",
};

test("進銷存表的網址:空的條件不送,只看有進出才帶 moved", () => {
  assert.equal(flowQuery(flowFilter), "from=2026-10-01&to=2026-10-12");
  assert.equal(
    flowQuery({ ...flowFilter, warehouse: 8, category: 3, search: " 皮套 ", moved: true }),
    "from=2026-10-01&to=2026-10-12&warehouse=8&category=3&search=%E7%9A%AE%E5%A5%97&moved=1",
  );
  assert.equal(flowQuery({ ...flowFilter, search: "   " }), "from=2026-10-01&to=2026-10-12");
});

test("異動查詢的網址:看畫面用頁碼,匯出要全部", () => {
  assert.equal(moveQuery(moveFilter, 2), `from=2026-10-01&to=2026-10-12&page=2&page_size=${PAGE_SIZE}`);
  assert.equal(
    moveQuery({ ...moveFilter, kind: "sale_void", warehouse: 8 }, "export"),
    "from=2026-10-01&to=2026-10-12&warehouse=8&kind=sale_void&export=1",
  );
});

test("從進銷存表點品名去異動查詢:帶的是商品編號,不是拿品號去找", () => {
  const flow = { ...flowFilter, warehouse: 8, category: 3, search: "皮套", moved: true };
  const carried = movesOfFlowRow(flow, { product: 41, sku: "A-000001", name: "側翻皮套" });
  assert.deepEqual(carried.filter, {
    from: "2026-10-01", to: "2026-10-12", warehouse: 8, kind: "", category: "", search: "", product: 41,
  });
  assert.deepEqual(carried.product, { id: 41, label: "A-000001 側翻皮套" });
  assert.equal(
    moveQuery(carried.filter, 1),
    `from=2026-10-01&to=2026-10-12&warehouse=8&product=41&page=1&page_size=${PAGE_SIZE}`,
  );
  assert.equal(moveQuery(carried.filter, "export"), "from=2026-10-01&to=2026-10-12&warehouse=8&product=41&export=1");
  // 拿掉指定的商品之後就不帶了
  assert.ok(!moveQuery({ ...carried.filter, product: "" }, 1).includes("product"));
});

test("序號查詢一打開列的是在門市裡的:在庫與已退", () => {
  assert.deepEqual(SERIAL_DEFAULT_STATUSES, ["in_stock", "returned"]);
  assert.equal(serialQuery(serialFilter, 1), `status=in_stock%2Creturned&page=1&page_size=${PAGE_SIZE}`);
  // 一個狀態都沒勾 = 全部(不送 status)
  assert.equal(serialQuery({ ...serialFilter, statuses: [] }, "export"), "export=1");
  assert.equal(
    serialQuery({ ...serialFilter, statuses: ["sold"], supplier: 5, soldFrom: "2026-10-01", soldTo: "2026-10-12", search: "5678" }, 1),
    `status=sold&supplier=5&sold_from=2026-10-01&sold_to=2026-10-12&search=5678&page=1&page_size=${PAGE_SIZE}`,
  );
});

test("狀態選單:名稱都是兩個字,預設是在店,全部 = 不篩", () => {
  assert.deepEqual([...new Set(SERIAL_STATUS_CHOICES.map((c) => c.label.length))], [2]);
  assert.equal(SERIAL_STATUS_CHOICES[0].key, "store");
  assert.deepEqual(statusesOf("store"), ["in_stock", "returned"]);
  assert.deepEqual(statusesOf("sold"), ["sold"]);
  assert.deepEqual(statusesOf("in_transit"), ["in_transit"]);
  assert.deepEqual(statusesOf("all"), []);
  assert.deepEqual(statusesOf("沒有這個"), ["in_stock", "returned"]);
  assert.equal(new Set(SERIAL_STATUS_CHOICES.map((c) => c.key)).size, SERIAL_STATUS_CHOICES.length);
});

test("可以不填的日期:空的不管,填了要是日期、不能顛倒", () => {
  assert.equal(optionalRangeReady("", ""), true);
  assert.equal(optionalRangeReady("2026-10-01", ""), true);
  assert.equal(optionalRangeReady("", "2026-10-01"), true);
  assert.equal(optionalRangeReady("2026-10-02", "2026-10-01"), false);
  assert.equal(optionalRangeReady("2026-10-01", "2026-10-01"), true);
  assert.equal(optionalRangeReady("10/1", ""), false);
  assert.equal(serialFilterReady(serialFilter), true);
  assert.equal(serialFilterReady({ ...serialFilter, soldFrom: "2026-10-05", soldTo: "2026-10-01" }), false);
  assert.equal(serialFilterReady({ ...serialFilter, receivedFrom: "abc" }), false);
});

test("進銷存表中間的欄 0 不寫;增減的加減號寫出來", () => {
  assert.equal(flowCell(0), "");
  assert.equal(flowCell(3), "3");
  assert.equal(flowCell(-2), "-2");
  assert.equal(signed(4), "+4");
  assert.equal(signed(-4), "−4");
  assert.equal(signed(0), "0");
});

test("一筆異動動到哪幾家門市;調撥另外寫路線", () => {
  const voided = { effects: [{ warehouse: 1, name: "湳雅店", delta: 4 }, { warehouse: 2, name: "民生店", delta: -4 }] };
  assert.deepEqual(effectLines(voided), [
    { name: "湳雅店", text: "+4", delta: 4 }, { name: "民生店", text: "−4", delta: -4 },
  ]);
  assert.deepEqual(effectLines({ effects: [] }), []);
  assert.equal(routeText({ kind: "transfer_out", from_name: "湳雅店", to_name: "民生店" }), "湳雅店 → 民生店");
  assert.equal(routeText({ kind: "transfer_in", from_name: "湳雅店", to_name: "民生店" }), "湳雅店 → 民生店");
  assert.equal(routeText({ kind: "sale", from_name: "湳雅店", to_name: "" }), "");
  assert.equal(routeText({ kind: "transfer_out", from_name: "湳雅店", to_name: "" }), "");
});

test("點單號去哪一頁", () => {
  assert.equal(docPath({ kind: "purchase", id: 7, no: "PO-000007" }), "/purchases/7");
  assert.equal(docPath({ kind: "sale", id: 9, no: "SO-000009" }), "/sales/9");
  assert.equal(docPath({ kind: "sale_return", id: 3, no: "SR-000003" }), "/sales/returns/3");
  assert.equal(docPath({ kind: "transfer", id: 4, no: "TO-000004" }), "/transfers/4");
  assert.equal(docPath({ kind: "repair", id: 5, no: "R-5" }), "/repairs/5");
});

test("時間用這台電腦的時區", () => {
  const iso = new Date(2026, 9, 2, 7, 5).toISOString();      // 台灣早上 = 世界時間前一天晚上
  assert.equal(shortTime(iso), "10-02 07:05");
  assert.equal(fullTime(iso), "2026-10-02 07:05");
  assert.equal(dayOf(iso), "2026-10-02");
  assert.equal(dayOf(null), "");
  assert.equal(shortTime("不是時間"), "");
});

test("一台設備的兩個碼;成本顯示成整數元", () => {
  assert.deepEqual(unitCodes({ serial_no: "356", imei: "356", sn: "F17" }), { imei: "356", sn: "F17" });
  assert.deepEqual(unitCodes({ serial_no: "F17", imei: "", sn: "F17" }), { imei: "", sn: "F17" });
  assert.deepEqual(unitCodes({ serial_no: "X1", imei: "", sn: "" }), { imei: "", sn: "X1" });
  assert.equal(costText("20000.50"), "20,001");
  assert.equal(costText("95.24"), "95");
});

test("畫面自己分頁:超出範圍就停在最後一頁", () => {
  const rows = Array.from({ length: 250 }, (_, i) => i);
  assert.equal(pageCount(250), 3);
  assert.equal(pageCount(0), 1);
  assert.equal(pageCount(100), 1);
  assert.deepEqual(pageSlice(rows, 1).length, 100);
  assert.deepEqual(pageSlice(rows, 3), rows.slice(200));
  assert.deepEqual(pageSlice(rows, 9), rows.slice(200));
  assert.deepEqual(pageSlice(rows, 0), rows.slice(0, 100));
  assert.deepEqual(pageSlice([], 1), []);
});

test("匯出的一格:IMEI 那種長數字寫成文字,不會被試算表變成 3.56E+14", () => {
  assert.equal(csvCell("356789012345678"), '"=""356789012345678"""');
  assert.equal(csvCell("471234567890"), '"=""471234567890"""');
  assert.equal(csvCell("12345678901"), "12345678901");       // 11 位以下試算表不會動
  assert.equal(csvCell(20000), "20000");
  assert.equal(csvCell("F17ABC"), "F17ABC");
  assert.equal(csvCell('9H "滿版", 黑'), '"9H ""滿版"", 黑"');
  assert.equal(csvCell("第一行\n第二行"), '"第一行\n第二行"');
  assert.equal(csvCell(null), "");
  assert.equal(csvCell(undefined), "");
  assert.equal(csvCell(0), "0");
  assert.equal(toCsv([["品號", "數量"], ["A,1", 3]]), '品號,數量\r\n"A,1",3');
});

const flowResult = {
  from: "2026-10-01", to: "2026-10-12", warehouse: null, row_count: 1, truncated: false, with_transit: true,
  columns: [
    { key: "purchase", label: "進貨", sign: 1 }, { key: "sale", label: "銷貨", sign: -1 },
    { key: "sale_return", label: "銷退", sign: 1 }, { key: "transfer_in", label: "調入", sign: 1 },
    { key: "transfer_out", label: "調出", sign: -1 }, { key: "usage", label: "領用", sign: -1 },
    { key: "adjust", label: "調整", sign: 1 },
  ],
  rows: [{
    product: 1, sku: "LC-000001", name: "側翻皮套", category: "皮套", opening: 0, purchase: 10, sale: 2,
    sale_return: 0, transfer_in: 4, transfer_out: 5, usage: 0, adjust: 0, closing: 7, returned: 0, transit: 1,
  }],
  totals: {},
};

test("進銷存表的匯出:數字照原樣(0 也寫),全公司那一張多一欄在途", () => {
  assert.deepEqual(flowTable(flowResult), [
    ["品號", "品名", "類別", "期初", "進貨", "銷貨", "銷退", "調入", "調出", "領用", "調整", "期末", "其中已退", "在途"],
    ["LC-000001", "側翻皮套", "皮套", 0, 10, 2, 0, 4, 5, 0, 0, 7, 0, 1],
  ]);
  const oneStore = flowTable({ ...flowResult, with_transit: false });
  assert.equal(oneStore[0].at(-1), "其中已退");
  assert.equal(oneStore[1].length, 13);
});

const move = {
  id: 1, created_at: new Date(2026, 9, 12, 14, 5).toISOString(), kind: "transfer_void", kind_label: "調撥作廢",
  product: 1, sku: "LC-000001", name: "側翻皮套", serial: null, serial_no: "", qty: 4,
  effects: [{ warehouse: 1, name: "湳雅店", delta: 4 }, { warehouse: 2, name: "民生店", delta: -4 }],
  from_name: "民生店", to_name: "湳雅店", doc: { kind: "transfer", id: 4, no: "TO-000004" }, note: "",
};

test("異動查詢的匯出:動到兩家門市的一家一列;只是紀錄的也有一列", () => {
  const table = moveTable([move, { ...move, id: 2, effects: [], doc: null, note: "已脫離本單" }]);
  assert.deepEqual(table[0], ["時間", "類別", "品號", "品名", "序號", "門市", "增減", "路線", "單號", "備註"]);
  assert.deepEqual(table[1], ["2026-10-12 14:05", "調撥作廢", "LC-000001", "側翻皮套", "", "湳雅店", 4, "", "TO-000004", ""]);
  assert.deepEqual(table[2].slice(5, 7), ["民生店", -4]);
  assert.deepEqual(table[3].slice(5), ["", 0, "", "", "已脫離本單"]);
  assert.equal(table.length, 4);
});

test("序號查詢的匯出:兩個碼分開、成本不加千分位、沒有賣出的空著", () => {
  const unit = {
    id: 1, serial_no: "356789012345678", imei: "356789012345678", sn: "F17ABC", product: 2, sku: "PH-000001",
    name: "iPhone 15 128GB 黑", status: "sold", status_label: "已售", store: "湳雅店",
    source: { kind: "purchase", label: "甲大盤商", doc: { kind: "purchase", id: 7, no: "PO-000007" } },
    received_at: new Date(2026, 9, 1, 9, 0).toISOString(), cost: "20000.00",
    sale: { doc: { kind: "sale", id: 9, no: "SO-000009" }, date: "2026-10-05" },
  };
  const table = serialTable([unit, { ...unit, source: null, sale: null, received_at: null, imei: "", sn: "" }]);
  assert.deepEqual(table[0], ["IMEI", "SN", "品號", "品名", "狀態", "門市", "來源", "進貨單號", "進貨日", "成本", "賣出單號", "賣出日"]);
  assert.deepEqual(table[1], [
    "356789012345678", "F17ABC", "PH-000001", "iPhone 15 128GB 黑", "已售", "湳雅店",
    "甲大盤商", "PO-000007", "2026-10-01", "20000", "SO-000009", "2026-10-05",
  ]);
  assert.deepEqual(table[2].slice(0, 2), ["", "356789012345678"]);
  assert.deepEqual(table[2].slice(6), ["", "", "", "20000", "", ""]);
  // 整份檔:IMEI 那一格是文字
  assert.ok(toCsv(table).includes('"=""356789012345678""",F17ABC'));
});

test("匯出被截短要講", () => {
  assert.equal(truncatedNote({ truncated: true, count: 20000 }), "只匯出前 20000 列,請把條件縮小");
  assert.equal(truncatedNote({ truncated: false, count: 12 }), "");
  assert.equal(truncatedNote({ count: 12 }), "");
});

test("三張表都掛在導覽上、名稱四個字,路由不是空殼", () => {
  const nav = readFileSync(new URL("../nav.ts", import.meta.url), "utf8");
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  for (const [path, label] of [["/inventory/flow", "進銷存表"], ["/inventory/movements", "異動查詢"], ["/serials", "序號查詢"]]) {
    assert.ok(nav.includes(`to: "${path}", label: "${label}"`), `${label} 沒有掛在導覽`);
    assert.equal(label.length, 4);
    assert.ok(new RegExp(`path="${path}"`).test(app), `${path} 沒有路由`);
  }
  assert.ok(!/Placeholder title="(序號查詢|異動查詢)"/.test(app), "還是空殼頁");
});
