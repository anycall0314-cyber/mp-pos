import { ReactNode, useEffect } from "react";

interface DrawerProps {
  open: boolean;
  title: string;
  onClose: () => void;
  width?: number;
  footer?: ReactNode;
  children: ReactNode;
  /** true 時點背景遮罩 + Escape 都不關閉,僅關閉按鈕能關;
   *  搭配 ProductForm 之類有輸入暫存的表單用,避免誤觸丟資料 */
  lockBackdrop?: boolean;
}

export function Drawer({
  open,
  title,
  onClose,
  width = 480,
  footer,
  children,
  lockBackdrop = false,
}: DrawerProps) {
  useEffect(() => {
    if (!open || lockBackdrop) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose, lockBackdrop]);

  if (!open) return null;
  return (
    <div
      className="drawer-backdrop"
      onClick={lockBackdrop ? undefined : onClose}
    >
      <aside
        className="drawer"
        style={{ width }}
        onClick={(e) => e.stopPropagation()}
      >
        <header className="drawer-header">
          <span>{title}</span>
          <button className="drawer-close" onClick={onClose} aria-label="關閉">
            ×
          </button>
        </header>
        <div className="drawer-body">{children}</div>
        {footer && <footer className="drawer-footer">{footer}</footer>}
      </aside>
    </div>
  );
}
