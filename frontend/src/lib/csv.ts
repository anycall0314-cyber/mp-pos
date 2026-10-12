// 匯出成試算表開得了的檔(CSV):全站只有這一份寫法。跑法:npm test。
//
// 兩件事最容易出錯:
// 1. **長數字(IMEI、條碼)與開頭是 0 的號碼(電話、門號)要寫成文字** —— 不然試算表會把 356789012345678 顯示成 3.56E+14
//    (存檔之後末幾碼變 0)、把 0912345678 變成 912345678。寫成 ="…" 試算表就照字面顯示。
// 2. 金額不要帶千分位的逗號(那是呼叫的人的事:用 `intStr`,不要用 `money`)。

/** 一格。有逗號 / 引號 / 換行的包起來;長數字與開頭是 0 的號碼寫成文字。 */
export function csvCell(value: unknown): string {
  const s = value === null || value === undefined ? "" : String(value);
  if (/^\d{12,}$/.test(s) || /^0\d+$/.test(s)) return `"=""${s}"""`;
  return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

/** 整張表(一列一行、每一列的格數由呼叫的人自己對齊)。 */
export function toCsv(table: unknown[][]): string {
  return table.map((row) => row.map(csvCell).join(",")).join("\r\n");
}

/** 檔案開頭的記號:讓 Excel 認得出這是 UTF-8(不然中文是亂碼)。 */
export const CSV_BOM = "﻿";
