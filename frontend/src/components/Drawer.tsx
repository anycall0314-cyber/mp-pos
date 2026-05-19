import { ReactNode, useEffect } from "react";

interface DrawerProps {
  open: boolean;
  title: string;
  onClose: () => void;
  width?: number;
  footer?: ReactNode;
  children: ReactNode;
}

export function Drawer({
  open,
  title,
  onClose,
  width = 520,
  footer,
  children,
}: DrawerProps) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="drawer-backdrop" onClick={onClose}>
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
