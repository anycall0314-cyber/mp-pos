import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { useInventoryAlerts } from "@/api/hooks";
import type { AlertSeverity, InventoryAlertRow } from "@/api/types";
import { Toolbar } from "@/components/Toolbar";

const SEVERITY_LABEL: Record<AlertSeverity, string> = {
  critical: "緊急",
  warning: "注意",
  info: "提醒",
};

const LIFECYCLE_BADGE_CLASS: Record<string, string> = {
  active: "ia-badge ia-badge-active",
  replacing: "ia-badge ia-badge-replacing",
  discontinued: "ia-badge ia-badge-discontinued",
  clearance: "ia-badge ia-badge-clearance",
};

export function InventoryAlertsPage() {
  const { data, isLoading, isError, error } = useInventoryAlerts();
  const counts = data?.counts;
  const rows = data?.rows ?? [];

  const [severityFilter, setSeverityFilter] = useState<AlertSeverity | "all">(
    "all",
  );

  const filtered = useMemo(() => {
    if (severityFilter === "all") return rows;
    return rows.filter((r) => r.severity === severityFilter);
  }, [rows, severityFilter]);

  return (
    <div className="page">
      <Toolbar title="庫存警示" />

      <div className="ia-counts-bar">
        <button
          type="button"
          className={`ia-count ia-count-critical${severityFilter === "critical" ? " active" : ""}`}
          onClick={() =>
            setSeverityFilter((s) => (s === "critical" ? "all" : "critical"))
          }
        >
          <span className="ia-count-num">{counts?.critical ?? 0}</span>
          <span className="ia-count-label">緊急</span>
        </button>
        <button
          type="button"
          className={`ia-count ia-count-warning${severityFilter === "warning" ? " active" : ""}`}
          onClick={() =>
            setSeverityFilter((s) => (s === "warning" ? "all" : "warning"))
          }
        >
          <span className="ia-count-num">{counts?.warning ?? 0}</span>
          <span className="ia-count-label">注意</span>
        </button>
        <button
          type="button"
          className={`ia-count ia-count-info${severityFilter === "info" ? " active" : ""}`}
          onClick={() =>
            setSeverityFilter((s) => (s === "info" ? "all" : "info"))
          }
        >
          <span className="ia-count-num">{counts?.info ?? 0}</span>
          <span className="ia-count-label">提醒</span>
        </button>
        <button
          type="button"
          className={`ia-count ia-count-total${severityFilter === "all" ? " active" : ""}`}
          onClick={() => setSeverityFilter("all")}
        >
          <span className="ia-count-num">{counts?.total ?? 0}</span>
          <span className="ia-count-label">全部</span>
        </button>
      </div>

      <div className="ia-list">
        {isLoading && <div className="md-empty">載入中…</div>}
        {isError && <div className="md-empty">{String(error)}</div>}
        {!isLoading && !isError && filtered.length === 0 && (
          <div className="ia-empty">
            <div className="ia-empty-title">
              {severityFilter === "all"
                ? "目前沒有需要關注的庫存"
                : `沒有${SEVERITY_LABEL[severityFilter]}等級的警示`}
            </div>
            <div className="ia-empty-hint">
              安全庫存與商品狀態可在
              <Link to="/products" className="ia-empty-link">
                商品管理
              </Link>
              設定
            </div>
          </div>
        )}
        {filtered.map((row) => (
          <AlertRow key={row.id} row={row} />
        ))}
      </div>
    </div>
  );
}

function AlertRow({ row }: { row: InventoryAlertRow }) {
  return (
    <div className={`ia-row ia-row-${row.severity}`}>
      <div className="ia-row-bar" />
      <div className="ia-row-main">
        <div className="ia-row-head">
          <div className="ia-row-name">{row.name}</div>
          <span className={LIFECYCLE_BADGE_CLASS[row.lifecycle_status]}>
            {row.lifecycle_status_label}
          </span>
        </div>
        <div className="ia-row-sub">
          {row.sku}
          {row.category_name && (
            <>
              <span className="ia-sep">·</span>
              {row.category_name}
            </>
          )}
        </div>
        <div className="ia-row-reason">{row.reason_label}</div>
        {row.related_hosts.length > 0 && (
          <div className="ia-row-hosts">
            關聯主機:
            {row.related_hosts.map((h) => h.name).join(" / ")}
          </div>
        )}
      </div>
      <div className="ia-row-stock">
        <div className="ia-row-stock-num">{row.current_qty}</div>
        <div className="ia-row-stock-of">
          {row.safety_stock > 0 ? `/ ${row.safety_stock}` : "件"}
        </div>
      </div>
      <div className="ia-row-actions">
        <Link
          to="/purchases/new"
          className="btn primary ia-row-btn"
          title="建立進貨單"
        >
          去進貨
        </Link>
        <Link
          to="/products"
          state={{ editId: row.id }}
          className="btn ia-row-btn"
          title="編輯此商品設定"
        >
          編輯商品
        </Link>
      </div>
    </div>
  );
}
