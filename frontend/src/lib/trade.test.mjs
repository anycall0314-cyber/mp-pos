// 批發(賣家)在畫面這一側:刷機配單、這一次出什麼、金額輸入、批發價預填。跑法:npm test。
import assert from "node:assert/strict";
import test from "node:test";

import {
  NO_PICKS, NO_UNIT_EDITS, NO_UNIT_FILTER, liveQuote, amountOf, autoPrice, bestCell, cellEdits, cellOf, cellText, currentRows, feeOf, filterUnits, fitsCell,
  followsNow, heldUnits, lineProgress, pendingCells, percentOf, pickQty, placeScan, planIsEmpty, priceOf, sameCell, setQty, shipLines, shipTo,
  shipTotal, sortUnits, toggleUnit, unitConfirmText, unitFacets, unitNeedsConfirm, unitPlan, unitPriceShown, unpick,
} from "./trade.ts";

const unitLine = {
  id: 11, sku: "PH-1", name: "中古 iPhone 13", unit_label: "A 級", product: 5, requires_serial: true, per_unit: true,
  qty: 1, shipped_qty: 0, cancelled_qty: 0, open_qty: 1, unit_price: 15000,
  unit: { serial: 901, serial_no: "U901", imei: "", sn: "U901", status: "in_stock", status_label: "在庫", warehouse: 1, warehouse_name: "湳雅店" },
};
const phoneLine = { ...unitLine, id: 12, name: "iPhone 17", per_unit: false, qty: 3, shipped_qty: 1, open_qty: 2, unit_price: 23000, unit: null };
const caseLine = { ...unitLine, id: 13, name: "皮套", requires_serial: false, per_unit: false, qty: 10, open_qty: 6, shipped_qty: 4, unit_price: 351, unit: null };
const doneLine = { ...caseLine, id: 14, open_qty: 0, shipped_qty: 10 };
const order = { id: 1, lines: [unitLine, phoneLine, caseLine, doneLine] };
const found = (serial, lines) => ({ serial, serial_no: `S${serial}`, imei: "", sn: `S${serial}`, name: "iPhone 17", lines });

test("刷到一台:放進對得到、還沒刷滿的第一行(由舊到新)", () => {
  const lines = [{ order: 1, order_no: "TO-1", line: 12, open_qty: 2 }, { order: 2, order_no: "TO-2", line: 22, open_qty: 1 }];
  let got = placeScan(NO_PICKS, found(1, lines));
  assert.deepEqual([got.line, got.order, got.picks.serials], [12, 1, { 12: [1] }]);
  got = placeScan(got.picks, found(2, lines));
  assert.deepEqual(got.picks.serials, { 12: [1, 2] });
  got = placeScan(got.picks, found(3, lines));
  assert.deepEqual([got.line, got.order, got.picks.serials], [22, 2, { 12: [1, 2], 22: [3] }]);
  assert.deepEqual(placeScan(got.picks, found(4, lines)), { error: "S4(iPhone 17)對得到的單都刷滿了" });
});

test("同一台刷兩次只算一次", () => {
  const lines = [{ order: 1, order_no: "TO-1", line: 12, open_qty: 2 }];
  const got = placeScan(NO_PICKS, found(1, lines));
  assert.deepEqual(placeScan(got.picks, found(1, lines)), { error: "S1 刷過了" });
});

test("中古機那一行可以用手點:出這一台 / 不出", () => {
  const on = toggleUnit(NO_PICKS, unitLine);
  assert.deepEqual(on.serials, { 11: [901] });
  assert.deepEqual(toggleUnit(on, unitLine).serials, { 11: [] });
  assert.equal(toggleUnit(NO_PICKS, phoneLine), NO_PICKS);                       // 不是指定哪一台的行點了沒有用
  assert.equal(toggleUnit(NO_PICKS, { ...unitLine, open_qty: 0 }), NO_PICKS);    // 出完了、不出了
});

test("刷錯的一台可以拿掉", () => {
  assert.deepEqual(unpick({ serials: { 12: [1, 2] }, qty: {} }, 12, 1).serials, { 12: [2] });
});

