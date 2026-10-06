import { memo, useMemo } from "react";

import type { LabelData } from "@/api/labels";
import { code128Bits } from "@/lib/code128";
import {
  LABEL,
  type BarLayout,
  dotsToMm,
  layoutBars,
  leftPadDots,
  printableCode,
} from "@/lib/labels";
import { money } from "@/lib/money";

/** 這個碼的條碼怎麼畫(整數個點);畫不出來回 null:太長放不下、或有 Code 128 沒有的字 */
function barsFor(code: string): BarLayout | null {
  const bits = code128Bits(code);
  return bits ? layoutBars(bits) : null;
}

/**
 * 這一張實際印哪個碼(原廠條碼印不下會改印品號,見 `printableCode`)。
 * 標籤與列印頁上面的提醒用同一支,兩邊講的才會一樣。
 */
export function codeToPrint(label: Pick<LabelData, "code" | "code_kind" | "sku">) {
  return printableCode(label, (code) => barsFor(code) !== null);
}

/**
 * 一張 50 × 30 mm 的商品標籤。尺寸與條碼的畫法見 `lib/labels.ts`。
 * 包了 memo:列印頁改一筆的張數時,其他幾百張不用跟著重畫。
 */
export const LabelTile = memo(function LabelTile({
  label,
  frame = false,
}: {
  label: LabelData;
  frame?: boolean;
}) {
  const printed = useMemo(
    () => codeToPrint(label),
    [label.code, label.code_kind, label.sku],
  );
  const layout = useMemo(
    () => (printed.bars ? barsFor(printed.code) : null),
    [printed.bars, printed.code],
  );
  const date = label.doc_date ? label.doc_date.slice(2) : "";
  return (
    <div className={`label-tile${frame ? " label-frame" : ""}`}>
      <div className="label-name">{label.name}</div>
      <div className="label-sub">
        <span>{label.sku}</span>
        {label.grade && <span>{label.grade} 級</span>}
      </div>
      <div>
        {layout ? (
          <svg
            className="label-bars"
            // 寬度、左邊的空白都是整數個點(一個點 0.125 mm):每一條線才會落在印表機的點上
            style={{
              width: `${dotsToMm(layout.widthDots)}mm`,
              height: `${LABEL.barHeightMm}mm`,
              marginLeft: `${dotsToMm(leftPadDots(layout.widthDots))}mm`,
            }}
            viewBox={`0 0 ${layout.widthDots} 10`}
            preserveAspectRatio="none"
            shapeRendering="crispEdges"
            aria-label={`條碼 ${printed.code}`}
          >
            {layout.bars.map((b) => (
              <rect key={b.x} x={b.x} y={0} width={b.w} height={10} fill="#000" />
            ))}
          </svg>
        ) : (
          // 印不出條碼:把碼本身印大一點、可以折行(只剩文字可以對了,不能再被切掉尾巴)
          <div className={`label-nobars${printed.code.length > 36 ? " long" : ""}`}>{printed.code}</div>
        )}
        {layout && <div className="label-code">{printed.code}</div>}
      </div>
      <div className="label-row">
        <span>{label.last5 ? `序末 ${label.last5}` : ""}</span>
        {label.price != null && <span className="label-price">${money(label.price)}</span>}
      </div>
      <div className="label-foot">
        {label.doc_no}
        {label.doc_no && date ? " · " : ""}
        {date}
      </div>
    </div>
  );
});
