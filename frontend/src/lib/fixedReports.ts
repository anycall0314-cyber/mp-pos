// 固定的報表(業績彙總 / 商品排行 / 每日彙總 / 佣金明細)在畫面這一側的規則。
// 內容(哪幾欄、怎麼算、誰看得到哪一欄)全部由伺服器決定(backend/apps/analytics/presets.py、
// sales/commission_views.py);這裡只管日期、網址、每一格怎麼顯示。跑法:npm test。
import { money } from "./money.ts";

import type { AbilityKey } from "./abilities.ts";

export type FixedReportKey = "staff" | "products" | "daily" | "customers" | "activations";

export interface FixedReportPage {
  key: FixedReportKey;
  path: string;
  title: string;
  /** 員工帳號頁的哪一個勾;沒有 = 只有管理員看得到(沒有勾可以開) */
  ability?: AbilityKey;
}

/** 幾張彙總報表的頁面(路徑、名稱、要哪一項權限)。名稱跟導覽的分頁、員工帳號頁的項目是同一個字。 */
export const FIXED_REPORTS: FixedReportPage[] = [
  { key: "daily", path: "/reports/daily", title: "每日彙總", ability: "report_daily" },
  { key: "staff", path: "/reports/staff", title: "業績彙總", ability: "report_staff" },
  { key: "products", path: "/reports/products", title: "商品排行", ability: "report_products" },
  // 照客戶 / 照會員看誰買得最多(2026-10-12;取舊歐睿 SA040 毛利彙總表的優點)。
  // 只有管理員看得到(owner 同一天:「客戶排行不用給店員看」),所以沒有 ability
  { key: "customers", path: "/reports/customers", title: "來源排行" },
  // 各家電信、各種方案開了幾門(2026-10-12;取舊歐睿 SIM031 開通數量統計)。逐筆的是佣金明細
  { key: "activations", path: "/reports/activations", title: "開通統計", ability: "report_activations" },
];

const pad = (n: number) => String(n).padStart(2, "0");

