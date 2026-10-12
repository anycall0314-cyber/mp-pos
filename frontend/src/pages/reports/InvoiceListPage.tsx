import { useState } from "react";
import { Link } from "react-router-dom";

import { fetchInvoiceListExport, useInvoiceList, useInvoiceTypes } from "@/api/hooks";
import type { Warehouse } from "@/api/types";
import { Banner, errorMessageOf } from "@/components/Banner";
import { Toolbar } from "@/components/Toolbar";
import { localDay, monthStart, rangeReady } from "@/lib/fixedReports";
import {
  choiceLabel,
  invoiceTable,
  returnedText,
  summaryCards,
  type InvoiceFilter,
} from "@/lib/invoiceList";
import { money } from "@/lib/money";
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

/**
 * 發票明細:有發票號碼的銷貨單一張一列(照號碼排)。作廢、待查的照樣列。
 * 合計的金額只算正常那幾張的發票面額(沒有扣銷退);銷退、作廢、待查各自一格。
 * 列哪幾張、狀態、合計、下拉的選項都由伺服器決定;鎖在門市的帳號只看自己門市。
 */
export function InvoiceListPage() {
  const [applied, setApplied] = useState<InvoiceFilter>(() => ({
    from: monthStart(),
    to: localDay(),
    by: "",
    warehouse: "",
    form: "",
    state: "",
    search: "",
  }));
  const [from, setFrom] = useState(applied.from);
  const [to, setTo] = useState(applied.to);
  const [by, setBy] = useState("");
  const [store, setStore] = useState<Picked<Warehouse>>(NOT_PICKED);
  const [form, setForm] = useState("");
  const [state, setState] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [exporting, setExporting] = useState(false);
  const [exportNote, setExportNote] = useState("");
  const [appliedStore, setAppliedStore] = useState<Picked<Warehouse>>(NOT_PICKED);
  const storeName = useStoreName(appliedStore);

  const { data, isFetching, isError, error } = useInvoiceList(applied, page);
  const types = useInvoiceTypes();
  const ready = rangeReady({ from, to });
  const rows = data?.results ?? [];
  const choices = data?.choices;

  function apply() {
    if (!ready) return;
    setApplied({ from, to, by, warehouse: store.id, form, state, search });
    setAppliedStore(store);
    setPage(1);
    setExportNote("");
  }

  async function exportAll() {
    setExporting(true);
    setExportNote("");
    try {
      const all = await fetchInvoiceListExport(applied);
      setExportNote(
        exportIfComplete(all, exportFileName("發票明細", { store: storeName, from: applied.from, to: applied.to }), () => invoiceTable(all.results, all.choices.state), downloadCsv),
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
        title="發票明細"
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
        {choices?.by && (
          <label>
            日期
            <select value={by || data?.by || ""} onChange={(e) => setBy(e.target.value)}>
              {choices.by.map((c) => (
                <option key={c.key} value={c.key}>
                  {c.label}
                </option>
              ))}
            </select>
          </label>
        )}
        <label>
          起日
          <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
        </label>
        <label>
          迄日
          <input type="date" value={to} onChange={(e) => setTo(e.target.value)} />
        </label>
        <StoreField value={store} onChange={setStore} />
        <label>
          類型
          <select value={form} onChange={(e) => setForm(e.target.value)}>
            <option value="">全部</option>
            {(types.data ?? [])
              .filter((t) => t.code !== "none")
              .map((t) => (
                <option key={t.code} value={t.code}>
                  {t.name}
                </option>
              ))}
          </select>
        </label>
        {choices?.state && (
          <label>
            狀態
            <select value={state} onChange={(e) => setState(e.target.value)}>
              <option value="">全部</option>
              {choices.state.map((c) => (
                <option key={c.key} value={c.key}>
                  {c.label}
                </option>
              ))}
            </select>
          </label>
        )}
        <label>
          搜尋
          <input
            type="text"
            value={search}
            placeholder="發票 / 統編 / 單號"
            onChange={(e) => setSearch(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.nativeEvent.isComposing) apply();
            }}
          />
        </label>
        <button
          className="btn"
          type="button"
          onClick={() => {
            setFrom(monthStart());
            setTo(localDay());
          }}
        >
          本月
        </button>
        <button className="btn primary" type="button" disabled={!ready} onClick={apply}>
          查詢
        </button>
      </div>
      {isError && <Banner kind="error" message={errorMessageOf(error)} />}
      {exportNote && <Banner kind="error" message={exportNote} />}

      {data && (
        <>
          <div className="ex-period">
            {data.from} ~ {data.to}　{choiceLabel(choices?.by, data.by)}　共 {data.count} 張
          </div>
          <div className="sd-summary">
            {summaryCards(data.totals, choices?.state).map((card) => (
              <div key={card.label} className="sd-summary-card">
                <div className="sd-summary-card-label">{card.label}</div>
                <div className="sd-summary-card-value">{card.value}</div>
              </div>
            ))}
          </div>
        </>
      )}

      <div className={`report-table sr-table${isFetching ? " sr-busy" : ""}`}>
        {!data && isFetching && <div className="md-empty">載入中…</div>}
        {data && rows.length === 0 && <div className="md-empty">這段期間沒有發票</div>}
        {data && rows.length > 0 && (
          <table className="report-grid">
            <thead>
              <tr>
                <th>發票日期</th>
                <th>發票號碼</th>
                <th>類型</th>
                <th>統編</th>
                <th>單號</th>
                <th>門市</th>
                <th>客戶</th>
                <th>課稅別</th>
                <th className="num">未稅</th>
                <th className="num">稅額</th>
                <th className="num">含稅</th>
                <th>狀態</th>
                <th className="num">銷退</th>
                <th>銷退日</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className={`report-row inv-${r.state}`}>
                  <td>{r.date}</td>
                  <td>{r.invoice_no}</td>
                  <td>{r.form}</td>
                  <td>{r.buyer_tax_id}</td>
                  <td>
                    <Link to={docPath(r.doc)}>{r.doc.no}</Link>
                  </td>
                  <td>{r.store}</td>
                  <td>{r.customer}</td>
                  <td>{r.tax_method}</td>
                  <td className="num">{money(r.subtotal)}</td>
                  <td className="num">{money(r.tax)}</td>
                  <td className="num">{money(r.total)}</td>
                  <td className="inv-state">{choiceLabel(choices?.state, r.state)}</td>
                  <td className="num">{returnedText(r)}</td>
                  <td>{r.return_date ?? ""}</td>
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
