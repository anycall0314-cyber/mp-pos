// 發票機(WP-103)接在這台電腦的 COM 埠:伺服器把一頁排好、轉成位元組(backend/apps/sales/wp103.py),
// 這裡用 Chrome 的 Web Serial 原樣送進去。不用驅動程式;只有電腦版的 Chrome / Edge 有這個功能。
// owner 2026-10-13:三聯式收銀機發票是過渡用的(之後走電子發票串接)→ 只做最簡單夠用的。

/** 可以選的傳輸速率(機器底下的指撥開關決定是哪一個;印出亂碼就換一個)。 */
export const BAUD_RATES = [9600, 19200, 38400, 4800] as const;

/** 這台電腦記住的設定:速率、樣張上面先空幾行。跟標籤的位置微調一樣記在瀏覽器裡(每一台機器不一樣)。 */
// topMax = 上面最多空幾行(空到「總計」剛好印在最後一行);跟伺服器的 `wp103.TOP_RANGE` 同一個數字,伺服器那邊有測試對
export const PRINTER_SETUP = { storageKey: "mp_pos_invoice_printer", topMax: 9 } as const;

export interface PrinterSetup {
  baud: number;
  /** 上面先空幾行(對紙用) */
  top: number;
}

export const DEFAULT_SETUP: PrinterSetup = { baud: BAUD_RATES[0], top: 0 };

/** 空幾行:整數、0 到上限;不是數字當 0。 */
export function clampTop(value: unknown): number {
  const n = typeof value === "number" && Number.isFinite(value) ? Math.round(value) : 0;
  return Math.max(0, Math.min(PRINTER_SETUP.topMax, n));
}

/** 讀回這台電腦存的設定;讀不出來、速率不是清單裡的 → 用預設的。 */
export function readPrinterSetup(raw: string | null | undefined): PrinterSetup {
  try {
    const got = JSON.parse(raw ?? "") as Partial<PrinterSetup> | null;
    if (!got || typeof got !== "object") return { ...DEFAULT_SETUP };
    const baud = (BAUD_RATES as readonly number[]).includes(got.baud as number) ? (got.baud as number) : DEFAULT_SETUP.baud;
    return { baud, top: clampTop(got.top) };
  } catch {
    return { ...DEFAULT_SETUP };
  }
}

/** 伺服器給的位元組是 base64 的字:轉回一個一個位元組。 */
export function bytesFromBase64(b64: string): Uint8Array {
  const text = atob(b64);
  const out = new Uint8Array(text.length);
  for (let i = 0; i < text.length; i += 1) out[i] = text.charCodeAt(i);
  return out;
}

/** Web Serial 裡用得到的那幾樣(TypeScript 內建的型別還沒有) */
export interface SerialPortLike {
  open(options: {
    baudRate: number;
    dataBits: number;
    stopBits: number;
    parity: "none" | "even" | "odd";
    flowControl: "none" | "hardware";
  }): Promise<void>;
  close(): Promise<void>;
  writable: { getWriter(): { write(data: Uint8Array): Promise<void>; close(): Promise<void>; releaseLock(): void } } | null;
}
interface SerialLike {
  requestPort(): Promise<SerialPortLike>;
  getPorts(): Promise<SerialPortLike[]>;
}

function serial(): SerialLike | null {
  if (typeof navigator === "undefined") return null;
  return (navigator as unknown as { serial?: SerialLike }).serial ?? null;
}

/** 這個瀏覽器能不能直接連發票機。 */
export function serialSupported(): boolean {
  return serial() !== null;
}

/** 讓人選發票機接的那個埠(瀏覽器會跳出清單)。**一定要在按鈕的點擊裡呼叫**;選過之後這台電腦會記得。 */
export async function choosePort(): Promise<SerialPortLike> {
  const api = serial();
  if (!api) throw new Error("這個瀏覽器不能直接連發票機");
  return api.requestPort();
}

/** 之前選過、瀏覽器還記得的那個埠;沒有回 null。 */
export async function rememberedPort(): Promise<SerialPortLike | null> {
  const api = serial();
  if (!api) return null;
  const ports = await api.getPorts();
  return ports[0] ?? null;
}

/**
 * 把一頁送進發票機:開埠(8 個資料位元、沒有同位、1 個停止位元 = 這台機器固定的)→ 寫 → 等寫完 → 關埠。
 * 每印一次開關一次:不佔著埠(一個 COM 埠同時只能給一個程式用)。寫到一半出錯也會關。
 * 一張發票不到 2K,機器的緩衝區 4K,所以不用流量控制。
 */
export async function sendToPrinter(port: SerialPortLike, baud: number, bytes: Uint8Array): Promise<void> {
  await port.open({ baudRate: baud, dataBits: 8, stopBits: 1, parity: "none", flowControl: "none" });
  try {
    if (!port.writable) throw new Error("發票機沒有回應");
    const writer = port.writable.getWriter();
    try {
      await writer.write(bytes);
      await writer.close();
    } finally {
      writer.releaseLock();
    }
  } finally {
    await port.close();
  }
}

/** 連不上、送不出去時給人看的一句。 */
export function printerErrorText(e: unknown): string {
  const name = (e as { name?: string } | null)?.name ?? "";
  if (name === "NotFoundError") return "沒有選發票機";
  if (name === "InvalidStateError") return "發票機正在忙,等一下再印";
  if (name === "NetworkError") return "連不上發票機:可能被別的程式佔著(舊系統開著?)、或線沒接好";
  return e instanceof Error && e.message ? e.message : "送不出去";
}
