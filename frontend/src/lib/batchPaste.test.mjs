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

test("批次貼上對不到的那幾列放進「沒加入」:第幾列、幾件、序號幾個(全站檢視 C8)", async () => {
  const { pasteLeftovers } = await import("./batchPaste.ts");
  const rows = [
    { rawProductText: "IP17 玻璃貼", productOption: { id: 1 }, qty: 5, serials: [] },
    { rawProductText: " 不知道的東西 ", productOption: null, qty: 3, serials: [] },
    { rawProductText: "", productOption: null, qty: 2, serials: ["A1", "A2"] },
  ];
  assert.deepEqual(pasteLeftovers(rows), [
    { kw: "不知道的東西", reason: "批次貼上第 2 列,3 件,對不到" },
    { kw: "第 3 列", reason: "批次貼上第 3 列,2 件、序號 2 個,對不到" },
  ]);
  assert.deepEqual(pasteLeftovers(rows.slice(0, 1)), []);
});
