// 瑕疵設備送廠商換貨(owner 2026-10-21「瑕疵部分照你的方法做，回來了名字改為已換貨」)。
// 規則在伺服器(backend/apps/inventory/vendor_exchange.py):那一台留在原門市、狀態「廠商換貨中」,不能賣、不能調撥;
// 換回來一定要刷回來的那一台(碼一樣 = 同一台;不一樣 = 換成另一台,帳上的碼改成新的、留紀錄)。
// 配件(同一天:「換貨的通常都是配件沒序號也可以嗎」):送出時從門市數量扣掉,換回來加回去(可以分批);
// 廠商少補 / 不補 →「不換了」(只有管理員)。廠商一定要選:同一個品號跟兩家進過的,列進過的廠商讓人照標籤選。

export interface VendorExchangeRow {
  id: number;
  kind: "serial" | "product";
  status: "pending" | "done" | "cancelled" | "unreturned";
  status_label: string;
  warehouse: { id: number; code: string; name: string };
  supplier: { id: number; name: string } | null;
  product: { id: number; sku: string; name: string };
  serial: number | null;
  qty: number;
  back_qty: number;
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
  /** 還在廠商那邊(不換了 = 沒回來)的成本;只有管理員拿得到 */
  amount?: string;
}

export interface SupplierHint {
  id: number;
  name: string;
  /** 最近一次跟這家進這個商品的日期 */
  last: string;
}

/** 刷到的碼是哪一台設備 / 哪一個配件(送廠商之前) */
export type ExchangeLookup =
  | {
      kind: "serial";
      serial: number;
      serial_no: string;
      product: { id: number; sku: string; name: string };
      warehouse: { id: number; name: string } | null;
      status: string;
      status_label: string;
      sendable: boolean;
      default_supplier: number | null;
      suppliers: SupplierHint[];
    }
  | {
      kind: "product";
      product: { id: number; sku: string; name: string };
      stores: { id: number; name: string; qty: number }[];
      default_supplier: number | null;
      suppliers: SupplierHint[];
    };

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
  if (row.status === "unreturned") return `不換了,回來 ${row.back_qty} 個、少 ${row.qty - row.back_qty} 個`;
  if (row.status !== "done") return row.status_label;
  if (row.kind === "product") return `已換貨 ${row.qty} 個`;
  return row.swapped ? `已換貨,換成 ${codesText(row.back_imei, row.back_sn)}` : "已換貨,同一台";
}

/** 數量那一格:設備 1;配件回來一部分的寫已回幾個 */
export function qtyText(row: VendorExchangeRow): string {
  return row.back_qty > 0 && row.status === "pending" ? `${row.qty}(已回 ${row.back_qty})` : String(row.qty);
}

/** 廠商選單:進過這個商品的排前面(最近的在前),其他廠商排後面(標籤上的廠商不在前面那幾家時還選得到) */
export function supplierGroups<T extends { id: number; name: string }>(
  hints: SupplierHint[],
  all: T[],
): { hinted: SupplierHint[]; others: T[] } {
  const seen = new Set(hints.map((h) => h.id));
  return { hinted: hints, others: all.filter((s) => !seen.has(s.id)) };
}

/** 配件預設從哪一家門市送:鎖在門市的只有自己那一家;否則第一家有貨的 */
export function defaultStore(stores: { id: number; qty: number }[]): number | "" {
  return (stores.find((s) => s.qty > 0) ?? stores[0])?.id ?? "";
}

/** 只列了最近幾筆的話講一句 */
export function cutText(list: VendorExchangeList | undefined): string {
  return list && list.count > list.results.length ? `只列最近 ${list.limit} 筆` : "";
}

/** 開單刷到的那一台在廠商換貨、而且就在這個出貨倉:剛刷的就是它 = 換回來了,可以按「已換貨」接著賣 */
export function backAtCounter(device: { status: string; warehouse: number | null }, at: number): boolean {
  return device.status === "rma" && device.warehouse === at;
}

/**
 * 刷到之後游標去哪裡(owner 2026-10-23 檢視 B7:以前一律跳到「瑕疵狀況」,一箱寄好幾台時接著刷第二台,
 * 第二台的碼會寫進第一台的瑕疵狀況、條碼槍的 Enter 把第一台送出,第二台沒送)。
 * 設備:廠商已經帶好(或不能送)→ 留在刷碼格、整段反白,再按 Enter 就送、刷下一台會蓋掉;沒有廠商 → 去選廠商。
 * 瑕疵狀況要點了才填。配件 → 數量。
 */
export function focusAfterLook(hit: ExchangeLookup): "code" | "supplier" | "qty" {
  if (hit.kind === "product") return "qty";
  return !hit.sendable || hit.default_supplier ? "code" : "supplier";
}
