// 新增配件時照品名先勾好適用機型(V2)。跑法:npm test。
import assert from "node:assert/strict";
import test from "node:test";

import { manualKeys, withPicked, withRemoved, withSuggested } from "./fitSuggest.ts";

const m = (k) => ({ model_key: k, model_name: k.toUpperCase() });
const empty = { related_models: [], fits_auto: [], fits_removed: [], name: "x" };
const keys = (s) => s.related_models.map((c) => c.model_key);

test("照品名的建議自動放上去,換品名時上一次自動放的換掉、人自己挑的不動", () => {
  let s = withPicked(empty, m("ip14"));
  s = withSuggested(s, [m("ip15pm"), m("ip16pm")]);
  assert.deepEqual(keys(s), ["ip14", "ip15pm", "ip16pm"]);
  assert.deepEqual(s.fits_auto, ["ip15pm", "ip16pm"]);
  assert.equal(s.name, "x");                                  // 其他欄位留著
  s = withSuggested(s, [m("ip16pm"), m("ip17pm")]);
  assert.deepEqual(keys(s), ["ip14", "ip16pm", "ip17pm"]);
  s = withSuggested(s, []);
  assert.deepEqual(keys(s), ["ip14"]);                        // 品名清掉:自動放的都拿掉,挑的留著
  assert.deepEqual(s.fits_auto, []);
});

test("人拿掉的不再自動放;自己再挑一次就算回來", () => {
  let s = withSuggested(empty, [m("ip15pm"), m("ip16pm")]);
  s = withRemoved(s, "ip16pm");
  assert.deepEqual(s.fits_removed, ["ip16pm"]);
  s = withSuggested(s, [m("ip15pm"), m("ip16pm")]);
  assert.deepEqual(keys(s), ["ip15pm"]);
  s = withPicked(s, m("ip16pm"));
  assert.deepEqual(s.fits_removed, []);
  assert.deepEqual(keys(s), ["ip15pm", "ip16pm"]);
  s = withSuggested(s, []);
  assert.deepEqual(keys(s), ["ip16pm"]);                      // 自己挑回來的是人挑的,不跟著品名走
});

test("建議裡已經是人挑的不重複放、也不變成自動;沒變就回原本那一份", () => {
  let s = withPicked(empty, m("ip15pm"));
  const same = withSuggested(s, [m("ip15pm"), m("ip15pm")]);
  assert.equal(same, s);
  assert.deepEqual(s.fits_auto, []);
  s = withSuggested(s, [m("ip16pm")]);
  assert.equal(withSuggested(s, [m("ip16pm")]), s);
  assert.equal(withPicked(s, m("ip15pm")), s);
});

test("問伺服器時只帶人自己挑的", () => {
  let s = withPicked(empty, m("b"));
  s = withPicked(s, m("a"));
  s = withSuggested(s, [m("c")]);
  assert.equal(manualKeys(s), "a,b");
});
