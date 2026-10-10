// 廠商叫貨在畫面這一側:包數、合計、鑰匙與「送出去了還不知道結果」。跑法:npm test。
import assert from "node:assert/strict";
import test from "node:test";

import { readFileSync } from "node:fs";

import {
  afterSend, amountText, beforeSend, draftFrom, emptyDraft, filterRows, kindsOf, linesToSend, newRequestKey, outcomeOf,
  packsFrom, packsText, rowTitle, sameAsSent, summarize, whenText, withPacks,
} from "./vendorOrder.ts";

const row = (key, extra = {}) => ({
  key, sku: key.split("#")[0], name: `品${key}`, kind: "片材規格", size: "", unit: "片", pack_qty: 25,
  spec_id: null, spec_label: "", unit_price: "150.00", pack_price: "3750.00", ...extra,
});
const ROWS = [row("G02"), row("G01", { pack_qty: 10, unit_price: "280.00" }), row("S09", { unit_price: null, pack_price: null }),
  row("M01#901", { pack_qty: 5, unit_price: "75.00", spec_id: 901, spec_label: "K43 iPhone 15 Pro" })];
let n = 0;
const random = () => `seed-${++n}`;

test("框裡打的字 → 包數:只收 0 到 9999 的整數", () => {
  assert.equal(packsFrom("2"), 2);
  assert.equal(packsFrom(" 12 "), 12);
  assert.equal(packsFrom(3), 3);
  assert.equal(packsFrom("9999"), 9999);
  for (const bad of ["", "-1", "1.5", "2包", "10000", "1e3", null, undefined, {}, "０２"]) assert.equal(packsFrom(bad), 0, String(bad));
});

test("改包數:0 包的不留在購物車,原本那一份不被改到", () => {
  const cart = { G02: 2 };
  assert.deepEqual(withPacks(cart, "G01", 3), { G02: 2, G01: 3 });
  assert.deepEqual(withPacks(cart, "G02", 0), {});
  assert.deepEqual(withPacks(cart, "G02", -5), {});
  assert.deepEqual(withPacks(cart, "G02", 1.5), {});
  assert.deepEqual(withPacks(cart, "G02", 99999), { G02: 9999 });
  assert.deepEqual(cart, { G02: 2 });
});

test("合計:包數 × 一包幾片 = 片數,片數 × 單價 = 金額;順序照廠商的清單", () => {
  const sum = summarize({ "M01#901": 3, G02: 2 }, ROWS);
  assert.deepEqual(sum.lines.map((l) => [l.row.key, l.packs, l.pieces, l.amount]), [["G02", 2, 50, 7500], ["M01#901", 3, 15, 1125]]);
  assert.deepEqual([sum.packs, sum.pieces, sum.amount, sum.gone], [5, 65, 8625, []]);
  assert.deepEqual(linesToSend(sum), [{ key: "G02", packs: 2 }, { key: "M01#901", packs: 3 }]);
  assert.deepEqual(summarize({}, ROWS), { lines: [], packs: 0, pieces: 0, amount: 0, gone: [] });
});

test("清單換過之後不在了、或變成沒有報價的:列出來,不默默丟掉也不照送", () => {
  const sum = summarize({ G02: 1, OLD: 4, S09: 2 }, ROWS);
  assert.deepEqual(sum.lines.map((l) => l.row.key), ["G02"]);
  assert.deepEqual(sum.gone.sort(), ["OLD", "S09"]);
  assert.deepEqual(linesToSend(sum), [{ key: "G02", packs: 1 }]);
  assert.deepEqual(summarize({ G02: 1 }, []).gone, ["G02"]);      // 清單還沒回來 / 是空的
});

test("幾包 = 幾片,兩個都寫出來", () => {
  assert.equal(packsText(2, 50, "片"), "2 包 = 50 片");
  assert.equal(packsText(1, 5, ""), "1 包 = 5 片");
  assert.equal(rowTitle({ name: "膜速箱", spec_label: "K43 iPhone 15 Pro", size: "" }), "膜速箱 K43 iPhone 15 Pro");
  assert.equal(rowTitle({ name: "高透亮面", spec_label: "", size: "125*196" }), "高透亮面 125*196");
});

test("鑰匙的樣子伺服器收得下,每一張新單不一樣", () => {
  const a = newRequestKey(), b = newRequestKey();
  assert.match(a, /^[A-Za-z0-9_-]{8,50}$/);
  assert.notEqual(a, b);
  assert.equal(newRequestKey(() => "x".repeat(80)).length, 50);
  assert.equal(newRequestKey(() => "abc"), "vo-abc");
});

