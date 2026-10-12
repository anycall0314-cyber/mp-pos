// 各張報表「匯出」的內容(2026-10-12 取舊歐睿報表優點的第 3 批:舊系統每一張都能轉 Excel)。跑法:npm test。
// 原則:檔的內容 = 這個帳號在畫面上本來就看得到的(欄位、門市範圍都由伺服器決定,這裡只是把收到的資料排成表);
// 畫面有合計的,檔的最後一列是「合計」;沒有值留空白(不寫成 0);金額是整數、不加千分位。
import { intStr } from "./money.ts";

type Format = "money" | "int" | "pct";

/** 檔裡的一格數字:金額收成整數;數量照原樣;比率寫成百分比(不然 0.2238 貼進試算表會被看成 0.22%);沒有值留空白。 */
export function exportNumber(value: unknown, format: Format = "money"): string | number {
  if (value === null || value === undefined || value === "") return "";
  if (format === "pct") return `${(Number(value) * 100).toFixed(1)}%`;
  if (format === "int") return Number(value);
  return intStr(value);
}

// ── 業績彙總 / 商品排行 / 每日彙總(欄位由伺服器給;只給管理員的欄,店員的資料裡本來就沒有)──

export interface FixedLike {
  columns: {
    dimensions: { label: string }[];
    measures: { key: string; label: string; format?: Format }[];
  };
  rows: { dims: { label: string }[]; values: Record<string, unknown> }[];
  totals: Record<string, unknown>;
}

/**
 * 最後一列是合計(伺服器算的、全部的)。所以**交進來的一定要是完整的列** —— 商品排行畫面只列前 200 名,
 * 匯出時頁面另外跟伺服器要全部的(`?export=1`),不能拿畫面上那一份(複審首輪:201 個商品時檔只有 200 列、合計卻是 201 個的)。
 */
export function fixedReportTable(result: FixedLike): unknown[][] {
  const { dimensions, measures } = result.columns;
  const numbers = (values: Record<string, unknown>) => measures.map((m) => exportNumber(values[m.key], m.format));
  return [
    [...dimensions.map((d) => d.label), ...measures.map((m) => m.label)],
    ...result.rows.map((r) => [...r.dims.map((d) => d.label), ...numbers(r.values)]),
    [...dimensions.map((_, i) => (i === 0 ? "合計" : "")), ...numbers(result.totals)],
  ];
}

// ── 佣金明細 ─────────────────────────────────────────────────

export interface CommissionLike {
  rows: {
    kind: "sale" | "return";
    date: string;
    doc_no: string;
    warehouse: string;
    msisdn: string;
    carrier: string;
    plan: string;
    sales_person: string;
    commission: string | null;
    company_commission?: string | null;
  }[];
  totals: { commission: string; company_commission?: string };
  /** 管理員才有公司佣金那一欄 */
  manager: boolean;
}

export function commissionTable(data: CommissionLike): unknown[][] {
  const head = ["日期", "單號", "類別", "門市", "門號", "電信", "方案", "業務員", "業務員佣金"];
  if (data.manager) head.push("公司佣金");
  const out: unknown[][] = [head];
  for (const r of data.rows) {
    const line: unknown[] = [
      r.date, r.doc_no, r.kind === "return" ? "銷退" : "銷貨", r.warehouse, r.msisdn, r.carrier, r.plan,
      r.sales_person, exportNumber(r.commission),
    ];
    if (data.manager) line.push(exportNumber(r.company_commission));
    out.push(line);
  }
  const total: unknown[] = ["合計", "", "", "", "", "", "", "", exportNumber(data.totals.commission)];
  if (data.manager) total.push(exportNumber(data.totals.company_commission));
  out.push(total);
  return out;
}

// ── 庫存查詢 ─────────────────────────────────────────────────

export interface MatrixProductLike {
  sku: string;
  name: string;
  spec: string;
  category_name: string;
  list_price: string;
  weighted_avg_cost: string;
  stock_by_warehouse: Record<string, number>;
  stock_total: number;
}

/** 每個商品一列:各門市一欄、合計、售價、平均成本、總成本(= 平均成本 × 合計,跟畫面同一個算法)。最後一列合計。 */
export function stockMatrixTable(
  warehouses: { id: number; name: string }[],
  products: MatrixProductLike[],
): unknown[][] {
  const out: unknown[][] = [
    ["品號", "品名", "規格", "類別", ...warehouses.map((w) => w.name), "合計", "售價", "平均成本", "總成本"],
  ];
  const sums = warehouses.map(() => 0);
  let grand = 0;
  let cost = 0;
  for (const p of products) {
    const each = warehouses.map((w) => p.stock_by_warehouse[String(w.id)] ?? 0);
    each.forEach((q, i) => (sums[i] += q));
    const value = Number(p.weighted_avg_cost || 0) * p.stock_total;
    grand += p.stock_total;
    cost += value;
    out.push([
      p.sku, p.name, p.spec, p.category_name, ...each, p.stock_total,
      intStr(p.list_price), intStr(p.weighted_avg_cost), intStr(value),
    ]);
  }
  // 合計列的平均成本 = 總成本 ÷ 合計(跟畫面最下面那一列一樣;沒有庫存就空著)
  out.push(["合計", "", "", "", ...sums, grand, "", grand > 0 ? intStr(cost / grand) : "", intStr(cost)]);
  return out;
}

