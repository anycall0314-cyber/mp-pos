import { useState } from "react";
import { Link } from "react-router-dom";

import { useCommissionLines } from "@/api/hooks";
import { Banner, errorMessageOf } from "@/components/Banner";
import { Toolbar } from "@/components/Toolbar";
import {
  cellText,
  isNegative,
  localDay,
  monthStart,
  type ReportRange,
} from "@/lib/fixedReports";

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

  return (
    <div className="page">
      <Toolbar title="佣金明細" />
      <ReportRangeBar applied={applied} onApply={setApplied} />
      {isError && <Banner kind="error" message={errorMessageOf(error)} />}

      {data && (
        <>
          <div className="ex-period">
            {data.applied.from} ~ {data.applied.to}　已扣銷退
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
