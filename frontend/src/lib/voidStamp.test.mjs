// 作廢的那一刻與誰按的怎麼寫成一行。跑法:npm test。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { voidStamp } from "./voidStamp.ts";

// 用這台電腦的時區組一個時間,測試在哪個時區跑都一樣
const local = (y, m, d, hh, mm) => new Date(y, m - 1, d, hh, mm).toISOString();

test("作廢的時間與帳號寫成一行;時間是這台電腦的", () => {
  assert.equal(voidStamp({ voided_at: local(2026, 10, 12, 14, 3), voided_by_name: "a-boss" }), "2026-10-12 14:03 a-boss");
  assert.equal(voidStamp({ voided_at: local(2026, 1, 5, 0, 30), voided_by_name: "clerk" }), "2026-01-05 00:30 clerk");
  // 跨年的看得出是哪一年
  assert.equal(voidStamp({ voided_at: local(2025, 12, 31, 23, 59), voided_by_name: "x" }), "2025-12-31 23:59 x");
});

test("沒有記到的不亂寫:沒有時間 = 空的;沒有帳號只寫時間", () => {
  assert.equal(voidStamp({ voided_at: null, voided_by_name: "a-boss" }), "");
  assert.equal(voidStamp({}), "");
  assert.equal(voidStamp({ voided_at: "", voided_by_name: "" }), "");
  assert.equal(voidStamp({ voided_at: "亂寫", voided_by_name: "x" }), "");
  assert.equal(voidStamp({ voided_at: local(2026, 10, 12, 9, 5), voided_by_name: "" }), "2026-10-12 09:05");
  assert.equal(voidStamp({ voided_at: local(2026, 10, 12, 9, 5), voided_by_name: null }), "2026-10-12 09:05");
});

test("銷貨單清單:作廢的單三個地方(單張、卡片、表格)都寫作廢的時間與帳號", () => {
  const page = readFileSync(new URL("../pages/sales/SalesListPage.tsx", import.meta.url), "utf8");
  assert.equal(page.split("{voidStamp(t)}<").length - 1, 3);
  // 只有作廢的單才寫(跟「已作廢」那個標記同一個條件)
  assert.equal(page.split("t.is_void && voidStamp(t)").length - 1, 3);
  const types = readFileSync(new URL("../api/types.ts", import.meta.url), "utf8");
  assert.match(types, /is_void: boolean;\s*\/\*\*[^\n]*\*\/\s*voided_at: string \| null;\s*voided_by_name: string;/);
});