test("不帶序號的那一行:預設出還沒出的全部,可以改少,不會超過", () => {
  assert.equal(pickQty(NO_PICKS, caseLine), 6);
  assert.equal(pickQty(setQty(NO_PICKS, caseLine, "2"), caseLine), 2);
  assert.equal(pickQty(setQty(NO_PICKS, caseLine, "99"), caseLine), 6);
  assert.equal(setQty(NO_PICKS, caseLine, "99").qty[13], 6);                    // 記下來的就是收過的數(不是靠顯示時才收)
  assert.equal(pickQty(setQty(NO_PICKS, caseLine, ""), caseLine), 0);
  assert.equal(pickQty(setQty(NO_PICKS, caseLine, "abc"), caseLine), 0);
  assert.equal(pickQty(setQty(NO_PICKS, caseLine, "1.5"), caseLine), 0);
});

test("帶序號的那一行:刷幾台出幾台(沒刷 = 不出)", () => {
  assert.equal(pickQty(NO_PICKS, phoneLine), 0);
  assert.equal(pickQty({ serials: { 12: [7] }, qty: {} }, phoneLine), 1);
});

test("送出去的只有要出的那幾行;出完的那一行不送", () => {
  const picks = setQty({ serials: { 11: [901] }, qty: {} }, caseLine, "2");
  assert.deepEqual(shipLines(order, picks), [
    { line: 11, qty: 1, serials: [901] },
    { line: 13, qty: 2, serials: [] },
  ]);
  assert.equal(shipTotal(order, picks), 15000 + 702);
  assert.deepEqual(shipLines(order, setQty(NO_PICKS, caseLine, "0")), []);
  // 已經出完 / 不出的那一行,就算還留著先前刷的碼也不送
  assert.deepEqual(shipLines({ id: 2, lines: [{ ...unitLine, open_qty: 0, shipped_qty: 1 }] }, { serials: { 11: [901] }, qty: {} }), []);
});

test("運費:空的是 0,只收 0 到 99999 的整數", () => {
  assert.deepEqual([feeOf(""), feeOf(" 120 "), feeOf("0"), feeOf("99999")], [0, 120, 0, 99999]);
  assert.deepEqual([feeOf("-1"), feeOf("1.5"), feeOf("100000"), feeOf("abc")], [null, null, null, null]);
});

test("收款金額:1 以上的整數(可以帶千分位)", () => {
  assert.deepEqual([amountOf("20,000"), amountOf("1"), amountOf("99999999")], [20000, 1, 99999999]);
  assert.deepEqual([amountOf(""), amountOf("0"), amountOf("-5"), amountOf("1.5"), amountOf("100000000")], [null, null, null, null, null]);
});

test("批發價:空的 = 照規則算;填的要是正的整數", () => {
  assert.deepEqual([priceOf(""), priceOf("14,200"), priceOf("0"), priceOf("12.5"), priceOf("abc")], [undefined, 14200, null, null, null]);
});

test("批發價預填跟伺服器同一個算法", () => {
  assert.equal(autoPrice("price_minus", 1000, 16000, 12000), 15000);
  assert.equal(autoPrice("price_percent", 90, 16000, 12000), 14400);
  assert.equal(autoPrice("cost_plus", 800, 16000, 12000), 12800);
  assert.equal(autoPrice("price_minus", 20000, 16000, 12000), null);      // 算出來不是正的:空著讓人填
  assert.equal(autoPrice("price_percent", 33, 9999, 0), 3300);            // 3299.67 → 四捨五入
});

test("一行的進度與收件那一句", () => {
  assert.equal(lineProgress({ qty: 3, shipped_qty: 0, cancelled_qty: 0 }), "訂 3");
  assert.equal(lineProgress({ qty: 3, shipped_qty: 1, cancelled_qty: 1 }), "訂 3 出 1 不出 1");
  assert.equal(lineProgress({ qty: 3, shipped_qty: 2, cancelled_qty: 1, received_qty: 1 }), "訂 3 出 2 收 1 不出 1");
  assert.equal(shipTo({ delivery_method: "宅配", ship_name: "乙一店", ship_phone: "035550000", ship_address: "新竹市" }), "宅配 乙一店 035550000 新竹市");
  assert.equal(shipTo({ delivery_method: "自取", ship_name: "", ship_phone: "", ship_address: "" }), "自取");
});

