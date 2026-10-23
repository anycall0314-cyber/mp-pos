// 發票明細在畫面這一側的規則(跑法:npm test)。列哪幾張、狀態怎麼判、合計怎麼算、誰看得到哪一家門市、
// 下拉有哪些選項與字,全部由伺服器決定(backend/apps/sales/invoice_report.py);
// 這裡只管條件怎麼變成網址、每一格怎麼寫、匯出的檔。
import { intStr, money } from "./money.ts";
import { PAGE_SIZE, type DocRef, type Listing } from "./stockReports.ts";

/** ok 正常 / void 作廢 / check 待查(記成作廢,但退的金額跟發票金額對不起來) */
export type InvoiceState = "ok" | "void" | "check";

export interface InvoiceRow {
  id: number;
  /** 發票日期(沒有填的看單據日期) */
  date: string;
  invoice_no: string;
  /** 發票類型的名稱 */
  form: string;
  buyer_tax_id: string;
  doc: DocRef;
  store: string;
  customer: string;
  /** 課稅別的名稱 */
  tax_method: string;
  subtotal: string;
  tax: string;
  total: string;
  state: InvoiceState;
  /** 哪一天作廢的:銷貨單作廢 = 作廢那一刻的日期(以前作廢、沒有記到的是空的);銷退時作廢原發票 = 銷退的日期 */
  void_date: string | null;
  /** 退了多少(含稅);照銷退日看的時候是這段期間退的 */
  returned: string;
  return_date: string | null;
}

export interface Choice {
  key: string;
  label: string;
}

export interface InvoiceTotals {
  ok_count: number;
  void_count: number;
  check_count: number;
  /** 下面三個是正常那幾張的發票面額(沒有扣銷退) */
  subtotal: string;
  tax: string;
  total: string;
  check_total: string;
  /** 作廢那幾張的發票面額 */
  void_total: string;
  /** 正常那幾張被退的 */
  returned: string;
}

export type InvoiceListing = Listing<InvoiceRow> & {
  from: string;
  to: string;
  by: string;
  totals: InvoiceTotals;
  choices: { by: Choice[]; state: Choice[] };
};

export interface InvoiceFilter {
  from: string;
  to: string;
  /** 期間看哪一個日期;空的 = 伺服器的預設(發票日) */
  by: string;
  warehouse: number | "";
  /** 發票類型的代碼 */
  form: string;
  state: string;
  /** 發票號碼 / 統編 / 銷貨單號 */
  search: string;
}

/** page = 第幾頁;"export" = 照同樣的條件全部(匯出用)。 */
export function invoiceQuery(f: InvoiceFilter, page: number | "export"): string {
  const q = new URLSearchParams();
  q.set("from", f.from);
  q.set("to", f.to);
  for (const key of ["by", "warehouse", "form", "state"] as const) {
    if (f[key] !== "") q.set(key, String(f[key]));
  }
  if (f.search.trim() !== "") q.set("search", f.search.trim());
  if (page === "export") q.set("export", "1");
  else {
    q.set("page", String(page));
    q.set("page_size", String(PAGE_SIZE));
  }
  return q.toString();
}

/** 選項的字(伺服器給的);清單裡沒有就照代碼寫。 */
export function choiceLabel(choices: Choice[] | undefined, key: string): string {
  return choices?.find((c) => c.key === key)?.label ?? key;
}

/** 銷退那一格:沒有退是空的(不寫 0,一眼看得出哪幾張有退)。 */
export function returnedText(row: Pick<InvoiceRow, "returned">): string {
  return Number(row.returned) === 0 ? "" : money(row.returned);
}

/**
 * 標題底下那一排:金額只算正常那幾張的發票面額(沒有扣銷退);銷退、作廢、待查各自一格。
 * 作廢、待查有幾張就寫幾張與那幾張的面額(會計要列作廢清單的金額);0 張不寫金額。
 * 字由伺服器的狀態清單給(正常 / 作廢 / 待查),其餘是欄名。
 */
export function summaryCards(totals: InvoiceTotals, states: Choice[] | undefined): { label: string; value: string }[] {
  const sheets = (count: number, total: string) => (count === 0 ? "0 張" : `${count} 張 ${money(total)}`);
  return [
    { label: choiceLabel(states, "ok"), value: `${totals.ok_count} 張` },
    { label: "未稅", value: money(totals.subtotal) },
    { label: "稅額", value: money(totals.tax) },
    { label: "含稅", value: money(totals.total) },
    { label: "銷退", value: money(totals.returned) },
    { label: choiceLabel(states, "void"), value: sheets(totals.void_count, totals.void_total) },
    { label: choiceLabel(states, "check"), value: sheets(totals.check_count, totals.check_total) },
  ];
}

export const INVOICE_HEAD = [
  "發票日期", "發票號碼", "類型", "買方統編", "銷貨單號", "門市", "來源", "課稅別", "未稅", "稅額", "含稅", "狀態", "作廢日",
  "銷退", "銷退日",
];

