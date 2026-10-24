import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";

import { cx } from "@/lib/uiKeys";

/**
 * 執行動作的按鈕(docs/ui-controls.md §1)。外觀沿用全站的 `.btn`(不另外一套 CSS):
 * variant:default 一般(中性細框)/ primary 主要(藍底;一個工作區至多一個)/ danger 危險 / text 文字型(低頻輔助)。
 * size:md 44px / sm 32px(桌面表格列裡)/ lg 48px(掃碼、結帳)。預設 type="button"(真的送表單才寫 submit)。
 * pending:處理中 —— 不能再按、位置不變,字換成 pendingLabel(沒給就照原本的字)。`primary` 不拿來表示「選中」(那是 Tabs / SegmentedControl)。
 * className 只放排版用的(寬度、位置),不要放顏色、圓角、留白。
 */
export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "default" | "primary" | "danger" | "text";
  size?: "md" | "sm" | "lg";
  pending?: boolean;
  pendingLabel?: ReactNode;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "default", size = "md", pending = false, pendingLabel, type = "button", disabled, className, children, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      disabled={disabled || pending}
      aria-busy={pending || undefined}
      className={cx(
        "btn",
        variant === "primary" && "primary",
        variant === "danger" && "danger",
        variant === "text" && "ui-btn-text",
        size === "sm" && "small",
        size === "lg" && "ui-btn-lg",
        className,
      )}
      {...rest}
    >
      {pending && pendingLabel !== undefined ? pendingLabel : children}
    </button>
  );
});
