import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { fetchSerialReportExport, useReleaseReturned, useSerialReport } from "@/api/hooks";
import { useCan } from "@/auth/AuthContext";
import { ArmButton } from "@/components/workbench/ArmButton";
import { toast } from "@/components/workbench/toast";
import { searchSuppliers } from "@/api/search";
import type { Supplier, Warehouse } from "@/api/types";
import { Banner, errorMessageOf } from "@/components/Banner";
import { ComboBox } from "@/components/ComboBox";
import { SerialHistoryModal } from "@/components/SerialHistoryModal";
import { Toolbar } from "@/components/Toolbar";
import { localDay } from "@/lib/fixedReports";
import { exportFileName, exportIfComplete } from "@/lib/reportExports";
import {
  costText,
  dayOf,
  docPath,
  pageCount,
  SERIAL_STATUS_CHOICES,
  serialFilterReady,
  serialTable,
  statusesOf,
  unitCodes,
  type SerialFilter,
} from "@/lib/stockReports";

import { downloadCsv, NOT_PICKED, Pager, StoreField, useStoreName, type Picked } from "./stockReportParts";

/**
 * 序號查詢:跨商品列每一台設備(新進的在前面)。一打開列的是在門市裡的(在庫 + 已退)。
 * 門市:還在店裡的看它在哪一家,已售出的看是哪一家賣的。點一列看那一台的完整履歷。
 * 跟庫存查詢一樣各門市都看得到(不照帳號的門市鎖)。
 */
