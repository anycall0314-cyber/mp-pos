import { useId, useLayoutEffect, useRef, type RefObject } from "react";

import { soleIndex, type InputLike } from "@/lib/keyboardBind";

/**
 * 主檔編輯表單用 `<dl>`(欄名在 dt、輸入框在下一個 dd)時,把欄名綁到那一格唯一的輸入框(全站控制項 MC-05):
 * 讀螢幕念得到「電話」「統一編號」,點欄名游標進到那一格。規則跟 Field 一樣:一格只有一個框才綁;
 * 一格唯一的是搜尋盒的只念欄名、點欄名不打開下拉(紅隊)。呼叫端自己給了 aria-label / aria-labelledby 的不蓋掉。
 * 只看得到的字(唯讀的 dl)不受影響 —— dd 裡沒有輸入框就不做事。
 *
 *   const dlRef = useDlLabels<HTMLDListElement>();
 *   <dl ref={dlRef}>…</dl>
 */
export function useDlLabels<T extends HTMLElement = HTMLDListElement>(): RefObject<T> {
  const ref = useRef<T>(null);
  const uid = useId().replace(/:/g, "");
  const seq = useRef(0);
  useLayoutEffect(() => {
    const root = ref.current;
    if (!root) return;
    const offs: (() => void)[] = [];
    root.querySelectorAll("dt").forEach((dt) => {
      const dd = dt.nextElementSibling;
      if (!dd || dd.tagName !== "DD") return;
      const els = Array.from(dd.querySelectorAll<HTMLElement>("input, select, textarea"));
      const facts: InputLike[] = els.map((el) => ({
        tag: el.tagName as InputLike["tag"],
        type: (el as HTMLInputElement).type ?? "",
        inSearchBox: !!el.closest(".combobox"),
      }));
      let target: HTMLElement | undefined = els[soleIndex(facts)];
      let searchBox = false;
      if (!target && els.length === 1 && facts[0].inSearchBox) {
        target = els[0];
        searchBox = true;
      }
      if (!target) return;
      if (!dt.id) dt.id = `${uid}-dt${seq.current++}`;
      const ours = target.dataset.dlLabel === "1";
      if (ours || (!target.getAttribute("aria-label") && !target.getAttribute("aria-labelledby"))) {
        target.setAttribute("aria-labelledby", dt.id);
        target.dataset.dlLabel = "1";
      }
      if (searchBox) return;
      const el = target;
      const focus = () => el.focus();
      dt.addEventListener("click", focus);
      offs.push(() => dt.removeEventListener("click", focus));
    });
    return () => offs.forEach((off) => off());
  });
  return ref;
}
