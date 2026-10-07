import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import { api } from "@/api/client";
import type { DuplicateBody, DuplicateCandidate, Product } from "@/api/types";
import { useCurrentUser } from "@/auth/AuthContext";
import { stockScope } from "@/lib/findFirst";
import { MiniThumb } from "@/components/photos/PhotoName";
import type { PeekTarget } from "@/components/photos/ProductPhotoPanel";

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
  /** 點縮圖 / 品名看照片與規格。不給就只顯示文字 */
  onPeek?: (t: PeekTarget) => void;
}

/**
 * 候選的一列。擋下來的回應只有品號與品名;照片與庫存另外跟商品要一次
 * (走商品自己的端點:鎖倉帳號看到的庫存跟別的頁面一樣,不另開一條路)。
 * 還沒拿到就先不寫庫存 —— 不能把「還不知道」顯示成「庫存 0」。
 */
function CandidateRow({
  c,
  onUseExisting,
  onPeek,
  busy,
}: {
  c: DuplicateCandidate;
  onUseExisting?: (c: DuplicateCandidate) => void;
  onPeek?: (t: PeekTarget) => void;
  busy: boolean;
}) {
  const scope = stockScope(useCurrentUser()?.profile);
  const query = useQuery({
    queryKey: ["product", c.id, "stock", scope ?? null],
    queryFn: () =>
      api<Product>(`/products/${c.id}/${scope === undefined ? "" : `?warehouse=${scope}`}`),
  });
  // 這一次沒查成功(商品被刪、沒有權限、斷線)就不顯示:手上那一份是之前查的,不能當成現在的庫存
  const detail = query.isError ? undefined : query.data;
  const peek = onPeek ? () => onPeek({ id: c.id, name: c.name, sku: c.sku }) : undefined;
  return (
    <div className="dup-row">
      {peek && <MiniThumb src={detail?.photo_thumb} onClick={peek} />}
      <div className="dup-row-main">
        <div>
          {peek ? (
            <button type="button" className="ph-name" title="看照片與規格" onClick={peek}>
              {c.name}
            </button>
          ) : (
            c.name
          )}
          {!c.is_active && <span className="intake-inactive-tag">已停用</span>}
        </div>
        <div className="dup-row-sub">
          {[
            c.sku,
            c.category_name,
            detail ? `庫存 ${detail.stock_qty ?? 0}` : "",
            ...c.reasons,
            ...c.differences,
          ]
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
  );
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
  onPeek,
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
        <CandidateRow
          key={c.id}
          c={c}
          onUseExisting={onUseExisting}
          onPeek={onPeek}
          busy={busy}
        />
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
