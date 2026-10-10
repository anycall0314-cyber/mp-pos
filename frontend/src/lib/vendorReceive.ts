// 廠商叫貨的「到貨入庫」在畫面這一側的規則。跑法:npm test。
// 伺服器決定:單價(廠商那張單現在的)、運費算不算進成本、最多能入幾個、那個品號能不能入。
// 這裡只管:這一次每一行入幾個(預設帶「廠商已出、這家店還沒入的」)、哪幾行還沒選品號、合計怎麼算。

export const MAX_QTY = 99999;

export interface ReceiveProduct {
  id: number;
  sku: string;
  name: string;
  is_active: boolean;
}

export interface ReceiveLine {
  key: string;
  sku: string;
  spec_id: number | null;
  spec_label: string;
  name: string;
  unit: string;
  pack_qty: number;
  /** 瑕疵補發的免費列:數量照入、不計價 */
  is_reissue: boolean;
  qty: number;
  shipped_qty: number;
  received_qty: number;
  remaining_qty: number;
  suggested_qty: number;
  unit_price: string;
  /** 這個料號已經對到店裡哪個品號(null = 還沒對過:這次選了就記住;對照也可以先在「對照」那一頁連好) */
  product: ReceiveProduct | null;
}

export interface ReceivePlan {
  order: number;
  vendor_order_no: string;
  vendor_status: string;
  vendor_logistics_status: string;
  vendor_tracking_no: string;
  payment_method: string;
  lines: ReceiveLine[];
  shipping_fee: string;
  freight_into_cost: boolean;
  freight_left: string;
  supplier: { id: number; name: string } | null;
  issue_note: string;
}

export interface PickedProduct {
  id: number;
  label: string;
}

/**
 * 這一次入庫填到一半的樣子。`requestKey` 整個面板開著的期間不換:沒有答覆時再按一次,不會入兩次。
 * `product` = 這個人自己挑的品號;`repick` = 哪幾行按了「改」(打開讓人重挑)。
 * **已經對到品號、又沒按「改」的那一行,入到哪裡一律看廠商這張單現在回的(`chosen`),不看草稿** ——
 * 被擋下來之後這張單會重抓,對照可能已經被別人改過:畫面寫的是新的,送出去的也必須是新的。
 */
export interface ReceiveDraft {
  requestKey: string;
  qty: Record<string, number>;
  product: Record<string, PickedProduct>;
  repick: Record<string, true>;
  note: string;
}

/** 框裡打的字 → 數量。不是 0 到上限之間的整數就當成 0(這一行這次不入)。 */
export function qtyFrom(raw: unknown): number {
  const text = typeof raw === "number" ? String(raw) : typeof raw === "string" ? raw.trim() : "";
  if (!/^\d{1,5}$/.test(text)) return 0;
  return Number(text);
}

/**
 * 打開面板時:數量帶「廠商已出、這家店還沒入的」。**品號不抄進草稿**:對過的那幾行入到哪裡每一次都看這張單現在回的(`chosen`);
 * 草稿的 `product` 只放這個人自己挑的 —— 抄進來的話,對照被別人解除之後(重抓變成還沒對過)那一格會留著舊的品號,看起來像他挑的。
 */
export function startDraft(plan: ReceivePlan, requestKey: string): ReceiveDraft {
  const qty: Record<string, number> = {};
  for (const line of plan.lines) {
    if (line.suggested_qty > 0) qty[line.key] = line.suggested_qty;
  }
  return { requestKey, qty, product: {}, repick: {}, note: plan.issue_note };
}

/** 這一行這次入到哪個品號(null = 還沒選)。對過、沒按「改」的 → 現在的對照;按了「改」的、還沒對過的 → 這個人挑的。 */
export function chosen(line: Pick<ReceiveLine, "key" | "product">, draft: ReceiveDraft): PickedProduct | null {
  if (line.product !== null && !draft.repick[line.key]) return { id: line.product.id, label: line.product.name };
  return draft.product[line.key] ?? null;
}

/** 按了「改」:這一行打開讓人重挑,框裡先帶**現在**對到的那一個(不是打開面板那時候的)。 */
export function withRepick(draft: ReceiveDraft, line: Pick<ReceiveLine, "key" | "product">): ReceiveDraft {
  const product = { ...draft.product };
  if (line.product !== null) product[line.key] = { id: line.product.id, label: line.product.name };
  return { ...draft, product, repick: { ...draft.repick, [line.key]: true } };
}

export function withQty(draft: ReceiveDraft, key: string, n: number): ReceiveDraft {
  const qty = { ...draft.qty };
  const clean = Number.isInteger(n) ? Math.min(Math.max(n, 0), MAX_QTY) : 0;
  if (clean > 0) qty[key] = clean;
  else delete qty[key];
  return { ...draft, qty };
}

