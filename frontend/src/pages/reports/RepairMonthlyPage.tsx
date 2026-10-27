import { useState } from "react";
import { Link } from "react-router-dom";

import { fetchRepairMonthlyExport, useRepairMonthly } from "@/api/hooks";
import { useSeesActualCost } from "@/auth/AuthContext";
import type { Warehouse } from "@/api/types";
import { Banner, errorMessageOf } from "@/components/Banner";
import { Toolbar } from "@/components/Toolbar";
import { isNegative, localDay, monthStart, rangeReady } from "@/lib/fixedReports";
import { money } from "@/lib/money";
import {
  PEOPLE_HEAD,
  repairCards,
  repairTable,
  wayLabel,
  type RepairFilter,
} from "@/lib/repairReport";
import { exportFileName, exportIfComplete } from "@/lib/reportExports";
import { docPath, pageCount } from "@/lib/stockReports";
import {
  downloadCsv,
  NOT_PICKED,
  Pager,
  StoreField,
  useStoreName,
  type Picked,
} from "@/pages/inventory/stockReportParts";
import { PeriodQuick } from "@/components/PeriodQuick";

/**
 * 維修月報:期間內完工的維修單 —— 合計、每個人分到多少、逐筆。
 * 哪幾張算、毛利怎麼算、每個人分到多少、下拉的選項都由伺服器決定;鎖在門市的帳號只看自己門市。
 */
export function RepairMonthlyPage() {
  // 不是管理員:伺服器照業務員成本算零件成本與毛利,欄名跟著換(owner 2026-10-28)
  const actual = useSeesActualCost();
  const [applied, setApplied] = useState<RepairFilter>(() => ({
    from: monthStart(),
    to: localDay(),
    warehouse: "",
    way: "",
  }));
  const [from, setFrom] = useState(applied.from);
  const [to, setTo] = useState(applied.to);
  const [store, setStore] = useState<Picked<Warehouse>>(NOT_PICKED);
  const [way, setWay] = useState("");
  const [page, setPage] = useState(1);
  const [exporting, setExporting] = useState(false);
  const [exportNote, setExportNote] = useState("");
  const [appliedStore, setAppliedStore] = useState<Picked<Warehouse>>(NOT_PICKED);
  const storeName = useStoreName(appliedStore);

  const { data, isFetching, isError, error } = useRepairMonthly(applied, page);
  const ready = rangeReady({ from, to });
  const rows = data?.results ?? [];
  const ways = data?.choices.way;

  function apply(over?: { from: string; to: string }) {
    if (!over && !ready) return;
    const range = over ?? { from, to };
    setApplied({ ...range, warehouse: store.id, way });
    setAppliedStore(store);
    setPage(1);
    setExportNote("");
  }

  async function exportAll() {
    setExporting(true);
    setExportNote("");
    try {
      const all = await fetchRepairMonthlyExport(applied);
      setExportNote(
        exportIfComplete(all, exportFileName("維修月報", { store: storeName, from: applied.from, to: applied.to }), () => repairTable(all, actual), downloadCsv),
      );
    } catch (e) {
      setExportNote(errorMessageOf(e));
    } finally {
      setExporting(false);
    }
  }

  return (
    <div className="page sr-page">
      <Toolbar
        title="維修月報"
        actions={
          <button
            className="btn"
            type="button"
            disabled={!data || data.count === 0 || exporting}
            onClick={exportAll}
          >
            匯出
          </button>
        }
      />
      <div className="list-filterbar sr-filter">
        <label>
          起日
          <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
        </label>
        <label>
          迄日
          <input type="date" value={to} onChange={(e) => setTo(e.target.value)} />
        </label>
        <StoreField value={store} onChange={setStore} />
        {ways && (
          <label>
            方式
            <select value={way} onChange={(e) => setWay(e.target.value)}>
              <option value="">全部</option>
              {ways.map((c) => (
                <option key={c.key} value={c.key}>
                  {c.label}
                </option>
              ))}
            </select>
          </label>
        )}
        <PeriodQuick
          onPick={(f, t) => {
            setFrom(f);
            setTo(t);
            apply({ from: f, to: t });
          }}
        />
        <button className="btn primary" type="button" disabled={!ready} onClick={() => apply()}>
          查詢
        </button>
      </div>
      {isError && <Banner kind="error" message={errorMessageOf(error)} />}
      {exportNote && <Banner kind="error" message={exportNote} />}

      {data && (
        <>
          <div className="ex-period">
            {data.from} ~ {data.to}　完工日
          </div>
          <div className="sd-summary">
            {repairCards(data.totals).map((card) => (
              <div key={card.label} className="sd-summary-card">
                <div className="sd-summary-card-label">{card.label}</div>
                <div className="sd-summary-card-value">{card.value}</div>
              </div>
            ))}
          </div>
        </>
      )}

      {data && data.people.length > 0 && (
        <div className="report-table rm-people">
          <table className="report-grid">
            <thead>
              <tr>
                {PEOPLE_HEAD.map((h, i) => (
                  <th key={h} className={i === 0 ? undefined : "num"}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.people.map((p) => (
                <tr key={p.id ?? "none"} className="report-row">
                  <td>{p.name}</td>
                  <td className="num">{p.received}</td>
                  <td className="num">{p.repaired}</td>
                  <td className={isNegative(p.amount) ? "num report-neg" : "num"}>{money(p.amount)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className={`report-table sr-table${isFetching ? " sr-busy" : ""}`}>
        {!data && isFetching && <div className="md-empty">載入中…</div>}
        {data && rows.length === 0 && <div className="md-empty">這段期間沒有完工的維修單</div>}
        {data && rows.length > 0 && (
          <table className="report-grid">
            <thead>
              <tr>
                <th>完工日</th>
                <th>單號</th>
                <th>門市</th>
                <th>機型</th>
                <th>方式</th>
                <th>收件</th>
                <th>維修</th>
                <th className="num">實付</th>
                <th className="num">{actual ? "成本" : "業務員成本"}</th>
                <th className="num">委外</th>
                <th className="num">{actual ? "毛利" : "業務員毛利"}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="report-row">
                  <td>{r.date}</td>
                  <td>
                    <Link to={docPath(r.doc)}>{r.doc.no}</Link>
                  </td>
                  <td>{r.store}</td>
                  <td>{r.model}</td>
                  <td>{wayLabel(ways, r.way)}</td>
                  <td>{r.receiver}</td>
                  <td>{r.technician}</td>
                  <td className="num">{money(r.paid)}</td>
                  <td className="num">{money(r.parts)}</td>
                  <td className="num">{money(r.outside)}</td>
                  <td className={isNegative(r.margin) ? "num report-neg" : "num"}>{money(r.margin)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      <Pager page={page} pages={pageCount(data?.count ?? 0)} onPage={setPage} busy={isFetching} />
    </div>
  );
}
