// 到貨入庫在畫面這一側:這一次每一行入幾個、哪幾行還沒選品號、合計。跑法:npm test。
import assert from "node:assert/strict";
import test from "node:test";

import {
  blocked, fill, lineState, lineTitle, mayReceive, newReceiveKey, pendingFrom, pendingOf, pendingSlot, pendingText,
  chosen, qtyFrom, receiveOutcome, receivedText, startDraft, summarize, withProduct, withQty, withRepick,
} from "./vendorReceive.ts";

const line = (key, extra = {}) => ({
  key, sku: key.split("|")[0], spec_id: null, spec_label: "", name: `品${key.split("|")[0]}`, unit: "片", pack_qty: 25,
  is_reissue: key.endsWith("|r"), qty: 50, shipped_qty: 50, received_qty: 0, remaining_qty: 50, suggested_qty: 50,
  unit_price: "150.00", product: null, ...extra,
});
const FILM = { id: 7, sku: "LC-0007", name: "高透亮面保護貼", is_active: true };
const plan = (lines, extra = {}) => ({
  order: 1, vendor_order_no: "MO-20261010-001", vendor_status: "已出貨", vendor_logistics_status: "", vendor_tracking_no: "",
  payment_method: "月結", lines, shipping_fee: "0.00", freight_into_cost: true, freight_left: "0.00", supplier: null,
  issue_note: "", ...extra,
});
const PLAN = plan([
  line("G02||p", { product: FILM }),
  line("G01||p", { qty: 10, shipped_qty: 4, remaining_qty: 10, suggested_qty: 4, unit_price: "280.00" }),
  line("M01|901|p", { spec_id: 901, spec_label: "K43 iPhone 15 Pro", qty: 5, shipped_qty: 0, remaining_qty: 5, suggested_qty: 0 }),
  // 免費補發的那一行伺服器回的單價是 0;這裡故意放 150:畫面看的是「免費」這個記號,不是單價剛好是 0
  line("G02||r", { qty: 5, shipped_qty: 5, remaining_qty: 5, suggested_qty: 5, unit_price: "150.00", product: FILM }),
], { issue_note: "上次少一包" });

test("框裡打的字 → 數量:只收 0 到 99999 的整數", () => {
  assert.equal(qtyFrom("25"), 25);
  assert.equal(qtyFrom(" 7 "), 7);
  assert.equal(qtyFrom(3), 3);
  assert.equal(qtyFrom("99999"), 99999);
  for (const bad of ["", "-1", "1.5", "2片", "100000", "1e3", null, undefined, {}, "２５"]) assert.equal(qtyFrom(bad), 0, String(bad));
});

test("打開面板:數量帶「廠商已出、這家店還沒入的」,備註帶上次記的;品號不抄進草稿(對過的看這張單現在回的)", () => {
  const draft = startDraft(PLAN, "recv-1");
  assert.deepEqual(draft, {
    requestKey: "recv-1",
    qty: { "G02||p": 50, "G01||p": 4, "G02||r": 5 },          // 還沒出的那一行不帶
    product: {},
    repick: {},
    note: "上次少一包",
  });
  assert.deepEqual(chosen(PLAN.lines[0], draft), { id: 7, label: "高透亮面保護貼" });
});

test("改數量與品號:0 個的不留;原本那一份不被改到", () => {
  const draft = startDraft(PLAN, "recv-1");
  assert.deepEqual(withQty(draft, "G01||p", 10).qty["G01||p"], 10);
  assert.equal("G02||p" in withQty(draft, "G02||p", 0).qty, false);
  assert.equal("G02||p" in withQty(draft, "G02||p", -3).qty, false);
  assert.equal("G02||p" in withQty(draft, "G02||p", 1.5).qty, false);
  assert.equal(withQty(draft, "G02||p", 1e9).qty["G02||p"], 99999);
  assert.deepEqual(withProduct(draft, "G01||p", { id: 9, label: "D3O" }).product["G01||p"], { id: 9, label: "D3O" });
  const picked = withProduct(draft, "G02||p", { id: 7, label: "高透" });
  assert.equal("G02||p" in withProduct(picked, "G02||p", null).product, false);
  assert.deepEqual(picked.product, { "G02||p": { id: 7, label: "高透" } });     // 清掉回的是新的一份
  assert.deepEqual(draft.qty, { "G02||p": 50, "G01||p": 4, "G02||r": 5 });
  assert.deepEqual(draft.product, {});
  assert.equal(withQty(draft, "G01||p", 9).requestKey, "recv-1");          // 鑰匙不換
});