test("銷貨被擋:認得出是「被同行訂走」的才問要不要抽回", () => {
  const units = [{ serial: "9", serial_no: "U9", name: "中古 iPhone", order_no: "TO-000001", partner: "乙通訊行" }];
  assert.deepEqual(heldUnits({ detail: "…", code: "trade_hold", units }), units);
  assert.equal(heldUnits({ detail: "庫存不足" }), null);
  assert.equal(heldUnits({ code: "trade_hold", units: [] }), null);
  assert.equal(heldUnits({ code: "something_else", units }), null);               // 別種錯誤就算帶著清單也不問
  assert.equal(heldUnits(null), null);
  assert.equal(heldUnits("trade_hold"), null);
});

test("出貨之前提醒收款:月結不提醒;預收夠了講預收多少;不夠講還差多少(只提醒)", async () => {
  const { prepayNote } = await import("./trade.ts");
  assert.equal(prepayNote({ payment_method: "月結", credit: 0 }, 15000), null);
  assert.equal(prepayNote({ payment_method: "匯款", credit: 0 }, 0), null);
  assert.deepEqual(prepayNote({ payment_method: "匯款", credit: 0 }, 15000), { text: "未收款 還差 15,000", warn: true });
  assert.deepEqual(prepayNote({ payment_method: "匯款", credit: 5000 }, 15000), { text: "未收款 還差 10,000", warn: true });
  assert.deepEqual(prepayNote({ payment_method: "現金", credit: 15000 }, 15000), { text: "預收 15,000", warn: false });
  assert.deepEqual(prepayNote({ payment_method: "匯款" }, 100), { text: "未收款 還差 100", warn: true });
});

// ── 中古機上架:同型號幾百台,篩出一群、整群同價 ──────────────────────────────────────────
const unit = (serial, grade, battery, note = "", extra = {}) => ({
  serial, product: 5, serial_no: `U${serial}`, imei: `35${serial}`, sn: `U${serial}`, grade, battery, note,
  retail_price: 16000, auto_price: 15000, is_listed: true, price: 15000, own: false, rule: null, ...extra,
});
const stock = [
  unit(1, "A", 92), unit(2, "A", 88, "螢幕小刮"), unit(3, "B", 85), unit(4, "A", 100), unit(5, "", null), unit(6, "C", 79, "無盒"),
  unit(7, "S", 100), unit(8, "B", null, "換過電池"),
];
const only = (f) => filterUnits(stock, { ...NO_UNIT_FILTER, ...f }).map((r) => r.serial);

test("排序:成色 S 到 D、沒評的最後;同成色電池高的在前", () => {
  assert.deepEqual(sortUnits(stock).map((r) => r.serial), [7, 4, 1, 2, 3, 8, 6, 5]);
});

test("篩選:成色一次一個、電池上下限、有沒有備註、序號或備註裡的字", () => {
  assert.deepEqual(only({}), [1, 2, 3, 4, 5, 6, 7, 8]);
  assert.deepEqual(only({ grade: "A" }), [1, 2, 4]);
  assert.deepEqual(only({ grade: "" }), [5]);                              // 沒評級的那一顆
  assert.deepEqual(only({ grade: "A", noted: "no" }), [1, 4]);
  assert.deepEqual(only({ grade: "A", noted: "yes" }), [2]);
  assert.deepEqual(only({ batteryMin: "90" }), [1, 4, 7]);                 // 沒記電池的不算符合
  assert.deepEqual(only({ batteryMax: "85" }), [3, 6]);
  assert.deepEqual(only({ batteryMin: "85", batteryMax: "92" }), [1, 2, 3]);
  assert.deepEqual(only({ batteryMin: "abc" }), []);                       // 打錯:不是「全部都符合」
  assert.deepEqual(only({ batteryMax: "101" }), []);
  assert.deepEqual(only({ q: "無盒" }), [6]);
  assert.deepEqual(only({ q: "u7" }), [7]);
  assert.deepEqual(only({ q: "358" }), [8]);
  assert.deepEqual([percentOf(""), percentOf(" 80 "), percentOf("100"), percentOf("101"), percentOf("8.5"), percentOf("-1")],
    [undefined, 80, 100, null, null, null]);
});

