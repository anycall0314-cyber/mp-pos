// 廠商叫貨在畫面這一側:包數、合計、鑰匙與「送出去了還不知道結果」。跑法:npm test。
import assert from "node:assert/strict";
import test from "node:test";

import { readFileSync } from "node:fs";

import {
  afterSend, amountText, beforeSend, commonUnit, draftFrom, emptyDraft, filterRows, kindsOf, linesToSend, newRequestKey, outcomeOf,
  linkedCount, linkedThen, packsFrom, packsText, rowTitle, sameAsSent, sentTitle, sentVendorSide, storeFirst, storeTitle, summarize, vendorSide,
  whenText, withPacks,
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
  assert.deepEqual(linesToSend(sum), [{ key: "G02", packs: 2, was: null }, { key: "M01#901", packs: 3, was: null }]);
  assert.deepEqual(summarize({}, ROWS), { lines: [], packs: 0, pieces: 0, amount: 0, gone: [] });
});

test("清單換過之後不在了、或變成沒有報價的:列出來,不默默丟掉也不照送", () => {
  const sum = summarize({ G02: 1, OLD: 4, S09: 2 }, ROWS);
  assert.deepEqual(sum.lines.map((l) => l.row.key), ["G02"]);
  assert.deepEqual(sum.gone.sort(), ["OLD", "S09"]);
  assert.deepEqual(linesToSend(sum), [{ key: "G02", packs: 1, was: null }]);
  assert.deepEqual(summarize({ G02: 1 }, []).gone, ["G02"]);      // 清單還沒回來 / 是空的
});

