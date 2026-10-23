import { money } from "./money.ts";

/**
 * 打烊實點(owner 2026-10-23「實點加上去」;規則在 backend/apps/cash/models.py 的 CashCount)。
 * 差額 = 點到 − 當下應有(負的 = 短少)。只是紀錄,不改帳。
 */
export function diffText(diff: number): string {
  if (diff === 0) return "相符";
  return diff < 0 ? `短少 ${money(-diff)}` : `多 ${money(diff)}`;
}

/** 打進來的「點到多少」:整數、不能是負的;空的 / 看不懂 = null(不能送) */
export function countedValue(raw: string): number | null {
  const t = raw.trim();
  return /^\d+$/.test(t) ? Number(t) : null;
}
