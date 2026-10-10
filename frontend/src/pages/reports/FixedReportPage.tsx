import { useState } from "react";

import { useFixedReport } from "@/api/hooks";
import { Banner, errorMessageOf } from "@/components/Banner";
import { Toolbar } from "@/components/Toolbar";
import {
  cellText,
  isNegative,
  localDay,
  monthStart,
  type FixedReportPage as PageInfo,
  type ReportRange,
} from "@/lib/fixedReports";

import { ReportRangeBar } from "./ReportRangeBar";

/**
 * 業績彙總 / 商品排行 / 每日彙總:哪幾欄、怎麼算、誰看得到哪一欄都是伺服器給的,這一頁只選日期與門市、照著畫。
 * 數字都是扣掉銷退之後的(退的那一天扣回去)。
 */
export function FixedReportPage({ report }: { report: PageInfo }) {
  const [applied, setApplied] = useState<ReportRange>(() => ({
    from: monthStart(),
    to: localDay(),
    warehouse: "",
  }));
  const { data, isLoading, isError, error } = useFixedReport(report.key, applied);
  const measures = data?.columns.measures ?? [];
  const rows = data?.rows ?? [];

  return (
    <div className="page">
      <Toolbar title={report.title} />
      <ReportRangeBar applied={applied} onApply={setApplied} by={data?.by} />
      {isError && <Banner kind="error" message={errorMessageOf(error)} />}

      {data && (
        <>
          <div className="ex-period">
            {data.applied.period.from} ~ {data.applied.period.to}　已扣銷退
          </div>
          <div className="sd-summary">
            {measures.map((m) => (
              <div key={m.key} className="sd-summary-card">
                <div className="sd-summary-card-label">{m.label}</div>
                <div className="sd-summary-card-value">
                  {cellText(data.totals[m.key], m.format)}
                </div>
              </div>
            ))}
          </div>
        </>
      )}

      <div className="report-table">
        {isLoading && <div className="md-empty">載入中…</div>}
        {data && rows.length === 0 && <div className="md-empty">這段期間沒有資料</div>}
        {data && rows.length > 0 && (
          <table className="report-grid">
            <thead>
              <tr>
                {data.columns.dimensions.map((d) => (
                  <th key={d.key}>{d.label}</th>
                ))}
                {measures.map((m) => (
                  <th key={m.key} className="num">
                    {m.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr key={`${row.dims[0]?.value ?? "none"}-${i}`} className="report-row">
                  {row.dims.map((d, j) => (
                    <td key={j}>{d.label}</td>
                  ))}
                  {measures.map((m) => (
                    <td
                      key={m.key}
                      className={isNegative(row.values[m.key]) ? "num report-neg" : "num"}
                    >
                      {cellText(row.values[m.key], m.format)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {data?.truncated && (
          <div className="ex-note">
            只列前 {rows.length} 筆(共 {data.row_count} 筆);上面的合計是全部
          </div>
        )}
      </div>
    </div>
  );
}