test("半自動的廠商:沒有參考價的也可以叫(金額當 0),不算「不在賣了」;真的不在清單上的照樣列出來", () => {
  const cart = { G02: 2, S09: 3, GONE: 1 };
  // 全自動:沒有報價的 S09 不能叫
  const strict = summarize(cart, ROWS);
  assert.deepEqual([strict.lines.map((l) => l.row.key), strict.gone.sort()], [["G02"], ["GONE", "S09"]]);
  // 半自動:S09 照叫,金額只算有價錢的
  const loose = summarize(cart, ROWS, true);
  assert.deepEqual(loose.lines.map((l) => [l.row.key, l.packs, l.pieces, l.amount]), [["G02", 2, 50, 7500], ["S09", 3, 75, 0]]);
  assert.deepEqual([loose.gone, loose.amount, loose.pieces], [["GONE"], 7500, 125]);
  assert.deepEqual(linesToSend(loose), [{ key: "G02", packs: 2, was: null }, { key: "S09", packs: 3, was: null }]);
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
  assert.deepEqual(stillListed, [{ key: "G02", packs: 2, was: null }]);            // 照現在的清單只剩一列
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

test("合計的單位:同一個單位就用它,混在一起寫「件」(每家廠商賣的單位不一樣)", () => {
  assert.equal(commonUnit(["片", "片"]), "片");
  assert.equal(commonUnit(["條"]), "條");
  assert.equal(commonUnit(["條", "個"]), "件");
  assert.equal(commonUnit(["條", "", "條"]), "條");          // 沒寫單位的不算
  assert.equal(commonUnit([]), "件");
  assert.equal(commonUnit(["", ""]), "件");
});

// ── 用店內品名叫貨(交接包 V1)──────────────────────────────────────────────
const film = { id: 7, sku: "AA-000007", name: "甲 高透亮面保護貼", is_active: true };
const head = { id: 9, sku: "CH-000009", name: "甲 20W 充電頭", is_active: true };
const STORE_ROWS = [
  row("G02"),                                                              // 沒連
  row("G01", { name: "D3O 7H", product: film }),
  row("H05", { name: "20W 充電頭", unit: "個", pack_qty: 5, product: head }),
  row("X01", { product: null }),                                           // 沒連(伺服器明講是空的)
  row("H10", { name: "充電頭 大包", unit: "個", pack_qty: 10, product: head }),   // 同一個店內商品的另一種包裝
];

test("大字:連到店內商品的寫店內的品名,沒連的寫廠商的叫法", () => {
  assert.equal(storeTitle(STORE_ROWS[1]), "甲 高透亮面保護貼");
  assert.equal(storeTitle(STORE_ROWS[0]), "品G02");
  assert.equal(storeTitle(STORE_ROWS[3]), "品X01");
  assert.equal(storeTitle({ name: "膜速箱", spec_label: "K43 iPhone 15 Pro", size: "", product: undefined }), "膜速箱 K43 iPhone 15 Pro");
});

test("小字:這一列在廠商那邊是什麼 —— 同一個店內商品的兩種包裝要分得出來", () => {
  // 連到店內商品的:廠商的叫法、料號、一包幾個都要有
  assert.equal(vendorSide(STORE_ROWS[2]), "20W 充電頭 · H05 · 一包 5 個");
  assert.equal(vendorSide(STORE_ROWS[4]), "充電頭 大包 · H10 · 一包 10 個");
  assert.equal(storeTitle(STORE_ROWS[2]), storeTitle(STORE_ROWS[4]));         // 大字一樣
  assert.notEqual(vendorSide(STORE_ROWS[2]), vendorSide(STORE_ROWS[4]));       // 小字分得出來
  // 沒連的:大字已經是廠商的叫法,小字只補料號與包裝
  assert.equal(vendorSide(STORE_ROWS[0]), "G02 · 一包 25 片");
  // 規格、尺寸算在廠商的叫法裡;沒寫單位的用「片」
  assert.equal(
    vendorSide({ name: "膜速箱", spec_label: "K43", size: "6.1", sku: "M01", pack_qty: 5, unit: "", product: film }),
    "膜速箱 K43 6.1 · M01 · 一包 5 片",
  );
});

test("清單的順序:連好的排前面、沒連的排後面,各自照廠商給的順序;沒連的一列都不會不見", () => {
  assert.deepEqual(storeFirst(STORE_ROWS).map((r) => r.key), ["G01", "H05", "H10", "G02", "X01"]);
  assert.equal(storeFirst(STORE_ROWS).length, STORE_ROWS.length);
  assert.deepEqual(storeFirst(ROWS).map((r) => r.key), ROWS.map((r) => r.key));     // 都沒連:原樣
  assert.deepEqual(storeFirst([]), []);
  assert.equal(linkedCount(STORE_ROWS), 3);
  assert.equal(linkedCount(ROWS), 0);
  const before = STORE_ROWS.map((r) => r.key);
  storeFirst(STORE_ROWS);
  assert.deepEqual(STORE_ROWS.map((r) => r.key), before);                            // 原本那一份不被改到
});

test("找:店內的品名 / 品號、廠商的品名 / 料號都找得到同一列;「只看店內」只留連好的", () => {
  const keys = (filter) => filterRows(STORE_ROWS, { text: "", kind: "", pickedOnly: false, ...filter }, {}).map((r) => r.key);
  assert.deepEqual(keys({ text: "高透亮面" }), ["G01"]);            // 店內的品名
  assert.deepEqual(keys({ text: "aa-000007" }), ["G01"]);          // 店內的品號(不分大小寫)
  assert.deepEqual(keys({ text: "d3o" }), ["G01"]);                // 廠商的品名
  assert.deepEqual(keys({ text: "g01" }), ["G01"]);                // 廠商的料號
  assert.deepEqual(keys({ text: "充電頭" }), ["H05", "H10"]);      // 店內品名、廠商品名都有這幾個字
  assert.deepEqual(keys({ text: "充電頭 大包" }), ["H10"]);        // 每一段字都要有:可以拿廠商的叫法分出包裝
  assert.deepEqual(keys({ text: "甲 h05" }), ["H05"]);             // 一段是店內的、一段是廠商的也行
  assert.deepEqual(keys({ linkedOnly: true }), ["G01", "H05", "H10"]);
  assert.deepEqual(keys({ linkedOnly: false }), ["G02", "G01", "H05", "X01", "H10"]);
  assert.deepEqual(keys({ linkedOnly: true, text: "品" }), []);    // 沒連的那幾列才有「品」
  assert.deepEqual(keys({ text: "品x01" }), ["X01"]);              // 沒連的照樣找得到(可以叫)
});

test("送出去的每一行帶著「畫面上看到它連到哪個店內商品」;沒連的是 null", () => {
  const sum = summarize({ G02: 1, G01: 2, H10: 3 }, STORE_ROWS);
  assert.deepEqual(linesToSend(sum), [
    { key: "G02", packs: 1, was: null },
    { key: "G01", packs: 2, was: 7 },
    { key: "H10", packs: 3, was: 9 },
  ]);
  // 同一個店內商品的兩種包裝是兩行、各算各的個數(2 包 × 5 與 2 包 × 10)
  const both = summarize({ H05: 2, H10: 2 }, STORE_ROWS);
  assert.deepEqual(both.lines.map((l) => [storeTitle(l.row), l.row.key, l.packs, l.pieces]), [
    ["甲 20W 充電頭", "H05", 2, 10],
    ["甲 20W 充電頭", "H10", 2, 20],
  ]);
});

test("叫貨紀錄:寫叫貨當下的店內品名,底下補廠商當時的叫法;那時候沒連的照舊寫廠商的", () => {
  const linked = { name: "20W 充電頭", spec_label: "白", product_name: "甲 20W 充電頭" };
  assert.equal(sentTitle(linked), "甲 20W 充電頭");
  assert.equal(sentVendorSide(linked), "20W 充電頭 白");
  for (const old of [{ name: "高透亮面", spec_label: "" }, { name: "高透亮面", spec_label: "", product_name: "" }]) {
    assert.equal(sentTitle(old), "高透亮面");
    assert.equal(sentVendorSide(old), "");                          // 大字已經是廠商的叫法,不重複
  }
});

test("叫貨頁:清單、確認框、叫貨紀錄都是店內品名在上、廠商的叫法在下;被擋下來會重抓清單", () => {
  const page = readFileSync(new URL("../pages/vendor-orders/VendorOrdersPage.tsx", import.meta.url), "utf8");
  // 清單:連好的排前面;大字用 storeTitle,連好的底下寫廠商的叫法;沒連的標「未對照」(一個都沒連的店不標,免得整頁都是)
  assert.match(page, /const rows = useMemo\(\(\) => storeFirst\(catalog\.data\?\.rows \?\? \[\]\), \[catalog\.data\]\);/);
  assert.match(page, /<td className="vo-name">\s*\{storeTitle\(row\)\}/);
  assert.match(page, /\{row\.product && <div className="vo-sub">\{rowTitle\(row\)\}<\/div>\}/);
  assert.match(page, /\{!row\.product && linked > 0 && <span className="wb-badge">未對照<\/span>\}/);
  assert.match(page, /\{row\.product && !row\.product\.is_active && <span className="wb-badge warn">已停用<\/span>\}/);
  // 找:帶著「只看店內」;有連的也有沒連的時候才出現那個勾
  assert.match(page, /filterRows\(rows, \{ text, kind, pickedOnly, linkedOnly \}, draft\.cart\)/);
  assert.match(page, /const canPickLinked = linked > 0 && linked < rows\.length;\s*const linkedOnly = wantLinkedOnly && canPickLinked;/);
  assert.match(page, /\{canPickLinked && \(\s*<label className="vo-check">\s*<input type="checkbox" checked=\{linkedOnly\}/);
  // 確認框:每一行底下都有廠商那邊是什麼(料號、一包幾個)
  assert.match(page, /\{storeTitle\(l\.row\)\}[^]{0,200}<div className="vo-sub">\{vendorSide\(l\.row\)\}<\/div>/);
  // 叫貨紀錄:叫貨當下的店內品名
  assert.match(page, /\{sentTitle\(i\)\}\s*\{sentVendorSide\(i\) && <div className="vo-sub">\{sentVendorSide\(i\)\}<\/div>\}/);
  // 被擋下來(可能是對照剛被改):重抓清單;包數留在草稿裡(afterSend 的 refused 不清購物車)
  const body = page.slice(page.indexOf("async function send()"));
  assert.match(body, /outcome\.kind === "refused"\) \{[^}]*void catalog\.refetch\(\);/);
  const draft = { ...emptyDraft(random), cart: { G02: 2, G01: 1 }, pending: true };
  assert.deepEqual(afterSend(draft, { kind: "refused", message: "對照剛剛被改了" }).cart, { G02: 2, G01: 1 });
  // 對照分頁改了對照:叫貨那一頁的清單要重抓
  const hooks = readFileSync(new URL("../api/hooks.ts", import.meta.url), "utf8");
  assert.match(hooks, /qc\.invalidateQueries\(\{ queryKey: \["vendor-catalog", vars\.warehouse, vars\.vendor\] \}\);/);
});

test("拿回來的是先前就成立的那一張、當時連到的店內商品跟畫面上的不一樣:講是哪幾行、當時連到誰", () => {
  const items = [
    { sku: "G02", spec_id: null, name: "高透亮面", spec_label: "", product: 7, product_name: "甲 高透亮面保護貼" },
    { sku: "M01", spec_id: 901, name: "膜速箱", spec_label: "K43", product: null, product_name: "" },
    { sku: "G01", spec_id: null, name: "D3O 7H", spec_label: "", product: 9, product_name: "甲 D3O 保護貼" },
  ];
  // 正常送出:畫面看到的跟單上記的一樣 → 沒有話要講
  assert.deepEqual(linkedThen([{ key: "G02", packs: 1, was: 7 }, { key: "M01#901", packs: 1, was: null }, { key: "G01", packs: 1, was: 9 }], items), []);
  // 另一個分頁先送了、之後對照才改:畫面上是 8,單上記的是當時的 7
  assert.deepEqual(linkedThen([{ key: "G02", packs: 1, was: 8 }, { key: "M01#901", packs: 1, was: null }], items),
    ["「高透亮面」當時連到的是「甲 高透亮面保護貼」"]);
  // 當時沒連、現在畫面上有連;當時有連、現在畫面上沒連
  assert.deepEqual(linkedThen([{ key: "M01#901", packs: 1, was: 5 }, { key: "G01", packs: 1, was: null }], items),
    ["「膜速箱 K43」當時連到的是沒有對照", "「D3O 7H」當時連到的是「甲 D3O 保護貼」"]);
  // 很早以前的單(沒有這幾格)當成當時沒連;畫面沒送的那幾行(清單沒載到)不比
  assert.deepEqual(linkedThen([{ key: "G02", packs: 1, was: null }], [{ sku: "G02", spec_id: null, name: "高透亮面", spec_label: "" }]), []);
  assert.deepEqual(linkedThen([], items), []);
  // 叫貨頁成立之後會講這件事
  const page = readFileSync(new URL("../pages/vendor-orders/VendorOrdersPage.tsx", import.meta.url), "utf8");
  const body = page.slice(page.indexOf("async function send()"));
  assert.match(body, /const then = linkedThen\(sent, order\.items\);\s*if \(then\.length > 0\) \{\s*toast\(`這張單先前就成立了,沒有再叫一次。\$\{then\.join\(";"\)\}`/);
});
