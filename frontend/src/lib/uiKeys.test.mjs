// 共用控制項的方向鍵規則與元件契約(docs/ui-controls.md §3、§4)。跑法:npm test。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { cx, nextIndex } from "./uiKeys.ts";

const read = (p) => readFileSync(new URL(p, import.meta.url), "utf8");

test("方向鍵:左右換一個、到頭繞回;Home / End;停用的跳過;其他鍵不處理", () => {
  assert.equal(nextIndex(3, 0, "ArrowRight"), 1);
  assert.equal(nextIndex(3, 2, "ArrowRight"), 0);
  assert.equal(nextIndex(3, 0, "ArrowLeft"), 2);
  assert.equal(nextIndex(3, 1, "Home"), 0);
  assert.equal(nextIndex(3, 0, "End"), 2);
  assert.equal(nextIndex(3, 0, "ArrowRight", (i) => i === 1), 2);
  assert.equal(nextIndex(3, 0, "End", (i) => i === 2), 1);
  assert.equal(nextIndex(3, 0, "Enter"), null);
  assert.equal(nextIndex(0, 0, "ArrowRight"), null);
  assert.equal(cx("btn", false, null, "primary", undefined), "btn primary");
});

test("元件契約:按鈕預設 type=button、處理中不能按;圖示按鈕一定有名稱;分頁 / 單選列只停一次 Tab、有選中語意;狀態標籤不能按", () => {
  const button = read("../components/ui/Button.tsx");
  assert.match(button, /type = "button"/);
  assert.match(button, /disabled=\{disabled \|\| pending\}/);
  assert.doesNotMatch(button, /variant === "primary" && "(selected|active)"/);
  const icon = read("../components/ui/IconButton.tsx");
  assert.match(icon, /label: string;/, "label 必填");
  assert.match(icon, /aria-label=\{label\}/);
  const tabs = read("../components/ui/Tabs.tsx");
  assert.match(tabs, /role="tab"/);
  assert.match(tabs, /aria-selected=\{t\.key === value\}/);
  assert.match(tabs, /tabIndex=\{t\.key === value \|\| \(at < 0 && i === 0\) \? 0 : -1\}/);
  assert.match(tabs, /aria-controls=\{panels \? `\$\{id\}-panel-\$\{t\.key\}` : undefined\}/);
  const seg = read("../components/ui/SegmentedControl.tsx");
  assert.match(seg, /role="radiogroup"/);
  assert.match(seg, /aria-checked=\{o\.value === value\}/);
  const badge = read("../components/ui/StatusBadge.tsx");
  assert.doesNotMatch(badge, /onClick=|<button/);
  // 外觀只在共用那一段:元件不寫 inline 外觀
  for (const f of ["Button", "IconButton", "Tabs", "SegmentedControl", "StatusBadge", "ToolbarField"]) {
    assert.doesNotMatch(read(`../components/ui/${f}.tsx`), /style=\{\{/, f);
  }
});
