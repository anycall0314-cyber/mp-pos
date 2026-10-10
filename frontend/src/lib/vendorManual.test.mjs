// 半自動廠商在畫面這一側:紀錄上的記號、到貨入庫填到一半的樣子、合計與擋不擋、還不知道結果的那一次、Excel 貼上怎麼拆。跑法:npm test。
import assert from "node:assert/strict";
import test from "node:test";

import {
  IMPORT_LABEL, PASTE_COLUMNS, addExtra, addable, cancelReminder, fillAll, freightOf, manualBlocked, manualMark,
  manualPendingFrom, manualPendingOf, manualSummary, needsSending, parseSheet, priceOf, priceText, removeExtra, shownLines,
  startManualDraft, withManualQty, withPrice,
} from "./vendorManual.ts";
import { withProduct, withRepick } from "./vendorReceive.ts";

const CABLE = { id: 7, sku: "CH-0007", name: "甲 快充線 1M", is_active: true };
const line = (key, extra = {}) => ({
  key, sku: key.split("|")[0], spec_id: null, spec_label: "", name: `品${key.split("|")[0]}`, unit: "條", pack_qty: 10,
  is_reissue: false, qty: 20, shipped_qty: 20, received_qty: 0, remaining_qty: 20, suggested_qty: 0, unit_price: "45.00",
  product: null, ...extra,
});
const PLAN = {
  order: 1, vendor_order_no: "VO-000001", manual: true, vendor_status: "", vendor_logistics_status: "", vendor_tracking_no: "",
  payment_method: "月結", shipping_fee: "0.00", freight_into_cost: true, freight_left: "0.00", supplier: null, issue_note: "上次少一包",
  lines: [
    line("C01||p", { product: CABLE }),
    line("H01||p", { qty: 5, shipped_qty: 5, remaining_qty: 5, unit_price: null }),       // 沒有參考價
    line("G01||p", { qty: 10, received_qty: 12, remaining_qty: -2, unit_price: "42.50" }),  // 已經入超過
  ],
  extras: [line("C02||p", { qty: 0, shipped_qty: 0, remaining_qty: 0, unit_price: "60.00" }), line("Z01||p", { qty: 0, remaining_qty: 0, unit_price: null })],
};

test("紀錄上的記號:取消蓋過其他;三個字數一樣;還沒傳又沒取消的要提醒", () => {
  assert.equal(manualMark({ sent_at: null, cancelled_at: null }), "未傳出");
  assert.equal(manualMark({ sent_at: "2026-10-11T10:00:00+08:00", cancelled_at: null }), "已傳出");
  assert.equal(manualMark({ sent_at: "2026-10-11T10:00:00+08:00", cancelled_at: "2026-10-11T11:00:00+08:00" }), "已取消");
  assert.equal(manualMark({ sent_at: null, cancelled_at: "2026-10-11T11:00:00+08:00" }), "已取消");
  assert.deepEqual([...new Set(["已取消", "未傳出", "已傳出"].map((s) => s.length))], [3]);
  assert.equal(needsSending({ manual: true, sent_at: null, cancelled_at: null }), true);
  assert.equal(needsSending({ manual: true, sent_at: "x", cancelled_at: null }), false);
  assert.equal(needsSending({ manual: true, sent_at: null, cancelled_at: "x" }), false);
  assert.equal(needsSending({ manual: false, sent_at: null, cancelled_at: null }), false);     // 直接送到廠商系統的不用
});

test("取消已經傳出去的單要提醒通知廠商;還沒傳的不用", () => {
  assert.equal(cancelReminder({ sent_at: "x" }, "乙配件"), "已取消。這張已經傳給乙配件了,記得通知他們");
  assert.equal(cancelReminder({ sent_at: null }, "乙配件"), "已取消");
});

