import { useRef, useState } from "react";

import {
  searchDevices,
  useDecideDeviceCandidate,
  useDeviceShares,
  useDeviceWatch,
  useRemoveDeviceShare,
  useSetDeviceShare,
} from "@/api/hooks";
import type { DeviceCandidateRow, DeviceRow, DeviceShareRule } from "@/api/types";
import { Banner } from "@/components/Banner";
import { ComboBox, type ComboOption } from "@/components/ComboBox";
import { apiErrorText } from "@/components/workbench/errors";
import { toast } from "@/components/workbench/toast";
import { listText, runLine, runNotes, stamp } from "@/lib/deviceWatch";

/**
 * 平台管理 → 型號庫:每天自動讀手機王加新機(backend/apps/catalog/device_watch.py)。
 * 上面是上一次檢查成功沒有;「待確認」= 很像型號庫某一支、新的品牌、看不出種類,要平台管理員按;
 * 「等資料」= 還沒上市 / 還沒有顏色或容量,之後每天再讀,齊了自動加;最下面是最近 30 天自動加的。
 * 「配件共用」= 新機的配件跟哪一支一樣(螢幕 / 機身分開;backend/apps/catalog/device_share.py),最近加的那幾支可以直接按「配件共用」帶進來。
 */
export function PlatformDevicesTab() {
  const watch = useDeviceWatch();
  const [shareFor, setShareFor] = useState<{ device: DeviceRow; n: number } | null>(null);
  const shareRef = useRef<HTMLDivElement>(null);
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

      <div ref={shareRef}>
        <SharePanel prefill={shareFor} />
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
              <th style={{ width: 110 }}></th>
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
                <td>
                  <button
                    className="btn"
                    type="button"
                    onClick={() => {
                      setShareFor((cur) => ({
                        device: { uid: d.uid, brand: d.brand, name: d.name, category: d.category, category_label: d.category_label, launched: d.launched },
                        n: (cur?.n ?? 0) + 1,
                      }));
                      shareRef.current?.scrollIntoView({ block: "start" });
                    }}
                  >
                    配件共用
                  </button>
                </td>
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

const deviceLabel = (d: DeviceRow) => `${d.brand} ${d.name}`.trim();
const partsText = (r: { screen: boolean; body: boolean }) => [r.screen && "螢幕", r.body && "機身"].filter(Boolean).join("、");

function deviceOption(d: DeviceRow, i: number): ComboOption<DeviceRow> {
  return { id: i + 1, label: deviceLabel(d), secondary: [d.category_label, d.launched].filter(Boolean).join(" "), payload: d };
}

/** 選一支型號庫的型號(ComboBox 只收數字編號:照這一次查到的順序編,選到的那一支自己帶著) */
function DevicePick({ value, onChange, category, placeholder, disabled }: {
  value: DeviceRow | null;
  onChange: (d: DeviceRow | null) => void;
  category?: string;
  placeholder: string;
  disabled?: boolean;
}) {
  const selected = value ? { ...deviceOption(value, -1), id: 1_000_000 } : null;
  return (
    <ComboBox<DeviceRow>
      value={selected ? selected.id : ""}
      selectedOption={selected}
      onChange={(_id, opt) => onChange(opt?.payload ?? null)}
      fetchOptions={async (q) => {
        if (!q.trim()) return [];
        const rows = await searchDevices(q);
        return rows.filter((d) => !category || d.category === category).map(deviceOption);
      }}
      placeholder={placeholder}
      disabled={disabled}
      emptyHint="型號庫找不到"
    />
  );
}

function SharePanel({ prefill }: { prefill: { device: DeviceRow; n: number } | null }) {
  const shares = useDeviceShares();
  const save = useSetDeviceShare();
  const remove = useRemoveDeviceShare();
  const [device, setDevice] = useState<DeviceRow | null>(null);
  const [sameAs, setSameAs] = useState<DeviceRow | null>(null);
  // 預設只勾螢幕:機身要確定真的同一套才勾(紅隊)
  const [screen, setScreen] = useState(true);
  const [body, setBody] = useState(false);
  const [error, setError] = useState("");
  // 按「修改」:兩支型號鎖住、只改螢幕 / 機身(換型號會變成另外一條,原本那一條還在 —— 複審 P2)
  const [editing, setEditing] = useState<number | null>(null);
  const [seen, setSeen] = useState(0);
  function reset(d: DeviceRow | null = null) {
    setDevice(d);
    setSameAs(null);
    setScreen(true);
    setBody(false);
    setEditing(null);
    setError("");
  }
  if (prefill && prefill.n !== seen) {
    setSeen(prefill.n);
    reset(prefill.device);
  }
  const busy = save.isPending || remove.isPending;
  const rules = shares.data ?? [];

  function edit(r: DeviceShareRule) {
    setDevice(r.device);
    setSameAs(r.same_as);
    setScreen(r.screen);
    setBody(r.body);
    setEditing(r.id);
    setError("");
  }

  async function go() {
    if (busy || !device || !sameAs) return;
    setError("");
    try {
      const r = await save.mutateAsync({ device: device.uid, same_as: sameAs.uid, screen, body });
      toast(r.products ? `${deviceLabel(device)}:加到 ${r.tenants} 家、${r.products} 個配件` : `${deviceLabel(device)}:已設定,目前沒有要加的配件`);
      reset();
    } catch (e) {
      setError(apiErrorText(e));
    }
  }

  async function drop(r: DeviceShareRule) {
    if (busy) return;
    setError("");
    try {
      await remove.mutateAsync(r.id);
      if (editing === r.id) reset();
      toast(`${deviceLabel(r.device)}:已取消,已經加上的留著`);
    } catch (e) {
      setError(apiErrorText(e));
    }
  }

  return (
    <>
      <div className="pv-head">
        <h3>配件共用 {rules.length}</h3>
      </div>
      <div className="dw-actions ds-form">
        <div className="ds-pick">
          <DevicePick value={device} onChange={(d) => { setDevice(d); if (d && sameAs && d.category !== sameAs.category) setSameAs(null); }}
                      placeholder="新機" disabled={busy || editing != null} />
        </div>
        <span>配件跟</span>
        <div className="ds-pick">
          <DevicePick value={sameAs} onChange={setSameAs} category={device?.category} placeholder="哪一支" disabled={busy || !device || editing != null} />
        </div>
        <span>一樣</span>
        <label className="ds-check">
          <input type="checkbox" checked={screen} onChange={(e) => setScreen(e.target.checked)} disabled={busy} />
          螢幕
        </label>
        <label className="ds-check">
          <input type="checkbox" checked={body} onChange={(e) => setBody(e.target.checked)} disabled={busy} />
          機身
        </label>
        <button className="btn primary" type="button" disabled={busy || !device || !sameAs || !(screen || body)} onClick={go}>
          設定
        </button>
        {editing != null && (
          <button className="btn" type="button" disabled={busy} onClick={() => reset()}>
            放棄
          </button>
        )}
      </div>
      {error && <div className="dw-error">{error}</div>}
      {shares.isError ? (
        <Banner kind="error" message={apiErrorText(shares.error)} />
      ) : rules.length === 0 ? (
        <div className="md-empty">{shares.isLoading ? "載入中…" : "沒有"}</div>
      ) : (
        <table className="line-table">
          <thead>
            <tr>
              <th>新機</th>
              <th>配件跟這一支一樣</th>
              <th style={{ width: 110 }}>一樣的</th>
              <th style={{ width: 110 }}>日期</th>
              <th style={{ width: 150 }}></th>
            </tr>
          </thead>
          <tbody>
            {rules.map((r) => (
              <tr key={r.id}>
                <td>{deviceLabel(r.device)}</td>
                <td>{deviceLabel(r.same_as)}</td>
                <td>{partsText(r)}</td>
                <td className="dw-nowrap">{stamp(r.created_at)}</td>
                <td>
                  <div className="dw-actions">
                    <button className="btn" type="button" disabled={busy} onClick={() => edit(r)}>
                      修改
                    </button>
                    <button className="btn" type="button" disabled={busy} onClick={() => drop(r)}>
                      取消
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
