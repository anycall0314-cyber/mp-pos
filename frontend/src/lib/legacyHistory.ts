/** 會員頁的舊系統紀錄:照日期分段(後端已經照日期新到舊排好),同一天的單放同一段、單的順序不變 */
export function byDate<T extends { document_date: string }>(docs: T[]): { date: string; docs: T[] }[] {
  const out: { date: string; docs: T[] }[] = [];
  for (const d of docs) {
    const last = out[out.length - 1];
    if (last && last.date === d.document_date) last.docs.push(d);
    else out.push({ date: d.document_date, docs: [d] });
  }
  return out;
}

/**
 * 舊系統的單別代碼寫成店員看得懂的字(全站檢視 E3):E 開頭是銷貨、F 開頭是退貨
 * (跟後端 `legacy/models.py` 認得的正負號同一套);認不得的照原樣。
 */
export function docKind(code: string): string {
  const c = code.trim().toUpperCase();
  if (c.startsWith("E")) return "銷貨";
  if (c.startsWith("F")) return "退貨";
  return code;
}
