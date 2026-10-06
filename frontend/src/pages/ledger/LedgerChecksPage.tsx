import { useLedgerChecks } from "@/api/hooks";
import type { LedgerCheckResult } from "@/api/types";
import { useCurrentUser } from "@/auth/AuthContext";
import { Banner } from "@/components/Banner";
import { Toolbar } from "@/components/Toolbar";
import { money } from "@/lib/money";

/**
 * 設定 → 每日對帳(公司管理員)
 *
 * 每天收店後背景程式自動拍庫存快照、跑一次對帳(apps/ledger);這頁只看結果。
 */

function when(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("zh-TW", { hour12: false });
}

function verdict(r: LedgerCheckResult): { text: string; className: string } {
  if (r.level === "info") return { text: "提醒", className: "ledger-info" };
  return r.ok
    ? { text: "一致", className: "backup-good" }
    : { text: "不一致", className: "backup-bad" };
}

export function LedgerChecksPage() {
  const role = useCurrentUser()?.profile?.role;
  const isAdmin = role === "tenant_admin";
  const { data, error } = useLedgerChecks();

  if (!isAdmin) {
    return (
      <div className="page">
        <Toolbar title="每日對帳" />
        <div className="entry-body">
          <Banner kind="error" message="需要公司管理員權限" />
        </div>
      </div>
    );
  }

  const latest = data?.latest;
  const snap = data?.snapshot;

  return (
    <div className="page">
      <Toolbar title="每日對帳" />
      <div className="entry-body backup-page">
        {error && <Banner kind="error" message={`讀取失敗:${String(error)}`} />}

        <section className="backup-card">
          <dl className="backup-facts">
            <dt>最近對帳</dt>
            <dd>{latest ? when(latest.finished_at) : "—"}</dd>
            <dt>結果</dt>
            <dd>
              {!latest ? (
                "—"
              ) : latest.before_restore ? (
                <span className="ledger-info">還原前的結果</span>
              ) : latest.ok ? (
                <span className="backup-good">全部一致</span>
              ) : (
                <span className="backup-bad">{latest.problem_count} 項不一致</span>
              )}
            </dd>
            <dt>庫存快照</dt>
            <dd>
              {snap
                ? `${snap.business_date}|${snap.qty.toLocaleString()} 件|成本 ${money(snap.cost_value)}`
                : "—"}
            </dd>
          </dl>
        </section>

        {latest?.results && (
          <section className="backup-card">
            <div className="section-head">檢查項目</div>
            <table className="backup-table ledger-table">
              <thead>
                <tr>
                  <th>項目</th>
                  <th>結果</th>
                  <th className="num">筆數</th>
                </tr>
              </thead>
              <tbody>
                {latest.results.map((r) => {
                  const v = verdict(r);
                  return (
                    <tr key={r.key}>
                      <td>
                        {r.label}
                        {r.detail && <div className="backup-sub">{r.detail}</div>}
                        {!r.ok &&
                          r.samples.map((s) => (
                            <div key={s} className="backup-sub">
                              {s}
                            </div>
                          ))}
                      </td>
                      <td className={v.className}>{v.text}</td>
                      <td className="num">{r.count ? r.count.toLocaleString() : ""}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </section>
        )}

        {data && data.history.length > 1 && (
          <section className="backup-card">
            <div className="section-head">最近紀錄</div>
            <table className="backup-table ledger-table">
              <tbody>
                {data.history.map((h) => (
                  <tr key={h.id}>
                    <td>{h.business_date}</td>
                    <td className={h.ok ? "backup-good" : "backup-bad"}>
                      {h.ok ? "全部一致" : `${h.problem_count} 項不一致`}
                      {h.before_restore && <span className="ledger-info">(還原前)</span>}
                    </td>
                    <td className="backup-sub">{when(h.finished_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        )}
      </div>
    </div>
  );
}
