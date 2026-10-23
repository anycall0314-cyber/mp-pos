// 清單上直接改的數字格的存檔狀態(UI 改善計劃 UI-13)。跑法:npm test。
import assert from "node:assert/strict";
import test from "node:test";

import { needsSave, phaseText, takeServerValue } from "./inlineSave.ts";

test("清單重新整理時:打過字、正在存、沒存成的格子不被換掉;只是點進去的照樣換", () => {
  assert.equal(takeServerValue("idle", false), true);
  assert.equal(takeServerValue("saved", false), true);
  assert.equal(takeServerValue("idle", true), false);
  assert.equal(takeServerValue("saving", false), false);
  assert.equal(takeServerValue("failed", true), false);
});

test("點進去沒打字:別人改了也不把舊的存回去(複審 P0)", () => {
  assert.equal(needsSave("1500", "1800", false), false);
  assert.equal(needsSave("1600", "1800", true), true);
});

test("跟伺服器一樣就不送(收成整數比)", () => {
  assert.equal(needsSave("1500", "1500.00"), false);
  assert.equal(needsSave("1600", "1500.00"), true);
  assert.equal(needsSave("", "0"), false);          // 清空 = 0(格子不收逗號、小數)
});

test("狀態字", () => {
  assert.deepEqual(["idle", "saving", "saved", "failed"].map(phaseText), ["", "存檔中", "已存", "沒存成"]);
});
