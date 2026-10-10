// 半自動廠商(廠商沒有系統可以接)在畫面這一側的規則。跑法:npm test。
// 伺服器決定:商品清單(平台的價目表)、叫貨單的單號與內容、能不能入庫、對照。
// 這裡只管:紀錄上這張單現在算哪一種(已取消 / 未傳 / 已傳)、到貨入庫填到一半的樣子(數量、實際單價、運費、加的品項)、
// 合計與什麼時候不能按確認、「還不知道結果的那一次」怎麼記。
import {
  MAX_QTY,
  chosen,
  lineTitle,
  type PickedProduct,
  type ReceiveLine,
  type ReceivePlan,
} from "./vendorReceive.ts";

/** 半自動的叫貨單在紀錄上的記號(三個字數一樣;取消蓋過其他)。 */
export type ManualMark = "已取消" | "未傳出" | "已傳出";

export function manualMark(order: { sent_at: string | null; cancelled_at: string | null }): ManualMark {
  if (order.cancelled_at) return "已取消";
  return order.sent_at ? "已傳出" : "未傳出";
}

/** 這張單要不要在紀錄上標出來提醒(還沒傳給廠商、又沒取消:老闆會以為貨在路上)。 */
export function needsSending(order: { manual: boolean; sent_at: string | null; cancelled_at: string | null }): boolean {
  return order.manual && !order.sent_at && !order.cancelled_at;
}

/** 取消一張已經傳給廠商的單:提醒要自己跟廠商講(POS 這邊只是標記)。 */
export function cancelReminder(order: { sent_at: string | null }, vendorName: string): string {
  return order.sent_at ? `已取消。這張已經傳給${vendorName}了,記得通知他們` : "已取消";
}

// ── 到貨入庫(半自動)────────────────────────────────────────────────────────
/** 半自動的一行:單價是參考價(可以是空的),實際單價由入庫的人填。 */
export type ManualLine = Omit<ReceiveLine, "unit_price"> & { unit_price: string | null };

export interface ManualPlan extends Omit<ReceivePlan, "lines"> {
  manual: true;
  lines: ManualLine[];
  /** 這張單沒叫、價目表上有的:入庫時可以加(換款、多送) */
  extras: ManualLine[];
}

/**
 * 填到一半的樣子。數量不預先帶(沒有廠商說出了幾個);`price` 是框裡的字(先帶參考價);
 * `added` = 這張單沒叫、這個人加進來的品項;`product` / `repick` 跟全自動那一套同一個意思(見 vendorReceive.ts 的 chosen)。
 */
export interface ManualDraft {
  requestKey: string;
  qty: Record<string, number>;
  price: Record<string, string>;
  product: Record<string, PickedProduct>;
  repick: Record<string, true>;
  added: string[];
  freight: string;
  note: string;
}

/** 參考價 "45.00" → 框裡的字 "45";"42.50" → "42.5";沒有 → 空的。 */
export function priceText(value: string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "";
  const n = Number(value);
  return Number.isFinite(n) ? String(n) : "";
}

export function startManualDraft(plan: ManualPlan, requestKey: string): ManualDraft {
  const price: Record<string, string> = {};
  for (const line of [...plan.lines, ...plan.extras]) {
    const text = priceText(line.unit_price);
    if (text) price[line.key] = text;
  }
  return { requestKey, qty: {}, price, product: {}, repick: {}, added: [], freight: "", note: plan.issue_note };
}

/** 框裡的字 → 實際單價。只收一般的寫法(123 / 123.5 / 123.45),0 到 9,999,999.99;其他是 null(還沒填好)。 */
export function priceOf(text: string | undefined): number | null {
  const t = (text ?? "").trim();
  if (!/^\d{1,7}(\.\d{1,2})?$/.test(t)) return null;
  return Number(t);
}

/** 框裡的字 → 這一次的運費(整數元;空的 = 0)。亂寫的是 null。 */
export function freightOf(text: string): number | null {
  const t = text.trim();
  if (t === "") return 0;
  if (!/^\d{1,7}$/.test(t)) return null;
  return Number(t);
}

export function withManualQty(draft: ManualDraft, key: string, n: number): ManualDraft {
  const qty = { ...draft.qty };
  const clean = Number.isInteger(n) ? Math.min(Math.max(n, 0), MAX_QTY) : 0;
  if (clean > 0) qty[key] = clean;
  else delete qty[key];
  return { ...draft, qty };
}

