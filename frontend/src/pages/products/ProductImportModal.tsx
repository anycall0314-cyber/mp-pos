import { useState } from "react";

import { api } from "@/api/client";

interface ImportReport {
  dry_run: boolean;
  total_rows: number;
  success_count: number;
  skip_count: number;
  created_categories: string[];
  success_rows: { row_no: number; sku: string; name: string; category: string }[];
  skip_rows: { row_no: number; sku: string; name: string; reason: string }[];
}

interface Props {
  open: boolean;
  onClose: () => void;
  onImported?: () => void;
}

export function ProductImportModal({ open, onClose, onImported }: Props) {
  const [file, setFile] = useState<File | null>(null);
  const [report, setReport] = useState<ImportReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!open) return null;

  async function preview() {
    if (!file) return;
    setLoading(true);
    setError(null);
    setReport(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("dry_run", "true");
      const res = await api<ImportReport>("/products/import/", {
        method: "POST",
        body: fd,
      });
      setReport(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  async function commit() {
    if (!file) return;
    setLoading(true);
    setError(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("dry_run", "false");
      const res = await api<ImportReport>("/products/import/", {
        method: "POST",
        body: fd,
      });
      setReport(res);
      onImported?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  function reset() {
    setFile(null);
    setReport(null);
    setError(null);
  }

  function close() {
    reset();
    onClose();
  }

  return (
    <div className="modal-overlay" onClick={close}>
      <div
        className="modal-card pi-modal"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
      >
        <div className="modal-title">商品匯入 (CSV / Excel)</div>
        <div className="modal-body">
          {!report && (
            <>
              <div className="pi-note">
                <div>
                  <b>必填欄位</b>(標題列):品名 / 類別 / 品號
                </div>
                <div>
                  <b>選填</b>:安全庫存(預設 0)、建議售價、條碼
                </div>
                <div className="pi-note-dim">
                  類別不存在會自動建立。已存在的品號 / 品名會跳過。
                  匯入商品的「商品狀態」預設為「待補齊」,不影響庫存警示。
                </div>
              </div>
              <input
                type="file"
                accept=".xlsx,.xls,.csv"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              />
              {file && (
                <div className="pi-file-info">
                  已選:<b>{file.name}</b> ({(file.size / 1024).toFixed(1)} KB)
                </div>
              )}
              {error && <div className="pi-error">{error}</div>}
            </>
          )}

          {report && (
            <>
              <div className="pi-summary">
                <div className="pi-summary-card pi-summary-ok">
                  <div className="pi-summary-num">{report.success_count}</div>
                  <div className="pi-summary-label">
                    {report.dry_run ? "預計成功" : "成功匯入"}
                  </div>
                </div>
                <div className="pi-summary-card pi-summary-skip">
                  <div className="pi-summary-num">{report.skip_count}</div>
                  <div className="pi-summary-label">略過</div>
                </div>
                <div className="pi-summary-card">
                  <div className="pi-summary-num">{report.total_rows}</div>
                  <div className="pi-summary-label">總列數</div>
                </div>
              </div>

              {report.created_categories.length > 0 && (
                <div className="pi-section">
                  <div className="pi-section-title">
                    自動建立 {report.created_categories.length} 個新類別
                  </div>
                  <div className="pi-cat-list">
                    {report.created_categories.map((c) => (
                      <span key={c} className="pi-cat-chip">
                        {c}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {report.skip_rows.length > 0 && (
                <div className="pi-section">
                  <div className="pi-section-title pi-section-warn">
                    略過列表
                  </div>
                  <table className="pi-table">
                    <thead>
                      <tr>
                        <th>列</th>
                        <th>品號</th>
                        <th>品名</th>
                        <th>略過原因</th>
                      </tr>
                    </thead>
                    <tbody>
                      {report.skip_rows.map((r) => (
                        <tr key={`${r.row_no}-${r.sku}-${r.name}`}>
                          <td>{r.row_no}</td>
                          <td>{r.sku}</td>
                          <td>{r.name}</td>
                          <td className="pi-skip-reason">{r.reason}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {report.success_rows.length > 0 && (
                <div className="pi-section">
                  <div className="pi-section-title pi-section-ok">
                    {report.dry_run ? "預計匯入" : "成功匯入"}前
                    {Math.min(report.success_rows.length, 30)} 筆
                  </div>
                  <table className="pi-table">
                    <thead>
                      <tr>
                        <th>列</th>
                        <th>品號</th>
                        <th>品名</th>
                        <th>類別</th>
                      </tr>
                    </thead>
                    <tbody>
                      {report.success_rows.slice(0, 30).map((r) => (
                        <tr key={`${r.row_no}-${r.sku}`}>
                          <td>{r.row_no}</td>
                          <td>{r.sku}</td>
                          <td>{r.name}</td>
                          <td>{r.category}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}
        </div>
        <div className="modal-actions">
          {!report && (
            <>
              <button className="btn" onClick={close} disabled={loading}>
                取消
              </button>
              <button
                className="btn primary"
                onClick={preview}
                disabled={!file || loading}
              >
                {loading ? "解析中…" : "預覽匯入"}
              </button>
            </>
          )}
          {report && report.dry_run && (
            <>
              <button className="btn" onClick={reset} disabled={loading}>
                重新選檔
              </button>
              <button
                className="btn primary"
                onClick={commit}
                disabled={loading || report.success_count === 0}
              >
                {loading
                  ? "匯入中…"
                  : `確認匯入 ${report.success_count} 筆`}
              </button>
            </>
          )}
          {report && !report.dry_run && (
            <button className="btn primary" onClick={close}>
              完成
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
