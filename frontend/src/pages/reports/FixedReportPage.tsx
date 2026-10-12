import { useState } from "react";

import { fetchFixedReportAll, useFixedReport } from "@/api/hooks";
import { Banner, errorMessageOf } from "@/components/Banner";
import { downloadCsv } from "@/components/downloadCsv";
import { Toolbar } from "@/components/Toolbar";
import {
  cellText,
  isNegative,
  localDay,
  monthStart,
  type FixedReportPage as PageInfo,
  type ReportRange,
} from "@/lib/fixedReports";

import { exportFileName, exportIfComplete, fixedReportTable } from "@/lib/reportExports";

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

  // 匯出:照畫面查的條件另外跟伺服器要**全部的列**(商品排行畫面只列前 200 名,檔不能只有前 200 名、合計卻是全部的)
  const [exporting, setExporting] = useState(false);
  const [exportNote, setExportNote] = useState("");
  async function exportAll() {
    setExporting(true);
    setExportNote("");
    try {
      const all = await fetchFixedReportAll(report.key, applied);
      setExportNote(
        exportIfComplete(
          { count: all.rows.length, truncated: all.truncated },
          exportFileName(report.title, {
            store: (all.applied.filters.find((f) => f.dimension === "warehouse")?.values ?? [])
              .map((v) => v.label)
              .join("、"),
            from: all.applied.period.from,
            to: all.applied.period.to,
          }),
          () => fixedReportTable(all),
          downloadCsv,
        ),
      );
    } catch (e) {
      setExportNote(errorMessageOf(e));
    } finally {
      setExporting(false);
    }
  }

  return (
    <div className="page">
      <Toolbar
        title={report.title}
        actions={
          <button className="btn" type="button" disabled={!data || rows.length === 0 || exporting} onClick={exportAll}>
            匯出
          </button>
        }
      />
      {exportNote && <Banner kind="error" message={exportNote} />}
      <ReportRangeBar applied={applied} onApply={setApplied} by={data?.by} />
      {isError && <Banner kind="error" message={errorMessageOf(error)} />}

      {data && (
        <>
          <div className="ex-period">
            {data.applied.period.from} ~ {data.applied.period.to}
            {data.note ? `　${data.note}` : ""}
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
