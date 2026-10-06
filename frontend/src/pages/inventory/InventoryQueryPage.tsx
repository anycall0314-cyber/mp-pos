import { Fragment, useEffect, useMemo, useState } from "react";

import { Link } from "react-router-dom";

import {
  StockMatrixProduct,
  StockMatrixWarehouse,
  useCategories,
  useDevicesByCode,
  useHomeSummary,
  useInStockSerials,
  usePendingTransfers,
  useStockMatrix,
  useWarehouses,
} from "@/api/hooks";
import { searchCategories } from "@/api/search";
import type { Category } from "@/api/types";
import { ComboBox, ComboOption } from "@/components/ComboBox";
import { CompatibilityModal } from "@/components/CompatibilityModal";
import { AccessoryLabelButton } from "@/components/labels/AccessoryLabelButton";
import { openLabelPrint } from "@/components/labels/openLabelPrint";
import { PhotoName, usePhotoPeek } from "@/components/photos/PhotoName";
import { SerialHistoryModal } from "@/components/SerialHistoryModal";
import { useIsMobile } from "@/hooks/useIsMobile";
import { codesLabel } from "@/lib/deviceCodes";
import { money, roundInt } from "@/lib/money";

/**
 * 庫存查詢(工作台版型)。
 *
 * 上面一排:搜尋框(Enter 就查)、分店、類別、常用類別;下面是每家分店一欄的庫存表。
 * 點一列就地展開:序號商品列出每家分店在庫的每一台(IMEI / SN / 成本 / 機況),
 * 配件列出還在調撥路上的單。不開彈出視窗。
 */

// 一頁幾筆。過濾在 DB 端做完才分頁,配合下面的上一頁 / 下一頁翻到底。
const MATRIX_PAGE_SIZE = 200;
const K_PINS = "mp_pos_inv_cat_pins";