export function withPrice(draft: ManualDraft, key: string, text: string): ManualDraft {
  return { ...draft, price: { ...draft.price, [key]: text } };
}

/** 「全部到齊」:每一行帶還沒入的(入超過的那幾行不帶)。只動數量。 */
export function fillAll(plan: ManualPlan, draft: ManualDraft): ManualDraft {
  const qty: Record<string, number> = {};
  for (const line of plan.lines) {
    const n = Math.max(line.remaining_qty, 0);
    if (n > 0) qty[line.key] = n;
  }
  return { ...draft, qty };
}

/** 加一項這張單沒叫的(要是伺服器說可以加的那幾項);加過的不重複。 */
export function addExtra(plan: ManualPlan, draft: ManualDraft, key: string): ManualDraft {
  if (draft.added.includes(key) || !plan.extras.some((l) => l.key === key)) return draft;
  return { ...draft, added: [...draft.added, key] };
}

/** 把加進來的那一項拿掉(它的數量一起清掉;單價留著,再加回來還在)。 */
export function removeExtra(draft: ManualDraft, key: string): ManualDraft {
  const qty = { ...draft.qty };
  delete qty[key];
  return { ...draft, qty, added: draft.added.filter((k) => k !== key) };
}

/** 畫面上要列的:這張單的每一行 + 這個人加進來的(照加的順序)。伺服器已經不給加的不列。 */
export function shownLines(plan: ManualPlan, draft: ManualDraft): ManualLine[] {
  const extras = draft.added.map((key) => plan.extras.find((l) => l.key === key)).filter((l): l is ManualLine => !!l);
  return [...plan.lines, ...extras];
}

/** 還可以加的那幾項(還沒加進來的)。 */
export function addable(plan: ManualPlan, draft: ManualDraft): ManualLine[] {
  return plan.extras.filter((l) => !draft.added.includes(l.key));
}

export interface ManualSend {
  key: string;
  qty: number;
  product: number;
  was: number | null;
  /** 實際單價(字串照人填的,例 "42.5");伺服器再驗一次 */
  unit_price: string;
}

export interface ManualSummary {
  lines: ManualSend[];
  pieces: number;
  /** 這一次的貨款(實際單價 × 數量;不含運費) */
  amount: number;
  /** 要入、但還沒選品號的那幾行 */
  unmapped: string[];
  /** 要入、但單價還沒填好的那幾行 */
  unpriced: string[];
  /** 比叫的多的那幾行(只提醒:廠商常常多送、併單) */
  over: string[];
  /** 這一次的運費;null = 框裡的字不對 */
  freight: number | null;
}

export function manualSummary(plan: ManualPlan, draft: ManualDraft): ManualSummary {
  const out: ManualSummary = { lines: [], pieces: 0, amount: 0, unmapped: [], unpriced: [], over: [], freight: freightOf(draft.freight) };
  for (const line of shownLines(plan, draft)) {
    const qty = draft.qty[line.key] ?? 0;
    if (qty <= 0) continue;
    out.pieces += qty;
    if (qty > line.remaining_qty) out.over.push(lineTitle(line));
    const price = priceOf(draft.price[line.key]);
    const picked = chosen(line, draft);
    if (price === null) out.unpriced.push(lineTitle(line));
    else out.amount += price * qty;
    if (!picked) out.unmapped.push(lineTitle(line));
    if (price !== null && picked) {
      out.lines.push({ key: line.key, qty, product: picked.id, was: line.product?.id ?? null, unit_price: (draft.price[line.key] ?? "").trim() });
    }
  }
  return out;
}

/** 為什麼現在不能按「確認入庫」(null = 可以)。比叫的多不擋。 */
export function manualBlocked(sum: ManualSummary): string | null {
  if (sum.pieces === 0) return "這一次沒有要入庫的東西";
  if (sum.unpriced.length > 0) return `還沒填實際單價:${sum.unpriced.join("、")}`;
  if (sum.unmapped.length > 0) return `還沒選品號:${sum.unmapped.join("、")}`;
  if (sum.freight === null) return "運費要是整數";
  return null;
}

/** 按了確認、還不知道結果的那一次(送出之前先記;規則跟全自動同一套,多了單價與運費)。 */
export interface ManualPending {
  requestKey: string;
  lines: ManualSend[];
  pieces: number;
  note: string;
  freight: number;
}

