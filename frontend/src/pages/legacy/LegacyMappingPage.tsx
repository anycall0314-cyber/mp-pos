import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "@/api/client";
import {
  useLegacyExceptions,
  useLegacyMapCandidates,
  useLegacyMaps,
  useLegacyMembers,
} from "@/api/hooks";
import {
  searchMembers,
  searchProducts,
  searchSalesPersons,
  searchWarehouses,
} from "@/api/search";
import type { LegacyMapKind, LegacyMapRow, LegacyMemberRow } from "@/api/types";
import { useCurrentUser } from "@/auth/AuthContext";
import { Banner } from "@/components/Banner";
import { ComboBox, type ComboOption } from "@/components/ComboBox";
import { Toolbar } from "@/components/Toolbar";

/**
 * 設定 → 舊系統對照(公司管理員)
 *
 * 舊 POS 的會員 / 店別 / 品號 / 業務員,要對到 MP 的會員 / 門市 / 商品 / 業務員,
 * 十年紀錄才能跟新系統放在同一張報表、會員頁才看得到。系統只列候選,一律由人確認。
 */

type Tab = "members" | LegacyMapKind | "exceptions";

const TABS: { key: Tab; label: string }[] = [
  { key: "members", label: "會員" },
  { key: "stores", label: "店別" },
  { key: "products", label: "品號" },
  { key: "salespersons", label: "業務" },
  { key: "exceptions", label: "待核" },
];

export function LegacyMappingPage() {
  const role = useCurrentUser()?.profile?.role;
  const isAdmin = role === "tenant_admin";
  const [tab, setTab] = useState<Tab>("members");

  if (!isAdmin) {
    return (
      <div className="page">
        <Toolbar title="舊系統對照" />
        <div className="entry-body">
          <Banner kind="error" message="需要公司管理員權限" />
        </div>
      </div>
    );
  }
  return (
    <div className="page">
      <Toolbar title="舊系統對照" />
      <div className="entry-body legacy-page">
        <div className="legacy-tabs">
          {TABS.map((t) => (
            <button
              key={t.key}
              className={`btn ${tab === t.key ? "primary" : ""}`}
              onClick={() => setTab(t.key)}
            >
              {t.label}
            </button>
          ))}
        </div>
        {tab === "members" && <MembersTab />}
        {(tab === "stores" || tab === "products" || tab === "salespersons") && (
          <MapsTab kind={tab} />
        )}
        {tab === "exceptions" && <ExceptionsTab />}
      </div>
    </div>
  );
}

function useAction() {
  const qc = useQueryClient();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function run(path: string, body: object = {}) {
    setError("");
    setBusy(true);
    try {
      await api(path, { method: "POST", body: JSON.stringify(body) });
      for (const key of ["legacy-members", "legacy-maps", "legacy-map-candidates",
        "legacy-member-detail", "legacy-exceptions", "legacy-history"]) {
        qc.invalidateQueries({ queryKey: [key] });
      }
      return true;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return false;
    } finally {
      setBusy(false);
    }
  }
  return { run, error, busy };
}

function StatusFilter({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">全部</option>
      <option value="unmapped">未對照</option>
      <option value="confirmed">已對照</option>
    </select>
  );
}

function Pager({ page, count, onPage }: { page: number; count: number; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(count / 50));
  if (pages <= 1) return null;
  return (
    <div className="legacy-pager">
      <button className="btn small" disabled={page <= 1} onClick={() => onPage(page - 1)}>
        上一頁
      </button>
      <span>
        {page} / {pages}
      </span>
      <button className="btn small" disabled={page >= pages} onClick={() => onPage(page + 1)}>
        下一頁
      </button>
    </div>
  );
}

