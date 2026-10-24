import { useState } from "react";
import { Link } from "react-router-dom";

import { useCommissionLines } from "@/api/hooks";
import { useDefaultWarehouse } from "@/auth/AuthContext";
import { Banner, errorMessageOf } from "@/components/Banner";
import { downloadCsv } from "@/components/downloadCsv";
import { Toolbar } from "@/components/Toolbar";
import {
  cellText,
  isNegative,
  localDay,
  monthStart,
  type ReportRange,
} from "@/lib/fixedReports";

import { commissionTable, exportFileName, exportIfComplete, tooManyToExport } from "@/lib/reportExports";

import { ReportRangeBar } from "./ReportRangeBar";

/**
 * 門號佣金明細:一筆門號一列;期間內的銷退另外一列負的(列在退的那一天)。
 * 合計 = 業績彙總同一段期間的「門號佣金」。公司佣金那一欄只有管理員的資料裡有。
 */
export function CommissionLinesPage() {
  const [applied, setApplied] = useState<ReportRange>(() => ({
    from: monthStart(),
    to: localDay(),
    warehouse: "",
  }));
  const { data, isLoading, isError, error } = useCommissionLines(applied);
  const rows = data?.rows ?? [];
  const manager = !!data?.manager;
  const lock = useDefaultWarehouse();
  // 超過一次列得出來的筆數:不給只有一部分的檔(拿去對佣金會少一截)
  const tooMany = tooManyToExport(rows.length, data?.truncated);

  return (
    <div className="page">
      <Toolbar
        title="佣金明細"
        actions={
          <button
            className="btn"
            type="button"
            disabled={!data || rows.length === 0 || !!tooMany}
            title={tooMany || undefined}
            onClick={() =>
              data &&
              exportIfComplete(
                { count: rows.length, truncated: data.truncated },
                exportFileName("佣金明細", {
                  store: lock.locked ? lock.name : (applied.warehouseName ?? ""),
                  from: data.applied.from,
                  to: data.applied.to,
                }),
                () => commissionTable(data),
                downloadCsv,
              )
            }
          >
            匯出
          </button>
        }
      />
      <ReportRangeBar applied={applied} onApply={setApplied} />
      {isError && <Banner kind="error" message={errorMessageOf(error)} />}

      {data && (
        <>
          <div className="ex-period">
            {/* 這一份是哪段期間、哪一家(data 跟 applied 是同一份查詢;全站檢視 R05) */}
            {data.applied.from} ~ {data.applied.to} · {lock.locked ? lock.name : applied.warehouseName || "全部門市"}　已扣銷退
          </div>
          <div className="sd-summary">
            <div className="sd-summary-card">
              <div className="sd-summary-card-label">業務員佣金</div>
              <div className="sd-summary-card-value">{cellText(data.totals.commission)}</div>
            </div>
            {manager && (
              <div className="sd-summary-card">
                <div className="sd-summary-card-label">公司佣金</div>
                <div className="sd-summary-card-value">
                  {cellText(data.totals.company_commission)}
                </div>
              </div>
            )}
            <div className="sd-summary-card">
              <div className="sd-summary-card-label">筆數</div>
              <div className="sd-summary-card-value">{data.row_count}</div>
            </div>
          </div>
        </>
      )}

      <div className="report-table">
        {isLoading && <div className="md-empty">載入中…</div>}
        {data && rows.length === 0 && <div className="md-empty">這段期間沒有門號</div>}
        {data && rows.length > 0 && (
          <table className="report-grid">
            <thead>
              <tr>
                <th>日期</th>
                <th>單號</th>
                <th>門市</th>
                <th>門號</th>
                <th>電信</th>
                <th>方案</th>
                <th>業務員</th>
                <th className="num">業務員佣金</th>
                {manager && <th className="num">公司佣金</th>}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={`${r.kind}-${r.doc_id}-${r.msisdn}`} className="report-row">
                  <td>{r.date}</td>
                  <td>
                    {r.kind === "sale" ? (
                      <Link to={`/sales/${r.doc_id}`}>{r.doc_no}</Link>
                    ) : (
                      <>
                        {r.doc_no} <span className="pill void">銷退</span>
                      </>
                    )}
                  </td>
                  <td>{r.warehouse}</td>
                  <td>{r.msisdn}</td>
                  <td>{r.carrier}</td>
                  <td>{r.plan}</td>
                  <td>{r.sales_person || "(未指定)"}</td>
                  <td className={isNegative(r.commission) ? "num report-neg" : "num"}>
                    {cellText(r.commission)}
                  </td>
                  {manager && (
                    <td className={isNegative(r.company_commission) ? "num report-neg" : "num"}>
                      {cellText(r.company_commission)}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {data?.truncated && (
          <div className="ex-note">
            只列前 {rows.length} 筆(共 {data.row_count} 筆以上);上面的合計是全部,請把期間縮短
          </div>
        )}
      </div>
    </div>
  );
}
