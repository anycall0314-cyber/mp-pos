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

// ── 中古機上架:同一個型號在庫幾百台,篩出差不多機況的那一群、整群同價(owner 2026-10-14) ──────────────
/** 上架那一頁的一台(篩選與定價只用到這幾格) */
export interface UnitLike {
  serial: number;
  serial_no: string;
  imei: string;
  sn: string;
  grade: string;
  battery: number | null;
  note: string;
  retail_price: number;
  auto_price: number | null;
  is_listed: boolean;
  /** 上架中的價;下架過的是它上一次的價;沒上過架是 null */
  price: number | null;
}

/** 成色一次只看一個(跟狀態一樣點一個換一個;紅隊:可以複選的話換下一個成色時上一個還亮著,會把剛改好的蓋掉) */
export interface UnitFilter {
  grade: string | null;
  batteryMin: string;
  batteryMax: string;
  noted: "" | "yes" | "no";
  q: string;
}
export const NO_UNIT_FILTER: UnitFilter = { grade: null, batteryMin: "", batteryMax: "", noted: "", q: "" };

const GRADE_ORDER = ["S", "A", "B", "C", "D", ""];
const gradeRank = (grade: string) => {
  const at = GRADE_ORDER.indexOf(grade);
  return at < 0 ? GRADE_ORDER.length : at;
};

/**
 * 手上這一份清單能不能拿來勾、拿來送:只有「現在問的這一份」的答案才行。
 * 換門市 / 狀態的那一下拿在手上的是上一份 —— 那一份一列都不算(複審 P0:不然「同價」會勾到上一間門市的那一群)。
 */
export function currentRows<T>(rows: T[] | undefined, isPrevious: boolean): T[] {
  return rows && !isPrevious ? rows : [];
}

/** 電池的上下限:空的 = 不限(undefined);0 到 100 的整數;不然 null(打錯,當成沒有符合的) */
export function percentOf(text: string): number | undefined | null {
  const t = text.trim();
  if (t === "") return undefined;
  if (!/^\d{1,3}$/.test(t) || Number(t) > 100) return null;
  return Number(t);
}

/** 照成色(S 到 D,沒評的最後)、電池高到低排:差不多機況的排在一起 */
export function sortUnits<T extends UnitLike>(rows: T[]): T[] {
  return [...rows].sort(
    (a, b) => gradeRank(a.grade) - gradeRank(b.grade) || (b.battery ?? -1) - (a.battery ?? -1) || a.serial - b.serial,
  );
}

export function filterUnits<T extends UnitLike>(rows: T[], f: UnitFilter): T[] {
  const low = percentOf(f.batteryMin);
  const high = percentOf(f.batteryMax);
  if (low === null || high === null) return [];
  const q = f.q.trim().toLowerCase();
  return rows.filter((r) => {
    if (f.grade !== null && r.grade !== f.grade) return false;
    // 有限電池的時候,沒記電池的那幾台不算符合(不知道是幾 %)
    if ((low !== undefined || high !== undefined) && r.battery === null) return false;
    if (low !== undefined && (r.battery as number) < low) return false;
    if (high !== undefined && (r.battery as number) > high) return false;
    if (f.noted === "yes" && r.note.trim() === "") return false;
    if (f.noted === "no" && r.note.trim() !== "") return false;
    return q === "" || [r.serial_no, r.imei, r.sn, r.note].some((text) => text.toLowerCase().includes(q));
  });
}

/** 篩選列每一顆上面寫的台數:是「別的條件照舊、只換這一顆」會剩幾台(點了 A 之後,「有備註」寫的是 A 裡面有備註的) */
export function unitFacets<T extends UnitLike>(rows: T[], f: UnitFilter) {
  const byGrade = new Map<string, number>();
  for (const r of filterUnits(rows, { ...f, grade: null })) byGrade.set(r.grade, (byGrade.get(r.grade) ?? 0) + 1);
  const others = filterUnits(rows, { ...f, noted: "" });
  const noted = others.filter((r) => r.note.trim() !== "").length;
  return {
    grades: [...byGrade.entries()].map(([grade, count]) => ({ grade, count })).sort((a, b) => gradeRank(a.grade) - gradeRank(b.grade)),
    noted,
    plain: others.length - noted,
  };
}

/** 這一列批發價那一格現在的字:自己打的優先 → 有勾而且上面有整群的價就是那個價 → 它原本的價(上架中的、或下架前的那個) → 空的(照規則) */
export function unitPriceText(row: UnitLike, typed: Record<number, string>, group: string, picked: boolean): string {
  if (typed[row.serial] !== undefined) return typed[row.serial];
  if (picked && group.trim() !== "") return group;
  return row.price !== null ? String(row.price) : "";
}

export interface UnitBatch {
  rows: { serial: number; price?: number }[];
  /** 用上面那個整群的價的有幾台 */
  grouped: number;
}

/** 勾著的這幾台要送出去什麼;有一台的價不對(或算不出來又沒填)就回是哪一台 */
export function unitBatch(chosen: UnitLike[], typed: Record<number, string>, group: string): UnitBatch | { error: string } {
  if (priceOf(group) === null) return { error: "批發價要填正的整數" };
  const rows: UnitBatch["rows"] = [];
  let grouped = 0;
  for (const r of chosen) {
    const price = priceOf(unitPriceText(r, typed, group, true));
    if (price === null || (price === undefined && r.auto_price === null)) return { error: `${r.serial_no} 的批發價要填正的整數` };
    if (typed[r.serial] === undefined && group.trim() !== "") grouped += 1;
    rows.push(price === undefined ? { serial: r.serial } : { serial: r.serial, price });
  }
  return { rows, grouped };
}

/** 一次動到很多台、或好幾台要變成同一個價:按下去之前先講清楚、再按一次才做(紅隊:這是同行馬上看得到的價,不能回頭) */
export const UNIT_CONFIRM_FROM = 10;
export function unitNeedsConfirm(count: number, grouped: number): boolean {
  return count >= UNIT_CONFIRM_FROM || grouped > 1;
}

/** 再按一次之前給人看的那一句:幾台、變成什麼價、原本是多少到多少;跟門市價差很多的另外提醒(只提醒) */
export function unitConfirmText(verb: string, chosen: UnitLike[], batch: UnitBatch, group: string): string {
  const price = priceOf(group);
  if (!batch.grouped || typeof price !== "number") return `${verb} ${chosen.length} 台`;
  const before = chosen.map((r) => r.price ?? r.auto_price).filter((n): n is number => n !== null);
  const range = before.length ? (Math.min(...before) === Math.max(...before) ? `${Math.min(...before)}` : `${Math.min(...before)}–${Math.max(...before)}`) : "";
  const retail = chosen.map((r) => r.retail_price).filter((n) => n > 0);
  const odd = retail.length > 0 && (price > Math.max(...retail) || price * 2 < Math.min(...retail));
  const rest = chosen.length - batch.grouped;
  return [
    `${batch.grouped} 台都${verb === "上架" ? "用" : "改成"} ${price}`,
    range && `原本 ${range}`,
    rest > 0 && `另外 ${rest} 台各自的價`,
    odd && "跟門市價差很多",
  ].filter(Boolean).join(",");
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
