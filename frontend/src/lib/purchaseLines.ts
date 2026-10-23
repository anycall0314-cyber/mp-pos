// 進貨明細在畫面這一側的規則(跑法:npm test)。怎麼算、誰看得到哪一家門市由伺服器決定
// (backend/apps/purchasing/line_report.py);這裡只管條件怎麼變成網址、匯出的檔。
import { intStr } from "./money.ts";
import { PAGE_SIZE, type DocRef } from "./stockReports.ts";

export interface PurchaseLine {
  id: number;
  date: string;
  doc: DocRef;
  store: string;
  supplier: string;
  product: number;
  sku: string;
  name: string;
  qty: number;
  /** 贈品幾個(進貨數量 − 計價數量) */
  free_qty: number;
  /** 單上打的單價 / 金額(含稅還是未稅看那張單) */
  unit_price: string;
  amount: string;
  /** 記進庫存的未稅成本(這一行的小計) */
  cost: string;
  note: string;
}

export interface PurchaseLineFilter {
  from: string;
  to: string;
  warehouse: number | "";
  supplier: number | "";
  category: number | "";
  search: string;
}

/** page = 第幾頁;"export" = 照同樣的條件全部(匯出用)。 */
export function purchaseLineQuery(f: PurchaseLineFilter, page: number | "export"): string {
  const q = new URLSearchParams();
  q.set("from", f.from);
  q.set("to", f.to);
  for (const key of ["warehouse", "supplier", "category"] as const) {
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

/** 數量那一格:有贈品的寫出來(「12(贈 2)」)。 */
export function qtyText(row: Pick<PurchaseLine, "qty" | "free_qty">): string {
  return row.free_qty > 0 ? `${row.qty}(贈 ${row.free_qty})` : String(row.qty);
}

export function purchaseLineTable(rows: PurchaseLine[]): unknown[][] {
  const head = ["日期", "單號", "門市", "廠商", "品號", "品名", "數量", "贈品", "單價", "金額", "成本", "備註"];
  return [
    head,
    ...rows.map((r) => [
      r.date, r.doc.no, r.store, r.supplier, r.sku, r.name, r.qty, r.free_qty,
      intStr(r.unit_price), intStr(r.amount), intStr(r.cost), r.note,
    ]),
  ];
}
