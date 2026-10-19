// 會員頁舊 POS 紀錄照日期分段。跑法:npm test。
import assert from "node:assert/strict";
import test from "node:test";

import { byDate } from "./legacyHistory.ts";

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