export function SerialListPage() {
  // 今日總覽「退回待確認」帶 ?status=returned 進來:一打開就是已退的那幾台
  const [params] = useSearchParams();
  const startStatus = SERIAL_STATUS_CHOICES.some((c) => c.key === params.get("status"))
    ? (params.get("status") as string)
    : "store";
  const canRelease = useCan("release_returned");
  const release = useReleaseReturned();
  const [applied, setApplied] = useState<SerialFilter>(() => ({
    statuses: statusesOf(startStatus),
    warehouse: "",
    supplier: "",
    receivedFrom: "",
    receivedTo: "",
    soldFrom: "",
    soldTo: "",
    search: "",
  }));
  const [status, setStatus] = useState(startStatus);
  const [store, setStore] = useState<Picked<Warehouse>>(NOT_PICKED);
  const [supplier, setSupplier] = useState<Picked<Supplier>>(NOT_PICKED);
  const [receivedFrom, setReceivedFrom] = useState("");
  const [receivedTo, setReceivedTo] = useState("");
  const [soldFrom, setSoldFrom] = useState("");
  const [soldTo, setSoldTo] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [unit, setUnit] = useState<number | null>(null);
  const [exporting, setExporting] = useState(false);
  const [exportNote, setExportNote] = useState("");
  const [appliedStore, setAppliedStore] = useState<Picked<Warehouse>>(NOT_PICKED);
  const storeName = useStoreName(appliedStore, false);

  const draft: SerialFilter = {
    statuses: statusesOf(status),
    warehouse: store.id,
    supplier: supplier.id,
    receivedFrom,
    receivedTo,
    soldFrom,
    soldTo,
    search,
  };
  const ready = serialFilterReady(draft);
  const { data, isFetching, isError, error } = useSerialReport(applied, page);
  const rows = data?.results ?? [];

  function apply() {
    if (!ready) return;
    setApplied(draft);
    setAppliedStore(store);
    setPage(1);
    setExportNote("");
  }

  async function exportAll() {
    setExporting(true);
    setExportNote("");
    try {
      const all = await fetchSerialReportExport(applied);
      setExportNote(
        exportIfComplete(
          all,
          exportFileName("序號查詢", { store: storeName, day: localDay() }),
          () => serialTable(all.results),
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
    <div className="page sr-page">
      <Toolbar
        title="序號查詢"
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
          狀態
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            {SERIAL_STATUS_CHOICES.map((c) => (
              <option key={c.key} value={c.key}>
                {c.label}
              </option>
            ))}
          </select>
        </label>
        <StoreField value={store} onChange={setStore} lockable={false} />
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
        <label>
          進貨
          <input type="date" value={receivedFrom} onChange={(e) => setReceivedFrom(e.target.value)} />
          <span>~</span>
          <input type="date" value={receivedTo} onChange={(e) => setReceivedTo(e.target.value)} />
        </label>
        <label>
          賣出
          <input type="date" value={soldFrom} onChange={(e) => setSoldFrom(e.target.value)} />
          <span>~</span>
          <input type="date" value={soldTo} onChange={(e) => setSoldTo(e.target.value)} />
        </label>
        <label>
          商品
          <input
            type="text"
            value={search}
            placeholder="序號 / 品號 / 品名"
            onChange={(e) => setSearch(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.nativeEvent.isComposing) apply();
            }}
          />
        </label>
        <button className="btn primary" type="button" disabled={!ready} onClick={apply}>
          查詢
        </button>
      </div>
      {isError && <Banner kind="error" message={errorMessageOf(error)} />}
      {exportNote && <Banner kind="error" message={exportNote} />}

      {data && (
        <div className="ex-period">
          共 {data.count} 台　成本合計 ${costText(data.cost_total)}
        </div>
      )}

      <div className={`report-table sr-table${isFetching ? " sr-busy" : ""}`}>
        {!data && isFetching && <div className="md-empty">載入中…</div>}
        {data && rows.length === 0 && <div className="md-empty">沒有符合的設備</div>}
        {data && rows.length > 0 && (
          <table className="report-grid">
            <thead>
              <tr>
                <th>IMEI</th>
                <th>SN</th>
                <th>品號</th>
                <th>品名</th>
                <th>狀態</th>
                <th>門市</th>
                <th>來源</th>
                <th>進貨單</th>
                <th>進貨日</th>
                <th className="num">成本</th>
                <th>賣出單</th>
                <th>賣出日</th>
                <th>處理</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const codes = unitCodes(r);
                return (
                  <tr key={r.id} className="report-row sr-pick" onClick={() => setUnit(r.id)}>
                    <td>{codes.imei}</td>
                    <td>{codes.sn}</td>
                    <td>{r.sku}</td>
                    <td className="sr-name">{r.name}</td>
                    <td>{r.status_label}</td>
                    <td>{r.store}</td>
                    <td>{r.source?.label}</td>
                    <td onClick={(e) => e.stopPropagation()}>
                      {r.source && <Link to={docPath(r.source.doc)}>{r.source.doc.no}</Link>}
                    </td>
                    <td>{dayOf(r.received_at)}</td>
                    <td className="num">{costText(r.cost)}</td>
                    <td onClick={(e) => e.stopPropagation()}>
                      {r.sale && <Link to={docPath(r.sale.doc)}>{r.sale.doc.no}</Link>}
                    </td>
                    <td>{r.sale?.date}</td>
                    {/* 銷退退回來的「已退」:確認可以賣 → 回在庫;有瑕疵的送廠商換貨(owner 2026-10-23) */}
                    <td onClick={(e) => e.stopPropagation()} className="sr-act">
                      {r.status === "returned" && (
                        <>
                          {canRelease && (
                            <ArmButton
                              label="確認可賣"
                              armedLabel="確定可賣?"
                              className="btn"
                              disabled={release.isPending}
                              onConfirm={() =>
                                release
                                  .mutateAsync(r.id)
                                  .then(() => toast(`${r.serial_no} 回到在庫`))
                                  .catch((e) => toast(errorMessageOf(e), "err"))
                              }
                            />
                          )}
                          <Link className="btn" to={`/inventory/vendor-exchanges?code=${encodeURIComponent(r.serial_no)}`}>
                            廠商換貨
                          </Link>
                        </>
                      )}
                    </td>
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
