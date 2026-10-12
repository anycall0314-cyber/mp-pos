// 盤點在畫面這一側的規則(跑法:npm test)。怎麼算差異、什麼時候動庫存、誰看得到帳上數量,
// 全部由伺服器決定(backend/apps/inventory/stockcount.py、stockcount_views.py);這裡只管每一格怎麼寫、核准時送什麼。
//
// owner 2026-10-12 定的三條:差異要管理員調整與核准(盤的人只記數到的,核准才動庫存)、帶序號的逐台刷、盤點中可以繼續開單。
// 盲盤:帳上數量、差異、金額只有管理員的回應裡有(這裡拿不到就不會畫)。
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

export interface CountDetail extends CountSummary {
  manager: boolean;
  /** 帳上有數量、還沒輸入的配件有幾樣(只有數字) */
  left: number;
  line_rows: CountLine[];
  scan_rows: CountScan[];
  missing_rows?: CountMissing[];
  extra_rows?: CountExtra[];
  amounts?: { lines: string; phones: string; total: string };
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

/**
 * 核准時送的內容。調整量空的 = 不送(伺服器照「數到的 − 當時帳上的」調);有填就要是整數,不是的話回一句話、不送。
 */
export function approveBody(
  detail: Pick<CountDetail, "line_rows" | "missing_rows">,
  lineEdits: Record<number, LineEdit | undefined>,
  missingEdits: Record<number, MissingEdit | undefined>,
): { error: string } | { lines: Record<string, object>; missing: Record<string, object> } {
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
  return { lines, missing };
}

/** 數量那一格打的字 → 0 以上的整數;不是就 null(不送)。 */
export function countedQty(text: string): number | null {
  const t = text.trim();
  return /^\d{1,7}$/.test(t) ? Number(t) : null;
}