test("一次帶好:只帶已出的 / 帶整張還沒入的;品號、備註、鑰匙不動", () => {
  const start = withProduct(withQty(startDraft(PLAN, "recv-1"), "G02||p", 1), "G01||p", { id: 9, label: "D3O" });
  const shipped = fill(PLAN, start, "shipped");
  assert.deepEqual(shipped.qty, { "G02||p": 50, "G01||p": 4, "G02||r": 5 });
  const all = fill(PLAN, start, "remaining");
  assert.deepEqual(all.qty, { "G02||p": 50, "G01||p": 10, "M01|901|p": 5, "G02||r": 5 });
  for (const d of [shipped, all]) {
    assert.deepEqual(d.product, start.product);
    assert.equal(d.note, "上次少一包");
    assert.equal(d.requestKey, "recv-1");
  }
  // 入過頭的那一行(還沒入的是負的)不帶
  const done = plan([line("G02||p", { received_qty: 60, remaining_qty: -10, suggested_qty: 0 })]);
  assert.deepEqual(fill(done, startDraft(done, "k"), "remaining").qty, {});
});

test("這一行算哪一種:不入 / 可以 / 比已出的多(只提醒)/ 比還沒入的多(不行)", () => {
  const l = line("G01||p", { qty: 10, shipped_qty: 4, received_qty: 2, remaining_qty: 8 });
  assert.equal(lineState(l, 0), "none");
  assert.equal(lineState(l, 2), "ok");          // 已出 4、入過 2 → 還有 2 個是出了沒入的
  assert.equal(lineState(l, 3), "early");
  assert.equal(lineState(l, 8), "early");
  assert.equal(lineState(l, 9), "over");
  // 入的比廠商記的出貨還多(之前提早入過):再入就是提醒
  assert.equal(lineState(line("G01||p", { qty: 10, shipped_qty: 4, received_qty: 6, remaining_qty: 4 }), 1), "early");
});

test("合計:只算這一次要入的;免費補發的算數量不算錢;沒選品號的不送", () => {
  const draft = withQty(startDraft(PLAN, "recv-1"), "M01|901|p", 5);
  const sum = summarize(PLAN, draft);
  assert.equal(sum.pieces, 50 + 4 + 5 + 5);
  assert.equal(sum.amount, 50 * 150 + 4 * 280 + 5 * 150);          // 補發的 5 片是 0
  assert.deepEqual(sum.lines, [{ key: "G02||p", qty: 50, product: 7, was: 7 }, { key: "G02||r", qty: 5, product: 7, was: 7 }]);
  assert.deepEqual(sum.unmapped, ["品G01", "品M01 K43 iPhone 15 Pro"]);
  assert.deepEqual(sum.over, []);
  assert.equal(sum.early, 1);                                      // M01 還沒出就要入 5 個
  assert.equal(blocked(sum), "還沒選品號:品G01、品M01 K43 iPhone 15 Pro");
  const ready = summarize(PLAN, withProduct(withProduct(draft, "G01||p", { id: 9, label: "D3O" }), "M01|901|p", { id: 8, label: "膜速箱" }));
  assert.equal(blocked(ready), null);
  assert.equal(ready.lines.length, 4);
});

