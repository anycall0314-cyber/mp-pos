import { useState } from "react";
import { Link, useLocation } from "react-router-dom";

import { fetchStockMovesExport, useStockMoves } from "@/api/hooks";
import type { Category, Warehouse } from "@/api/types";
import { AppliedFilters } from "@/components/AppliedFilters";
import { Banner, errorMessageOf } from "@/components/Banner";
import { appliedList, cond, rangeCond } from "@/lib/appliedFilters";
import { SerialHistoryModal } from "@/components/SerialHistoryModal";
import { Toolbar } from "@/components/Toolbar";
import { localDay, monthStart, rangeReady } from "@/lib/fixedReports";
import { exportFileName, exportIfComplete } from "@/lib/reportExports";
import {
  docPath,
  effectLines,
  moveTable,
  pageCount,
  routeText,
  shortTime,
  type MoveFilter,
} from "@/lib/stockReports";

import {
  CategoryField,
  downloadCsv,
  NOT_PICKED,
  Pager,
  StoreField,
  useStoreName,
  type Picked,
} from "./stockReportParts";

/** 從進銷存表點品名帶過來的條件(放在瀏覽紀錄裡,重新整理還在)。 */
interface CarriedIn {
  filter?: MoveFilter;
  store?: Picked<Warehouse>;
  /** 指定的那一個商品(編號 + 顯示用的品號品名) */
  product?: { id: number; label: string };
}

/**
 * 異動查詢:逐筆列出庫存的每一次進出(新的在前面)。哪一筆算哪一類、動到哪家門市由伺服器決定
 * (inventory/flows.py,跟進銷存表同一份)。作廢各自一列。點單號看那張單、點序號看那一台的履歷。
 */