test("草稿讀回來:壞掉的當成沒有,好的原樣(鑰匙與鎖住的狀況都在)", () => {
  const good = { requestKey: "vo-12345678", cart: { G02: 2, BAD: 0, X: 1.5, Y: "3", Z: 10000 }, payment_method: "月結",
    delivery_method: "宅配", note: "下午再送", pending: true };
  assert.deepEqual(draftFrom(good), { ...good, cart: { G02: 2 } });
  for (const bad of [null, undefined, "x", 5, {}, { requestKey: "短" }, { requestKey: "有 空白 12345" }, { requestKey: 12345678 }]) {
    const d = draftFrom(bad, random);
    assert.deepEqual([d.cart, d.pending, d.note], [{}, false, ""], JSON.stringify(bad));
    assert.match(d.requestKey, /^vo-seed-\d+$/);
  }
  assert.equal(draftFrom({ requestKey: "vo-12345678", pending: "yes" }).pending, false);
  assert.equal(draftFrom({ requestKey: "vo-12345678", note: "長".repeat(300) }).note.length, 200);
});

test("送出之後:成立、明確沒成立、不知道", () => {
  assert.deepEqual(outcomeOf(201, "placed", ""), { kind: "placed" });
  assert.deepEqual(outcomeOf(200, "placed", ""), { kind: "placed" });
  assert.deepEqual(outcomeOf(201, "unknown", "連不到膜總裁"), { kind: "unknown", message: "連不到膜總裁" });
  assert.equal(outcomeOf(200, "sending", "").kind, "unknown");
  assert.equal(outcomeOf(200, undefined, "").kind, "unknown");
  assert.deepEqual(outcomeOf(400, undefined, "月結額度不足"), { kind: "refused", message: "月結額度不足" });
  assert.equal(outcomeOf(403, undefined, "沒有權限").kind, "refused");
  assert.equal(outcomeOf(404, undefined, "").kind, "refused");
  // 正在送出、逾時、伺服器出錯、沒有連到:都不能當成沒成立(重開一張會變兩張)
  for (const status of [409, 408, 500, 502, 503, 0]) assert.equal(outcomeOf(status, undefined, "").kind, "unknown", String(status));
  assert.equal(outcomeOf(0, undefined, "").message, "沒有連到伺服器");
});

test("送出之後草稿怎麼變:成立才換新鑰匙;沒成立留著改;不知道就鎖住、鑰匙不變", () => {
  const draft = { requestKey: "vo-12345678", cart: { G02: 2 }, payment_method: "貨到付款", delivery_method: "自取", note: "x", pending: false };
  const placed = afterSend(draft, { kind: "placed" }, random);
  assert.notEqual(placed.requestKey, draft.requestKey);
  assert.deepEqual([placed.cart, placed.note, placed.pending, placed.payment_method, placed.delivery_method], [{}, "", false, "貨到付款", "自取"]);
  assert.deepEqual(afterSend({ ...draft, pending: true }, { kind: "refused", message: "x" }), { ...draft, pending: false });
  assert.deepEqual(afterSend(draft, { kind: "unknown", message: "x" }), { ...draft, pending: true });
  assert.equal(emptyDraft(random).pending, false);
});

test("總額與運費:還不知道寫 —,不寫成 0", () => {
  assert.equal(amountText("7500.00"), "7,500");
  assert.equal(amountText("0.00"), "0");
  assert.equal(amountText(null), "—");
  assert.equal(amountText(undefined), "—");
  assert.equal(amountText(""), "—");
});

test("找商品:每一段字都要對得上;只看已選;藏起來的已選照樣算在合計裡", () => {
  const rows = [...ROWS, row("M01#902", { kind: "膜速箱", pack_qty: 5, spec_id: 902, spec_label: "K44", name: "膜速箱補貨" }),
    row("G03", { name: "高透亮面(平板)", size: "200*280" })];
  rows[3] = { ...rows[3], kind: "膜速箱", name: "膜速箱補貨" };
  const keys = (filter, cart = {}) => filterRows(rows, { text: "", kind: "", pickedOnly: false, ...filter }, cart).map((r) => r.key);
  assert.deepEqual(keys({}), rows.map((r) => r.key));
  assert.deepEqual(keys({ text: "k43" }), ["M01#901"]);
  assert.deepEqual(keys({ text: " 膜速箱  K44 " }), ["M01#902"]);
  assert.deepEqual(keys({ text: "g0" }), ["G02", "G01", "G03"]);
  assert.deepEqual(keys({ text: "200*280" }), ["G03"]);
  assert.deepEqual(keys({ text: "沒有這個" }), []);
  assert.deepEqual(keys({ kind: "膜速箱" }), ["M01#901", "M01#902"]);
  assert.deepEqual(keys({ kind: "膜速箱", text: "iphone" }), ["M01#901"]);
  assert.deepEqual(keys({ pickedOnly: true }, { G01: 1, "M01#902": 2, GONE: 3 }), ["G01", "M01#902"]);
  assert.deepEqual(keys({ pickedOnly: true }), []);
  assert.deepEqual(kindsOf(rows), ["片材規格", "膜速箱"]);
  assert.deepEqual(kindsOf([]), []);
  // 篩掉看不到的那幾列,合計還是全部已選的
  assert.equal(summarize({ G01: 1, "M01#902": 2 }, rows).lines.length, 2);
});

