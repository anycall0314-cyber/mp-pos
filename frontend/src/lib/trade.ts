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
  /** 哪個型號(價目是一個型號一張表) */
  product: number;
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
  /** 獨立定價:價目表怎麼改都不動它 */
  own: boolean;
  /** 價目表上符合它的最細的那一格(沒有獨立定價的話用的就是這一格的價);沒有符合的是 null */
  rule: number | null;
}

/** 成色一次只看一個(跟狀態一樣點一個換一個;紅隊:可以複選的話換下一個成色時上一個還亮著,會把剛改好的蓋掉) */
export interface UnitFilter {
  grade: string | null;
  batteryMin: string;
  batteryMax: string;
  noted: "" | "yes" | "no";
  q: string;
  /** 只看獨立定價的那幾台(價目怎麼改都不動的,要人自己記得回來看) */
  onlyOwn?: boolean;
}
export const NO_UNIT_FILTER: UnitFilter = { grade: null, batteryMin: "", batteryMax: "", noted: "", q: "", onlyOwn: false };

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
    if (f.onlyOwn && !r.own) return false;
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
    own: filterUnits(rows, { ...f, onlyOwn: false }).filter((r) => r.own).length,
  };
}

// ── 價目表:一格 = 成色 + 電池區間 + 有沒有備註 → 一個價;符合的都用那個價,只有獨立定價的不跟(伺服器 `pricing.py`,這裡跟它同一套) ──
export interface PriceCell {
  grade: string;
  battery_min: number;
  battery_max: number;
  noted: "" | "yes" | "no";
}
export interface PriceRule extends PriceCell {
  id: number;
  /** 哪個型號的價目 */
  product: number;
  price: number;
  text: string;
  /** 全公司現在用這一格的有幾台(「全部型號」那個入口不算,是 null) */
  followers: number | null;
}
type PricedCell = PriceCell & { product: number; price: number };

/** 篩選列上點的成色 / 電池 / 備註就是價目的那一格。電池打錯回 null(不能存) */
export function cellOf(f: UnitFilter): PriceCell | null {
  const low = percentOf(f.batteryMin);
  const high = percentOf(f.batteryMax);
  if (low === null || high === null || (low ?? 0) > (high ?? 100)) return null;
  return { grade: f.grade ?? "", battery_min: low ?? 0, battery_max: high ?? 100, noted: f.noted };
}

export const sameCell = (a: PriceCell, b: PriceCell) =>
  a.grade === b.grade && a.battery_min === b.battery_min && a.battery_max === b.battery_max && a.noted === b.noted;

const cellBounded = (c: PriceCell) => c.battery_min !== 0 || c.battery_max !== 100;

/** 給人看的一格:「A 級 電池 85 以上 沒備註」「A 級」「全部」 */
export function cellText(c: PriceCell): string {
  const parts = c.grade ? [`${c.grade} 級`] : [];
  if (cellBounded(c)) {
    parts.push(c.battery_max === 100 ? `電池 ${c.battery_min} 以上` : c.battery_min === 0 ? `電池 ${c.battery_max} 以下` : `電池 ${c.battery_min}–${c.battery_max}`);
  }
  if (c.noted) parts.push(c.noted === "yes" ? "有備註" : "沒備註");
  return parts.join(" ") || "全部";
}

export function fitsCell(c: PriceCell, r: Pick<UnitLike, "grade" | "battery" | "note">): boolean {
  if (c.grade && r.grade !== c.grade) return false;
  if (cellBounded(c) && (r.battery === null || r.battery < c.battery_min || r.battery > c.battery_max)) return false;
  if (c.noted && (c.noted === "yes") !== (r.note.trim() !== "")) return false;
  return true;
}

const cellRank = (c: PriceCell) => (c.grade ? 4 : 0) + (cellBounded(c) ? 2 : 0) + (c.noted ? 1 : 0);

/** 符合這一台的格子裡最細的那一格(先比有沒有指定成色、再比有沒有限電池、再比有沒有指定備註) */
export function bestCell<T extends PriceCell>(cells: T[], r: Pick<UnitLike, "grade" | "battery" | "note">): T | null {
  let found: T | null = null;
  for (const c of cells) if (fitsCell(c, r) && (found === null || cellRank(c) > cellRank(found))) found = c;
  return found;
}

/** 這一頁上人動過的:哪幾台改成跟價目(true)/ 獨立(false)、哪幾台打了自己的價、價目那一格打了什麼 */
export interface UnitEdits {
  follow: Record<number, boolean>;
  typed: Record<number, string>;
  cellPrice: string;
}
export const NO_UNIT_EDITS: UnitEdits = { follow: {}, typed: {}, cellPrice: "" };

/** 這一台現在算不算跟著價目(勾著的):自己打了價就是獨立;不然看人有沒有改過、沒改過照它原本的 */
export function followsNow(r: UnitLike, edits: UnitEdits): boolean {
  if (edits.typed[r.serial] !== undefined) return false;
  return edits.follow[r.serial] ?? !r.own;
}

/** 價目表加上價目那一格還沒存的價(存了之後會是什麼樣子)。`product` = 那一格是哪個型號的 */
export function pendingCells(rules: PriceRule[], cell: PriceCell | null, edits: UnitEdits, product?: number): PricedCell[] {
  const price = priceOf(edits.cellPrice);
  if (cell === null || product === undefined || typeof price !== "number") return rules;
  return [...rules.filter((r) => r.product !== product || !sameCell(r, cell)), { ...cell, product, price }];
}

/** 這一台用哪一格:只看它自己那個型號的價目(「全部型號」那個入口一次有好幾個型號的價目;複審 P1) */
export const cellFor = <T extends PricedCell>(cells: T[], r: UnitLike): T | null => bestCell(cells.filter((c) => c.product === r.product), r);