export function StockMovesPage() {
  const carried = (useLocation().state ?? {}) as CarriedIn;
  const [applied, setApplied] = useState<MoveFilter>(
    () =>
      carried.filter ?? {
        from: monthStart(),
        to: localDay(),
        warehouse: "",
        kind: "",
        category: "",
        search: "",
        product: "",
      },
  );
  // 從進銷存表帶過來的那一個商品:鎖在那一個上(不是用品號去找),按 × 才放掉、改回用打字找
  const [only, setOnly] = useState(carried.product ?? null);
  const [from, setFrom] = useState(applied.from);
  const [to, setTo] = useState(applied.to);
  const [store, setStore] = useState<Picked<Warehouse>>(carried.store ?? NOT_PICKED);
  const [kind, setKind] = useState(applied.kind);
  const [category, setCategory] = useState<Picked<Category>>(NOT_PICKED);
  const [search, setSearch] = useState(applied.search);
  const [page, setPage] = useState(1);
  const [unit, setUnit] = useState<number | null>(null);
  const [exporting, setExporting] = useState(false);
  const [exportNote, setExportNote] = useState("");
  // 查詢當下選的門市(檔名用;畫面上的框之後可能又被改了)
  const [appliedStore, setAppliedStore] = useState<Picked<Warehouse>>(carried.store ?? NOT_PICKED);
  const [appliedCategory, setAppliedCategory] = useState<Picked<Category>>(NOT_PICKED);
  const [appliedOnly, setAppliedOnly] = useState(carried.product ?? null);
  const storeName = useStoreName(appliedStore);

  const { data, isFetching, isError, error } = useStockMoves(applied, page);
  const ready = rangeReady({ from, to });
  const rows = data?.results ?? [];

  function apply() {
    if (!ready) return;
    setApplied({
      from, to, warehouse: store.id, kind, category: category.id,
      search: only ? "" : search, product: only ? only.id : "",
    });
    setAppliedStore(store);
    setAppliedCategory(category);
    setAppliedOnly(only);
    setPage(1);
    setExportNote("");
  }

  // 已套用的條件(查的那一份;預設 = 本月、全部)
  const appliedItems = appliedList([
    rangeCond("期間", applied.from, applied.to, { from: monthStart(), to: localDay() }),
    applied.warehouse !== "" && cond("門市", storeName),
    cond("異動", applied.kind && ((data?.kinds ?? []).find((k) => k.key === applied.kind)?.label ?? applied.kind)),
    applied.category !== "" && cond("類別", appliedCategory.option?.label),
    cond("商品", appliedOnly ? appliedOnly.label : applied.search),
  ]);

  function clearAll() {
    const fresh: MoveFilter = { from: monthStart(), to: localDay(), warehouse: "", kind: "", category: "", search: "", product: "" };
    setFrom(fresh.from);
    setTo(fresh.to);
    setStore(NOT_PICKED);
    setKind("");
    setCategory(NOT_PICKED);
    setSearch("");
    setOnly(null);
    setApplied(fresh);
    setAppliedStore(NOT_PICKED);
    setAppliedCategory(NOT_PICKED);
    setAppliedOnly(null);
    setPage(1);
    setExportNote("");
  }

  async function exportAll() {
    setExporting(true);
    setExportNote("");
    try {
      const all = await fetchStockMovesExport(applied);
      setExportNote(
        exportIfComplete(all, exportFileName("異動查詢", { store: storeName, from: applied.from, to: applied.to }), () => moveTable(all.results), downloadCsv),
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
        title="異動查詢"
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
          異動
          <select value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="">全部異動</option>
            {(data?.kinds ?? []).map((k) => (
              <option key={k.key} value={k.key}>
                {k.label}
              </option>
            ))}
          </select>
        </label>
        <CategoryField value={category} onChange={setCategory} />
        <label>
          商品
          {only ? (
            <span className="sr-only-one">
              {only.label}
              <button type="button" aria-label="不指定商品" onClick={() => setOnly(null)}>
                ×
              </button>
            </span>
          ) : (
            <input
              type="text"
              value={search}
              placeholder="品號 / 品名 / 序號"
              onChange={(e) => setSearch(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.nativeEvent.isComposing) apply();
              }}
            />
          )}
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
      <AppliedFilters items={appliedItems} onClear={clearAll} />
      {isError && <Banner kind="error" message={errorMessageOf(error)} />}
      {exportNote && <Banner kind="error" message={exportNote} />}

      {data && (
        <div className="ex-period">
          {data.from} ~ {data.to}　共 {data.count} 筆
        </div>
      )}

      <div className={`report-table sr-table${isFetching ? " sr-busy" : ""}`}>
        {!data && isFetching && <div className="md-empty">載入中…</div>}
        {data && rows.length === 0 && <div className="md-empty">這段期間沒有異動</div>}
        {data && rows.length > 0 && (
          <table className="report-grid">
            <thead>
              <tr>
                <th>時間</th>
                <th>異動</th>
                <th>品號</th>
                <th>品名</th>
                <th>序號</th>
                <th>門市</th>
                <th className="num">增減</th>
                <th>單號</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const lines = effectLines(r);
                const route = routeText(r);
                return (
                  <tr key={r.id} className="report-row">
                    <td>{shortTime(r.created_at)}</td>
                    <td>
                      {r.kind_label}
                      {r.note && <div className="sr-dim">{r.note}</div>}
                    </td>
                    <td>{r.sku}</td>
                    <td className="sr-name">{r.name}</td>
                    <td>
                      {r.serial !== null && (
                        <button className="sr-link" type="button" onClick={() => setUnit(r.serial)}>
                          {r.serial_no}
                        </button>
                      )}
                    </td>
                    <td>
                      {lines.map((l, i) => (
                        <div key={i}>{l.name}</div>
                      ))}
                      {route && <div className="sr-dim">{route}</div>}
                    </td>
                    <td className="num">
                      {lines.length === 0 && "0"}
                      {lines.map((l, i) => (
                        <div key={i} className={l.delta < 0 ? "report-neg-text" : undefined}>
                          {l.text}
                        </div>
                      ))}
                    </td>
                    <td>{r.doc && <Link to={docPath(r.doc)}>{r.doc.no}</Link>}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
      <Pager page={page} pages={pageCount(data?.count ?? 0)} onPage={setPage} busy={isFetching} />
      {unit !== null && <SerialHistoryModal serialId={unit} onClose={() => setUnit(null)} />}
    </div>
  );
}