test("清單上的時間是這台電腦的時間,不是把世界時間的字串直接切下來", () => {
  const pad = (n) => String(n).padStart(2, "0");
  const local = (iso) => { const d = new Date(iso); return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`; };
  for (const iso of ["2026-10-10T07:29:41.123456Z", "2026-10-10T15:29:41+08:00", "2026-12-31T23:59:00Z"]) assert.equal(whenText(iso), local(iso));
  // 同一個時刻的兩種寫法顯示成一樣(切字串的話會是 07:29 與 15:29)
  assert.equal(whenText("2026-10-10T07:29:00Z"), whenText("2026-10-10T15:29:00+08:00"));
  assert.match(whenText("2026-10-10T07:29:00Z"), /^\d{2}-\d{2} \d{2}:\d{2}$/);
  for (const bad of [null, undefined, "", "不是時間"]) assert.equal(whenText(bad), "");
});

test("按下送出、請求還沒出去就先鎖住並存起來(重新整理回來還是鎖著、同一把鑰匙)", () => {
  const draft = { requestKey: "vo-12345678", cart: { G02: 2 }, payment_method: "月結", delivery_method: "宅配", note: "x", pending: false };
  assert.deepEqual(beforeSend(draft), { ...draft, pending: true });
  assert.equal(draft.pending, false);                       // 不改到原本那一份
  // 存起來再讀回來(= 重新整理):還是鎖著、鑰匙與內容都沒變
  assert.deepEqual(draftFrom(JSON.parse(JSON.stringify(beforeSend(draft)))), { ...draft, pending: true });
  // 叫貨頁真的是先鎖、先存,才送出去
  const page = readFileSync(new URL("../pages/vendor-orders/VendorOrdersPage.tsx", import.meta.url), "utf8");
  const body = page.slice(page.indexOf("async function send()"));
  const lock = body.indexOf("setDraft(beforeSend("), go = body.indexOf("place.mutateAsync(");
  assert.ok(lock > 0 && go > 0 && lock < go, "send() 要先 setDraft(beforeSend(…)) 才 place.mutateAsync(…)");
});

test("回來的已成立那一張是不是這張草稿:每一列的包數都一樣才算", () => {
  const items = [{ sku: "G02", spec_id: null, packs: 2 }, { sku: "M01", spec_id: 901, packs: 3 }];
  assert.equal(sameAsSent({ G02: 2, "M01#901": 3 }, items), true);
  assert.equal(sameAsSent({ "M01#901": 3, G02: 2 }, items), true);          // 順序不管
  assert.equal(sameAsSent({ G01: 2, "M01#901": 3 }, items), false);         // 換了東西
  assert.equal(sameAsSent({ G02: 5, "M01#901": 3 }, items), false);         // 改了包數
  assert.equal(sameAsSent({ G02: 2 }, items), false);                       // 少一列
  assert.equal(sameAsSent({ G02: 2, "M01#901": 3, G01: 1 }, items), false); // 多一列
  assert.equal(sameAsSent({ M01: 3, G02: 2 }, items), false);               // 規格不一樣
  assert.equal(sameAsSent({ G02: 2, "M01#901": 3, G01: 0 }, items), true);  // 0 包的不算一列
  assert.equal(sameAsSent({}, items), true);                                // 草稿是空的:沒有東西可比
});

test("送出之後其中一項下架:比的是草稿的完整內容,不是現在清單上還有的那幾列", () => {
  // 叫了 G02 × 2、G01 × 3,廠商成立了但回應沒回來;之後 G01 下架
  const cart = { G02: 2, G01: 3 };
  const placed = [{ sku: "G02", spec_id: null, packs: 2 }, { sku: "G01", spec_id: null, packs: 3 }];
  const rowsNow = ROWS.filter((r) => r.key !== "G01");
  const stillListed = linesToSend(summarize(cart, rowsNow));
  assert.deepEqual(stillListed, [{ key: "G02", packs: 2 }]);            // 照現在的清單只剩一列
  assert.equal(sameAsSent(cart, placed), true);                           // 但成立的就是這張草稿:不能說「這一份還沒送出」
  // 叫貨頁比的是草稿的購物車
  const page = readFileSync(new URL("../pages/vendor-orders/VendorOrdersPage.tsx", import.meta.url), "utf8");
  const body = page.slice(page.indexOf("async function send()"));
  assert.ok(body.includes("sameAsSent(now.cart, order.items)"), "send() 要拿 now.cart 去比");
  assert.ok(!/sameAsSent\(\s*sent\b/.test(body), "不能拿照清單篩過的 sent 去比");
});

test("這把鑰匙成立的是先前的另一份:現在這一份留著、換新鑰匙、不鎖(不能當成這一份成立了)", () => {
  const draft = { requestKey: "vo-12345678", cart: { G01: 9 }, payment_method: "月結", delivery_method: "宅配", note: "x", pending: true };
  const next = afterSend(draft, { kind: "other", orderNo: "MO-1" }, random);
  assert.deepEqual([next.cart, next.note, next.pending, next.payment_method], [{ G01: 9 }, "x", false, "月結"]);
  assert.notEqual(next.requestKey, draft.requestKey);
  assert.match(next.requestKey, /^vo-seed-\d+$/);
});