// ─────────────────────────── 會員 ───────────────────────────
function MembersTab() {
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("unmapped");
  const [page, setPage] = useState(1);
  const [open, setOpen] = useState<number | null>(null);
  const list = useLegacyMembers({ q, status, page, page_size: 50 });
  const { run, error, busy } = useAction();
  const s = list.data?.summary;

  return (
    <>
      {error && <Banner kind="error" message={error} />}
      {list.error && <Banner kind="error" message={`讀取失敗:${String(list.error)}`} />}
      <div className="legacy-toolbar">
        <input
          placeholder="舊編號 / 姓名 / 電話"
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setPage(1);
          }}
        />
        <StatusFilter
          value={status}
          onChange={(v) => {
            setStatus(v);
            setPage(1);
          }}
        />
        {s && (
          <span className="legacy-sub">
            共 {s.total} · 已對照 {s.confirmed} · 未對照 {s.unmapped}
            {s.open_exceptions > 0 && ` · 待核 ${s.open_exceptions}`}
          </span>
        )}
      </div>
      <table className="line-table">
        <thead>
          <tr>
            <th>舊編號</th>
            <th>姓名</th>
            <th>電話</th>
            <th className="num">單數</th>
            <th className="num">淨額</th>
            <th>最近</th>
            <th>對照</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {(list.data?.results ?? []).map((m) => (
            <MemberRow
              key={m.id}
              m={m}
              open={open === m.id}
              onToggle={() => setOpen(open === m.id ? null : m.id)}
              run={run}
              busy={busy}
            />
          ))}
          {list.data && list.data.results.length === 0 && (
            <tr>
              <td colSpan={8} className="md-empty">
                沒有資料
              </td>
            </tr>
          )}
        </tbody>
      </table>
      <Pager page={page} count={list.data?.count ?? 0} onPage={setPage} />
    </>
  );
}

function MemberRow({
  m, open, onToggle, run, busy,
}: {
  m: LegacyMemberRow;
  open: boolean;
  onToggle: () => void;
  run: (path: string, body?: object) => Promise<boolean>;
  busy: boolean;
}) {
  return (
    <>
      <tr>
        <td title={JSON.stringify(m.source_member_id_exact)}>{m.source_member_id}</td>
        <td>{m.name}</td>
        <td>{m.phone}</td>
        <td className="num">{m.documents}</td>
        <td className="num">{m.net_amount?.display}</td>
        <td>{m.last_date ?? "—"}</td>
        <td>{m.member ? `${m.member.code} ${m.member.name}` : "—"}</td>
        <td className="legacy-actions">
          {m.status === "confirmed" ? (
            <button className="btn small" disabled={busy}
              onClick={() => run(`/legacy/members/${m.id}/unlink/`)}>
              取消對照
            </button>
          ) : (
            <>
              <button className="btn small" disabled={busy} onClick={onToggle}>
                對照會員
              </button>
              <button className="btn small" disabled={busy}
                onClick={() => run(`/legacy/members/${m.id}/create-member/`)}>
                建立會員
              </button>
            </>
          )}
        </td>
      </tr>
      {open && m.status !== "confirmed" && (
        <tr>
          <td colSpan={8}>
            <MemberPicker legacyId={m.id} run={run} busy={busy} onDone={onToggle} />
          </td>
        </tr>
      )}
    </>
  );
}

function MemberPicker({
  legacyId, run, busy, onDone,
}: {
  legacyId: number;
  run: (path: string, body?: object) => Promise<boolean>;
  busy: boolean;
  onDone: () => void;
}) {
  const detail = useQuery({
    queryKey: ["legacy-member-detail", legacyId],
    queryFn: () =>
      api<{ candidates: { id: number; code: string; name: string; phone: string; reason: string }[] }>(
        `/legacy/members/${legacyId}/`,
      ),
  });
  const [picked, setPicked] = useState<number | "">("");
  const link = async (member: number, method: string) => {
    if (await run(`/legacy/members/${legacyId}/link/`, { member, method })) onDone();
  };
  return (
    <div className="legacy-pick">
      {(detail.data?.candidates ?? []).map((c) => (
        <div key={c.id} className="legacy-candidate">
          <span>
            {c.code} {c.name} {c.phone} <span className="legacy-sub">{c.reason}</span>
          </span>
          <button className="btn small" disabled={busy}
            onClick={() => link(c.id, c.reason === "電話相同" ? "phone" : "name")}>
            確認
          </button>
        </div>
      ))}
      <div className="legacy-candidate">
        <ComboBox
          value={picked}
          onChange={(id) => setPicked(id)}
          fetchOptions={searchMembers}
          placeholder="搜尋會員"
        />
        <button className="btn small" disabled={busy || picked === ""}
          onClick={() => picked !== "" && link(picked, "manual")}>
          確認
        </button>
      </div>
    </div>
  );
}

