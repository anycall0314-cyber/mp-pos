import { useRef, useState } from "react";

import { QtyInput } from "@/components/workbench/QtyInput";
import { MAX_SHEETS } from "@/lib/labels";

import { openLabelPrint } from "./openLabelPrint";

/**
 * 配件補印標籤:按「列印標籤」→ 打張數 → Enter 或「列印」。就地展開,不開視窗。
 * (序號商品是一台一張,在每一台那一列按「標籤」。)
 */
export function AccessoryLabelButton({ productId }: { productId: number }) {
  const [open, setOpen] = useState(false);
  const [copies, setCopies] = useState(1);
  const box = useRef<HTMLSpanElement>(null);

  /**
   * 印「框裡現在看到的數字」。打了範圍外的數字(0、太大、不是整數)時不送 ——
   * 這時候框裡的字還沒被改回來,拿上一個有效的張數去印的話,人看到的跟印出來的會不一樣。
   * Enter 與「列印」按鈕走同一條。
   */
  function printTyped() {
    const raw = box.current?.querySelector("input")?.value.trim() ?? "";
    const n = Number(raw);
    if (raw === "" || !Number.isInteger(n) || n < 1 || n > MAX_SHEETS) return;
    openLabelPrint(`product=${productId}&copies=${n}`);
    setOpen(false);
  }

  if (!open) {
    return (
      <button
        type="button"
        className="wb-btn small"
        onClick={(e) => {
          e.stopPropagation();
          // 每次打開都從 1 張開始(不沿用上一次的數字:直接按 Enter 會照上次的張數印)
          setCopies(1);
          setOpen(true);
        }}
      >
        列印標籤
      </button>
    );
  }
  return (
    <span ref={box} className="label-ask" onClick={(e) => e.stopPropagation()}>
      <QtyInput
        value={copies}
        min={1}
        max={MAX_SHEETS}
        autoFocus
        aria-label="標籤張數"
        onFocus={(e) => e.currentTarget.select()}
        onCommit={setCopies}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            e.stopPropagation();
            setOpen(false);
            return;
          }
          if (e.key !== "Enter" || e.repeat) return;
          e.preventDefault();
          printTyped();
        }}
      />
      <span>張</span>
      <button
        type="button"
        className="wb-btn small"
        // 按下去的時候游標留在張數那一格(不然那一格一離開,打錯的數字會先被改回上一個,印出來的就不是剛剛看到的)
        onMouseDown={(e) => e.preventDefault()}
        onClick={printTyped}
      >
        列印
      </button>
      <button type="button" className="wb-btn small" onClick={() => setOpen(false)}>
        取消
      </button>
    </span>
  );
}