test("每一行都帶著「畫面上原本對到誰」:換了的、沒換的、第一次選的", () => {
  const open = startDraft(PLAN, "recv-abcdefgh");
  // G02 原本對到 7,這個人按了「改」換成 9;G01 還沒對過,這次選 9
  const pressed = withRepick(open, PLAN.lines[0]);
  assert.deepEqual([pressed.repick, open.repick, open.product], [{ "G02||p": true }, {}, {}]);     // 原本那一份不被改到
  const draft = withProduct(withProduct(pressed, "G02||p", { id: 9, label: "D3O" }), "G01||p", { id: 9, label: "D3O" });
  assert.deepEqual(summarize(PLAN, draft).lines, [
    { key: "G02||p", qty: 50, product: 9, was: 7 },
    { key: "G01||p", qty: 4, product: 9, was: null },
    { key: "G02||r", qty: 5, product: 7, was: 7 },
  ]);
  // 按了「改」又選回原本那一個:送的就是原本那一個
  const back = withProduct(draft, "G02||p", { id: 7, label: "高透" });
  assert.deepEqual(summarize(PLAN, back).lines[0], { key: "G02||p", qty: 50, product: 7, was: 7 });
  // 記下來再讀回來是同一份(再送一次送的要是同一份)
  const pending = pendingOf(draft, summarize(PLAN, draft));
  assert.deepEqual(pendingFrom(pendingText(pending)), pending);
  assert.deepEqual(pendingFrom(pendingText(pending)).lines.map((l) => l.was), [7, null, 7]);
  // 這一版之前記下來的沒有那一格:當成還沒對過;亂寫的整份不要
  const old = JSON.stringify({ ...pending, lines: [{ key: "G02||p", qty: 50, product: 9 }] });
  assert.deepEqual(pendingFrom(old).lines, [{ key: "G02||p", qty: 50, product: 9, was: null }]);
  for (const odd of ["7", 0, -1, 1.5, true, {}]) {
    const text = JSON.stringify({ ...pending, lines: [{ key: "G02||p", qty: 50, product: 9, was: odd }] });
    assert.equal(pendingFrom(text), null, String(odd));
  }
});

test("沒按「改」的那一行跟著這張單現在的對照走,不是打開面板那時候的", () => {
  // 打開時 G02 對到 7、G01 還沒對過(這個人自己挑了 9)
  const draft = withProduct(startDraft(PLAN, "recv-abcdefgh"), "G01||p", { id: 9, label: "D3O" });
  assert.deepEqual(chosen(PLAN.lines[0], draft), { id: 7, label: "高透亮面保護貼" });
  assert.deepEqual(chosen(PLAN.lines[1], draft), { id: 9, label: "D3O" });
  assert.equal(chosen(PLAN.lines[2], draft), null);
  // 被擋下來、重抓:別人把 G02 改成 8、把 G01 連到 5
  const OTHER = { id: 8, sku: "LC-0008", name: "別的膜", is_active: true };
  const LATE = { id: 5, sku: "LC-0005", name: "別人連的", is_active: true };
  const again = plan([line("G02||p", { product: OTHER }), line("G01||p", { product: LATE }), ...PLAN.lines.slice(2)]);
  assert.deepEqual(chosen(again.lines[0], draft), { id: 8, label: "別的膜" });
  assert.deepEqual(chosen(again.lines[1], draft), { id: 5, label: "別人連的" });       // 自己挑的 9 不算數了(畫面寫的是 5)
  const sent = summarize(again, draft).lines;
  // 送出去的品號與「畫面上對到誰」都是現在的:沒有人要換
  assert.deepEqual(sent.slice(0, 2), [{ key: "G02||p", qty: 50, product: 8, was: 8 }, { key: "G01||p", qty: 4, product: 5, was: 5 }]);
  // 這時候才按「改」:框裡先帶現在對到的那一個(8),不是一開始的 7
  const pressed = withRepick(draft, again.lines[0]);
  assert.deepEqual(chosen(again.lines[0], pressed), { id: 8, label: "別的膜" });
  assert.deepEqual(draft.product, { "G01||p": { id: 9, label: "D3O" } });               // 原本那一份不被改到
  assert.deepEqual(summarize(again, pressed).lines[0], { key: "G02||p", qty: 50, product: 8, was: 8 });
  // 按了「改」之後清掉沒選:這一行算還沒選品號(不能偷偷回到原本對到的)
  const cleared = withProduct(pressed, "G02||p", null);
  assert.equal(chosen(again.lines[0], cleared), null);
  assert.deepEqual(summarize(again, cleared).unmapped, ["品G02"]);
  // 換成別的:品號是新的、「原本對到誰」還是畫面上那一個
  const moved = withProduct(pressed, "G02||p", { id: 7, label: "高透" });
  assert.deepEqual(summarize(again, moved).lines[0], { key: "G02||p", qty: 50, product: 7, was: 8 });
  // 對照被別人**解除**了(重抓變成還沒對過):沒按過「改」的那一行不能留著舊的品號,要這個人自己再挑
  const gone = plan([line("G02||p"), ...PLAN.lines.slice(1)]);
  assert.equal(chosen(gone.lines[0], draft), null);
  assert.deepEqual(summarize(gone, draft).unmapped.includes("品G02"), true);
  assert.equal(summarize(gone, draft).lines.some((l) => l.key === "G02||p"), false);
  // 還沒對過的那一行按不了「改」;真的被呼叫也不會憑空多一個品號
  assert.equal(chosen(PLAN.lines[2], withRepick(draft, PLAN.lines[2])), null);
});

