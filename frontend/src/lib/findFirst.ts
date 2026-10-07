/**
 * 「新增商品先找一次」那個框的規則(純函式,給 pages/products/FindFirstPanel 用;有測試)。
 *
 * 兩條:
 * 1. **沒查成功不能當成「沒有這個商品」**:還在找、查失敗、還沒找過,都不能往下建。
 * 2. **畫面上的候選一定是「框裡現在這句話」查出來的**:比較晚回來的舊回應不算數;
 *    字改過了,先前那一批候選只能看、不能選用,也不能拿它當「找過了」往下建。
 */
import { looksLikeImei } from "./deviceCodes.ts";

interface FoundProduct {
  id: number;
  sku: string;
  name: string;
  spec?: string;
  barcode?: string;
  category_name?: string;
  stock_qty?: number | null;
  is_active: boolean;
}

/** 候選的一列 */
export interface FoundRow<P extends FoundProduct = FoundProduct> {
  product: P;
  /** 為什麼找到它(只打品號 / 條碼片段找到的沒有) */
  reasons: string[];
  /** 跟打的字哪裡不一樣 */
  differences: string[];
}

interface Resolved<P extends FoundProduct> {
  product: P;
  /** related = 同機型但有差異(弱);其餘(條碼 / 叫法相同、特徵相符)是強的 */
  level: string;
  reasons: string[];
  differences: string[];
}

export type FindState<P extends FoundProduct = FoundProduct> =
  | { phase: "idle"; seq: number }
  | { phase: "loading"; seq: number; asked: string }
  | { phase: "done"; seq: number; asked: string; rows: FoundRow<P>[] }
  | { phase: "error"; seq: number; asked: string; message: string };

export const IDLE: FindState<never> = { phase: "idle", seq: 0 };

/** 框裡有字才找 */
export function askable(input: string): boolean {
  return input.trim().length > 0;
}

/** 開始找這句話。每找一次換一個號碼,回應要拿同一個號碼回來才算數 */
export function ask<P extends FoundProduct>(state: FindState<P>, input: string): FindState<P> {
  if (!askable(input)) return state;
  return { phase: "loading", seq: state.seq + 1, asked: input.trim() };
}

/** 查到了。不是現在這一次的回應(比較晚回來的舊回應)不算 */
export function settle<P extends FoundProduct>(
  state: FindState<P>,
  seq: number,
  rows: FoundRow<P>[],
): FindState<P> {
  if (state.phase !== "loading" || state.seq !== seq) return state;
  return { phase: "done", seq, asked: state.asked, rows };
}

/** 沒查成功。同樣只認現在這一次 */
export function fail<P extends FoundProduct>(
  state: FindState<P>,
  seq: number,
  message: string,
): FindState<P> {
  if (state.phase !== "loading" || state.seq !== seq) return state;
  return { phase: "error", seq, asked: state.asked, message };
}

/** 整個框清掉重來(關掉再開)。號碼接著往下走,關掉之前送出去的回應回來也不算 */
export function reset<P extends FoundProduct>(state: FindState<P>): FindState<P> {
  return { phase: "idle", seq: state.seq + 1 };
}

/**
 * 從照片面板按「使用此商品」的那一刻再核對一次:那顆按鈕是點開照片時給的,之後可能已經不算數了 ——
 * 框關掉了、又找了別的(號碼不同)、字改過。只要有一樣不對就不能選用。
 */
export function stillUsable<P extends FoundProduct>(
  state: FindState<P>,
  input: string,
  given: { seq: number; open: boolean },
): boolean {
  return given.open && state.seq === given.seq && state.phase === "done" && viewOf(state, input).canUse;
}

export interface FindView<P extends FoundProduct = FoundProduct> {
  rows: FoundRow<P>[];
  /** 候選是先前那句話的:看得到、不能選 */
  stale: boolean;
  /** 候選可以選用 */
  canUse: boolean;
  /** 可以往下建新的(這句話找過、而且查成功了) */
  canCreate: boolean;
  note: string;
}

