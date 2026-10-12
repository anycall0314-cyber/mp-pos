// 庫存三張(進銷存表、異動查詢、序號查詢)在畫面這一側的規則。跑法:npm test。
// 怎麼算、誰看得到哪一家門市全部由伺服器決定(backend/apps/inventory/flows.py、reports.py);
// 這裡只管:條件怎麼變成網址、每一格怎麼顯示、匯出的檔長什麼樣、點單號去哪一頁。
import { intStr, money } from "./money.ts";

// ── 伺服器回來的樣子 ─────────────────────────────────────────

export interface FlowColumn {
  key: string;
  label: string;
  /** 這一欄對庫存是加(1)還是減(-1) */
  sign: number;
}

export interface FlowRow {
  product: number;
  sku: string;
  name: string;
  category: string;
  opening: number;
  closing: number;
  /** 期末裡「已退」的那幾台(序號商品被客人退回來、還沒處理) */
  returned: number;
  /** 調撥途中(只有全公司那一張有) */
  transit: number;
  [column: string]: number | string;
}

export interface FlowResult {
  from: string;
  to: string;
  warehouse: number | null;
  columns: FlowColumn[];
  rows: FlowRow[];
  row_count: number;
  truncated: boolean;
  totals: Record<string, number>;
  with_transit: boolean;
}

export interface DocRef {
  kind: "purchase" | "sale" | "sale_return" | "transfer" | "repair";
  id: number;
  no: string;
}

export interface MoveRow {
  id: number;
  created_at: string;
  kind: string;
  kind_label: string;
  product: number | null;
  sku: string;
  name: string;
  serial: number | null;
  serial_no: string;
  qty: number;
  effects: { warehouse: number; name: string; delta: number }[];
  from_name: string;
  to_name: string;
  doc: DocRef | null;
  note: string;
}

export interface SerialRow {
  id: number;
  serial_no: string;
  imei: string;
  sn: string;
  product: number;
  sku: string;
  name: string;
  status: string;
  status_label: string;
  store: string;
  source: { kind: "purchase" | "trade_in"; label: string; doc: DocRef } | null;
  received_at: string | null;
  cost: string;
  sale: { doc: DocRef; date: string } | null;
}

export interface Listing<T> {
  count: number;
  results: T[];
  next?: string | null;
  truncated?: boolean;
}

// ── 條件 → 網址 ─────────────────────────────────────────────

export interface FlowFilter {
  from: string;
  to: string;
  warehouse: number | "";
  category: number | "";
  search: string;
  /** 只列期間內有進出的 */
  moved: boolean;
}

export interface MoveFilter {
  from: string;
  to: string;
  warehouse: number | "";
  kind: string;
  category: number | "";
  search: string;
  /** 就是這一個商品(從進銷存表點品名過來);空的 = 不指定 */
  product: number | "";
}

export interface SerialFilter {
  statuses: string[];
  warehouse: number | "";
  supplier: number | "";
  receivedFrom: string;
  receivedTo: string;
  soldFrom: string;
  soldTo: string;
  search: string;
}

/** 序號查詢一打開列的是「在門市裡的」:在庫 + 已退(已退的也在店裡,盤點要點得到)。 */
export const SERIAL_DEFAULT_STATUSES = ["in_stock", "returned"];

/**
 * 序號查詢的「狀態」選單(名稱一律兩個字)。在店 = 在庫 + 已退;在途 = 調撥中(跟進銷存表的「在途」同一個詞);
 * 全部 = 不篩(含維修中)。
 */
export const SERIAL_STATUS_CHOICES: { key: string; label: string; statuses: string[] }[] = [
  { key: "store", label: "在店", statuses: SERIAL_DEFAULT_STATUSES },
  { key: "in_stock", label: "在庫", statuses: ["in_stock"] },
  { key: "returned", label: "已退", statuses: ["returned"] },
  { key: "in_transit", label: "在途", statuses: ["in_transit"] },
  { key: "sold", label: "已售", statuses: ["sold"] },
  { key: "void", label: "作廢", statuses: ["void"] },
  { key: "all", label: "全部", statuses: [] },
];

export function statusesOf(choice: string): string[] {
  return (SERIAL_STATUS_CHOICES.find((c) => c.key === choice) ?? SERIAL_STATUS_CHOICES[0]).statuses;
}

export const PAGE_SIZE = 100;

function put(q: URLSearchParams, key: string, value: string | number | "" | undefined) {
  if (value !== undefined && value !== "" && String(value).trim() !== "") q.set(key, String(value).trim());
}

