import type { AnalyticsResult, AnalyticsSpec } from "@/api/types";

/**
 * 自訂分析查完收成一行(全站檢視 V06c)。
 *
 * 那一行只用伺服器回來的這次查詢(`result.applied`、`result.columns`)寫,不另寫文案 —— 表格是哪一次查的,摘要就寫哪一次(紅隊)。
 * 要寫出:期間、跟哪一期比、哪幾家門市(沒篩 = 全部,列出店名,看得出含不含維修倉)、依什麼分、看哪幾個指標、其他每一個條件的內容。
 * 門市也只看伺服器回的條件:鎖在門市的帳號伺服器會把那一家寫進條件;不看這台電腦記的登入資料(複審 P0:中途解鎖時會寫錯範圍)。
 * **不准只寫「條件 N 個」**(老闆、店員都答不出是哪幾家)。
 */
export function recapParts(
  result: Pick<AnalyticsResult, "applied" | "columns">,
  allStores: string[],
): string[] {
  const { applied, columns } = result;
  const parts = [`${applied.period.from} ~ ${applied.period.to}`];
  parts.push(
    applied.compare_period
      ? `對比${applied.compare === "last_year" ? "去年同期" : "上一期"} ${applied.compare_period.from} ~ ${applied.compare_period.to}`
      : "不比較",
  );
  const stores = applied.filters.find((f) => f.dimension === "warehouse");
  if (stores) parts.push(`門市:${stores.values.map((v) => v.label).join("、")}`);
  else parts.push(allStores.length ? `全部門市(${allStores.join("、")})` : "全部門市");
  const dims = columns.dimensions.map((d) => (d.key === "date" && applied.grain ? `${d.label}(${grainLabel(applied.grain)})` : d.label));
  parts.push(dims.length ? `依${dims.join("、")}` : "不分組");
  parts.push(columns.measures.map((m) => m.label).join("、"));
  for (const f of applied.filters) {
    if (f.dimension === "warehouse") continue;
    parts.push(`${f.label}:${f.values.map((v) => v.label).join("、")}`);
  }
  return parts;
}

function grainLabel(grain: string): string {
  return ({ day: "按日", week: "按週", month: "按月", quarter: "按季", year: "按年" } as Record<string, string>)[grain] ?? grain;
}

/**
 * 兩份查詢單是不是同一個查詢:比內容,不比寫法(鍵的順序、沒選的條件、預設期間帶不帶日期都不算不同)。
 * 上面的條件改了、還沒按查詢 → 摘要那一行標「尚未重查」,下面的結果還是上一輪的(紅隊:結果先留著對著看,但要知道是舊的)。
 */
export function sameQuery(a: AnalyticsSpec | null, b: AnalyticsSpec | null): boolean {
  return queryKeyOf(a) === queryKeyOf(b);
}

function queryKeyOf(spec: AnalyticsSpec | null): string {
  if (!spec) return "";
  const p = spec.period;
  const period = p.preset && p.preset !== "custom" ? [p.preset] : [p.from ?? "", p.to ?? ""];
  const grain = spec.dimensions.includes("date") ? p.grain ?? "" : "";
  const filters = Object.entries(spec.filters ?? {})
    .filter(([, values]) => values.length > 0)
    .map(([key, values]) => [key, values.map((v) => JSON.stringify(v)).sort()] as const)
    .sort(([x], [y]) => (x < y ? -1 : x > y ? 1 : 0));
  return JSON.stringify([spec.measures, spec.dimensions, period, grain, filters, spec.compare || null, spec.sort || ""]);
}