/** 畫面上現在該是什麼樣子。input = 框裡現在的字 */
export function viewOf<P extends FoundProduct>(state: FindState<P>, input: string): FindView<P> {
  const off = { rows: [], stale: false, canUse: false, canCreate: false };
  if (state.phase === "idle") return { ...off, note: "" };
  if (state.phase === "loading") return { ...off, note: "尋找中…" };
  if (state.phase === "error") return { ...off, note: "沒有查成功,請再找一次" };
  if (input.trim() !== state.asked) {
    return { rows: state.rows, stale: true, canUse: false, canCreate: false, note: "內容改了,請再找一次" };
  }
  return {
    rows: state.rows,
    stale: false,
    canUse: true,
    canCreate: true,
    note: state.rows.length ? "" : "沒有找到",
  };
}

/** 一段字拆成一塊一塊:英文一塊、數字一塊、其他(中文、符號)一塊 */
function pieces(word: string): string[] {
  return word.match(/[a-z]+|[0-9]+|[^a-z0-9]+/g) ?? [];
}

// 數字前面可以是:最前面、不是數字也不是小數點的字、或「前面不是數字的小數點」(那個點不是小數的一部分)
const NUMBER_START = "(?:^|[^0-9.]|(?:^|[^0-9])\\.)";
// 數字後面不可以是:數字、或「後面接著數字的小數點」
const NUMBER_END = "(?![0-9]|\\.[0-9])";

/**
 * 接在數字後面的單位。分開打的「20 W」要併成一段「20W」再比(`queryWords`);
 * 不在這裡的英文(pro、max、plus…)不是單位,不併。
 */
const UNITS = new Set([
  "w", "v", "a", "ma", "mah", "g", "gb", "mb", "t", "tb", "m", "mm", "cm", "hz", "k", "d", "h", "吋",
]);
/** 同一個單位的兩種寫法:256G = 256GB、1T = 1TB(打哪一種都對得上另一種) */
const SAME_UNIT: Record<string, string> = { g: "gb?", gb: "gb?", t: "tb?", tb: "tb?" };

const escapeRe = (text: string) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/**
 * hay(小寫)裡有沒有 word 這一段字。不是單純的「包含」:
 * - **數字要是一整段**:word 開頭是數字,前面不能還是數字;結尾是數字,後面不能還是數字。
 *   `512` 不算在條碼 `4719512345678` 裡、`20w` 不算在 `120w` 裡、`12gb` 不算在 `512gb` 裡;`512gb`、`ip15` 裡的算。
 *   **小數是同一個數字**:`2.5d` 裡沒有 `5d`、也沒有單獨的 `2`(小數點前後都是數字時,兩邊是連在一起的)。
 * - **英文要從一個字的開頭對起**:word 開頭是英文,前面不能還是英文(`s25` 不算在 `plus 25w` 裡);後面可以還有(`pro` 對 `promax`)。
 * - **數字後面接的英文要是完整的**(單位、機型後綴):`1.2m` 不算在 `1.2mm` 裡、`13p` 不算在 `13pm` / `13pro` 裡;
 *   例外只有同一個單位的兩種寫法(`256g` = `256gb`、`1t` = `1tb`)。
 * - 英文與數字之間可以隔著空白 / 斜線 / 連字號:黏在一起打的 `iphone15` 對得上 `iPhone 15`。
 */
function hasWord(hay: string, word: string): boolean {
  const runs = pieces(word);
  if (!runs.length) return false;
  const first = runs[0];
  const last = runs[runs.length - 1];
  const before = /^[0-9]/.test(first) ? NUMBER_START : /^[a-z]/.test(first) ? "(?:^|[^a-z])" : "";
  // 最後一塊是英文、而且它前面那一塊是數字:這是接在數字後面的單位 / 後綴,要完整
  const suffix = runs.length >= 2 && /^[a-z]/.test(last) && /^[0-9]/.test(runs[runs.length - 2]);
  const parts = runs.map(escapeRe);
  if (suffix) parts[parts.length - 1] = SAME_UNIT[last] ?? parts[parts.length - 1];
  const after = /[0-9]$/.test(last) ? NUMBER_END : suffix ? "(?![a-z])" : "";
  return new RegExp(before + parts.join("[\\s/-]*") + after).test(hay);
}

/**
 * 打的字分成一段一段(小寫;空白、斜線、連字號分段)。
 * 數字後面隔著空白接一個單位(`20 W`、`1.2 M`、`256 G`)= 同一段:不併的話 `20` 會對到 `20V`、`W` 會對到旁邊的 `65W`,
 * 兩個不相干的規格拼成「字都對得上」。
 */
