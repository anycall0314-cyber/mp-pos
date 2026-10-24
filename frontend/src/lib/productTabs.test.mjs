// 從商品管理另開的分頁做完回原本那一頁(全站檢視 D4)。跑法:npm test。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { PRODUCT_SAVED_MSG, isProductSavedMessage } from "./productTabs.ts";

test("只認得自己的訊息:型別對、編號是數字或 null", () => {
  assert.equal(isProductSavedMessage({ type: PRODUCT_SAVED_MSG, id: 3 }), true);
  assert.equal(isProductSavedMessage({ type: PRODUCT_SAVED_MSG, id: null }), true);
  assert.equal(isProductSavedMessage({ type: PRODUCT_SAVED_MSG, id: null, find: "iPhone 17 Pro" }), true);
  assert.equal(isProductSavedMessage({ type: PRODUCT_SAVED_MSG, id: null, find: 3 }), false);
  assert.equal(isProductSavedMessage({ type: PRODUCT_SAVED_MSG, id: "3" }), false);
  assert.equal(isProductSavedMessage({ type: "other", id: 3 }), false);
  assert.equal(isProductSavedMessage(null), false);
});

test("新增商品「回商品頁」先回原本那一頁、沒有才在這一頁換頁;商品管理聽訊息時看來源", () => {
  const form = readFileSync(new URL("../pages/products/ProductFormPage.tsx", import.meta.url), "utf8");
  assert.match(form, /if \(!backToOpener\(saved\.id\)\) backToList\(saved\.id\);/);
  const list = readFileSync(new URL("../pages/products/ProductsPage.tsx", import.meta.url), "utf8");
  assert.match(list, /e\.origin !== window\.location\.origin \|\| !isProductSavedMessage\(e\.data\)/);
});