test("每一顆上面的台數:別的條件照舊、只換這一顆會剩幾台", () => {
  let got = unitFacets(stock, NO_UNIT_FILTER);
  assert.deepEqual(got.grades, [{ grade: "S", count: 1 }, { grade: "A", count: 3 }, { grade: "B", count: 2 }, { grade: "C", count: 1 }, { grade: "", count: 1 }]);
  assert.deepEqual([got.noted, got.plain, got.own], [3, 5, 0]);
  assert.equal(unitFacets([...stock, unit(9, "A", 90, "", { own: true })], { ...NO_UNIT_FILTER, onlyOwn: true }).own, 1);   // 那一顆不受自己影響
  assert.deepEqual(filterUnits([...stock, unit(9, "A", 90, "", { own: true })], { ...NO_UNIT_FILTER, onlyOwn: true }).map((r) => r.serial), [9]);
  got = unitFacets(stock, { ...NO_UNIT_FILTER, grade: "A" });
  assert.deepEqual([got.noted, got.plain], [1, 2]);                        // A 級裡面有備註的
  assert.equal(got.grades.find((g) => g.grade === "B").count, 2);          // 成色那一排不受自己影響
  got = unitFacets(stock, { ...NO_UNIT_FILTER, noted: "yes" });
  assert.deepEqual(got.grades.map((g) => [g.grade, g.count]), [["A", 1], ["B", 1], ["C", 1]]);
});

// ── 價目表:一格 = 成色 + 電池區間 + 有沒有備註;符合的都用那個價,獨立定價的不跟 ──────────────────────
const rule = (id, price, cell = {}, followers = 0) => {
  const full = { grade: "", battery_min: 0, battery_max: 100, noted: "", ...cell };
  return { id, product: 5, price, followers, text: cellText(full), ...full };
};
const A = rule(1, 12000, { grade: "A" }, 100);
const A_LOW = rule(2, 11000, { grade: "A", battery_max: 84 }, 20);
const A_PLAIN = rule(3, 12500, { grade: "A", noted: "no" }, 80);
const ANY = rule(4, 10000, {}, 5);

test("篩選列上點的就是價目的那一格;電池打錯不能存", () => {
  assert.deepEqual(cellOf(NO_UNIT_FILTER), { grade: "", battery_min: 0, battery_max: 100, noted: "" });
  assert.deepEqual(cellOf({ ...NO_UNIT_FILTER, grade: "A", batteryMin: "85", noted: "no", q: "無盒", onlyOwn: true }),
    { grade: "A", battery_min: 85, battery_max: 100, noted: "no" });                // 搜尋、只看獨立不是價目的一部分
  assert.equal(cellOf({ ...NO_UNIT_FILTER, batteryMin: "abc" }), null);
  assert.equal(cellOf({ ...NO_UNIT_FILTER, batteryMin: "90", batteryMax: "80" }), null);
  assert.deepEqual([cellText(ANY), cellText(A), cellText(A_LOW), cellText(A_PLAIN), cellText({ grade: "B", battery_min: 80, battery_max: 89, noted: "yes" }),
    cellText({ grade: "", battery_min: 85, battery_max: 100, noted: "" })],
    ["全部", "A 級", "A 級 電池 84 以下", "A 級 沒備註", "B 級 電池 80–89 有備註", "電池 85 以上"]);
  assert.equal(sameCell(A, { grade: "A", battery_min: 0, battery_max: 100, noted: "" }), true);
  assert.equal(sameCell(A, A_LOW), false);
});

