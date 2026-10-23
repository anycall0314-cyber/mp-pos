// 下拉的 Enter「完全相同才自動選」(全站檢視 A2)。跑法:npm test。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { sameCardNo, sameMember } from "./exactPick.ts";

const read = (p) => readFileSync(new URL(p, import.meta.url), "utf8");

test("卡號、會員:完全相同(去空白連字號、不分大小寫)才算", () => {
  assert.equal(sameCardNo({ label: "8988 6001-2345" }, "898860012345"), true);
  assert.equal(sameCardNo({ label: "898860012345" }, "89886001234"), false);   // 少一碼
  assert.equal(sameCardNo({ label: "898860012345" }, ""), false);
  const m = { label: "王小明", payload: { phone: "0912-345-678", tax_id: "", national_id: "A123456789", code: "M-00012", name: "王小明" } };
  assert.equal(sameMember(m, "0912345678"), true);
  assert.equal(sameMember(m, "a123456789"), true);
  assert.equal(sameMember(m, "王小明"), true);
  assert.equal(sameMember(m, "0912"), false);
  assert.equal(sameMember(m, "王小"), false);
});

test("下拉的 Enter:等現在打的字的結果回來才選;給了完全相同的比法、沒動過上下鍵就只選完全相同的", () => {
  const box = read("../components/ComboBox.tsx");
  assert.match(box, /if \(resultsFor\.current !== query\) \{\s*pendingEnter\.current = true;\s*void runSearch\(query\);\s*return;\s*\}/);
  assert.match(box, /resultsFor\.current = q;\s*setOptions\(results\);/);
  assert.match(box, /if \(exactOnEnter && !moved\.current\) \{/);
  // 等的時候按了 Esc / 點到外面 / 自己選了:晚到的結果不再替他選(複審 P1)
  assert.match(box, /pendingEnter\.current = false;\s*if \(!open\) return;\s*enterPick\(\);/);
  assert.match(box, /e\.key === "Escape"\) \{\s*pendingEnter\.current = false;/);
  assert.match(box, /function pickOption\(opt: ComboOption<T>\) \{\s*if \(opt\.disabled\) return;\s*pendingEnter\.current = false;/);
  const page = read("../pages/sales/SalesWorkbenchPage.tsx");
  assert.match(page, /exactOnEnter=\{sameMember\}/);
  assert.match(page, /exactOnEnter=\{sameCardNo\}/);
});

test("開單:免用不再切未稅;選好會員回刷碼框;找不到可以新增會員(帶電話);結帳成功收起來", () => {
  const page = read("../pages/sales/SalesWorkbenchPage.tsx");
  assert.ok(!page.includes('setTaxMethod("untaxed")'), "免用發票不再寫死切成未稅(owner 2026-10-23)");
  // 課稅別照那種發票設的帶(業務設定「帶入課稅別」;紅隊:不改「免用」的定義,每家自己設)
  assert.match(page, /const taxOf = taxMethodFor\(invoiceTypes, code\);\s*if \(taxOf\) setTaxMethod\(taxOf\);/);
  assert.match(page, /onChange=\{\(e\) => chooseInvoice\(e\.target\.value\)\}/);
  assert.match(page, /if \(nameLooksScanned\(name\)\) \{/);
  assert.match(page, /if \(opt\) window\.setTimeout\(backToScan, 0\);/);
  assert.match(page, /onCreateNew=\{newMemberFrom\}\s*createNewLabel="新增會員"/);
  assert.match(page, /setDone\(created\);\s*\/\/[^\n]*\n\s*\/\/[^\n]*\n\s*setPanel\(null\);/);
  assert.ok(!page.includes("繼續開單"), "結完帳不用再按繼續開單");
});
