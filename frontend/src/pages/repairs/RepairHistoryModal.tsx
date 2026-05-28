import { useEffect } from "react";

import { useRepairHistoryByPhone } from "@/api/hooks";
import type { RepairHistoryItem } from "@/api/types";

interface Props {
  open: boolean;
  phone: string;
  onClose: () => void;
  onPick: (item: RepairHistoryItem) => void;
}

export function RepairHistoryModal({ open, phone, onClose, onPick }: Props) {
  const { data, isLoading } = useRepairHistoryByPhone(open ? phone : "");

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div
        className="modal-card rh-modal"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-title">
          歷史維修紀錄 · 電話 {phone || "(未填)"}
          <button type="button" className="rh-close" onClick={onClose}>
            ×
          </button>
        </div>
        <div className="modal-body rh-body">
          {!phone && (
            <div className="rh-empty">請先在客戶欄選擇含電話的客戶</div>
          )}
          {phone && isLoading && <div className="rh-empty">載入中…</div>}
          {phone && !isLoading && (data?.length ?? 0) === 0 && (
            <div className="rh-empty">
              查無相符維修紀錄,請確認客戶電話是否正確
            </div>
          )}
          {phone && (data?.length ?? 0) > 0 && (
            <table className="rh-table">
              <thead>
                <tr>
                  <th>單號</th>
                  <th>收件 / 完修</th>
                  <th>方式</th>
                  <th>機型 / 序號</th>
                  <th>項目</th>
                  <th>狀態 / 保固</th>
                  <th style={{ width: 80 }}></th>
                </tr>
              </thead>
              <tbody>
                {(data ?? []).map((row) => (
                  <tr key={row.id}>
                    <td>
                      <b>{row.no}</b>
                    </td>
                    <td>
                      <div>{row.received_date}</div>
                      <div className="rh-sub">
                        {row.completed_date ?? "(未完工)"}
                      </div>
                    </td>
                    <td>{row.mode_label}</td>
                    <td>
                      <div>{row.host_model_name || "—"}</div>
                      <div className="rh-sub">{row.device_serial}</div>
                    </td>
                    <td>{row.repair_item_name || "—"}</td>
                    <td>
                      <div>{row.status_label}</div>
                      {row.completed_date && (
                        <div
                          className={
                            "rh-badge " +
                            (row.warranty_within ? "ok" : "expired")
                          }
                        >
                          {row.warranty_within
                            ? `保固有效 · 第 ${row.days_since_complete} 天`
                            : `已超出 ${
                                (row.days_since_complete ?? 0) -
                                row.warranty_days
                              } 天`}
                        </div>
                      )}
                    </td>
                    <td>
                      <button
                        type="button"
                        className="btn primary"
                        onClick={() => onPick(row)}
                      >
                        選此單
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        <div className="modal-actions">
          <button type="button" className="btn" onClick={onClose}>
            關閉
          </button>
        </div>
      </div>
    </div>
  );
}
