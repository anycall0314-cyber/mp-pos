// 合約到期日的試算(addMonths)。跑法:npm test。要跟後端 apps/core/dates.py 的 add_months 一樣。
import assert from "node:assert/strict";
import test from "node:test";

import { addMonths } from "./dates.ts";

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
