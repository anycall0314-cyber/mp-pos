// 盤點在畫面這一側的規則(跑法:npm test)。怎麼算差異、什麼時候動庫存、誰看得到帳上數量,
// 全部由伺服器決定(backend/apps/inventory/stockcount.py、stockcount_views.py);這裡只管每一格怎麼寫、核准時送什麼。
//
// owner 2026-10-12 定的三條:差異要管理員調整與核准(盤的人只記數到的,核准才動庫存)、帶序號的逐台刷、盤點中可以繼續開單。
// 盲盤:帳上數量、差異、金額只有管理員的回應裡有(這裡拿不到就不會畫)。
import { normalizeCode } from "./deviceCodes.ts";
import { money } from "./money.ts";

export type CountStatus = "counting" | "submitted" | "approved" | "void";

export interface CountSummary {
  id: number;
  no: string;
  warehouse: { id: number; name: string };
  /** 只盤哪幾個類別;空的 = 全部 */
  categories: string[];
  status: CountStatus;
  status_label: string;
  note: string;
  /** 送出的人表明「手機全部刷完了」(有才算手機少了哪幾台) */
  phones_done: boolean;
  created_at: string;
  created_by: string;
  submitted_at: string | null;
  approved_at: string | null;
  lines: number;
  scans: number;
}

export interface CountLine {
  id: number;
  product: { id: number; sku: string; name: string };
  counted_qty: number;
  counted_at: string;
  /** 開盤之後到輸入那一刻出了幾個、進了幾個(有數字 = 數完到輸入之間有動過) */
  moved_out: number;
  moved_in: number;
  // 以下只有管理員的回應裡有
  book_qty?: number;
  diff?: number;
  adjust_qty?: number | null;
  skipped?: boolean;
  reason?: string;
  unit_cost?: string;
  amount?: string;
}

export interface CountScan {
  id: number;
  code: string;
  /** 系統認不認得這個碼 */
  known: boolean;
  name: string;
}

export interface CountMissing {
  id: number;
  serial_no: string;
  name: string;
  cost: string;
  skipped: boolean;
  reason: string;
  /** 核准時真的標成盤虧了 */
  applied: boolean;
  found: boolean;
  /** 現在帳上還在這家門市在庫(不在的核准時不會標成盤虧) */
  still_here: boolean;
}

export interface CountExtra {
  id: number;
  code: string;
  name: string;
  state: string;
}

/** 系統不認得的碼(第一次盤點入庫):舊系統的機器清單對得到的帶著舊品號、舊品名、成本、售價。只有管理員的回應裡有。 */
export interface CountNew {
  id: number;
  code: string;
  old_code: string;
  old_name: string;
  /** 核准時分組用:舊品名的前三段(空的 = 舊系統清單上沒有) */
  group: string;
  old_cost: string | null;
  old_price: string | null;
  /** 先帶出來的品號(舊品號對照過的)/ 核准之後是入的那一個;unit = 逐台記售價的 */
  product: { id: number; sku: string; name: string; unit: boolean } | null;
  unit_cost: string | null;
  unit_price: string | null;
  skipped: boolean;
  reason: string;
  /** 核准時入庫了 */
  added: boolean;
}

/** 手機走動盤點的一支手機:waiting 等手機掃 / expired QR 過期 / connected 連著 / idle 太久沒刷 / ended 結束了 */
export interface CountPhone {
  id: number;
  label: string;
  status: "waiting" | "expired" | "connected" | "idle" | "ended";
}

/** 手機在「配件」模式刷到、系統不認得的碼:要指定配件或寫原因不入,才能送出 */
export interface CountUnknown {
  id: number;
  code: string;
  times: number;
  label: string;
  product: { id: number; sku: string; name: string } | null;
  skipped: boolean;
  reason: string;
  resolved: boolean;
}

/** 這家門市送廠商換貨、還沒換回來的(盤點不用刷,但另外列出來;每個人都看得到) */
export interface CountVendor {
  id: number;
  serial_no: string;
  name: string;
  supplier: string;
  days: number;
}

