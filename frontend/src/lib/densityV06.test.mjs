// 庫存、盤點、報表、匯入的資訊密度(全站檢視 V06,各頁分開做)。跑法:npm test。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (p) => readFileSync(new URL(p, import.meta.url), "utf8");
const css = read("../styles.css");

test("V06a 庫存查詢:表頭黏在上面、本頁合計黏在下面(寫明本頁);overflow 用 clip(hidden 會讓黏住失效)", () => {
  const page = read("../pages/inventory/InventoryQueryPage.tsx");
  assert.match(page, /<table className="wb-table inv-sticky">/);
  assert.match(page, /本頁合計/);
  assert.match(css, /\.wb-table\.inv-sticky \{ overflow: clip; \}/);
  assert.match(css, /\.wb-table\.inv-sticky thead th \{ position: sticky; top: -14px;/);
  assert.match(css, /\.wb-table\.inv-sticky tr\.total > td \{ position: sticky; bottom: -28px;/);
});

test("V06b 盤點手機配對:沒配上 QR 照開,掃了才收成「已配對 N 台」;N 只算現在連著的;電腦抓不到新資料寫「連線中斷」", () => {
  const page = read("../pages/inventory/StockCountPage.tsx");
  const lib = read("./stockCount.ts");
  assert.match(lib, /if \(stale\) return "連線中斷";/);
  assert.match(lib, /filter\(\(p\) => p\.status === "connected"\)\.length;\n  return n > 0 \? `已配對 \$\{n\} 台` : "";/);
  assert.match(lib, /p\.status === "waiting" \|\| p\.status === "connected" \|\| p\.status === "lost"/, "斷線的還要一直抓,回來才看得到");
  assert.match(lib, /lost: "斷線"/);
  // 剛發的 QR Code 被掃了才收起來(不是一開就收);收起來時按鈕還是「手機盤點」(手機上的訊息叫人按這個)
  assert.match(page, /if \(pairStatus !== "connected"\) return;\n    setPhoneOpen\(false\);\n    setPair\(null\);/);
  assert.match(page, /const stale = live && clock - dataUpdatedAt > PHONE_STALE_MS;/);
  assert.match(page, /\{paired && <span className=\{stale \? "sc-paired stale" : "sc-paired"\}>\{paired\}<\/span>\}\n\s+<button className="btn sc-phone-btn" type="button" aria-expanded=\{phoneOpen\} onClick=\{\(\) => setPhoneOpen\(\(v\) => !v\)\}>\n\s+手機盤點\n/);
  // 重抓失敗不能整頁換成錯誤(畫面上的東西會不見),只有一開始就抓不到才整頁錯誤
  assert.match(page, /  if \(!detail\) return <div className="page"><Banner kind="error"/);
  assert.doesNotMatch(page, /isError \|\| !detail/);
  // 送出還在配件那一排最右邊(紅隊:不換位置)
  assert.match(page, /<span className="sc-submit">[\s\S]{0,200}<ArmButton label="送出"/);
});

test("V06c 自訂分析摘要:寫出期間、比較、門市、分組、指標、每一個條件;不准只寫條件個數", async () => {
  const { recapParts } = await import("./exploreRecap.ts");
  const result = {
    applied: {
      period: { from: "2026-10-01", to: "2026-10-31" }, grain: "month", compare: "last_year",
      compare_period: { from: "2025-10-01", to: "2025-10-31" },
      filters: [
        { dimension: "warehouse", label: "門市", values: [{ value: 1, label: "巨城店" }, { value: 2, label: "湳雅店" }] },
        { dimension: "category", label: "類別", values: [{ value: 3, label: "手機" }, { value: 4, label: "配件" }] },
      ],
    },
    columns: {
      dimensions: [{ key: "warehouse", label: "門市" }, { key: "brand", label: "品牌" }, { key: "date", label: "日期" }],
      measures: [{ key: "net_sales", label: "淨銷售額", format: "money" }, { key: "gross_profit", label: "毛利", format: "money" }],
    },
  };
  const all = ["巨城店", "湳雅店", "維修倉"];
  assert.deepEqual(recapParts(result, all), [
    "2026-10-01 ~ 2026-10-31", "對比去年同期 2025-10-01 ~ 2025-10-31", "門市:巨城店、湳雅店",
    "依門市、品牌、日期(按月)", "淨銷售額、毛利", "類別:手機、配件",
  ]);
  const plain = { ...result, applied: { ...result.applied, compare: null, compare_period: undefined, filters: [] }, columns: { ...result.columns, dimensions: [] } };
  assert.deepEqual(recapParts(plain, all), ["2026-10-01 ~ 2026-10-31", "不比較", "全部門市(巨城店、湳雅店、維修倉)", "不分組", "淨銷售額、毛利"],
    "沒篩門市要列出全部的店名,看得出含不含維修倉");
  // 鎖在門市的帳號:伺服器把那一家寫進條件,摘要照它寫(不看這台電腦記的登入資料;複審 P0)
  const locked = { ...result, applied: { ...result.applied, filters: [{ dimension: "warehouse", label: "門市", values: [{ value: 2, label: "湳雅店" }] }] } };
  assert.equal(recapParts(locked, all)[2], "門市:湳雅店");
  assert.ok(!recapParts(result, all).some((p) => /條件 ?\d+ ?個/.test(p)));
});

test("V06c 改了沒重查:比內容不比寫法;頁面查完才收、匯出在摘要那一排、指標卡壓扁", async () => {
  const { sameQuery } = await import("./exploreRecap.ts");
  const base = { measures: ["net_sales"], dimensions: ["warehouse"], period: { preset: "this_month", grain: "month" }, filters: { warehouse: [1, 2] }, compare: null, sort: "" };
  assert.ok(sameQuery(base, { ...base, period: { grain: "month", preset: "this_month", from: "2026-10-01" }, filters: { warehouse: [2, 1], brand: [] } }));
  assert.ok(sameQuery(base, { ...base, period: { preset: "this_month", grain: "day" } }), "沒有依日期分時,日期單位不算");
  assert.ok(!sameQuery(base, { ...base, filters: { warehouse: [1] } }));
  assert.ok(!sameQuery(base, { ...base, compare: "previous" }));
  assert.ok(!sameQuery(base, { ...base, period: { preset: "custom", from: "2026-10-01", to: "2026-10-31", grain: "month" } }));
  assert.ok(!sameQuery(base, null));
  const page = read("../pages/reports/ExploreReportPage.tsx");
  assert.match(page, /if \(!collapseNext\.current \|\| query\.isFetching\) return;\n    collapseNext\.current = false;\n    if \(query\.isSuccess\) setBuilderOpen\(false\);/, "結果回來才收、查失敗不收");
  assert.match(page, /\{builderOpen && \(\n\s+<div className="ex-builder">/);
  assert.match(page, /\{!sameQuery\(buildSpec\(\), applied\) && <span className="ex-recap-stale">尚未重查<\/span>\}/);
  assert.match(page, /<span className="ex-recap-actions">[\s\S]{0,300}\{builderOpen \? "收起" : "修改"\}[\s\S]{0,200}onClick=\{exportCsv\}>\n\s+匯出/);
  assert.equal((page.match(/onClick=\{exportCsv\}/g) ?? []).length, 1, "匯出只在摘要那一排");
  assert.match(css, /\.ex-summary \.sd-summary-card \{ display: flex; align-items: baseline;/);
});
