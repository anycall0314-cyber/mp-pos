// 結帳拆帳:點空的那一格自動填剩下的(全站檢視 A10)。跑法:npm test。
import assert from "node:assert/strict";
import test from "node:test";

import { fillRemaining } from "./splitPay.ts";

test("空的或 0 的那一格:填還差多少", () => {
  assert.equal(fillRemaining("0", 12000), "12000");
  assert.equal(fillRemaining("", 3500), "3500");
  assert.equal(fillRemaining(undefined, 1), "1");
});

test("已經有數字、或已經收夠:不動", () => {
  assert.equal(fillRemaining("5000", 7000), null);
  assert.equal(fillRemaining("0", 0), null);
  assert.equal(fillRemaining("0", -300), null);      // 收超過了
});
