// 固定的報表在畫面這一側:日期、網址、每一格怎麼顯示。跑法:npm test。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  FIXED_REPORTS, cellText, draftPending, exportTitle, isNegative, localDay, monthStart, quickRange, rangeQuery, rangeReady,
  resultScope, shiftDay, switchApplied,
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

test("幾張彙總報表的名稱、網址、權限各是各的,而且導覽與路由用的是同一份", () => {
  assert.deepEqual(FIXED_REPORTS.map((r) => [r.key, r.path, r.title, r.ability]), [
    ["daily", "/reports/daily", "每日彙總", "report_daily"],
    ["staff", "/reports/staff", "業績彙總", "report_staff"],
    ["products", "/reports/products", "商品排行", "report_products"],
    ["customers", "/reports/customers", "來源排行", undefined],               // 只有管理員看得到:沒有勾
    ["activations", "/reports/activations", "開通統計", "report_activations"],  // 2026-10-12:各家電信開了幾門
  ]);
  assert.deepEqual([...new Set(FIXED_REPORTS.map((r) => r.title.length))], [4]);
  const nav = readFileSync(new URL("../nav.ts", import.meta.url), "utf8");
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  for (const r of FIXED_REPORTS) {
    const at = nav.indexOf(`to: "${r.path}"`);
    assert.ok(at >= 0, `導覽沒有 ${r.path}`);
    const entry = nav.slice(at, nav.indexOf("},", at));           // 這一頁在導覽裡的那一段
    // 有勾的掛那個勾;沒有勾的(只有管理員看得到)掛 managersOnly —— 兩種一定有一種,不能什麼都沒掛
    if (r.ability) assert.ok(entry.includes(`needs: ["${r.ability}"]`), `導覽的 ${r.title} 沒有掛權限`);
    else assert.ok(entry.includes("managersOnly: true") && !entry.includes("needs:"), `導覽的 ${r.title} 要只給管理員`);
  }
  assert.deepEqual(FIXED_REPORTS.filter((r) => !r.ability).map((r) => r.key), ["customers"]);
  // 路由:沒有勾的那一張用「只有管理員」的守門,不是什麼都不擋
  assert.match(app, /r\.ability \? \(\s*<NeedsAbility ability=\{r\.ability\}[\s\S]*?\) : \(\s*<ManagersOnly doing=/);
  assert.ok(app.includes("FIXED_REPORTS.map"), "路由要照 FIXED_REPORTS 產生,不另外寫一份");
  // 以前的空殼「開通查詢」那個網址(有人存了書籤)要帶到開通統計,不是停在「尚未實作」
  assert.match(app, /path="\/telecom\/activations"\s+element=\{<Navigate to="\/reports\/activations" replace \/>\}/);
  assert.ok(!app.includes('<Placeholder title="開通查詢" />'));
});

test("期間旁邊那幾個字(扣了什麼)是伺服器給的,頁面不自己寫死", () => {
  // 開通統計的新辦 / 續約 / 攜碼三欄是成交的數、沒有扣銷退:頁面寫死「已扣銷退」就講錯了
  const page = readFileSync(new URL("../pages/reports/FixedReportPage.tsx", import.meta.url), "utf8");
  assert.ok(!page.includes("已扣銷退"));
  assert.ok(page.includes("data.note"));
});

test("期間可以改看別的日期(開通統計:上線日):選了才送;下拉的字是伺服器給的;匯出的檔名看得出是哪一種", () => {
  // owner 2026-10-12:開通統計要能照上線日看
  assert.equal(rangeQuery({ from: "2026-10-01", to: "2026-10-12" }), "from=2026-10-01&to=2026-10-12");
  assert.equal(rangeQuery({ from: "2026-10-01", to: "2026-10-12", date: "" }), "from=2026-10-01&to=2026-10-12");
  assert.equal(
    rangeQuery({ from: "2026-10-01", to: "2026-10-12", warehouse: 8, by: "plan", date: "start" }),
    "from=2026-10-01&to=2026-10-12&warehouse=8&by=plan&date=start",
  );
  const dates = [{ key: "doc", label: "開單日" }, { key: "start", label: "上線日" }];
  assert.equal(exportTitle("開通統計", { dates, date: "start" }), "開通統計-上線日");
  assert.equal(exportTitle("開通統計", { dates, date: "doc" }), "開通統計");          // 預設那一種不加字(檔名跟以前一樣)
  assert.equal(exportTitle("開通統計", { dates, date: "" }), "開通統計");
  assert.equal(exportTitle("開通統計", { dates }), "開通統計");
  assert.equal(exportTitle("開通統計", { dates, date: "gone" }), "開通統計");
  assert.equal(exportTitle("業績彙總", { dates: [], date: "doc" }), "業績彙總");        // 只有一種看法的報表
  assert.equal(exportTitle("業績彙總", {}), "業績彙總");
  assert.deepEqual([...new Set(dates.map((d) => d.label.length))], [3]);

  const page = readFileSync(new URL("../pages/reports/FixedReportPage.tsx", import.meta.url), "utf8");
  assert.ok(page.includes("dates={data?.dates}"), "日期的選項要照伺服器給的畫");
  assert.ok(page.includes("data.pending ? `　${data.pending}` : \"\""), "還沒填上線日的那一句是伺服器寫的");
  assert.match(page, /const title = exportTitle\(report\.title, all\);[\s\S]*?exportFileName\(title, \{/, "匯出的檔名要看得出是哪一種日期");
  const bar = readFileSync(new URL("../pages/reports/ReportRangeBar.tsx", import.meta.url), "utf8");
  assert.match(bar, /dates && dates\.length > 1 && \(/);                              // 只有一種就不出下拉
  assert.match(bar, /value=\{applied\.date \|\| dates\[0\]\.key\}/);
  // 選了就查;框裡改了還沒查的起訖日、門市一起查(全站檢視 R05)
  assert.match(bar, /onApply\(switchApplied\(applied, draft, \{ date: e\.target\.value \}\)\)/);
  for (const text of [page, bar]) {
    const code = text.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/[^\n]*/g, "");
    for (const word of ["開單日", "上線日"]) assert.ok(!code.includes(word), `畫面寫死了「${word}」`);
  }
  const hooks = readFileSync(new URL("../api/hooks.ts", import.meta.url), "utf8");
  assert.ok(hooks.includes("`/analytics/presets/${key}/?${rangeQuery(range)}&export=1`"));     // 匯出跟畫面用同一份條件(含日期)
});

test("快速鈕:今天、昨天、本月、上月(跨月、跨年、閏年)", () => {
  const at = new Date(2026, 2, 1, 7, 30);           // 2026-03-01 早上 7:30(台灣早上 8 點前也算當天)
  assert.deepEqual(quickRange("today", at), { from: "2026-03-01", to: "2026-03-01" });
  assert.deepEqual(quickRange("yesterday", at), { from: "2026-02-28", to: "2026-02-28" });
  assert.deepEqual(quickRange("month", at), { from: "2026-03-01", to: "2026-03-01" });
  assert.deepEqual(quickRange("lastMonth", at), { from: "2026-02-01", to: "2026-02-28" });
  assert.deepEqual(quickRange("lastMonth", new Date(2024, 2, 15)), { from: "2024-02-01", to: "2024-02-29" });
  assert.deepEqual(quickRange("lastMonth", new Date(2026, 0, 10)), { from: "2025-12-01", to: "2025-12-31" });
  assert.deepEqual(quickRange("yesterday", new Date(2026, 0, 1)), { from: "2025-12-31", to: "2025-12-31" });
});

test("前一天、後一天", () => {
  assert.equal(shiftDay("2026-03-01", -1), "2026-02-28");
  assert.equal(shiftDay("2025-12-31", 1), "2026-01-01");
});


// 全站檢視 R05:框裡改了還沒查、切分組 / 日期基準,結果與框裡寫的要對得上
const APPLIED = { from: "2026-10-01", to: "2026-10-24", warehouse: "", warehouseName: "", by: "product" };
const draftOf = (over = {}) => ({ from: "2026-10-01", to: "2026-10-24", warehouse: "", warehouseName: "", ...over });

test("框裡的起訖日、門市跟結果不一樣才算還沒查;分組不算(一選就查)", () => {
  assert.equal(draftPending(draftOf(), APPLIED), false);
  assert.equal(draftPending(draftOf({ from: "2026-09-01" }), APPLIED), true);
  assert.equal(draftPending(draftOf({ to: "2026-10-23" }), APPLIED), true);
  assert.equal(draftPending(draftOf({ warehouse: 2, warehouseName: "民生店" }), APPLIED), true);
  assert.equal(draftPending(draftOf(), { from: "2026-10-01", to: "2026-10-24" }), false); // 沒有門市 = 全部
});

test("切分組 / 日期基準:連框裡改了還沒查的起訖日、門市一起查;起訖日不合法就只換那一個", () => {
  const changed = switchApplied(APPLIED, draftOf({ from: "2026-09-01", warehouse: 1, warehouseName: "湳雅店" }), { by: "brand" });
  assert.deepEqual(changed, { from: "2026-09-01", to: "2026-10-24", warehouse: 1, warehouseName: "湳雅店", by: "brand" });
  assert.equal(draftPending(draftOf({ from: "2026-09-01", warehouse: 1, warehouseName: "湳雅店" }), changed), false);
  const basis = switchApplied(APPLIED, draftOf({ to: "2026-10-20" }), { date: "start" });
  assert.equal(basis.to, "2026-10-20");
  assert.equal(basis.date, "start");
  assert.equal(basis.by, "product");
  // 起日晚於迄日:只換分組,期間照舊(框裡的留著,旁邊照樣寫還沒查詢)
  const bad = switchApplied(APPLIED, draftOf({ from: "2026-11-01" }), { by: "category" });
  assert.deepEqual(bad, { ...APPLIED, by: "category" });
  assert.equal(draftPending(draftOf({ from: "2026-11-01" }), bad), true);
});

test("結果上面那一行照伺服器回的寫:期間、門市(沒選 = 全部門市)、有兩種日期才寫看哪一種", () => {
  const period = { from: "2026-09-01", to: "2026-09-30" };
  assert.equal(resultScope({ applied: { period, filters: [] } }), "2026-09-01 ~ 2026-09-30 · 全部門市");
  assert.equal(
    resultScope({ applied: { period, filters: [{ dimension: "warehouse", values: [{ label: "湳雅店" }] }] } }),
    "2026-09-01 ~ 2026-09-30 · 湳雅店",
  );
  const dates = [{ key: "doc", label: "開單日" }, { key: "start", label: "上線日" }];
  assert.equal(resultScope({ applied: { period, filters: [] }, dates, date: "start" }), "2026-09-01 ~ 2026-09-30 · 全部門市 · 上線日");
  assert.equal(resultScope({ applied: { period, filters: [] }, dates }), "2026-09-01 ~ 2026-09-30 · 全部門市 · 開單日");
});

test("報表那一排:兩個下拉都走 switchApplied、改了沒查寫「還沒查詢」;固定報表結果那一行用 resultScope", () => {
  const bar = readFileSync(new URL("../pages/reports/ReportRangeBar.tsx", import.meta.url), "utf8");
  assert.match(bar, /onApply\(switchApplied\(applied, draft, \{ date: e\.target\.value \}\)\)/);
  assert.match(bar, /onApply\(switchApplied\(applied, draft, \{ by: e\.target\.value \}\)\)/);
  assert.doesNotMatch(bar, /onApply\(\{ \.\.\.applied, (by|date):/);
  assert.match(bar, /\{pending && <span className="range-pending">還沒查詢<\/span>\}/);
  const page = readFileSync(new URL("../pages/reports/FixedReportPage.tsx", import.meta.url), "utf8");
  assert.match(page, /\{resultScope\(data\)\}/);
  // 匯出照畫面那一份(已套用的),不是框裡還沒查的
  assert.match(page, /fetchFixedReportAll\(report\.key, applied\)/);
});
