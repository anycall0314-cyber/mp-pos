// 商品管理按「編輯」改完 / 上一頁回來,清單回到原來的樣子(全站檢視 R07)。跑法:npm test。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { LIST_RETURN_KEY, readListSnapshot, returnTarget, saveListSnapshot } from "./productListReturn.ts";

function memory() {
  const data = {};
  return { data, getItem: (k) => (k in data ? data[k] : null), setItem: (k, v) => (data[k] = v) };
}

const snap = (over = {}) => ({
  leftTab: "products",
  productQuery: "假皮套",
  appliedProductQuery: "假皮套",
  categoryQuery: "",
  selection: { kind: "product", id: 29 },
  detailTab: "basic",
  browseAt: null,
  listScroll: 500,
  ...over,
});

test("按編輯時記下清單的樣子,回到同一頁(同一個瀏覽紀錄)拿得回來;別頁拿不到", () => {
  const store = memory();
  saveListSnapshot(store, "k1", snap());
  assert.deepEqual(readListSnapshot(store, "k1"), snap());
  assert.equal(readListSnapshot(store, "k2"), null);
  assert.deepEqual(readListSnapshot(store, "k1"), snap()); // 不刪:再上一頁 / 下一頁回來還在
  saveListSnapshot(store, "k1", snap({ listScroll: 80 }));
  assert.equal(readListSnapshot(store, "k1").listScroll, 80);
  // 分類瀏覽進去的:頁籤與走到哪一層一起回來
  const browse = { mode: "phone", category: { id: 2, name: "皮套", kind: "accessory" }, brand: { id: "none", name: "未分" } };
  saveListSnapshot(store, "k3", snap({ leftTab: "models", browseAt: browse }));
  assert.deepEqual(readListSnapshot(store, "k3").browseAt, browse);
});

test("只留最近 10 次;壞掉的、瀏覽器不給存的都當成沒有(回來照舊)", () => {
  const store = memory();
  for (let i = 0; i < 12; i += 1) saveListSnapshot(store, `k${i}`, snap({ listScroll: i }));
  assert.equal(readListSnapshot(store, "k0"), null);
  assert.equal(readListSnapshot(store, "k1"), null);
  assert.equal(readListSnapshot(store, "k11").listScroll, 11);
  assert.equal(JSON.parse(store.data[LIST_RETURN_KEY]).order.length, 10);
  store.data[LIST_RETURN_KEY] = "{壞掉";
  assert.equal(readListSnapshot(store, "k11"), null);
  assert.equal(readListSnapshot(null, "k11"), null);
  saveListSnapshot({ getItem: () => null, setItem: () => { throw new Error("full"); } }, "k", snap()); // 不會炸
});

test("編輯頁存好 / 取消:從商品頁點進來的回上一頁;直接打網址進來的去商品頁選到這一筆", () => {
  assert.equal(returnTarget("k1", 3, 29), -1);
  assert.equal(returnTarget(undefined, 3, 29), "/products?selected=29");
  assert.equal(returnTarget("k1", 0, 29), "/products?selected=29"); // 瀏覽紀錄裡沒有上一頁(新分頁打開)
  assert.equal(returnTarget("", 3, 29), "/products?selected=29");
  assert.equal(returnTarget(null, null), "/products");
});

const read = (p) => readFileSync(new URL(p, import.meta.url), "utf8");

test("接法:商品頁照記下的樣子開始、編輯鍵帶鑰匙並記下;編輯頁照 returnTarget 回去;改用既有商品照舊去選那一個", () => {
  const page = read("../pages/products/ProductsPage.tsx");
  assert.match(page, /const \[back\] = useState\(\(\) => readListSnapshot\(sessionStore\(\), location\.key\)\);/);
  for (const init of [
    'useState(back?.productQuery ?? "")',
    'useState(back?.appliedProductQuery ?? "")',
    'useState(back?.categoryQuery ?? "")',
    "useState<Selection>((back?.selection as Selection | undefined) ?? null)",
    'back?.leftTab ?? "products"',
    'useState<"basic" | "aliases">(back?.detailTab ?? "basic")',
  ]) {
    assert.ok(page.includes(init), init);
  }
  assert.match(page, /state=\{\{ listKey: location\.key \}\}\s+onClick=\{\(\) => saveListSnapshot\(sessionStore\(\), location\.key, listSnapshot\(\)\)\}/);
  assert.match(page, /listBody\.current\.scrollTop = back\.listScroll;/);
  assert.match(page, /initialAt=\{browseAt\.current\}/);
  const form = read("../pages/products/ProductFormPage.tsx");
  assert.match(form, /const to = returnTarget\(\s*\(location\.state as \{ listKey\?: unknown \} \| null\)\?\.listKey,/);
  assert.match(form, /if \(to === -1\) nav\(-1\);\s+else nav\(to\);/);
  assert.match(form, /nav\(`\/products\?selected=\$\{existing\}`\);/);
});
