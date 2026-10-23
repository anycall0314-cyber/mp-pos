// 打烊實點的差額與輸入(owner 2026-10-23「實點加上去」)。跑法:npm test。
import assert from "node:assert/strict";
import test from "node:test";

import { countedValue, diffText } from "./cashCount.ts";

test("差額:負的是短少、正的是多、0 是相符", () => {
  assert.equal(diffText(0), "相符");
  assert.equal(diffText(-300), "短少 300");
  assert.equal(diffText(1250), "多 1,250");
});

test("點到多少只收整數", () => {
  assert.equal(countedValue(" 12000 "), 12000);
  assert.equal(countedValue("0"), 0);
  for (const bad of ["", "12.5", "-3", "abc"]) assert.equal(countedValue(bad), null, bad);
});
