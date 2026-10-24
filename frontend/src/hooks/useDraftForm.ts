import { useEffect, useState } from "react";

import { useArm } from "@/components/workbench/useArm";
import { emptyDraft, isDirty, leaveArmed, leaveDraft, savedDraft, syncDraft, type Draft } from "@/lib/draftGuard";

/**
 * 主檔頁的表單草稿(全站檢視 R02 / V01;規則在 lib/draftGuard.ts):
 * 只在換了一筆(`formKey` 變了)時重新填;背景重新讀到不蓋掉正在打的字;那一筆還沒讀到 `ready` 是 false(不給表單)。
 * 會丟掉沒存內容的操作走 `leave(目標, 要做的事)`:沒改過直接做,改過要同一個目標按兩次。
 *
 * `load()` 回那一筆的表單(還沒讀到回 null);`deps` 是 load 用到、讀到之後才有的東西(那一筆的資料)。
 */
export function useDraftForm<F>(empty: F, formKey: string | null, load: () => F | null, deps: unknown[]) {
  const [draft, setDraft] = useState<Draft<F>>(() => emptyDraft(empty));
  const arm = useArm();
  useEffect(() => {
    const next = syncDraft(draft, formKey, load);
    if (!next) return;
    setDraft(next);
    if (next.key !== null) arm.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [formKey, ...deps]);
  const dirty = isDirty(draft);
  return {
    form: draft.form,
    /** 現在顯示的表單就是 `formKey` 那一筆的 */
    ready: formKey !== null && draft.key === formKey,
    dirty,
    /** 改過按第一下時,畫面要寫那一句(`LEAVE_TEXT`) */
    warning: arm.armed !== null,
    patch<K extends keyof F>(k: K, v: F[K]) {
      setDraft((d) => ({ ...d, form: { ...d.form, [k]: v } }));
    },
    /** 存好了:存回來的樣子就是新的基準 */
    saved(key: string, form: F) {
      setDraft(savedDraft(key, form));
    },
    leave(target: string, go: () => void) {
      leaveDraft(dirty, arm, target, go);
    },
    armed(target: string) {
      return leaveArmed(arm.armed, target);
    },
  };
}
