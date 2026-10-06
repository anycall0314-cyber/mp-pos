import { MouseEvent, useEffect, useRef, useState } from "react";

interface Props {
  label: string;
  /** 第一次按之後換成這幾個字;沒給就是「再按一次」加上原本的字(入庫 → 再按一次入庫) */
  armedLabel?: string;
  onConfirm: () => Promise<unknown> | void;
  className?: string;
  disabled?: boolean;
  title?: string;
}

/** 第一次按之後這麼久以內的第二下不算(滑鼠連點兩下不是「看過之後再按一次」) */
const DOUBLE_CLICK_MS = 500;

/**
 * 兩段式按鈕:第一次按只換字,4 秒內再按一次才真的做。
 * 取代 confirm 彈出視窗(作廢、入庫這種按錯代價大的動作)。
 * 換上去的字帶著動作名稱:同一列有兩顆(入庫、作廢)時,不會兩顆都變成一樣的「再按一次」。
 */
export function ArmButton({
  label,
  armedLabel,
  onConfirm,
  className = "wb-btn",
  disabled,
  title,
}: Props) {
  const [armed, setArmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const timer = useRef<number>();
  const armedAt = useRef(0);
  const running = useRef(false);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      window.clearTimeout(timer.current);
    };
  }, []);

  async function click(e: MouseEvent) {
    e.stopPropagation();
    if (running.current) return;
    if (!armed) {
      setArmed(true);
      armedAt.current = Date.now();
      timer.current = window.setTimeout(() => setArmed(false), 4000);
      return;
    }
    if (Date.now() - armedAt.current < DOUBLE_CLICK_MS) return;
    window.clearTimeout(timer.current);
    running.current = true;
    setBusy(true);
    try {
      await onConfirm();
    } finally {
      running.current = false;
      // 做完之後這一列可能已經不在畫面上
      if (alive.current) {
        setBusy(false);
        setArmed(false);
      }
    }
  }

  return (
    <button
      type="button"
      className={`${className}${armed ? " armed" : ""}`}
      disabled={disabled || busy}
      onClick={click}
      title={title}
    >
      {armed ? (armedLabel ?? `再按一次${label}`) : label}
    </button>
  );
}
