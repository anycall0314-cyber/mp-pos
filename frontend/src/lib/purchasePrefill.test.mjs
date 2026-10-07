// 「建好品號 → 按進貨」的網址:組出來的、讀進來的都要對;不能進貨的不給「進貨」。跑法:npm test。
import assert from "node:assert/strict";
import test from "node:test";

import {
  carriedQty,
  draftQty,
  MAX_PREFILL,
  prefillReport,
  purchaseLinkFor,
  readPrefill,
  sortFetched,
  withPrefill,
} from "./purchasePrefill.ts";

/** 網址上的 add 讀出來是哪幾個商品(走的就是進貨開單頁讀網址的那一支) */
const parseAddParam = (raw) =>
  readPrefill(raw == null ? "" : `?add=${encodeURIComponent(raw)}`).ids;

const item = (id, extra = {}) => ({ id, is_secondhand: false, is_virtual: false, is_active: true, ...extra });

test("一般商品:去進貨開單頁,帶著它", () => {
  assert.equal(purchaseLinkFor([item(12)]), "/purchases/new?add=12");
  assert.equal(purchaseLinkFor([item(12), item(13), item(12)]), "/purchases/new?add=12,13");   // 重複的只帶一次
});

test("中古機不走一般進貨單:只有中古機就去中古收購;混著的只帶一般的", () => {
  assert.equal(purchaseLinkFor([item(5, { is_secondhand: true })]), "/secondhand-acquisition");
  assert.equal(purchaseLinkFor([item(5, { is_secondhand: true }), item(6)]), "/purchases/new?add=6");
});

test("不能進貨的沒有「進貨」:虛擬商品、停用的、還沒有編號的", () => {
  assert.equal(purchaseLinkFor([item(7, { is_virtual: true })]), null);
  assert.equal(purchaseLinkFor([item(8, { is_active: false })]), null);
  assert.equal(purchaseLinkFor([item(8, { is_active: false, is_secondhand: true })]), null);
  assert.equal(purchaseLinkFor([{ name: "預覽時還沒有編號" }]), null);
  assert.equal(purchaseLinkFor([]), null);
  // 沒有寫 is_active 的(手機精靈回來的品項)當成啟用
  assert.equal(purchaseLinkFor([{ id: 9, is_secondhand: false }]), "/purchases/new?add=9");
});

test("一次帶的個數有上限", () => {
  const many = Array.from({ length: MAX_PREFILL + 20 }, (_, i) => item(i + 1));
  const link = purchaseLinkFor(many);
  assert.equal(parseAddParam(new URL(link, "http://x").searchParams.get("add")).length, MAX_PREFILL);
});

test("讀網址上的 add:只收正整數、不重複、照順序", () => {
  assert.deepEqual(parseAddParam("12,13"), [12, 13]);
  assert.deepEqual(parseAddParam(" 12 , 13 ,12"), [12, 13]);
  assert.deepEqual(parseAddParam("13,12"), [13, 12]);
  assert.deepEqual(parseAddParam("abc,-3,0,1.5,7,１２,"), [7]);
  assert.deepEqual(parseAddParam("9".repeat(30)), []);              // 長到不像編號
  assert.deepEqual(parseAddParam(""), []);
  assert.deepEqual(parseAddParam(null), []);
  assert.equal(parseAddParam(Array.from({ length: 500 }, (_, i) => i + 1).join(",")).length, MAX_PREFILL);
});

test("組出來的網址讀得回來", () => {
  const link = purchaseLinkFor([item(21), item(22), item(23)]);
  assert.deepEqual(parseAddParam(new URL(link, "http://x").searchParams.get("add")), [21, 22, 23]);
});

test("帶不完的要講:網址上多一個 more,進貨開單頁讀得到", () => {
  const many = Array.from({ length: MAX_PREFILL + 7 }, (_, i) => item(i + 1));
  const link = purchaseLinkFor(many);
  assert.ok(link.endsWith("&more=7"), link);
  const read = readPrefill(link.slice(link.indexOf("?")));
  assert.equal(read.ids.length, MAX_PREFILL);
  assert.equal(read.more, 7);
  // 剛好帶得完的不多寫 more
  assert.equal(purchaseLinkFor(many.slice(0, MAX_PREFILL)).includes("more"), false);
});

