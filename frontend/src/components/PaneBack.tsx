import { useLayoutEffect, useRef } from "react";

import { NARROW, openPaneAtTop, trackListScroll } from "@/lib/paneScroll";

// 主檔頁(會員、來源、廠商、業務員、商品)右邊那一塊,窄畫面整頁換掉清單時最上面那一條「×」回清單(全站檢視 R01)。
// 電腦上不顯示(左右兩欄本來就看得到清單;樣式在 styles.css 的 .pc-pane-back)。
// 窄畫面打開時從最上面看那一筆,回清單時捲回原來的位置(規則在 lib/paneScroll.ts;清單元件沒卸掉,搜尋也還在)。
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
  useLayoutEffect(() => {
    const page = document.scrollingElement;
    if (!open || !page || !window.matchMedia(NARROW).matches) return;
    return openPaneAtTop(window, page, listAt.current, () => !leaving.current);
  }, [open]);
  if (!open) return null;
  return (
    <div className="pc-pane-back">
      <button type="button" className="md-detail-close" aria-label="收起" title="收起" onClick={onClose} disabled={disabled}>
        ×
      </button>
    </div>
  );
}
