import type { IntakeItem } from "@/api/types";

/**
 * 進貨匯入:單據總額旁邊並排的「明細合計」(全站檢視 V06e,紅隊:兩個數字要同時看得到,不用捲到底才知道對不對得上)。
 * 跟過帳時伺服器核對的同一個算法(`identity/services.py` 的單據總額平衡):每一行 實際單價 × 實際數量,駁回的不算;
 * 還沒確認的那幾行也先算進去(確認完不是駁回就會算)。差超過 1 元伺服器就擋過帳,這裡只是先標出來。
 */
export const TOTAL_TOLERANCE = 1;

export function linesTotal(items: Pick<IntakeItem, "match_status" | "effective_unit_price" | "effective_qty">[]): number {
  return items
    .filter((it) => it.match_status !== "rejected")
    .reduce((sum, it) => sum + Number(it.effective_unit_price || 0) * it.effective_qty, 0);
}

/** 單據總額 − 明細合計;沒填單據總額、或差在容差裡 = null(不標) */
export function totalGap(documentTotal: string | null, lines: number): number | null {
  if (documentTotal === null || documentTotal === "") return null;
  const gap = Number(documentTotal) - lines;
  return Math.abs(gap) > TOTAL_TOLERANCE ? gap : null;
}
