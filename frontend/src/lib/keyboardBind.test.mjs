// 共用欄位與清單的鍵盤(全站檢視 L04)。跑法:npm test。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { soleIndex, stepKey } from "./keyboardBind.ts";

const read = (p) => readFileSync(new URL(p, import.meta.url), "utf8");
const inp = (type = "text", inSearchBox = false, tag = "INPUT") => ({ tag, type, inSearchBox });

test("欄名只綁一格一個框;搜尋盒、type=search、一格好幾個框不綁;隱藏的框不算", () => {
  assert.equal(soleIndex([inp()]), 0);
  assert.equal(soleIndex([inp("hidden"), inp("date")]), 1);
  assert.equal(soleIndex([inp("text", false, "SELECT")]), 0);
  assert.equal(soleIndex([inp("text", true)]), -1, "ComboBox 裡的搜尋框");
  assert.equal(soleIndex([inp("search")]), -1);
  assert.equal(soleIndex([inp(), inp()]), -1, "一格兩個框");
  assert.equal(soleIndex([]), -1);
  const field = read("../components/Field.tsx");
  assert.match(field, /inSearchBox: !!el\.closest\("\.combobox"\)/);
  assert.match(field, /<div className="field-error-msg" id=\{errId\}>/);
  assert.match(field, /if \(!described\) target\.setAttribute\("aria-describedby", errId\);/, "不蓋掉原本就有的說明");
});

test("清單方向鍵換列到頭停住;整張清單只有一個 Tab 停點;鍵盤打開 + 鍵盤關才回到那一列", () => {
  assert.equal(stepKey([1, 2, 3], 1, 1), 2);
  assert.equal(stepKey([1, 2, 3], 3, 1), 3);
  assert.equal(stepKey([1, 2, 3], 1, -1), 1);
  assert.equal(stepKey([1, 2, 3], 9, 1), 1, "現在那一列不在了從第一列開始");
  assert.equal(stepKey([], 1, 1), null);
  const md = read("../components/master-detail/MasterDetail.tsx");
  assert.match(md, /tabIndex=\{k === tabStop \? 0 : -1\}/);
  // 列裡的勾選 / 輸入框 / 按鈕的按鍵不歸列管(全站控制項 F02:電信方案勾選按空白會變成打開詳細)
  assert.match(md, /onKeyDown=\{\(e\) => \{\n\s+\/\/[^\n]*\n\s+if \(e\.target !== e\.currentTarget\) return;/);
  assert.match(read("../pages/products/ProductTypesPage.tsx"), /onKeyDown=\{\(e\) => \{\n\s+\/\/[^\n]*\n\s+if \(e\.target !== e\.currentTarget\) return;\n\s+if \(e\.key === "Enter" \|\| e\.key === " "\)/);
  assert.match(md, /returnTo\.current = keyOpened\.current !== null && e\.detail === 0 \? keyOpened\.current : null;/, "滑鼠按 × 不搬游標(紅隊)");
  assert.match(md, /onClick=\{\(\) => \{\n\s+keyOpened\.current = null;\n\s+setSelectedKey\(k\);/, "滑鼠點列打開的不算鍵盤打開");
});