interface CatRef {
  id: number;
  label: string;
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

/** 品況顯示:有掛品況主檔就用它,舊資料退回中古機旗標。 */
function conditionLabel(p: StockMatrixProduct): string {
  if (p.condition_name) return p.condition_name;
  return p.is_secondhand ? "中古機" : "";
}

/** 價格欄:沒有價格(0 或空的)顯示「—」 */
function price(v: string | number | null | undefined): string {
  return roundInt(v) > 0 ? money(v) : "—";
}

function readPins(): CatRef[] | null {
  try {
    const raw = localStorage.getItem(K_PINS);
    if (raw === null) return null;
    const list = JSON.parse(raw);
    return Array.isArray(list)
      ? list.filter((c) => c && Number(c.id) > 0 && typeof c.label === "string")
      : [];
  } catch {
    return [];
  }
}
function writePins(list: CatRef[]) {
  try {
    localStorage.setItem(K_PINS, JSON.stringify(list));
  } catch {
    /* 存不了就算了 */
  }
}

/** 序號商品:某一家分店在庫的每一台 */
function UnitsOfStore({
  product,
  warehouse,
  onHistory,
}: {
  product: StockMatrixProduct;
  warehouse: StockMatrixWarehouse;
  onHistory: (serialId: number) => void;
}) {
  const serials = useInStockSerials(product.id, warehouse.id);
  const rows = serials.data ?? [];
  const qty = product.stock_by_warehouse[String(warehouse.id)] ?? 0;
  return (
    <div className="wb-inv-store">
      <div>
        <b>{warehouse.name}</b>
        <span className="wb-dim"> 在庫 {qty}</span>
      </div>
      {serials.isLoading && <div className="wb-dim wb-small">載入中…</div>}
      {serials.isError && <span className="wb-badge bad">序號沒載到</span>}
      {rows.map((s) => (
        <div key={s.id} className="wb-inv-unit">
          <span className="wb-mono">{codesLabel(s)}</span>
          <span className="wb-dim">成本 {price(s.purchase_unit_cost)}</span>
          {product.tracks_unit_condition && (
            <>
              {s.condition_grade && <span>{s.condition_grade} 級</span>}
              {s.custom_unit_price && (
                <span>售價 {price(s.custom_unit_price)}</span>
              )}
              {s.battery_health != null && (
                <span className="wb-dim">電池 {s.battery_health}%</span>
              )}
              {s.condition_note && (
                <span className="wb-dim">{s.condition_note}</span>
              )}
            </>
          )}
          {s.received_at && (
            <span className="wb-dim">{s.received_at.slice(0, 10)} 進</span>
          )}
          <button
            type="button"
            className="wb-link"
            onClick={(e) => {
              e.stopPropagation();
              onHistory(s.id);
            }}
          >
            履歷
          </button>
          <button
            type="button"
            className="wb-link"
            title="印這一台的標籤"
            onClick={(e) => {
              e.stopPropagation();
              openLabelPrint(`serials=${s.id}`);
            }}
          >
            標籤
          </button>
        </div>
      ))}
      {!serials.isLoading && rows.length < qty && rows.length > 0 && (
        <div className="wb-dim wb-small">只列前 {rows.length} 台</div>
      )}
    </div>
  );
}

/** 配件:沒有序號,列出跟這家分店有關、已送出還沒入庫的調撥 */
function PendingOfStore({
  product,
  warehouse,
}: {
  product: StockMatrixProduct;
  warehouse: StockMatrixWarehouse;
}) {
  const pending = usePendingTransfers(product.id, warehouse.id);
  const rows = pending.data ?? [];
  const qty = product.stock_by_warehouse[String(warehouse.id)] ?? 0;
  return (
    <div className="wb-inv-store">
      <div>
        <b>{warehouse.name}</b>
        <span className="wb-dim"> 在庫 {qty}</span>
      </div>
      {pending.isError && <span className="wb-badge bad">調撥中的單沒載到</span>}
      {rows.map((t, i) => {
        const other = t.direction === "out" ? t.to_warehouse : t.from_warehouse;
        return (
          <div key={`${t.transfer_no}-${i}`} className="wb-inv-unit">
            <span className="wb-badge warn">調撥中</span>
            <span>
              {t.direction === "out" ? "調去" : "要從"}
              {other.name}
              {t.direction === "out" ? "" : "進來"} ×{t.qty}
            </span>
            <span className="wb-dim">
              {t.transfer_no} · {t.doc_date}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function ProductDetail({
  product,
  warehouses,
  onHistory,
  onCompat,
}: {
  product: StockMatrixProduct;
  warehouses: StockMatrixWarehouse[];
  onHistory: (serialId: number) => void;
  onCompat: () => void;
}) {
  const stocked = warehouses.filter(
    (w) => (product.stock_by_warehouse[String(w.id)] ?? 0) > 0,
  );
  // 配件:沒貨的分店也可能有東西正在調過來
  const shown = product.requires_serial ? stocked : warehouses;
  return (
    <div>
      <div className="wb-inv-stores">
        {shown.length === 0 && <span className="wb-dim">沒有在庫</span>}
        {shown.map((w) =>
          product.requires_serial ? (
            <UnitsOfStore
              key={w.id}
              product={product}
              warehouse={w}
              onHistory={onHistory}
            />
          ) : (
            <PendingOfStore key={w.id} product={product} warehouse={w} />
          ),
        )}
      </div>
      <div className="wb-detail-actions">
        <button
          type="button"
          className="wb-btn small"
          onClick={(e) => {
            e.stopPropagation();
            onCompat();
          }}
        >
          相容機型
        </button>
        {/* 配件:打張數補印。序號商品一台一張,在上面每一台那一列按「標籤」 */}
        {!product.requires_serial && <AccessoryLabelButton productId={product.id} />}
      </div>
    </div>
  );
}

export function InventoryQueryPage() {
  const isMobile = useIsMobile();
  // 還沒查之前:列出低於安全庫存的品項,一進來就看到要注意的
  const homeSummary = useHomeSummary();
  const lowStockItems = homeSummary.data?.low_stock?.items ?? [];

  const [keyword, setKeyword] = useState("");
  const [selectedCategories, setSelectedCategories] = useState<CatRef[]>([]);
  const [pins, setPins] = useState<CatRef[]>(() => readPins() ?? []);

  const warehousesQuery = useWarehouses();
  const allWarehouses = useMemo(
    () => warehousesQuery.data ?? [],
    [warehousesQuery.data],
  );
  const [selectedWarehouseIds, setSelectedWarehouseIds] = useState<Set<number>>(
    new Set(),
  );
  // 首次載入時每家分店都選起來
  useEffect(() => {
    if (allWarehouses.length > 0 && selectedWarehouseIds.size === 0) {
      setSelectedWarehouseIds(new Set(allWarehouses.map((w) => w.id)));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [allWarehouses]);

  // 第一次用:先把手機、中古這類主力類別釘成常用(之後由人自己釘 / 取消)
  const categoriesQuery = useCategories();
  useEffect(() => {
    if (readPins() !== null || !categoriesQuery.data) return;
    const seeded = categoriesQuery.data
      .filter((c) => /手機|中古|二手|平板|穿戴/.test(c.name))
      .slice(0, 6)
      .map((c) => ({ id: c.id, label: c.name }));
    writePins(seeded);
    setPins(seeded);
  }, [categoriesQuery.data]);

  // 已套用的條件(按查詢、或查過之後再動篩選才更新)
  const [applied, setApplied] = useState<AppliedFilter | null>(null);
  const [page, setPage] = useState(1);
  const [opened, setOpened] = useState<Set<number>>(new Set());
  const [historyId, setHistoryId] = useState<number | null>(null);
  /** 點品名看照片與規格(只是看,不會展開那一列) */
  const peek = usePhotoPeek();
  const [compat, setCompat] = useState<{ id: number; name: string } | null>(
    null,
  );

  // 關鍵字剛好是某一台設備的碼(IMEI 或 SN)時,把那一台現在的狀態與分店講出來:
  // 下面的表是「同款商品」的在庫數,刷到的那一台可能已經賣掉、或在別的分店。
  const devices = useDevicesByCode(applied?.keyword ?? "");

  const matrix = useStockMatrix(
    {
      warehouseIds: applied?.warehouseIds ?? [],
      search: applied?.keyword,
      categoryIds: applied?.categoryIds,
      inStockOnly: true,
      page,
      pageSize: MATRIX_PAGE_SIZE,
    },
    { enabled: !!applied && applied.warehouseIds.length > 0 },
  );

  const warehouses = matrix.data?.warehouses ?? [];
  const rawProducts = matrix.data?.products ?? [];
  const matrixTotal = matrix.data?.total ?? 0;
  const pageCount = Math.max(1, Math.ceil(matrixTotal / MATRIX_PAGE_SIZE));

  // 資料變少(別人賣掉 / 改條件)時頁碼可能超界,後端會夾回最後一頁,
  // 這裡跟著它回報的頁碼校正,避免畫面停在空白頁又看不到分頁按鈕。
  const servedPage = matrix.data?.page;
  useEffect(() => {
    if (servedPage !== undefined && servedPage !== page) {
      setPage(servedPage);
    }
  }, [servedPage, page]);

  const [sort, setSort] = useState<SortState | null>(null);
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
      const cmp =
        typeof av === "string" && typeof bv === "string"
          ? av.localeCompare(bv, "zh-Hant")
          : (av as number) - (bv as number);
      return sort.dir === "asc" ? cmp : -cmp;
    });
    return arr;
  }, [rawProducts, sort]);

  // 點欄位標題:第一次升冪、再點降冪、第三次回預設
  function toggleSort(key: SortKey) {
    setSort((prev) => {
      if (!prev || !sortKeyEquals(prev.by, key)) return { by: key, dir: "asc" };
      if (prev.dir === "asc") return { by: key, dir: "desc" };
      return null;
    });
  }
  function sortMark(key: SortKey): string {
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
  const grandCost = products.reduce(
    (s, p) => s + Number(p.weighted_avg_cost || 0) * p.stock_total,
    0,
  );

  function apply(next?: {
    keyword?: string;
    categories?: CatRef[];
    warehouseIds?: Set<number>;
  }) {
    const ids = next?.warehouseIds ?? selectedWarehouseIds;
    setPage(1);
    setOpened(new Set());
    setApplied({
      keyword: (next?.keyword ?? keyword).trim(),
      categoryIds: (next?.categories ?? selectedCategories).map((c) => c.id),
      warehouseIds: Array.from(ids),
    });
  }

  function resetFilters() {
    setKeyword("");
    setSelectedCategories([]);
    setSelectedWarehouseIds(new Set(allWarehouses.map((w) => w.id)));
    setApplied(null);
    setPage(1);
    setOpened(new Set());
  }

  function toggleCategory(c: CatRef) {
    const next = selectedCategories.some((x) => x.id === c.id)
      ? selectedCategories.filter((x) => x.id !== c.id)
      : [...selectedCategories, c];
    setSelectedCategories(next);
    // 點類別就直接查(不用再按查詢)
    if (selectedWarehouseIds.size > 0) apply({ categories: next });
  }
  function togglePin(c: CatRef) {
    const next = pins.some((x) => x.id === c.id)
      ? pins.filter((x) => x.id !== c.id)
      : [...pins, c];
    setPins(next);
    writePins(next);
  }
  function toggleWarehouse(wid: number) {
    const next = new Set(selectedWarehouseIds);
    if (next.has(wid)) next.delete(wid);
    else next.add(wid);
    setSelectedWarehouseIds(next);
    if (next.size === 0) {
      // 一家都沒選:結果先藏起來(不能上面寫沒選分店、下面還是剛才那家的庫存)。
      // 查詢條件留著,再選回任何一家就照原本的條件重查。
      setOpened(new Set());
      return;
    }
    // 查過之後再換分店:跟著重查
    if (applied) apply({ warehouseIds: next });
  }
  function toggleOpen(pid: number) {
    setOpened((prev) => {
      const next = new Set(prev);
      if (next.has(pid)) next.delete(pid);
      else next.add(pid);
      return next;
    });
  }

  // 常用類別那一排:釘起來的 + 這次選的(還沒釘的排後面)
  const catChips: CatRef[] = [
    ...pins,
    ...selectedCategories.filter((c) => !pins.some((p) => p.id === c.id)),
  ];
  const noStore = selectedWarehouseIds.size === 0;
  const ready = !!applied && !noStore && !matrix.isLoading && !matrix.isError;
  const colCount = 7 + warehouses.length;

  return (
    <div className="wb">
      <div className="wb-row">
        <div className="wb-field grow" style={{ maxWidth: 460 }}>
          <label>搜尋品名 / 品號 / IMEI</label>
          <input
            type="text"
            className="wb-big"
            autoFocus
            value={keyword}
            placeholder="例:A17、保護貼、IMEI 末幾碼"
            onChange={(e) => setKeyword(e.target.value)}
            onKeyDown={(e) => {
              if (e.nativeEvent.isComposing || e.keyCode === 229) return;
              if (e.key === "Enter" && !noStore) {
                e.preventDefault();
                apply();
              }
            }}
          />
        </div>
        <div className="wb-field">
          <label>分店{noStore ? "(至少選一家)" : ""}</label>
          <div className="wb-chips" style={{ minHeight: 44 }}>
            {allWarehouses.map((w) => (
              <button
                key={w.id}
                type="button"
                className={`wb-chip cat${
                  selectedWarehouseIds.has(w.id) ? " on" : ""
                }`}
                onClick={() => toggleWarehouse(w.id)}
              >
                {w.name}
              </button>
            ))}
            {allWarehouses.length > 1 &&
              selectedWarehouseIds.size < allWarehouses.length && (
                <button
                  type="button"
                  className="wb-link"
                  onClick={() => {
                    const all = new Set(allWarehouses.map((w) => w.id));
                    setSelectedWarehouseIds(all);
                    if (applied) apply({ warehouseIds: all });
                  }}
                >
                  全選
                </button>
              )}
          </div>
        </div>
        <div className="wb-field" style={{ width: 190 }}>
          <label>類別</label>
          <div style={{ minHeight: 44, display: "flex", alignItems: "center" }}>
            <ComboBox<Category>
              value=""
              selectedOption={null}
              onChange={(_id, opt?: ComboOption<Category> | null) => {
                if (!opt) return;
                const c = { id: opt.id as number, label: opt.label };
                if (!selectedCategories.some((x) => x.id === c.id)) {
                  toggleCategory(c);
                }
              }}
              fetchOptions={searchCategories}
              placeholder="找類別…"
            />
          </div>
        </div>
        <div style={{ minHeight: 44, display: "flex", gap: 10, alignItems: "center" }}>
          <button
            type="button"
            className="wb-btn blue"
            onClick={() => apply()}
            disabled={noStore}
          >
            查詢
          </button>
          <button type="button" className="wb-btn" onClick={resetFilters}>
            清除
          </button>
          <span className="wb-dim wb-small">
            {ready
              ? `共 ${matrixTotal} 項 · 本頁庫存 ${grandTotal} 件`
              : applied && !noStore && matrix.isLoading
                ? "查詢中…"
                : ""}
          </span>
        </div>
      </div>

      {catChips.length > 0 && (
        <div className="wb-row">
          <div className="wb-field grow">
            <label>常用類別</label>
            <div className="wb-chips">
              {catChips.map((c) => {
                const on = selectedCategories.some((x) => x.id === c.id);
                const pinned = pins.some((x) => x.id === c.id);
                return (
                  <span key={c.id} className={`wb-chip cat${on ? " on" : ""}`}>
                    <button
                      type="button"
                      className="pin"
                      title={pinned ? "取消常用" : "釘成常用"}
                      onClick={() => togglePin(c)}
                    >
                      {pinned ? "★" : "☆"}
                    </button>
                    <button
                      type="button"
                      className="name"
                      onClick={() => toggleCategory(c)}
                    >
                      {c.label}
                    </button>
                  </span>
                );
              })}
            </div>
          </div>
        </div>
      )}

      {(noStore ? [] : (devices.data ?? [])).map((d) => (
        <div key={d.id} className="wb-warn wb-inv-hit">
          <span>
            <span className="wb-mono">{codesLabel(d)}</span> · {d.product_name} ·{" "}
            <b>{d.status_label}</b>
            {d.warehouse
              ? ` · ${
                  allWarehouses.find((w) => w.id === d.warehouse)?.name ??
                  d.warehouse_code ??
                  ""
                }`
              : ""}
          </span>
          <button
            type="button"
            className="wb-link"
            onClick={() => setHistoryId(d.id)}
          >
            履歷
          </button>
        </div>
      ))}

      <div style={{ marginTop: 12 }}>
        {noStore && (
          <div
            className="wb-dim"
            style={{ textAlign: "center", padding: "28px 0" }}
          >
            先選分店
          </div>
        )}
        {!applied && !noStore && (
          <LowStockPanel
            items={lowStockItems}
            onPick={(name) => {
              setKeyword(name);
              if (!noStore) apply({ keyword: name, categories: [] });
            }}
          />
        )}
        {applied && !noStore && matrix.isError && (
          <div className="wb-warn err">{String(matrix.error)}</div>
        )}

        {ready && isMobile && (
          <div className="wb-inv-cards">
            {products.length === 0 && (
              <div className="wb-card wb-dim">查無資料</div>
            )}
            {products.map((p) => (
              <div
                key={p.id}
                className="wb-card wb-inv-card"
                onClick={() => toggleOpen(p.id)}
              >
                <div>
                  <PhotoName
                    id={p.id}
                    name={p.name}
                    sku={p.sku}
                    thumb={p.photo_thumb}
                    onPeek={peek.open}
                    className="pname"
                  />
                  <span className="pcode">{p.sku}</span>
                </div>
                <div className="wb-dim wb-small">
                  {[p.category_name, p.spec, conditionLabel(p)]
                    .filter(Boolean)
                    .join(" · ")}
                </div>
                <div className="wb-inv-card-stores">
                  {warehouses.map((w) => {
                    const qty = p.stock_by_warehouse[String(w.id)] ?? 0;
                    return (
                      <span key={w.id} className={qty > 0 ? "" : "wb-dim"}>
                        {w.name} <b>{qty}</b>
                      </span>
                    );
                  })}
                  <span>
                    合計 <b>{p.stock_total}</b>
                  </span>
                </div>
                <div className="wb-dim wb-small">
                  售價 {price(p.list_price)} · 平均成本{" "}
                  {price(p.weighted_avg_cost)}
                </div>
                {opened.has(p.id) && (
                  <div className="wb-inv-card-detail">
                    <ProductDetail
                      product={p}
                      warehouses={warehouses}
                      onHistory={setHistoryId}
                      onCompat={() => setCompat({ id: p.id, name: p.name })}
                    />
                  </div>
                )}
              </div>
            ))}
            {products.length > 0 && (
              <div className="wb-card wb-inv-card">
                <div className="wb-dim wb-small">本頁合計</div>
                <div className="wb-inv-card-stores">
                  {warehouses.map((w) => (
                    <span key={w.id}>
                      {w.name} <b>{totalsByWarehouse[String(w.id)] ?? 0}</b>
                    </span>
                  ))}
                  <span>
                    合計 <b>{grandTotal}</b>
                  </span>
                </div>
                <div className="wb-dim wb-small">總成本 {price(grandCost)}</div>
              </div>
            )}
          </div>
        )}

        {ready && !isMobile && (
          <table className="wb-table">
            <thead>
              <tr>
                <th>品號</th>
                <th
                  className="sortable"
                  onClick={() => toggleSort({ kind: "name" })}
                >
                  品名{sortMark({ kind: "name" })}
                </th>
                <th
                  className="sortable"
                  onClick={() => toggleSort({ kind: "category" })}
                >
                  類別{sortMark({ kind: "category" })}
                </th>
                {warehouses.map((w) => (
                  <th
                    key={w.id}
                    className="num sortable"
                    onClick={() =>
                      toggleSort({ kind: "warehouse", warehouseId: w.id })
                    }
                  >
                    {w.name}
                    {sortMark({ kind: "warehouse", warehouseId: w.id })}
                  </th>
                ))}
                <th
                  className="num sortable"
                  onClick={() => toggleSort({ kind: "total" })}
                >
                  合計{sortMark({ kind: "total" })}
                </th>
                <th className="num">售價</th>
                <th className="num">平均成本</th>
                <th className="num">總成本</th>
              </tr>
            </thead>
            <tbody>
              {products.length === 0 && (
                <tr>
                  <td colSpan={colCount} className="empty">
                    查無資料
                  </td>
                </tr>
              )}
              {products.map((p) => {
                const cond = conditionLabel(p);
                return (
                  <Fragment key={p.id}>
                    <tr className="clickable" onClick={() => toggleOpen(p.id)}>
                      <td className="wb-dim" style={{ whiteSpace: "nowrap" }}>
                        {p.sku}
                      </td>
                      <td>
                        <PhotoName
                          id={p.id}
                          name={p.name}
                          sku={p.sku}
                          thumb={p.photo_thumb}
                          onPeek={peek.open}
                        />
                        {p.spec && (
                          <span className="wb-dim wb-small"> {p.spec}</span>
                        )}
                        {cond && p.tracks_unit_condition && (
                          <>
                            {" "}
                            <span className="wb-badge">{cond}</span>
                          </>
                        )}
                      </td>
                      <td className="wb-dim wb-small">{p.category_name}</td>
                      {warehouses.map((w) => {
                        const qty = p.stock_by_warehouse[String(w.id)] ?? 0;
                        return (
                          <td key={w.id} className="num">
                            {qty > 0 ? (
                              <b>{qty}</b>
                            ) : (
                              <span className="wb-dim">0</span>
                            )}
                          </td>
                        );
                      })}
                      <td className="num">
                        <b>{p.stock_total}</b>
                      </td>
                      <td className="num">{price(p.list_price)}</td>
                      <td className="num">{price(p.weighted_avg_cost)}</td>
                      <td className="num">
                        {price(Number(p.weighted_avg_cost) * p.stock_total)}
                      </td>
                    </tr>
                    {opened.has(p.id) && (
                      <tr className="detail">
                        <td colSpan={colCount}>
                          <ProductDetail
                            product={p}
                            warehouses={warehouses}
                            onHistory={setHistoryId}
                            onCompat={() =>
                              setCompat({ id: p.id, name: p.name })
                            }
                          />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
              {products.length > 0 && (
                <tr className="total">
                  <td colSpan={3} style={{ textAlign: "right" }}>
                    本頁合計
                  </td>
                  {warehouses.map((w) => (
                    <td key={w.id} className="num">
                      {totalsByWarehouse[String(w.id)] ?? 0}
                    </td>
                  ))}
                  <td className="num">{grandTotal}</td>
                  <td></td>
                  <td className="num">
                    {grandTotal > 0 ? price(grandCost / grandTotal) : "—"}
                  </td>
                  <td className="num">{price(grandCost)}</td>
                </tr>
              )}
            </tbody>
          </table>
        )}

        {applied && !noStore && pageCount > 1 && (
          <div className="wb-pager">
            <button
              type="button"
              className="wb-btn small"
              disabled={page <= 1}
              onClick={() => setPage((n) => Math.max(1, n - 1))}
            >
              上一頁
            </button>
            <span className="wb-dim wb-small">
              第 {page} / {pageCount} 頁{sort ? " · 排序限本頁" : ""}
            </span>
            <button
              type="button"
              className="wb-btn small"
              disabled={page >= pageCount || !(matrix.data?.has_more ?? false)}
              onClick={() => setPage((n) => Math.min(pageCount, n + 1))}
            >
              下一頁
            </button>
          </div>
        )}
      </div>

      {historyId != null && (
        <SerialHistoryModal
          serialId={historyId}
          onClose={() => setHistoryId(null)}
        />
      )}
      {compat && (
        <CompatibilityModal
          productId={compat.id}
          productName={compat.name}
          onClose={() => setCompat(null)}
        />
      )}
      {peek.panel}
    </div>
  );
}

interface LowStockItem {
  id: number;
  name: string;
  sku: string;
  qty: number;
  safety_stock: number;
}

/** 還沒查之前:低於安全庫存的品項,點一下就查那一項 */
function LowStockPanel({
  items,
  onPick,
}: {
  items: LowStockItem[];
  onPick: (name: string) => void;
}) {
  if (items.length === 0) {
    return (
      <div className="wb-dim" style={{ textAlign: "center", padding: "28px 0" }}>
        打關鍵字,或點類別開始查
      </div>
    );
  }
  return (
    <>
      <div className="wb-section" style={{ marginTop: 0 }}>
        <h3>低於安全庫存 {items.length} 項</h3>
        <Link to="/products" className="wb-link">
          調整安全庫存
        </Link>
      </div>
      <table className="wb-table">
        <thead>
          <tr>
            <th>品號</th>
            <th>品名</th>
            <th className="num">安全庫存</th>
            <th className="num">現有</th>
          </tr>
        </thead>
        <tbody>
          {items.map((it) => (
            <tr
              key={it.id}
              className="clickable"
              onClick={() => onPick(it.name)}
              title="點一下查這個品項"
            >
              <td className="wb-dim">{it.sku}</td>
              <td>{it.name}</td>
              <td className="num">{it.safety_stock}</td>
              <td className="num">
                <span className="wb-badge warn">{it.qty}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
