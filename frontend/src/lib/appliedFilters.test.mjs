// 清單上面那一排「已套用的條件」。跑法:npm test。
import assert from "node:assert/strict";
import test from "node:test";

import { appliedList, cond, dayText, rangeCond, rangeText } from "./appliedFilters.ts";

const now = new Date(2026, 9, 23);

test("只列有值的條件", () => {
  assert.deepEqual(appliedList([cond("門市", "民生店"), cond("廠商", ""), null, false, cond("商品", "  ")]), [
    { label: "門市", value: "民生店" },
  ]);
});

test("日期:今年寫月-日、別年寫全", () => {
  assert.equal(dayText("2026-10-01", now), "10-01");
  assert.equal(dayText("2025-12-31", now), "2025-12-31");
});

test("起迄的寫法", () => {
  assert.equal(rangeText("", "", now), "");
  assert.equal(rangeText("2026-10-01", "2026-10-23", now), "10-01 ~ 10-23");
  assert.equal(rangeText("2026-10-05", "2026-10-05", now), "10-05");
  assert.equal(rangeText("2026-10-01", "", now), "10-01 起");
  assert.equal(rangeText("", "2026-10-23", now), "到 10-23");
});

test("起迄跟預設一樣不算", () => {
  const month = { from: "2026-10-01", to: "2026-10-23" };
  assert.equal(rangeCond("期間", "2026-10-01", "2026-10-23", month, now), null);
  assert.deepEqual(rangeCond("期間", "2026-09-01", "2026-09-30", month, now), { label: "期間", value: "09-01 ~ 09-30" });
  assert.equal(rangeCond("進貨", "", "", undefined, now), null);
  assert.deepEqual(rangeCond("期間", "", "", month, now), { label: "期間", value: "全部" });   // 預設有期間、清成全部
});
