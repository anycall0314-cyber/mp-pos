import { useState } from "react";
import { Link } from "react-router-dom";

import { fetchPurchaseLinesExport, usePurchaseLines } from "@/api/hooks";
import { searchSuppliers } from "@/api/search";
import type { Category, Supplier, Warehouse } from "@/api/types";
import { Banner, errorMessageOf } from "@/components/Banner";
import { ComboBox } from "@/components/ComboBox";
import { Toolbar } from "@/components/Toolbar";
import { localDay, monthStart, rangeReady } from "@/lib/fixedReports";
import { money } from "@/lib/money";
import { purchaseLineTable, qtyText, type PurchaseLineFilter } from "@/lib/purchaseLines";
import { exportFileName, exportIfComplete } from "@/lib/reportExports";
import { docPath, pageCount } from "@/lib/stockReports";
import {
  CategoryField,
  downloadCsv,
  NOT_PICKED,
  Pager,
  StoreField,
  useStoreName,
  type Picked,
} from "@/pages/inventory/stockReportParts";

/**
 * 進貨明細:進貨單的每一行一列(新的在前面)。不列作廢的進貨單。
 * 成本 = 記進庫存的未稅成本;單價、金額是單上打的。合計是照條件全部的,不是只有這一頁。
 * 鎖在門市的帳號只看自己門市(伺服器決定)。
 */
export function PurchaseLinesPage() {
  const [applied, setApplied] = useState<PurchaseLineFilter>(() => ({
    from: monthStart(),
    to: localDay(),
    warehouse: "",
    supplier: "",
    category: "",
    search: "",
  }));
  const [from, setFrom] = useState(applied.from);
  const [to, setTo] = useState(applied.to);
  const [store, setStore] = useState<Picked<Warehouse>>(NOT_PICKED);
  const [supplier, setSupplier] = useState<Picked<Supplier>>(NOT_PICKED);
  const [category, setCategory] = useState<Picked<Category>>(NOT_PICKED);
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [exporting, setExporting] = useState(false);
  const [exportNote, setExportNote] = useState("");
  const [appliedStore, setAppliedStore] = useState<Picked<Warehouse>>(NOT_PICKED);
  const storeName = useStoreName(appliedStore);

  const { data, isFetching, isError, error } = usePurchaseLines(applied, page);
  const ready = rangeReady({ from, to });
  const rows = data?.results ?? [];

  function apply() {
    if (!ready) return;
    setApplied({ from, to, warehouse: store.id, supplier: supplier.id, category: category.id, search });
    setAppliedStore(store);
    setPage(1);
    setExportNote("");
  }

  async function exportAll() {
    setExporting(true);
    setExportNote("");
    try {
      const all = await fetchPurchaseLinesExport(applied);
      setExportNote(
        exportIfComplete(all, exportFileName("進貨明細", { store: storeName, from: applied.from, to: applied.to }), () => purchaseLineTable(all.results), downloadCsv),
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
        title="進貨明細"
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
        <label>
          廠商
          <ComboBox<Supplier>
            value={supplier.id}
            selectedOption={supplier.option}
            onChange={(id, opt) => setSupplier({ id, option: opt ?? null })}
            fetchOptions={searchSuppliers}
            placeholder="全部"
          />
        </label>
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
        <div className="ex-period">
          {data.from} ~ {data.to}　共 {data.count} 行
        </div>
      )}

      <div className={`report-table sr-table${isFetching ? " sr-busy" : ""}`}>
        {!data && isFetching && <div className="md-empty">載入中…</div>}
        {data && rows.length === 0 && <div className="md-empty">這段期間沒有進貨</div>}
        {data && rows.length > 0 && (
          <table className="report-grid">
            <thead>
              <tr>
                <th>日期</th>
                <th>單號</th>
                <th>門市</th>
                <th>廠商</th>
                <th>品號</th>
                <th>品名</th>
                <th className="num">數量</th>
                <th className="num">單價</th>
                <th className="num">金額</th>
                <th className="num" title="記進庫存的未稅成本(含分攤的運費)">
                  成本
                </th>
                <th>備註</th>
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
                  <td>{r.supplier}</td>
                  <td>{r.sku}</td>
                  <td>{r.name}</td>
                  <td className="num">{qtyText(r)}</td>
                  <td className="num">{money(r.unit_price)}</td>
                  <td className="num">{money(r.amount)}</td>
                  <td className="num">{money(r.cost)}</td>
                  <td className="sr-dim">{r.note}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <td colSpan={6}>合計</td>
                <td className="num">{data.totals.qty}</td>
                <td />
                <td className="num">{money(data.totals.amount)}</td>
                <td className="num">{money(data.totals.cost)}</td>
                <td />
              </tr>
            </tfoot>
          </table>
        )}
      </div>
      <Pager page={page} pages={pageCount(data?.count ?? 0)} onPage={setPage} busy={isFetching} />
    </div>
  );
}
