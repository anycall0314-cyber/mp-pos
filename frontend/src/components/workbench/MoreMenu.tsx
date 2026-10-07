import { ReactNode, useEffect, useRef, useState } from "react";

interface Props {
  /** 選單裡的東西;拿到的 close 用來在做完之後把選單收起來 */
  children: (close: () => void) => ReactNode;
  disabled?: boolean;
  /** 按鈕上的字(不給就是「更多」) */
  label?: string;
  /** 按鈕的樣式(不給就是開單頁頁首的小按鈕) */
  buttonClass?: string;
}

/**
 * 開單頁頁首的「更多」:放不常用、按錯代價大的動作(清空草稿)。
 * 跟掃碼框、儲存 / 結帳隔開,不會在連續刷碼時誤觸。點別的地方或按 Esc 收起來。
 */
export function MoreMenu({
  children,
  disabled,
  label = "更多",
  buttonClass = "wb-btn small",
}: Props) {
  const [open, setOpen] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onDown(e: MouseEvent) {
      if (!boxRef.current?.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div className="ws-more" ref={boxRef}>
      <button
        type="button"
        className={buttonClass}
        aria-haspopup="menu"
        aria-expanded={open}
        disabled={disabled}
        onClick={() => setOpen((v) => !v)}
      >
        {label}
      </button>
      {open && (
        <div className="ws-more-menu" role="menu">
          {children(() => setOpen(false))}
        </div>
      )}
    </div>
  );
}
