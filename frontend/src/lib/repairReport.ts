// 維修月報在畫面這一側的規則(跑法:npm test)。哪幾張算、毛利怎麼算、每個人分到多少、誰看得到哪一家門市、
// 下拉有哪些選項與字,全部由伺服器決定(backend/apps/repairs/report.py);這裡只管條件怎麼變成網址、每一格怎麼寫、匯出的檔。
import { intStr, money } from "./money.ts";
import { PAGE_SIZE, type DocRef, type Listing } from "./stockReports.ts";

export interface RepairRow {
  id: number;
  /** 完工那一天 */
  date: string;
  doc: DocRef;
  store: string;
  model: string;
  /** in_house 自修 / vendor 委外 / transfer 內轉 */
  way: string;
  receiver: string;
  /** 另外的維修人員;空的 = 收件人自己修(委外給外廠的也是空的) */
  technician: string;
  paid: string;
  parts: string;
  outside: string;
  margin: string;
}

export interface RepairTotals {
  count: number;
  paid: string;
  parts: string;
  outside: string;
  margin: string;
}

export interface RepairPerson {
  id: number | null;
  name: string;
  received: number;
  repaired: number;
  /** 這個人分到的(收件的份 + 維修的份);全部的人加起來 = 合計的毛利 */
  amount: string;
}

export interface Choice {
  key: string;
  label: string;
}

export type RepairListing = Listing<RepairRow> & {
  from: string;
  to: string;
  totals: RepairTotals;
  people: RepairPerson[];
  choices: { way: Choice[] };
};

export interface RepairFilter {
  from: string;
  to: string;
  warehouse: number | "";
  /** 修法的代碼;空的 = 全部 */
  way: string;
}

/** page = 第幾頁;"export" = 照同樣的條件全部(匯出用)。 */
export function repairQuery(f: RepairFilter, page: number | "export"): string {
  const q = new URLSearchParams();
  q.set("from", f.from);
  q.set("to", f.to);
  if (f.warehouse !== "") q.set("warehouse", String(f.warehouse));
  if (f.way !== "") q.set("way", f.way);
  if (page === "export") q.set("export", "1");
  else {
    q.set("page", String(page));
    q.set("page_size", String(PAGE_SIZE));
  }
  return q.toString();
}

/** 選項的字(伺服器給的);清單裡沒有就照代碼寫。 */
export function wayLabel(choices: Choice[] | undefined, key: string): string {
  return choices?.find((c) => c.key === key)?.label ?? key;
}

/** 標題底下那一排:實付 − 成本 − 委外 = 毛利。 */
export function repairCards(totals: RepairTotals): { label: string; value: string }[] {
  return [
    { label: "件數", value: String(totals.count) },
    { label: "實付", value: money(totals.paid) },
    { label: "成本", value: money(totals.parts) },
    { label: "委外", value: money(totals.outside) },
    { label: "毛利", value: money(totals.margin) },
  ];
}

export const PEOPLE_HEAD = ["人員", "收件", "維修", "分到"];
export const REPAIR_HEAD = ["完工日", "維修單號", "門市", "機型", "方式", "收件人", "維修人員", "實付", "零件成本", "委外費用", "毛利"];
/** 不是管理員:伺服器給的零件成本與毛利是照業務員成本算的(owner 2026-10-28),欄名跟著換 */
export const REPAIR_HEAD_STAFF = REPAIR_HEAD.map((h) => (h === "零件成本" ? "業務員成本" : h === "毛利" ? "業務員毛利" : h));

/**
 * 匯出:上面是每個人分到多少,空一行,下面是逐筆。金額不加千分位。
 * 兩段都在同一個檔裡:只匯出逐筆的話,檔裡看不出每個人分到多少(那是伺服器照每一張單算的,逐筆的欄算不回來)。
 */
export function repairTable(listing: Pick<RepairListing, "results" | "people" | "choices">, actual = true): unknown[][] {
  return [
    PEOPLE_HEAD,
    ...listing.people.map((p) => [p.name, p.received, p.repaired, intStr(p.amount)]),
    [],
    actual ? REPAIR_HEAD : REPAIR_HEAD_STAFF,
    ...listing.results.map((r) => [
      r.date, r.doc.no, r.store, r.model, wayLabel(listing.choices.way, r.way), r.receiver, r.technician,
      intStr(r.paid), intStr(r.parts), intStr(r.outside), intStr(r.margin),
    ]),
  ];
}
