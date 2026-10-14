// 批次貼上:一行怎麼切。跑法:npm test。
import assert from "node:assert/strict";
import test from "node:test";

import { parseLine } from "./batchPaste.ts";

test("從 Excel 複製的(Tab):第四格才是序號,後面的欄不算序號", () => {
  const row = parseLine("iPhone 13 128G 白色\t1\t12000\t356121234567891\tB\t16800\t85\t輕微擦痕");
  assert.deepEqual([row.rawProductText, row.qty, row.unit_price, row.serials], ["iPhone 13 128G 白色", 1, "12000", ["356121234567891"]]);
  assert.deepEqual(parseLine("iPhone 16\t2\t32000\t356121234567890; 356121234567891").serials, ["356121234567890", "356121234567891"]);
});

test("用空白 / 逗號分的照舊:第三格之後都是序號", () => {
  assert.deepEqual(parseLine("PH-000023 2 29000 356121234567000 356121234567001").serials, ["356121234567000", "356121234567001"]);
  assert.deepEqual(parseLine("PH-000023,1,29000,356121234567000"),
    { raw: "PH-000023,1,29000,356121234567000", rawProductText: "PH-000023", qty: 1, unit_price: "29000", serials: ["356121234567000"] });
  assert.equal(parseLine("   "), null);
  assert.equal(parseLine("只有品名"), null);
});
