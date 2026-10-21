// 瑕疵設備送廠商換貨(owner 2026-10-21「瑕疵部分照你的方法做，回來了名字改為已換貨」)。
// 規則在伺服器(backend/apps/inventory/vendor_exchange.py):那一台留在原門市、狀態「廠商換貨中」,不能賣、不能調撥;
// 換回來一定要刷回來的那一台(碼一樣 = 同一台;不一樣 = 換成另一台,帳上的碼改成新的、留紀錄)。

export interface VendorExchangeRow {
  id: number;
  status: "pending" | "done" | "cancelled";
  status_label: string;
  warehouse: { id: number; code: string; name: string };
  supplier: { id: number; name: string } | null;
  product: { id: number; sku: string; name: string };
  serial: number;
  sent_imei: string;
  sent_sn: string;
  back_imei: string;
  back_sn: string;
  swapped: boolean;
  note: string;
  sent_by: string;
  sent_at: string;
  done_by: string;
  done_at: string | null;
  /** 送出到今天(處理過的:到處理那天)幾天 */
  days: number;
}

export interface VendorExchangeList {
  results: VendorExchangeRow[];
  count: number;
  limit: number;
}

export type ExchangeTab = "pending" | "closed";

/** 頁面上面的兩個分頁(字數一樣) */
export const EXCHANGE_TABS: { key: ExchangeTab; label: string }[] = [
  { key: "pending", label: "換貨中" },
  { key: "closed", label: "已處理" },
];

export function codesText(imei: string, sn: string): string {
  return [imei, sn].filter(Boolean).join(" / ") || "—";
}

/** 處理過的那一筆結果怎麼寫 */
export function resultText(row: VendorExchangeRow): string {
  if (row.status === "cancelled") return "標錯了";
  if (row.status !== "done") return row.status_label;
  return row.swapped ? `已換貨,換成 ${codesText(row.back_imei, row.back_sn)}` : "已換貨,同一台";
}

/** 只列了最近幾筆的話講一句 */
export function cutText(list: VendorExchangeList | undefined): string {
  return list && list.count > list.results.length ? `只列最近 ${list.limit} 筆` : "";
}

/** 開單刷到的那一台在廠商換貨、而且就在這個出貨倉:剛刷的就是它 = 換回來了,可以按「已換貨」接著賣 */
export function backAtCounter(device: { status: string; warehouse: number | null }, at: number): boolean {
  return device.status === "rma" && device.warehouse === at;
}