test("兩格都符合的時候比較細的那一格算數(成色 → 電池 → 備註),跟伺服器同一套", () => {
  const cells = [ANY, A, A_LOW, A_PLAIN];
  assert.equal(bestCell(cells, unit(1, "A", 90)).id, 3);                    // 沒備註的 A
  assert.equal(bestCell(cells, unit(2, "A", 90, "無盒")).id, 1);            // 有備註:不在「沒備註」那一格
  assert.equal(bestCell(cells, unit(3, "A", 80)).id, 2);                    // 有限電池的贏過指定備註的
  assert.equal(bestCell(cells, unit(4, "A", null)).id, 3);                  // 沒記電池的不算在有限電池的格子裡
  assert.equal(bestCell(cells, unit(5, "B", 90)).id, 4);
  assert.equal(bestCell([A, A_LOW], unit(6, "C", 90)), null);
  assert.equal(fitsCell({ grade: "", battery_min: 0, battery_max: 100, noted: "yes" }, unit(7, "C", 90, "  ")), false);   // 只有空白不算有備註
});

test("每一台顯示的價:獨立的是它自己的;跟價目的是存了之後它會用的那一格", () => {
  const follower = unit(1, "A", 90, "", { price: 12000 });
  const special = unit(2, "A", 90, "無盒", { price: 9500, own: true });
  const loose = unit(3, "B", 90, "", { price: 14000 });                      // 沒有符合的格子
  const cell = { grade: "A", battery_min: 0, battery_max: 100, noted: "" };
  const edits = { ...NO_UNIT_EDITS, cellPrice: "11500" };
  const cells = pendingCells([A], cell, edits, 5);
  assert.deepEqual(cells.map((c) => c.price), [11500]);                      // 同一格換成還沒存的價
  assert.deepEqual(pendingCells([A], cell, NO_UNIT_EDITS, 5), [A]);
  assert.deepEqual(pendingCells([A], cell, edits), [A]);                     // 沒講是哪個型號(全部型號):沒有價目那一格
  assert.deepEqual([followsNow(follower, edits), followsNow(special, edits)], [true, false]);
  assert.equal(unitPriceShown(follower, edits, cells), "11500");
  assert.equal(unitPriceShown(special, edits, cells), "9500");               // 獨立的不動
  assert.equal(unitPriceShown(loose, edits, cells), "14000");
  // 把勾拿掉:變獨立、顯示它現在的價;勾回來:顯示價目的價;在自己那一列打字:就是獨立
  assert.equal(unitPriceShown(follower, { ...edits, follow: { 1: false } }, cells), "12000");
  assert.equal(unitPriceShown(special, { ...edits, follow: { 2: true } }, cells), "11500");
  const typed = { ...edits, typed: { 1: "9000" } };
  assert.deepEqual([followsNow(follower, typed), unitPriceShown(follower, typed, cells)], [false, "9000"]);
  assert.equal(unitPriceShown(unit(4, "C", 90, "", { price: null }), NO_UNIT_EDITS, []), "");
});

test("改價:只送有變的;價目的價變了才送那一格", () => {
  const follower = unit(1, "A", 90, "", { price: 12000 });
  const second = unit(2, "A", 88, "", { price: 12000 });
  const special = unit(3, "A", 90, "無盒", { price: 9500, own: true });
  const shown = [follower, second, special];
  const cell = { grade: "A", battery_min: 0, battery_max: 100, noted: "" };
  let plan = unitPlan(shown, [A], cell, NO_UNIT_EDITS, false, 5);
  assert.equal(planIsEmpty(plan), true);                                     // 什麼都沒動
  plan = unitPlan(shown, [A], cell, { ...NO_UNIT_EDITS, cellPrice: "12000" }, false, 5);
  assert.equal(planIsEmpty(plan), true);                                     // 打了一樣的價
  plan = unitPlan(shown, [A], cell, { ...NO_UNIT_EDITS, cellPrice: "11500" }, false, 5);
  assert.deepEqual([plan.rows, plan.cell, plan.cell_price, plan.cellFrom], [[], cell, 11500, 12000]);   // 跟著的那幾台不用一台一台送
  // 取消一台的勾(獨立、價照舊)、把特殊的勾回來、另一台打自己的價
  plan = unitPlan(shown, [A], cell, { follow: { 1: false, 3: true }, typed: { 2: "11000" }, cellPrice: "" }, false, 5);
  assert.deepEqual(plan.rows, [{ serial: 1, own: true }, { serial: 2, price: 11000 }, { serial: 3 }]);
  assert.deepEqual([plan.toOwn, plan.toFollow, plan.priced, plan.cell], [1, 1, 1, undefined]);
  // 還沒有這一格:打了價就是新的一格
  plan = unitPlan(shown, [], cell, { ...NO_UNIT_EDITS, cellPrice: "12000" }, false, 5);
  assert.deepEqual([plan.cell, plan.cell_price, plan.cellFrom], [cell, 12000, null]);
  assert.deepEqual(unitPlan(shown, [A], cell, { ...NO_UNIT_EDITS, cellPrice: "abc" }, false, 5), { error: "價目要填正的整數" });
  assert.deepEqual(unitPlan(shown, [A], cell, { ...NO_UNIT_EDITS, typed: { 2: "0" } }, false, 5), { error: "U2 的批發價要填正的整數" });
  // 改不了價目的人(鎖門市、全部型號):沒有那一格,打了也不送
  plan = unitPlan(shown, [A], null, { ...NO_UNIT_EDITS, cellPrice: "11500" }, false, 5);
  assert.equal(planIsEmpty(plan), true);
});

