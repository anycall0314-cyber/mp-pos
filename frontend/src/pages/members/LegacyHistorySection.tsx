import { Fragment, useState } from "react";

import { type LegacyHistoryFilters, useLegacyHistory } from "@/api/hooks";
import { useCurrentUser } from "@/auth/AuthContext";
import { Banner } from "@/components/Banner";
import { errorText } from "@/lib/errorText";
import { byDate, docKind } from "@/lib/legacyHistory";

/**
 * 會員頁:舊系統(歐睿)紀錄。
 *
 * 2026-10-24 全站檢視 E3:叫法統一「舊系統」;單別寫銷貨 / 退貨(不寫 E01、F11);只留一個金額(淨額);
 * 篩選只留日期與品名;待核的只給管理員看、不用紅色(店員看了以為出錯)。
 *
 * 跟 MP 自己的銷貨分開顯示:這裡的金額是舊系統報表值,不是實收。
 * 合計由後端照完整篩選範圍計算(不是加總畫面上這一頁)。
 * 待核的舊紀錄不併入合計,另外提示。
 * 只看:「可能是同一人」的舊會員要對照,在會員名單右邊(`LegacyLinkCandidates`;消費紀錄分頁不給任何操作,owner 2026-10-21)。
 * 品項直接列出來、不折疊(owner 2026-10-19:「直接顯示所有消費品項，你可以用日期幫我分族群組，但不要折疊」):
 * 照日期分段,同一天裡每張單一小段(店別、單別、單號),底下是那張單的品項。負數(退貨 / 折讓)那一行另外標。
 * 「品名」是舊品名 / 品號的文字比對(舊品名十年來寫法不一),不是「同一樣商品」。
 */

export function LegacyHistorySection({ memberId }: { memberId: number }) {
  const role = useCurrentUser()?.profile?.role;
  const isAdmin = role === "tenant_admin";
  const [filters, setFilters] = useState<LegacyHistoryFilters>({});
  const [page, setPage] = useState(1);

  const history = useLegacyHistory(memberId, filters, page);
  const data = history.data;
  const pages = data ? Math.max(1, Math.ceil(data.count / 20)) : 1;
  const linked = data?.summary.linked_legacy_members ?? [];

  function patch(k: keyof LegacyHistoryFilters, v: string) {
    setFilters((f) => ({ ...f, [k]: v }));
    setPage(1);
  }

  // 沒有舊紀錄就整段不出現;有打篩選條件時不收(不然打一個找不到的品名,整段連同篩選格一起不見)
  const filtering = Object.values(filters).some((v) => v);
  const adminNote = isAdmin && (linked.length > 0 || (data?.pending.count ?? 0) > 0);
  if (data && data.count === 0 && !filtering && !adminNote) {
    return null;
  }

  return (
    <div style={{ marginTop: 24 }}>
      <h4 className="pc-detail-title">
        舊系統
        {data && ` (${data.summary.documents} 張 · $${data.summary.net_amount.display})`}
      </h4>
      {history.error && <Banner kind="error" message={`讀取失敗:${errorText(history.error)}`} />}
      {isAdmin && data && data.pending.count > 0 && (
        <div className="legacy-sub">另有待核 {data.pending.items} 筆,沒算進合計</div>
      )}

      {isAdmin && linked.length > 0 && (
        <div className="legacy-links">
          <div className="legacy-sub">已對照舊編號:{linked.join("、")}</div>
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
          placeholder="品名"
          value={filters.item ?? ""}
          onChange={(e) => patch("item", e.target.value)}
        />
      </div>

      <div className="md-table legacy-table-wrap" style={{ height: "auto" }}>
        <table>
          <thead>
            <tr>
              <th>品名</th>
              <th className="num" style={{ width: 52 }}>數量</th>
              <th className="num" style={{ width: 80 }}>單價</th>
              <th className="num" style={{ width: 90 }}>金額</th>
              <th style={{ width: 80 }}>業務員</th>
              <th>備註 / 方案</th>
            </tr>
          </thead>
          <tbody>
            {byDate(data?.results ?? []).map((g) => (
              <Fragment key={g.date}>
                <tr className="legacy-date">
                  <td colSpan={6}>{g.date}</td>
                </tr>
                {g.docs.map((d) => (
                  <Fragment key={d.id}>
                    <tr className="legacy-doc">
                      <td colSpan={6}>
                        {d.store} · {docKind(d.document_type)} {d.document_number}
                        <span className="legacy-tag">舊系統</span>
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
                <td colSpan={6} className="md-empty">
                  {filters.item ? "找不到這個品名" : "沒有舊系統紀錄"}
                </td>
              </tr>
            )}
            {history.isLoading && (
              <tr>
                <td colSpan={6} className="md-empty">
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
