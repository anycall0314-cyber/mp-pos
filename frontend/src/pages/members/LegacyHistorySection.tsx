import { useQueryClient } from "@tanstack/react-query";
import { Fragment, useState } from "react";

import { api } from "@/api/client";
import {
  type LegacyHistoryFilters,
  useLegacyCandidates,
  useLegacyHistory,
} from "@/api/hooks";
import type { LegacyMemberRow } from "@/api/types";
import { useCurrentUser } from "@/auth/AuthContext";
import { Banner } from "@/components/Banner";
import { byDate } from "@/lib/legacyHistory";

/**
 * 會員頁:舊 POS(歐睿)紀錄。
 *
 * 跟 MP 自己的銷貨分開顯示:這裡的金額是舊系統報表值,不是實收。
 * 合計由後端照完整篩選範圍計算(不是加總畫面上這一頁)。
 * 待核的舊紀錄不併入合計,另外提示。
 * 管理員另外看得到「可能是同一人」的舊會員,可以確認或取消對照。
 * 品項直接列出來、不折疊(owner 2026-10-19:「直接顯示所有消費品項，你可以用日期幫我分族群組，但不要折疊」):
 * 照日期分段,同一天裡每張單一小段(店別、單別、單號),底下是那張單的品項。負數(退貨 / 折讓)那一行另外標。
 * 「品名」是舊品名 / 品號的文字比對(舊品名十年來寫法不一),不是「同一樣商品」。
 */

const DOC_TYPES = ["E01", "E11", "E12", "E13", "F01", "F11", "F13", "FS11"];