export interface CountDetail extends CountSummary {
  manager: boolean;
  /** 帳上有數量、還沒輸入的配件有幾樣(只有數字) */
  left: number;
  line_rows: CountLine[];
  scan_rows: CountScan[];
  phones?: CountPhone[];
  unknown_rows?: CountUnknown[];
  vendor_rows?: CountVendor[];
  /** 剛按「手機盤點」那一次回來才有:QR Code 的憑證(只在這一刻看得到) */
  pair?: { id: number; label: string; token: string; expires_at: string };
  missing_rows?: CountMissing[];
  extra_rows?: CountExtra[];
  new_rows?: CountNew[];
  amounts?: { lines: string; phones: string; total: string };
}

/** 舊系統清單上有、新系統還沒入庫的(管理員;沒有成本)。 */
export interface OldUnitsLeft {
  total: number;
  stores: { store: string; count: number }[];
  rows: { code: string; old_code: string; old_name: string; store: string; purchased_on: string | null }[];
}

/** 「還沒入庫」那一行:各家舊店幾台。 */
export function oldStoresText(left: Pick<OldUnitsLeft, "stores">): string {
  return left.stores.map((s) => `${s.store} ${s.count}`).join("　");
}

/** 範圍那一格:沒挑類別 = 全部。 */
export function scopeText(count: Pick<CountSummary, "categories">): string {
  return count.categories.length ? count.categories.join("、") : "全部";
}

/** 開盤之後有動過:「出 2 進 1」;都沒有 = 空的(不寫 0)。 */
export function movedHint(line: Pick<CountLine, "moved_out" | "moved_in">): string {
  return [line.moved_out ? `出 ${line.moved_out}` : "", line.moved_in ? `進 ${line.moved_in}` : ""].filter(Boolean).join(" ");
}

/** 差多少:多的寫 +2、少的寫 -1、一樣寫 0。 */
export function signed(n: number): string {
  return n > 0 ? `+${n}` : String(n);
}

/** 單號旁邊那一行:盤了幾樣、刷了幾台;還在盤的才寫還有幾樣沒盤。 */
export function progressText(detail: Pick<CountDetail, "line_rows" | "scan_rows" | "left" | "status">): string {
  const parts = [`配件 ${detail.line_rows.length} 樣`, `手機 ${detail.scan_rows.length} 台`];
  if (detail.status === "counting") parts.push(`未盤 ${detail.left} 樣`);
  return parts.join("　");
}

/** 管理員那一排金額:配件、手機、合計(少的是負的)。 */
export function amountCards(amounts: NonNullable<CountDetail["amounts"]>): { label: string; value: string }[] {
  return [
    { label: "配件", value: money(amounts.lines) },
    { label: "手機", value: money(amounts.phones) },
    { label: "合計", value: money(amounts.total) },
  ];
}

/** 多出來的那一台怎麼寫:系統不認得的寫「不認得」,認得的寫品名與帳上的狀態。 */
export function extraText(extra: Pick<CountExtra, "name" | "state">): string {
  return extra.name ? `${extra.name} ${extra.state}`.trim() : "不認得";
}

/** 少的那一台現在的情況:核准之後看有沒有標成盤虧 / 找回;還沒核准看它還在不在庫。 */
export function missingText(m: Pick<CountMissing, "applied" | "found" | "skipped" | "still_here">, approved: boolean): string {
  if (m.found) return "已找回";
  if (m.applied) return "盤虧";
  if (approved) return m.skipped ? "不調" : "已不在庫";
  return m.still_here ? "" : "已不在庫";
}

/** 管理員在畫面上改的:調整量(字,空的 = 照差異)、先不調、原因。 */
export interface LineEdit {
  adjust: string;
  skipped: boolean;
  reason: string;
}

export interface MissingEdit {
  skipped: boolean;
  reason: string;
}

/** 系統不認得的那一台,管理員在畫面上定的:入哪個品號、成本、售價(逐台記售價的才有)、不入。 */
export interface NewEdit {
  product: CountNew["product"];
  cost: string;
  price: string;
  skipped: boolean;
  reason: string;
}