export function queryWords(asked: string): string[] {
  const raw = asked.toLowerCase().split(/[\s/-]+/).filter(Boolean);
  const words: string[] = [];
  for (let i = 0; i < raw.length; i++) {
    const next = raw[i + 1];
    if (/^[0-9]+(?:\.[0-9]+)?$/.test(raw[i]) && next !== undefined && UNITS.has(next)) {
      words.push(raw[i] + next);
      i++;
    } else {
      words.push(raw[i]);
    }
  }
  return words;
}

/**
 * 這個商品的品名 / 規格 / 類別 / 品號 / 條碼裡,是不是真的有打的**每一段字**(不分大小寫;空白、斜線、連字號分段,
 * 所以打 `SAM-NOTE5` 跟品名寫 `SAM NOTE5` 對得上,反過來也是)。每一段怎麼算「有」見 `hasWord`。
 * 片段搜尋是「長得像就算」:打「iPhone 99 Ultra」會回來一堆別的 iPhone。要分得出「真的有這些字」跟「只是有點像」。
 */
export function hasEveryWord(p: FoundProduct, asked: string): boolean {
  const words = queryWords(asked);
  if (!words.length) return false;
  const hay = [p.name, p.spec, p.category_name, p.sku, p.barcode]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
  return words.every((w) => hasWord(hay, w));
}

/** 片段搜尋找到、共用比對沒有的那些列,要講它是哪一種(不然「真的有這些字」跟「只是有點像」長得一樣) */
export const WHY_WORDS = "字都對得上";
export const WHY_ALIKE = "只是相似";

/**
 * 候選的順序(同一個商品只出現一次;零庫存、已停用的都留著 —— 沒庫存不代表沒建過):
 * 1. 共用比對裡**強的**(條碼 / 已確認叫法相同、特徵相符):最可能就是它。
 * 2. 片段搜尋找到、而且品名裡**真的有打的每一段字**的(寫「字都對得上」)。
 * 3. 共用比對裡**只是相關的**(同機型但有差異)。
 * 4. 片段搜尋裡只是長得像的(寫「只是相似」)。
 * 2 要在 3 前面:打「iphone 15 512」時同機型的保護貼有二十個,真正叫這個名字的手機會被擠到看不到的地方。
 * 3 要在 4 前面:打「iPhone 15 保護貼」時片段搜尋回來的是幾十支 iPhone,店裡寫成 `IP15` 的保護貼要先看到。
 * 兩邊都找到的,原因與差異照樣帶著,商品資料用共用比對回的那一份(鎖倉帳號的庫存是伺服器照他的門市算的)。
 * 打的是一長串數字(6 碼以上)時,片段搜尋還會去對每一台的序號(IMEI),那不在商品資料裡、這裡看不出來:
 * 第 4 段就不寫「只是相似」(它可能正是那一台的商品)。
 */
export function mergeRows<P extends FoundProduct>(
  resolved: Resolved<P>[],
  plain: P[],
  asked: string,
): FoundRow<P>[] {
  const rows: FoundRow<P>[] = [];
  const seen = new Set<number>();
  const byId = new Map<number, Resolved<P>>();
  for (const c of resolved) if (!byId.has(c.product.id)) byId.set(c.product.id, c);
  const longNumber = /^\d{6,}$/.test(asked.replace(/[\s-]/g, ""));
  const add = (product: P, why: "words" | "alike" | null) => {
    if (seen.has(product.id)) return;
    seen.add(product.id);
    const from = byId.get(product.id);
    rows.push({
      product: from?.product ?? product,
      reasons: from ? from.reasons : why === "words" ? [WHY_WORDS] : [],
      differences: from ? from.differences : why === "alike" && !longNumber ? [WHY_ALIKE] : [],
    });
  };
  for (const c of resolved) if (c.level !== "related") add(c.product, null);
  for (const p of plain) if (hasEveryWord(p, asked)) add(p, "words");
  for (const c of resolved) add(c.product, null);
  for (const p of plain) add(p, "alike");
  return rows;
}

