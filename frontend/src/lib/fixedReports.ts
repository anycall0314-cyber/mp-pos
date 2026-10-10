// 固定的報表(業績彙總 / 商品排行 / 每日彙總 / 佣金明細)在畫面這一側的規則。
// 內容(哪幾欄、怎麼算、誰看得到哪一欄)全部由伺服器決定(backend/apps/analytics/presets.py、
// sales/commission_views.py);這裡只管日期、網址、每一格怎麼顯示。跑法:npm test。
import { money } from "./money.ts";

import type { AbilityKey } from "./abilities.ts";

export type FixedReportKey = "staff" | "products" | "daily";

export interface FixedReportPage {
  key: FixedReportKey;
  path: string;
  title: string;
  ability: AbilityKey;
}

/** 三張彙總報表的頁面(路徑、名稱、要哪一項權限)。名稱跟導覽的分頁、員工帳號頁的項目是同一個字。 */
export const FIXED_REPORTS: FixedReportPage[] = [
  { key: "daily", path: "/reports/daily", title: "每日彙總", ability: "report_daily" },
  { key: "staff", path: "/reports/staff", title: "業績彙總", ability: "report_staff" },
  { key: "products", path: "/reports/products", title: "商品排行", ability: "report_products" },
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

export interface ReportRange {
  from: string;
  to: string;
  /** 沒選 = 全公司(鎖在門市的帳號伺服器一律只算自己那一家,送什麼都一樣) */
  warehouse?: number | "";
  /** 商品排行:照商品 / 品類 / 品牌 */
  by?: string;
}

/** 查詢字串:空的不送。 */
export function rangeQuery(range: ReportRange): string {
  const q = new URLSearchParams();
  q.set("from", range.from);
  q.set("to", range.to);
  if (range.warehouse !== undefined && range.warehouse !== "")
    q.set("warehouse", String(range.warehouse));
  if (range.by) q.set("by", range.by);
  return q.toString();
}

/** 日期要兩個都有、而且開始不晚於結束才查(不然伺服器只會回一句格式不對)。 */
export function rangeReady(range: { from: string; to: string }): boolean {
  const ok = (s: string) => /^\d{4}-\d{2}-\d{2}$/.test(s);
  return ok(range.from) && ok(range.to) && range.from <= range.to;
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
