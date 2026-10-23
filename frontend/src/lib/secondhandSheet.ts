// 中古機大量進貨的 Excel:預覽之後哪幾台可以加進進貨單、怎麼併成明細(跑法:npm test)。
// 讀檔、品名對哪個品號、碼在不在系統裡都是伺服器做的(backend/apps/purchasing/secondhand_sheet.py);
// 這裡只管:對不到的品名人挑了哪一個、哪幾台能加、成本照稅別顯示多少、同一個品號併成一行。
// 紅隊(2026-10-14):品名只認確定的,不確定的不先帶(要人自己挑);碼已經在系統裡的那一台不能加;預覽第一行寫進哪家店、哪家廠商、稅別。

export interface SheetRow {
  row: number;
  name: string;
  imei: string;
  sn: string;
  grade: string;
  battery: number | null;
  cost: number | null;
  price: number | null;
  note: string;
  problems: string[];
  /** 伺服器確定對到的品號編號;null = 要人挑 */
  product: number | null;
}

export interface SheetPreview<P> {
  rows: SheetRow[];
  /** 對不到的品名與幾台 */
  names: { name: string; count: number }[];
  /** 對到的品號的完整商品資料 */
  products: P[];
}

/** 一台的機況(跟進貨單上手動刷的那一台同一個樣子) */
export interface SheetEntry {
  imei: string;
  sn: string;
  grade?: "S" | "A" | "B" | "C" | "D";
  cost: string;
  price?: string;
  battery?: string;
  note?: string;
}

/** 這一列最後入哪個品號:伺服器對到的,不然是人替這個品名挑的。 */
export function productOf<P extends { id: number }>(row: SheetRow, products: Map<number, P>, picks: Record<string, P | undefined>): P | null {
  if (row.product !== null) return products.get(row.product) ?? null;
  return picks[row.name] ?? null;
}

/** 可以加進進貨單的:沒有問題、有品號。 */
export function readyRows<P extends { id: number }>(rows: SheetRow[], products: Map<number, P>, picks: Record<string, P | undefined>): SheetRow[] {
  return rows.filter((r) => r.problems.length === 0 && productOf(r, products, picks) !== null);
}

/** 預覽上面那一行的數字:能加幾台、有問題幾台、還沒挑品號幾台。 */
export function sheetCounts<P extends { id: number }>(rows: SheetRow[], products: Map<number, P>, picks: Record<string, P | undefined>) {
  const ready = readyRows(rows, products, picks).length;
  const bad = rows.filter((r) => r.problems.length > 0).length;
  return { ready, bad, unpicked: rows.length - ready - bad };
}

/** 一台 → 進貨單上的一台。進價寫在那一台自己的成本(含稅單存檔時照原本的規則除 1.05)。 */
export function entryOf(row: SheetRow): SheetEntry {
  const entry: SheetEntry = { imei: row.imei, sn: row.sn, cost: String(row.cost ?? 0) };
  if (row.grade) entry.grade = row.grade as SheetEntry["grade"];
  if (row.price !== null && row.price > 0) entry.price = String(row.price);
  if (row.battery !== null) entry.battery = String(row.battery);
  if (row.note) entry.note = row.note;
  return entry;
}

/** 能加的那幾台照品號併成一行一個品號(照檔案裡第一次出現的順序)。 */
export function groupForPurchase<P extends { id: number }>(
  rows: SheetRow[],
  products: Map<number, P>,
  picks: Record<string, P | undefined>,
): { product: P; entries: SheetEntry[] }[] {
  const out: { product: P; entries: SheetEntry[] }[] = [];
  for (const row of readyRows(rows, products, picks)) {
    const product = productOf(row, products, picks)!;
    let group = out.find((g) => g.product.id === product.id);
    if (!group) {
      group = { product, entries: [] };
      out.push(group);
    }
    group.entries.push(entryOf(row));
  }
  return out;
}

/** 預覽第一行:進哪家店、哪家廠商、課稅別(紅隊第 3 條;課稅別的名稱照進貨單那一頁的)。 */
export function sheetHeader(warehouse: string, supplier: string, taxLabel: string): string {
  return [warehouse || "未選門市", supplier || "未選廠商", taxLabel].join(" · ");
}

/** 這一台記進庫存的成本(含稅單 = 進價 ÷ 1.05,跟存檔時的算法一樣;顯示用)。 */
export function costIn(cost: number | null, taxMethod: string): number {
  const gross = cost ?? 0;
  return taxMethod === "taxable_included" ? gross / 1.05 : gross;
}

/** 範本的檔(伺服器給 base64)→ 可以下載的檔。 */
export function templateBlob(base64: string): Blob {
  const bin = atob(base64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return new Blob([bytes], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" });
}

/** 匯入表格沒加進去的那幾列(有問題、還沒挑品號):放進掃碼框的「沒加入」,逐筆處理(全站檢視 C8) */
export function sheetLeftovers<P extends { id: number }>(
  rows: SheetRow[],
  products: Map<number, P>,
  picks: Record<string, P | undefined>,
): { kw: string; reason: string }[] {
  const ready = new Set(readyRows(rows, products, picks));
  // 用品名當那一筆的字(重查找的是商品);碼寫在原因裡,補的時候照著刷
  return rows.filter((r) => !ready.has(r)).map((r) => {
    const code = r.imei || r.sn;
    return {
      kw: r.name || code,
      reason: `匯入表格第 ${r.row} 列${code ? `(${code})` : ""}:${r.problems.length > 0 ? r.problems.join("、") : "還沒挑品號"}`,
    };
  });
}
