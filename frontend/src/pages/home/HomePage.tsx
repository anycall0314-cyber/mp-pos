import { useEffect, useState } from "react";
import { NavLink } from "react-router-dom";

import { TrendingItem, useHomeSummary, useTrending, useWarehouses } from "@/api/hooks";
import { useCurrentUser } from "@/auth/AuthContext";
import { useIsMobile } from "@/hooks/useIsMobile";
import {
  type HomeGroup,
  HOME_STORE_KEY,
  loadState,
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
 *  - 今日營收 | 最近交易
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
  // 窄螢幕的頁標題在上方那一條(App),這裡不重複放
  const narrow = useIsMobile(900);

  const today = summary.data?.today;
  const recent = summary.data?.recent_sales ?? [];
  // 待辦 / 注意的連結帶著現在看的那一家(鎖門市 = 自己那一家;沒鎖 = 選的那一家,全公司不帶;全站檢視 R06)
  const linkStore = locked ? (user?.profile?.default_warehouse_id ?? null) : store;
  const todo = todoGroups(summary.data, who, linkStore);
  const notice = noticeGroups(summary.data, who, linkStore);

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

  // 第一次沒讀到 / 讀到過之後重抓失敗 / 讀到了 分開講(全站檢視 R08;規則在 lib/homeTodo.ts::loadState)
  const sumState = ready ? loadState({ isLoading: summary.isLoading, isError: summary.isError, hasData: !!summary.data }) : "loading";
  const loading = sumState === "loading";
  const failed = sumState === "failed";
  const trendState = loadState({ isLoading: trending.isLoading, isError: trending.isError, hasData: !!trending.data });

  return (
    <div className="page">
      <header className="hp-statusbar">
        <div className="hp-statusbar-left">
          {!narrow && <h1 className="hp-title">今日總覽</h1>}
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
        {sumState === "stale" && (
          <div className="hp-stale">
            更新失敗,顯示 {fmtTime(new Date(summary.dataUpdatedAt))} 的資料{" "}
            <button type="button" className="btn" onClick={() => summary.refetch()} disabled={summary.isFetching}>
              重試
            </button>
          </div>
        )}
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

        <div className="hp-three-col">
          <section className="hp-panel">
            <div className="hp-panel-head">
              <div className="hp-panel-title">今日營收</div>
              {reachable("/reports/sales-daily", who) && (
                <NavLink to="/reports/sales-daily" className="hp-panel-link">
                  銷貨日報 →
                </NavLink>
              )}
            </div>
            <div className="hp-stat-row">
              <StatCard label="營業額" value={summary.data ? `$${money(today?.revenue)}` : "—"} />
              <StatCard label="銷貨筆數" value={summary.data ? String(today?.sales_count ?? 0) : "—"} />
            </div>
            <div className="hp-subhead">最近交易</div>
            <div className="hp-panel-body">
              {loading && <div className="hp-panel-empty">載入中…</div>}
              {failed && <RetryLine retry={() => summary.refetch()} />}
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

          <section className="hp-panel">
            <div className="hp-panel-head">
              <div className="hp-panel-title">
                銷量回溫
                {trendState === "stale" && <span className="hp-panel-meta">更新失敗</span>}
              </div>
              <NavLink to="/inventory" className="hp-panel-link">
                查看庫存 →
              </NavLink>
            </div>
            <div className="hp-panel-body">
              {trendState === "loading" && <div className="hp-panel-empty">載入中…</div>}
              {trendState === "failed" && <RetryLine retry={() => trending.refetch()} />}
              {trending.data && (trending.data.trending_up?.length ?? 0) === 0 && (
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
                {trendState === "stale" && <span className="hp-panel-meta">更新失敗</span>}
              </div>
              <NavLink to="/inventory" className="hp-panel-link">
                查看庫存 →
              </NavLink>
            </div>
            <div className="hp-panel-body">
              {trendState === "loading" && <div className="hp-panel-empty">載入中…</div>}
              {trendState === "failed" && <RetryLine retry={() => trending.refetch()} />}
              {trending.data && (trending.data.trending_down?.length ?? 0) === 0 && (
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
  if (failed) return <RetryLine retry={retry} />;
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

/** 第一次就沒讀到:不寫成「沒有…」,給一顆重試 */
function RetryLine({ retry }: { retry: () => void }) {
  return (
    <div className="hp-panel-empty">
      沒有讀到{" "}
      <button type="button" className="btn" onClick={retry}>
        重試
      </button>
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="hp-stat-card">
      <div className="hp-stat-label">{label}</div>
      <div className="hp-stat-value">{value}</div>
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
