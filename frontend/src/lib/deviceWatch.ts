// 平台管理 → 型號庫(型號庫每天自動讀手機王加新機)畫面上的字。規則在 backend/apps/catalog/device_watch.py。
import type { DeviceWatchRun } from "@/api/types";

/** 一次檢查寫成一行:「10/16 05:31 成功 · 清單 572 支 · 加入 1 · 待確認 0 · 等資料 0」;沒成功的寫原因。 */
export function runLine(run: DeviceWatchRun | null): string {
  if (!run) return "還沒有檢查過";
  const when = run.finished_at ? stamp(run.finished_at) : `${run.day.slice(5).replace("-", "/")} 檢查中`;
  const c = run.counts ?? {};
  const listed = (c.list_cellphone ?? 0) + (c.list_tablet ?? 0) + (c.list_wearable ?? 0);
  const parts = [when, run.ok ? "成功" : "沒有成功"];
  if (listed) parts.push(`清單 ${listed} 支`);
  parts.push(`加入 ${c.added ?? 0}`, `補上 ${c.updated ?? 0}`, `待確認 ${c.review ?? 0}`, `等資料 ${c.waiting ?? 0}`);
  return parts.join(" · ");
}

/** 「10/16 05:31」(這台電腦的時區) */
export function stamp(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(d.getMonth() + 1)}/${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

/** 沒成功時要講的事(讀不到的原因);成功時只留「建了幾個品號」「補上…」這種。 */
export function runNotes(run: DeviceWatchRun | null): string[] {
  return run?.notes ?? [];
}

/** 容量 / 顏色 / 連線寫成一格:「256GB、512GB」;沒有寫「—」。 */
export function listText(values: string[]): string {
  return values.length ? values.join("、") : "—";
}
