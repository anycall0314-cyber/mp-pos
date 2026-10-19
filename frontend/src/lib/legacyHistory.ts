/** 會員頁的舊 POS 紀錄:照日期分段(後端已經照日期新到舊排好),同一天的單放同一段、單的順序不變 */
export function byDate<T extends { document_date: string }>(docs: T[]): { date: string; docs: T[] }[] {
  const out: { date: string; docs: T[] }[] = [];
  for (const d of docs) {
    const last = out[out.length - 1];
    if (last && last.date === d.document_date) last.docs.push(d);
    else out.push({ date: d.document_date, docs: [d] });
  }
  return out;
}