test("不能按確認入庫的三種情況,先講數量、再講品號", () => {
  const nothing = { ...startDraft(PLAN, "k"), qty: {} };
  assert.equal(blocked(summarize(PLAN, nothing)), "這一次沒有要入庫的東西");
  const over = withQty(startDraft(PLAN, "k"), "G01||p", 11);
  assert.equal(blocked(summarize(PLAN, over)), "比還沒入庫的多:品G01");
  assert.deepEqual(summarize(PLAN, over).over, ["品G01"]);
});

test("廠商改過單:草稿裡有、單上已經沒有的那一行不算、不送", () => {
  const draft = withProduct(withQty(startDraft(PLAN, "k"), "G99||p", 3), "G99||p", { id: 5, label: "舊的" });
  const sum = summarize(PLAN, draft);
  assert.equal(sum.lines.some((l) => l.key === "G99||p"), false);
  assert.equal(sum.pieces, 59);
});

test("紀錄上的「已入庫」:作廢的進貨單不算;不是從這裡叫的只寫入了幾個", () => {
  const r = (qty, is_void = false) => ({ id: qty, purchase_order: 1, purchase_order_no: "PO-000001", is_void, total_cost: "0", freight: "0", qty, created_at: "", created_by: "" });
  assert.equal(receivedText({ items: [{ qty: 50 }, { qty: 10 }], receipts: [] }), "0 / 60");
  assert.equal(receivedText({ items: [{ qty: 50 }, { qty: 10 }], receipts: [r(25), r(50, true), r(10)] }), "35 / 60");
  assert.equal(receivedText({ items: [], receipts: [] }), "");
  assert.equal(receivedText({ items: [], receipts: [r(25), r(5, true)] }), "25");
});

test("只有確定成立的單可以到貨入庫", () => {
  assert.equal(mayReceive({ state: "placed" }), true);
  assert.equal(mayReceive({ state: "unknown" }), false);
  assert.equal(mayReceive({ state: "sending" }), false);
});

test("品名:有規格的帶規格;入庫的鑰匙符合伺服器的格式", () => {
  assert.equal(lineTitle({ name: "膜速箱", spec_label: "K43 iPhone 15 Pro" }), "膜速箱 K43 iPhone 15 Pro");
  assert.equal(lineTitle({ name: "高透亮面", spec_label: "" }), "高透亮面");
  const key = newReceiveKey(() => "0b9c2f6e-1d2a-4c3b-9e8f-aabbccddeeff");
  assert.equal(key, "recv-0b9c2f6e1d2a4c3b9e8faabb");
  assert.match(key, /^[A-Za-z0-9_-]{8,50}$/);
  assert.match(newReceiveKey(), /^recv-[A-Za-z0-9]{8,24}$/);
  assert.notEqual(newReceiveKey(), newReceiveKey());
});