/** 批發價那一格現在要顯示的字:獨立的是它自己的(打的優先);跟價目的是存了之後它會用的那一格的價,沒有符合的格子就是它現在的價 */
export function unitPriceShown(r: UnitLike, edits: UnitEdits, cells: PricedCell[]): string {
  if (edits.typed[r.serial] !== undefined) return edits.typed[r.serial];
  if (!followsNow(r, edits)) return r.price !== null ? String(r.price) : "";
  const cell = cellFor(cells, r);
  return cell ? String(cell.price) : r.price !== null ? String(r.price) : "";
}

export interface UnitPlan {
  rows: { serial: number; price?: number; own?: boolean }[];
  cell?: PriceCell;
  cell_price?: number;
  /** 給「再按一次」那一句用的數字 */
  cellFrom: number | null;
  toOwn: number;
  toFollow: number;
  priced: number;
  listed: number;
}

/**
 * 按下去要送什麼。`listing` = 未上架那一頁按「上架」:畫面上列出來的每一台都上架;不然只送有變的那幾台。
 * 有一台的價不對、或要上架卻沒有價,回是哪一台。
 */
export function unitPlan(shown: UnitLike[], rules: PriceRule[], cell: PriceCell | null, edits: UnitEdits, listing: boolean, product?: number): UnitPlan | { error: string } {
  const plan: UnitPlan = { rows: [], cellFrom: null, toOwn: 0, toFollow: 0, priced: 0, listed: 0 };
  const cellPrice = priceOf(edits.cellPrice);
  if (cellPrice === null) return { error: "價目要填正的整數" };
  if (product === undefined) cell = null;                                   // 價目那一格只有看一個型號的時候才有
  const exact = cell ? rules.find((r) => r.product === product && sameCell(r, cell)) : undefined;
  if (cell && typeof cellPrice === "number" && cellPrice !== exact?.price) {
    plan.cell = cell;
    plan.cell_price = cellPrice;
    plan.cellFrom = exact?.price ?? null;
  }
  const cells = pendingCells(rules, cell, edits, product);
  for (const r of shown) {
    const typed = edits.typed[r.serial];
    const follows = followsNow(r, edits);
    if (typed !== undefined) {
      const price = priceOf(typed);
      if (typeof price !== "number") return { error: `${r.serial_no} 的批發價要填正的整數` };
      if (listing || price !== r.price || !r.own) {
        plan.rows.push({ serial: r.serial, price });
        plan.priced += 1;
      }
    } else if (!follows) {
      if (r.price === null) return { error: `${r.serial_no} 要獨立定價,請填價` };
      if (listing || !r.own) plan.rows.push({ serial: r.serial, own: true });
      if (!r.own) plan.toOwn += 1;
    } else {
      if (listing && cellFor(cells, r) === null && r.price === null && r.auto_price === null) return { error: `${r.serial_no} 的批發價要填正的整數` };
      if (listing || r.own) plan.rows.push({ serial: r.serial });
      if (r.own) plan.toFollow += 1;
    }
  }
  plan.listed = listing ? shown.length : 0;
  return plan;
}

export const planIsEmpty = (plan: UnitPlan) => plan.rows.length === 0 && plan.cell === undefined;

/** 改到價目的一格(全公司符合的都會變)、或一次十台以上:按下去之前先講清楚、再按一次才做(紅隊:這是同行馬上看得到的價,不能回頭) */
export const UNIT_CONFIRM_FROM = 10;
export function unitNeedsConfirm(plan: UnitPlan): boolean {
  return plan.cell !== undefined || plan.rows.length >= UNIT_CONFIRM_FROM || plan.toOwn > 0;
}

/** 再按一次之前給人看的那一句。`followers` = 這一格現在全公司有幾台在用(新的一格不知道,講「符合的」) */
export function unitConfirmText(plan: UnitPlan, followers: number | null, retail: number[]): string {
  const parts: string[] = [];
  if (plan.cell !== undefined && plan.cell_price !== undefined) {
    const who = followers === null ? "全公司符合的" : `全公司用這一格的 ${followers} 台`;
    const odd = retail.length > 0 && (plan.cell_price > Math.max(...retail) || plan.cell_price * 2 < Math.min(...retail));
    parts.push(`價目「${cellText(plan.cell)}」${plan.cellFrom === null ? "" : `${plan.cellFrom} → `}${plan.cell_price}:${who}都用這個價,之後進貨的也是${odd ? "(跟門市價差很多)" : ""}`);
  }
  if (plan.listed) parts.push(`上架 ${plan.listed} 台`);
  if (plan.toOwn) parts.push(`${plan.toOwn} 台改成獨立定價(之後價目怎麼改都不動它)`);
  if (plan.toFollow) parts.push(`${plan.toFollow} 台改回跟價目`);
  if (plan.priced) parts.push(`${plan.priced} 台各自的價`);
  return parts.join(";");
}

/** 型號清單上當場改的價目:哪幾格真的變了(打錯的回 error) */
export function cellEdits(rules: PriceRule[], typed: Record<number, string>): { cells: { id: number; price: number }[]; followers: number } | { error: string } {
  const cells: { id: number; price: number }[] = [];
  let followers = 0;
  for (const rule of rules) {
    const text = typed[rule.id];
    if (text === undefined) continue;
    const price = priceOf(text);
    if (typeof price !== "number") return { error: `「${rule.text}」的價要填正的整數` };
    if (price === rule.price) continue;
    cells.push({ id: rule.id, price });
    followers += rule.followers ?? 0;
  }
  return { cells, followers };
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
