/**
 * 記在這台電腦的小設定(上次選的電信業者這種):讀不到、寫不進去(無痕視窗、被擋)就當沒有,畫面照常。
 */
export function readKey(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function writeKey(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    // 寫不進去就算了:下次再選一次
  }
}

/** 記著的編號還在清單上才用;看不懂、已經沒有的當成沒記 */
export function pickRemembered(raw: string | null, ids: number[]): number | null {
  const n = Number(raw);
  return Number.isInteger(n) && n > 0 && ids.includes(n) ? n : null;
}
