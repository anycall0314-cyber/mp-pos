// 銷貨日報在畫面這一側的規則(跑法:npm test)。
// 資料由伺服器一次給齊(backend/apps/sales/daily_report.py):期間內的銷貨單與銷退,每一行的欄位名稱跟銷貨單清單一樣,
// 銷退的每一行數量與金額是負的。這裡管:條件怎麼變成網址、打了商品的字之後列哪幾行、合計怎麼算、匯出的檔。
// **合計的算法是從原本的頁面原樣搬過來的**(2026-10-12 之前寫在 SalesDailyReport.tsx 裡),數字不因為這次改動而變。
import { staffMargin } from "./staffCost.ts";
import { intStr } from "./money.ts";

export interface DailyItem {
  id: number;
  line_no: number;
  product: number;
  product_sku: string;
  product_name: string;
  product_counts_margin: boolean;
  /** 客人要不要付(手機回補不用付:不算金額,只算毛利)。舊資料沒有 = 要付 */
  counts_cash?: boolean;
  product_warehouse_type: string;
  serials: { serial_no: string }[];
  qty: number;
  unit_price: string;
  amount: string;
  untaxed_amount: string;
  cost_at_post: string;
  staff_cost: string;
  /** 打了商品的字時,這一行對不對得上(沒打字 = 都是 true) */
  matched: boolean;
}

export interface DailyOrder {
  id: number;
  no: string;
  doc_date: string;
  is_void: boolean;
  warehouse_code: string | null;
  warehouse_name: string | null;
  sales_person_name: string | null;
  customer_name: string | null;
  member_name: string | null;
  items: DailyItem[];
  /** 銷退才有:原銷貨單 */
  original_so?: number;
  original_so_no?: string;
}

export interface DailyReport {
  from: string;
  to: string;
  warehouse: number | null;
  orders: DailyOrder[];
  returns: DailyOrder[];
  searching: boolean;
  truncated: boolean;
  limit: number;
}

export interface DailyFilter {
  from: string;
  to: string;
  warehouse: number | "";
  sales_person: number | "";
  customer: number | "";
  member: number | "";
  /** 品號 / 品名 / 序號 */
  search: string;
}

export function dailyQuery(f: DailyFilter): string {
  const q = new URLSearchParams();
  q.set("from", f.from);
  q.set("to", f.to);
  for (const key of ["warehouse", "sales_person", "customer", "member"] as const) {
    if (f[key] !== "") q.set(key, String(f[key]));
  }
  if (f.search.trim() !== "") q.set("search", f.search.trim());
  return q.toString();
}

const pad = (n: number) => String(n).padStart(2, "0");

