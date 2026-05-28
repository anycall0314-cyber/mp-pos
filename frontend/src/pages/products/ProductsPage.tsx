import { useEffect, useMemo, useState } from "react";

import { useCategories, useProducts, useSaveCategory } from "@/api/hooks";
import type { Product } from "@/api/types";
import { Banner } from "@/components/Banner";
import { Toolbar } from "@/components/Toolbar";

import { BulkAddProductsModal } from "./BulkAddProductsModal";
import { ProductExpanderModal } from "./ProductExpanderModal";
import { ProductForm } from "./ProductForm";
import { ProductImportModal } from "./ProductImportModal";

function formatMoney(value: string | number) {
  const n = Number(value);
  return Number.isFinite(n) ? Math.round(n).toLocaleString() : "—";
}

function flagText(p: Product) {
  const flags: string[] = [];
  if (p.requires_serial) flags.push("追序號");
  if (p.allows_telecom_line) flags.push("可綁約");
  if (p.allows_commission) flags.push("可佣金");
  return flags.length > 0 ? flags.join(" / ") : "純商品";
}

type Selection =
  | { kind: "product"; id: number }
  | { kind: "category"; id: number }
  | { kind: "new_category" }
  | null;

interface CategoryEditState {
  code: string;
  name: string;
  is_active: boolean;
  is_secondhand_default: boolean;
}

interface CategoryNewState {
  code: string;
  name: string;
  sort_order: string;
  is_active: boolean;
  is_secondhand_default: boolean;
}

const EMPTY_NEW_CAT: CategoryNewState = {
  code: "",
  name: "",
  sort_order: "",
  is_active: true,
  is_secondhand_default: false,
};