test("上架:畫面上列出來的每一台都送;沒有價的要擋", () => {
  const cell = { grade: "A", battery_min: 0, battery_max: 100, noted: "" };
  const fresh = unit(1, "A", 90, "", { is_listed: false, price: null });
  const was = unit(2, "A", 90, "", { is_listed: false, price: 13800, own: true });       // 下架過的獨立定價
  const noPrice = unit(3, "B", 90, "", { is_listed: false, price: null, auto_price: null });
  let plan = unitPlan([fresh, was], [A], cell, NO_UNIT_EDITS, true, 5);
  assert.deepEqual([plan.rows, plan.listed], [[{ serial: 1 }, { serial: 2, own: true }], 2]);
  assert.deepEqual(unitPlan([noPrice], [A], cell, NO_UNIT_EDITS, true, 5), { error: "U3 的批發價要填正的整數" });
  assert.deepEqual(unitPlan([noPrice], [A], cell, { ...NO_UNIT_EDITS, follow: { 3: false } }, true, 5), { error: "U3 要獨立定價,請填價" });
  plan = unitPlan([noPrice], [A], cell, { ...NO_UNIT_EDITS, typed: { 3: "8000" } }, true, 5);
  assert.deepEqual(plan.rows, [{ serial: 3, price: 8000 }]);
  // 沒有符合的格子、但這一次順便定了「全部」那一格:有價了
  plan = unitPlan([noPrice], [], { grade: "", battery_min: 0, battery_max: 100, noted: "" }, { ...NO_UNIT_EDITS, cellPrice: "9000" }, true, 5);
  assert.deepEqual([plan.rows, plan.cell_price], [[{ serial: 3 }], 9000]);
});

test("要不要再按一次、按之前講什麼", () => {
  const cell = { grade: "A", battery_min: 0, battery_max: 100, noted: "no" };
  const shown = [unit(1, "A", 90, "", { price: 12000 }), unit(2, "A", 88, "", { price: 12000 })];
  let plan = unitPlan(shown, [A_PLAIN], cell, { ...NO_UNIT_EDITS, cellPrice: "11500" }, false, 5);
  assert.equal(unitNeedsConfirm(plan), true);                                // 改到價目:全公司符合的都會變
  assert.equal(unitConfirmText(plan, 80, [16000, 16000]), "A 級 沒備註 12500 → 11500 · 80 台");
  plan = unitPlan(shown, [], cell, { ...NO_UNIT_EDITS, cellPrice: "1150" }, false, 5);        // 新的一格、少打一個 0
  assert.equal(unitConfirmText(plan, null, [16000, 16000]), "A 級 沒備註 1150 · 價差大");
  plan = unitPlan(shown, [A_PLAIN], cell, { ...NO_UNIT_EDITS, follow: { 1: false } }, false, 5);
  assert.equal(unitNeedsConfirm(plan), true);                                // 變成獨立:之後不跟著動,要講清楚(紅隊:店員以為只是這次跳過)
  assert.equal(unitConfirmText(plan, null, []), "獨立 1 台");
  plan = unitPlan(shown, [A_PLAIN], cell, { ...NO_UNIT_EDITS, typed: { 1: "9000" } }, false, 5);
  assert.deepEqual([unitNeedsConfirm(plan), unitConfirmText(plan, null, [])], [false, "自訂 1 台"]);   // 一台打一個價:直接改
  plan = unitPlan([unit(1, "A", 90, "", { own: true })], [A_PLAIN], cell, { ...NO_UNIT_EDITS, follow: { 1: true } }, false, 5);
  assert.deepEqual([unitNeedsConfirm(plan), unitConfirmText(plan, null, [])], [false, "跟價目 1 台"]);
  const many = Array.from({ length: 12 }, (_, i) => unit(i + 1, "B", 90, "", { is_listed: false }));
  plan = unitPlan(many, [], null, NO_UNIT_EDITS, true, 5);
  assert.deepEqual([unitNeedsConfirm(plan), unitConfirmText(plan, null, [])], [true, "上架 12 台"]);
});

