import { useState } from "react";

import { usePartsUsageReport } from "@/api/hooks";
import { Toolbar } from "@/components/Toolbar";

function firstOfMonth(): string {
  const d = new Date();
  return new Date(d.getFullYear(), d.getMonth(), 1)
    .toISOString()
    .slice(0, 10);
}

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

export function PartsUsageReportPage() {
  const [from, setFrom] = useState(firstOfMonth);
  const [to, setTo] = useState(today);
  const [applied, setApplied] = useState({ from: firstOfMonth(), to: today() });

  const { data, isLoading } = usePartsUsageReport(applied);
  const rows = data?.rows ?? [];
  const summary = data?.summary;

  function exportCsv() {
    if (!rows.length) return;
    const headers = ["品號", "品名", "倉別", "維修領用", "對外調貨", "合計"];
    const lines = [headers.join(",")];
    for (const r of rows) {
      lines.push(
        [
          r.sku,
          (r.name || "").replace(/,/g, " "),
          r.warehouse_type === "parts" ? "零件倉" : "商品倉",
          r.repair_qty,
          r.transfer_qty,
          r.total_qty,
        ].join(","),
      );
    }
    const csv = "﻿" + lines.join("\r\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `零件耗用報表_${applied.from}_${applied.to}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  return (
    <div className="page">
      <Toolbar title="零件耗用報表" />
      <div className="list-filterbar">
        <label>
          起日
          <input
            type="date"
            value={from}
            onChange={(e) => setFrom(e.target.value)}
          />
        </label>
        <label>
          迄日
          <input
            type="date"
            value={to}
            onChange={(e) => setTo(e.target.value)}
          />
        </label>
        <button
          className="btn"
          type="button"
          onClick={() => {
            setFrom(firstOfMonth());
            setTo(today());
          }}
        >
          本月
        </button>
        <button
          className="btn primary"
          type="button"
          onClick={() => setApplied({ from, to })}
        >
          查詢
        </button>
        <button
          className="btn"
          type="button"
          onClick={exportCsv}
          disabled={!rows.length}
        >
          轉 Excel
        </button>
      </div>

      {summary && (
        <div className="sd-summary">
          <div className="sd-summary-card">
            <div className="sd-summary-card-label">維修領用 合計</div>
            <div className="sd-summary-card-value">
              {summary.repair_qty_total}
            </div>
          </div>
          <div className="sd-summary-card">
            <div className="sd-summary-card-label">對外調貨 合計</div>
            <div className="sd-summary-card-value">
              {summary.transfer_qty_total}
            </div>
          </div>
          <div className="sd-summary-card">
            <div className="sd-summary-card-label">總出貨 合計</div>
            <div className="sd-summary-card-value">
              {summary.total_qty_total}
            </div>
          </div>
          <div className="sd-summary-card">
            <div className="sd-summary-card-label">品項數</div>
            <div className="sd-summary-card-value">{summary.rows_count}</div>
          </div>
        </div>
      )}

      <div className="report-table">
        {isLoading && <div className="md-empty">載入中…</div>}
        {!isLoading && rows.length === 0 && (
          <div className="md-empty">該區間沒有零件異動紀錄</div>
        )}
        {rows.length > 0 && (
          <table className="report-grid">
            <thead>
              <tr>
                <th>品號</th>
                <th>品名</th>
                <th>倉別</th>
                <th className="num">維修領用</th>
                <th className="num">對外調貨</th>
                <th className="num">合計</th>
                <th className="num">當前單位成本</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.product_id} className="report-row">
                  <td>{r.sku}</td>
                  <td>{r.name}</td>
                  <td>{r.warehouse_type === "parts" ? "零件倉" : "商品倉"}</td>
                  <td className="num">{r.repair_qty}</td>
                  <td className="num">{r.transfer_qty}</td>
                  <td className="num">
                    <b>{r.total_qty}</b>
                  </td>
                  <td className="num">
                    {Math.round(Number(r.unit_cost)).toLocaleString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