export function withProduct(draft: ReceiveDraft, key: string, picked: PickedProduct | null): ReceiveDraft {
  const product = { ...draft.product };
  if (picked) product[key] = picked;
  else delete product[key];
  return { ...draft, product };
}

/** 兩顆「一次帶好」:只帶廠商已出的 / 帶整張還沒入的(貨到齊了、廠商還沒按出貨)。品號與備註不動。 */
export function fill(plan: ReceivePlan, draft: ReceiveDraft, how: "shipped" | "remaining"): ReceiveDraft {
  const qty: Record<string, number> = {};
  for (const line of plan.lines) {
    const n = how === "shipped" ? line.suggested_qty : Math.max(line.remaining_qty, 0);
    if (n > 0) qty[line.key] = n;
  }
  return { ...draft, qty };
}

/**
 * 這一行這次要入的數量算哪一種:
 * none 不入 / ok / early 比廠商已出的多(只提醒:貨可能已經在店裡、廠商還沒按出貨)/ over 比還沒入的多(不行)。
 */
export type LineState = "none" | "ok" | "early" | "over";

export function lineState(line: ReceiveLine, qty: number): LineState {
  if (!qty) return "none";
  if (qty > line.remaining_qty) return "over";
  if (qty > Math.max(line.shipped_qty - line.received_qty, 0)) return "early";
  return "ok";
}

/**
 * 送給伺服器的一行。`was` = **畫面上這一行原本對到誰**(商品編號;null = 畫面上是還沒對過)。
 * 伺服器拿它跟現在的對照比:不一樣 = 這個畫面是舊的(對照剛被別人改掉或解除)→ 不入、對照也不動。
 * `product` 跟 `was` 不一樣 = 這個人按了「改」換成別的(或第一次挑),對照跟著換。
 */
export interface ReceiveSend {
  key: string;
  qty: number;
  product: number;
  was: number | null;
}

export interface ReceiveSummary {
  lines: ReceiveSend[];
  pieces: number;
  /** 這一次的貨款(廠商單價 × 數量;免費補發是 0;不含運費) */
  amount: number;
  /** 要入、但還沒選品號的那幾行(品名) */
  unmapped: string[];
  /** 比還沒入的多的那幾行(品名) */
  over: string[];
  /** 比廠商已出的多(只提醒) */
  early: number;
}

export function lineTitle(line: Pick<ReceiveLine, "name" | "spec_label">): string {
  return [line.name, line.spec_label].filter(Boolean).join(" ");
}

/** 草稿對上廠商這張單**現在**的每一行。草稿裡有、單上已經沒有的行直接不算(廠商改過單)。 */
export function summarize(plan: ReceivePlan, draft: ReceiveDraft): ReceiveSummary {
  const out: ReceiveSummary = { lines: [], pieces: 0, amount: 0, unmapped: [], over: [], early: 0 };
  for (const line of plan.lines) {
    const qty = draft.qty[line.key] ?? 0;
    const state = lineState(line, qty);
    if (state === "none") continue;
    out.pieces += qty;
    out.amount += line.is_reissue ? 0 : Number(line.unit_price) * qty;
    if (state === "over") out.over.push(lineTitle(line));
    if (state === "early") out.early += 1;
    const picked = chosen(line, draft);
    if (!picked) out.unmapped.push(lineTitle(line));
    else out.lines.push({ key: line.key, qty, product: picked.id, was: line.product?.id ?? null });
  }
  return out;
}

/** 為什麼現在不能按「確認入庫」(null = 可以)。 */
export function blocked(sum: ReceiveSummary): string | null {
  if (sum.pieces === 0) return "這一次沒有要入庫的東西";
  if (sum.over.length > 0) return `比還沒入庫的多:${sum.over.join("、")}`;
  if (sum.unmapped.length > 0) return `還沒選品號:${sum.unmapped.join("、")}`;
  return null;
}

export interface ReceiptRow {
  id: number;
  purchase_order: number;
  purchase_order_no: string;
  is_void: boolean;
  total_cost: string;
  freight: string;
  qty: number;
  created_at: string;
  created_by: string;
}

/** 紀錄那一欄:這張叫貨單已經入了幾個(作廢的進貨單不算)。叫了幾個只有從這裡叫的才知道。 */
export function receivedText(order: { items: { qty: number }[]; receipts: ReceiptRow[] }): string {
  const got = order.receipts.filter((r) => !r.is_void).reduce((sum, r) => sum + r.qty, 0);
  const ordered = order.items.reduce((sum, i) => sum + i.qty, 0);
  if (ordered > 0) return `${got} / ${ordered}`;
  return got > 0 ? String(got) : "";
}

