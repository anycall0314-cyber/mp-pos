// 主檔頁窄畫面「整頁換成那一筆、× 回清單」時,清單捲到哪要記得(全站檢視 R01;用在 components/PaneBack.tsx)。跑法:npm test。
//
// 窄畫面是整頁一起捲。打開那一筆的當下清單已經藏起來、頁面變短,瀏覽器已經把位置縮掉了 ——
// 那時候才讀會讀到縮過的數字,所以清單開著的時候就一直記著。

export const NARROW = "(max-width: 768px)";

interface Page {
  scrollTop: number;
}

interface Win {
  addEventListener(type: "scroll", fn: () => void, options?: AddEventListenerOptions): void;
  removeEventListener(type: "scroll", fn: () => void): void;
  requestAnimationFrame(fn: () => void): number;
}

/** 清單開著時:現在的位置先記一次,之後每捲一次記一次。回傳停止記的函式。 */
export function trackListScroll(win: Win, page: Page, store: { current: number }): () => void {
  const keep = () => {
    store.current = page.scrollTop;
  };
  keep();
  win.addEventListener("scroll", keep, { passive: true });
  return () => win.removeEventListener("scroll", keep);
}

/**
 * 打開那一筆:從最上面開始看。回傳「回清單」時要做的事:等清單畫回來(下一格畫面)再捲回 `kept`;
 * `stillHere()` 回 false(整頁換掉了)就不捲,免得把別的頁捲到清單的位置。
 */
export function openPaneAtTop(win: Win, page: Page, kept: number, stillHere: () => boolean): () => void {
  page.scrollTop = 0;
  return () => {
    win.requestAnimationFrame(() => {
      if (stillHere()) page.scrollTop = kept;
    });
  };
}
