import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { useClearancePressure, useInventoryAlerts } from "@/api/hooks";
import type {
  AlertSeverity,
  ClearancePressureRow,
  InventoryAlertRow,
} from "@/api/types";
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

type Tab = "alerts" | "clearance";

export function InventoryAlertsPage() {
  const [tab, setTab] = useState<Tab>("alerts");
  const alerts = useInventoryAlerts();
  const clearance = useClearancePressure();

  return (
    <div className="page">
      <Toolbar title="庫存警示">
        <div className="ia-tabs">
          <button
            type="button"
            className={`ia-tab${tab === "alerts" ? " active" : ""}`}
            onClick={() => setTab("alerts")}
          >
            補貨警示
            {alerts.data && alerts.data.counts.total > 0 && (
              <span className="ia-tab-badge">
                {alerts.data.counts.total}
              </span>
            )}
          </button>
          <button
            type="button"
            className={`ia-tab${tab === "clearance" ? " active" : ""}`}
            onClick={() => setTab("clearance")}
          >
            清倉壓力
            {clearance.data && clearance.data.counts.recommend_discount > 0 && (
              <span className="ia-tab-badge ia-tab-badge-warn">
                {clearance.data.counts.recommend_discount}
              </span>
            )}
          </button>
        </div>
      </Toolbar>

      {tab === "alerts" && <AlertsPanel />}
      {tab === "clearance" && <ClearancePanel />}
    </div>
  );
}

function AlertsPanel() {
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
    <>
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
    </>
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
          {row.accessory_type === "phone_specific" && (
            <span className="ia-badge ia-badge-acc">機型專屬</span>
          )}
          {row.accessory_type === "universal" && (
            <span className="ia-badge ia-badge-acc">通用型</span>
          )}
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
        {row.safety_formula && (
          <div className="ia-row-formula">動態:{row.safety_formula}</div>
        )}
        {row.related_hosts.length > 0 && (
          <div className="ia-row-hosts">
            關聯主機:{row.related_hosts.map((h) => h.name).join(" / ")}
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
        <Link to="/purchases/new" className="btn primary ia-row-btn">
          去進貨
        </Link>
        <Link to="/products" className="btn ia-row-btn">
          編輯商品
        </Link>
      </div>
    </div>
  );
}

function ClearancePanel() {
  const { data, isLoading, isError, error } = useClearancePressure();
  const rows = data?.rows ?? [];
  const threshold = data?.threshold_days ?? 60;

  return (
    <>
      <div className="ia-counts-bar">
        <div className="ia-count ia-count-warning" style={{ cursor: "default" }}>
          <span className="ia-count-num">
            {data?.counts.recommend_discount ?? 0}
          </span>
          <span className="ia-count-label">建議降價</span>
        </div>
        <div className="ia-count ia-count-total" style={{ cursor: "default" }}>
          <span className="ia-count-num">{data?.counts.total ?? 0}</span>
          <span className="ia-count-label">出清品項</span>
        </div>
      </div>
      <div className="ia-hint">
        預估清倉天數 = 目前庫存 ÷ 過去 30 天日均銷量;
        超過 {threshold} 天會自動標記建議降價
      </div>

      <div className="ia-list">
        {isLoading && <div className="md-empty">載入中…</div>}
        {isError && <div className="md-empty">{String(error)}</div>}
        {!isLoading && !isError && rows.length === 0 && (
          <div className="ia-empty">
            <div className="ia-empty-title">目前沒有出清中的商品</div>
            <div className="ia-empty-hint">
              在商品管理把狀態改為「清倉處理」即可進入此清單
            </div>
          </div>
        )}
        {rows.map((row) => (
          <ClearanceRow
            key={row.id}
            row={row}
            thresholdDays={threshold}
          />
        ))}
      </div>
    </>
  );
}

function ClearanceRow({
  row,
  thresholdDays,
}: {
  row: ClearancePressureRow;
  thresholdDays: number;
}) {
  // 嚴重度視覺:超過門檻 = critical 紅、接近門檻(>50%) = warning 黃、其他 info 藍
  const sev: AlertSeverity = row.recommend_discount
    ? "critical"
    : row.estimated_days > thresholdDays * 0.5
    ? "warning"
    : "info";
  const daysLabel =
    row.estimated_days >= 999 ? "—" : `${row.estimated_days} 天`;

  return (
    <div className={`ia-row ia-row-${sev}`}>
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
        <div className="ia-row-reason">
          {row.recommend_discount ? "建議降價加速出清" : "監控中"}
        </div>
        <div className="ia-row-formula">
          {row.source_label} · {row.daily_avg_label}
        </div>
        {row.related_hosts.length > 0 && (
          <div className="ia-row-hosts">
            關聯主機:{row.related_hosts.map((h) => h.name).join(" / ")}
          </div>
        )}
      </div>
      <div className="ia-row-stock">
        <div className="ia-row-stock-num">{daysLabel}</div>
        <div className="ia-row-stock-of">
          剩 {row.current_qty} 件
        </div>
      </div>
      <div className="ia-row-actions">
        <Link to="/products" className="btn primary ia-row-btn">
          調整售價
        </Link>
      </div>
    </div>
  );
}
