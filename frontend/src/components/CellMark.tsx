import type { useCellSaves } from "@/hooks/useCellSaves";
import { cellText } from "@/lib/settingsTabs";

/**
 * 離開格子就存 / 點了就存的那一格旁邊:「存檔中 / 已存 / 沒存成 重送」(全站檢視 L02;平台管理也用,全站控制項 F03)。
 * 沒存成可以直接按一下用同一個值重送(勾選再點一次會變成改回去)。
 */
export function CellMark({ cell, k }: { cell: ReturnType<typeof useCellSaves>; k: string }) {
  const state = cell.get(k)?.state;
  if (!state) return null;
  if (state === "failed") {
    return (
      <button type="button" className="cell-mark failed" onClick={() => cell.retry(k)}>
        {cellText(state)} 重送
      </button>
    );
  }
  return <span className={`cell-mark ${state}`}>{cellText(state)}</span>;
}
