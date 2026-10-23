// 現金調整:事由決定方向(全站檢視 E7)。跑法:npm test。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { directionOfReason } from "./cashAdjust.ts";

test("補充備用金一定是存入、領現存銀行 / 老闆領用一定是提取;盤點校正、其他照人選", () => {
  assert.equal(directionOfReason("refill"), "in");
  assert.equal(directionOfReason("deposit"), "out");
  assert.equal(directionOfReason("owner_take"), "out");
  assert.equal(directionOfReason("adjustment"), null);
  assert.equal(directionOfReason("other"), null);
  const form = readFileSync(new URL("../pages/cash/CashAdjustmentForm.tsx", import.meta.url), "utf8");
  // 先選事由、方向跟著;固定的那幾種方向鎖住
  assert.ok(form.indexOf('<Field label="事由">') < form.indexOf('<Field label="方向" required>'));
  assert.match(form, /disabled=\{directionOfReason\(state\.reason\) !== null\}/);
});