/** 這台電腦的幾天前("YYYY-MM-DD";0 = 今天)。不用 toISOString:那是世界時間,台灣早上八點以前會變成昨天。 */
export function daysAgo(days: number, now: Date = new Date()): string {
  const d = new Date(now.getFullYear(), now.getMonth(), now.getDate() - days);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/**
 * 要列出來的單與行。打了商品的字:只留對得上的那幾行(一行都沒有的單不列);
 * 勾了「整張單」(whole)就整張都留。沒打字 = 原樣。
 */
export function shownOrders(orders: DailyOrder[], whole: boolean): DailyOrder[] {
  if (whole) return orders;
  const out: DailyOrder[] = [];
  for (const o of orders) {
    if (o.items.every((it) => it.matched)) {
      out.push(o);
      continue;
    }
    const items = o.items.filter((it) => it.matched);
    if (items.length > 0) out.push({ ...o, items });
  }
  return out;
}

export function splitOrders(orders: DailyOrder[]): { active: DailyOrder[]; voided: DailyOrder[] } {
  const active: DailyOrder[] = [];
  const voided: DailyOrder[] = [];
  for (const o of orders) (o.is_void ? voided : active).push(o);
  return { active, voided };
}

// ── 每一行的數字(從原本的頁面原樣搬過來)────────────────────────

/** 收購二手等不計毛利的行(只算現金)不算成本與毛利。 */
export function itemCountsMargin(it: Pick<DailyItem, "product_counts_margin">): boolean {
  return it.product_counts_margin !== false;
}

/** 這一行客人付的金額:手機回補那種客人不用付的是 0(金額合計跟收到的錢對得上;毛利照樣算它) */
export function paidAmount(it: Pick<DailyItem, "amount" | "counts_cash">): number {
  return it.counts_cash === false ? 0 : Number(it.amount);
}

/** 一張單客人付的含稅金額(手機寬度那張卡片底下的「含稅金額」;回補不算) */
export function orderPaidAmount(o: Pick<DailyOrder, "items">): number {
  return o.items.reduce((s, it) => s + paidAmount(it), 0);
}

/** 毛利 = 未稅金額 − 成本(未稅金額是存檔當下存死的,報表不自己回推稅別)。 */
export function itemGrossProfit(it: DailyItem): number {
  if (!itemCountsMargin(it)) return 0;
  return Number(it.untaxed_amount) - Number(it.cost_at_post);
}

/** 業務員毛利 = 未稅金額 − 業務員成本(成交當下記在單上的;沒有設定規則時跟毛利一樣)。 */
export function itemStaffProfit(it: DailyItem): number {
  return staffMargin(it);
}

export function serialList(it: Pick<DailyItem, "serials">): string {
  if (!it.serials || it.serials.length === 0) return "";
  return it.serials.map((s) => s.serial_no).join(" / ");
}

export interface DailyTotals {
  lines: number;
  amountIncl: number;
  cost: number;
  profit: number;
  staffProfit: number;
  /** 零件調貨單獨統計(不汙染商品毛利) */
  partsLines: number;
  partsAmount: number;
  partsCost: number;
  partsProfit: number;
  partsStaffProfit: number;
}

/** 標題旁邊那幾格的合計(商品 / 零件分開)。銷貨單與銷退用同一支算:銷退的數字是負的,算出來就是負的。 */
export function dailyTotals(orders: DailyOrder[]): DailyTotals {
  let lines = 0;
  let amountIncl = 0;
  let cost = 0;
  let profit = 0;
  let staffProfit = 0;
  let partsLines = 0;
  let partsAmount = 0;
  let partsCost = 0;
  let partsProfit = 0;
  let partsStaffProfit = 0;
  for (const o of orders) {
    for (const it of o.items) {
      const isParts = it.product_warehouse_type === "parts";
      if (isParts) {
        partsLines += 1;
        partsAmount += paidAmount(it);
        if (itemCountsMargin(it)) {
          partsCost += Number(it.cost_at_post);
          partsProfit += itemGrossProfit(it);
          partsStaffProfit += itemStaffProfit(it);
        }
      } else {
        lines += 1;
        amountIncl += paidAmount(it);
        if (itemCountsMargin(it)) {
          cost += Number(it.cost_at_post);
          profit += itemGrossProfit(it);
          staffProfit += itemStaffProfit(it);
        }
      }
    }
  }
  return {
    lines, amountIncl, cost, profit, staffProfit,
    partsLines, partsAmount, partsCost, partsProfit, partsStaffProfit,
  };
}

/**
 * 扣掉銷退之後的那一組(動手前紅隊第 1 條:銷退列出來了,標題卻沒有一個「已經扣掉」的數字,打烊與算獎金會看錯)。
 * 銷退的合計本身是負的,所以是相加。商品的那幾格;零件調貨另外一排。
 */
export function netTotals(
  sold: Pick<DailyTotals, "amountIncl" | "profit" | "staffProfit">,
  back: Pick<DailyTotals, "amountIncl" | "profit" | "staffProfit">,
): { amount: number; profit: number; staffProfit: number } {
  return {
    amount: sold.amountIncl + back.amountIncl,
    profit: sold.profit + back.profit,
    staffProfit: sold.staffProfit + back.staffProfit,
  };
}

/**
 * 現在有哪幾個「會讓合計變小」的條件(紅隊第 3 條:查完商品忘了清,會把畫面上的合計當成整天的)。
 * 有任何一個,標題旁邊就要亮「篩選中」。期間與門市不算(那是這張表本來的範圍)。
 */
export function narrowedBy(f: Pick<DailyFilter, "sales_person" | "customer" | "member" | "search">): string[] {
  const out: string[] = [];
  if (f.sales_person !== "") out.push("業務員");
  if (f.customer !== "") out.push("來源");
  if (f.member !== "") out.push("會員");
  if (f.search.trim() !== "") out.push("商品");
  return out;
}

/** 客戶那一格:這張單的來源;有會員而且不是同一個名字就接在後面。 */
export function customerText(o: Pick<DailyOrder, "customer_name" | "member_name">): string {
  const who = o.customer_name ?? "直客";
  return o.member_name && o.member_name !== who ? `${who} · ${o.member_name}` : who;
}

/** 超過一次能給的上限時要講的話(沒超過 = 空的)。 */
export function truncatedText(report: Pick<DailyReport, "truncated" | "limit">): string {
  return report.truncated ? `超過 ${report.limit} 張,只列前 ${report.limit} 張,合計不完整,請縮短期間` : "";
}

// ── 匯出 ────────────────────────────────────────────────────

export const DAILY_CSV_HEAD = [
  "日期", "單號", "門市", "業務員", "來源", "商品", "序號", "數量", "單價", "金額", "成本", "毛利", "業務員毛利",
  "作廢", "銷退", "原銷貨單", "會員",
];

/**
 * 匯出的表:正常單、銷退、作廢,一行一列。**前 14 欄的欄名與內容跟以前一樣**(客戶那一欄只寫來源,不接會員 ——
 * 有人拿舊的檔在對),後面多「銷退」「原銷貨單」「會員」。
 */
export function dailyTable(active: DailyOrder[], returns: DailyOrder[], voided: DailyOrder[]): unknown[][] {
  const out: unknown[][] = [DAILY_CSV_HEAD];
  const write = (o: DailyOrder, kind: "sale" | "return" | "void") => {
    for (const it of o.items) {
      const counts = itemCountsMargin(it);
      out.push([
        o.doc_date,
        o.no,
        `${o.warehouse_code ?? ""} ${o.warehouse_name ?? ""}`.trim(),
        o.sales_person_name ?? "",
        o.customer_name ?? "直客",
        it.product_name,
        serialList(it),
        String(it.qty),
        intStr(it.unit_price),
        intStr(it.amount),
        counts ? intStr(it.cost_at_post) : "",
        counts ? intStr(itemGrossProfit(it)) : "",
        counts ? intStr(itemStaffProfit(it)) : "",
        kind === "void" ? "Y" : "",
        kind === "return" ? "Y" : "",
        o.original_so_no ?? "",
        o.member_name ?? "",
      ]);
    }
  };
  for (const o of active) write(o, "sale");
  for (const o of returns) write(o, "return");
  for (const o of voided) write(o, "void");
  return out;
}