export function flowQuery(f: FlowFilter): string {
  const q = new URLSearchParams();
  q.set("from", f.from);
  q.set("to", f.to);
  put(q, "warehouse", f.warehouse);
  put(q, "category", f.category);
  put(q, "search", f.search);
  if (f.moved) q.set("moved", "1");
  return q.toString();
}

/** page = 第幾頁;"export" = 照同樣的條件全部(匯出用)。 */
export function moveQuery(f: MoveFilter, page: number | "export"): string {
  const q = new URLSearchParams();
  q.set("from", f.from);
  q.set("to", f.to);
  put(q, "warehouse", f.warehouse);
  put(q, "kind", f.kind);
  put(q, "category", f.category);
  put(q, "search", f.search);
  put(q, "product", f.product);
  paging(q, page);
  return q.toString();
}

/**
 * 從進銷存表的一列去異動查詢:同一段期間、同一家門市、**就是這一個商品**(帶商品編號)。
 * 不能用品號去找 —— 那是「包含」,`A-000001` 會連 `BA-000001` 一起列出來,加起來就對不上這一列。
 */
export function movesOfFlowRow(
  flow: Pick<FlowFilter, "from" | "to" | "warehouse">,
  row: Pick<FlowRow, "product" | "sku" | "name">,
): { filter: MoveFilter; product: { id: number; label: string } } {
  return {
    filter: { from: flow.from, to: flow.to, warehouse: flow.warehouse, kind: "", category: "", search: "", product: row.product },
    product: { id: row.product, label: `${row.sku} ${row.name}` },
  };
}

export function serialQuery(f: SerialFilter, page: number | "export"): string {
  const q = new URLSearchParams();
  if (f.statuses.length > 0) q.set("status", f.statuses.join(","));
  put(q, "warehouse", f.warehouse);
  put(q, "supplier", f.supplier);
  put(q, "received_from", f.receivedFrom);
  put(q, "received_to", f.receivedTo);
  put(q, "sold_from", f.soldFrom);
  put(q, "sold_to", f.soldTo);
  put(q, "search", f.search);
  paging(q, page);
  return q.toString();
}

function paging(q: URLSearchParams, page: number | "export") {
  if (page === "export") q.set("export", "1");
  else {
    q.set("page", String(page));
    q.set("page_size", String(PAGE_SIZE));
  }
}

const DAY = /^\d{4}-\d{2}-\d{2}$/;

/** 可以不填的一組日期:空的不管;填了要是日期,兩格都填時開始不晚於結束。 */
export function optionalRangeReady(from: string, to: string): boolean {
  if (from && !DAY.test(from)) return false;
  if (to && !DAY.test(to)) return false;
  return !(from && to && from > to);
}

export function serialFilterReady(f: SerialFilter): boolean {
  return optionalRangeReady(f.receivedFrom, f.receivedTo) && optionalRangeReady(f.soldFrom, f.soldTo);
}

// ── 每一格怎麼顯示 ───────────────────────────────────────────

/** 進銷存表中間那幾欄:0 不寫(整張表才看得出哪裡有進出);期初、期末一律寫出來。 */
export function flowCell(value: number): string {
  return value === 0 ? "" : String(value);
}

/** 異動的數量:加減號寫出來(減號用全形的,跟加號一樣寬)。 */
export function signed(delta: number): string {
  if (delta > 0) return `+${delta}`;
  if (delta < 0) return `−${-delta}`;
  return "0";
}

/** 這一筆異動動到哪家門市、各多少(一筆最多兩家:確認過才作廢的調撥)。沒動到任何一家 = 只是紀錄。 */
export function effectLines(row: Pick<MoveRow, "effects">): { name: string; text: string; delta: number }[] {
  return row.effects.map((e) => ({ name: e.name, text: signed(e.delta), delta: e.delta }));
}

/** 調撥的那幾類另外寫路線(從哪到哪)。 */
export function routeText(row: Pick<MoveRow, "kind" | "from_name" | "to_name">): string {
  if (!["transfer_out", "transfer_in"].includes(row.kind)) return "";
  return row.from_name && row.to_name ? `${row.from_name} → ${row.to_name}` : "";
}

/** 點單號去哪一頁。 */
export function docPath(doc: DocRef): string {
  switch (doc.kind) {
    case "purchase":
      return `/purchases/${doc.id}`;
    case "sale":
      return `/sales/${doc.id}`;
    case "sale_return":
      return `/sales/returns/${doc.id}`;
    case "transfer":
      return `/transfers/${doc.id}`;
    case "repair":
      return `/repairs/${doc.id}`;
  }
}

