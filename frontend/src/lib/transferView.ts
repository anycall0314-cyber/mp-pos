// 調撥頁(全站檢視 V03):一進來先看清單,按「新增調撥」才是開單的工作台。跑法:npm test。

/** 在清單頁收到的一串鍵是不是條碼槍刷的(6 個字以上、1.5 秒內打完再按 Enter;人手打不會這麼快) */
export function scannedOnList(buf: string, elapsedMs: number): boolean {
  return buf.length >= 6 && elapsedMs <= 1500;
}