test("讀網址:add / more 拿掉、別的參數留著;網址自己超過上限的也算沒帶到", () => {
  assert.deepEqual(readPrefill("?add=3,4&x=1"), { ids: [3, 4], more: 0, rest: "?x=1" });
  assert.deepEqual(readPrefill("?x=1&add=3&more=2&y=z"), { ids: [3], more: 2, rest: "?x=1&y=z" });
  assert.deepEqual(readPrefill("?add=3"), { ids: [3], more: 0, rest: "" });
  assert.deepEqual(readPrefill(""), { ids: [], more: 0, rest: "" });
  const long = Array.from({ length: MAX_PREFILL + 2 }, (_, i) => i + 1).join(",");
  assert.equal(readPrefill(`?add=${long}&more=5`).more, 7);
  // more 只收一般的數字
  for (const bad of ["-3", "1e3", "abc", "", "１２"]) {
    assert.equal(readPrefill(`?add=3&more=${bad}`).more, 0, bad);
  }
});

test("同一個參數寫了好幾次,全部都算", () => {
  assert.deepEqual(readPrefill("?add=1&add=2,3&add=1").ids, [1, 2, 3]);
});

const none = { secondhand: [], virtual: [], inactive: [], missing: 0, other: [], more: 0 };

test("都加進去了:沒有話要講", () => {
  assert.deepEqual(prefillReport(none), []);
});

test("沒加進去的一種一行;名字最多寫三個,總共幾項一定講", () => {
  assert.deepEqual(prefillReport({ ...none, secondhand: ["甲"] }), ["「甲」是中古機,沒有加入:請到「中古收購」進"]);
  assert.deepEqual(prefillReport({ ...none, secondhand: ["甲", "乙", "丙", "丁", "甲"] }), [
    "「甲」「乙」「丙」等 4 項是中古機,沒有加入:請到「中古收購」進",
  ]);
  assert.deepEqual(prefillReport({ ...none, virtual: ["門號方案"] }), ["「門號方案」是虛擬商品,不用進貨,沒有加入"]);
  // 停用的一樣只寫一行(六十個停用的不能變成六十行,把「知道了」擠到畫面外)
  assert.deepEqual(prefillReport({ ...none, inactive: ["子", "丑", "寅", "卯", "辰"] }), [
    "「子」「丑」「寅」等 5 項已停用,沒有加入:要管理員恢復之後才能進貨",
  ]);
  // 找不到的要講幾個(三個找不到不能只講「有商品找不到」)
  assert.deepEqual(prefillReport({ ...none, missing: 3 }), ["有 3 個商品查不到(可能已經刪除,或網路沒回應),沒有加入"]);
  // 其他原因:一樣的只講一次,不一樣的都留著(不截掉)
  assert.deepEqual(prefillReport({ ...none, other: ["子", "子", "丑", "寅", "卯"] }), ["子", "丑", "寅", "卯"]);
  assert.deepEqual(prefillReport({ ...none, more: 7 }), [
    `一次最多帶 ${MAX_PREFILL} 項,另有 7 項沒有帶過來:請用搜尋加入`,
  ]);
});

test("好幾種一起發生:每一種都講,不互相蓋掉", () => {
  const lines = prefillReport({ secondhand: ["甲"], virtual: ["乙"], inactive: ["丙"], missing: 2, other: ["這張單已經送出"], more: 5 });
  assert.equal(lines.length, 6);
  assert.ok(lines[0].includes("中古機") && lines[1].includes("虛擬商品") && lines[2].includes("已停用") && lines[3].includes("2 個"));
  assert.equal(lines[4], "這張單已經送出");
  assert.ok(lines[5].includes("另有 5 項"));
  // 一次帶進來不管有幾個商品、出了幾種狀況,最多就是這幾行
  const many = Array.from({ length: 60 }, (_, i) => `品${i}`);
  assert.ok(prefillReport({ secondhand: many, virtual: many, inactive: many, missing: 60, other: [], more: 99 }).length <= 5);
});

