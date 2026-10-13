/**
 * 商品標籤(45 × 25 mm、上下兩聯,Argox OS-2130D 熱感式 203 dpi)的尺寸與「條碼照印表機的點數畫」的規則。
 * 純函式,`labels.test.mjs` 有測試。
 *
 * **標籤紙是上下兩聯**(owner 2026-10-13:寬 45 mm、高 25 mm,中間有一條撕線,撕開各自是一張):
 * 上半、下半印一樣的內容、上下對稱(字都是正的,只是順序倒過來),條碼只有一個、跨在撕線上 ——
 * 撕開之後兩邊各留半個高度的條碼、各自刷得到。跨著印的好處是撕線的位置差一點也沒關係。
 *
 * 為什麼要自己算:熱感印表機一個點 0.125 mm,只有黑跟白。條碼的每一條線如果不是剛好整數個點
 * (例如把條碼圖拉寬到貼滿標籤),印出來的線有粗有細、邊緣是灰的,條碼槍刷不到。
 * 所以一個單位(最細的那條線)固定是整數個點:放得下用 3 點,放不下用 2 點;
 * 2 點還放不下就是這個碼太長 —— 不印糊的條碼,只印文字,並且在畫面上講出來。
 */

/** 標籤紙與印表機。尺寸只寫在這裡(列印樣式 `.label-*` 用同一組數字,`labels.test.mjs` 會對) */
export const LABEL = {
  widthMm: 45,
  heightMm: 25,
  /** 203 dpi = 一公釐 8 個點 */
  dotsPerMm: 8,
  /** 左右留白(標籤紙對位會有一點偏,貼著邊印會被切掉) */
  sideMarginMm: 1.5,
  /** 條碼的高度:跨在撕線上,上下兩聯各一半 */
  barHeightMm: 7.2,
  /** 條碼兩邊要留的空白:10 個單位(Code 128 的規定,少了槍會讀不到) */
  quietModules: 10,
  /** 一個單位幾個點:先試大的 */
  moduleDots: [3, 2],
  /** 品名一行放不下時最多壓扁到多少(再放不下才切掉尾巴) */
  minSqueeze: 0.75,
  /** 品名壓到格子的幾成寬:留一點點,螢幕上量的跟印表機畫的字寬會差一點,不然最後一個字的邊會被切到 */
  nameRoom: 0.985,
} as const;

/** 撕線離標籤上緣幾公釐 */
export function foldMm(): number {
  return LABEL.heightMm / 2;
}

/** 條碼的上緣離標籤上緣幾公釐(條碼的正中間就是撕線) */
export function barTopMm(): number {
  return (LABEL.heightMm - LABEL.barHeightMm) / 2;
}

/**
 * 品名只有一行:放不下時把字壓扁(只壓寬度)讓整個品名進得去 —— 配件的品名差別常常在最後面(`…/13吋` 與 `…/11吋`),
 * 切掉尾巴就分不出來。最多壓到 `minSqueeze`,再放不下才切。量不到寬度(0)當成不用壓。
 */
export function squeezeFor(textWidth: number, boxWidth: number): number {
  if (!(textWidth > 0) || !(boxWidth > 0)) return 1;
  const room = boxWidth * LABEL.nameRoom;
  if (textWidth <= room) return 1;
  return Math.max(LABEL.minSqueeze, room / textWidth);
}

/**
 * 標籤上的日期:中華民國年月日、中間不分隔(owner 2026-10-13;舊標籤就是這樣印:`1140204`)。
 * 給的是 "2026-10-06" 這種;看不懂的回空的(不印,不猜)。
 */
export function rocDay(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso ?? "");
  if (!m) return "";
  const year = Number(m[1]) - 1911;
  if (year < 1) return "";
  return `${year}${m[2]}${m[3]}`;
}

/**
 * 序號拆成 [前面, 末幾碼](店員對實機看的是末幾碼:有條碼時字只印末幾碼,印不出條碼時整串都印、末幾碼標粗)。
 * 拆不出來就是 [整串, ""]:紙上印的那一串不是以它結尾(原廠條碼改印品號時,後端給的末 5 碼是另一個碼的)、或整串就那麼長。
 */
export function splitTail(code: string, tail: string): [string, string] {
  if (!tail || code.length <= tail.length || !code.endsWith(tail)) return [code, ""];
  return [code.slice(0, code.length - tail.length), tail];
}

/**
 * 位置微調:這台印表機印出來偏了多少,就把整張反方向推回去(公釐;往右、往下是正的)。
 * **記在這台電腦的瀏覽器**,不是公司的設定:每一台印表機、每一次校正偏的都不一樣(owner 2026-10-13 實機:偏下不到 1 mm)。
 * 一格 0.25 mm = 印表機的 2 個點,所以條碼的線推完還是落在點上;最多推 3 mm(再多就是紙張尺寸設錯,不是微調該處理的)。
 */