/** 金額照伺服器給的字放進輸入框:整數就不帶「.00」。 */
export function plainAmount(text: string | null | undefined): string {
  if (text === null || text === undefined) return "";
  return text.replace(/\.00$/, "");
}

/** 還沒動過的那一台:先帶出來的品號、舊系統的成本與售價。 */
export function newEditOf(row: CountNew, edits: Record<number, NewEdit | undefined>): NewEdit {
  return edits[row.id] ?? {
    product: row.product,
    cost: plainAmount(row.unit_cost ?? row.old_cost),
    price: plainAmount(row.unit_price ?? row.old_price),
    skipped: false,
    reason: "",
  };
}

/** 照舊品名分組(紅隊:同一組一次指定型號)。照出現的順序;舊系統清單上沒有的一組。 */
export function newGroups(rows: CountNew[]): { key: string; label: string; rows: CountNew[] }[] {
  const out: { key: string; label: string; rows: CountNew[] }[] = [];
  for (const row of rows) {
    const key = row.group;
    let group = out.find((g) => g.key === key);
    if (!group) {
      group = { key, label: key || "舊系統沒有", rows: [] };
      out.push(group);
    }
    group.rows.push(row);
  }
  return out;
}

/** 勾著的那幾台換成同一個品號(售價只有逐台記售價的品號才留著)。 */
export function assignProduct(
  rows: CountNew[],
  picked: Set<number>,
  product: NonNullable<CountNew["product"]>,
  edits: Record<number, NewEdit | undefined>,
): Record<number, NewEdit | undefined> {
  const next = { ...edits };
  for (const row of rows) {
    if (!picked.has(row.id)) continue;
    const edit = newEditOf(row, edits);
    next[row.id] = { ...edit, product, skipped: false, price: product.unit ? edit.price : "" };
  }
  return next;
}

const AMOUNT = /^\d{1,12}(\.\d{1,2})?$/;

/**
 * 核准時送的內容。調整量空的 = 不送(伺服器照「數到的 − 當時帳上的」調);有填就要是整數,不是的話回一句話、不送。
 */
export function approveBody(
  detail: Pick<CountDetail, "line_rows" | "missing_rows" | "new_rows">,
  lineEdits: Record<number, LineEdit | undefined>,
  missingEdits: Record<number, MissingEdit | undefined>,
  newEdits: Record<number, NewEdit | undefined> = {},
): { error: string } | { lines: Record<string, object>; missing: Record<string, object>; extras: Record<string, object> } {
  const lines: Record<string, object> = {};
  for (const row of detail.line_rows) {
    const edit = lineEdits[row.id];
    if (!edit) continue;
    const one: { adjust_qty?: number; skipped: boolean; reason: string } = { skipped: edit.skipped, reason: edit.reason.trim() };
    const text = edit.adjust.trim();
    if (text !== "") {
      if (!/^[+-]?\d+$/.test(text)) return { error: `「${row.product.name}」的調整量要是整數` };
      one.adjust_qty = Number(text);
    }
    lines[String(row.id)] = one;
  }
  const missing: Record<string, object> = {};
  for (const row of detail.missing_rows ?? []) {
    const edit = missingEdits[row.id];
    if (edit) missing[String(row.id)] = { skipped: edit.skipped, reason: edit.reason.trim() };
  }
  // 系統不認得的:有品號、沒勾不入的才入庫(伺服器那邊沒送的一律不入)。成本一定要填(沒有就 0),售價可以空著
  const extras: Record<string, object> = {};
  for (const row of detail.new_rows ?? []) {
    const edit = newEditOf(row, newEdits);
    if (edit.skipped || !edit.product) {
      extras[String(row.id)] = { skipped: true, reason: edit.reason.trim() };
      continue;
    }
    const cost = edit.cost.replace(/,/g, "").trim();
    if (!AMOUNT.test(cost)) return { error: `${row.code} 的成本要填(沒有就填 0)` };
    const one: { product: number; unit_cost: string; unit_price?: string; reason: string } = {
      product: edit.product.id, unit_cost: cost, reason: edit.reason.trim(),
    };
    const price = edit.price.replace(/,/g, "").trim();
    if (edit.product.unit && price !== "") {
      if (!AMOUNT.test(price)) return { error: `${row.code} 的售價要是數字` };
      one.unit_price = price;
    }
    extras[String(row.id)] = one;
  }
  return { lines, missing, extras };
}

