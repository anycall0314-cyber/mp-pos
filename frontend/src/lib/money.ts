/**
 * 金額的唯一顯示規則:全站金額一律整數元、四捨五入。
 *
 * 資料庫的金額欄位帶兩位小數("1500.00"),平均成本 / 未稅金額真的會有零頭(952.38)。
 * 畫面、輸入框、列印、匯出都不出現小數點,統一走這裡,不要各頁自己 Math.round:
 * `Math.round(-2.5)` 是 -2(往正的方向),退款 / 負毛利會跟正數差一塊。
 */
/**
 * 四捨五入到整數元。剛好一半的一律進位(離 0 遠的那一邊):2.5 → 3、-2.5 → -3。
 * 空的 / 不是數字 → 0。(收 unknown:報表的列是沒有型別的資料,一樣要能直接丟進來)
 */
export function roundInt(v: unknown): number {
  if (v === null || v === undefined || v === "") return 0;
  const n = typeof v === "number" ? v : Number(v);
  if (!Number.isFinite(n)) return 0;
  // 先收到小數六位再進位:1.255 × 100 在電腦裡是 125.49999999999999,直接進位會少一塊
  const abs = Math.round(Number(Math.abs(n).toFixed(6)));
  return n < 0 && abs !== 0 ? -abs : abs;
}

/** 畫面上的金額:整數 + 千分位(1,500)。 */
export function money(v: unknown): string {
  return roundInt(v).toLocaleString("en-US");
}

/**
 * 輸入框 / 送給伺服器用的整數字串("1500.00" → "1500")。
 * 空的回 `empty`(預設 "0";輸入框想留白就傳 "")。
 */
export function intStr(v: unknown, empty = "0"): string {
  if (v === null || v === undefined) return empty;
  if (typeof v === "string" && v.trim() === "") return empty;
  const n = typeof v === "number" ? v : Number(v);
  if (!Number.isFinite(n)) return empty;
  return String(roundInt(n));
}

/**
 * 送出用:這一格跟載入時一模一樣(沒動過)就把原本的值原樣送回去,動過的才收成整數。
 * 以前存的 100.50 只改備註時不會被悄悄改成 101;成本(95.24)沒動也不會變。
 */
export function keepOrInt(current: unknown, loaded: unknown, empty = "0"): string {
  if (loaded !== null && loaded !== undefined && String(current) === String(loaded)) {
    return String(loaded);
  }
  return intStr(current, empty);
}

/**
 * 一行明細的金額 = 數量 × 單價,單價先收成整數元(畫面上看到的單價是多少,就用多少乘)。
 * 3 × 10.4 是 30,不是 31:先乘再進位會跟畫面上的「10 × 3」對不起來。
 */
export function lineTotal(qty: unknown, unitPrice: unknown): number {
  return roundInt(qty) * roundInt(unitPrice);
}

export type TaxMethod = "taxable_included" | "taxable_excluded" | string;

/**
 * 明細金額 → [未稅小計, 稅額, 含稅總額],三個都是整數元。
 * 跟伺服器存檔時的算法一模一樣(backend 的 `_calc_tax` / `_calc_doc_tax`),
 * 畫面上試算的數字才會等於存下來的數字:每一行的金額先各自四捨五入再加總;
 * 含稅:未稅 = 加總 ÷ 1.05 四捨五入,稅額 = 總額 − 未稅;外加:稅額 = 加總 × 5% 四捨五入。
 */
export function splitTax(
  lineAmounts: unknown[],
  method: TaxMethod,
): [number, number, number] {
  const sum = lineAmounts.reduce<number>((s, a) => s + roundInt(a), 0);
  if (method === "taxable_included") {
    const subtotal = roundInt((sum * 100) / 105);
    return [subtotal, sum - subtotal, sum];
  }
  if (method === "taxable_excluded") {
    const tax = roundInt((sum * 5) / 100);
    return [sum, tax, sum + tax];
  }
  return [sum, 0, sum];
}

/**
 * 把未稅小計分到每一行,回傳每一行的未稅金額(跟後端 `split_tax_by_line` 同一套算法):
 * 每行先照稅別各自算,四捨五入的零頭補在金額(絕對值)最大的那一行(一樣大取前面那一行),
 * 整張加起來正好等於 `splitTax()` 的未稅小計。要「只算其中幾行」的數字(例如不計毛利的商品不算)用這個。
 */
export function splitUntaxedByLine(
  lineAmounts: unknown[],
  method: TaxMethod,
): number[] {
  const amounts = lineAmounts.map(roundInt);
  if (amounts.length === 0) return [];
  const [subtotal] = splitTax(amounts, method);
  const each = amounts.map((a) =>
    method === "taxable_included" ? roundInt((a * 100) / 105) : a,
  );
  const diff = subtotal - each.reduce((sum, u) => sum + u, 0);
  if (diff !== 0) {
    let k = 0;
    amounts.forEach((a, i) => {
      if (Math.abs(a) > Math.abs(amounts[k])) k = i;
    });
    each[k] += diff;
  }
  return each;
}