// ── 合約到期 ─────────────────────────────────────────────────

export interface ContractLike {
  msisdn: string;
  contract_end: string;
  days_left: number;
  plan_name: string;
  carrier_name: string;
  so_no: string;
  warehouse_name: string;
  sales_person_name: string;
  customer_name: string;
  customer_phone: string;
  member_name: string;
  member_phone: string;
  state: "open" | "contacted" | "declined" | "renewed";
  follow: { status: string; note: string } | null;
}

const CONTRACT_STATE: Record<ContractLike["state"], string> = {
  open: "未聯絡", contacted: "已聯絡", declined: "不續約", renewed: "已續約",
};

export function contractTable(rows: ContractLike[]): unknown[][] {
  return [
    ["到期日", "剩幾天", "門號", "客戶", "客戶電話", "會員", "會員電話", "電信", "方案", "門市", "業務員", "銷貨單", "狀況", "備註"],
    ...rows.map((r) => [
      r.contract_end, r.days_left, r.msisdn, r.customer_name, r.customer_phone, r.member_name, r.member_phone,
      r.carrier_name, r.plan_name, r.warehouse_name, r.sales_person_name, r.so_no,
      CONTRACT_STATE[r.state] ?? "", r.follow?.note ?? "",
    ]),
  ];
}

// ── 要翻頁的清單:把每一頁抓完 ──────────────────────────────────

/**
 * 從第一頁一路抓到沒有下一頁為止。`fetchPage(游標)` 回這一頁的列與下一頁的游標(null = 沒有了)。
 * 最多 `maxPages` 頁:超過就停,`truncated = true`(畫面要講「只匯出前幾列」),不會無止盡地抓。
 * 中間有一頁失敗 → 整個丟出去(不給一份只有一半、看起來卻像完整的檔)。
 */
export async function collectPages<T, C>(
  first: C,
  fetchPage: (cursor: C) => Promise<{ rows: T[]; next: C | null }>,
  maxPages = 100,
): Promise<{ rows: T[]; truncated: boolean }> {
  const rows: T[] = [];
  let cursor: C | null = first;
  for (let i = 0; i < maxPages && cursor !== null; i++) {
    const page: { rows: T[]; next: C | null } = await fetchPage(cursor);
    rows.push(...page.rows);
    cursor = page.next;
  }
  return { rows, truncated: cursor !== null };
}

/**
 * 超過一次能匯出的上限時要講的話(沒超過 = 空的)。**有這句話就不給檔**(紅隊第 2 條:老闆把只有前幾列的檔交給會計,
 * 加總少一截、獎金就算錯;寧可請他把條件縮小再匯一次,直到一次是完整的)。
 */
export function tooManyToExport(limit: number, truncated: boolean | undefined): string {
  return truncated ? `超過 ${limit} 列,沒有匯出(不給只有一部分的檔)。請把條件縮小再匯出一次` : "";
}

/**
 * **完整才存檔**:超過上限(`truncated`)就不存、回要講給人聽的話;存了回空字串。
 * 每一頁的「匯出」都走這一支(不直接呼叫存檔),所以「不給只有一部分的檔」只有一個地方決定。
 * `table` 是函式:被擋下來的時候不用白排一次。
 */
export function exportIfComplete(
  got: { count: number; truncated?: boolean },
  fileName: string,
  table: () => unknown[][],
  save: (fileName: string, table: unknown[][]) => void,
): string {
  const tooMany = tooManyToExport(got.count, got.truncated);
  if (tooMany) return tooMany;
  save(fileName, table());
  return "";
}

/**
 * 檔名:報表名稱_門市_期間.csv(紅隊第 3 條:同一天匯出兩家店的同一張報表,檔名一樣會分不出來)。
 * store:門市名稱;空字串 / null = 沒選門市(寫「全部門市」);undefined = 這張報表沒有門市這個條件(不寫)。
 * 有期間就寫期間,沒有(現在的庫存、名單)寫 day。門市名稱裡不能當檔名的字換成「-」。
 */
export function exportFileName(
  title: string,
  parts: { store?: string | null; from?: string; to?: string; day?: string } = {},
): string {
  const names = [title];
  if (parts.store !== undefined) names.push((parts.store || "全部門市").replace(/[\\/:*?"<>|\s]+/g, "-"));
  if (parts.from && parts.to) names.push(parts.from, parts.to);
  else if (parts.day) names.push(parts.day);
  return `${names.join("_")}.csv`;
}