test("帶過來的配件數量先是 0(還沒說進幾件);序號商品是一個空位", () => {
  assert.equal(carriedQty({ requires_serial: false }), 0);
  assert.equal(carriedQty({}), 0);
  assert.equal(carriedQty({ requires_serial: true }), 1);
});

test("草稿載回來:帶過來還沒填的配件還是 0,不能變成 1;其他最少 1", () => {
  const acc = { requires_serial: false };
  const phone = { requires_serial: true };
  assert.equal(draftQty({ qty: 0, product: acc }), 0);
  assert.equal(draftQty({ qty: 5, product: acc }), 5);
  assert.equal(draftQty({ qty: 0, product: phone }), 1);      // 序號商品沒有 0
  assert.equal(draftQty({ qty: 3, product: phone }), 3);
  // 壞掉的草稿(不是數字、沒有這一欄、負的):照舊當 1,不當成「還沒填」
  for (const bad of [undefined, null, "", "abc", -2, "0", NaN]) {
    assert.equal(draftQty({ qty: bad, product: acc }), 1, String(bad));
  }
});

test("查回來的商品:中古機、虛擬商品、查不到的不能進一般進貨單;停用的另外講;其餘照順序", () => {
  const ok = (value) => ({ status: "fulfilled", value });
  const p = (name, extra = {}) => ({ name, is_secondhand: false, is_virtual: false, is_active: true, ...extra });
  const sorted = sortFetched([
    ok(p("手機")),
    ok(p("中古", { is_secondhand: true })),
    { status: "rejected", reason: new Error("404") },
    ok(p("門號", { is_virtual: true })),
    ok(p("停用殼", { is_active: false })),
    ok(p("殼")),
    { status: "rejected", reason: new Error("timeout") },
    ok(null),
  ]);
  assert.deepEqual(sorted.fresh.map((x) => x.name), ["手機", "殼"]);
  assert.deepEqual(sorted.secondhand, ["中古"]);
  assert.deepEqual(sorted.virtual, ["門號"]);
  assert.deepEqual(sorted.inactive, ["停用殼"]);
  assert.equal(sorted.missing, 3);
  // 停用的中古機:算中古機(不會因為「恢復」就能走一般進貨)
  assert.deepEqual(sortFetched([ok(p("舊機", { is_secondhand: true, is_active: false }))]).secondhand, ["舊機"]);
});

test("把還沒做完的寫回網址:讀得回來、別的參數留著、做完了就拿掉", () => {
  // 寫進去再讀出來是同一批(重新整理靠的就是這個)
  const two = withPrefill("?add=9&x=1", [3, 4, 3], 2);
  assert.deepEqual(readPrefill(two), { ids: [3, 4], more: 2, rest: "?x=1" });
  // 兩批併在一起:前面還沒做完的不能從網址上不見
  assert.deepEqual(readPrefill(withPrefill("?add=7", [5, 7], 0)).ids, [5, 7]);
  // 都做完了:add / more 拿掉,別的留著
  assert.equal(withPrefill("?add=3&more=2&x=1", [], 0), "?x=1");
  assert.equal(withPrefill("?add=3", [], 5), "");          // 沒有 add 就沒有 more
  assert.equal(withPrefill("", [], 0), "");
  // 寫出來的固定是同一個樣子(拿它跟網址比,才知道是不是自己寫的那一份)
  assert.equal(withPrefill(two, [3, 4], 2), two);
  // 不是編號的不寫進去
  assert.deepEqual(readPrefill(withPrefill("", [0, -1, 2.5, 8], 0)).ids, [8]);
  assert.equal(withPrefill("", [0, -1, 2.5, 8], 0), "?add=8");
});
