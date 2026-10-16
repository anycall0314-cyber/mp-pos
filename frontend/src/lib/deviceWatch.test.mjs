import assert from "node:assert/strict";
import { test } from "node:test";

import { listText, runLine } from "./deviceWatch.ts";

test("一次檢查寫成一行,沒成功寫沒有成功", () => {
  const ok = { day: "2026-10-16", finished_at: "2026-10-16T05:31:00+08:00", ok: true, notes: [],
    counts: { list_cellphone: 277, list_tablet: 102, list_wearable: 193, added: 1, review: 2 } };
  const line = runLine(ok);
  assert.match(line, /成功 · 清單 572 支 · 加入 1 · 補上 0 · 待確認 2 · 等資料 0$/);
  assert.match(runLine({ ...ok, ok: false, counts: {} }), /沒有成功 · 加入 0/);
  assert.equal(runLine(null), "還沒有檢查過");
  assert.match(runLine({ ...ok, finished_at: null }), /^10\/16 檢查中/);
});

test("清單寫成一格", () => {
  assert.equal(listText(["256GB", "512GB"]), "256GB、512GB");
  assert.equal(listText([]), "—");
});