const pad = (n: number) => String(n).padStart(2, "0");

/** 伺服器給的時間 → 這台電腦的「月-日 時:分」(跨年的清單在匯出檔裡有完整日期)。 */
export function shortTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** 完整的「年-月-日 時:分」(匯出用)。 */
export function fullTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** 只要日期(進貨日)。沒有 = 空的。 */
export function dayOf(iso: string | null): string {
  return iso ? fullTime(iso).slice(0, 10) : "";
}

/** 一台設備顯示哪兩個碼:有 IMEI 就 IMEI 在前;兩個都沒有(不該發生)退回主碼。 */
export function unitCodes(row: Pick<SerialRow, "serial_no" | "imei" | "sn">): { imei: string; sn: string } {
  if (!row.imei && !row.sn) return { imei: "", sn: row.serial_no };
  return { imei: row.imei, sn: row.sn };
}

// ── 分頁(進銷存表一次拿全部,畫面自己分)─────────────────────

export function pageCount(total: number, size: number = PAGE_SIZE): number {
  return Math.max(1, Math.ceil(total / size));
}

export function pageSlice<T>(rows: T[], page: number, size: number = PAGE_SIZE): T[] {
  const p = Math.min(Math.max(1, page), pageCount(rows.length, size));
  return rows.slice((p - 1) * size, p * size);
}

// ── 匯出 ────────────────────────────────────────────────────

/**
 * 試算表的一格。有逗號 / 引號 / 換行的包起來;**12 位以上的純數字(IMEI、條碼)寫成文字** ——
 * 不然試算表會把它當成數字、顯示成 3.56E+14,存檔之後末幾碼就變成 0。
 */
export function csvCell(value: unknown): string {
  const s = value === null || value === undefined ? "" : String(value);
  if (/^\d{12,}$/.test(s)) return `"=""${s}"""`;
  return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

export function toCsv(table: unknown[][]): string {
  return table.map((row) => row.map(csvCell).join(",")).join("\r\n");
}

export function flowTable(result: FlowResult): unknown[][] {
  const head = ["品號", "品名", "類別", "期初", ...result.columns.map((c) => c.label), "期末", "其中已退"];
  if (result.with_transit) head.push("在途");
  const line = (r: FlowRow) => {
    const out: unknown[] = [
      r.sku, r.name, r.category, r.opening,
      ...result.columns.map((c) => r[c.key]),
      r.closing, r.returned,
    ];
    if (result.with_transit) out.push(r.transit);
    return out;
  };
  return [head, ...result.rows.map(line)];
}

export function moveTable(rows: MoveRow[]): unknown[][] {
  const head = ["時間", "類別", "品號", "品名", "序號", "門市", "增減", "路線", "單號", "備註"];
  const out: unknown[][] = [head];
  for (const r of rows) {
    // 動到兩家門市的(確認過才作廢的調撥)一家一列,加起來才對得上
    const effects = r.effects.length > 0 ? r.effects : [{ name: "", delta: 0 }];
    for (const e of effects) {
      out.push([
        fullTime(r.created_at), r.kind_label, r.sku, r.name, r.serial_no,
        e.name, e.delta, routeText(r), r.doc?.no ?? "", r.note,
      ]);
    }
  }
  return out;
}

export function serialTable(rows: SerialRow[]): unknown[][] {
  const head = ["IMEI", "SN", "品號", "品名", "狀態", "門市", "來源", "進貨單號", "進貨日", "成本", "賣出單號", "賣出日"];
  return [
    head,
    ...rows.map((r) => {
      const codes = unitCodes(r);
      return [
        codes.imei, codes.sn, r.sku, r.name, r.status_label, r.store,
        r.source?.label ?? "", r.source?.doc.no ?? "", dayOf(r.received_at),
        intStr(r.cost), r.sale?.doc.no ?? "", r.sale?.date ?? "",
      ];
    }),
  ];
}

/** 成本在畫面顯示成整數元(全站同一條規則;存的還是到分)。匯出的檔不加千分位,試算表才當成數字。 */
export function costText(value: string | number): string {
  return money(value);
}

/** 匯出被伺服器截短時要講的話(沒截短 = 空的)。 */
export function truncatedNote(listing: { truncated?: boolean; count: number }): string {
  return listing.truncated ? `只匯出前 ${listing.count} 列,請把條件縮小` : "";
}