test("打開面板:數量一格都不帶;單價先帶參考價(沒有的空著);品號不抄進草稿", () => {
  const draft = startManualDraft(PLAN, "recv-abcdefgh");
  assert.deepEqual(draft, {
    requestKey: "recv-abcdefgh", qty: {}, price: { "C01||p": "45", "G01||p": "42.5", "C02||p": "60" }, product: {}, repick: {},
    added: [], freight: "", note: "上次少一包",
  });
  assert.equal(priceText("45.00"), "45");
  assert.equal(priceText("42.50"), "42.5");
  assert.equal(priceText("0.00"), "0");
  for (const none of [null, undefined, "", "abc"]) assert.equal(priceText(none), "", String(none));
});

test("單價只收一般的寫法,0 到 9,999,999.99、最多兩位小數", () => {
  for (const [text, n] of [["45", 45], ["42.5", 42.5], ["0", 0], ["0.05", 0.05], [" 118 ", 118], ["9999999.99", 9999999.99]]) {
    assert.equal(priceOf(text), n, text);
  }
  for (const bad of ["", " ", undefined, "abc", "-1", "+5", "1.234", "1,200", "1e2", "12345678", ".5", "5.", "$45"]) {
    assert.equal(priceOf(bad), null, String(bad));
  }
});

test("運費:整數元,空的是 0,亂寫的不算", () => {
  assert.equal(freightOf(""), 0);
  assert.equal(freightOf("  "), 0);
  assert.equal(freightOf("80"), 80);
  assert.equal(freightOf("9999999"), 9999999);
  for (const bad of ["80.5", "-1", "abc", "12345678", "1,000"]) assert.equal(freightOf(bad), null, bad);
});

test("改數量與單價:0 個的不留;原本那一份不被改到", () => {
  const draft = startManualDraft(PLAN, "recv-abcdefgh");
  const a = withManualQty(draft, "C01||p", 20);
  assert.deepEqual([a.qty, draft.qty], [{ "C01||p": 20 }, {}]);
  assert.deepEqual(withManualQty(a, "C01||p", 0).qty, {});
  assert.deepEqual(withManualQty(a, "C01||p", -3).qty, {});
  assert.deepEqual(withManualQty(a, "C01||p", 1.5).qty, {});
  assert.equal(withManualQty(a, "C01||p", 1e9).qty["C01||p"], 99999);
  const b = withPrice(draft, "H01||p", "118");
  assert.deepEqual([b.price["H01||p"], draft.price["H01||p"]], ["118", undefined]);
  assert.equal(b.requestKey, "recv-abcdefgh");
});

test("全部到齊:每一行帶還沒入的;入超過的不帶;單價、品號、加的品項不動", () => {
  const draft = withPrice(addExtra(PLAN, startManualDraft(PLAN, "recv-abcdefgh"), "C02||p"), "H01||p", "118");
  const all = fillAll(PLAN, withManualQty(draft, "C02||p", 3));
  assert.deepEqual(all.qty, { "C01||p": 20, "H01||p": 5 });       // G01 已經入超過;加進來的 C02 回到沒填
  assert.deepEqual([all.price, all.added], [draft.price, ["C02||p"]]);
});

test("加一項這張單沒叫的:只能加伺服器說可以加的,不重複;拿掉時數量一起清", () => {
  const start = startManualDraft(PLAN, "recv-abcdefgh");
  const one = addExtra(PLAN, start, "C02||p");
  assert.deepEqual([one.added, start.added], [["C02||p"], []]);
  assert.equal(addExtra(PLAN, one, "C02||p"), one);                 // 加過的
  assert.equal(addExtra(PLAN, one, "NOPE||p"), one);                // 不在可以加的裡面
  assert.equal(addExtra(PLAN, one, "C01||p"), one);                 // 本來就在單上
  const two = addExtra(PLAN, one, "Z01||p");
  assert.deepEqual(shownLines(PLAN, two).map((l) => l.key), ["C01||p", "H01||p", "G01||p", "C02||p", "Z01||p"]);
  assert.deepEqual(addable(PLAN, two), []);
  assert.deepEqual(addable(PLAN, one).map((l) => l.key), ["Z01||p"]);
  const back = removeExtra(withManualQty(two, "C02||p", 10), "C02||p");
  assert.deepEqual([back.added, back.qty, back.price["C02||p"]], [["Z01||p"], {}, "60"]);
  // 伺服器重抓之後那一項不能加了:畫面不列
  assert.deepEqual(shownLines({ ...PLAN, extras: [] }, two).map((l) => l.key), ["C01||p", "H01||p", "G01||p"]);
});

