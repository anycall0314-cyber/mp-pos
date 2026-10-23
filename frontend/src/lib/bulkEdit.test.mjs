// 批次修改的屬性每個各自「不改 / 是 / 否」(全站檢視 D9)。跑法:npm test。
import assert from "node:assert/strict";
import test from "node:test";

import { attrPatch, attrSummary, attrsFromDraft, keepAll } from "./bulkEdit.ts";

test("預設全部不改,什麼都不送", () => {
  assert.deepEqual(attrPatch(keepAll()), {});
});

test("只送有選的那幾個:打開可綁門號,不會順便關掉需追蹤序號", () => {
  const attrs = { ...keepAll(), allows_telecom_line: "yes", counts_cash: "no" };
  assert.deepEqual(attrPatch(attrs), { allows_telecom_line: true, counts_cash: false });
  assert.equal("requires_serial" in attrPatch(attrs), false);
});

test("以前的草稿(五個勾)載回來一律不改;這一版存的照原樣", () => {
  assert.deepEqual(attrsFromDraft({ requires_serial: false, allows_telecom_line: true }), keepAll());
  assert.deepEqual(attrsFromDraft(undefined), keepAll());
  assert.deepEqual(attrsFromDraft({ requires_serial: "no", counts_margin: "yes" }), {
    ...keepAll(), requires_serial: "no", counts_margin: "yes",
  });
});

test("確認的那一句用畫面上的名字", () => {
  assert.deepEqual(attrSummary({ ...keepAll(), requires_serial: "no" }), ["需追蹤序號:否"]);
});