export function manualPendingOf(draft: ManualDraft, sum: ManualSummary): ManualPending {
  return { requestKey: draft.requestKey, lines: sum.lines, pieces: sum.pieces, note: draft.note, freight: sum.freight ?? 0 };
}

const whole = (n: unknown, min: number): n is number => typeof n === "number" && Number.isInteger(n) && n >= min;

/** 瀏覽器裡記的那一格 → 還不知道結果的那一次。讀不懂的一律當成沒有(不拿壞掉的內容去入庫)。 */
export function manualPendingFrom(raw: string | null | undefined): ManualPending | null {
  if (!raw) return null;
  let d: unknown;
  try {
    d = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!d || typeof d !== "object") return null;
  const p = d as Partial<ManualPending>;
  if (typeof p.requestKey !== "string" || !/^[A-Za-z0-9_-]{8,50}$/.test(p.requestKey)) return null;
  if (!Array.isArray(p.lines) || p.lines.length === 0) return null;
  if (!whole(p.freight, 0)) return null;
  const lines: ManualSend[] = [];
  for (const l of p.lines as unknown[]) {
    const row = l as Partial<ManualSend> | null;
    if (!row || typeof row.key !== "string" || !row.key || !whole(row.qty, 1) || !whole(row.product, 1)) return null;
    if (typeof row.unit_price !== "string" || priceOf(row.unit_price) === null) return null;
    const was = row.was ?? null;
    if (was !== null && !whole(was, 1)) return null;
    lines.push({ key: row.key, qty: row.qty, product: row.product, was, unit_price: row.unit_price });
  }
  return {
    requestKey: p.requestKey,
    lines,
    pieces: lines.reduce((sum, l) => sum + l.qty, 0),
    note: typeof p.note === "string" ? p.note : "",
    freight: p.freight,
  };
}

// ── 平台:從 Excel 整批貼上價目表 ────────────────────────────────────────────
export interface PastedItem {
  name: string;
  spec: string;
  sku: string;
  kind: string;
  unit: string;
  pack_qty: string;
  ref_price: string;
}

export const PASTE_COLUMNS: { field: keyof PastedItem; label: string; also: string[] }[] = [
  { field: "name", label: "品名", also: ["名稱", "商品名稱", "品項"] },
  { field: "spec", label: "規格", also: ["型號", "款式"] },
  { field: "sku", label: "料號", also: ["貨號", "品號", "編號"] },
  { field: "kind", label: "種類", also: ["類別", "分類"] },
  { field: "unit", label: "單位", also: [] },
  { field: "pack_qty", label: "一包幾個", also: ["入數", "包裝", "每包"] },
  { field: "ref_price", label: "參考單價", also: ["單價", "價格", "進價", "售價"] },
];

/**
 * Excel 複製貼上的字(一列一行、欄位用 Tab 隔開)→ 一列一項。
 * 第一行如果是欄名(有一格叫「品名」之類的)就照欄名對(欄的順序隨意、可以少幾欄、認不得的欄略過);
 * 沒有欄名就照固定的順序:品名、規格、料號、種類、單位、一包幾個、參考單價。整行空白的略過。
 */
export function parseSheet(text: string): PastedItem[] {
  const table = text
    .replace(/\r\n?/g, "\n")
    .split("\n")
    .map((line) => line.split("\t").map((cell) => cell.trim()))
    .filter((cells) => cells.some((c) => c !== ""));
  if (table.length === 0) return [];
  const find = (cell: string) => PASTE_COLUMNS.find((c) => c.label === cell || c.also.includes(cell))?.field;
  const header = table[0].map(find);
  const hasHeader = header.includes("name");
  const order: (keyof PastedItem | undefined)[] = hasHeader ? header : PASTE_COLUMNS.map((c) => c.field);
  return (hasHeader ? table.slice(1) : table).map((cells) => {
    const row: PastedItem = { name: "", spec: "", sku: "", kind: "", unit: "", pack_qty: "", ref_price: "" };
    cells.forEach((cell, i) => {
      const field = order[i];
      if (field && row[field] === "") row[field] = cell;
    });
    return row;
  });
}

/** 預覽上每一列的那個字(同一欄字數一樣)。 */
export const IMPORT_LABEL: Record<string, string> = { new: "新增", update: "更新", same: "不變", error: "有錯" };