/** 這台電腦的今天("YYYY-MM-DD")。不用 toISOString:那是世界時間,台灣早上八點以前會變成昨天。 */
export function localDay(now: Date = new Date()): string {
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

/** 這個月的 1 號。 */
export function monthStart(now: Date = new Date()): string {
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-01`;
}

/** 報表上面那一組快速鈕(全站檢視 E10:各頁一樣是今天、昨天、本月、上月) */
export type QuickRange = "today" | "yesterday" | "month" | "lastMonth";
export const QUICK_RANGES: { key: QuickRange; label: string }[] = [
  { key: "today", label: "今天" },
  { key: "yesterday", label: "昨天" },
  { key: "month", label: "本月" },
  { key: "lastMonth", label: "上月" },
];

/** 快速鈕的起訖日(照這台電腦的日期) */
export function quickRange(kind: QuickRange, now: Date = new Date()): { from: string; to: string } {
  const today = localDay(now);
  if (kind === "today") return { from: today, to: today };
  if (kind === "yesterday") {
    const y = localDay(new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1));
    return { from: y, to: y };
  }
  if (kind === "month") return { from: monthStart(now), to: today };
  const first = new Date(now.getFullYear(), now.getMonth() - 1, 1);
  const last = new Date(now.getFullYear(), now.getMonth(), 0);
  return { from: localDay(first), to: localDay(last) };
}

/** 往前 / 往後幾天(營業日報的前一天、後一天) */
export function shiftDay(day: string, days: number): string {
  const [y, m, d] = day.split("-").map(Number);
  return localDay(new Date(y, m - 1, d + days));
}

export interface ReportRange {
  from: string;
  to: string;
  /** 沒選 = 全公司(鎖在門市的帳號伺服器一律只算自己那一家,送什麼都一樣) */
  warehouse?: number | "";
  /** 商品排行:照商品 / 品類 / 品牌 */
  by?: string;
  /** 期間看哪一種日期(開通統計:開單日 / 上線日);沒有 = 伺服器的預設 */
  date?: string;
  /** 選到的門市叫什麼(匯出的檔名用;不送伺服器。沒選 = 空的) */
  warehouseName?: string;
}

/** 查詢字串:空的不送。 */
export function rangeQuery(range: ReportRange): string {
  const q = new URLSearchParams();
  q.set("from", range.from);
  q.set("to", range.to);
  if (range.warehouse !== undefined && range.warehouse !== "")
    q.set("warehouse", String(range.warehouse));
  if (range.by) q.set("by", range.by);
  if (range.date) q.set("date", range.date);
  return q.toString();
}

/**
 * 匯出的檔名用的報表名稱:期間看的不是預設那一種日期時把它寫進去(「開通統計-上線日」),
 * 不然兩種看法匯出來的檔名一模一樣、數字卻不同。
 */
export function exportTitle(
  title: string,
  result: { dates?: { key: string; label: string }[]; date?: string },
): string {
  const dates = result.dates ?? [];
  if (dates.length < 2 || !result.date || result.date === dates[0].key) return title;
  const picked = dates.find((d) => d.key === result.date);
  return picked ? `${title}-${picked.label}` : title;
}

/** 日期要兩個都有、而且開始不晚於結束才查(不然伺服器只會回一句格式不對)。 */
export function rangeReady(range: { from: string; to: string }): boolean {
  const ok = (s: string) => /^\d{4}-\d{2}-\d{2}$/.test(s);
  return ok(range.from) && ok(range.to) && range.from <= range.to;
}

/**
 * 結果上面那一行:這一份是哪段期間、哪一家門市、(開通統計)看哪一種日期 —— 照伺服器回的那一份寫,
 * 不照框裡寫的(框裡改了還沒查的時候,兩個會不一樣;全站檢視 R05)。
 */
export function resultScope(result: {
  applied: { period: { from: string; to: string }; filters: { dimension: string; values: { label: string }[] }[] };
  dates?: { key: string; label: string }[];
  date?: string;
}): string {
  const stores = result.applied.filters.find((f) => f.dimension === "warehouse")?.values.map((v) => v.label) ?? [];
  const parts = [`${result.applied.period.from} ~ ${result.applied.period.to}`, stores.length ? stores.join("、") : "全部門市"];
  if (result.dates && result.dates.length > 1) {
    const basis = result.dates.find((d) => d.key === result.date) ?? result.dates[0];
    parts.push(basis.label);
  }
  return parts.join(" · ");
}

/** 報表上面那一排框裡現在寫的(還沒按查詢的也算) */
export interface RangeDraft {
  from: string;
  to: string;
  warehouse: number | "";
  warehouseName: string;
}

/** 框裡的起訖日、門市跟畫面上那一份結果用的不一樣 = 改了還沒查(旁邊寫「還沒查詢」;全站檢視 R05) */
export function draftPending(draft: RangeDraft, applied: ReportRange): boolean {
  return draft.from !== applied.from || draft.to !== applied.to || draft.warehouse !== (applied.warehouse ?? "");
}

/**
 * 分組、日期基準一選就查:連框裡改了還沒查的起訖日、門市一起查,結果跟框裡寫的永遠是同一份(全站檢視 R05:
 * 以前只換分組、照舊的日期查,框裡寫 9/1 結果卻是 10/1)。框裡的起訖日不合法就只換那一個下拉,框裡的留著、旁邊照樣寫「還沒查詢」。
 */
export function switchApplied(applied: ReportRange, draft: RangeDraft, change: { by?: string; date?: string }): ReportRange {
  if (!rangeReady(draft)) return { ...applied, ...change };
  return { ...applied, from: draft.from, to: draft.to, warehouse: draft.warehouse, warehouseName: draft.warehouseName, ...change };
}

/**
 * 一格怎麼顯示:金額整數元(全站同一條規則)、數量照原樣、沒有值(方案當時沒設定公司佣金)寫「未設定」
 * —— 不能寫成 0:0 是「設定了 0 元」,兩個意思不一樣。
 */
export function cellText(value: unknown, format: "money" | "int" | "pct" = "money"): string {
  if (value === null || value === undefined || value === "") return "未設定";
  if (format === "int") return String(value);
  if (format === "pct") return `${(Number(value) * 100).toFixed(1)}%`;
  return money(value);
}

/** 負的數字(銷退扣回去的那幾格)要看得出來。 */
export function isNegative(value: unknown): boolean {
  return value !== null && value !== undefined && value !== "" && Number(value) < 0;
}
