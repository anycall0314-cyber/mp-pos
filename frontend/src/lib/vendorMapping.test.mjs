// 品名連連看在畫面這一側:清單怎麼篩、連了幾個、存完放回哪裡、先帶什麼字、哪種商品連不了。跑法:npm test。
import assert from "node:assert/strict";
import test from "node:test";

import {
  ACTION_LABEL, actionsOf, counts, filterRows, findText, itemTitle, linkFetched, oneAtATime, savedText, whyNot, withSaved,
} from "./vendorMapping.ts";

const FILM = { id: 7, sku: "LC-0007", name: "甲 高透亮面保護貼", is_active: true };
const D3O = { id: 8, sku: "LC-0008", name: "甲 D3O 保護貼", is_active: true };
const row = (key, extra = {}) => ({
  key, sku: key.split("#")[0], spec_id: null, name: `品${key}`, spec_label: "", kind: "片材規格", size: "", unit: "片",
  pack_qty: 25, product: null, ...extra,
});
const ROWS = [
  row("G02", { name: "高透亮面", size: "125*196", product: FILM }),
  row("G01", { name: "D3O 7H" }),
  row("M01#901", { name: "膜速箱", spec_id: 901, spec_label: "K43 iPhone 15 Pro", product: D3O }),
  row("M01#902", { name: "膜速箱", spec_id: 902, spec_label: "K44" }),
];
const DATA = { warehouse: 1, vendor: "moceo", supplier: null, rows: ROWS };

test("廠商那一邊的叫法:品名 + 規格 + 尺寸,空的不留空白", () => {
  assert.equal(itemTitle(ROWS[0]), "高透亮面 125*196");
  assert.equal(itemTitle(ROWS[2]), "膜速箱 K43 iPhone 15 Pro");
  assert.equal(itemTitle(ROWS[1]), "D3O 7H");
});

test("連了幾個 / 一共幾個", () => {
  assert.deepEqual(counts(ROWS), { linked: 2, total: 4 });
  assert.deepEqual(counts([]), { linked: 0, total: 0 });
  assert.deepEqual(counts([ROWS[1]]), { linked: 0, total: 1 });
});

test("只看沒連的", () => {
  assert.deepEqual(filterRows(ROWS, { text: "", unlinkedOnly: true }).map((r) => r.key), ["G01", "M01#902"]);
  assert.deepEqual(filterRows(ROWS, { text: "", unlinkedOnly: false }).map((r) => r.key), ROWS.map((r) => r.key));
});

test("找的字兩邊都比:廠商的品名、規格、料號、尺寸,與連到的店內品名、品號;每個字都要有", () => {
  const find = (text, unlinkedOnly = false) => filterRows(ROWS, { text, unlinkedOnly }).map((r) => r.key);
  assert.deepEqual(find("膜速箱"), ["M01#901", "M01#902"]);
  assert.deepEqual(find("iphone 膜速"), ["M01#901"]);          // 不分大小寫、順序不拘
  assert.deepEqual(find("g02"), ["G02"]);                      // 料號
  assert.deepEqual(find("IPHONE K43"), ["M01#901"]);           // 打大寫也一樣
  assert.deepEqual(find("125*196"), ["G02"]);                  // 尺寸
  assert.deepEqual(find("保護貼"), ["G02", "M01#901"]);        // 店內品名
  assert.deepEqual(find("lc-0008"), ["M01#901"]);              // 店內品號
  assert.deepEqual(find("d3o"), ["G01", "M01#901"]);           // 一邊是廠商品名、一邊是店內品名
  assert.deepEqual(find("d3o", true), ["G01"]);
  assert.deepEqual(find("膜速箱 高透"), []);                   // 兩個字要在同一列
  assert.deepEqual(find("   "), ROWS.map((r) => r.key));
});

test("存完:那一列放回原本的位置,別的列不動、原本那一份不被改到", () => {
  const saved = { ...ROWS[1], product: FILM };
  const next = withSaved(DATA, saved);
  assert.deepEqual(next.rows.map((r) => [r.key, r.product?.id ?? null]), [["G02", 7], ["G01", 7], ["M01#901", 8], ["M01#902", null]]);
  assert.equal(next.rows[0], ROWS[0]);
  assert.equal(DATA.rows[1].product, null);
  assert.equal(next.warehouse, 1);
  // 解除
  assert.equal(withSaved(DATA, { ...ROWS[0], product: null }).rows[0].product, null);
});

test("存完才回來、清單已經換了(沒有那一列)或還沒有清單:不動", () => {
  assert.equal(withSaved(DATA, row("ZZ", { product: FILM })), DATA);
  assert.equal(withSaved(undefined, ROWS[0]), undefined);
});

test("去找店內商品時先帶的字:品名 + 規格,不帶料號與尺寸", () => {
  assert.equal(findText(ROWS[0]), "高透亮面");
  assert.equal(findText(ROWS[2]), "膜速箱 K43 iPhone 15 Pro");
  assert.equal(findText({ name: "", spec_label: "" }), "");
  assert.equal(findText({ name: " 膜 ", spec_label: "" }), "膜");
});

