// 批發(賣家)在畫面這一側:刷機配單、這一次出什麼、金額輸入、批發價預填。跑法:npm test。
import assert from "node:assert/strict";
import test from "node:test";

import {
  NO_PICKS, amountOf, autoPrice, feeOf, heldUnits, lineProgress, pickQty, placeScan, priceOf, setQty, shipLines, shipTo, shipTotal,
  toggleUnit, unpick,
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
