// 會員頁舊 POS 紀錄照日期分段。跑法:npm test。
import assert from "node:assert/strict";
import test from "node:test";

import { byDate, docKind } from "./legacyHistory.ts";

test("同一天的單放同一段,順序照後端給的", () => {
  const docs = [
    { id: 3, document_date: "2026-10-11" },
    { id: 2, document_date: "2026-10-11" },
    { id: 1, document_date: "2025-01-02" },
  ];
  assert.deepEqual(byDate(docs).map((g) => [g.date, g.docs.map((d) => d.id)]), [
    ["2026-10-11", [3, 2]],
    ["2025-01-02", [1]],
  ]);
  assert.deepEqual(byDate([]), []);
});

test("單別代碼寫成銷貨 / 退貨,認不得的照原樣", () => {
  for (const c of ["E01", "E11", "E12", "E13"]) assert.equal(docKind(c), "銷貨");
  for (const c of ["F01", "F11", "F13", "FS11", " f11 "]) assert.equal(docKind(c), "退貨");
  assert.equal(docKind("X9"), "X9");
});
