import { useEffect, useMemo, useState } from "react";

import {
  StockMatrixProduct,
  useInStockSerials,
  usePendingTransfers,
  useStockMatrix,
  useWarehouses,
} from "@/api/hooks";
import { searchCategories } from "@/api/search";
import type { Category } from "@/api/types";
import { ComboBox, ComboOption } from "@/components/ComboBox";
import { SerialHistoryModal } from "@/components/SerialHistoryModal";
import { Toolbar } from "@/components/Toolbar";

interface SerialListModalProps {
  product: StockMatrixProduct;
  warehouseId: number;
  warehouseLabel: string;
  onClose: () => void;
}

function SerialListModal({
  product,
  warehouseId,
  warehouseLabel,
  onClose,
}: SerialListModalProps) {
  const serials = useInStockSerials(product.id, warehouseId);
  const rows = serials.data ?? [];
  const [historyId, setHistoryId] = useState<number | null>(null);

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div
        className="modal-card serial-list-modal"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        <div className="modal-title">
          {product.name} · {warehouseLabel}
        </div>
        <div className="modal-body">
          {serials.isLoading && <div className="md-empty">…</div>}
          {!serials.isLoading && (
            <table className="line-table">
              <thead>
                <tr>
                  <th style={{ width: 40 }}>#</th>
                  <th>序號</th>
                  <th>進貨日</th>
                  <th className="num">單台成本</th>
                  {product.is_secondhand && <th>成色</th>}
                  {product.is_secondhand && (
                    <th className="num">自定售價</th>
                  )}
                  {product.is_secondhand && (
                    <th className="num">電池 %</th>
                  )}
                  {product.is_secondhand && <th>備註</th>}
                  <th style={{ width: 60 }}></th>
                </tr>
              </thead>
              <tbody>
                {rows.map((s, i) => (
                  <tr key={s.id}>
                    <td>{i + 1}</td>
                    <td>{s.serial_no}</td>
                    <td>{s.received_at?.slice(0, 10) ?? "—"}</td>
                    <td className="num">
                      {Math.round(Number(s.purchase_unit_cost)).toLocaleString()}
                    </td>
                    {product.is_secondhand && (
                      <td>{s.condition_grade || "—"}</td>
                    )}
                    {product.is_secondhand && (
                      <td className="num">
                        {s.custom_unit_price
                          ? Math.round(
                              Number(s.custom_unit_price),
                            ).toLocaleString()
                          : "—"}
                      </td>
                    )}
                    {product.is_secondhand && (
                      <td className="num">{s.battery_health ?? "—"}</td>
                    )}
                    {product.is_secondhand && (
                      <td>{s.condition_note || "—"}</td>
                    )}
                    <td>
                      <button
                        type="button"
                        className="btn"
                        style={{ fontSize: 12, padding: "2px 6px" }}
                        onClick={() => setHistoryId(s.id)}
                      >
                        履歷
                      </button>
                    </td>
                  </tr>
                ))}
                {rows.length === 0 && (
                  <tr>
                    <td
                      colSpan={product.is_secondhand ? 9 : 5}
                      className="md-empty"
                    >
                      —
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          )}
        </div>
        <div className="modal-actions">
          <button className="btn primary" type="button" onClick={onClose}>
            關閉
          </button>
        </div>
      </div>
      {historyId != null && (
        <SerialHistoryModal
          serialId={historyId}
          onClose={() => setHistoryId(null)}
        />
      )}
    </div>
  );
}

// 配件:沒有序號履歷,改顯示「與本倉相關、已派發未確認」的調撥狀態
function TransferStatusModal({
  product,
  warehouseId,
  warehouseLabel,
  onClose,
}: SerialListModalProps) {
  const pending = usePendingTransfers(product.id, warehouseId);
  const rows = pending.data ?? [];

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div
        className="modal-card serial-list-modal"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        <div className="modal-title">
          {product.name} · {warehouseLabel}
        </div>
        <div className="modal-body">
          <div
            style={{
              fontSize: 13,
              color: "var(--text-dim)",
              marginBottom: 8,
            }}
          >
            配件無序號履歷;以下為與本倉相關、已派發但尚未確認的調撥。
          </div>
          {pending.isLoading && <div className="md-empty">…</div>}
          {!pending.isLoading && (
            <table className="line-table">
              <thead>
                <tr>
                  <th style={{ width: 40 }}>#</th>
                  <th>單號</th>
                  <th>方向</th>
                  <th>對方倉</th>
                  <th>單據日期</th>
                  <th className="num">數量</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((t, i) => {
                  const counterpart =
                    t.direction === "out" ? t.to_warehouse : t.from_warehouse;
                  return (
                    <tr key={`${t.transfer_no}-${i}`}>
                      <td>{i + 1}</td>
                      <td>{t.transfer_no}</td>
                      <td>
                        {t.direction === "out"
                          ? "調出本倉"
                          : t.direction === "in"
                            ? "調入本倉"
                            : "—"}
                      </td>
                      <td>
                        {counterpart.code} {counterpart.name}
                      </td>
                      <td>{t.doc_date}</td>
                      <td className="num">{t.qty}</td>
                    </tr>
                  );
                })}
                {rows.length === 0 && (
                  <tr>
                    <td colSpan={6} className="md-empty">
                      目前沒有調撥中(未確認)的單據
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          )}
        </div>
        <div className="modal-actions">
          <button className="btn primary" type="button" onClick={onClose}>
            關閉
          </button>
        </div>
      </div>
    </div>
  );
}

interface AppliedFilter {
  keyword: string;
  categoryIds: number[];
  warehouseIds: number[];
}

type SortKey =
  | { kind: "category" }
  | { kind: "name" }
  | { kind: "total" }
  | { kind: "warehouse"; warehouseId: number };

interface SortState {
  by: SortKey;
  dir: "asc" | "desc";
}

function sortKeyEquals(a: SortKey, b: SortKey): boolean {
  if (a.kind !== b.kind) return false;
  if (a.kind === "warehouse" && b.kind === "warehouse") {
    return a.warehouseId === b.warehouseId;
  }
  return true;
}

export function InventoryQueryPage() {
  // 表單狀態(未送出)
  const [keyword, setKeyword] = useState("");
  // 類別多選:chip 集合;categoryPicker 是 ComboBox 暫存,選後加入 chip 並清空
  const [selectedCategories, setSelectedCategories] = useState<
    { id: number; label: string }[]
  >([]);
  const [categoryPicker, setCategoryPicker] = useState<number | "">("");
  const [categoryPickerOption, setCategoryPickerOption] =
    useState<ComboOption<Category> | null>(null);

  // 倉別多選
  const warehousesQuery = useWarehouses();
  const allWarehouses = warehousesQuery.data ?? [];
  const [selectedWarehouseIds, setSelectedWarehouseIds] = useState<
    Set<number>
  >(new Set());

  // 首次載入時把所有倉預設勾起來
  useEffect(() => {
    if (allWarehouses.length > 0 && selectedWarehouseIds.size === 0) {
      setSelectedWarehouseIds(new Set(allWarehouses.map((w) => w.id)));
    }
  }, [allWarehouses]);

  // 已套用篩選(按查詢才會更新,跟著觸發 API)
  const [applied, setApplied] = useState<AppliedFilter | null>(null);

  // 點數字打開的明細
  const [serialDialog, setSerialDialog] = useState<{
    product: StockMatrixProduct;
    warehouseId: number;
    warehouseLabel: string;
  } | null>(null);

  const matrix = useStockMatrix(
    {
      warehouseIds: applied?.warehouseIds ?? [],
      search: applied?.keyword,
      categoryIds: applied?.categoryIds,
      inStockOnly: true,
    },
    { enabled: !!applied && (applied.warehouseIds.length > 0) },
  );

  const warehouses = matrix.data?.warehouses ?? [];
  const rawProducts = matrix.data?.products ?? [];

  // 排序狀態(null = 用 API 預設順序)
  const [sort, setSort] = useState<SortState | null>(null);

  // 套用排序
  const products = useMemo(() => {
    if (!sort) return rawProducts;
    const arr = [...rawProducts];
    arr.sort((a, b) => {
      let av: string | number;
      let bv: string | number;
      switch (sort.by.kind) {
        case "category":
          av = a.category_name;
          bv = b.category_name;
          break;
        case "name":
          av = a.name;
          bv = b.name;
          break;
        case "total":
          av = a.stock_total;
          bv = b.stock_total;
          break;
        case "warehouse":
          av = a.stock_by_warehouse[String(sort.by.warehouseId)] ?? 0;
          bv = b.stock_by_warehouse[String(sort.by.warehouseId)] ?? 0;
          break;
      }
      let cmp = 0;
      if (typeof av === "string" && typeof bv === "string") {
        // localeCompare 對中文 / 英文混合排序最穩
        cmp = av.localeCompare(bv, "zh-Hant");
      } else {
        cmp = (av as number) - (bv as number);
      }
      return sort.dir === "asc" ? cmp : -cmp;
    });
    return arr;
  }, [rawProducts, sort]);

  // 點欄位標題:第一次升冪、再點變降冪、第三次回預設
  function toggleSort(key: SortKey) {
    setSort((prev) => {
      if (!prev || !sortKeyEquals(prev.by, key)) {
        return { by: key, dir: "asc" };
      }
      if (prev.dir === "asc") return { by: key, dir: "desc" };
      return null;
    });
  }

  function sortIndicator(key: SortKey): string {
    if (!sort || !sortKeyEquals(sort.by, key)) return "";
    return sort.dir === "asc" ? " ▲" : " ▼";
  }

  const totalsByWarehouse = useMemo(() => {
    const m: Record<string, number> = {};
    for (const w of warehouses) m[String(w.id)] = 0;
    for (const p of products) {
      for (const [wid, qty] of Object.entries(p.stock_by_warehouse)) {
        m[wid] = (m[wid] ?? 0) + qty;
      }
    }
    return m;
  }, [warehouses, products]);
  const grandTotal = products.reduce((s, p) => s + p.stock_total, 0);

  function runQuery() {
    setApplied({
      keyword: keyword.trim(),
      categoryIds: selectedCategories.map((c) => c.id),
      warehouseIds: Array.from(selectedWarehouseIds),
    });
  }

  function resetFilters() {
    setKeyword("");
    setSelectedCategories([]);
    setCategoryPicker("");
    setCategoryPickerOption(null);
    setSelectedWarehouseIds(new Set(allWarehouses.map((w) => w.id)));
    setApplied(null);
  }

  function addCategory(opt: ComboOption<Category>) {
    setSelectedCategories((prev) =>
      prev.some((c) => c.id === opt.id)
        ? prev
        : [...prev, { id: opt.id as number, label: opt.label }],
    );
    setCategoryPicker("");
    setCategoryPickerOption(null);
  }

  function removeCategory(id: number) {
    setSelectedCategories((prev) => prev.filter((c) => c.id !== id));
  }

  function toggleWarehouse(wid: number) {
    setSelectedWarehouseIds((prev) => {
      const next = new Set(prev);
      if (next.has(wid)) next.delete(wid);
      else next.add(wid);
      return next;
    });
  }

  function setAllWarehouses(checked: boolean) {
    if (checked) {
      setSelectedWarehouseIds(new Set(allWarehouses.map((w) => w.id)));
    } else {
      setSelectedWarehouseIds(new Set());
    }
  }

  return (
    <div className="page">
      <Toolbar title="庫存查詢" />

      <div className="list-filterbar inventory-filterbar">
        <label style={{ minWidth: 220 }}>
          關鍵字
          <input
            type="text"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                runQuery();
              }
            }}
            placeholder="品名 / 品號 / IMEI"
            style={{ minWidth: 180 }}
          />
        </label>
        <label style={{ minWidth: 260 }}>
          類別 (可多選)
          <div style={{ minWidth: 200 }}>
            <ComboBox<Category>
              value={categoryPicker}
              selectedOption={categoryPickerOption}
              onChange={(_id, opt) => {
                if (opt) addCategory(opt);
              }}
              fetchOptions={searchCategories}
              placeholder={
                selectedCategories.length === 0 ? "全部" : "繼續加類別…"
              }
            />
            {selectedCategories.length > 0 && (
              <div
                style={{
                  display: "flex",
                  flexWrap: "wrap",
                  gap: 4,
                  marginTop: 4,
                }}
              >
                {selectedCategories.map((c) => (
                  <span
                    key={c.id}
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 4,
                      padding: "2px 6px",
                      background: "var(--panel-2)",
                      border: "1px solid var(--border)",
                      borderRadius: 3,
                      fontSize: 13,
                    }}
                  >
                    {c.label}
                    <button
                      type="button"
                      onClick={() => removeCategory(c.id)}
                      style={{
                        background: "transparent",
                        border: 0,
                        color: "var(--text-dim)",
                        cursor: "pointer",
                        padding: 0,
                        fontSize: 14,
                        lineHeight: 1,
                      }}
                      title="移除"
                    >
                      ×
                    </button>
                  </span>
                ))}
              </div>
            )}
          </div>
        </label>

        <button
          type="button"
          className="btn primary"
          onClick={runQuery}
          disabled={selectedWarehouseIds.size === 0}
        >
          查詢
        </button>
        <button type="button" className="btn" onClick={resetFilters}>
          清除
        </button>
        <span className="list-filterbar-count">
          {applied && !matrix.isLoading
            ? `${products.length} 項 · 總庫存 ${grandTotal} 件`
            : ""}
        </span>
      </div>

      {/* 倉別勾選列 */}
      <div className="warehouse-picker">
        <div className="warehouse-picker-label">倉別</div>
        <label className="warehouse-picker-item">
          <input
            type="checkbox"
            checked={
              allWarehouses.length > 0 &&
              selectedWarehouseIds.size === allWarehouses.length
            }
            onChange={(e) => setAllWarehouses(e.target.checked)}
          />
          <strong>全選</strong>
        </label>
        {allWarehouses.map((w) => (
          <label key={w.id} className="warehouse-picker-item">
            <input
              type="checkbox"
              checked={selectedWarehouseIds.has(w.id)}
              onChange={() => toggleWarehouse(w.id)}
            />
            {w.code} {w.name}
          </label>
        ))}
        {selectedWarehouseIds.size === 0 && (
          <span className="warehouse-picker-hint">至少勾選一個倉</span>
        )}
      </div>

      <div className="md-table" style={{ height: "calc(100% - 130px)" }}>
        {!applied && (
          <div className="md-empty">
            設定篩選條件後,點上方「查詢」開始
          </div>
        )}
        {applied && matrix.isLoading && (
          <div className="md-empty">查詢中…</div>
        )}
        {applied && matrix.isError && (
          <div className="md-empty">{String(matrix.error)}</div>
        )}
        {serialDialog &&
          (serialDialog.product.requires_serial ? (
            <SerialListModal
              product={serialDialog.product}
              warehouseId={serialDialog.warehouseId}
              warehouseLabel={serialDialog.warehouseLabel}
              onClose={() => setSerialDialog(null)}
            />
          ) : (
            <TransferStatusModal
              product={serialDialog.product}
              warehouseId={serialDialog.warehouseId}
              warehouseLabel={serialDialog.warehouseLabel}
              onClose={() => setSerialDialog(null)}
            />
          ))}
        {applied && !matrix.isLoading && !matrix.isError && (
          <table className="stock-matrix-table">
            <thead>
              <tr>
                <th style={{ width: 50 }} className="num">
                  序
                </th>
                <th
                  style={{ width: 110 }}
                  className="sortable"
                  onClick={() => toggleSort({ kind: "category" })}
                >
                  類別{sortIndicator({ kind: "category" })}
                </th>
                <th
                  className="sortable"
                  onClick={() => toggleSort({ kind: "name" })}
                >
                  品名{sortIndicator({ kind: "name" })}
                </th>
                <th style={{ width: 150 }}>規格</th>
                {warehouses.map((w) => (
                  <th
                    key={w.id}
                    className="num sortable"
                    onClick={() =>
                      toggleSort({ kind: "warehouse", warehouseId: w.id })
                    }
                  >
                    {w.code}
                    {sortIndicator({ kind: "warehouse", warehouseId: w.id })}
                    <div className="warehouse-col-name">{w.name}</div>
                  </th>
                ))}
                <th
                  className="num sortable"
                  onClick={() => toggleSort({ kind: "total" })}
                >
                  小計{sortIndicator({ kind: "total" })}
                </th>
                <th className="num" style={{ width: 90 }}>
                  平均成本
                </th>
              </tr>
            </thead>
            <tbody>
              {products.map((p, i) => (
                <tr key={p.id}>
                  <td className="num">{i + 1}</td>
                  <td>{p.category_name}</td>
                  <td>{p.name}</td>
                  <td style={{ color: "var(--text-dim)" }}>{p.spec || "—"}</td>
                  {warehouses.map((w) => {
                    const qty = p.stock_by_warehouse[String(w.id)] ?? 0;
                    return (
                      <td key={w.id} className="num">
                        {qty > 0 ? (
                          <button
                            type="button"
                            className="stock-link"
                            onClick={() =>
                              setSerialDialog({
                                product: p,
                                warehouseId: w.id,
                                warehouseLabel: `${w.code} ${w.name}`,
                              })
                            }
                          >
                            {qty}
                          </button>
                        ) : (
                          <span style={{ color: "var(--text-dim)" }}>0</span>
                        )}
                      </td>
                    );
                  })}
                  <td className="num" style={{ fontWeight: 600 }}>
                    {p.stock_total}
                  </td>
                  <td className="num">
                    {Number(p.weighted_avg_cost) > 0
                      ? Math.round(
                          Number(p.weighted_avg_cost),
                        ).toLocaleString()
                      : "—"}
                  </td>
                </tr>
              ))}
              {products.length === 0 && (
                <tr>
                  <td
                    colSpan={6 + warehouses.length}
                    className="md-empty"
                  >
                    查無資料
                  </td>
                </tr>
              )}
              {products.length > 0 && (
                <tr className="stock-matrix-total-row">
                  <td colSpan={4} style={{ textAlign: "right" }}>
                    各倉合計
                  </td>
                  {warehouses.map((w) => (
                    <td key={w.id} className="num">
                      {totalsByWarehouse[String(w.id)] ?? 0}
                    </td>
                  ))}
                  <td className="num">{grandTotal}</td>
                  <td className="num">
                    {grandTotal > 0
                      ? Math.round(
                          products.reduce(
                            (s, p) =>
                              s + Number(p.weighted_avg_cost || 0) * p.stock_total,
                            0,
                          ) / grandTotal,
                        ).toLocaleString()
                      : "—"}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
