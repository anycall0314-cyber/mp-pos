/**
 * 結帳拆帳(全站檢視 A10):點進還是 0 / 空的那一格,自動填入還差多少(一半現金一半刷卡,不用心算)。
 * 已經有數字的格子不動;已經收夠(或收超過)不填。回 null = 不用改。
 */
import { intStr } from "./money.ts";

export function fillRemaining(current: string | undefined, remaining: number): string | null {
  if (!(remaining > 0)) return null;
  if (Number(intStr(current ?? "")) !== 0) return null;
  return String(Math.trunc(remaining));
}
