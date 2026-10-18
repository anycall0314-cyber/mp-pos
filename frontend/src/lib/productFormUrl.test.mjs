// 商品建檔整頁的網址(SPEC-005)。跑法:npm test。
import assert from "node:assert/strict";
import test from "node:test";

import { newProductUrl, prefillFromParams } from "./productFormUrl.ts";

test("先找的那一句帶到新分頁,再原樣讀回來(含空白、斜線、加號)", () => {
  const url = newProductUrl({ name: "背蓋/DAP/IP17 PM+/透", barcode: "4710007834930" });
  assert.ok(url.startsWith("/products/new?"));
  const back = prefillFromParams(new URL(url, "http://x").searchParams);
  assert.deepEqual(back, { name: "背蓋/DAP/IP17 PM+/透", barcode: "4710007834930" });
});

test("沒帶字就是乾淨的新增頁", () => {
  assert.equal(newProductUrl(null), "/products/new");
  assert.equal(newProductUrl({ name: "  ", barcode: "" }), "/products/new");
  assert.deepEqual(prefillFromParams(new URLSearchParams("")), { name: "", barcode: "" });
});
