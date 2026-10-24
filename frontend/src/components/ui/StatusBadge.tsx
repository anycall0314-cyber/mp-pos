import type { ReactNode } from "react";

import { cx } from "@/lib/uiKeys";

/**
 * 顯示狀態(未開通、已停用、限管理、已作廢…;docs/ui-controls.md §1)。純顯示、不能按 —— 沒有 onClick,看起來也不像按鈕。
 * 為什麼這樣要另外寫在旁邊(不要只靠顏色或滑鼠提示)。
 */
export function StatusBadge({ tone = "neutral", children, className }: { tone?: "neutral" | "info" | "success" | "warn" | "danger"; children: ReactNode; className?: string }) {
  return <span className={cx("ui-badge", tone !== "neutral" && tone, className)}>{children}</span>;
}
