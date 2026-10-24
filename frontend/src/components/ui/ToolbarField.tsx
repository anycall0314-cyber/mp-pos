import type { ReactNode } from "react";

import { cx } from "@/lib/uiKeys";

/**
 * 查詢 / 工作對象工具列上「欄名 + 一個控制項」(門市、廠商分類、狀態…;docs/ui-controls.md §1)。
 * 欄名看得到(不靠 placeholder 當唯一欄名),點欄名游標進那一格(用 label 包住)。
 * 放在 `ControlBar`(`.ui-toolbar`)裡:桌面滑鼠用的高度 40px(compact),觸控照舊 44px。
 */
export function ToolbarField({ label, children, className }: { label: string; children: ReactNode; className?: string }) {
  return (
    <label className={cx("ui-tf", className)}>
      <span className="ui-tf-label">{label}</span>
      {children}
    </label>
  );
}

/** 一排查詢 / 工作對象工具列(會換行,不會整頁橫捲) */
export function ControlBar({ children, className, label }: { children: ReactNode; className?: string; label?: string }) {
  return (
    <div className={cx("ui-toolbar", className)} role={label ? "group" : undefined} aria-label={label}>
      {children}
    </div>
  );
}
