import { useState } from "react";

import { useInvoiceTrackJumps, useJumpInvoiceTrack } from "@/api/hooks";
import type { InvoiceTrack } from "@/api/types";
import { apiErrorText } from "@/components/workbench/errors";
import { toast } from "@/components/workbench/toast";
import { invoiceNo, jumpPreview, jumpSummary, parseJumpInput } from "@/lib/invoiceTracks";

/**
 * 跳號(owner 2026-10-13:發票機故障之後要能指定從幾號開始印)。
 * 打的是**發票機裡那捲紙的下一張**;按確定之前先寫出會跳過哪幾號(或往回幾張)。
 * 系統設定的字軌清單與開單頁的發票號碼旁邊開的是同一個視窗。規則在 `lib/invoiceTracks.ts`,擋在伺服器。
 */
export function InvoiceJumpDialog({
  track,
  onClose,
  onDone,
}: {
  track: InvoiceTrack;
  onClose: () => void;
  onDone?: (track: InvoiceTrack) => void;
}) {
  const jump = useJumpInvoiceTrack();
  const log = useInvoiceTrackJumps(track.id);
  const [text, setText] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const preview = jumpPreview(track, text);

  async function submit() {
    const n = parseJumpInput(track, text);
    if (!preview.ok || n === null || jump.isPending) return;
    setError("");
    try {
      const saved = await jump.mutateAsync({ id: track.id, next_number: n, reason: reason.trim() });
      toast(saved.next_invoice_no ? `下一張 ${saved.next_invoice_no}` : "這條字軌用完了", "ok");
      onDone?.(saved);
      onClose();
    } catch (e) {
      setError(apiErrorText(e));
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div
        className="modal-card invoice-jump-modal"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        <div className="modal-title">
          跳號 · {track.prefix}
          {track.warehouse_name ? ` · ${track.warehouse_name}` : ""}
        </div>
        <form
          className="modal-body"
          onSubmit={(e) => {
            e.preventDefault();
            void submit();
          }}
        >
          <div className="modal-row">
            <span>系統下一張</span>
            <b>{track.is_depleted ? "已用完" : invoiceNo(track.prefix, track.next_number)}</b>
          </div>
          <label className="modal-row">
            <span>紙上下一張</span>
            <input
              autoFocus
              inputMode="numeric"
              value={text}
              onChange={(e) => {
                setText(e.target.value);
                setError("");
              }}
              placeholder={invoiceNo(track.prefix, track.next_number)}
            />
          </label>
          <label className="modal-row">
            <span>為什麼跳號</span>
            <input
              value={reason}
              maxLength={100}
              onChange={(e) => setReason(e.target.value)}
              placeholder="卡紙"
            />
          </label>
          {preview.text && (
            <div className={`invoice-jump-note${preview.kind === "forward" ? "" : " err"}`}>
              {preview.text}
            </div>
          )}
          {error && <div className="invoice-jump-note err">{error}</div>}
          {/* 表單裡要有送出鈕,Enter 才會送 */}
          <button type="submit" hidden />
        </form>
        {(log.data ?? []).length > 0 && (
          <div className="invoice-jump-log">
            {(log.data ?? []).map((j) => (
              <div key={j.id} className="modal-row">
                <span>
                  {j.created_at.slice(0, 10)} {j.from_no} → {j.to_no}
                </span>
                <span>
                  {jumpSummary(j)}
                  {j.reason ? ` · ${j.reason}` : ""}
                  {j.by ? ` · ${j.by}` : ""}
                </span>
              </div>
            ))}
          </div>
        )}
        <div className="modal-actions">
          <button className="btn" type="button" onClick={onClose}>
            取消
          </button>
          <button
            className="btn primary"
            type="button"
            onClick={() => void submit()}
            disabled={!preview.ok || jump.isPending}
          >
            確定
          </button>
        </div>
      </div>
    </div>
  );
}