export function ProductsPage() {
  // ─── 商品搜尋
  // 預設顯示「近期新增 10 筆」(按建立時間倒序);有搜尋字才用搜尋
  const [productQuery, setProductQuery] = useState("");
  const [appliedProductQuery, setAppliedProductQuery] = useState("");
  const isSearching = appliedProductQuery.length > 0;
  const productsResult = useProducts(
    isSearching
      ? `search=${encodeURIComponent(appliedProductQuery)}&page_size=100`
      : `ordering=-created_at&page_size=10`,
  );

  // ─── 類別搜尋(類別本來就少,一次撈完前端過濾)
  const [categoryQuery, setCategoryQuery] = useState("");
  const categoriesResult = useCategories();
  const sortedCategories = useMemo(() => {
    const list = categoriesResult.data ?? [];
    return [...list].sort(
      (a, b) => a.sort_order - b.sort_order || a.code.localeCompare(b.code),
    );
  }, [categoriesResult.data]);
  const filteredCategories = useMemo(() => {
    const q = categoryQuery.trim().toLowerCase();
    if (!q) return sortedCategories;
    return sortedCategories.filter(
      (c) =>
        c.code.toLowerCase().includes(q) || c.name.toLowerCase().includes(q),
    );
  }, [sortedCategories, categoryQuery]);

  // ─── 選擇與右側面板
  const [selection, setSelection] = useState<Selection>(null);
  // 左側欄頁籤:商品列表 vs 類別管理
  const [leftTab, setLeftTab] = useState<"products" | "categories">(
    "products",
  );

  const selectedProduct = useMemo(() => {
    if (selection?.kind !== "product") return null;
    return (
      (productsResult.data ?? []).find((p) => p.id === selection.id) ?? null
    );
  }, [selection, productsResult.data]);

  const selectedCategory = useMemo(() => {
    if (selection?.kind !== "category") return null;
    return (
      (categoriesResult.data ?? []).find((c) => c.id === selection.id) ?? null
    );
  }, [selection, categoriesResult.data]);

  // ─── 商品 Drawer(編輯 / 新增)
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerInitial, setDrawerInitial] = useState<Product | null>(null);

  // ─── 批次新增 Modal
  const [bulkOpen, setBulkOpen] = useState(false);
  const [expanderOpen, setExpanderOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [bulkResult, setBulkResult] = useState<string | null>(null);

  // ─── 類別編輯(右側面板 inline form)
  const saveCategory = useSaveCategory();
  const [catEdit, setCatEdit] = useState<CategoryEditState>({
    code: "",
    name: "",
    is_active: true,
    is_secondhand_default: false,
  });
  const [catError, setCatError] = useState<string | null>(null);
  const [catSavedFlash, setCatSavedFlash] = useState(false);

  // ─── 新增類別(右側面板 inline form)
  const [catNew, setCatNew] = useState<CategoryNewState>(EMPTY_NEW_CAT);
  const [catNewError, setCatNewError] = useState<string | null>(null);

  // 選到一個類別時把資料載到編輯狀態
  useEffect(() => {
    if (!selectedCategory) return;
    setCatEdit({
      code: selectedCategory.code,
      name: selectedCategory.name,
      is_active: selectedCategory.is_active,
      is_secondhand_default: selectedCategory.is_secondhand_default,
    });
    setCatError(null);
    setCatSavedFlash(false);
  }, [selectedCategory?.id]);

  async function saveCategoryEdit() {
    if (!selectedCategory) return;
    try {
      await saveCategory.mutateAsync({
        id: selectedCategory.id,
        code: catEdit.code.trim().toUpperCase(),
        name: catEdit.name.trim(),
        is_active: catEdit.is_active,
        is_secondhand_default: catEdit.is_secondhand_default,
      });
      setCatError(null);
      setCatSavedFlash(true);
      setTimeout(() => setCatSavedFlash(false), 2000);
    } catch (e) {
      setCatError(e instanceof Error ? e.message : "儲存失敗");
    }
  }

  function startCreatingCategory() {
    setCatNew(EMPTY_NEW_CAT);
    setCatNewError(null);
    setSelection({ kind: "new_category" });
  }

  async function saveNewCategory() {
    const code = catNew.code.trim().toUpperCase();
    const name = catNew.name.trim();
    if (!code || !name) {
      setCatNewError("代碼與名稱必填");
      return;
    }
    if (!confirm(`確定新增類別「${code} ${name}」?`)) return;
    const explicit = Number(catNew.sort_order);
    const sort_order =
      Number.isFinite(explicit) && explicit > 0
        ? explicit
        : sortedCategories.length > 0
        ? Math.max(...sortedCategories.map((c) => c.sort_order)) + 10
        : 10;
    try {
      await saveCategory.mutateAsync({
        code,
        name,
        sort_order,
        is_active: catNew.is_active,
        is_secondhand_default: catNew.is_secondhand_default,
      });
      // 留在新增畫面、清空輸入,方便連續新增
      setCatNew(EMPTY_NEW_CAT);
      setCatNewError(null);
    } catch (e) {
      setCatNewError(e instanceof Error ? e.message : "建立失敗");
    }
  }

  // ─── 拖拉排序
  const [draggingId, setDraggingId] = useState<number | null>(null);
  const [dragOverId, setDragOverId] = useState<number | null>(null);

  async function handleCategoryReorder(srcId: number, targetId: number) {
    if (srcId === targetId) return;
    const arr = [...sortedCategories];
    const fromIdx = arr.findIndex((c) => c.id === srcId);
    const toIdx = arr.findIndex((c) => c.id === targetId);
    if (fromIdx < 0 || toIdx < 0) return;
    const [removed] = arr.splice(fromIdx, 1);
    arr.splice(toIdx, 0, removed);
    const renumbered = arr.map((c, i) => ({ ...c, sort_order: (i + 1) * 10 }));
    const changed = renumbered.filter((c, i) => {
      const before = sortedCategories[i];
      return !before || before.id !== c.id || before.sort_order !== c.sort_order;
    });
    try {
      await Promise.all(
        changed.map((c) =>
          saveCategory.mutateAsync({ id: c.id, sort_order: c.sort_order }),
        ),
      );
    } catch (e) {
      setCatError("排序儲存失敗,請重新整理頁面");
    }
  }

  function runProductSearch() {
    setAppliedProductQuery(productQuery.trim());
  }

  function clearProductSearch() {
    setProductQuery("");
    setAppliedProductQuery("");
    if (selection?.kind === "product") setSelection(null);
  }

  return (
    <div className="page">
      <Toolbar
        title=""
        actions={
          leftTab === "products" ? (
            <>
              <button className="btn" onClick={() => setExpanderOpen(true)}>
                型號展開
              </button>
              <button className="btn" onClick={() => setBulkOpen(true)}>
                批次貼上
              </button>
              <button className="btn" onClick={() => setImportOpen(true)}>
                匯入 Excel
              </button>
              <button
                className="btn primary"
                onClick={() => {
                  setDrawerInitial(null);
                  setDrawerOpen(true);
                }}
              >
                + 新增商品
              </button>
            </>
          ) : (
            <button
              className="btn primary"
              onClick={startCreatingCategory}
            >
              + 新增類別
            </button>
          )
        }
      >
        <div className="tab-switcher">
          <button
            type="button"
            className={
              leftTab === "products"
                ? "tab-switcher-item active"
                : "tab-switcher-item"
            }
            onClick={() => setLeftTab("products")}
          >
            商品列表
          </button>
          <button
            type="button"
            className={
              leftTab === "categories"
                ? "tab-switcher-item active"
                : "tab-switcher-item"
            }
            onClick={() => setLeftTab("categories")}
          >
            類別管理
          </button>
        </div>
      </Toolbar>
      {bulkResult && (
        <div
          style={{
            padding: "6px 16px",
            background: "rgba(128,208,144,0.15)",
            color: "#80d090",
            fontSize: 13,
          }}
        >
          {bulkResult}
        </div>
      )}

      <div className="pc-layout">
        <aside
          className="pc-master"
          style={{ gridTemplateRows: "1fr" }}
        >
          {/* ─── 商品區 ─── */}
          {leftTab === "products" && (
          <section className="pc-section pc-section-products">
            <div className="pc-section-header">商品</div>
            <div className="pc-section-search">
              <input
                value={productQuery}
                onChange={(e) => setProductQuery(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    runProductSearch();
                  }
                }}
                placeholder="輸入品名 / 條碼,按 Enter 搜尋"
              />
              <button className="btn primary" onClick={runProductSearch}>
                搜尋
              </button>
              {appliedProductQuery && (
                <button className="btn" onClick={clearProductSearch}>
                  清除
                </button>
              )}
            </div>
            <div className="pc-section-body">
              {productsResult.isLoading && (
                <div className="md-empty">
                  {isSearching ? "搜尋中…" : "載入中…"}
                </div>
              )}
              {!productsResult.isLoading && !productsResult.isError && (
                <>
                  {!isSearching && (productsResult.data ?? []).length > 0 && (
                    <div
                      style={{
                        padding: "6px 12px",
                        fontSize: 12,
                        color: "var(--text-dim)",
                        background: "var(--panel-2)",
                        borderBottom: "1px solid var(--border)",
                      }}
                    >
                      近期新增 {(productsResult.data ?? []).length} 筆
                      (搜尋以看更多)
                    </div>
                  )}
                  <table className="pc-list-table">
                    <thead>
                      <tr>
                        <th>品名</th>
                        <th style={{ width: 80 }}>類別</th>
                        <th className="num" style={{ width: 50 }}>
                          在庫
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {(productsResult.data ?? []).map((p) => (
                        <tr
                          key={p.id}
                          onClick={() =>
                            setSelection({ kind: "product", id: p.id })
                          }
                          className={
                            selection?.kind === "product" &&
                            selection.id === p.id
                              ? "selected"
                              : ""
                          }
                        >
                          <td>{p.name}</td>
                          <td>{p.category_name}</td>
                          <td className="num">{p.stock_qty}</td>
                        </tr>
                      ))}
                      {(productsResult.data ?? []).length === 0 && (
                        <tr>
                          <td colSpan={3} className="md-empty">
                            {isSearching ? "查無商品" : "尚無商品"}
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </>
              )}
            </div>
          </section>
          )}

          {/* ─── 類別區 ─── */}
          {leftTab === "categories" && (
          <section className="pc-section pc-section-categories category-mgr">
            <div className="pc-section-header">
              <span>類別(拖拉重排)</span>
            </div>
            <div className="pc-section-search">
              <input
                value={categoryQuery}
                onChange={(e) => setCategoryQuery(e.target.value)}
                placeholder="輸入代碼 / 名稱 過濾"
              />
            </div>
            <div className="pc-section-body">
              <table className="pc-list-table">
                <thead>
                  <tr>
                    <th style={{ width: 22 }}></th>
                    <th className="num" style={{ width: 44 }}>
                      序
                    </th>
                    <th style={{ width: 70 }}>代碼</th>
                    <th>名稱</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredCategories.map((c) => {
                    const isSelected =
                      selection?.kind === "category" && selection.id === c.id;
                    return (
                      <tr
                        key={c.id}
                        draggable
                        onDragStart={(e) => {
                          setDraggingId(c.id);
                          e.dataTransfer.effectAllowed = "move";
                          e.dataTransfer.setData("text/plain", String(c.id));
                        }}
                        onDragOver={(e) => {
                          e.preventDefault();
                          if (dragOverId !== c.id) setDragOverId(c.id);
                        }}
                        onDragLeave={() => setDragOverId(null)}
                        onDrop={(e) => {
                          e.preventDefault();
                          const src = draggingId;
                          setDraggingId(null);
                          setDragOverId(null);
                          if (src != null) handleCategoryReorder(src, c.id);
                        }}
                        onDragEnd={() => {
                          setDraggingId(null);
                          setDragOverId(null);
                        }}
                        onClick={() =>
                          setSelection({ kind: "category", id: c.id })
                        }
                        className={[
                          isSelected ? "selected" : "",
                          draggingId === c.id ? "row-dragging" : "",
                          dragOverId === c.id && draggingId !== c.id
                            ? "row-drag-over"
                            : "",
                        ]
                          .filter(Boolean)
                          .join(" ")}
                      >
                        <td className="drag-handle">≡</td>
                        <td className="num">{c.sort_order}</td>
                        <td>{c.code}</td>
                        <td>
                          {c.name}
                          {!c.is_active && (
                            <span
                              style={{
                                color: "var(--text-dim)",
                                marginLeft: 6,
                                fontSize: 12,
                              }}
                            >
                              (停用)
                            </span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                  {filteredCategories.length === 0 && (
                    <tr>
                      <td colSpan={4} className="md-empty">
                        {sortedCategories.length === 0
                          ? "尚無類別,新增商品時可順手建立"
                          : "無符合"}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>
          )}
        </aside>

        {/* ─── 右側面板 ─── */}
        <main className="pc-detail">
          {!selection && (
            <div className="md-empty" style={{ marginTop: 60 }}>
              從左側選擇商品或類別以檢視 / 編輯
            </div>
          )}

          {selectedProduct && (
            <div className="pc-detail-body">
              <h3 className="pc-detail-title">{selectedProduct.name}</h3>
              <dl>
                <dt>品名</dt>
                <dd>{selectedProduct.name}</dd>
                <dt>規格</dt>
                <dd>{selectedProduct.spec || "—"}</dd>
                <dt>條碼</dt>
                <dd>{selectedProduct.barcode || "—"}</dd>
                <dt>類別</dt>
                <dd>
                  {selectedProduct.category_code}{" "}
                  {selectedProduct.category_name}
                </dd>
                <dt>建議零售價</dt>
                <dd>{formatMoney(selectedProduct.list_price)}</dd>
                <dt>加權平均成本</dt>
                <dd>{formatMoney(selectedProduct.weighted_avg_cost)}</dd>
                <dt>屬性</dt>
                <dd>{flagText(selectedProduct)}</dd>
                <dt>狀態</dt>
                <dd>{selectedProduct.is_active ? "啟用" : "停用"}</dd>
              </dl>
              <div style={{ marginTop: 16, display: "flex", gap: 8 }}>
                <button
                  className="btn primary"
                  onClick={() => {
                    setDrawerInitial(selectedProduct);
                    setDrawerOpen(true);
                  }}
                >
                  編輯
                </button>
              </div>
            </div>
          )}

          {selection?.kind === "new_category" && (
            <div className="pc-detail-body">
              <h3 className="pc-detail-title">新增類別</h3>
              {catNewError && (
                <Banner kind="error" message={catNewError} />
              )}
              <dl>
                <dt>
                  代碼 <span style={{ color: "#ff7070" }}>*</span>
                </dt>
                <dd>
                  <input
                    value={catNew.code}
                    onChange={(e) =>
                      setCatNew((s) => ({
                        ...s,
                        code: e.target.value.toUpperCase(),
                      }))
                    }
                    maxLength={8}
                    placeholder="例:PH / AC / TB"
                    style={{ width: 140 }}
                    autoFocus
                  />
                  <span
                    style={{
                      color: "var(--text-dim)",
                      fontSize: 12,
                      marginLeft: 8,
                    }}
                  >
                    2–4 個英數字,會作為品號前綴
                  </span>
                </dd>
                <dt>
                  名稱 <span style={{ color: "#ff7070" }}>*</span>
                </dt>
                <dd>
                  <input
                    value={catNew.name}
                    onChange={(e) =>
                      setCatNew((s) => ({ ...s, name: e.target.value }))
                    }
                    maxLength={80}
                    placeholder="例:手機 / 配件"
                    style={{ width: 260 }}
                  />
                </dd>
                <dt>排序</dt>
                <dd>
                  <input
                    type="number"
                    step="1"
                    value={catNew.sort_order}
                    onChange={(e) =>
                      setCatNew((s) => ({ ...s, sort_order: e.target.value }))
                    }
                    placeholder="自動"
                    style={{ width: 100 }}
                  />
                  <span
                    style={{
                      color: "var(--text-dim)",
                      fontSize: 12,
                      marginLeft: 8,
                    }}
                  >
                    留空會排到最後
                  </span>
                </dd>
                <dt>啟用</dt>
                <dd>
                  <label
                    style={{
                      display: "inline-flex",
                      gap: 6,
                      alignItems: "center",
                    }}
                  >
                    <input
                      type="checkbox"
                      checked={catNew.is_active}
                      onChange={(e) =>
                        setCatNew((s) => ({
                          ...s,
                          is_active: e.target.checked,
                        }))
                      }
                    />
                    {catNew.is_active ? "啟用" : "停用"}
                  </label>
                </dd>
                <dt>中古機類別</dt>
                <dd>
                  <label
                    style={{
                      display: "inline-flex",
                      gap: 6,
                      alignItems: "center",
                    }}
                  >
                    <input
                      type="checkbox"
                      checked={catNew.is_secondhand_default}
                      onChange={(e) =>
                        setCatNew((s) => ({
                          ...s,
                          is_secondhand_default: e.target.checked,
                        }))
                      }
                    />
                    <span style={{ color: "var(--text-dim)", fontSize: 12 }}>
                      勾起時,本類別下所有商品自動標為中古機(逐隻記成色 / 電池 / 自定售價)
                    </span>
                  </label>
                </dd>
              </dl>
              <div style={{ marginTop: 16, display: "flex", gap: 8 }}>
                <button
                  className="btn primary"
                  onClick={saveNewCategory}
                  disabled={saveCategory.isPending}
                >
                  建立
                </button>
                <button className="btn" onClick={() => setSelection(null)}>
                  取消
                </button>
              </div>
            </div>
          )}

          {selectedCategory && (
            <div className="pc-detail-body">
              <h3 className="pc-detail-title">
                類別 · {selectedCategory.code} {selectedCategory.name}
              </h3>
              {catError && <Banner kind="error" message={catError} />}
              {catSavedFlash && <Banner kind="success" message="已儲存" />}
              <dl>
                <dt>代碼</dt>
                <dd>
                  <input
                    value={catEdit.code}
                    onChange={(e) =>
                      setCatEdit((s) => ({
                        ...s,
                        code: e.target.value.toUpperCase(),
                      }))
                    }
                    maxLength={8}
                    style={{ width: 120 }}
                  />
                </dd>
                <dt>名稱</dt>
                <dd>
                  <input
                    value={catEdit.name}
                    onChange={(e) =>
                      setCatEdit((s) => ({ ...s, name: e.target.value }))
                    }
                    maxLength={80}
                    style={{ width: 240 }}
                  />
                </dd>
                <dt>排序</dt>
                <dd>
                  {selectedCategory.sort_order}{" "}
                  <span style={{ color: "var(--text-dim)", fontSize: 12 }}>
                    (左側拖拉重排)
                  </span>
                </dd>
                <dt>啟用</dt>
                <dd>
                  <label
                    style={{
                      display: "inline-flex",
                      gap: 6,
                      alignItems: "center",
                    }}
                  >
                    <input
                      type="checkbox"
                      checked={catEdit.is_active}
                      onChange={(e) =>
                        setCatEdit((s) => ({
                          ...s,
                          is_active: e.target.checked,
                        }))
                      }
                    />
                    {catEdit.is_active ? "啟用" : "停用"}
                  </label>
                </dd>
                <dt>中古機類別</dt>
                <dd>
                  <label
                    style={{
                      display: "inline-flex",
                      gap: 6,
                      alignItems: "center",
                    }}
                  >
                    <input
                      type="checkbox"
                      checked={catEdit.is_secondhand_default}
                      onChange={(e) =>
                        setCatEdit((s) => ({
                          ...s,
                          is_secondhand_default: e.target.checked,
                        }))
                      }
                    />
                    <span style={{ color: "var(--text-dim)", fontSize: 12 }}>
                      勾起並儲存時,會把底下所有商品同步標為中古機
                      (反向取消不會還原既有商品)
                    </span>
                  </label>
                </dd>
              </dl>
              <div style={{ marginTop: 16, display: "flex", gap: 8 }}>
                <button
                  className="btn primary"
                  onClick={saveCategoryEdit}
                  disabled={saveCategory.isPending}
                >
                  儲存
                </button>
              </div>
            </div>
          )}
        </main>
      </div>

      <ProductForm
        open={drawerOpen}
        initial={drawerInitial}
        onClose={() => setDrawerOpen(false)}
      />
      <BulkAddProductsModal
        open={bulkOpen}
        onClose={() => setBulkOpen(false)}
        onSuccess={(count) => {
          setBulkOpen(false);
          setBulkResult(`成功建立 ${count} 筆商品`);
          setTimeout(() => setBulkResult(null), 4000);
        }}
      />
      <ProductImportModal
        open={importOpen}
        onClose={() => setImportOpen(false)}
        onImported={() => {
          // 匯入成功後讓商品 / 類別清單重抓
          productsResult.refetch();
          categoriesResult.refetch();
        }}
      />
      <ProductExpanderModal
        open={expanderOpen}
        onClose={() => setExpanderOpen(false)}
        onSuccess={(count) => {
          setExpanderOpen(false);
          setBulkResult(`型號展開:成功建立 ${count} 筆商品`);
          setTimeout(() => setBulkResult(null), 4000);
        }}
      />
    </div>
  );
}
