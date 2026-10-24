import { ReactNode, useEffect, useId, useRef, useState } from "react";

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
 * 是「展開 / 收起」(disclosure),不是完整的選單(全站控制項 T04):按鈕帶 aria-expanded / aria-controls,
 * 展開後照一般 Tab 順序走到裡面的按鈕;Esc 收起、游標回到「更多」;點外面收起、不搶別的格子的游標。
 * 打開不會執行裡面任何一個動作;收起時裡面的兩段式按鈕跟著重來(元件卸下)。
 */
export function MoreMenu({
  children,
  disabled,
  label = "更多",
  buttonClass = "wb-btn small",
}: Props) {
  const [open, setOpen] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelId = useId();

  // 裡面的動作做完收起來:游標在裡面的就回到「更多」(裡面那顆不見了,游標不會掉到頁面最上面;
  // 那個動作接著打開的視窗關掉時也回得到這裡,全站控制項 MC-03)
  function closeFromInside() {
    const inside = !!boxRef.current?.contains(document.activeElement);
    setOpen(false);
    if (inside) triggerRef.current?.focus();
  }

  useEffect(() => {
    if (!open) return;
    function onDown(e: MouseEvent) {
      if (!boxRef.current?.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key !== "Escape") return;
      // 游標在裡面(或在「更多」上)才把它帶回「更多」;在別的地方按 Esc 只收起來
      const inside = !!boxRef.current?.contains(document.activeElement);
      setOpen(false);
      if (inside) triggerRef.current?.focus();
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
        ref={triggerRef}
        type="button"
        className={buttonClass}
        aria-expanded={open}
        aria-controls={panelId}
        disabled={disabled}
        onClick={() => setOpen((v) => !v)}
      >
        {label}
      </button>
      {open && (
        <div className="ws-more-menu" id={panelId}>
          {children(closeFromInside)}
        </div>
      )}
    </div>
  );
}
