// 批發品批次上架 / 改價:預覽改完的價、要送什麼、確認那一行。跑法:npm test。
import assert from "node:assert/strict";
import test from "node:test";

import { goodsAfter, goodsConfirmText, goodsNeedsConfirm, goodsPlan, goodsPrice, percentText } from "./tradeGoods.ts";

const row = (product, list_price, extra = {}) => ({ product, name: `品${product}`, list_price, is_listed: false, price: null, percent: null, ...extra });
const screens = [row(1, 2000), row(2, 3000, { is_listed: true, price: 2100 }), row(3, 1000, { is_listed: true, percent: 80 })];

test("現在的批發價:固定價、門市價的幾 %(四捨五入)、照同行折數算不出單一個價", () => {
  assert.deepEqual(screens.map(goodsPrice), [null, 2100, 800]);
  assert.equal(goodsPrice(row(4, 999, { percent: 85 })), 849);              // 849.15
  assert.equal(goodsPrice(row(5, 990, { percent: 85 })), 842);              // 841.5 → 842
  assert.deepEqual([percentText(""), percentText("70"), percentText("0"), percentText("201"), percentText("7.5"), percentText("abc")],
    [undefined, 70, null, null, null, null]);
});

test("改完之後是什麼:這一次的方式;自己那一列打了固定價優先;清空 = 照折數", () => {
  assert.deepEqual(goodsAfter(screens[0], "percent", "70"), { price: null, percent: 70 });
  assert.deepEqual(goodsAfter(screens[0], "fixed", "1,500"), { price: 1500, percent: null });
  assert.deepEqual(goodsAfter(screens[1], "partner", ""), { price: null, percent: null });
  assert.deepEqual(goodsAfter(screens[1], null, ""), { price: 2100, percent: null });      // 不改價
  assert.deepEqual(goodsAfter(screens[0], "percent", "70", "1800"), { price: 1800, percent: null });
  assert.deepEqual(goodsAfter(screens[1], null, "", ""), { price: null, percent: null });
  assert.equal(goodsAfter(screens[0], "percent", "abc"), null);
  assert.equal(goodsAfter(screens[0], null, "", "0"), null);
});

test("要送什麼:只送有變的;開放 / 收回跟改價可以一起", () => {
  let plan = goodsPlan(screens, true, "percent", "70", {});
  assert.deepEqual(plan.rows, [{ product: 1, is_listed: true, percent: 70 }, { product: 2, percent: 70 }, { product: 3, percent: 70 }]);
  assert.deepEqual([plan.before, plan.after, plan.toPartner, plan.odd], [[2100, 800], [1400, 2100, 700], 0, false]);
  plan = goodsPlan(screens, false, null, "", {});
  assert.deepEqual(plan.rows, [{ product: 2, is_listed: false }, { product: 3, is_listed: false }]);       // 本來就沒開放的不送
  plan = goodsPlan(screens, null, "partner", "", {});
  assert.deepEqual([plan.rows, plan.toPartner], [[{ product: 2, price: null }, { product: 3, price: null }], 2]);
  plan = goodsPlan(screens, null, null, "", { 1: "1999" });
  assert.deepEqual(plan.rows, [{ product: 1, price: 1999 }]);
  assert.deepEqual(goodsPlan(screens, null, "fixed", "", {}), { error: "固定價要填正的整數" });
  assert.deepEqual(goodsPlan(screens, null, "percent", "250", {}), { error: "% 要填 1 到 200" });
  assert.deepEqual(goodsPlan(screens, null, null, "", { 2: "x" }), { error: "「品2」的價要填正的整數" });
});

test("確認那一行只有數字;把 70 打進固定價看得出來", () => {
  const plan = goodsPlan(screens, true, "percent", "70", {});
  assert.equal(goodsNeedsConfirm(plan), true);
  assert.equal(goodsConfirmText(plan, true), "3 個 · 開放 · 800–2100 → 700–2100 · 每個同行一樣");
  const typo = goodsPlan(screens, null, "fixed", "70", {});                  // 店員把 70(%)打進固定價
  assert.equal(goodsConfirmText(typo, null), "3 個 · 800–2100 → 70 · 每個同行一樣 · 價差大");
  const back = goodsPlan(screens, null, "partner", "", {});
  assert.equal(goodsConfirmText(back, null), "2 個 · 照折數 2 個");
  const few = goodsPlan(screens.slice(0, 2), true, null, "", {});
  assert.equal(goodsNeedsConfirm(few), false);                              // 開放一個、沒改價:直接做
  const many = goodsPlan(Array.from({ length: 12 }, (_, i) => row(i + 10, 500)), true, null, "", {});
  assert.deepEqual([goodsNeedsConfirm(many), goodsConfirmText(many, true)], [true, "12 個 · 開放"]);
});

test("門市價有小數:門市% 的預覽跟伺服器一樣四捨五入", () => {
  assert.equal(goodsPrice(row(9, 100.99, { percent: 70 })), 71);               // 70.693
  assert.deepEqual(goodsPlan([row(9, 100.99)], null, "percent", "70", {}).after, [71]);
});

test("開放的時候也套用選好的價(預覽的價就是存下去的價)", () => {
  const plan = goodsPlan([row(1, 2000, { price: 500 })], true, "fixed", "700", {});
  assert.deepEqual(plan.rows, [{ product: 1, is_listed: true, price: 700 }]);
});
