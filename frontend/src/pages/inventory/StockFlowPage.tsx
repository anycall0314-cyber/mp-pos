import { useState } from "react";
import { Link } from "react-router-dom";

import { useStockFlow } from "@/api/hooks";
import type { Category, Warehouse } from "@/api/types";
import { Banner, errorMessageOf } from "@/components/Banner";
import { Toolbar } from "@/components/Toolbar";
import { localDay, monthStart, rangeReady } from "@/lib/fixedReports";
import {
  flowCell,
  flowTable,
  movesOfFlowRow,
  pageCount,
  pageSlice,
  type FlowFilter,
  type FlowRow,
} from "@/lib/stockReports";

import {
  CategoryField,
  downloadCsv,
  NOT_PICKED,
  Pager,
  StoreField,
  type Picked,
} from "./stockReportParts";

/**
 * 進銷存表:一段期間每個商品的 期初、進貨、銷貨、銷退、調入、調出、領用、調整、期末(只有數量)。
 * 怎麼算在伺服器(inventory/reports.py):期末從現在的實際庫存往回推,每一列等式一定成立。
 * 一次拿全部(伺服器有上限)、畫面自己分頁;匯出的是全部,不是這一頁。點品名去異動查詢看是哪幾筆。
 */
export function StockFlowPage() {
  const [applied, setApplied] = useState<FlowFilter>(() => ({
    from: monthStart(),
    to: localDay(),
    warehouse: "",
    category: "",
    search: "",
    moved: false,
  }));
  const [from, setFrom] = useState(applied.from);
  const [to, setTo] = useState(applied.to);
  const [store, setStore] = useState<Picked<Warehouse>>(NOT_PICKED);
  const [category, setCategory] = useState<Picked<Category>>(NOT_PICKED);
  const [search, setSearch] = useState("");
  const [moved, setMoved] = useState(false);
  const [page, setPage] = useState(1);
  // 查詢當下選的門市(點品名帶去異動查詢用;畫面上的框之後可能又被改了)
  const [appliedStore, setAppliedStore] = useState<Picked<Warehouse>>(NOT_PICKED);

  const { data, isFetching, isError, error } = useStockFlow(applied);
  const ready = rangeReady({ from, to });
  const rows = data?.rows ?? [];
  const shown = pageSlice(rows, page);

  function apply() {
    if (!ready) return;
    setApplied({ from, to, warehouse: store.id, category: category.id, search, moved });
    setAppliedStore(store);
    setPage(1);
  }

  /** 點品名帶去異動查詢的條件:同一段期間、同一家門市、就是這一個商品。 */
  function movesFor(row: FlowRow) {
    return { ...movesOfFlowRow(applied, row), store: appliedStore };
  }

  return (
    <div className="page sr-page">
      <Toolbar
        title="進銷存表"
        actions={
          <button
            className="btn"
            type="button"
            disabled={!data || rows.length === 0}
            onClick={() => data && downloadCsv(`進銷存表_${data.from}_${data.to}.csv`, flowTable(data))}
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
        <CategoryField value={category} onChange={setCategory} />
        <label>
          商品
          <input
            type="text"
            value={search}
            placeholder="品號 / 品名"
            onChange={(e) => setSearch(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.nativeEvent.isComposing) apply();
            }}
          />
        </label>
        <label className="sr-check">
          <input type="checkbox" checked={moved} onChange={(e) => setMoved(e.target.checked)} />
          只看有進出
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

      {data && (
        <div className="ex-period">
          {data.from} ~ {data.to}　共 {data.row_count} 項
          {data.truncated && `　只列前 ${rows.length} 項,請把條件縮小`}
        </div>
      )}

      <div className={`report-table sr-table${isFetching ? " sr-busy" : ""}`}>
        {!data && isFetching && <div className="md-empty">載入中…</div>}
        {data && rows.length === 0 && <div className="md-empty">沒有符合的商品</div>}
        {data && rows.length > 0 && (
          <table className="report-grid">
            <thead>
              <tr>
                <th>品號</th>
                <th>品名</th>
                <th>類別</th>
                <th className="num">期初</th>
                {data.columns.map((c) => (
                  <th key={c.key} className="num">
                    {c.label}
                  </th>
                ))}
                <th className="num">期末</th>
                {data.with_transit && (
                  <th className="num" title="調撥途中,對方還沒確認">
                    在途
                  </th>
                )}
              </tr>
            </thead>
            <tbody>
              {shown.map((r) => (
                <tr key={r.product} className="report-row">
                  <td>{r.sku}</td>
                  <td className="sr-name">
                    <Link to="/inventory/movements" state={movesFor(r)}>
                      {r.name}
                    </Link>
                  </td>
                  <td>{r.category}</td>
                  <td className="num">{r.opening}</td>
                  {data.columns.map((c) => (
                    <td key={c.key} className={Number(r[c.key]) < 0 ? "num report-neg" : "num"}>
                      {flowCell(Number(r[c.key]))}
                    </td>
                  ))}
                  <td className="num sr-closing">
                    {r.returned > 0 && <span className="wb-badge warn">含已退 {r.returned}</span>}
                    {r.closing}
                  </td>
                  {data.with_transit && <td className="num">{flowCell(r.transit)}</td>}
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <td colSpan={3}>合計</td>
                <td className="num">{data.totals.opening}</td>
                {data.columns.map((c) => (
                  <td key={c.key} className="num">
                    {data.totals[c.key]}
                  </td>
                ))}
                <td className="num">{data.totals.closing}</td>
                {data.with_transit && <td className="num">{data.totals.transit}</td>}
              </tr>
            </tfoot>
          </table>
        )}
      </div>
      <Pager page={page} pages={pageCount(rows.length)} onPage={setPage} />
    </div>
  );
}
