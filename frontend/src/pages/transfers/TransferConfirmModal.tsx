import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { ApiHttpError } from "@/api/client";
import {
  useConfirmTransferOrder,
  useTransferOrders,
} from "@/api/hooks";
import { Banner } from "@/components/Banner";

interface Props {
  open: boolean;
  onClose: () => void;
}

function daysSince(iso: string): number {
  const t = new Date(iso).getTime();
  if (!Number.isFinite(t)) return 0;
  return Math.max(0, Math.floor((Date.now() - t) / 86_400_000));
}

/**
 * 待確認調撥單 modal:
 * - 開啟時撈所有 status=dispatched 且 !is_void 的單(不限日期)
 * - 每筆右側兩個操作:看明細(跳 entry page,modal 關閉)、一鍵確認入庫(經 confirm dialog)
 * - 確認成功後該筆自動從列表消失(invalidate query)
 */
export function TransferConfirmModal({ open, onClose }: Props) {
  const navigate = useNavigate();
  // 不帶日期 filter,只篩 status;只在 modal 開啟時撈
  const { data, isLoading, isError, refetch } = useTransferOrders({
    status: "dispatched",
  });
  const confirmMutation = useConfirmTransferOrder();
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  // modal 重開時清掉 error / busy
  useEffect(() => {
    if (open) {
      setError(null);
      setBusyId(null);
      refetch();
    }
  }, [open, refetch]);

  // Esc 關閉
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  // 後端會回所有狀態的單,雖然這裡已傳 status=dispatched,還是擋一下 is_void
  const rows = (data ?? []).filter(
    (t) => t.status === "dispatched" && !t.is_void,
  );

  async function handleConfirm(id: number, no: string, toWarehouse: string) {
    if (
      !confirm(
        `確認入庫調撥單 ${no}?核對數量無誤後送出,目的倉「${toWarehouse}」將收到全部明細。`,
      )
    )
      return;
    setError(null);
    setBusyId(id);
    try {
      await confirmMutation.mutateAsync(id);
    } catch (e) {
      if (e instanceof ApiHttpError) {
        const body = e.body;
        if (typeof body === "object" && body && "detail" in body) {
          setError(String((body as { detail: unknown }).detail));
        } else {
          setError(`確認失敗 (${e.status}): ${JSON.stringify(body)}`);
        }
      } else {
        setError(String(e));
      }
    } finally {
      setBusyId(null);
    }
  }

  function gotoDetail(id: number) {
    onClose();
    navigate(`/transfers/${id}`);
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div
        className="modal-card transfer-confirm-modal"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        <div className="modal-title">
          待確認調撥單{" "}
          {rows.length > 0 && (
            <span style={{ color: "var(--text-dim)", fontWeight: "normal" }}>
              ({rows.length} 筆)
            </span>
          )}
        </div>

        {error && <Banner kind="error" message={error} />}

        <div className="modal-body">
          {isLoading && <div className="md-empty">載入中…</div>}
          {isError && (
            <div className="md-empty">載入失敗,請關閉重開</div>
          )}
          {!isLoading && !isError && rows.length === 0 && (
            <div className="md-empty">
              目前沒有待確認的調撥單
            </div>
          )}
          {!isLoading && !isError && rows.length > 0 && (
            <table className="line-table">
              <thead>
                <tr>
                  <th>單號</th>
                  <th>日期</th>
                  <th>來源倉</th>
                  <th>目的倉</th>
                  <th className="num">明細</th>
                  <th>派發</th>
                  <th>備註</th>
                  <th style={{ width: 170 }}>操作</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((t) => {
                  const dayDiff = daysSince(t.created_at);
                  const isBusy = busyId === t.id;
                  return (
                    <tr key={t.id}>
                      <td>
                        <button
                          type="button"
                          className="link-button"
                          onClick={() => gotoDetail(t.id)}
                          title="查看明細"
                        >
                          {t.no}
                        </button>
                      </td>
                      <td>{t.doc_date}</td>
                      <td>
                        {t.from_warehouse_code} {t.from_warehouse_name}
                      </td>
                      <td>
                        {t.to_warehouse_code} {t.to_warehouse_name}
                      </td>
                      <td className="num">{t.items.length}</td>
                      <td
                        style={{
                          color: dayDiff >= 3 ? "#f0b060" : "var(--text-dim)",
                          fontSize: 13,
                        }}
                        title={`派發於 ${t.created_at}`}
                      >
                        {dayDiff === 0 ? "今天" : `${dayDiff} 天前`}
                      </td>
                      <td
                        style={{
                          color: "var(--text-dim)",
                          fontSize: 13,
                          maxWidth: 180,
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          whiteSpace: "nowrap",
                        }}
                        title={t.note}
                      >
                        {t.note || "—"}
                      </td>
                      <td>
                        <div style={{ display: "flex", gap: 4 }}>
                          <button
                            type="button"
                            className="btn"
                            style={{ fontSize: 13, padding: "3px 8px" }}
                            onClick={() => gotoDetail(t.id)}
                            disabled={isBusy}
                          >
                            看明細
                          </button>
                          <button
                            type="button"
                            className="btn primary"
                            style={{ fontSize: 13, padding: "3px 8px" }}
                            onClick={() =>
                              handleConfirm(
                                t.id,
                                t.no,
                                t.to_warehouse_name,
                              )
                            }
                            disabled={isBusy}
                          >
                            {isBusy ? "確認中…" : "一鍵確認"}
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>

        <div className="modal-actions">
          <button className="btn" type="button" onClick={onClose}>
            關閉
          </button>
        </div>
      </div>
    </div>
  );
}
