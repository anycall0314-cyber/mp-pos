// 批發(賣家那一半)在畫面這一側:刷到的機器配到哪一行、這一次出貨送什麼、批發價怎麼預填。
// 規則只有伺服器那一份(backend/apps/trade/);這裡只是不讓人白按,送出去之後伺服器會再檢查一次。
import { roundInt } from "./money.ts";

export interface TradeUnitRef {
  serial: number;
  serial_no: string;
  imei: string;
  sn: string;
  status: string;
  status_label: string;
  warehouse: number | null;
  warehouse_name: string;
}

export interface TradeLine {
  id: number;
  sku: string;
  name: string;
  unit_label: string;
  product: number;
  requires_serial: boolean;
  per_unit: boolean;
  qty: number;
  shipped_qty: number;
  cancelled_qty: number;
  open_qty: number;
  /** 買家回報已經收進庫存幾個(收進去的那一次出貨不能取消) */
  received_qty?: number;
  unit_price: number;
  /** 中古機:訂的是哪一台(單上列完整的序號,出貨的人才找得到) */
  unit: TradeUnitRef | null;
}

export interface TradeShipmentRow {
  id: number;
  no: string;
  warehouse_name: string;
  sales_order: number;
  sales_order_no: string;
  shipped_at: string;
  goods_amount: number;
  shipping_fee: number;
  shipping_method: string;
  tracking_no: string;
  is_void: boolean;
  returned: boolean;
  lines: { line: number; qty: number; serials: string[] }[];
}

export interface TradeOrder {
  id: number;
  no: string;
  partner: number;
  partner_name: string;
  /** 平台內的同行 / 對外(不在這套 POS 上的系統,用金鑰來買);對外的另外有怎麼聯絡 */
  partner_kind?: "platform" | "external";
  partner_contact?: string;
  /** 這個同行已經給了、還沒被出過貨的單用掉的錢(先收款再出貨的看這個數) */
  credit?: number;
  buyer_store: string;
  status: "pending" | "accepted" | "shipped" | "rejected" | "cancelled";
  status_text: string;
  placed_at: string;
  payment_method: string;
  delivery_method: string;
  ship_name: string;
  ship_phone: string;
  ship_address: string;
  invoice_type: string;
  buyer_tax_id: string;
  buyer_name: string;
  invoice_email: string;
  note: string;
  close_reason: string;
  closed_by_buyer: boolean;
  is_test: boolean;
  goods_total: number;
  owed: number;
  paid: number;
  due: number;
  payment_status: string;
  lines: TradeLine[];
  shipments: TradeShipmentRow[];
}

/** 刷到一台之後伺服器回的:它是哪一台、可以出在哪幾行(由舊到新) */
export interface ScanFound {
  serial: number;
  serial_no: string;
  imei: string;
  sn: string;
  name: string;
  lines: { order: number; order_no: string; line: number; open_qty: number }[];
}

/** 這一次要出的:每一行(編號)刷了哪幾台;不帶序號的那幾行記要出幾個(沒記 = 還沒出的全部) */
export interface Picks {
  serials: Record<number, number[]>;
  qty: Record<number, number>;
}

export const NO_PICKS: Picks = { serials: {}, qty: {} };

const picked = (picks: Picks, line: number) => picks.serials[line] ?? [];

/** 這一行這一次出幾個 */
export function pickQty(picks: Picks, line: TradeLine): number {
  if (line.requires_serial) return picked(picks, line.id).length;
  const n = picks.qty[line.id];
  return n === undefined ? line.open_qty : Math.min(Math.max(n, 0), line.open_qty);
}

/** 刷到一台 → 放進它對得到、還沒刷滿的第一行。刷過了、都滿了回原因。 */
export function placeScan(picks: Picks, found: ScanFound): { picks: Picks; line: number; order: number } | { error: string } {
  if (Object.values(picks.serials).some((ids) => ids.includes(found.serial))) {
    return { error: `${found.serial_no} 刷過了` };
  }
  const target = found.lines.find((l) => picked(picks, l.line).length < l.open_qty);
  if (!target) return { error: `${found.serial_no}(${found.name})對得到的單都刷滿了` };
  return {
    picks: { ...picks, serials: { ...picks.serials, [target.line]: [...picked(picks, target.line), found.serial] } },
    line: target.line,
    order: target.order,
  };
}

/** 中古機那一行點一下:出這一台 / 不出(刷不到碼的時候用手點) */
export function toggleUnit(picks: Picks, line: TradeLine): Picks {
  if (!line.unit || line.open_qty < 1) return picks;
  const on = picked(picks, line.id).includes(line.unit.serial);
  return { ...picks, serials: { ...picks.serials, [line.id]: on ? [] : [line.unit.serial] } };
}

/** 帶序號的那一行把刷錯的一台拿掉 */
export function unpick(picks: Picks, line: number, serial: number): Picks {
  return { ...picks, serials: { ...picks.serials, [line]: picked(picks, line).filter((id) => id !== serial) } };
}

