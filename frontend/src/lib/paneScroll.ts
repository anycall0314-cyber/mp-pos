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

/** 清單開著時:現在的位置先記一次,之後每捲一次記一次。回傳停止記的函式。`win` 可以是整頁(window)或清單那一塊自己 */
export function trackListScroll(
  win: Pick<Win, "addEventListener" | "removeEventListener">,
  page: Page,
  store: { current: number },
): () => void {
  const keep = () => {
    store.current = page.scrollTop;
  };
  keep();
  win.addEventListener("scroll", keep, { passive: true });
  return () => win.removeEventListener("scroll", keep);
}

/**
 * 打開那一筆:讓那一塊從頭看起。那一塊本來就在畫面上半部(主檔頁:標題下面)就捲到整頁最上面;
 * 在比較下面(進貨匯入:上面還有建立表單)就捲到那一塊的開頭。`paneTop` = 那一塊在整頁的位置、`viewH` = 畫面高。
 * 回傳「回清單」時要做的事:等清單畫回來(下一格畫面)再捲回 `kept`;
 * `stillHere()` 回 false(整頁換掉了)就不捲,免得把別的頁捲到清單的位置。
 */
export function openPaneAtTop(
  win: Win,
  page: Page,
  kept: number,
  pane: { paneTop: number; viewH: number },
  stillHere: () => boolean,
): () => void {
  page.scrollTop = pane.paneTop < pane.viewH * 0.4 ? 0 : pane.paneTop;
  return () => {
    win.requestAnimationFrame(() => {
      if (stillHere()) page.scrollTop = kept;
    });
  };
}

/**
 * 電腦上清單是那一塊自己捲(不是整頁):打開那一筆時清單被藏起來(電腦也整頁的主檔頁),藏起來位置會歸零,
 * 回清單時(下一格畫面)捲回 `kept`。清單一直看得到(商品頁左右兩欄)就不動 —— 人可能在看詳情時捲過清單(全站檢視 V01)。
 */
export function keepListBody(
  win: Pick<Win, "requestAnimationFrame">,
  body: Page,
  kept: number,
  hidden: boolean,
  stillHere: () => boolean,
): () => void {
  return () => {
    if (!hidden) return;
    win.requestAnimationFrame(() => {
      if (stillHere()) body.scrollTop = kept;
    });
  };
}
