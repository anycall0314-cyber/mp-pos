/**
 * 商品標籤(50 × 30 mm,Argox OS-2130D 熱感式 203 dpi)的尺寸與「條碼照印表機的點數畫」的規則。
 * 純函式,`labels.test.mjs` 有測試。
 *
 * 為什麼要自己算:熱感印表機一個點 0.125 mm,只有黑跟白。條碼的每一條線如果不是剛好整數個點
 * (例如把條碼圖拉寬到貼滿標籤),印出來的線有粗有細、邊緣是灰的,條碼槍刷不到。
 * 所以一個單位(最細的那條線)固定是整數個點:放得下用 3 點,放不下用 2 點;
 * 2 點還放不下就是這個碼太長 —— 不印糊的條碼,只印文字,並且在畫面上講出來。
 */

/** 標籤紙與印表機。尺寸只寫在這裡(列印樣式 `.label-*` 用同一組數字) */
export const LABEL = {
  widthMm: 50,
  heightMm: 30,
  /** 203 dpi = 一公釐 8 個點 */
  dotsPerMm: 8,
  /** 左右留白(標籤紙對位會有一點偏,貼著邊印會被切掉) */
  sideMarginMm: 1.5,
  /** 條碼的高度 */
  barHeightMm: 8,
  /** 條碼兩邊要留的空白:10 個單位(Code 128 的規定,少了槍會讀不到) */
  quietModules: 10,
  /** 一個單位幾個點:先試大的 */
  moduleDots: [3, 2],
} as const;

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
 */
export function layoutBars(bits: string, areaDots: number = barAreaDots()): BarLayout | null {
  if (!/^[01]+$/.test(bits)) return null;
  const modules = bits.length + LABEL.quietModules * 2;
  const moduleDots = LABEL.moduleDots.find((d) => modules * d <= areaDots);
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
