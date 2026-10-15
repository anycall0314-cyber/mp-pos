// 手機走動盤點那一頁的規則(跑法:npm test)。伺服器的規則在 backend/apps/inventory/stockcount_phone.py。
//
// 相機一直對著條碼,每一格畫面都讀得到同一個碼:不能每一格都 +1。
// 一個一個刷同一種配件(一堆裡每一個都是同一個條碼)時,要「拿開、換下一個」才算下一下:
// **同一個碼要先看不到一陣子(gapMs)再出現才算;不管哪個碼,兩下之間至少隔 minMs**(手抖、對焦時跳來跳去不會多算)。

export interface GateOptions {
  /** 同一個碼要先看不到多久,再出現才算下一下 */
  gapMs?: number;
  /** 兩下之間至少隔多久 */
  minMs?: number;
}

/** 每一格讀到碼就問一次:這一格算不算新的一下。 */
export function createScanGate({ gapMs = 450, minMs = 700 }: GateOptions = {}) {
  const lastSeen = new Map<string, number>();
  let lastCode = "";
  let lastAccepted = -Infinity;
  /** 「拿開再出現」過、還沒算的那個碼:太快(不到 minMs)先記著,之後一直讀得到也要算(複審 P2:不能被吃掉) */
  let armed: string | null = null;
  return (code: string, now: number): boolean => {
    const seen = lastSeen.get(code);
    lastSeen.set(code, now);
    if (code !== lastCode || seen === undefined || now - seen > gapMs) armed = code;
    if (armed !== code || now - lastAccepted < minMs) return false;
    armed = null;
    lastCode = code;
    lastAccepted = now;
    return true;
  };
}

/** 「這一堆幾個」那一格打的字 → 1 到 9999 的整數;不是就 null。 */
export function pileQty(text: string): number | null {
  const t = text.trim();
  return /^\d{1,4}$/.test(t) && Number(t) >= 1 ? Number(t) : null;
}

export type TapKind = "line" | "scan" | "unknown";

export interface PhoneTap {
  id: number;
  kind: TapKind;
  code: string;
  undone: boolean;
  name: string;
  /** 配件:這一下加了幾個(+1,或改成「這一堆幾個」之後的數) */
  step?: number;
  /** 配件:這個品項大家合起來數到幾個;沒對到的碼:刷了幾次 */
  total?: number;
}

/** 一下寫成一行字:配件「+1 → 共 5」、沒對到「沒對到 共 2 次」、手機只有品名。 */
export function tapText(t: Pick<PhoneTap, "kind" | "step" | "total" | "undone">): string {
  if (t.undone) return "收回了";
  if (t.kind === "line") return `+${t.step ?? 1} → 共 ${t.total ?? 0}`;
  if (t.kind === "unknown") return `共 ${t.total ?? 0} 次`;
  return "";
}

/** 讀條碼要認的格式:舊系統的貼紙(Code 128 / 39)、商品條碼(EAN / UPC)、機器的 IMEI / SN(Code 128)、偶爾的 QR。 */
export const BARCODE_FORMATS = ["code_128", "code_39", "code_93", "ean_13", "ean_8", "upc_a", "upc_e", "itf", "codabar", "qr_code", "data_matrix"];