/** 不帶序號的那一行:這一次出幾個(輸入框的字;空的、不是數字 = 0;超過還沒出的 = 還沒出的) */
export function setQty(picks: Picks, line: TradeLine, text: string): Picks {
  const n = /^\d+$/.test(text.trim()) ? Number(text.trim()) : 0;
  return { ...picks, qty: { ...picks.qty, [line.id]: Math.min(n, line.open_qty) } };
}

/** 送給伺服器的這一次出貨(只有要出的那幾行) */
export function shipLines(order: TradeOrder, picks: Picks): { line: number; qty: number; serials: number[] }[] {
  return order.lines
    .filter((l) => l.open_qty > 0)
    .map((l) => ({ line: l.id, qty: pickQty(picks, l), serials: l.requires_serial ? picked(picks, l.id) : [] }))
    .filter((l) => l.qty > 0);
}

/** 這一次的貨款(整數元) */
export function shipTotal(order: TradeOrder, picks: Picks): number {
  return order.lines.reduce((sum, l) => sum + (l.open_qty > 0 ? roundInt(l.unit_price * pickQty(picks, l)) : 0), 0);
}

/** 運費輸入框:空的 = 0;不是 0 到 99999 的整數 = null(不能送) */
export function feeOf(text: string): number | null {
  const t = text.trim();
  if (t === "") return 0;
  return /^\d{1,5}$/.test(t) ? Number(t) : null;
}

/** 收款金額輸入框:1 到 99999999 的整數,不然 null */
export function amountOf(text: string): number | null {
  const t = text.trim().replace(/,/g, "");
  if (!/^\d{1,8}$/.test(t)) return null;
  const n = Number(t);
  return n >= 1 ? n : null;
}

/** 批發價輸入框:空的 = 照規則算(undefined);正的整數;不然 null(不能送) */
export function priceOf(text: string): number | undefined | null {
  const t = text.trim().replace(/,/g, "");
  if (t === "") return undefined;
  if (!/^\d{1,7}$/.test(t)) return null;
  return Number(t) >= 1 ? Number(t) : null;
}

export type UnitRule = "price_minus" | "price_percent" | "cost_plus";

/** 照規則預填這一台的批發價(跟伺服器 `listing.auto_price` 同一個算法);算出來不是正的 = 空的,要人填 */
export function autoPrice(rule: UnitRule, value: number, retail: number, cost: number): number | null {
  const raw = rule === "cost_plus" ? cost + value : rule === "price_percent" ? (retail * value) / 100 : retail - value;
  const price = roundInt(raw);
  return price > 0 ? price : null;
}

/** 一行的進度:訂 3 出 2 收 1 不出 1(收 = 買家已經入庫的) */
export function lineProgress(line: Pick<TradeLine, "qty" | "shipped_qty" | "cancelled_qty" | "received_qty">): string {
  const parts = [`訂 ${line.qty}`];
  if (line.shipped_qty) parts.push(`出 ${line.shipped_qty}`);
  if (line.received_qty) parts.push(`收 ${line.received_qty}`);
  if (line.cancelled_qty) parts.push(`不出 ${line.cancelled_qty}`);
  return parts.join(" ");
}

/** 一張單在清單上的那一句收件:宅配 王小明 0912… 新竹市… / 自取 */
export function shipTo(order: Pick<TradeOrder, "delivery_method" | "ship_name" | "ship_phone" | "ship_address">): string {
  return [order.delivery_method, order.ship_name, order.ship_phone, order.ship_address].filter(Boolean).join(" ");
}

/** 門市開銷貨單被擋:是不是「這幾台被同行訂走了」。是的話回那幾台(畫面讓人選賣給現場客人或保留) */
export interface HeldUnit {
  serial: string;
  serial_no: string;
  name: string;
  order_no: string;
  partner: string;
}

export function heldUnits(body: unknown): HeldUnit[] | null {
  if (!body || typeof body !== "object" || (body as { code?: unknown }).code !== "trade_hold") return null;
  const units = (body as { units?: unknown }).units;
  return Array.isArray(units) && units.length > 0 ? (units as HeldUnit[]) : null;
}

/**
 * 出貨之前提醒收款(紅隊 2026-10-14:外面今天才接上的,跟月結的老同行在同一張清單上)。錢不經過系統,所以**只提醒、不擋**。
 * 月結的不提醒;其他的:預收的錢夠這一次 → 「預收 N」;不夠 → 「未收款 還差 N」(warn)。這一次沒有要出的不講。
 */
export function prepayNote(order: Pick<TradeOrder, "payment_method" | "credit">, shipping: number): { text: string; warn: boolean } | null {
  if (order.payment_method === "月結" || shipping <= 0) return null;
  const credit = order.credit ?? 0;
  if (credit >= shipping) return { text: `預收 ${credit.toLocaleString("en-US")}`, warn: false };
  return { text: `未收款 還差 ${(shipping - credit).toLocaleString("en-US")}`, warn: true };
}