/** 能不能打開到貨入庫:只有確定成立的單(不確定的要先「再送一次」確認)。入了幾個、還能入幾個由伺服器照廠商現在的單算。 */
export function mayReceive(order: { state: string }): boolean {
  return order.state === "placed";
}

/**
 * 按了「確認入庫」、還不知道結果的那一次(複審 2026-10-10:入庫成功但回應沒回來,關掉面板再開會換一把新鑰匙、
 * 同一批貨再入一次)。**送出之前先記在瀏覽器裡**(一張叫貨單一格);知道結果才清掉。
 * 還記著的時候,面板只給「再送一次」:同一把鑰匙、同樣的內容 —— 入過了伺服器回同一次,沒入過就是這一次入。
 */
export interface PendingReceive {
  requestKey: string;
  lines: ReceiveSend[];
  pieces: number;
  note: string;
}

export function pendingSlot(orderId: number): string {
  return `mp_pos_vendor_receive_${orderId}`;
}

export function pendingOf(draft: ReceiveDraft, sum: ReceiveSummary): PendingReceive {
  return { requestKey: draft.requestKey, lines: sum.lines, pieces: sum.pieces, note: draft.note };
}

export function pendingText(pending: PendingReceive): string {
  return JSON.stringify(pending);
}

const whole = (n: unknown, min: number): n is number => typeof n === "number" && Number.isInteger(n) && n >= min;

/** 瀏覽器裡記的那一格 → 還不知道結果的那一次。讀不懂的一律當成沒有(不拿壞掉的內容去入庫)。 */
export function pendingFrom(raw: string | null | undefined): PendingReceive | null {
  if (!raw) return null;
  let d: unknown;
  try {
    d = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!d || typeof d !== "object") return null;
  const p = d as Partial<PendingReceive>;
  if (typeof p.requestKey !== "string" || !/^[A-Za-z0-9_-]{8,50}$/.test(p.requestKey)) return null;
  if (!Array.isArray(p.lines) || p.lines.length === 0) return null;
  const lines: PendingReceive["lines"] = [];
  for (const l of p.lines as unknown[]) {
    const row = l as { key?: unknown; qty?: unknown; product?: unknown; was?: unknown } | null;
    if (!row || typeof row.key !== "string" || !row.key || !whole(row.qty, 1) || !whole(row.product, 1)) return null;
    // 「畫面上原本對到誰」要原樣留著:再送一次送的必須是同一份。這一版之前記下來的沒有這一格 = 當成還沒對過
    const was = row.was ?? null;
    if (was !== null && !whole(was, 1)) return null;
    lines.push({ key: row.key, qty: row.qty, product: row.product, was });
  }
  return {
    requestKey: p.requestKey,
    lines,
    pieces: lines.reduce((sum, l) => sum + l.qty, 0),
    note: typeof p.note === "string" ? p.note : "",
  };
}

/**
 * 伺服器對「確認入庫」的答覆算哪一種:
 * done 入了(這一次,或同一把鑰匙之前那一次)/ refused 明確沒有入 / unknown 不知道(沒連到、逾時、伺服器出錯)。
 * 只有 unknown 要繼續記著。`status` = HTTP 狀態碼;沒有連到伺服器給 null。
 *
 * `resend` = 這是在確認「上一次有沒有入」(上一次沒有拿到答覆)。這時候被擋不一定代表上一次沒入:
 * 沒登入(401)、沒有權限(403)、找不到(404)是伺服器**還沒查這把鑰匙**就擋的 —— 上一次可能早就入了(複審第二輪:
 * 入庫成功、回應沒回來 → 這個人的權限被關掉 → 再送一次回 403 → 當成沒入 → 權限開回來之後同一批貨再入一次)。
 * 只有 400 / 422 是伺服器查過這把鑰匙(沒有入過)之後才講的「不行」,才算明確沒有入。
 * 第一次送(鑰匙是新的)被擋,任何 4xx 都是這一次自己被擋,明確沒有入。
 */
export type ReceiveOutcome = "done" | "refused" | "unknown";

export function receiveOutcome(status: number | null, resend: boolean): ReceiveOutcome {
  if (status === null) return "unknown";
  if (status >= 200 && status < 300) return "done";
  if (resend) return status === 400 || status === 422 ? "refused" : "unknown";
  if (status >= 400 && status < 500 && status !== 408 && status !== 409 && status !== 429) return "refused";
  return "unknown";
}

/** 新的一把入庫鑰匙(每開一次面板一把)。 */
export function newReceiveKey(random: () => string = () => crypto.randomUUID()): string {
  return `recv-${random().replace(/[^A-Za-z0-9]/g, "").slice(0, 24)}`;
}
