import { useEffect, useState } from "react";

/**
 * 工作台的訊息條:畫面下方中間,幾秒自己消失,不擋操作。
 * 取代 alert / confirm 彈出視窗;可以帶一個動作(例如「復原」)。
 */
export type ToastKind = "" | "ok" | "err";

interface ToastAction {
  label: string;
  fn: () => void;
}

interface ToastItem {
  id: number;
  msg: string;
  kind: ToastKind;
  action?: ToastAction;
  ms: number;
}

let seq = 0;
let push: ((t: ToastItem) => void) | null = null;

export function toast(
  msg: string,
  kind: ToastKind = "",
  opts?: { ms?: number; action?: ToastAction },
) {
  const ms =
    opts?.ms ?? (opts?.action ? 7000 : kind === "err" ? 5000 : 2500);
  push?.({ id: ++seq, msg, kind, action: opts?.action, ms });
}

export function ToastHost() {
  const [items, setItems] = useState<ToastItem[]>([]);

  useEffect(() => {
    const timers = new Set<number>();
    push = (t) => {
      // 最多疊三則,舊的先讓位
      setItems((cur) => [...cur.slice(-2), t]);
      const timer = window.setTimeout(() => {
        timers.delete(timer);
        setItems((cur) => cur.filter((x) => x.id !== t.id));
      }, t.ms);
      timers.add(timer);
    };
    return () => {
      push = null;
      timers.forEach((t) => window.clearTimeout(t));
    };
  }, []);

  if (items.length === 0) return null;
  return (
    <div className="wb-toasts" role="status" aria-live="polite">
      {items.map((t) => (
        <div key={t.id} className={`wb-toast${t.kind ? " " + t.kind : ""}`}>
          {t.msg}
          {t.action && (
            <button
              type="button"
              onClick={() => {
                setItems((cur) => cur.filter((x) => x.id !== t.id));
                t.action!.fn();
              }}
            >
              {t.action.label}
            </button>
          )}
        </div>
      ))}
    </div>
  );
}
