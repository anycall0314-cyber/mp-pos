import { useState } from "react";

import { useDecideDeviceCandidate, useDeviceWatch } from "@/api/hooks";
import type { DeviceCandidateRow } from "@/api/types";
import { Banner } from "@/components/Banner";
import { apiErrorText } from "@/components/workbench/errors";
import { toast } from "@/components/workbench/toast";
import { listText, runLine, runNotes, stamp } from "@/lib/deviceWatch";

/**
 * 平台管理 → 型號庫:每天自動讀手機王加新機(backend/apps/catalog/device_watch.py)。
 * 上面是上一次檢查成功沒有;「待確認」= 很像型號庫某一支、新的品牌、看不出種類,要平台管理員按;
 * 「等資料」= 還沒上市 / 還沒有顏色或容量,之後每天再讀,齊了自動加;最下面是最近 30 天自動加的。
 */
export function PlatformDevicesTab() {
  const watch = useDeviceWatch();
  const data = watch.data;
  const review = (data?.candidates ?? []).filter((c) => c.status === "review");
  const waiting = (data?.candidates ?? []).filter((c) => c.status === "waiting");

  if (watch.isLoading) return <div className="md-empty">載入中…</div>;
  if (watch.isError || !data) return <Banner kind="error" message={apiErrorText(watch.error)} />;
  return (
    <div className="dw-page">
      <div className={`dw-last ${data.last && !data.last.ok ? "bad" : ""}`}>
        <div>上一次:{runLine(data.last)}</div>
        <div className="dw-dim">
          每天 {data.at || "不自動檢查"} · 型號庫 {data.catalog_count} 支 · 新機自動建品號:
          {data.auto_tenants.length ? data.auto_tenants.join("、") : "沒有公司勾"}
        </div>
        {data.last && !data.last.ok && runNotes(data.last).map((n) => <div key={n}>{n}</div>)}
      </div>

      <div className="pv-head">
        <h3>待確認 {review.length}</h3>
      </div>
      {review.length === 0 ? <div className="md-empty">沒有</div> : <CandidateTable rows={review} />}

      <div className="pv-head">
        <h3>等資料 {waiting.length}</h3>
      </div>
      {waiting.length === 0 ? <div className="md-empty">沒有</div> : <CandidateTable rows={waiting} />}

      <div className="pv-head">
        <h3>最近 30 天自動加的 {data.added.length}</h3>
      </div>
      {data.added.length === 0 ? (
        <div className="md-empty">沒有</div>
      ) : (
        <table className="line-table">
          <thead>
            <tr>
              <th style={{ width: 90 }}>加入</th>
              <th style={{ width: 70 }}>類別</th>
              <th>型號</th>
              <th style={{ width: 90 }}>上市</th>
              <th>容量</th>
              <th>顏色</th>
            </tr>
          </thead>
          <tbody>
            {data.added.map((d) => (
              <tr key={d.uid}>
                <td>{stamp(d.created_at)}</td>
                <td>{d.category_label}</td>
                <td>
                  {d.sources[0] ? (
                    <a href={d.sources[0]} target="_blank" rel="noreferrer noopener">
                      {d.brand} {d.name}
                    </a>
                  ) : (
                    `${d.brand} ${d.name}`
                  )}
                </td>
                <td className="dw-nowrap">{d.launched}</td>
                <td>{listText(d.capacities)}</td>
                <td>{listText(d.colors)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <div className="pv-head">
        <h3>最近 7 次檢查</h3>
      </div>
      {data.runs.length === 0 ? (
        <div className="md-empty">還沒有檢查過</div>
      ) : (
        <ul className="dw-runs">
          {data.runs.map((r) => (
            <li key={r.day} className={r.ok ? "" : "bad"}>
              {runLine(r)}
              {r.notes.length > 0 && <div className="dw-dim">{r.notes.slice(0, 5).join(";")}</div>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function CandidateTable({ rows }: { rows: DeviceCandidateRow[] }) {
  return (
    <table className="line-table dw-table">
      <thead>
        <tr>
          <th>手機王的名稱</th>
          <th style={{ width: 70 }}>類別</th>
          <th style={{ width: 90 }}>上市</th>
          <th>容量 / 顏色</th>
          <th>原因</th>
          <th style={{ width: 360 }}>要怎麼辦</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((c) => (
          <CandidateRow key={c.id} row={c} />
        ))}
      </tbody>
    </table>
  );
}

function CandidateRow({ row }: { row: DeviceCandidateRow }) {
  const decide = useDecideDeviceCandidate();
  const [name, setName] = useState(row.name);
  const [sameAs, setSameAs] = useState(row.near[0]?.uid ?? "");
  const [error, setError] = useState("");
  const busy = decide.isPending;

  async function go(action: "add" | "same" | "dismiss", uid?: string) {
    if (busy) return;
    setError("");
    try {
      const r = await decide.mutateAsync({ id: row.id, action, name: action === "add" ? name : undefined, uid });
      const done = action === "add" ? "已加進型號庫" : action === "same" ? "記成型號庫原本那一支" : "不收";
      toast(`${row.list_name}:${done}${r.count > 1 ? `(同一支 ${r.count} 頁)` : ""}`);
    } catch (e) {
      setError(apiErrorText(e));
    }
  }

  return (
    <tr>
      <td>
        <a href={row.url} target="_blank" rel="noreferrer noopener">
          {row.list_name}
        </a>
      </td>
      <td>{row.category_label || "—"}</td>
      <td className="dw-nowrap">{row.launched || "—"}</td>
      <td>
        <div>{listText(row.capacities)}</div>
        <div className="dw-dim">{listText(row.colors)}</div>
      </td>
      <td>{row.reason}</td>
      <td>
        <div className="dw-actions">
          {row.can_add && (
            <>
              <label className="dw-name">
                <span>{row.brand || "品牌?"}</span>
                <input value={name} onChange={(e) => setName(e.target.value)} disabled={busy} aria-label="型號名稱" />
              </label>
              <button className="btn primary" type="button" disabled={busy || !name.trim()} onClick={() => go("add")}>
                新增型號
              </button>
            </>
          )}
          {row.near.length > 1 && (
            <select value={sameAs} onChange={(e) => setSameAs(e.target.value)} disabled={busy} aria-label="是型號庫的哪一支">
              {row.near.map((n) => (
                <option key={n.uid} value={n.uid}>
                  {n.name}
                </option>
              ))}
            </select>
          )}
          {row.near.length > 0 && (
            <button className="btn" type="button" disabled={busy || !sameAs} onClick={() => go("same", sameAs)}>
              同一型號
            </button>
          )}
          <button className="btn" type="button" disabled={busy} onClick={() => go("dismiss")}>
            不收這筆
          </button>
        </div>
        {row.near.length === 1 && <div className="dw-dim">同一型號 = {row.near[0].name}</div>}
        {error && <div className="dw-error">{error}</div>}
      </td>
    </tr>
  );
}
