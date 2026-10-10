// 固定的報表在畫面這一側:日期、網址、每一格怎麼顯示。跑法:npm test。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  FIXED_REPORTS, cellText, isNegative, localDay, monthStart, rangeQuery, rangeReady,
} from "./fixedReports.ts";

test("今天與月初用的是這台電腦的日期,不是世界時間", () => {
  // 台灣 2026-10-01 早上 07:30 = 世界時間 9/30 23:30:用 toISOString 會變成昨天、月初變成 9/1
  const early = new Date(2026, 9, 1, 7, 30);
  assert.equal(localDay(early), "2026-10-01");
  assert.equal(monthStart(early), "2026-10-01");
  assert.equal(localDay(new Date(2026, 0, 5, 23, 59)), "2026-01-05");
  assert.equal(monthStart(new Date(2026, 11, 31, 12, 0)), "2026-12-01");
});

test("查詢字串:空的不送", () => {
  assert.equal(rangeQuery({ from: "2026-09-01", to: "2026-09-30" }), "from=2026-09-01&to=2026-09-30");
  assert.equal(rangeQuery({ from: "2026-09-01", to: "2026-09-30", warehouse: "" }),
    "from=2026-09-01&to=2026-09-30");
  assert.equal(rangeQuery({ from: "2026-09-01", to: "2026-09-30", warehouse: 3, by: "category" }),
    "from=2026-09-01&to=2026-09-30&warehouse=3&by=category");
  assert.equal(rangeQuery({ from: "2026-09-01", to: "2026-09-30", by: "" }), "from=2026-09-01&to=2026-09-30");
});

test("日期兩個都有、開始不晚於結束才查", () => {
  assert.equal(rangeReady({ from: "2026-09-01", to: "2026-09-30" }), true);
  assert.equal(rangeReady({ from: "2026-09-30", to: "2026-09-30" }), true);
  assert.equal(rangeReady({ from: "2026-10-01", to: "2026-09-30" }), false);
  assert.equal(rangeReady({ from: "", to: "2026-09-30" }), false);
  assert.equal(rangeReady({ from: "2026-09-01", to: "" }), false);
  assert.equal(rangeReady({ from: "2026/09/01", to: "2026-09-30" }), false);
});

test("一格怎麼顯示:金額整數元、數量照原樣、沒有值是未設定(不是 0)", () => {
  assert.equal(cellText("25780.00"), "25,780");
  assert.equal(cellText("-5900.00"), "-5,900");
  assert.equal(cellText("0.00"), "0");
  assert.equal(cellText("952.50"), "953");
  assert.equal(cellText(4, "int"), "4");
  assert.equal(cellText(1234, "int"), "1234"); // 數量不加千分位(跟自訂分析同一個樣子)
  assert.equal(cellText(0, "int"), "0");
  assert.equal(cellText(null), "未設定");
  assert.equal(cellText(undefined, "int"), "未設定");
  assert.equal(cellText("0.2130", "pct"), "21.3%");
});

test("負的看得出來;0 與沒有值不算負的", () => {
  assert.equal(isNegative("-5900.00"), true);
  assert.equal(isNegative(-1), true);
  assert.equal(isNegative("0.00"), false);
  assert.equal(isNegative("6000.00"), false);
  assert.equal(isNegative(null), false);
  assert.equal(isNegative(""), false);
});

test("三張報表的名稱、網址、權限各是各的,而且導覽與路由用的是同一份", () => {
  assert.deepEqual(FIXED_REPORTS.map((r) => [r.key, r.path, r.title, r.ability]), [
    ["daily", "/reports/daily", "每日彙總", "report_daily"],
    ["staff", "/reports/staff", "業績彙總", "report_staff"],
    ["products", "/reports/products", "商品排行", "report_products"],
  ]);
  const nav = readFileSync(new URL("../nav.ts", import.meta.url), "utf8");
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  for (const r of FIXED_REPORTS) {
    assert.ok(nav.includes(`to: "${r.path}"`), `導覽沒有 ${r.path}`);
    assert.ok(nav.includes(`needs: ["${r.ability}"]`), `導覽的 ${r.title} 沒有掛權限`);
  }
  assert.ok(app.includes("FIXED_REPORTS.map"), "路由要照 FIXED_REPORTS 產生,不另外寫一份");
});
