// 廠商叫貨(膜總裁)在畫面這一側的規則。跑法:npm test。
// 伺服器決定價錢、一包幾片、送給廠商什麼;這裡只管:包數怎麼填、合計怎麼算、
// 這張叫貨單的鑰匙與「送出去了還不知道結果」怎麼記(同一把鑰匙再送不會變成兩張)。
import { money } from "./money.ts";

export const MAX_PACKS = 9999;

export interface CatalogRow {
  key: string;
  sku: string;
  name: string;
  kind: string;
  size: string;
  unit: string;
  pack_qty: number;
  spec_id: number | null;
  spec_label: string;
  /** null = 這個帳號沒有這一項的報價(不能叫) */
  unit_price: string | null;
  pack_price: string | null;
}

/** 購物車:哪一列叫幾包。0 包的不留。 */
export type Cart = Record<string, number>;

/** 框裡打的字 → 包數。不是 0 到上限之間的整數就當成 0(不叫)。 */
export function packsFrom(raw: unknown): number {
  const text = typeof raw === "number" ? String(raw) : typeof raw === "string" ? raw.trim() : "";
  if (!/^\d{1,4}$/.test(text)) return 0;
  return Number(text);
}

export function withPacks(cart: Cart, key: string, packs: number): Cart {
  const next = { ...cart };
  const n = Number.isInteger(packs) ? Math.min(Math.max(packs, 0), MAX_PACKS) : 0;
  if (n > 0) next[key] = n;
  else delete next[key];
  return next;
}

export interface CartLine {
  row: CatalogRow;
  packs: number;
  /** 包數 × 一包幾片:送給廠商的是這個 */
  pieces: number;
  amount: number;
}

export interface CartSummary {
  lines: CartLine[];
  packs: number;
  pieces: number;
  amount: number;
  /** 購物車裡有、但廠商現在的清單沒有(或沒有報價)的那幾列:不能送 */
  gone: string[];
}

/**
 * 購物車對上廠商**現在**的清單。順序照清單(畫面上看到的順序)。
 * 清單換過之後不在了、或變成沒有報價的,列在 gone —— 不能默默丟掉(人以為叫了)也不能照送(伺服器會擋)。
 */
export function summarize(cart: Cart, rows: CatalogRow[]): CartSummary {
  const byKey = new Map(rows.map((r) => [r.key, r]));
  const lines: CartLine[] = [];
  for (const row of rows) {
    const packs = cart[row.key] ?? 0;
    if (packs <= 0 || row.unit_price === null) continue;
    const pieces = packs * row.pack_qty;
    lines.push({ row, packs, pieces, amount: Number(row.unit_price) * pieces });
  }
  const gone = Object.keys(cart).filter((key) => {
    const row = byKey.get(key);
    return cart[key] > 0 && (!row || row.unit_price === null);
  });
  return {
    lines,
    packs: lines.reduce((s, l) => s + l.packs, 0),
    pieces: lines.reduce((s, l) => s + l.pieces, 0),
    amount: lines.reduce((s, l) => s + l.amount, 0),
    gone,
  };
}

export interface RowFilter {
  text: string;
  /** "" = 全部 */
  kind: string;
  pickedOnly: boolean;
}

/** 廠商的清單有哪幾種(照出現的順序)。 */
export function kindsOf(rows: CatalogRow[]): string[] {
  const out: string[] = [];
  for (const r of rows) if (r.kind && !out.includes(r.kind)) out.push(r.kind);
  return out;
}

/**
 * 清單太長(膜速箱一個規格一列)時用來找的:打的每一段字都要在 品名 / 規格 / 料號 / 尺寸 裡(不分大小寫);
 * 「只看已選」留下購物車裡有的。只是藏起來,不影響合計與送出(藏起來的已選照樣算)。
 */
export function filterRows(rows: CatalogRow[], filter: RowFilter, cart: Cart): CatalogRow[] {
  const words = filter.text.toLowerCase().split(/\s+/).filter(Boolean);
  return rows.filter((r) => {
    if (filter.kind && r.kind !== filter.kind) return false;
    if (filter.pickedOnly && !((cart[r.key] ?? 0) > 0)) return false;
    const hay = `${r.name} ${r.spec_label} ${r.sku} ${r.size}`.toLowerCase();
    return words.every((w) => hay.includes(w));
  });
}

/** 送給伺服器的明細:只有鍵與包數。價錢、品名、一包幾片伺服器自己跟廠商要。 */
export function linesToSend(summary: CartSummary): { key: string; packs: number }[] {
  return summary.lines.map((l) => ({ key: l.row.key, packs: l.packs }));
}

/** 「2 包 = 50 片」:店員講的是包,廠商收的是片,兩個都寫出來。 */
export function packsText(packs: number, pieces: number, unit: string): string {
  return `${packs} 包 = ${pieces} ${unit || "片"}`;
}

export function rowTitle(row: { name: string; spec_label: string; size: string }): string {
  return [row.name, row.spec_label, row.size].filter(Boolean).join(" ");
}

// ── 這張叫貨單的鑰匙與草稿 ──────────────────────────────────────────────────
export interface OrderDraft {
  /** 這張叫貨單的鑰匙:從開始填到確定成立(或確定沒成立)都是同一把 */
  requestKey: string;
  cart: Cart;
  payment_method: string;
  delivery_method: string;
  note: string;
  /** 送出去了、還不知道有沒有成立:整張鎖住,只能用同一把鑰匙再送 */
  pending: boolean;
}