test("型號清單上當場改價目:只送真的變了的那幾格", () => {
  const rules = [A, A_LOW, ANY];
  assert.deepEqual(cellEdits(rules, {}), { cells: [], followers: 0 });
  assert.deepEqual(cellEdits(rules, { 1: "12000", 2: "10800" }), { cells: [{ id: 2, price: 10800 }], followers: 20 });   // 打回原本的價不算
  assert.deepEqual(cellEdits(rules, { 1: "11,500", 4: "9500" }), { cells: [{ id: 1, price: 11500 }, { id: 4, price: 9500 }], followers: 105 });
  assert.deepEqual(cellEdits(rules, { 2: "" }), { error: "「A 級 電池 84 以下」的價要填正的整數" });
  assert.deepEqual(cellEdits(rules, { 2: "abc" }), { error: "「A 級 電池 84 以下」的價要填正的整數" });
});

test("上一份清單一列都不算:換門市的那一下不會勾到上一間門市的", () => {
  assert.deepEqual(currentRows(stock, false).map((r) => r.serial), stock.map((r) => r.serial));
  assert.deepEqual(currentRows(stock, true), []);                          // 手上是上一份(新的還沒回來)
  assert.deepEqual(currentRows(undefined, false), []);
  // 上一份不算 → 篩出來是空的 → 在「同價」打字不會勾到任何一台、也送不出去
  assert.deepEqual(filterUnits(currentRows(stock, true), NO_UNIT_FILTER), []);
});

test("全部型號那個入口:每一台只用它自己那個型號的價目(複審 P1:勾回來顯示的價要跟存下去的一樣)", () => {
  const other = { ...rule(9, 8000, { grade: "A" }), product: 6, followers: null };
  const mine = unit(1, "A", 90, "", { price: 15000, own: true });           // 型號 5,獨立 15000
  const theirs = unit(2, "A", 90, "", { product: 6, price: 9000, own: true });
  const edits = { ...NO_UNIT_EDITS, follow: { 1: true, 2: true } };
  const cells = pendingCells([A, other], cellOf(NO_UNIT_FILTER), edits);   // 沒有型號:不加價目那一格
  assert.equal(unitPriceShown(mine, edits, cells), "12000");                 // 型號 5 的 A 級
  assert.equal(unitPriceShown(theirs, edits, cells), "8000");               // 型號 6 的 A 級
  const plan = unitPlan([mine, theirs], [A, other], cellOf(NO_UNIT_FILTER), { ...edits, cellPrice: "7000" }, false);
  assert.deepEqual([plan.rows, plan.cell, plan.toFollow], [[{ serial: 1 }, { serial: 2 }], undefined, 2]);   // 全部型號不能改價目那一格
});

test("剛加的外部同行那一格:報價連結跟著清單上最新的(換新之後不會複製到舊的)", () => {
  const issued = { id: 7, quote: { path: "/api/trade/quote/old/", on: true } };
  assert.deepEqual(liveQuote(issued, [{ id: 7, quote: { path: "/api/trade/quote/new/", on: true } }]), { path: "/api/trade/quote/new/", on: true });
  assert.deepEqual(liveQuote(issued, [{ id: 7, quote: { path: "/api/trade/quote/old/", on: false } }]).on, false);
  assert.deepEqual(liveQuote(issued, []), issued.quote);                      // 清單還沒回來:先用建立當下的
});
