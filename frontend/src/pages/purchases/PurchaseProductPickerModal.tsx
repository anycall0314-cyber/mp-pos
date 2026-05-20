import { useEffect, useMemo, useState } from "react";

import { api } from "@/api/client";
import type { Paginated, Product } from "@/api/types";
import { Banner } from "@/components/Banner";

export interface PickerProduct {
  product: Product;
  qty: number;
}

interface Props {
  open: boolean;
  onClose: () => void;
  onConfirm: (selected: PickerProduct[]) => void;
  /** "regular":排除中古機;"secondhand-vendor":只列中古機。預設 regular */
  mode?: "regular" | "secondhand-vendor";
}

interface RowState {
  product: Product;
  selected: boolean;
  qty: number;
}

export function PurchaseProductPickerModal({
  open,
  onClose,
  onConfirm,
  mode = "regular",
}: Props) {
  const secondhandFilter =
    mode === "secondhand-vendor"
      ? "&is_secondhand=true"
      : "&is_secondhand=false";
  const [search, setSearch] = useState("");
  const [appliedSearch, setAppliedSearch] = useState("");
  const [rows, setRows] = useState<RowState[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      setSearch("");
      setAppliedSearch("");
      setRows([]);
      setError(null);
    }
  }, [open]);

  // 跑搜尋:預設不撈,使用者按 Enter 或搜尋鍵
  useEffect(() => {
    if (!open) return;
    if (!appliedSearch) {
      setRows([]);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    api<Paginated<Product>>(
      `/products/?search=${encodeURIComponent(
        appliedSearch,
      )}&page_size=50&is_active=true${secondhandFilter}`,
    )
      .then((data) => {
        if (cancelled) return;
        // 已選的保留勾選與數量(merge)
        setRows((prev) => {
          const prevMap = new Map(prev.map((r) => [r.product.id, r]));
          return data.results.map((p) => {
            const existed = prevMap.get(p.id);
            return existed
              ? { product: p, selected: existed.selected, qty: existed.qty }
              : { product: p, selected: false, qty: 1 };
          });
        });
      })
      .catch((e) => {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : "搜尋失敗");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, appliedSearch, secondhandFilter]);

  function runSearch() {
    setAppliedSearch(search.trim());
  }

  function toggleAll(sel: boolean) {
    setRows((prev) => prev.map((r) => ({ ...r, selected: sel })));
  }

  function toggleOne(id: number, sel: boolean) {
    setRows((prev) =>
      prev.map((r) => (r.product.id === id ? { ...r, selected: sel } : r)),
    );
  }

  function updateQty(id: number, qty: number) {
    setRows((prev) =>
      prev.map((r) =>
        r.product.id === id ? { ...r, qty: Math.max(1, qty || 1) } : r,
      ),
    );
  }

  const selectedCount = useMemo(
    () => rows.filter((r) => r.selected).length,
    [rows],
  );

  function confirm() {
    const items: PickerProduct[] = rows
      .filter((r) => r.selected)
      .map((r) => ({ product: r.product, qty: r.qty }));
    if (items.length === 0) {
      setError("尚未勾選任何商品");
      return;
    }
    onConfirm(items);
  }

  if (!open) return null;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div
        className="modal-card picker-modal"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        <div className="modal-title">
          {mode === "secondhand-vendor"
            ? "批次選中古機入庫"
            : "批次選商品入庫"}
        </div>

        {error && <Banner kind="error" message={error} />}

        <div className="modal-body">
          <div
            style={{
              display: "flex",
              gap: 6,
              alignItems: "center",
              marginBottom: 8,
            }}
          >
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  runSearch();
                }
              }}
              placeholder="輸入品名 / 品號 / 條碼 後按 Enter"
              autoFocus
              style={{ flex: 1 }}
            />
            <button className="btn primary" type="button" onClick={runSearch}>
              搜尋
            </button>
            {rows.length > 0 && (
              <>
                <button
                  type="button"
                  className="btn"
                  onClick={() => toggleAll(true)}
                >
                  全選
                </button>
                <button
                  type="button"
                  className="btn"
                  onClick={() => toggleAll(false)}
                >
                  全不選
                </button>
              </>
            )}
          </div>

          {loading && <div className="md-empty">搜尋中…</div>}

          {!loading && !appliedSearch && (
            <div className="md-empty">
              輸入關鍵字搜尋商品。勾選後按下方「加入」即可批次加入進貨單。
            </div>
          )}

          {!loading && appliedSearch && rows.length === 0 && (
            <div className="md-empty">查無商品</div>
          )}

          {rows.length > 0 && (
            <div
              style={{
                maxHeight: 420,
                overflow: "auto",
                border: "1px solid var(--border)",
                borderRadius: 3,
              }}
            >
              <table className="line-table">
                <thead>
                  <tr>
                    <th style={{ width: 32 }}></th>
                    <th>品名</th>
                    <th style={{ width: 110 }}>品號</th>
                    <th style={{ width: 80 }}>類別</th>
                    <th style={{ width: 100 }} className="num">
                      上次進價
                    </th>
                    <th style={{ width: 80 }} className="num">
                      數量
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.product.id}>
                      <td>
                        <input
                          type="checkbox"
                          checked={r.selected}
                          onChange={(e) =>
                            toggleOne(r.product.id, e.target.checked)
                          }
                        />
                      </td>
                      <td>{r.product.name}</td>
                      <td>{r.product.sku}</td>
                      <td>{r.product.category_name}</td>
                      <td className="num">
                        {r.product.last_purchase_price
                          ? Math.round(
                              Number(r.product.last_purchase_price),
                            ).toLocaleString()
                          : "—"}
                      </td>
                      <td>
                        <input
                          type="number"
                          step="1"
                          className="num-input"
                          value={r.qty}
                          disabled={!r.selected}
                          onChange={(e) =>
                            updateQty(r.product.id, Number(e.target.value))
                          }
                          style={{ width: 60, textAlign: "right" }}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div className="modal-actions">
          <button className="btn" type="button" onClick={onClose}>
            取消
          </button>
          <button
            className="btn primary"
            type="button"
            onClick={confirm}
            disabled={selectedCount === 0}
          >
            加入 {selectedCount} 筆到進貨單
          </button>
        </div>
      </div>
    </div>
  );
}
