import { useEffect, useRef, useState } from "react";

/**
 * Modal 草稿共用 hook。
 *
 * 三層自動存:
 * 1. state 變動 → debounce 600ms 寫 localStorage
 * 2. 元件 unmount(切分頁 / 關抽屜)同步 flush
 * 3. beforeunload(關瀏覽器)同步 flush
 *
 * 載入時機:
 * - modal 開啟且 isEditMode=false 時讀 localStorage,若有 draft 回給呼叫端讓他顯示 banner
 *
 * 清除時機:
 * - 呼叫端送出成功 → markSavedAndClear()
 * - 使用者選擇捨棄 → discardDraft() 或 markSavedAndClear()
 *
 * 編輯既有資料時:isEditMode=true 整套草稿系統關閉(不存、不載)
 */
export interface DraftPayload<T> {
  state: T;
  savedAt: string;
}

export interface UseModalDraftOpts<T> {
  /** 不同 modal 用不同 key 避免衝突;例:"product-form-draft-new"。 */
  key: string;
  /** Modal 是否開啟。關閉時不寫不讀。 */
  open: boolean;
  /** 當前 state。 */
  state: T;
  /** 編輯既有資料時 true → 整套草稿系統關閉。 */
  isEditMode: boolean;
  /** 判斷 state 是否「空白未動過」。空白就不寫,避免覆蓋之前的真草稿。 */
  isEmpty: (s: T) => boolean;
  /** 自訂序列化(預設 JSON.stringify)。Set / Map 等需要自己處理。 */
  serialize?: (s: T) => unknown;
  /** 自訂反序列化(預設 identity)。 */
  deserialize?: (raw: unknown) => T;
}

export interface UseModalDraftResult<T> {
  /** 載入時偵測到的草稿(包含 savedAt)。呼叫端用來顯示 banner。 */
  draft: DraftPayload<T> | null;
  /** 載入草稿後呼叫:把 draft 套用到自己的 state(由呼叫端負責 setState),然後通知 hook 已套用。 */
  consumeDraft: () => void;
  /** 使用者選「捨棄草稿」時呼叫。 */
  discardDraft: () => void;
  /** 送出成功 / 明確捨棄離開時呼叫:停止 unmount flush + 清除 localStorage。 */
  markSavedAndClear: () => void;
}

export function useModalDraft<T>({
  key,
  open,
  state,
  isEditMode,
  isEmpty,
  serialize,
  deserialize,
}: UseModalDraftOpts<T>): UseModalDraftResult<T> {
  const [draft, setDraft] = useState<DraftPayload<T> | null>(null);
  const skipRef = useRef(false);
  const flushRef = useRef<() => void>(() => {});

  const ser = serialize ?? ((s: T) => s as unknown);
  const de = deserialize ?? ((raw: unknown) => raw as T);

  // 開啟時 reset skipRef + 讀 localStorage
  useEffect(() => {
    if (!open) return;
    skipRef.current = false;
    if (isEditMode) {
      setDraft(null);
      return;
    }
    try {
      const raw = localStorage.getItem(key);
      if (raw) {
        const parsed = JSON.parse(raw) as { state: unknown; savedAt: string };
        if (parsed?.state && parsed?.savedAt) {
          setDraft({ state: de(parsed.state), savedAt: parsed.savedAt });
        } else {
          setDraft(null);
        }
      } else {
        setDraft(null);
      }
    } catch {
      setDraft(null);
    }
  }, [open, isEditMode, key]);

  // debounce auto-save
  useEffect(() => {
    if (!open || isEditMode) return;
    if (skipRef.current) return;
    if (isEmpty(state)) return;
    const t = setTimeout(() => {
      try {
        localStorage.setItem(
          key,
          JSON.stringify({
            state: ser(state),
            savedAt: new Date().toISOString(),
          }),
        );
      } catch {}
    }, 600);
    return () => clearTimeout(t);
  }, [state, open, isEditMode, key]);

  // 用 ref 保留最新版的 flush 函數
  useEffect(() => {
    flushRef.current = () => {
      if (skipRef.current) return;
      if (!open || isEditMode) return;
      if (isEmpty(state)) return;
      try {
        localStorage.setItem(
          key,
          JSON.stringify({
            state: ser(state),
            savedAt: new Date().toISOString(),
          }),
        );
      } catch {}
    };
  }, [state, open, isEditMode, key]);

  // beforeunload + unmount flush
  useEffect(() => {
    const onBeforeUnload = () => flushRef.current();
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => {
      window.removeEventListener("beforeunload", onBeforeUnload);
      flushRef.current();
    };
  }, []);

  return {
    draft,
    consumeDraft: () => {
      setDraft(null);
      try {
        localStorage.removeItem(key);
      } catch {}
    },
    discardDraft: () => {
      setDraft(null);
      try {
        localStorage.removeItem(key);
      } catch {}
    },
    markSavedAndClear: () => {
      skipRef.current = true;
      try {
        localStorage.removeItem(key);
      } catch {}
    },
  };
}
