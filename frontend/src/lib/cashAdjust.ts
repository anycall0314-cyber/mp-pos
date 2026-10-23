/**
 * 現金調整:事由決定方向(全站檢視 E7;伺服器同一份規則在 `cash.models.CashAdjustment.REASON_DIRECTION`)。
 * 以前方向、事由各選各的,選了「領現存銀行」忘了改方向 = 記成放進櫃子,營業日報的結餘差兩倍。
 * 盤點校正、其他兩個方向都可能:回 null,照人選的。
 */
export function directionOfReason(reason: string): "in" | "out" | null {
  if (reason === "refill") return "in";
  if (reason === "deposit" || reason === "owner_take") return "out";
  return null;
}
