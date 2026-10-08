/**
 * 「新增手機型號」每個容量的建議售價。規則只有這一份(有測試)。
 *
 * 同一款手機不同容量價錢不一樣(owner 2026-10-08:以前整批只有一個價錢,建完要一個一個改)。
 * 同一個容量不分品況都帶這個價錢:已拆封、中古機本來就每一台另外定價,這個數字只是沒定價時的預設。
 */
import { intStr } from "./money.ts";

/** 打在每個容量那一格裡的字({容量: 還沒整理的輸入})。拿掉的容量留著,再加回來時字還在。 */
export type CapacityPrices = Record<string, string>;

/** 某一個容量那一格現在的字(沒打過是空的)。容量的字可以是任何東西,只認自己記的那一份。 */
export function priceOf(prices: CapacityPrices, capacity: string): string {
  return Object.hasOwn(prices, capacity) ? prices[capacity] : "";
}

/**
 * 改某一個容量那一格。建議售價沒有負的:**開頭的**負號直接拿掉(不然要到按預覽才被伺服器整批退回)。
 * 只拿開頭的:貼上 `1e-3` 這種寫法時,中間那個負號是數字的一部分,拿掉會變成 1000。
 */
export function withPrice(
  prices: CapacityPrices,
  capacity: string,
  value: string,
): CapacityPrices {
  return { ...prices, [capacity]: value.replace(/^\s*-+/, "") };
}

/**
 * 送給伺服器的:**現在選的**每一個容量各一格,收成整數元(沒填的是 "0")。
 * 已經拿掉的容量不送 —— 伺服器看到沒有要建的容量會當成寫錯、整批退回。
 */
export function pricesPayload(
  capacities: readonly string[],
  prices: CapacityPrices,
): Record<string, string> {
  // 用 fromEntries 組:容量的字是人打的,叫什麼都要當成一般的鍵(一格一格指定的話,`__proto__` 這種字會被吃掉)
  return Object.fromEntries(
    capacities
      // 空白的容量伺服器會丟掉(不建),價錢也就不送
      .filter((cap) => cap.trim() !== "")
      .map((cap) => [cap, intStr(priceOf(prices, cap))]),
  );
}

/** 範本帶進來的容量 / 顏色:去頭尾空白、丟掉空的、同一個字只留一個(照原本的順序)。 */
export function tidyChips(list: readonly string[]): string[] {
  const out: string[] = [];
  for (const raw of list) {
    const text = String(raw ?? "").trim();
    if (text !== "" && !out.includes(text)) out.push(text);
  }
  return out;
}

/**
 * 「這一次要建的是什麼」的指紋:預覽時記下來,按「確認建立」時再算一次,不一樣就不建、請人重新預覽。
 * 預覽之後內容還可能被換掉(例:範本的資料比較晚才回來,把容量整份換掉)—— 那時畫面上的清單與價錢已經不是要建的那一批。
 * 「是不是預覽」與「哪裡不同的理由」不算在內(理由是預覽之後才填的)。
 */
export function planKey(payload: object): string {
  const { dry_run: _dry, distinct_reasons: _why, ...plan } = payload as Record<string, unknown>;
  return JSON.stringify(sortKeys(plan));
}

function sortKeys(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sortKeys);
  if (value && typeof value === "object") {
    const rec = value as Record<string, unknown>;
    return Object.fromEntries(Object.keys(rec).sort().map((k) => [k, sortKeys(rec[k])]));
  }
  return value;
}
