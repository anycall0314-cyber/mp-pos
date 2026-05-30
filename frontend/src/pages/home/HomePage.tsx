import { useEffect, useState } from "react";
import { NavLink } from "react-router-dom";

import { TrendingItem, useHomeSummary, useTrending } from "@/api/hooks";
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
  const trending = useTrending(6);
  const now = useNow();

  const today = summary.data?.today;
  const yesterday = summary.data?.yesterday;
  const lowStock = summary.data?.low_stock;
  const recent = summary.data?.recent_sales ?? [];
  const repair = summary.data?.repair_alerts;
  const repairAlertsCount =
    (repair?.overdue_repairs.count ?? 0) +
    (repair?.overdue_external.count ?? 0) +
    (repair?.awaiting_pickup.count ?? 0) +
    (repair?.parts_low_stock.count ?? 0);
  const noticeCount = (lowStock?.count ?? 0) + repairAlertsCount;

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
          <span
            className="hp-status-version"
            title="目前部署版本(git 短 hash · 建構時間)"
          >
            v{__APP_VERSION__}
          </span>
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
              value={String(summary.data?.repair_in_progress ?? 0)}
              hint={
                (summary.data?.repair_overdue ?? 0) > 0 ? (
                  <span className="hp-stat-warn">
                    {summary.data?.repair_overdue} 件逾期
                  </span>
                ) : (
                  "—"
                )
              }
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
              <NavLink to="/inventory/alerts" className="hp-panel-link">
                查看全部 →
              </NavLink>
            </div>
            <div className="hp-panel-body">
              {summary.isLoading && (
                <div className="hp-panel-empty">載入中…</div>
              )}
              {!summary.isLoading && noticeCount === 0 && (
                <div className="hp-panel-empty">目前沒有待辦事項</div>
              )}
              {repair?.overdue_repairs.items.map((it) => (
                <NavLink
                  key={`or-${it.id}`}
                  to={`/repairs/${it.id}`}
                  className="hp-alert-row hp-alert-link"
                >
                  <span className="hp-alert-dot hp-alert-red" />
                  <div className="hp-alert-content">
                    <div className="hp-alert-title">
                      維修單 {it.no} 逾期 {it.overdue_days} 天
                    </div>
                    <div className="hp-alert-sub">
                      {it.customer_name} · {it.host_model_name} ·{" "}
                      {it.status_label}
                    </div>
                  </div>
                </NavLink>
              ))}
              {repair?.overdue_external.items.map((it) => (
                <NavLink
                  key={`oe-${it.id}`}
                  to={`/repairs/${it.id}`}
                  className="hp-alert-row hp-alert-link"
                >
                  <span className="hp-alert-dot hp-alert-red" />
                  <div className="hp-alert-content">
                    <div className="hp-alert-title">
                      委外維修 {it.no} 超過取回日 {it.overdue_days} 天
                    </div>
                    <div className="hp-alert-sub">
                      廠商:{it.vendor_name} · {it.customer_name}
                    </div>
                  </div>
                </NavLink>
              ))}
              {repair?.awaiting_pickup.items.map((it) => (
                <NavLink
                  key={`ap-${it.id}`}
                  to={`/repairs/${it.id}`}
                  className="hp-alert-row hp-alert-link"
                >
                  <span className="hp-alert-dot hp-alert-yellow" />
                  <div className="hp-alert-content">
                    <div className="hp-alert-title">
                      待取件 {it.ready_days} 天 · {it.customer_name}
                    </div>
                    <div className="hp-alert-sub">
                      {it.host_model_name}
                      {it.customer_phone && (
                        <> · 電話 {it.customer_phone}</>
                      )}
                    </div>
                  </div>
                </NavLink>
              ))}
              {repair?.parts_low_stock.items.map((it) => (
                <NavLink
                  key={`pl-${it.id}`}
                  to="/inventory/alerts"
                  className="hp-alert-row hp-alert-link"
                >
                  <span className="hp-alert-dot hp-alert-yellow" />
                  <div className="hp-alert-content">
                    <div className="hp-alert-title">
                      零件不足·維修備料 {it.name} 剩 {it.qty} 件
                    </div>
                    <div className="hp-alert-sub">
                      低於安全庫存({it.safety_stock}) · 點此調整
                    </div>
                  </div>
                </NavLink>
              ))}
              {lowStock?.items?.map((it) => (
                <NavLink
                  key={`ls-${it.id}`}
                  to="/inventory/alerts"
                  className="hp-alert-row hp-alert-link"
                >
                  <span className="hp-alert-dot hp-alert-red" />
                  <div className="hp-alert-content">
                    <div className="hp-alert-title">
                      {it.name} 庫存剩 {it.qty} 件
                    </div>
                    <div className="hp-alert-sub">
                      低於安全庫存({it.safety_stock}) · 建議補貨
                    </div>
                  </div>
                </NavLink>
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

        <div className="hp-two-col">
          <section className="hp-panel">
            <div className="hp-panel-head">
              <div className="hp-panel-title">
                銷量回溫
                <span className="hp-panel-meta">
                  最近 14 天 vs 過去 90 天
                </span>
              </div>
              <NavLink to="/inventory" className="hp-panel-link">
                查看庫存 →
              </NavLink>
            </div>
            <div className="hp-panel-body">
              {trending.isLoading && (
                <div className="hp-panel-empty">載入中…</div>
              )}
              {!trending.isLoading &&
                (trending.data?.trending_up?.length ?? 0) === 0 && (
                  <div className="hp-panel-empty">
                    暫無顯著回溫商品 — 系統每晚重算
                  </div>
                )}
              {trending.data?.trending_up?.map((it) => (
                <TrendingRow key={`up-${it.id}`} item={it} />
              ))}
            </div>
          </section>

          <section className="hp-panel">
            <div className="hp-panel-head">
              <div className="hp-panel-title">
                銷量退燒
                <span className="hp-panel-meta">考慮清倉或降價</span>
              </div>
              <NavLink to="/inventory" className="hp-panel-link">
                查看庫存 →
              </NavLink>
            </div>
            <div className="hp-panel-body">
              {trending.isLoading && (
                <div className="hp-panel-empty">載入中…</div>
              )}
              {!trending.isLoading &&
                (trending.data?.trending_down?.length ?? 0) === 0 && (
                  <div className="hp-panel-empty">
                    暫無顯著退燒商品 — 系統每晚重算
                  </div>
                )}
              {trending.data?.trending_down?.map((it) => (
                <TrendingRow key={`dn-${it.id}`} item={it} />
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

function TrendingRow({ item }: { item: TrendingItem }) {
  const ratio = Number(item.trend_ratio);
  const recent = Number(item.velocity_recent_14d);
  const baseline = Number(item.velocity_baseline_90d);
  // 換算成「+N% / -N%」字面;baseline 0 時 ratio 算出 2.0,顯示「新熱」
  let trendLabel = "";
  let trendClass = "";
  if (baseline === 0 && recent > 0) {
    trendLabel = "新崛起";
    trendClass = "hp-trend-up";
  } else if (ratio >= 1) {
    trendLabel = `+${Math.round((ratio - 1) * 100)}%`;
    trendClass = "hp-trend-up";
  } else {
    trendLabel = `-${Math.round((1 - ratio) * 100)}%`;
    trendClass = "hp-trend-down";
  }
  const dailyHint =
    recent >= 1 ? `近 14 天日均 ${recent.toFixed(1)}` : `近 14 天 ${recent.toFixed(2)}/日`;
  const stockHint =
    item.kind === "up"
      ? `庫存 ${item.stock} 件${
          item.dynamic_safety_stock > 0
            ? ` / 建議 ${item.dynamic_safety_stock}`
            : ""
        }`
      : `庫存 ${item.stock} 件`;
  return (
    <NavLink
      to={`/inventory?search=${encodeURIComponent(item.sku)}`}
      className="hp-alert-row hp-alert-link"
    >
      <span
        className={`hp-trend-badge ${trendClass}`}
        title={`recent ${item.velocity_recent_14d} / baseline ${item.velocity_baseline_90d}`}
      >
        {trendLabel}
      </span>
      <div className="hp-alert-content">
        <div className="hp-alert-title">{item.name}</div>
        <div className="hp-alert-sub">
          {dailyHint} · {stockHint}
        </div>
      </div>
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