test("合計:只算這一次要入的;要入的每一行都要有單價與品號;比叫的多只記下來", () => {
  let draft = startManualDraft(PLAN, "recv-abcdefgh");
  assert.deepEqual(manualSummary(PLAN, draft), { lines: [], pieces: 0, amount: 0, unmapped: [], unpriced: [], over: [], freight: 0 });
  assert.equal(manualBlocked(manualSummary(PLAN, draft)), "這一次沒有要入庫的東西");
  draft = withManualQty(withManualQty(withManualQty(draft, "C01||p", 20), "H01||p", 5), "G01||p", 1);
  let sum = manualSummary(PLAN, draft);
  assert.equal(sum.pieces, 26);
  assert.equal(sum.amount, 20 * 45 + 1 * 42.5);                     // 充電頭還沒填單價,不算進去
  assert.deepEqual([sum.unpriced, sum.unmapped, sum.over], [["品H01"], ["品H01", "品G01"], ["品G01"]]);
  assert.deepEqual(sum.lines, [{ key: "C01||p", qty: 20, product: 7, was: 7, unit_price: "45" }]);
  assert.equal(manualBlocked(sum), "還沒填實際單價:品H01");          // 先講單價
  // 品號選好了、單價還沒填:這一行不能送出去(不能把空的單價當成 0 元)
  const noPrice = manualSummary(PLAN, withProduct(draft, "H01||p", { id: 8, label: "充電頭" }));
  assert.deepEqual([noPrice.lines.map((l) => l.key), noPrice.unpriced], [["C01||p"], ["品H01"]]);
  draft = withPrice(draft, "H01||p", " 118 ");
  assert.equal(manualBlocked(manualSummary(PLAN, draft)), "還沒選品號:品H01、品G01");
  draft = withProduct(withProduct(draft, "H01||p", { id: 8, label: "充電頭" }), "G01||p", { id: 9, label: "別的線" });
  sum = manualSummary(PLAN, draft);
  assert.equal(manualBlocked(sum), null);                           // 比叫的多(G01)不擋
  assert.deepEqual(sum.lines, [
    { key: "C01||p", qty: 20, product: 7, was: 7, unit_price: "45" },
    { key: "H01||p", qty: 5, product: 8, was: null, unit_price: "118" },
    { key: "G01||p", qty: 1, product: 9, was: null, unit_price: "42.5" },
  ]);
  assert.equal(sum.amount, 900 + 590 + 42.5);
  // 運費亂寫:擋
  assert.equal(manualBlocked(manualSummary(PLAN, { ...draft, freight: "8o" })), "運費要是整數");
  assert.equal(manualSummary(PLAN, { ...draft, freight: "80" }).freight, 80);
});

test("加進來的品項一樣算;按了「改」換品號帶著畫面上原本對到誰;0 元可以(沒收錢的)", () => {
  let draft = addExtra(PLAN, startManualDraft(PLAN, "recv-abcdefgh"), "C02||p");
  draft = withProduct(withManualQty(draft, "C02||p", 10), "C02||p", { id: 11, label: "2M 線" });
  draft = withProduct(withRepick(withManualQty(withPrice(draft, "C01||p", "0"), "C01||p", 2), PLAN.lines[0]), "C01||p", { id: 12, label: "換一個" });
  const sum = manualSummary(PLAN, draft);
  assert.deepEqual(sum.lines, [
    { key: "C01||p", qty: 2, product: 12, was: 7, unit_price: "0" },
    { key: "C02||p", qty: 10, product: 11, was: null, unit_price: "60" },
  ]);
  assert.deepEqual([sum.amount, sum.over, manualBlocked(sum)], [600, ["品C02"], null]);   // 加進來的那一項本來就沒叫:算「比叫的多」
});

