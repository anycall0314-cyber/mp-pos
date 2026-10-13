import { memo, useLayoutEffect, useMemo, useRef, useState } from "react";

import type { LabelData } from "@/api/labels";
import { code128Bits } from "@/lib/code128";
import {
  LABEL,
  type BarLayout,
  barTopMm,
  dotsToMm,
  layoutBars,
  leftPadDots,
  moduleDotsFor,
  halfText,
  printableCode,
  squeezeFor,
} from "@/lib/labels";
import { money } from "@/lib/money";

/** 這個碼的條碼怎麼畫(整數個點);畫不出來回 null:太長放不下、或有 Code 128 沒有的字。線寬照碼的種類(有序號的可以用細線) */
function barsFor(code: string, codeKind: string): BarLayout | null {
  const bits = code128Bits(code);
  if (!bits) return null;
  return layoutBars(bits, undefined, moduleDotsFor(codeKind));
}

/**
 * 這一張實際印哪個碼(原廠條碼印不下會改印品號,見 `printableCode`)。
 * 標籤與列印頁上面的提醒用同一支,兩邊講的才會一樣。
 */
export function codeToPrint(label: Pick<LabelData, "code" | "code_kind" | "sku">) {
  return printableCode(label, (code) => barsFor(code, label.code_kind) !== null);
}

/** 印不出條碼時,碼的字超過這麼多就用小一號的字(兩聯各自要放得下整串) */
const LONG_CODE = 58;

/**
 * 一張 45 × 25 mm、上下兩聯的商品標籤。尺寸與條碼的畫法見 `lib/labels.ts`。
 * 上半與下半內容一樣、上下對稱;條碼只有一個,跨在中間的撕線上(撕開兩邊各留一半)。
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
    () => (printed.bars ? barsFor(printed.code, label.code_kind) : null),
    [printed.bars, printed.code, label.code_kind],
  );
  // 品名一行放不下就壓扁:量上半那一份(字本來多寬、格子多寬),上下兩聯用同一個比例。
  // 量的是畫出來的寬度(有小數;`offsetWidth` 是整數,差那半個點最後一個字會被切到),所以要除掉**畫面上現在**已經壓的比例 ——
  // 從元素自己身上讀,不另外記(開發模式這一段會連跑兩次,另外記的那一份會比畫面早一步,就壓過頭了)
  const nameRef = useRef<HTMLSpanElement>(null);
  const [squeeze, setSqueeze] = useState(1);
  useLayoutEffect(() => {
    const text = nameRef.current;
    const box = text?.parentElement;
    if (!text || !box) return;
    const now = Number(/scaleX\(([\d.]+)\)/.exec(text.style.transform)?.[1] ?? 1) || 1;
    setSqueeze(squeezeFor(text.getBoundingClientRect().width / now, box.getBoundingClientRect().width));
  }, [label.name]);

  const half = (side: "top" | "bottom") => (
    <Half
      side={side}
      label={label}
      code={printed.code}
      bars={layout !== null}
      squeeze={squeeze}
      nameRef={side === "top" ? nameRef : undefined}
    />
  );
  return (
    <div className={`label-tile${frame ? " label-frame" : ""}`}>
      {/* 內容包一層:位置微調推的是這一層(樣式 `.label-inner`);測試標籤的外框留在紙的四邊不跟著動 */}
      <div className="label-inner">
        {half("top")}
        {layout && (
          <svg
            className="label-bars"
            // 寬度、左邊的空白都是整數個點(一個點 0.125 mm):每一條線才會落在印表機的點上
            style={{
              width: `${dotsToMm(layout.widthDots)}mm`,
              height: `${LABEL.barHeightMm}mm`,
              top: `${barTopMm()}mm`,
              left: `${LABEL.sideMarginMm + dotsToMm(leftPadDots(layout.widthDots))}mm`,
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
        )}
        {half("bottom")}
        {frame && (
          <>
            {/* 測試標籤:左右各一小段線,要剛好落在撕線上 */}
            <span className="label-fold l" />
            <span className="label-fold r" />
          </>
        )}
      </div>
    </div>
  );
});

/** 一聯:品名、進貨單與日期 + 成色 + 售價、碼的字(有序號的只印末 5 碼)+ 品號;下半那一聯順序倒過來(樣式 `column-reverse`) */
function Half({
  side,
  label,
  code,
  bars,
  squeeze,
  nameRef,
}: {
  side: "top" | "bottom";
  label: LabelData;
  code: string;
  bars: boolean;
  squeeze: number;
  nameRef?: React.Ref<HTMLSpanElement>;
}) {
  const text = halfText(label, code, bars);
  return (
    <div className={`label-half ${side}`}>
      <div className="label-name">
        <span ref={nameRef} style={squeeze < 1 ? { transform: `scaleX(${squeeze})` } : undefined}>
          {label.name}
        </span>
      </div>
      <div className="label-meta">
        <span className="label-src">{text.source}</span>
        {label.grade && <span className="label-grade">{label.grade} 級</span>}
        {label.price != null && <span className="label-price">${money(label.price)}</span>}
      </div>
      {bars ? (
        <>
          <div className="label-codeline">
            {text.mode === "tail" ? (
              <span className="label-last5">
                序末 <b>{text.tail}</b>
              </span>
            ) : (
              <span className="label-code">{text.head}</span>
            )}
            <span className="label-sku">{text.sku}</span>
          </div>
          {/* 條碼的那一半(條碼本身是另外疊上去的,跨兩聯) */}
          <div className="label-slot" />
        </>
      ) : (
        // 印不出條碼:原本條碼那一半拿來把整個碼印出來、可以折行(只剩文字可以對了,不能被切掉尾巴);序號的末 5 碼標粗
        <div className={`label-nobars${code.length > LONG_CODE ? " long" : ""}`}>
          {text.head}
          {text.tail && <b>{text.tail}</b>}
        </div>
      )}
    </div>
  );
}
