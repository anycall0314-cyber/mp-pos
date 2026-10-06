import JsBarcode from "jsbarcode";

/**
 * 把一個碼編成 Code 128 的黑白樣式("1101001…",1 = 黑,一個字一個單位)。
 * 編碼交給 jsbarcode(會自己挑最短的編法:連續的數字兩個兩個編);畫由我們自己照印表機的點數畫(`lib/labels.ts`)。
 *
 * **給什麼就編什麼,不偷偷修**(不去頭尾空白):條碼下面印的字是同一個字串,這裡自己修過的話,槍讀到的跟紙上看到的就不是同一個碼。
 * 要不要去空白由上一層(`printableCode`)決定,而且條碼跟字用同一個結果。
 * 編不了回 null:空的、有中文 / 全形字、有換行或 Tab(條碼編得進去、紙上卻看不出來的字,不收)。
 */
export function code128Bits(value: string): string | null {
  const text = value;
  if (!/^[\x20-\x7e]+$/.test(text)) return null;
  const holder: { encodings?: { data: string }[] } = {};
  try {
    JsBarcode(holder, text, { format: "CODE128" });
  } catch {
    return null;
  }
  const bits = (holder.encodings ?? []).map((e) => e.data).join("");
  return /^[01]+$/.test(bits) ? bits : null;
}
