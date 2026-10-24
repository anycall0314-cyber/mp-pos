import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";

import { cx } from "@/lib/uiKeys";

/**
 * 只有圖示的動作(×、箭頭、眼睛…;docs/ui-controls.md §1、§4)。`label` 一定要給,寫「動作 + 對象」
 * (例:「移除第 2 筆商品」「關閉維修歷史」「清除會員搜尋」)—— 念給讀螢幕的聽、也是滑鼠停上去的提示。
 * 看起來小(32px),觸控裝置的有效範圍至少 44 × 44px(CSS 管)。
 */
export interface IconButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "aria-label"> {
  label: string;
  children: ReactNode;
}

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { label, title, type = "button", className, children, ...rest },
  ref,
) {
  return (
    <button ref={ref} type={type} aria-label={label} title={title ?? label} className={cx("ui-icon-btn", className)} {...rest}>
      <span aria-hidden="true">{children}</span>
    </button>
  );
});
