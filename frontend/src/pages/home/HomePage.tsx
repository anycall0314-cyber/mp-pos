import { useEffect, useState } from "react";
import { NavLink } from "react-router-dom";

import { TrendingItem, useHomeSummary, useTrending, useWarehouses } from "@/api/hooks";
import { useCurrentUser } from "@/auth/AuthContext";
import {
  type HomeGroup,
  HOME_STORE_KEY,
  noticeGroups,
  pickStore,
  quickActions,
  reachable,
  todoGroups,
} from "@/lib/homeTodo";
import { money } from "@/lib/money";

/**
 * 今日總覽(2026-10-23 改成「今天要做的事」;UI 改善計劃 6.1、全站檢視 G7,規則在 lib/homeTodo.ts):
 *  - 最上面一排:門市(沒鎖門市的帳號可以選,每一區跟著同一家)· 帳號 · 日期時間
 *  - 四顆櫃檯動作(看不到那一頁的收起來)
 *  - 待辦(按下去做得完的)| 注意(給管店的人看的)
 *  - 今日營收(範圍與幾點更新)| 最近交易
 *  - 銷量回溫 / 退燒
 * 資料來源:GET /home-summary/(每 30 秒重抓)
 */
export function HomePage() {
  const user = useCurrentUser();
  const who = { role: user?.profile?.role, abilities: user?.abilities };
  const locked = !!user?.profile?.is_warehouse_locked;
  const warehouses = useWarehouses();
  const stores = (warehouses.data ?? []).filter((w) => w.is_active);
  const [storeRaw, setStoreRaw] = useState<string | null>(readStore);
  const store = locked ? null : pickStore(storeRaw, stores.map((w) => w.id));
  // 記著選過某一家:等門市清單回來才知道它還在不在,不先抓一次全公司
  const ready = locked || !storeRaw || !!warehouses.data || warehouses.isError;
  const summary = useHomeSummary(store, ready);
  const trending = useTrending(6);
  const now = useNow();

  const today = summary.data?.today;
  const yesterday = summary.data?.yesterday;
  const recent = summary.data?.recent_sales ?? [];
  const todo = todoGroups(summary.data, who);
  const notice = noticeGroups(summary.data, who);

  const scopeName = locked
    ? user?.profile?.default_warehouse_name || summary.data?.warehouse_name || ""
    : (stores.find((w) => w.id === store)?.name ?? "全公司");

  function chooseStore(value: string) {
    setStoreRaw(value || null);
    try {
      if (value) localStorage.setItem(HOME_STORE_KEY, value);
      else localStorage.removeItem(HOME_STORE_KEY);
    } catch {
      /* 這台電腦不給記也沒關係 */
    }
  }

  const loading = summary.isLoading || !ready;
  const failed = summary.isError && !summary.data;

  return (
    <div className="page">
      <header className="hp-statusbar">
        <div className="hp-statusbar-left">
          {locked ? (
            <span className="hp-status-wh">{scopeName}</span>
          ) : (
            <select
              className="hp-store"
              aria-label="門市"
              value={store ?? ""}
              onChange={(e) => chooseStore(e.target.value)}
            >
              <option value="">全公司</option>
              {stores.map((w) => (
                <option key={w.id} value={w.id}>
                  {w.name}
                </option>
              ))}
            </select>
          )}
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
        <nav className="hp-actions" aria-label="櫃檯動作">
          {quickActions(who).map((a) => (
            <NavLink key={a.to} to={a.to} className="hp-action">
              {a.label}
            </NavLink>
          ))}
        </nav>

        <div className="hp-two-col">
          <section className="hp-panel">
            <div className="hp-panel-head">
              <div className="hp-panel-title">待辦</div>
            </div>
            <GroupList groups={todo} loading={loading} failed={failed} empty="沒有待辦" retry={() => summary.refetch()} />
          </section>
          <section className="hp-panel">
            <div className="hp-panel-head">
              <div className="hp-panel-title">注意</div>
            </div>
            <GroupList groups={notice} loading={loading} failed={failed} empty="沒有要注意的" retry={() => summary.refetch()} />
          </section>
        </div>

        <div className="hp-two-col">
          <section className="hp-panel">
            <div className="hp-panel-head">
              <div className="hp-panel-title">
                今日營收
                <span className="hp-panel-meta">
                  {scopeName}
                  {summary.dataUpdatedAt ? ` · ${fmtTime(new Date(summary.dataUpdatedAt))} 更新` : ""}
                </span>
              </div>
            </div>
            <div className="hp-stat-row">
              <StatCard label="營業額" value={summary.data ? `$${money(today?.revenue)}` : "—"} hint={pctDiff(today?.revenue, yesterday?.revenue)} />
              <StatCard label="銷貨筆數" value={summary.data ? String(today?.sales_count ?? 0) : "—"} hint={absDiff(today?.sales_count, yesterday?.sales_count)} />
            </div>
          </section>

          <section className="hp-panel">
            <div className="hp-panel-head">
              <div className="hp-panel-title">最近交易</div>
              {reachable("/reports/sales-daily", who) && (
                <NavLink to="/reports/sales-daily" className="hp-panel-link">
                  銷貨日報 →
                </NavLink>
              )}
            </div>
            <div className="hp-panel-body">
              {loading && <div className="hp-panel-empty">載入中…</div>}
              {!loading && !failed && recent.length === 0 && (
                <div className="hp-panel-empty">今天還沒有交易</div>
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
                    ${money(s.total)}
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
                <span className="hp-panel-meta">近 14 天比近 90 天 · 全公司</span>
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
                  <div className="hp-panel-empty">沒有回溫的商品</div>
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
                <span className="hp-panel-meta">近 14 天比近 90 天 · 全公司</span>
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
                  <div className="hp-panel-empty">沒有退燒的商品</div>
                )}
              {trending.data?.trending_down?.map((it) => (
                <TrendingRow key={`dn-${it.id}`} item={it} />
              ))}
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}

function readStore(): string | null {
  try {
    return localStorage.getItem(HOME_STORE_KEY);
  } catch {
    return null;
  }
}

/** 待辦 / 注意:一組一行「名稱 數字」(點了到那一頁、帶好條件),底下最多三筆 */
function GroupList({
  groups,
  loading,
  failed,
  empty,
  retry,
}: {
  groups: HomeGroup[];
  loading: boolean;
  failed: boolean;
  empty: string;
  retry: () => void;
}) {
  if (loading) return <div className="hp-panel-empty">載入中…</div>;
  if (failed)
    return (
      <div className="hp-panel-empty">
        沒有讀到{" "}
        <button type="button" className="btn" onClick={retry}>
          重試
        </button>
      </div>
    );
  if (groups.length === 0) return <div className="hp-panel-empty">{empty}</div>;
  return (
    <div className="hp-panel-body">
      {groups.map((g) => (
        <div key={g.key} className="hp-group">
          <NavLink to={g.to} className="hp-group-head">
            <span>{g.label}</span>
            <span className="hp-group-count">{g.count}</span>
          </NavLink>
          {g.items.map((it) => (
            <NavLink key={it.key} to={it.to} className="hp-group-item">
              <span className="hp-group-title">{it.title}</span>
              {it.sub && <span className="hp-group-sub">{it.sub}</span>}
            </NavLink>
          ))}
        </div>
      ))}
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
      <span className={`hp-trend-badge ${trendClass}`}>
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
      <span className="hp-stat-up">昨天沒有</span>
    ) : (
      "—"
    );
  }
  const pct = ((today - yesterday) / yesterday) * 100;
  if (Math.abs(pct) < 0.1) return <span>跟昨天一樣</span>;
  const cls = pct > 0 ? "hp-stat-up" : "hp-stat-down";
  const sign = pct > 0 ? "↑" : "↓";
  return (
    <span className={cls}>
      比昨天 {sign}
      {Math.abs(pct).toFixed(1)}%
    </span>
  );
}

function absDiff(today?: number, yesterday?: number): React.ReactNode {
  if (today == null || yesterday == null) return null;
  const d = today - yesterday;
  if (d === 0) return <span>跟昨天一樣</span>;
  const cls = d > 0 ? "hp-stat-up" : "hp-stat-down";
  const sign = d > 0 ? "↑" : "↓";
  return (
    <span className={cls}>
      比昨天 {sign}
      {Math.abs(d)} 筆
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
