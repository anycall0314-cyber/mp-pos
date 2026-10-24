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
  /** true 時整個抽屜(頁首、內容、頁尾)都不能動:上面疊了另一個面板(看照片與規格)時用,
   *  不然可以用鍵盤(Tab)繞回下面這一個按東西 */
  frozen?: boolean;
  /** true = 正在送出(全站控制項 F04):× / Escape / 點遮罩都不關,整個抽屜不能動,送完(成功或失敗)才放開。
   *  關掉抽屜不會取消已經送出去的寫入,所以送出中不給關,免得以為取消了、或換成另一份可以改的表單 */
  busy?: boolean;
}

export function Drawer({
  open,
  title,
  onClose,
  width = 480,
  footer,
  children,
  lockBackdrop = false,
  frozen = false,
  busy = false,
}: DrawerProps) {
  useEffect(() => {
    if (!open || lockBackdrop || busy) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose, lockBackdrop, busy]);

  if (!open) return null;
  return (
    <div
      className="drawer-backdrop"
      onClick={lockBackdrop || busy ? undefined : onClose}
    >
      <aside
        className="drawer"
        style={{ width }}
        onClick={(e) => e.stopPropagation()}
        {...(frozen || busy ? { inert: "" } : {})}
        aria-busy={busy || undefined}
      >
        <header className="drawer-header">
          <span>{title}</span>
          <button className="drawer-close" onClick={onClose} aria-label="關閉" disabled={busy}>
            ×
          </button>
        </header>
        <div className="drawer-body">{children}</div>
        {footer && <footer className="drawer-footer">{footer}</footer>}
      </aside>
    </div>
  );
}
