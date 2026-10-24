import type { LedgerCheckResult } from "@/api/types";

/**
 * 備份還原、每日對帳的排法(全站檢視 L03)。只排、不改判定。
 */

/** 還原那一塊的四步(字數一樣);只標現在在哪一步,不加「下一步」(紅隊:看起來要按下一步,老闆會以為還原換了手續) */
export const RESTORE_STEPS = ["選檔", "檢查", "確認", "進度"] as const;

/**
 * 現在在第幾步(1 起算):還原排入 / 進行中 / 全公司暫停 = 4;檢查完有摘要 = 2,確認字打對了 = 3;其餘 = 1。
 * 摘要與打字確認照舊在同一塊(紅隊:不要拆開)。
 */
export function restoreStep(s: { pending: boolean; confirmReady: boolean; maintenance: boolean; restoring: boolean }): number {
  if (s.maintenance || s.restoring) return 4;
  if (s.pending) return s.confirmReady ? 3 : 2;
  return 1;
}

/**
 * 每日對帳的檢查項目:有不一致時,不一致的排最上面、「提醒」照舊留在外面、一致的收成「其餘 N 項一致」;
 * 全部一致就照原本整張表(紅隊:畫面上沒有「還沒做完」這一類,不要新造)。
 */
export function splitChecks<T extends Pick<LedgerCheckResult, "ok" | "level">>(results: T[]): { shown: T[]; folded: T[] } {
  const bad = results.filter((r) => r.level !== "info" && !r.ok);
  if (bad.length === 0) return { shown: results, folded: [] };
  const info = results.filter((r) => r.level === "info");
  const good = results.filter((r) => r.level !== "info" && r.ok);
  return { shown: [...bad, ...info], folded: good };
}