test("哪種商品一看就知道連不了:停用、中古、要刷序號、虛擬;其餘可以", () => {
  assert.equal(whyNot({ is_active: true, requires_serial: false, is_secondhand: false, is_virtual: false }), null);
  assert.equal(whyNot({}), null);                                           // 沒講的不先擋,伺服器會說
  assert.equal(whyNot({ is_active: false }), "這個商品已經停用");
  assert.equal(whyNot({ requires_serial: true }), "要刷序號的商品不能連");
  assert.equal(whyNot({ requires_serial: true, is_secondhand: true }), "中古機要逐台記,不能連");
  assert.equal(whyNot({ is_virtual: true }), "虛擬商品沒有庫存,不能連");
  assert.equal(whyNot({ is_active: false, is_virtual: true }), "這個商品已經停用");
});

test("存完怎麼講:第一次連、改連、解除各一句", () => {
  assert.equal(savedText({ ...ROWS[1], product: FILM }, null), "D3O 7H:已連到 甲 高透亮面保護貼");
  assert.equal(savedText({ ...ROWS[0], product: D3O }, FILM), "高透亮面 125*196:改連到 甲 D3O 保護貼");
  assert.equal(savedText({ ...ROWS[0], product: FILM }, FILM), "高透亮面 125*196:已連到 甲 高透亮面保護貼");
  assert.equal(savedText({ ...ROWS[0], product: null }, FILM), "高透亮面 125*196:已解除");
  assert.equal(savedText({ ...ROWS[1], product: null }, null), "D3O 7H:沒有連");
});

test("每一列的按鈕:沒連的只有「連結」,連了的是「改連」「解除」;字數都一樣", () => {
  assert.deepEqual(actionsOf(ROWS[1]), ["link"]);
  assert.deepEqual(actionsOf(ROWS[0]), ["change", "unlink"]);
  assert.deepEqual([...new Set(Object.values(ACTION_LABEL).map((s) => s.length))], [2]);
  assert.deepEqual(Object.keys(ACTION_LABEL).sort(), ["change", "link", "unlink"]);
});

const later = () => {
  let done;
  const promise = new Promise((resolve, reject) => { done = { resolve, reject }; });
  return { promise, ...done };
};
const tick = () => new Promise((r) => setImmediate(r));

test("一次只存一筆:前一筆還沒回來,別的不做;做完(成功或出錯)才放開,畫面跟著知道是哪一列", async () => {
  const seen = [];
  const gate = oneAtATime((busy) => seen.push(busy));
  const first = later();
  const a = gate.run("G02", () => first.promise);
  assert.equal(gate.busy(), "G02");
  assert.equal(await gate.run("G01", async () => "不該做"), null);      // 別列
  assert.equal(await gate.run("G02", async () => "不該做"), null);      // 同一列連點
  assert.deepEqual(seen, ["G02"]);
  first.resolve("好了");
  assert.equal(await a, "好了");
  assert.deepEqual([gate.busy(), seen], [null, ["G02", null]]);
  // 出錯也要放開(不然整頁的按鈕永遠按不了)
  await assert.rejects(gate.run("G01", async () => { throw new Error("壞了"); }), /壞了/);
  assert.equal(gate.busy(), null);
  assert.equal(await gate.run("G01", async () => 7), 7);
  // 不給畫面那一支也能用
  assert.equal(await oneAtATime().run("X", async () => 1), 1);
});

test("選了「就是這個」:商品晚一點才查回來,連的是按下去那一刻的那一列(不是後來點的別列)", async () => {
  const fetching = later();
  const linked = [];
  const said = [];
  const deps = {
    fetch: () => fetching.promise,
    link: async (row, p) => { linked.push([row.key, p.id]); return true; },
    say: (t) => said.push(t),
    errorText: (e) => `讀不到:${e.message}`,
  };
  let current = ROWS[1];                              // 畫面上「正在處理的那一列」:G01
  const running = linkFetched(current, deps);
  current = null;                                     // 表單關了
  await tick();
  current = ROWS[3];                                  // 人接著點了別列
  fetching.resolve({ id: 7, is_active: true });
  assert.equal(await running, true);
  assert.deepEqual([linked, said, current.key], [[["G01", 7]], [], "M01#902"]);
});

test("選了「就是這個」:查不回來、或那個商品連不了 → 講原因、不連", async () => {
  const run = async (fetch) => {
    const linked = [];
    const said = [];
    const ok = await linkFetched(ROWS[1], {
      fetch, link: async (row, p) => { linked.push([row.key, p.id]); return true; }, say: (t) => said.push(t),
      errorText: (e) => `讀不到:${e.message}`,
    });
    return [ok, linked, said];
  };
  assert.deepEqual(await run(async () => { throw new Error("斷線"); }), [false, [], ["讀不到:斷線"]]);
  assert.deepEqual(await run(async () => ({ id: 3, requires_serial: true })), [false, [], ["要刷序號的商品不能連"]]);
  assert.deepEqual(await run(async () => ({ id: 3, is_active: false })), [false, [], ["這個商品已經停用"]]);
  assert.deepEqual(await run(async () => ({ id: 3 })), [true, [["G01", 3]], []]);
  // 伺服器不給連(存的那一步回 false):照實回沒連成
  assert.equal(await linkFetched(ROWS[1], { fetch: async () => ({ id: 3 }), link: async () => false, say: () => {}, errorText: String }), false);
});
