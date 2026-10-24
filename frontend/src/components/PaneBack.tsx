import { useLayoutEffect, useRef } from "react";

import { keepListBody, NARROW, openPaneAtTop, trackListScroll } from "@/lib/paneScroll";

// 主檔頁(會員、來源、廠商、業務員、商品)與進貨匯入的單項核對,右邊那一塊整頁換掉清單時最上面那一條「×」回清單(全站檢視 R01)。
// 窄畫面都顯示;電腦上只有也整頁的主檔頁(`pane-page`:來源、廠商、業務員;V01)顯示,其他左右兩欄本來就看得到清單(樣式在 styles.css 的 .pc-pane-back)。
// 打開時從最上面看那一筆,回清單時捲回原來的位置 —— 窄畫面是整頁捲、電腦上是清單那一塊自己捲,兩個都記(規則在 lib/paneScroll.ts;清單元件沒卸掉,搜尋也還在)。
export function PaneBack({ open, onClose, disabled }: { open: boolean; onClose: () => void; disabled?: boolean }) {
  const leaving = useRef(false);
  // 先宣告:整頁離開時這一個先被收掉,下面那一個就不會把別的頁捲到清單的位置
  useLayoutEffect(() => {
    leaving.current = false;
    return () => {
      leaving.current = true;
    };
  }, []);
  const listAt = useRef(0);
  useLayoutEffect(() => {
    const page = document.scrollingElement;
    if (open || !page) return;
    return trackListScroll(window, page, listAt);
  }, [open]);
  // 電腦上清單那一塊自己捲:清單開著時一直記,打開那一筆時清單藏起來了才在回來時捲回去
  const bodyAt = useRef(0);
  useLayoutEffect(() => {
    const body = listBody();
    if (open || !body) return;
    return trackListScroll(body, body, bodyAt);
  }, [open]);
  useLayoutEffect(() => {
    const body = listBody();
    if (!open || !body) return;
    const master = body.closest(".pc-master");
    const hidden = !!master && window.getComputedStyle(master).display === "none";
    return keepListBody(window, body, bodyAt.current, hidden, () => !leaving.current);
  }, [open]);
  const bar = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const page = document.scrollingElement;
    const pane = bar.current?.parentElement;
    if (!open || !page || !pane || !window.matchMedia(NARROW).matches) return;
    const paneTop = pane.getBoundingClientRect().top + page.scrollTop;
    return openPaneAtTop(window, page, listAt.current, { paneTop, viewH: window.innerHeight }, () => !leaving.current);
  }, [open]);
  if (!open) return null;
  return (
    <div className="pc-pane-back" ref={bar}>
      <button type="button" className="md-detail-close" aria-label="收起" title="收起" onClick={onClose} disabled={disabled}>
        ×
      </button>
    </div>
  );
}

/** 這一頁主檔清單那一塊(電腦上它自己捲) */
function listBody(): HTMLElement | null {
  return document.querySelector<HTMLElement>(".pc-layout > .pc-master .pc-section-body");
}