export function newRequestKey(random: () => string = defaultRandom): string {
  return `vo-${random()}`.slice(0, 50);
}

function defaultRandom(): string {
  const c = globalThis.crypto;
  if (c && typeof c.randomUUID === "function") return c.randomUUID();
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}

export function emptyDraft(random?: () => string): OrderDraft {
  return { requestKey: newRequestKey(random), cart: {}, payment_method: "", delivery_method: "", note: "", pending: false };
}

/** 存在瀏覽器裡的草稿讀回來;壞掉的、缺東西的一律當成沒有(換一張新的)。 */
export function draftFrom(raw: unknown, random?: () => string): OrderDraft {
  const d = raw as Partial<OrderDraft> | null;
  if (!d || typeof d !== "object" || typeof d.requestKey !== "string" || !/^[A-Za-z0-9_-]{8,50}$/.test(d.requestKey))
    return emptyDraft(random);
  const cart: Cart = {};
  if (d.cart && typeof d.cart === "object")
    for (const [key, packs] of Object.entries(d.cart))
      if (typeof packs === "number" && Number.isInteger(packs) && packs > 0 && packs <= MAX_PACKS) cart[key] = packs;
  return {
    requestKey: d.requestKey,
    cart,
    payment_method: typeof d.payment_method === "string" ? d.payment_method : "",
    delivery_method: typeof d.delivery_method === "string" ? d.delivery_method : "",
    note: typeof d.note === "string" ? d.note.slice(0, 200) : "",
    pending: d.pending === true,
  };
}

/**
 * 按下「送出」的那一刻、請求還沒出去之前先做這件事:把草稿標成「送出去了還不知道結果」並存起來。
 * 不先存的話:廠商已經成立、回應還在路上時重新整理頁面,畫面是沒鎖的;人改了內容再送,
 * 同一把鑰匙拿回來的是**原本那一張**,畫面卻說成功 —— 新改的其實沒有叫到(複審抓到的)。
 */
export function beforeSend(draft: OrderDraft): OrderDraft {
  return { ...draft, pending: true };
}

/**
 * 回來的那張「已成立」的單,是不是就是這張草稿的內容(每一列的包數都一樣)。
 * 不一樣 = 這把鑰匙先前已經成立過另一份(上一次送出其實成功了),現在這一份沒有送出去。
 *
 * **比的是草稿裡完整的購物車,不是照現在的清單篩過的那幾列**:叫了兩項、廠商成立了、回應沒回來,
 * 之後其中一項下架 —— 照現在的清單只剩一列,跟成立的那一張(兩列)對不起來,會被誤判成「這一份還沒送出」,
 * 人照著再送一次就重複叫了(複審第二輪抓到的)。草稿是空的(沒有東西可比)就不比。
 */
export function sameAsSent(
  cart: Cart,
  items: { sku: string; spec_id: number | null; packs: number }[],
): boolean {
  const mine = Object.entries(cart).filter(([, packs]) => packs > 0);
  if (mine.length === 0) return true;
  const got = new Map(items.map((i) => [i.spec_id === null ? i.sku : `${i.sku}#${i.spec_id}`, i.packs]));
  return mine.length === got.size && mine.every(([key, packs]) => got.get(key) === packs);
}

export type SendOutcome =
  /** 成立了:草稿收掉,下一張用新鑰匙 */
  | { kind: "placed" }
  /** 這把鑰匙成立的是先前送的另一份;畫面上現在這一份沒有送出:內容留著、換新鑰匙、不鎖 */
  | { kind: "other"; orderNo: string }
  /** 明確沒有成立(伺服器或廠商擋下來):草稿留著、同一把鑰匙,改一改可以再送 */
  | { kind: "refused"; message: string }
  /** 不知道:整張鎖住,只能用同一把鑰匙再送一次 */
  | { kind: "unknown"; message: string };

/**
 * 送出之後怎麼辦。`status` = 我們自己伺服器回的 HTTP 狀態(沒有連到是 0);`state` = 回來那張叫貨單的狀況。
 * 409 = 那一張正在送出:也是「不知道」,等一下再送一次。其餘 4xx = 明確沒成立。斷線 / 5xx = 不知道。
 */
export function outcomeOf(status: number, state: string | undefined, message: string): SendOutcome {
  if (status >= 200 && status < 300) {
    if (state === "placed") return { kind: "placed" };
    return { kind: "unknown", message: message || "不確定有沒有成立" };
  }
  if (status >= 400 && status < 500 && status !== 408 && status !== 409) return { kind: "refused", message };
  return { kind: "unknown", message: message || "沒有連到伺服器" };
}

export function afterSend(draft: OrderDraft, outcome: SendOutcome, random?: () => string): OrderDraft {
  if (outcome.kind === "other") return { ...draft, requestKey: newRequestKey(random), pending: false };
  if (outcome.kind === "placed") return { ...emptyDraft(random), payment_method: draft.payment_method, delivery_method: draft.delivery_method };
  if (outcome.kind === "refused") return { ...draft, pending: false };
  return { ...draft, pending: true };
}

/**
 * 清單上的時間:「10-10 15:29」,**這台電腦的時間**。伺服器給的是世界時間(…Z)或帶時區的字串,
 * 直接切字串會差八小時。看不懂的回空字串。
 */
export function whenText(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** 總額與運費:沒有值寫「—」(還不知道),不寫成 0。 */
export function amountText(value: string | null | undefined): string {
  return value === null || value === undefined || value === "" ? "—" : money(value);
}
