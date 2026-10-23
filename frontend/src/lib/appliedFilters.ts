/**
 * 清單上面那一排「已套用的條件」(2026-10-23,UI 改善計劃 5.4):每一頁同一個寫法 ——
 * 只列跟這一頁預設不一樣的條件(「門市:民生店」「進貨:10-01 ~ 10-23」),旁邊一顆「清除條件」回到預設。
 * 有「查詢」鍵的頁,列的是**已經查的那一份**(框裡改了還沒按查詢的不算),清單上的資料就是照這幾條查的。
 */
export interface Applied {
  label: string;
  value: string;
}

/** 只留有值的條件(空字串、null、false 不列) */
export function appliedList(items: (Applied | null | false | undefined)[]): Applied[] {
  return items.filter((x): x is Applied => !!x && x.value.trim() !== "");
}

/** 一個條件:值是空的就不列 */
export function cond(label: string, value: string | null | undefined): Applied | null {
  return value && value.trim() ? { label, value: value.trim() } : null;
}

/** 日期:今年的寫月-日,別年的寫全 */
export function dayText(day: string, now: Date = new Date()): string {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) return day;
  return Number(day.slice(0, 4)) === now.getFullYear() ? day.slice(5) : day;
}

/** 起迄:兩個都空 = 沒有條件;同一天寫一天;只有一邊寫「起」/「到」 */
export function rangeText(from: string, to: string, now: Date = new Date()): string {
  if (!from && !to) return "";
  if (from && to) return from === to ? dayText(from, now) : `${dayText(from, now)} ~ ${dayText(to, now)}`;
  return from ? `${dayText(from, now)} 起` : `到 ${dayText(to, now)}`;
}

/** 起迄跟預設一樣(例:本月、今天)就不算套用條件 */
export function rangeCond(
  label: string,
  from: string,
  to: string,
  fallback: { from: string; to: string } = { from: "", to: "" },
  now: Date = new Date(),
): Applied | null {
  if (from === fallback.from && to === fallback.to) return null;
  // 預設有期間、現在兩格都空 = 看全部日期(也是一個跟預設不一樣的條件)
  if (!from && !to) return cond(label, "全部");
  return cond(label, rangeText(from, to, now));
}
