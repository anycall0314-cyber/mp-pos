// 編到一半、還沒儲存的表單不被默默蓋掉(全站檢視 R02;來源頁、零件範本頁)。跑法:npm test。
//
// 兩件事:
// 1. 只有換了一筆(或改成新增)才重新填表單;同一筆在背景重新讀到、換左邊分類,都不動正在打的字。
// 2. 會丟掉沒存內容的操作(點別筆、新增、取消、×):沒改過直接做;改過要按兩次,第二下要按同一個目標
//    (跟作廢同一套兩段式:4 秒內、半秒內的第二下不算,`components/workbench/useArm`),不跳瀏覽器確認框、不自動儲存。

/** 表單內容與它是從哪一筆來的。`base` = 讀進來(或存好)那一刻的樣子,跟 `form` 不一樣就是改過還沒存 */
export interface Draft<F> {
  key: string | null;
  form: F;
  base: F;
}

/** 改過按第一下時表單上面那一句 */
export const LEAVE_TEXT = "還沒儲存,再按一次放棄";

export function emptyDraft<F>(form: F): Draft<F> {
  return { key: null, form, base: form };
}

/**
 * 現在要編的是 `key` 這一筆;回傳新的 Draft,不用換回 null。
 * - 同一筆:不動(背景刷新、換分類都是這種)。
 * - 收起來(key = null):只記下沒在編;下次打開同一筆會重新讀,不會留著上次放棄的字。
 * - 換一筆:`load()` 讀那一筆;還沒讀到(回 null)就先等,表單不給打(免得把上一筆的字存到這一筆)。
 */
export function syncDraft<F>(draft: Draft<F>, key: string | null, load: () => F | null): Draft<F> | null {
  if (key === draft.key) return null;
  if (key === null) return { ...draft, key: null };
  const form = load();
  if (form === null) return null;
  return { key, form, base: form };
}

/** 存好了:存回來的樣子就是新的基準(不算改過) */
export function savedDraft<F>(key: string, form: F): Draft<F> {
  return { key, form, base: form };
}

/** 跟讀進來那一刻比,改過沒有 */
export function changed<F>(form: F, base: F): boolean {
  return JSON.stringify(form) !== JSON.stringify(base);
}

export function isDirty<F>(draft: Draft<F>): boolean {
  return draft.key !== null && changed(draft.form, draft.base);
}

interface Arm {
  confirm(key: string): boolean;
  reset(): void;
}

/** 會丟掉沒存內容的操作:沒改過直接做;改過第一下只標起來(回 false),同一個 `target` 再按一次才做 */
export function leaveDraft(dirty: boolean, arm: Arm, target: string, go: () => void): boolean {
  if (dirty && !arm.confirm(`leave:${target}`)) return false;
  arm.reset();
  go();
  return true;
}

/** 這個目標是不是按了第一下(按鈕換字用) */
export function leaveArmed(armed: string | null, target: string): boolean {
  return armed === `leave:${target}`;
}