export function LegacyHistorySection({ memberId }: { memberId: number }) {
  const role = useCurrentUser()?.profile?.role;
  const isAdmin = role === "tenant_admin";
  const qc = useQueryClient();
  const [filters, setFilters] = useState<LegacyHistoryFilters>({});
  const [page, setPage] = useState(1);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const history = useLegacyHistory(memberId, filters, page);
  const candidates = useLegacyCandidates(memberId, isAdmin);
  const data = history.data;
  const pages = data ? Math.max(1, Math.ceil(data.count / 20)) : 1;
  const linked = data?.summary.linked_legacy_members ?? [];

  function patch(k: keyof LegacyHistoryFilters, v: string) {
    setFilters((f) => ({ ...f, [k]: v }));
    setPage(1);
  }

  async function act(path: string, body: object) {
    setError("");
    setBusy(true);
    try {
      await api(path, { method: "POST", body: JSON.stringify(body) });
      qc.invalidateQueries({ queryKey: ["legacy-history"] });
      qc.invalidateQueries({ queryKey: ["legacy-candidates"] });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const link = (c: LegacyMemberRow) =>
    act(`/legacy/members/${c.id}/link/`, {
      member: memberId,
      method: c.reason === "電話相同" ? "phone" : "name",
    });

  if (!isAdmin && data && data.count === 0 && linked.length === 0 && !data.pending.count) {
    return null;
  }

  return (
    <div style={{ marginTop: 24 }}>
      <h4 className="pc-detail-title">
        舊 POS 紀錄
        {data &&
          ` (${data.summary.documents} 張 · ${data.summary.items} 筆 · 淨額 $${data.summary.net_amount.display} · 原始額 $${data.summary.amount.display})`}
      </h4>
      {error && <Banner kind="error" message={error} />}
      {history.error && <Banner kind="error" message={`讀取失敗:${String(history.error)}`} />}
      {data && data.pending.count > 0 && (
        <Banner kind="error" message={`有待核舊 POS 紀錄 ${data.pending.items} 筆`} />
      )}

      {isAdmin && (
        <div className="legacy-links">
          {linked.length > 0 && (
            <div className="legacy-sub">已對照舊編號:{linked.join("、")}</div>
          )}
          {(candidates.data ?? []).map((c) => (
            <div key={c.id} className="legacy-candidate">
              <span>
                {c.source_member_id} {c.name} {c.phone}
                <span className="legacy-sub">
                  {" "}
                  {c.reason} · {c.documents} 張 · ${c.net_amount?.display}
                </span>
              </span>
              <button className="btn small" disabled={busy} onClick={() => link(c)}>
                確認對照
              </button>
            </div>
          ))}
        </div>
      )}

      <div className="legacy-filters">
        <input
          type="date"
          value={filters.date_from ?? ""}
          onChange={(e) => patch("date_from", e.target.value)}
        />
        <input
          type="date"
          value={filters.date_to ?? ""}
          onChange={(e) => patch("date_to", e.target.value)}
        />
        <input
          placeholder="店別"
          value={filters.store ?? ""}
          onChange={(e) => patch("store", e.target.value)}
        />
        <select
          value={filters.doc_type ?? ""}
          onChange={(e) => patch("doc_type", e.target.value)}
        >
          <option value="">全部單別</option>
          {DOC_TYPES.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
        <input
          placeholder="單號"
          value={filters.doc_no ?? ""}
          onChange={(e) => patch("doc_no", e.target.value)}
        />
        <input
          placeholder="舊品名或品號"
          value={filters.item ?? ""}
          onChange={(e) => patch("item", e.target.value)}
        />
      </div>

      <div className="md-table legacy-table-wrap" style={{ height: "auto" }}>
        <table>
          <thead>
            <tr>
              <th>品名 / 品號</th>
              <th className="num" style={{ width: 52 }}>數量</th>
              <th className="num" style={{ width: 80 }}>單價</th>
              <th className="num" style={{ width: 80 }}>原始額</th>
              <th className="num" style={{ width: 80 }}>淨額</th>
              <th style={{ width: 80 }}>業務員</th>
              <th>備註 / 方案</th>
            </tr>
          </thead>
          <tbody>
            {byDate(data?.results ?? []).map((g) => (
              <Fragment key={g.date}>
                <tr className="legacy-date">
                  <td colSpan={7}>{g.date}</td>
                </tr>
                {g.docs.map((d) => (
                  <Fragment key={d.id}>
                    <tr className="legacy-doc">
                      <td colSpan={7}>
                        {d.store} · {d.document_type} {d.document_number}
                        <span className="legacy-tag">舊 POS</span>
                      </td>
                    </tr>
                    {d.items.map((i) => (
                      <tr key={i.ordinal} className={i.net_amount.minor < 0 ? "legacy-neg" : ""}>
                        <td>
                          <div style={{ whiteSpace: "pre-wrap" }}>
                            {i.product_name}
                            {i.net_amount.minor < 0 && <span className="legacy-tag">退貨 / 折讓</span>}
                          </div>
                          <div className="legacy-sub">{i.product_code}</div>
                        </td>
                        <td className="num">{i.quantity}</td>
                        <td className="num">{i.unit_price ? i.unit_price.display : "—"}</td>
                        <td className="num">{i.amount.display}</td>
                        <td className="num">{i.net_amount.display}</td>
                        <td>{i.salesperson}</td>
                        <td style={{ whiteSpace: "pre-wrap" }}>
                          {[i.remarks, i.promotion].filter(Boolean).join("\n")}
                        </td>
                      </tr>
                    ))}
                  </Fragment>
                ))}
              </Fragment>
            ))}
            {data && data.results.length === 0 && (
              <tr>
                <td colSpan={7} className="md-empty">
                  {filters.item ? "找不到這個品名" : "尚無舊 POS 紀錄"}
                </td>
              </tr>
            )}
            {history.isLoading && (
              <tr>
                <td colSpan={7} className="md-empty">
                  載入中…
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {pages > 1 && (
        <div className="legacy-pager">
          <button className="btn small" disabled={page <= 1} onClick={() => setPage(page - 1)}>
            上一頁
          </button>
          <span>
            {page} / {pages}
          </span>
          <button
            className="btn small"
            disabled={page >= pages}
            onClick={() => setPage(page + 1)}
          >
            下一頁
          </button>
        </div>
      )}
    </div>
  );
}
