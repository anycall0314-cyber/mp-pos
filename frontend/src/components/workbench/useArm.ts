import { useEffect, useRef, useState } from "react";

/**
 * 不是一顆獨立按鈕的兩段式(切換分頁、點狀態節點這種):第一次按只標起來、換字,4 秒內再按一次才算
 * (跟 ArmButton 同一套:半秒內的第二下不算 —— 滑鼠連點不是看過之後再按)。全站檢視 G1:取代瀏覽器的確認框。
 *
 *   const arm = useArm();
 *   if (!arm.confirm("complete")) return;   // 第一次:回 false、換字
 *   arm.armed === "complete" ? "再按一次完成" : "完成"
 */
export function useArm(ms = 4000) {
  const [armed, setArmed] = useState<string | null>(null);
  const armedRef = useRef<string | null>(null);
  const at = useRef(0);
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(timer.current), []);

  function set(k: string | null) {
    armedRef.current = k;
    setArmed(k);
  }

  function confirm(key: string): boolean {
    if (armedRef.current === key) {
      if (Date.now() - at.current < 500) return false;
      window.clearTimeout(timer.current);
      set(null);
      return true;
    }
    set(key);
    at.current = Date.now();
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => set(null), ms);
    return false;
  }

  return { armed, confirm, reset: () => set(null) };
}