/** 候選第二行:品號 / 類別 / 規格 */
export function rowFacts(row: FoundRow): string {
  const p = row.product;
  return [p.sku, p.category_name, p.spec].filter(Boolean).join(" / ");
}

/** 候選第三行:庫存(0 也寫出來) / 為什麼找到 / 哪裡不同 */
export function rowWhy(row: FoundRow): string {
  return [
    `庫存 ${row.product.stock_qty ?? 0}`,
    row.reasons.join("、"),
    row.differences.join(";"),
  ]
    .filter(Boolean)
    .join(" / ");
}

/**
 * 打的是不是條碼:去掉空白與連字號之後整串數字、8 碼以上(跟後端找商品時的認法一樣;
 * 照著包裝上印的 `4712-3456-7890` 打也算)。是的話回那一串數字,不是回 null。
 */
export function barcodeIn(text: string): string | null {
  const digits = text.replace(/[\s-]/g, "");
  return /^\d{8,}$/.test(digits) ? digits : null;
}

export function looksLikeBarcode(text: string): boolean {
  return barcodeIn(text) !== null;
}

/** 送去找的字:條碼送那一串數字(伺服器只認整串數字),其餘照打的 */
export function searchText(asked: string): string {
  return barcodeIn(asked) ?? asked.trim();
}

/**
 * 確定沒有、要建新的:找的時候打的字帶進表單 —— 是條碼就放條碼,不然放品名。
 * 15 碼、檢查碼正確的是手機的 IMEI(某一台的序號,不是商品的條碼):哪一格都不帶,
 * 不然刷了盒子上的 IMEI 找不到、接著建商品,那一台的 IMEI 就變成整個商品的條碼。
 */
export function createPrefill(asked: string): { name: string; barcode: string } {
  const code = barcodeIn(asked);
  if (code === null) return { name: asked.trim(), barcode: "" };
  if (looksLikeImei(code)) return { name: "", barcode: "" };
  return { name: "", barcode: code };
}

/** 「記住這個叫法」之後,那一句話現在是哪一種:直接對到 / 只幫助搜尋 / 沒記住 */
function rememberKind(action: string, verified: boolean | null | undefined): "direct" | "keyword" | "none" {
  if (action === "keyword") return "keyword";
  if (action === "created" || action === "kept" || action === "repointed") {
    // 「原本就記著」(kept)的那一筆可能本來就只是搜尋用的字:要看它是不是已確認的,不能看到 kept 就說會直接對到
    return verified === true ? "direct" : "keyword";
  }
  return "none";
}

/**
 * 「記住這個叫法」記成了什麼,講給人聽(action 與 verified 都是後端回的:做了什麼、那一筆叫法是不是已確認的)。
 * 太籠統、或有好幾款都符合的叫法,後端只記成搜尋用的字,不會直接對到 —— 兩種要分清楚,
 * 不然人以為記住了,下次打同一句話卻還是要自己挑。
 */
export function rememberNote(action: string, verified: boolean | null | undefined): string {
  const kind = rememberKind(action, verified);
  if (kind === "direct") return "叫法已記住:以後直接對到這一款";
  if (kind === "keyword") return "叫法已記下:只幫助搜尋,不會直接對到";
  return "叫法沒有記住";
}

/** 那一句話用什麼顏色講:直接對到 = 成功;只幫助搜尋 = 一般;沒記住 = 錯誤(不能用成功的顏色講沒成功的事) */
export function rememberTone(action: string, verified: boolean | null | undefined): "ok" | "" | "err" {
  const kind = rememberKind(action, verified);
  return kind === "direct" ? "ok" : kind === "keyword" ? "" : "err";
}

/**
 * 候選上的「庫存」算哪一家門市。
 * 鎖在一家門市的店員只看自己那一家(共用比對那一半伺服器本來就這樣回;片段搜尋與查重那一半要跟著帶,
 * 不然同一份清單裡有的是本店、有的是全公司)。鎖倉卻沒設門市 → 0 號門市(庫存一律 0,跟伺服器一樣)。
 * 沒鎖的不限門市(全公司)。
 */
export function stockScope(
  profile: { is_warehouse_locked?: boolean; default_warehouse_id?: number | null } | null | undefined,
): number | undefined {
  if (!profile?.is_warehouse_locked) return undefined;
  return profile.default_warehouse_id ?? 0;
}
