// 庫存、盤點、報表、匯入的資訊密度(全站檢視 V06,各頁分開做)。跑法:npm test。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (p) => readFileSync(new URL(p, import.meta.url), "utf8");
const css = read("../styles.css");

test("V06a 庫存查詢:表頭黏在上面、本頁合計黏在下面(寫明本頁);overflow 用 clip(hidden 會讓黏住失效)", () => {
  const page = read("../pages/inventory/InventoryQueryPage.tsx");
  assert.match(page, /<table className="wb-table inv-sticky">/);
  assert.match(page, /本頁合計/);
  assert.match(css, /\.wb-table\.inv-sticky \{ overflow: clip; \}/);
  assert.match(css, /\.wb-table\.inv-sticky thead th \{ position: sticky; top: -14px;/);
  assert.match(css, /\.wb-table\.inv-sticky tr\.total > td \{ position: sticky; bottom: -28px;/);
});
