import { useEffect, useRef } from "react";

import type { DuplicateBody, DuplicateCandidate } from "@/api/types";

/**
 * 差異理由有沒有內容:至少兩個字(文字或數字),只打標點或空白不算。
 * 跟後端 `has_real_reason` 同一個規則,按鈕才不會亮了送出去又被退回。
 */
export function hasRealReason(reason: string | undefined): boolean {
  return ((reason ?? "").match(/[\p{L}\p{N}]/gu) ?? []).length >= 2;
}

interface Props {
  dup: DuplicateBody;
  reason: string;
  onReasonChange: (v: string) => void;
  /** 選「就是這個」。不給就不顯示那顆按鈕 */
  onUseExisting?: (c: DuplicateCandidate) => void;
  /** 寫好差異後「繼續新增」 */
  onProceed: () => void;
  busy?: boolean;
}

/**
 * 新增商品被防重複關卡擋下時顯示:列出既有商品,讓人選「就是這個」,
 * 或寫下哪裡不同再「繼續新增」。條碼 / 已確認叫法相同時沒有「繼續新增」。
 */
export function DuplicatePanel({
  dup,
  reason,
  onReasonChange,
  onUseExisting,
  onProceed,
  busy = false,
}: Props) {
  const hard = dup.kind === "identifier";
  // 按「儲存」的時候人通常在表單下面,面板出現在上面會看不到
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    ref.current?.scrollIntoView({ block: "nearest" });
  }, [dup]);
  return (
    <div className="dup-panel" ref={ref}>
      <div className="dup-title">
        {hard ? "條碼 / 叫法已屬於這個商品" : "可能已經建過"}
      </div>
      {dup.candidates.map((c) => (
        <div key={c.id} className="dup-row">
          <div className="dup-row-main">
            <div>
              {c.name}
              {!c.is_active && (
                <span className="intake-inactive-tag">已停用</span>
              )}
            </div>
            <div className="dup-row-sub">
              {[c.sku, c.category_name, ...c.reasons, ...c.differences]
                .filter(Boolean)
                .join(" / ")}
            </div>
          </div>
          {onUseExisting && (
            <button
              type="button"
              className="btn small primary"
              disabled={busy}
              onClick={() => onUseExisting(c)}
            >
              就是這個
            </button>
          )}
        </div>
      ))}
      {!hard && (
        <div className="dup-proceed">
          <input
            value={reason}
            onChange={(e) => onReasonChange(e.target.value)}
            placeholder="哪裡不同"
            maxLength={200}
          />
          <button
            type="button"
            className="btn small"
            disabled={busy || !hasRealReason(reason)}
            onClick={onProceed}
          >
            繼續新增
          </button>
        </div>
      )}
    </div>
  );
}
