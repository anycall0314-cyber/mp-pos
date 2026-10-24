import { useEffect, useId, useRef, type KeyboardEvent } from "react";

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/** 框裡現在按得到的東西(看不到的、在 inert 裡的不算) */
function focusables(box: HTMLElement): HTMLElement[] {
  return Array.from(box.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
    (el) => !el.closest("[inert]") && el.getClientRects().length > 0,
  );
}

/**
 * 抽屜 / 彈窗的焦點規則(全站控制項 MC-03):
 * - 有名字:標題的 id 給 aria-labelledby(`titleId`)。
 * - 打開時游標進到框裡:裡面已經有 autoFocus 的就照它,沒有就停在框本身(不會自己點到任何按鈕)。
 * - Tab / Shift+Tab 在框裡繞,不會跑到背後的頁面(背後的儲存、導覽按不到)。
 * - 關掉時游標回到打開它的那顆按鈕;頁面自己已經把游標移到別處(例:結帳完回掃碼框)就不搶。
 * 什麼時候能關(Escape、點遮罩、送出中)照各自原本的規則,這裡不管。
 *
 *   const dlg = useDialogFocus(open);
 *   <div role="dialog" aria-modal="true" aria-labelledby={dlg.titleId} ref={dlg.ref} tabIndex={-1} onKeyDown={dlg.onKeyDown}>
 *     <div id={dlg.titleId}>標題</div>
 */
export function useDialogFocus<T extends HTMLElement = HTMLDivElement>(open: boolean) {
  const ref = useRef<T>(null);
  const titleId = useId();
  const opener = useRef<Element | null>(null);
  const wasOpen = useRef(false);
  // 打開的那一次記下游標原本在哪(要在裡面的 autoFocus 搶走之前記)
  if (open && !wasOpen.current && typeof document !== "undefined") opener.current = document.activeElement;
  wasOpen.current = open;

  useEffect(() => {
    if (!open) return;
    const box = ref.current;
    if (box && !box.contains(document.activeElement)) box.focus();
    return () => {
      const back = opener.current;
      opener.current = null;
      const now = document.activeElement;
      if (back instanceof HTMLElement && back.isConnected && (!now || now === document.body)) back.focus();
    };
  }, [open]);

  function onKeyDown(e: KeyboardEvent) {
    // 裡面的元件自己處理了 Tab(例:搜尋盒選候選)就不動
    if (e.key !== "Tab" || e.defaultPrevented) return;
    const box = ref.current;
    if (!box) return;
    const items = focusables(box);
    if (items.length === 0) {
      e.preventDefault();
      box.focus();
      return;
    }
    const first = items[0];
    const last = items[items.length - 1];
    const at = document.activeElement;
    if (e.shiftKey && (at === first || at === box)) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && at === last) {
      e.preventDefault();
      first.focus();
    }
  }

  return { ref, titleId, onKeyDown };
}