/** 系統不認得的那一台在核准之後怎麼寫:入了 / 不入。 */
export function newResult(row: Pick<CountNew, "added" | "skipped">): string {
  return row.added ? "已入" : "不入";
}

/** 數量那一格打的字 → 0 以上的整數;不是就 null(不送)。 */
export function countedQty(text: string): number | null {
  const t = text.trim();
  return /^\d{1,7}$/.test(t) ? Number(t) : null;
}

/**
 * 配件那一格刷到 / 打完 Enter 的字,是不是這個商品的品號或條碼(完全相同)。
 * 條碼槍打得比搜尋快:只有這種才直接選起來,其他的要人看著下拉挑(`ScanBox`)。舊貼紙印的是舊品號 = 商品的條碼。
 */
export function sameCode(p: { sku: string; barcode?: string | null }, text: string): boolean {
  const key = normalizeCode(text);
  return !!key && (normalizeCode(p.sku) === key || (!!p.barcode && normalizeCode(p.barcode) === key));
}

/** 這個商品可不可以在配件那一格打數量;不行回一句話(記在「沒加入」)。伺服器一樣會擋(`stockcount._countable`)。 */
export function notCountable(p: { name: string; requires_serial: boolean; is_virtual: boolean }): string | null {
  if (p.requires_serial) return `「${p.name}」是帶序號的,請在手機那一格刷`;
  if (p.is_virtual) return `「${p.name}」沒有庫存,不用盤`;
  return null;
}

/**
 * 配件那一格又選到一個商品(刷的或挑的):可不可以換成它。不行回一句話 —— 那一個碼記在「沒加入」(複審 P1):
 * 條碼槍連刷兩張、搜尋還沒回來時,第二張不能默默蓋掉還沒記下數量的第一張。同一個商品再選一次照收。
 */
export function pickProblem(
  pending: { id: number; name: string } | null,
  next: { id: number; name: string; requires_serial: boolean; is_virtual: boolean },
): string | null {
  const why = notCountable(next);
  if (why) return why;
  if (pending && pending.id !== next.id) return `「${pending.name}」還沒記下`;
  return null;
}

/** 刷到的配件這張單已經記過:數量那一格先放原本記的(重新輸入 = 整個換掉,要讓人看見) */
export function recordedQty(rows: Pick<CountLine, "product" | "counted_qty">[], productId: number): string {
  const row = rows.find((r) => r.product.id === productId);
  return row ? String(row.counted_qty) : "";
}


/** 有沒有手機在走動盤點(等掃 / 連著):有的話盤點單要一直重抓,手機刷進來的數量才看得到。 */
export function phonesLive(detail: Pick<CountDetail, "phones" | "status"> | undefined): boolean {
  return !!detail && detail.status === "counting" && (detail.phones ?? []).some((p) => p.status === "waiting" || p.status === "connected");
}

/** 一支手機的狀態寫成字。 */
export function phoneStatusText(status: CountPhone["status"]): string {
  return { waiting: "等掃", expired: "過期", connected: "連著", idle: "閒置", ended: "結束" }[status];
}

/** 手機掃的網址:憑證放在 # 後面(不會進伺服器的紀錄,也不會被帶到別的網站)。 */
export function phoneCountUrl(origin: string, token: string): string {
  return `${origin}/m/count#${token}`;
}

/** 還沒處理的沒對到的碼有幾個(有的話不能送出)。 */
export function unknownLeft(rows: Pick<CountUnknown, "resolved">[] | undefined): number {
  return (rows ?? []).filter((r) => !r.resolved).length;
}