// ─────────────────────────── 店別 / 品號 / 業務員 ───────────────────────────
const SEARCH: Record<LegacyMapKind, (q: string) => Promise<ComboOption<unknown>[]>> = {
  stores: searchWarehouses as (q: string) => Promise<ComboOption<unknown>[]>,
  products: searchProducts as (q: string) => Promise<ComboOption<unknown>[]>,
  salespersons: searchSalesPersons as (q: string) => Promise<ComboOption<unknown>[]>,
};

function MapsTab({ kind }: { kind: LegacyMapKind }) {
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("unmapped");
  const [page, setPage] = useState(1);
  const [open, setOpen] = useState<number | null>(null);
  const list = useLegacyMaps(kind, { q, status, page, page_size: 50 });
  const { run, error, busy } = useAction();
  const s = list.data?.summary;
  return (
    <>
      {error && <Banner kind="error" message={error} />}
      {list.error && <Banner kind="error" message={`讀取失敗:${String(list.error)}`} />}
      <div className="legacy-toolbar">
        <input
          placeholder={kind === "products" ? "舊品號 / 品名" : "舊代號"}
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setPage(1);
          }}
        />
        <StatusFilter
          value={status}
          onChange={(v) => {
            setStatus(v);
            setPage(1);
          }}
        />
        {s && (
          <span className="legacy-sub">
            共 {s.total} · 已對照 {s.confirmed} · 未對照 {s.unmapped}
          </span>
        )}
      </div>
      <table className="line-table">
        <thead>
          <tr>
            <th>舊代號</th>
            {kind === "products" && <th>舊品名</th>}
            <th className="num">筆數</th>
            <th className="num">淨額</th>
            <th>對照</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {(list.data?.results ?? []).map((r) => (
            <MapRow
              key={r.id}
              kind={kind}
              r={r}
              open={open === r.id}
              onToggle={() => setOpen(open === r.id ? null : r.id)}
              run={run}
              busy={busy}
            />
          ))}
          {list.data && list.data.results.length === 0 && (
            <tr>
              <td colSpan={6} className="md-empty">
                沒有資料
              </td>
            </tr>
          )}
        </tbody>
      </table>
      <Pager page={page} count={list.data?.count ?? 0} onPage={setPage} />
    </>
  );
}

function MapRow({
  kind, r, open, onToggle, run, busy,
}: {
  kind: LegacyMapKind;
  r: LegacyMapRow;
  open: boolean;
  onToggle: () => void;
  run: (path: string, body?: object) => Promise<boolean>;
  busy: boolean;
}) {
  const cols = kind === "products" ? 6 : 5;
  return (
    <>
      <tr>
        <td title={JSON.stringify(r.key_exact)}>{r.key || "(空白)"}</td>
        {kind === "products" && <td style={{ whiteSpace: "pre-wrap" }}>{r.name_seen}</td>}
        <td className="num">{r.items}</td>
        <td className="num">{r.net_amount?.display}</td>
        <td>{r.target?.label ?? "—"}</td>
        <td className="legacy-actions">
          {r.status === "confirmed" ? (
            <button className="btn small" disabled={busy}
              onClick={() => run(`/legacy/maps/${kind}/${r.id}/revoke/`)}>
              取消對照
            </button>
          ) : (
            <button className="btn small" disabled={busy} onClick={onToggle}>
              選擇對象
            </button>
          )}
        </td>
      </tr>
      {open && r.status !== "confirmed" && (
        <tr>
          <td colSpan={cols}>
            <MapPicker kind={kind} id={r.id} run={run} busy={busy} onDone={onToggle} />
          </td>
        </tr>
      )}
    </>
  );
}