test("按了確認、還不知道結果的那一次:送出之前記下來的就是送出去的那一份(同一把鑰匙、同樣的內容)", () => {
  const draft = withProduct(withQty({ ...startDraft(PLAN, "recv-abcdefgh"), note: "少一包" }, "M01|901|p", 0), "G01||p", { id: 9, label: "D3O" });
  const pending = pendingOf(draft, summarize(PLAN, draft));
  assert.deepEqual(pending, {
    requestKey: "recv-abcdefgh",
    lines: [{ key: "G02||p", qty: 50, product: 7, was: 7 }, { key: "G01||p", qty: 4, product: 9, was: null }, { key: "G02||r", qty: 5, product: 7, was: 7 }],
    pieces: 59,
    note: "少一包",
  });
  // 存進瀏覽器再讀回來是同一份;一張叫貨單一格
  assert.deepEqual(pendingFrom(pendingText(pending)), pending);
  assert.equal(pendingSlot(12), "mp_pos_vendor_receive_12");
  assert.notEqual(pendingSlot(12), pendingSlot(13));
});

test("瀏覽器裡那一格讀不懂就當成沒有(不拿壞掉的內容去入庫)", () => {
  const good = { requestKey: "recv-abcdefgh", lines: [{ key: "G02||p", qty: 50, product: 7, was: 7 }], pieces: 50, note: "" };
  assert.deepEqual(pendingFrom(JSON.stringify(good)), good);
  // 幾個是照明細加起來的,不看存的那個數字;備註不是字就當成空的
  assert.deepEqual(pendingFrom(JSON.stringify({ ...good, pieces: 999, note: 5 })), good);
  for (const bad of [null, undefined, "", "{", "[]", "7", "null",
    JSON.stringify({ ...good, requestKey: "x" }), JSON.stringify({ ...good, requestKey: "有中文的鑰匙abcdefgh" }),
    JSON.stringify({ ...good, requestKey: 12345678 }), JSON.stringify({ ...good, lines: [] }), JSON.stringify({ ...good, lines: "x" }),
    JSON.stringify({ ...good, lines: [{ key: "G02||p", qty: 0, product: 7 }] }),
    JSON.stringify({ ...good, lines: [{ key: "G02||p", qty: 1.5, product: 7 }] }),
    JSON.stringify({ ...good, lines: [{ key: "G02||p", qty: "50", product: 7 }] }),
    JSON.stringify({ ...good, lines: [{ key: "", qty: 5, product: 7 }] }),
    JSON.stringify({ ...good, lines: [{ key: "G02||p", qty: 5 }] }),
    JSON.stringify({ ...good, lines: [{ key: "G02||p", qty: 5, product: 0 }] }),
    JSON.stringify({ ...good, lines: [good.lines[0], null] })]) {
    assert.equal(pendingFrom(bad), null, String(bad));
  }
});

test("第一次送的答覆:入了 / 明確沒入(這一次自己被擋)/ 不知道 —— 只有不知道要繼續記著", () => {
  assert.equal(receiveOutcome(201, false), "done");
  assert.equal(receiveOutcome(200, false), "done");
  for (const refused of [400, 401, 403, 404, 422]) assert.equal(receiveOutcome(refused, false), "refused", String(refused));
  // 沒連到、逾時、太頻繁、伺服器出錯(可能已經入了才出錯):都不能當成沒入
  for (const unknown of [null, 408, 409, 429, 500, 502, 503, 504, 0, 302]) assert.equal(receiveOutcome(unknown, false), "unknown", String(unknown));
});

test("再送一次(確認上一次)被擋:沒權限 / 找不到 / 沒登入證明不了上一次沒入,要繼續記著", () => {
  assert.equal(receiveOutcome(200, true), "done");          // 上一次入過了,伺服器回同一次
  assert.equal(receiveOutcome(201, true), "done");          // 上一次沒到,這一次入的
  // 伺服器查過這把鑰匙(沒入過)之後才講的不行
  for (const refused of [400, 422]) assert.equal(receiveOutcome(refused, true), "refused", String(refused));
  // 還沒查鑰匙就擋的:上一次可能早就入了(權限被關掉 → 403 → 當成沒入 → 權限開回來再入一次 = 入兩次)
  for (const unknown of [401, 403, 404, 405, 410, 418, null, 408, 409, 429, 500, 502, 503, 504, 0, 302]) {
    assert.equal(receiveOutcome(unknown, true), "unknown", String(unknown));
  }
});
