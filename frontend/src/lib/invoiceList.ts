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
 * 字由伺服器的狀態清單給(正常 / 作廢 / 待查),其餘是欄名。
 */
export function summaryCards(totals: InvoiceTotals, states: Choice[] | undefined): { label: string; value: string }[] {
  return [
    { label: choiceLabel(states, "ok"), value: `${totals.ok_count} 張` },
    { label: "未稅", value: money(totals.subtotal) },
    { label: "稅額", value: money(totals.tax) },
    { label: "含稅", value: money(totals.total) },
    { label: "銷退", value: money(totals.returned) },
    { label: choiceLabel(states, "void"), value: `${totals.void_count} 張` },
    {
      label: choiceLabel(states, "check"),
      value: totals.check_count === 0 ? "0 張" : `${totals.check_count} 張 ${money(totals.check_total)}`,
    },
  ];
}

export const INVOICE_HEAD = [
  "發票日期", "發票號碼", "類型", "買方統編", "銷貨單號", "門市", "客戶", "課稅別", "未稅", "稅額", "含稅", "狀態", "銷退", "銷退日",
];

/** 匯出:一張發票一列,金額不加千分位;沒有退的「銷退」是 0(檔裡要能加總)。 */
export function invoiceTable(rows: InvoiceRow[], states: Choice[] | undefined): unknown[][] {
  return [
    INVOICE_HEAD,
    ...rows.map((r) => [
      r.date, r.invoice_no, r.form, r.buyer_tax_id, r.doc.no, r.store, r.customer, r.tax_method,
      intStr(r.subtotal), intStr(r.tax), intStr(r.total), choiceLabel(states, r.state),
      intStr(r.returned), r.return_date ?? "",
    ]),
  ];
}