function MapPicker({
  kind, id, run, busy, onDone,
}: {
  kind: LegacyMapKind;
  id: number;
  run: (path: string, body?: object) => Promise<boolean>;
  busy: boolean;
  onDone: () => void;
}) {
  const candidates = useLegacyMapCandidates(kind, id);
  const [picked, setPicked] = useState<number | "">("");
  const confirm = async (target: number, method: string) => {
    if (await run(`/legacy/maps/${kind}/${id}/confirm/`, { target, method })) onDone();
  };
  return (
    <div className="legacy-pick">
      {(candidates.data ?? []).map((c) => (
        <div key={c.id} className="legacy-candidate">
          <span>
            {c.label} <span className="legacy-sub">{c.reason}</span>
          </span>
          <button className="btn small" disabled={busy}
            onClick={() => confirm(c.id, c.reason === "代碼相同" ? "code" : kind === "products" ? "match" : "name")}>
            確認
          </button>
        </div>
      ))}
      <div className="legacy-candidate">
        <ComboBox
          value={picked}
          onChange={(v) => setPicked(v)}
          fetchOptions={SEARCH[kind]}
          placeholder="搜尋"
        />
        <button className="btn small" disabled={busy || picked === ""}
          onClick={() => picked !== "" && confirm(picked, "manual")}>
          確認
        </button>
      </div>
    </div>
  );
}

// ─────────────────────────── 待核 ───────────────────────────
function ExceptionsTab() {
  const list = useLegacyExceptions();
  const { run, error, busy } = useAction();
  const [note, setNote] = useState<Record<number, string>>({});
  const [evidence, setEvidence] = useState<Record<number, string>>({});
  return (
    <>
      {error && <Banner kind="error" message={error} />}
      {(list.data ?? []).map((e) => (
        <div key={e.id} className="backup-card">
          <div className="section-head">
            舊編號 {e.legacy_member} · {e.status === "open" ? "待核" : "已處理"}
          </div>
          <dl className="backup-facts">
            <dt>來源累計</dt>
            <dd>{e.list_amount.display}</dd>
            <dt>明細淨額</dt>
            <dd>{e.detail_net_amount.display}</dd>
            <dt>差額</dt>
            <dd>{e.difference.display}</dd>
            <dt>單據 / 明細</dt>
            <dd>
              {e.documents} / {e.items}
            </dd>
          </dl>
          <div className="legacy-raw">{e.rows_json}</div>
          {e.status === "open" ? (
            <div className="legacy-pick">
              <textarea
                placeholder="理由"
                value={note[e.id] ?? ""}
                onChange={(ev) => setNote({ ...note, [e.id]: ev.target.value })}
              />
              <textarea
                placeholder="新的來源證據"
                value={evidence[e.id] ?? ""}
                onChange={(ev) => setEvidence({ ...evidence, [e.id]: ev.target.value })}
              />
              <div>
                <button
                  className="btn small"
                  disabled={busy || !(note[e.id] ?? "").trim() || !(evidence[e.id] ?? "").trim()}
                  onClick={() =>
                    run(`/legacy/exceptions/${e.id}/resolve/`, {
                      note: note[e.id],
                      evidence: evidence[e.id],
                    })
                  }
                >
                  結案
                </button>
              </div>
            </div>
          ) : (
            <dl className="backup-facts">
              <dt>處理人</dt>
              <dd>{e.resolved_by || "—"}</dd>
              <dt>處理時間</dt>
              <dd>{e.resolved_at ?? "—"}</dd>
              <dt>理由</dt>
              <dd style={{ whiteSpace: "pre-wrap" }}>{e.resolution_note}</dd>
              <dt>新證據</dt>
              <dd style={{ whiteSpace: "pre-wrap" }}>{e.resolution_evidence}</dd>
            </dl>
          )}
        </div>
      ))}
      {list.data && list.data.length === 0 && <div className="md-empty">沒有待核紀錄</div>}
    </>
  );
}