test("還不知道結果的那一次:記下來的就是送出去的那一份;讀不懂的整份不要", () => {
  let draft = withManualQty(startManualDraft(PLAN, "recv-abcdefgh"), "C01||p", 20);
  draft = { ...draft, freight: "80", note: "少一包" };
  const pending = manualPendingOf(draft, manualSummary(PLAN, draft));
  assert.deepEqual(pending, {
    requestKey: "recv-abcdefgh", lines: [{ key: "C01||p", qty: 20, product: 7, was: 7, unit_price: "45" }], pieces: 20,
    note: "少一包", freight: 80,
  });
  assert.deepEqual(manualPendingFrom(JSON.stringify(pending)), pending);
  assert.deepEqual(manualPendingFrom(JSON.stringify({ ...pending, pieces: 999, note: 5 })), { ...pending, note: "" });
  const lineOf = (extra) => JSON.stringify({ ...pending, lines: [{ ...pending.lines[0], ...extra }] });
  for (const bad of [null, undefined, "", "{", "[]", "7",
    JSON.stringify({ ...pending, requestKey: "x" }), JSON.stringify({ ...pending, lines: [] }), JSON.stringify({ ...pending, freight: -1 }),
    JSON.stringify({ ...pending, freight: "80" }), JSON.stringify({ ...pending, freight: undefined }),
    lineOf({ qty: 0 }), lineOf({ product: 0 }), lineOf({ key: "" }), lineOf({ unit_price: 45 }), lineOf({ unit_price: "abc" }),
    lineOf({ unit_price: undefined }), lineOf({ was: "7" }), lineOf({ was: 0 })]) {
    assert.equal(manualPendingFrom(bad), null, String(bad));
  }
  assert.deepEqual(manualPendingFrom(lineOf({ was: null })).lines[0].was, null);
});

test("Excel 貼上:有欄名照欄名(順序隨意、可以少欄、認不得的略過);沒有欄名照固定順序;空行略過", () => {
  const withHeader = "料號\t品名\t單價\t備註\t入數\r\nC01\t快充線 1M\t45\t熱賣\t10\r\n\r\n\t行動電源\t$1,250\t\t\n";
  assert.deepEqual(parseSheet(withHeader), [
    { name: "快充線 1M", spec: "", sku: "C01", kind: "", unit: "", pack_qty: "10", ref_price: "45" },
    { name: "行動電源", spec: "", sku: "", kind: "", unit: "", pack_qty: "", ref_price: "$1,250" },
  ]);
  const plain = " 快充線 \t1M\tC01\t線材\t條\t10\t45\n充電頭\n";
  assert.deepEqual(parseSheet(plain), [
    { name: "快充線", spec: "1M", sku: "C01", kind: "線材", unit: "條", pack_qty: "10", ref_price: "45" },
    { name: "充電頭", spec: "", sku: "", kind: "", unit: "", pack_qty: "", ref_price: "" },
  ]);
  assert.deepEqual(parseSheet(""), []);
  assert.deepEqual(parseSheet("\n\t\t\n"), []);
  // 欄名重複時用第一個;多出來的格子不理
  assert.deepEqual(parseSheet("品名\t品名\nA\tB\tC")[0].name, "A");
  assert.deepEqual(parseSheet("甲\t\t\t\t\t\t\t多的\t再多")[0].name, "甲");
  assert.deepEqual(PASTE_COLUMNS.map((c) => c.label), ["品名", "規格", "料號", "種類", "單位", "一包幾個", "參考單價"]);
});

test("預覽上的四個字:字數一樣", () => {
  assert.deepEqual(Object.keys(IMPORT_LABEL).sort(), ["error", "new", "same", "update"]);
  assert.deepEqual([...new Set(Object.values(IMPORT_LABEL).map((s) => s.length))], [2]);
});
