// 商品表單:商品性質照類別帶,人自己選過就不替他改(全站檢視 D3)。跑法:npm test。
// 「人選過」要跟著草稿走(複審 P1:以前記在畫面的暫存裡,存草稿再載入就忘了,換類別把人選的「通用配件」蓋回「機型配件」)。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const src = readFileSync(new URL("../pages/products/ProductForm.tsx", import.meta.url), "utf8");

test("人選過商品性質記在表單狀態(跟著草稿存),換類別看它", () => {
  assert.match(src, /\n  nature_touched: boolean;/);
  assert.match(src, /if \(!next \|\| state\.nature_touched \|\| state\.warehouse_type !== "product"\) return;/);
  assert.match(src, /function changeNatureByHand\(next: AccessoryType\) \{\s*changeNature\(next\);\s*patch\("nature_touched", true\);/);
  // 載入草稿是把存的那一份整個鋪回去(包含 nature_touched)
  assert.match(src, /const merged = \{ \.\.\.EMPTY, \.\.\.stored \};/);
  // 編輯時用過的商品(庫存屬性鎖住)不跟著類別改
  assert.match(src, /if \(isEdit && flagsLocked\) return;/);
});