export const NUDGE = { stepMm: 0.25, maxMm: 3, storageKey: "mp_pos_label_nudge" } as const;

export interface Nudge {
  x: number;
  y: number;
}

export type NudgeMove = "up" | "down" | "left" | "right";

/** 收成一格一格的、不超過上限;不是數字的當 0 */
function snapNudge(value: unknown): number {
  const mm = typeof value === "number" && Number.isFinite(value) ? value : 0;
  const most = NUDGE.maxMm / NUDGE.stepMm;
  const steps = Math.max(-most, Math.min(most, Math.round(mm / NUDGE.stepMm)));
  // `|| 0`:−0 也收成 0(不然畫面會印出「上 0」)
  return steps * NUDGE.stepMm || 0;
}

/** 存在瀏覽器的那一份讀回來。看不懂的、超出範圍的都收回來:壞掉的設定不能把標籤推到紙外面 */
export function readNudge(raw: string | null | undefined): Nudge {
  if (!raw) return { x: 0, y: 0 };
  try {
    const saved = JSON.parse(raw) as { x?: unknown; y?: unknown } | null;
    return { x: snapNudge(saved?.x), y: snapNudge(saved?.y) };
  } catch {
    return { x: 0, y: 0 };
  }
}

/** 按一下推一格(印出來偏下就按「往上」) */
export function moveNudge(now: Nudge, move: NudgeMove): Nudge {
  const step = NUDGE.stepMm;
  if (move === "up") return { x: now.x, y: snapNudge(now.y - step) };
  if (move === "down") return { x: now.x, y: snapNudge(now.y + step) };
  if (move === "left") return { x: snapNudge(now.x - step), y: now.y };
  return { x: snapNudge(now.x + step), y: now.y };
}

/** 現在推了多少:「上 0.75 · 左 0.25 mm」;沒有推就是空的 */
export function nudgeText(now: Nudge): string {
  const parts: string[] = [];
  if (now.y) parts.push(`${now.y < 0 ? "上" : "下"} ${Math.abs(now.y)}`);
  if (now.x) parts.push(`${now.x < 0 ? "左" : "右"} ${Math.abs(now.x)}`);
  return parts.length ? `${parts.join(" · ")} mm` : "";
}

/** 一聯上面的字(上下兩聯印的一樣)。畫面照這個排,不自己決定印什麼 */
export interface HalfText {
  /** 進貨單號 · 日期(民國);都沒有就是空的 */
  source: string;
  /**
   * 碼的那一行怎麼印:
   * - `tail`:只印末幾碼(放在 `tail`)—— **有序號、而且條碼印得出來的那一台**(owner 2026-10-13「有序號的產品,僅需印後五碼」;
   *   條碼仍然是整支序號,刷了才找得到這一台)
   * - `full`:整串都印(`head` + `tail`;`tail` 是序號的末幾碼,畫面標粗)—— 配件的原廠條碼 / 品號,
   *   以及**印不出條碼的序號**(只剩字可以對,不能只印末幾碼)
   */
  mode: "tail" | "full";
  head: string;
  tail: string;
  /** 右邊的品號;條碼印的就是品號時不重複印 */
  sku: string;
}

/** `code` = 紙上實際印的那個碼(`printableCode` 的結果),`bars` = 條碼印不印得出來 */
export function halfText(
  label: { code_kind: string; sku: string; last5: string; doc_no: string; doc_date: string },
  code: string,
  bars: boolean,
): HalfText {
  const source = [label.doc_no, rocDay(label.doc_date)].filter(Boolean).join(" · ");
  const sku = label.sku.trim() === code ? "" : label.sku.trim();
  if (label.code_kind !== "serial") return { source, mode: "full", head: code, tail: "", sku };
  const [head, tail] = splitTail(code, label.last5);
  if (bars) return { source, mode: "tail", head: "", tail: tail || code, sku };
  return { source, mode: "full", head, tail, sku };
}

/** 條碼可以用的寬度(點) */
export function barAreaDots(): number {
  return (LABEL.widthMm - LABEL.sideMarginMm * 2) * LABEL.dotsPerMm;
}

export interface BarLayout {
  /** 一個單位幾個點 */
  moduleDots: number;
  /** 整個條碼(含兩邊空白)幾個點寬 */
  widthDots: number;
  /** 每一條黑線:從第幾個點開始、幾個點寬 */
  bars: { x: number; w: number }[];
}

/**
 * 把條碼的黑白樣式("1101001…",1 = 黑)排成整數個點。
 * 放不下回 null(這個碼太長,不印條碼)。
 * `tryDots` 只有測試標籤的「細線」那一張會給(一個單位 1 點:看這台印表機與條碼槍吃不吃得下);一般的標籤不給。
 */
