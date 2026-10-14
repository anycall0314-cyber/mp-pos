// 批發(賣家)在畫面這一側:刷機配單、這一次出什麼、金額輸入、批發價預填。跑法:npm test。
import assert from "node:assert/strict";
import test from "node:test";

import {
  NO_PICKS, NO_UNIT_FILTER, amountOf, autoPrice, currentRows, feeOf, filterUnits, heldUnits, lineProgress, percentOf, pickQty, placeScan, priceOf, setQty,
  shipLines, shipTo, shipTotal, sortUnits, toggleUnit, unitBatch, unitConfirmText, unitFacets, unitNeedsConfirm, unitPriceText, unpick,
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
  serial, serial_no: `U${serial}`, imei: `35${serial}`, sn: `U${serial}`, grade, battery, note,
  retail_price: 16000, auto_price: 15000, is_listed: true, price: 15000, ...extra,
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
  assert.deepEqual([got.noted, got.plain], [3, 5]);
  got = unitFacets(stock, { ...NO_UNIT_FILTER, grade: "A" });
  assert.deepEqual([got.noted, got.plain], [1, 2]);                        // A 級裡面有備註的
  assert.equal(got.grades.find((g) => g.grade === "B").count, 2);          // 成色那一排不受自己影響
  got = unitFacets(stock, { ...NO_UNIT_FILTER, noted: "yes" });
  assert.deepEqual(got.grades.map((g) => [g.grade, g.count]), [["A", 1], ["B", 1], ["C", 1]]);
});

test("批發價那一格:自己打的 → 有勾才吃上面整群的價 → 原本的價 → 空的", () => {
  const a = unit(1, "A", 92);
  assert.equal(unitPriceText(a, {}, "", true), "15000");
  assert.equal(unitPriceText(a, {}, "12000", true), "12000");
  assert.equal(unitPriceText(a, {}, "12000", false), "15000");            // 沒勾的不會變
  assert.equal(unitPriceText(a, { 1: "11000" }, "12000", true), "11000");
  assert.equal(unitPriceText(a, { 1: "" }, "12000", true), "");            // 自己清空 = 照規則,不是吃整群的價
  // 下架過的那一台:帶它上一次的價,不是悄悄換成照規則的價(紅隊)
  assert.equal(unitPriceText(unit(9, "A", 90, "", { is_listed: false, price: 13800 }), {}, "", true), "13800");
  assert.equal(unitPriceText(unit(9, "A", 90, "", { is_listed: false, price: null }), {}, "", true), "");
});

test("送出去的那一批:整群的價、各自的價、照規則的分開算", () => {
  const [a, b, c] = [unit(1, "A", 92), unit(2, "A", 88, "螢幕小刮"), unit(3, "A", 85, "", { is_listed: false, price: null })];
  assert.deepEqual(unitBatch([a, b, c], { 2: "11500" }, "12000"),
    { rows: [{ serial: 1, price: 12000 }, { serial: 2, price: 11500 }, { serial: 3, price: 12000 }], grouped: 2 });
  // 上面空著:上架中的照原本的價送(不會變),沒上過架的照規則
  assert.deepEqual(unitBatch([a, c], {}, ""), { rows: [{ serial: 1, price: 15000 }, { serial: 3 }], grouped: 0 });
  assert.deepEqual(unitBatch([a], {}, "abc"), { error: "批發價要填正的整數" });
  assert.deepEqual(unitBatch([a, b], { 2: "0" }, ""), { error: "U2 的批發價要填正的整數" });
  assert.deepEqual(unitBatch([{ ...c, auto_price: null }], {}, ""), { error: "U3 的批發價要填正的整數" });   // 算不出來又沒填
  assert.deepEqual(unitBatch([{ ...c, auto_price: null }], {}, "9000"), { rows: [{ serial: 3, price: 9000 }], grouped: 1 });
});

test("要不要再按一次:好幾台同一個價、或一次動到很多台", () => {
  assert.equal(unitNeedsConfirm(1, 1), false);                             // 一台打一個價
  assert.equal(unitNeedsConfirm(3, 0), false);                             // 三台各自的價
  assert.equal(unitNeedsConfirm(2, 2), true);
  assert.equal(unitNeedsConfirm(10, 0), true);
  assert.equal(unitNeedsConfirm(9, 0), false);
});

test("再按一次之前的那一句:幾台、什麼價、原本多少;跟門市價差很多另外講", () => {
  const group = [unit(1, "A", 92, "", { price: 11500 }), unit(2, "A", 88, "", { price: 13000 }), unit(3, "A", 85, "", { price: 12000 })];
  let batch = unitBatch(group, {}, "12000");
  assert.equal(unitConfirmText("改價", group, batch, "12000"), "3 台都改成 12000,原本 11500–13000");
  batch = unitBatch(group, { 2: "9000" }, "12000");
  assert.equal(unitConfirmText("改價", group, batch, "12000"), "2 台都改成 12000,原本 11500–13000,另外 1 台各自的價");
  batch = unitBatch(group, {}, "1200");                                    // 少打一個 0
  assert.equal(unitConfirmText("改價", group, batch, "1200"), "3 台都改成 1200,原本 11500–13000,跟門市價差很多");
  batch = unitBatch(group, {}, "17000");                                   // 比門市價還貴
  assert.match(unitConfirmText("改價", group, batch, "17000"), /跟門市價差很多$/);
  const same = [unit(1, "A", 92), unit(2, "A", 88)];
  assert.equal(unitConfirmText("上架", same, unitBatch(same, {}, "14000"), "14000"), "2 台都用 14000,原本 15000");
  const many = Array.from({ length: 12 }, (_, i) => unit(i + 1, "A", 90));
  assert.equal(unitConfirmText("上架", many, unitBatch(many, {}, ""), ""), "上架 12 台");
});

test("上一份清單一列都不算:換門市的那一下不會勾到上一間門市的", () => {
  assert.deepEqual(currentRows(stock, false).map((r) => r.serial), stock.map((r) => r.serial));
  assert.deepEqual(currentRows(stock, true), []);                          // 手上是上一份(新的還沒回來)
  assert.deepEqual(currentRows(undefined, false), []);
  // 上一份不算 → 篩出來是空的 → 在「同價」打字不會勾到任何一台、也送不出去
  assert.deepEqual(filterUnits(currentRows(stock, true), NO_UNIT_FILTER), []);
});
