import { useCallback, useRef, useState } from "react";

import type { CellState } from "@/lib/settingsTabs";

/**
 * 自動存的格子各自的存檔狀態(全站檢視 L02)。`save(格子, 改成的值, 送出)`:
 * 送出前記「存檔中」與改成的值,成功記「已存」,失敗記「沒存成」並留著改成的值(畫面照它顯示);
 * `retry(格子)` 用同一個值再送一次(勾選、單選再點一次會變成改回去,所以沒存成要能直接重送)。
 * 同一格連改兩次、回應先後顛倒時只認最後一次送的(不然先送的晚回來會蓋掉後送的結果)。
 */
export function useCellSaves() {
  const [, setCellsState] = useState<Record<string, { state: CellState; value: unknown }>>({});
  // 同一瞬間觸發兩次(離開格子又馬上再離開)時,第二次要看得到第一次剛記的:判斷一律讀這份,畫面照 state 重畫
  const now = useRef<Record<string, { state: CellState; value: unknown }>>({});
  const setCells = useCallback((f: (c: Record<string, { state: CellState; value: unknown }>) => Record<string, { state: CellState; value: unknown }>) => {
    now.current = f(now.current);
    setCellsState(now.current);
  }, []);
  const senders = useRef(new Map<string, { value: unknown; send: () => Promise<unknown> }>());
  const latest = useRef(new Map<string, number>());
  const save = useCallback(async (key: string, value: unknown, send: () => Promise<unknown>) => {
    const seq = (latest.current.get(key) ?? 0) + 1;
    latest.current.set(key, seq);
    senders.current.set(key, { value, send });
    setCells((c) => ({ ...c, [key]: { state: "saving", value } }));
    let ok = true;
    try {
      await send();
    } catch {
      ok = false;
    }
    if (latest.current.get(key) !== seq) return;
    setCells((c) => ({ ...c, [key]: { state: ok ? "saved" : "failed", value } }));
  }, [setCells]);
  const retry = useCallback(
    (key: string) => {
      const last = senders.current.get(key);
      if (last) void save(key, last.value, last.send);
    },
    [save],
  );
  /** 沒存成之後又改回原本的值:拿掉這一格的狀態(也作廢還在路上的那一次) */
  const clear = useCallback((key: string) => {
    latest.current.set(key, (latest.current.get(key) ?? 0) + 1);
    senders.current.delete(key);
    setCells((c) => {
      const next = { ...c };
      delete next[key];
      return next;
    });
  }, [setCells]);
  function get<V>(key: string) {
    return now.current[key] as { state: CellState; value: V } | undefined;
  }
  return { get, save, retry, clear };
}