/** 匯出:一張發票一列,金額不加千分位;沒有退的「銷退」是 0(檔裡要能加總)。 */
export function invoiceTable(rows: InvoiceRow[], states: Choice[] | undefined): unknown[][] {
  return [
    INVOICE_HEAD,
    ...rows.map((r) => [
      r.date, r.invoice_no, r.form, r.buyer_tax_id, r.doc.no, r.store, r.customer, r.tax_method,
      intStr(r.subtotal), intStr(r.tax), intStr(r.total), choiceLabel(states, r.state), r.void_date ?? "",
      intStr(r.returned), r.return_date ?? "",
    ]),
  ];
}

// ---- 開立發票彙總表(給會計師;照舊歐睿那一份的格式;怎麼分列、扣什麼都由伺服器決定) ----

export interface SummaryAmounts {
  subtotal: string;
  tax: string;
  total: string;
}

/** 上段:同一天 × 門市 × 發票類型 × 字軌一列;號碼是當天第一張 ~ 最後一張。 */
export interface SummaryIssued extends SummaryAmounts {
  date: string;
  store: string;
  form: string;
  first: string;
  last: string;
  count: number;
}

/** 下段:作廢與退回一張一列,金額是負的。 */
export interface SummaryReversed extends SummaryAmounts {
  date: string;
  store: string;
  form: string;
  invoice_no: string;
  kind: string;
}

export interface InvoiceSummary {
  from: string;
  to: string;
  issued: SummaryIssued[];
  reversed: SummaryReversed[];
  totals: { issued: SummaryAmounts; reversed: SummaryAmounts; net: SummaryAmounts };
  choices: { kind: Choice[] };
}

/** 彙總表只看期間、門市、發票類型(狀態、搜尋、日期看哪一個不套)。 */
export function summaryQuery(f: InvoiceFilter): string {
  const q = new URLSearchParams();
  q.set("from", f.from);
  q.set("to", f.to);
  if (f.warehouse !== "") q.set("warehouse", String(f.warehouse));
  if (f.form !== "") q.set("form", f.form);
  return q.toString();
}

const pad = (n: number) => String(n).padStart(2, "0");

/** 上一期發票(兩個月一期,單數月開始):十一月報稅時按「上期」= 9/1 ~ 10/31;一月 = 去年 11/1 ~ 12/31。 */
export function lastPeriod(now: Date = new Date()): { from: string; to: string } {
  const month = now.getMonth() + 1;
  let first = (month % 2 === 1 ? month : month - 1) - 2;
  let year = now.getFullYear();
  if (first < 1) {
    first += 12;
    year -= 1;
  }
  const lastDay = new Date(year, first + 1, 0).getDate();        // 第二個月的最後一天
  return { from: `${year}-${pad(first)}-01`, to: `${year}-${pad(first + 1)}-${pad(lastDay)}` };
}

/** 舊系統的日期寫法:20260905。 */
const compact = (day: string) => day.replaceAll("-", "");

const SUMMARY_HEAD = ["序號", "日期", "店別", "發票類別", "發票號碼", "銷貨金額", "銷貨稅額", "銷貨合計"];

function amounts(a: SummaryAmounts): string[] {
  return [intStr(a.subtotal), intStr(a.tax), intStr(a.total)];
}

/**
 * 匯出的檔:照舊系統的欄位順序(會計師不用重新看懂)——
 * 標題、上段(開立)+ 小計、下段(作廢與退回,多一欄說明)+ 小計、總計。金額不加千分位(檔裡要能加總)。
 * store:門市名稱,空的 = 全部門市;madeAt:製表時間。
 */
export function summaryTable(data: InvoiceSummary, store: string, madeAt: string): unknown[][] {
  const blank = ["", "", "", ""];
  return [
    ["開立發票彙總表", `日期：${compact(data.from)} ~ ${compact(data.to)}`, `門市：${store || "全部門市"}`, `製表時間：${madeAt}`],
    SUMMARY_HEAD,
    ...data.issued.map((r, i) => [i + 1, compact(r.date), r.store, r.form, `${r.first}-${r.last}`, ...amounts(r)]),
    ["金額小計：", ...blank, ...amounts(data.totals.issued)],
    [],
    ["作廢與退回"],
    [...SUMMARY_HEAD, "說明"],
    ...data.reversed.map((r, i) => [
      i + 1, compact(r.date), r.store, r.form, `${r.invoice_no}-${r.invoice_no}`, ...amounts(r),
      choiceLabel(data.choices.kind, r.kind),
    ]),
    ["金額小計：", ...blank, ...amounts(data.totals.reversed)],
    [],
    ["金額總計：", ...blank, ...amounts(data.totals.net)],
  ];
}

/** 製表時間:這台電腦的時間,2026/10/20 14:05。 */
export function madeAtText(now: Date = new Date()): string {
  return `${now.getFullYear()}/${pad(now.getMonth() + 1)}/${pad(now.getDate())} ${pad(now.getHours())}:${pad(now.getMinutes())}`;
}
