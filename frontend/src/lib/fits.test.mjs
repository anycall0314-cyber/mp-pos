// 配件的適用機型寫成一行。跑法:npm test。
import assert from "node:assert/strict";
import test from "node:test";

import { fitsLine } from "./fits.ts";

const h = (...names) => names.map((model_name) => ({ model_name }));

test("沒有適用機型就什麼都不寫", () => {
  assert.equal(fitsLine(undefined), "");
  assert.equal(fitsLine([]), "");
});

test("最多寫三款,多的寫總共幾款;重複的只算一次", () => {
  assert.equal(fitsLine(h("iPad Air (2020)", "iPad Air 5 (M1)")), "適用 iPad Air (2020)、iPad Air 5 (M1)");
  assert.equal(fitsLine(h("A", "B", "C", "D", "A")), "適用 A、B、C 等 4 款");
  assert.equal(fitsLine(h("A", "B", "C", "D"), 10), "適用 A、B、C、D");
});
