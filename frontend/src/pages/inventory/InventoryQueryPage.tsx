import { useState } from "react";

import {
  useInStockSerials,
  useProducts,
  useStockBalances,
} from "@/api/hooks";
import { searchCategories, searchWarehouses } from "@/api/search";
import type { Category, Product, Warehouse } from "@/api/types";
import { ComboBox, ComboOption } from "@/components/ComboBox";
import { SerialHistoryModal } from "@/components/SerialHistoryModal";
import { Toolbar } from "@/components/Toolbar";

interface AppliedFilter {
  keyword: string;
  category: number | "";
  warehouse: number | "";
}

function buildQS(f: AppliedFilter): string {
  const u = new URLSearchParams();
  u.set("page_size", "200");
  u.set("is_active", "true");
  u.set("in_stock_only", "true");
  if (f.keyword) u.set("search", f.keyword);
  if (f.category !== "") u.set("category", String(f.category));
  if (f.warehouse !== "") u.set("warehouse", String(f.warehouse));
  return u.toString();
}

interface SerialListModalProps {
  product: Product;
  warehouseId?: number;
  onClose: () => void;
}

function SerialListModal({
  product,
  warehouseId,
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
        <div className="modal-title">{product.name}</div>
        <div className="modal-body">
          {serials.isLoading && <div className="md-empty">…</div>}
          {!serials.isLoading && (
            <table className="line-table">
              <thead>
                <tr>
                  <th style={{ width: 40 }}>#</th>
                  <th>序號</th>
                  <th>倉別</th>
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
                    <td>{s.warehouse_code ?? "—"}</td>
                    <td>{s.received_at?.slice(0, 10) ?? "—"}</td>
                    <td className="num">
                      {Number(s.purchase_unit_cost).toLocaleString()}
                    </td>
                    {product.is_secondhand && (
                      <td>{s.condition_grade || "—"}</td>
                    )}
                    {product.is_secondhand && (
                      <td className="num">
                        {s.custom_unit_price
                          ? Number(s.custom_unit_price).toLocaleString()
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
                        style={{ fontSize: 11, padding: "2px 6px" }}
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
                      colSpan={product.is_secondhand ? 10 : 6}
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

interface BalanceListModalProps {
  product: Product;
  warehouseId?: number;
  onClose: () => void;
}

function BalanceListModal({
  product,
  warehouseId,
  onClose,
}: BalanceListModalProps) {
  const balances = useStockBalances({
    product: product.id,
    warehouse: warehouseId,
  });
  const rows = balances.data ?? [];
  const total = rows.reduce((s, b) => s + b.qty, 0);

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div
        className="modal-card serial-list-modal"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        <div className="modal-title">{product.name} · 各倉分佈</div>
        <div className="modal-body">
          {balances.isLoading && <div className="md-empty">載入中…</div>}
          {!balances.isLoading && (
            <table className="line-table">
              <thead>
                <tr>
                  <th style={{ width: 40 }}>#</th>
                  <th>倉庫</th>
                  <th className="num">在庫</th>
                  <th className="num">加權平均成本</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((b, i) => (
                  <tr key={b.id}>
                    <td>{i + 1}</td>
                    <td>
                      {b.warehouse_code} {b.warehouse_name}
                    </td>
                    <td className="num">{b.qty}</td>
                    <td className="num">
                      {Number(b.weighted_avg_cost).toLocaleString()}
                    </td>
                  </tr>
                ))}
                {rows.length === 0 && (
                  <tr>
                    <td colSpan={4} className="md-empty">
                      —
                    </td>
                  </tr>
                )}
                {rows.length > 0 && (
                  <tr style={{ fontWeight: 600 }}>
                    <td colSpan={2}>合計</td>
                    <td className="num">{total}</td>
                    <td className="num">—</td>
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

export function InventoryQueryPage() {
  // 表單狀態 — 使用者打字 / 切下拉時更新,但不會觸發 API
  const [keyword, setKeyword] = useState("");
  const [category, setCategory] = useState<number | "">("");
  const [categoryOption, setCategoryOption] =
    useState<ComboOption<Category> | null>(null);
  const [warehouse, setWarehouse] = useState<number | "">("");
  const [warehouseOption, setWarehouseOption] =
    useState<ComboOption<Warehouse> | null>(null);

  // 已套用 — 按「查詢」才更新,API 只在這個有值時呼叫
  const [applied, setApplied] = useState<AppliedFilter | null>(null);

  // 點在庫數字打開的明細 modal:序號商品開序號清單,配件開各倉分佈
  const [serialDialog, setSerialDialog] = useState<Product | null>(null);
  const [balanceDialog, setBalanceDialog] = useState<Product | null>(null);

  const queryString = applied ? buildQS(applied) : "";
  const products = useProducts(queryString, { enabled: !!applied });
  const rows = products.data ?? [];
  const totalStock = rows.reduce((s, p) => s + (p.stock_qty || 0), 0);

  function runQuery() {
    setApplied({
      keyword: keyword.trim(),
      category,
      warehouse,
    });
  }

  function resetFilters() {
    setKeyword("");
    setCategory("");
    setCategoryOption(null);
    setWarehouse("");
    setWarehouseOption(null);
    setApplied(null);
  }

  return (
    <div className="page">
      <Toolbar title="庫存查詢" />
      <div className="list-filterbar">
        <label style={{ minWidth: 240 }}>
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
            style={{ minWidth: 180 }}
          />
        </label>
        <label style={{ minWidth: 220 }}>
          類別
          <div style={{ minWidth: 160 }}>
            <ComboBox<Category>
              value={category}
              selectedOption={categoryOption}
              onChange={(id, opt) => {
                setCategory(id);
                setCategoryOption(opt ?? null);
              }}
              fetchOptions={searchCategories}
              placeholder=""
            />
          </div>
        </label>
        <label style={{ minWidth: 220 }}>
          倉庫
          <div style={{ minWidth: 160 }}>
            <ComboBox<Warehouse>
              value={warehouse}
              selectedOption={warehouseOption}
              onChange={(id, opt) => {
                setWarehouse(id);
                setWarehouseOption(opt ?? null);
              }}
              fetchOptions={searchWarehouses}
              placeholder=""
            />
          </div>
        </label>
        <button
          type="button"
          className="btn primary"
          onClick={runQuery}
          disabled={products.isFetching}
        >
          查詢
        </button>
        <button type="button" className="btn" onClick={resetFilters}>
          清除
        </button>
        <span className="list-filterbar-count">
          {applied && !products.isLoading
            ? `${rows.length} 項 · 總庫存 ${totalStock} 件`
            : ""}
        </span>
      </div>
      <div className="md-table" style={{ height: "calc(100% - 80px)" }}>
        {applied && products.isError && (
          <div className="md-empty">{String(products.error)}</div>
        )}
        {serialDialog && (
          <SerialListModal
            product={serialDialog}
            warehouseId={applied?.warehouse || undefined}
            onClose={() => setSerialDialog(null)}
          />
        )}
        {balanceDialog && (
          <BalanceListModal
            product={balanceDialog}
            warehouseId={applied?.warehouse || undefined}
            onClose={() => setBalanceDialog(null)}
          />
        )}
        {applied && !products.isError && (
          <table>
            <thead>
              <tr>
                <th>品名</th>
                <th>類別</th>
                <th>條碼</th>
                <th className="num">在庫</th>
                <th className="num">建議售價</th>
                <th className="num">加權平均成本</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((p) => (
                <tr key={p.id}>
                  <td>{p.name}</td>
                  <td>{p.category_name}</td>
                  <td>{p.barcode || "—"}</td>
                  <td className="num">
                    {p.is_virtual ? (
                      <span style={{ color: "var(--text-dim)" }}>—</span>
                    ) : p.stock_qty === 0 ? (
                      <span style={{ color: "#ff7070" }}>0</span>
                    ) : (
                      <button
                        type="button"
                        className="stock-link"
                        onClick={() =>
                          p.requires_serial
                            ? setSerialDialog(p)
                            : setBalanceDialog(p)
                        }
                      >
                        {p.stock_qty}
                      </button>
                    )}
                  </td>
                  <td className="num">
                    {Number(p.list_price).toLocaleString()}
                  </td>
                  <td className="num">
                    {Number(p.weighted_avg_cost).toLocaleString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
