// 合約到期日的試算(addMonths)。跑法:npm test。要跟後端 apps/core/dates.py 的 add_months 一樣。
import assert from "node:assert/strict";
import test from "node:test";

import { addMonths, shortDay } from "./dates.ts";

test("同一天、幾個月之後", () => {
  assert.equal(addMonths("2026-10-06", 24), "2028-10-06");
  assert.equal(addMonths("2026-10-06", 30), "2029-04-06");
  assert.equal(addMonths("2026-12-31", 1), "2027-01-31");
});

test("那個月沒有這一天就落在月底", () => {
  assert.equal(addMonths("2027-01-31", 1), "2027-02-28");
  assert.equal(addMonths("2026-08-31", 30), "2029-02-28");
  assert.equal(addMonths("2026-02-28", 24), "2028-02-28");
});

test("格式不對回空字串,不亂算", () => {
  assert.equal(addMonths("", 24), "");
  assert.equal(addMonths("2026/10/06", 24), "");
  assert.equal(addMonths("2026-10-06", 1.5), "");
});

test("報表列上的日期:期間在同一年只寫月日,跨年才寫完整的", () => {
  assert.equal(shortDay("2026-10-06", "2026-10-01", "2026-10-10"), "10-06");
  assert.equal(shortDay("2026-01-05", "2026-01-01", "2026-12-31"), "01-05");
  // 期間跨年:哪一年要看得出來
  assert.equal(shortDay("2025-12-31", "2025-12-01", "2026-01-31"), "2025-12-31");
  assert.equal(shortDay("2026-01-02", "2025-12-01", "2026-01-31"), "2026-01-02");
  // 這一天不在期間的那一年(不該發生;發生了寧可寫完整的)
  assert.equal(shortDay("2025-10-06", "2026-10-01", "2026-10-10"), "2025-10-06");
  // 格式不對就照原樣,不猜
  assert.equal(shortDay("", "2026-10-01", "2026-10-10"), "");
  assert.equal(shortDay("2026/10/06", "2026-10-01", "2026-10-10"), "2026/10/06");
  assert.equal(shortDay("2026-10-06", "", "2026-10-10"), "2026-10-06");
  assert.equal(shortDay("2026-10-06", "2026-10-01", ""), "2026-10-06");
});
