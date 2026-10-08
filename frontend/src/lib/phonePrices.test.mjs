// 「新增手機型號」每個容量的建議售價。跑法:npm test(Node 22.6 以上,直接讀 .ts)。
import assert from "node:assert/strict";
import test from "node:test";

import { planKey, priceOf, pricesPayload, tidyChips, withPrice } from "./phonePrices.ts";

test("改一格不動別格,也不動原本那一份", () => {
  const before = { "256GB": "29900" };
  const after = withPrice(before, "512GB", "36900");
  assert.deepEqual(after, { "256GB": "29900", "512GB": "36900" });
  assert.deepEqual(before, { "256GB": "29900" });
  assert.deepEqual(withPrice(after, "256GB", ""), { "256GB": "", "512GB": "36900" });
});

test("送出去的是現在選的每一個容量,各一格、整數元", () => {
  const prices = { "256GB": "29900", "512GB": "36900.5", "1TB": "44900.4" };
  assert.deepEqual(pricesPayload(["256GB", "512GB", "1TB"], prices), {
    "256GB": "29900", "512GB": "36901", "1TB": "44900",
  });
});

test("建議售價沒有負的:開頭的負號直接拿掉", () => {
  assert.deepEqual(withPrice({}, "256GB", "-100"), { "256GB": "100" });
  assert.deepEqual(withPrice({}, "256GB", "-"), { "256GB": "" });
  assert.deepEqual(withPrice({}, "256GB", " --5"), { "256GB": "5" });
  assert.deepEqual(withPrice({}, "256GB", "29900"), { "256GB": "29900" });
});

test("數字中間的負號是數字的一部分,不能拿掉(貼上 1e-3 不會變成 1000)", () => {
  const prices = withPrice({}, "256GB", "1e-3");
  assert.deepEqual(prices, { "256GB": "1e-3" });
  assert.deepEqual(pricesPayload(["256GB"], prices), { "256GB": "0" }); // 0.001 收成整數元是 0
  assert.deepEqual(pricesPayload(["256GB"], withPrice({}, "256GB", "-1e-3")), { "256GB": "0" });
  assert.deepEqual(pricesPayload(["256GB"], withPrice({}, "256GB", "1e3")), { "256GB": "1000" });
});

test("容量的字叫什麼都當成一般的鍵(__proto__、constructor、toString)", () => {
  for (const cap of ["__proto__", "constructor", "toString", "hasOwnProperty"]) {
    assert.equal(priceOf({}, cap), "", cap); // 沒打過就是空的,不會拿到物件本來就有的東西
    assert.equal(pricesPayload([cap], {})[cap], "0", cap);
    const prices = withPrice({}, cap, "29900");
    assert.equal(priceOf(prices, cap), "29900", cap);
    const sent = pricesPayload([cap, "256GB"], withPrice(prices, "256GB", "31900"));
    assert.deepEqual(Object.keys(sent), [cap, "256GB"], cap);
    assert.equal(JSON.parse(JSON.stringify(sent))[cap], "29900", cap); // 真的送得出去
    assert.equal(sent["256GB"], "31900", cap);
  }
});

test("空白的容量不送價錢(伺服器不會建它,送了整批會被退回)", () => {
  assert.deepEqual(pricesPayload(["256GB", "", "   "], { "256GB": "29900", "": "1", "   ": "2" }), {
    "256GB": "29900",
  });
});

test("範本帶進來的容量:去空白、丟掉空的、同一個字只留一個,順序不變", () => {
  assert.deepEqual(tidyChips([" 256GB ", "", "128GB", "   ", "256GB", "512GB"]), ["256GB", "128GB", "512GB"]);
  assert.deepEqual(tidyChips([]), []);
  const given = [" a "];
  tidyChips(given);
  assert.deepEqual(given, [" a "]); // 不動原本那一份
});

test("要建的內容的指紋:內容一樣就一樣(不管是不是預覽、理由填了什麼、欄位的順序)", () => {
  const plan = { brand_id: 1, capacities: ["256GB", "512GB"], list_prices: { "256GB": "29900", "512GB": "36900" } };
  assert.equal(planKey({ ...plan, dry_run: true }), planKey({ ...plan, dry_run: false }));
  assert.equal(planKey({ ...plan, distinct_reasons: { a: "不同" } }), planKey(plan));
  assert.equal(planKey({ list_prices: { "512GB": "36900", "256GB": "29900" }, capacities: ["256GB", "512GB"], brand_id: 1 }), planKey(plan));
});

test("要建的內容變了,指紋就不一樣(容量、價錢、順序、別的欄位)", () => {
  const plan = { brand_id: 1, capacities: ["256GB", "512GB"], list_prices: { "256GB": "29900", "512GB": "36900" } };
  const key = planKey(plan);
  assert.notEqual(planKey({ ...plan, capacities: ["128GB", "512GB"] }), key);
  assert.notEqual(planKey({ ...plan, capacities: ["512GB", "256GB"] }), key);
  assert.notEqual(planKey({ ...plan, list_prices: { "256GB": "29900", "512GB": "0" } }), key);
  assert.notEqual(planKey({ ...plan, brand_id: 2 }), key);
  assert.notEqual(planKey({ ...plan, colors: ["黑"] }), key);
});

test("沒填的容量送 0(伺服器那一邊每個容量都拿得到值)", () => {
  assert.deepEqual(pricesPayload(["256GB", "512GB"], { "256GB": "29900" }), {
    "256GB": "29900", "512GB": "0",
  });
  assert.deepEqual(pricesPayload(["256GB"], { "256GB": "  " }), { "256GB": "0" });
});

test("已經拿掉的容量不送(字還留著,加回來還在)", () => {
  const prices = { "128GB": "25900", "256GB": "29900" };
  assert.deepEqual(pricesPayload(["256GB"], prices), { "256GB": "29900" });
  assert.deepEqual(pricesPayload(["256GB", "128GB"], prices), { "256GB": "29900", "128GB": "25900" });
  assert.deepEqual(pricesPayload([], prices), {});
});