export function layoutBars(
  bits: string,
  areaDots: number = barAreaDots(),
  tryDots: readonly number[] = LABEL.moduleDots,
): BarLayout | null {
  if (!/^[01]+$/.test(bits)) return null;
  const modules = bits.length + LABEL.quietModules * 2;
  const moduleDots = tryDots.find((d) => modules * d <= areaDots);
  if (!moduleDots) return null;
  const bars: { x: number; w: number }[] = [];
  let i = 0;
  while (i < bits.length) {
    if (bits[i] === "0") {
      i += 1;
      continue;
    }
    let j = i;
    while (j < bits.length && bits[j] === "1") j += 1;
    bars.push({ x: (LABEL.quietModules + i) * moduleDots, w: (j - i) * moduleDots });
    i = j;
  }
  return { moduleDots, widthDots: modules * moduleDots, bars };
}

/** 條碼在可用寬度裡置中時,左邊要空幾個點(整數:條碼的起點也要落在點上) */
export function leftPadDots(widthDots: number, areaDots: number = barAreaDots()): number {
  return Math.max(0, Math.floor((areaDots - widthDots) / 2));
}

/** 點 → 公釐(給樣式用) */
export function dotsToMm(dots: number): number {
  return dots / LABEL.dotsPerMm;
}

/**
 * 這一張實際要印哪個碼的條碼。
 * - 印得下:就印它。
 * - **原廠條碼**印不下(太長、或有條碼沒有的字)而品號印得下:改印品號的條碼(`swapped`)——
 *   刷品號一樣找得到這個商品,比完全沒有條碼好;條碼下面的字也跟著印品號(字跟線要是同一個碼)。
 * - 序號印不下不能換:那是「這一台」的碼,換成品號就刷不到這一台了。只印文字(`bars: false`)。
 */
export function printableCode(
  label: { code: string; code_kind: string; sku: string },
  fits: (code: string) => boolean,
): { code: string; bars: boolean; swapped: boolean } {
  // 頭尾的空白先去掉,而且**條碼跟下面的字用同一個去過的字串**(回傳的 `code`):
  // 只有條碼去、字沒去的話,槍讀到的跟紙上看到的差一個看不見的空白,拿去對庫存會對不到
  const code = label.code.trim();
  const sku = label.sku.trim();
  if (fits(code)) return { code, bars: true, swapped: false };
  if (label.code_kind === "barcode" && sku && fits(sku)) {
    return { code: sku, bars: true, swapped: true };
  }
  return { code, bars: false, swapped: false };
}

export interface LabelEntry {
  key: string;
  /** 序號商品的某一台 = 編號;配件 = null */
  serial_id: number | null;
  copies: number;
}

/** 一筆最多印幾張(多打一個 0 就是一整卷標籤) */
export const MAX_SHEETS = 500;
/** 整批最多印幾張:超過就不送印(一張進貨單十行配件、每行幾百件,加起來會是幾千張) */
export const MAX_TOTAL_SHEETS = 1000;

/** 張數在這個數字以內才自己跳列印視窗(多的先讓人看一眼張數) */
export const AUTO_PRINT_MAX = 100;

/**
 * 要不要自己跳出列印視窗。
 * 不跳:被要求不要跳、沒有東西要印、張數很多、或有事情要先讓人看到
 * (少印了幾台、條碼印不下 —— 列印視窗一跳出來就把那一排提醒蓋住了)。
 */
export function shouldAutoPrint(s: { auto: boolean; total: number; hasWarning: boolean }): boolean {
  return s.auto && !s.hasWarning && s.total >= 1 && s.total <= AUTO_PRINT_MAX;
}

/** 整批一共幾張(不展開,只是加總) */
export function totalSheets(entries: LabelEntry[], edited: Record<string, number>): number {
  return entries.reduce((sum, entry) => sum + copiesOf(entry, edited), 0);
}

/**
 * 每一筆要印幾張:某一台固定 1 張;配件用畫面上改過的張數(沒改就是伺服器給的)。
 * 張數只收 0 到 500 的整數(0 = 這一筆不印)。
 */
export function copiesOf(entry: LabelEntry, edited: Record<string, number>): number {
  if (entry.serial_id !== null) return 1;
  const n = edited[entry.key] ?? entry.copies;
  if (!Number.isInteger(n) || n < 0) return 0;
  return Math.min(n, MAX_SHEETS);
}

/** 照張數展開成一張一張(順序照原本的) */
export function expandSheets<T extends LabelEntry>(
  entries: T[],
  edited: Record<string, number>,
): { key: string; entry: T }[] {
  const out: { key: string; entry: T }[] = [];
  // 超過整批的上限就不展開(畫面會請人把張數改少):幾千張一次畫出來瀏覽器會卡住,印出來也是一整卷
  if (totalSheets(entries, edited) > MAX_TOTAL_SHEETS) return out;
  for (const entry of entries) {
    const n = copiesOf(entry, edited);
    for (let i = 0; i < n; i += 1) out.push({ key: `${entry.key}-${i}`, entry });
  }
  return out;
}
