// 進貨單底下「還缺什麼」那一句點了捲到那一行(全站檢視 C5)。跑法:npm test。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const page = readFileSync(new URL("../pages/purchases/PurchaseWorkbenchPage.tsx", import.meta.url), "utf8");

test("點了要用 setCurrent:掃碼要刷進的那一行也跟著換(複審 P0:只改畫面上的那一行,刷碼掛到別行)", () => {
  const i = page.indexOf('className="ws-issue ws-issue-link"');
  assert.ok(i > 0);
  const handler = page.slice(i, i + 600);
  assert.match(handler, /setCurrent\(issueKey\);/);
  assert.doesNotMatch(handler, /setCurrentKey\(issueKey\)/);
});

test("validate() 記下有問題的是哪一行;單據層的問題(廠商、門市)沒有那一行", () => {
  assert.match(page, /function validate\(\): string \| null \{\n\s*\/\/[^\n]*\n\s*issueKeyRef\.current = null;/);
  assert.match(page, /for \(const l of ls\) \{\n\s*issueKeyRef\.current = l\.key;/);
});
