import { useEffect, useState } from "react";
import { NavLink } from "react-router-dom";

import { useHomeSummary } from "@/api/hooks";
import { useCurrentUser } from "@/auth/AuthContext";

/**
 * 登入後第一眼:
 *  - 頂部狀態列(門市 / 帳號 / 日期時間 / 系統正常)
 *  - 今日快覽 4 卡片(營業額、銷貨筆數、維修待處理、庫存警示)
 *  - 需要注意 + 最近交易 兩欄
 *  - 快速入口(高頻操作大按鈕)
 * 資料來源:GET /home-summary/(每 30 秒重抓)
 */
export function HomePage() {
  const user = useCurrentUser();
  const summary = useHomeSummary();
  const now = useNow();

  const today = summary.data?.today;
  const yesterday = summary.data?.yesterday;
  const lowStock = summary.data?.low_stock;
  const recent = summary.data?.recent_sales ?? [];

  const revenueDiff = pctDiff(today?.revenue, yesterday?.revenue);
  const countDiff = absDiff(today?.sales_count, yesterday?.sales_count);

  const warehouseName =
    summary.data?.warehouse_name || user?.profile?.default_warehouse_name || "全公司";

  return (
    <div className="page">
      <header className="hp-statusbar">
        <div className="hp-statusbar-left">
          <span className="hp-status-dot" title="系統正常" />
          <span className="hp-status-label">系統正常</span>
          <span className="hp-status-sep">·</span>
          <span className="hp-status-wh">{warehouseName}</span>
          {user?.username && (
            <>
              <span className="hp-status-sep">·</span>
              <span className="hp-status-user">{user.username}</span>
            </>
          )}
        </div>
        <div className="hp-statusbar-right">
          <span className="hp-status-date">{fmtDate(now)}</span>
          <span className="hp-status-time">{fmtTime(now)}</span>
        </div>
      </header>

      <div className="hp-body">
        <section className="hp-section">
          <div className="hp-section-title">今日快覽</div>
          <div className="hp-stat-grid">
            <StatCard
              label="今日營業額"
              value={`$${(today?.revenue ?? 0).toLocaleString()}`}
              hint={revenueDiff}
            />
            <StatCard
              label="銷貨筆數"
              value={String(today?.sales_count ?? 0)}
              hint={countDiff}
            />
            <StatCard
              label="維修待處理"
              value="—"
              hint={<span className="hp-stat-muted">(模組尚未實作)</span>}
            />
            <StatCard
              label="庫存警示"
              value={String(lowStock?.count ?? 0)}
              hint={
                (lowStock?.count ?? 0) > 0 ? (
                  <span className="hp-stat-warn">品項低於安全庫存</span>
                ) : (
                  "—"
                )
              }
            />
          </div>
        </section>

        <div className="hp-two-col">
          <section className="hp-panel">
            <div className="hp-panel-head">
              <div className="hp-panel-title">需要注意</div>
              <NavLink to="/inventory" className="hp-panel-link">
                查看全部 →
              </NavLink>
            </div>
            <div className="hp-panel-body">
              {summary.isLoading && (
                <div className="hp-panel-empty">載入中…</div>
              )}
              {!summary.isLoading && (lowStock?.items?.length ?? 0) === 0 && (
                <div className="hp-panel-empty">目前沒有待辦事項</div>
              )}
              {lowStock?.items?.map((it) => (
                <div key={it.id} className="hp-alert-row">
                  <span className="hp-alert-dot hp-alert-red" />
                  <div className="hp-alert-content">
                    <div className="hp-alert-title">
                      {it.name} 庫存剩 {it.qty} 件
                    </div>
                    <div className="hp-alert-sub">
                      低於安全庫存({it.safety_stock}) · 建議補貨
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </section>

          <section className="hp-panel">
            <div className="hp-panel-head">
              <div className="hp-panel-title">最近交易</div>
              <NavLink to="/reports/sales-daily" className="hp-panel-link">
                銷貨日報 →
              </NavLink>
            </div>
            <div className="hp-panel-body">
              {summary.isLoading && (
                <div className="hp-panel-empty">載入中…</div>
              )}
              {!summary.isLoading && recent.length === 0 && (
                <div className="hp-panel-empty">今日尚無交易</div>
              )}
              {recent.map((s) => (
                <NavLink
                  key={s.id}
                  to={`/sales/${s.id}`}
                  className="hp-recent-row"
                >
                  <div className="hp-recent-avatar">
                    {(s.customer_name || "?").slice(0, 1)}
                  </div>
                  <div className="hp-recent-content">
                    <div className="hp-recent-title">
                      {s.items_brief || s.customer_name}
                    </div>
                    <div className="hp-recent-sub">
                      {fmtRecentTime(s.doc_time)}
                      {s.sales_person_name && (
                        <> · 業務:{s.sales_person_name}</>
                      )}
                    </div>
                  </div>
                  <div className="hp-recent-amount">
                    ${s.total.toLocaleString()}
                  </div>
                </NavLink>
              ))}
            </div>
          </section>
        </div>

        <section className="hp-section">
          <div className="hp-section-title">快速入口</div>
          <div className="hp-quick-grid">
            <QuickLink to="/sales/new" label="銷貨作業" tone="primary" />
            <QuickLink to="/purchases/new" label="進貨作業" tone="primary" />
            <QuickLink to="/inventory" label="庫存查詢" tone="primary" />
            <QuickLink to="/customers" label="客戶管理" />
            <QuickLink to="/reports/sales-daily" label="銷貨日報" />
            <QuickLink to="/reports/business-daily" label="營業日報" />
            <QuickLink to="/transfers/new" label="調撥作業" />
            <QuickLink to="/telecom/billing" label="代收話費" />
            <QuickLink to="/products" label="商品建立" />
          </div>
        </section>
      </div>
    </div>
  );
}

function StatCard({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: React.ReactNode;
}) {
  return (
    <div className="hp-stat-card">
      <div className="hp-stat-label">{label}</div>
      <div className="hp-stat-value">{value}</div>
      {hint && <div className="hp-stat-hint">{hint}</div>}
    </div>
  );
}

function QuickLink({
  to,
  label,
  tone,
}: {
  to: string;
  label: string;
  tone?: "primary";
}) {
  return (
    <NavLink
      to={to}
      className={`hp-quick-link${tone === "primary" ? " primary" : ""}`}
    >
      {label}
    </NavLink>
  );
}

function pctDiff(today?: number, yesterday?: number): React.ReactNode {
  if (today == null || yesterday == null) return null;
  if (yesterday === 0) {
    return today > 0 ? (
      <span className="hp-stat-up">昨日無資料</span>
    ) : (
      "—"
    );
  }
  const pct = ((today - yesterday) / yesterday) * 100;
  if (Math.abs(pct) < 0.1) return <span>持平 vs 昨日</span>;
  const cls = pct > 0 ? "hp-stat-up" : "hp-stat-down";
  const sign = pct > 0 ? "↑" : "↓";
  return (
    <span className={cls}>
      {sign}
      {Math.abs(pct).toFixed(1)}% vs 昨日
    </span>
  );
}

function absDiff(today?: number, yesterday?: number): React.ReactNode {
  if (today == null || yesterday == null) return null;
  const d = today - yesterday;
  if (d === 0) return <span>持平 vs 昨日</span>;
  const cls = d > 0 ? "hp-stat-up" : "hp-stat-down";
  const sign = d > 0 ? "↑" : "↓";
  return (
    <span className={cls}>
      {sign}
      {Math.abs(d)} 筆 vs 昨日
    </span>
  );
}

function useNow() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 30000);
    return () => clearInterval(t);
  }, []);
  return now;
}

function fmtDate(d: Date): string {
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  const weekday = ["週日", "週一", "週二", "週三", "週四", "週五", "週六"][
    d.getDay()
  ];
  return `${yyyy}/${mm}/${dd} ${weekday}`;
}

function fmtTime(d: Date): string {
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  return `${hh}:${mm}`;
}

function fmtRecentTime(iso: string): string {
  const d = new Date(iso);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}
