import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  useCategories,
  usePhoneModels,
  useProducts,
  useProductsByPhoneModel,
  useSaveCategory,
} from "@/api/hooks";
import { api } from "@/api/client";
import type { Product } from "@/api/types";
import { Banner } from "@/components/Banner";
import { Toolbar } from "@/components/Toolbar";
import { MoreMenu } from "@/components/workbench/MoreMenu";
import { useReorder } from "@/hooks/useReorder";
import { toast } from "@/components/workbench/toast";
import { money } from "@/lib/money";
import { purchaseLinkFor } from "@/lib/purchasePrefill";
import { canSetStaffCost, ruleText, staffCostApplies } from "@/lib/staffCost";

import { BulkAddProductsModal } from "./BulkAddProductsModal";
import { BulkCreatePartsModal } from "./BulkCreatePartsModal";
import { BulkEditProductsModal } from "./BulkEditProductsModal";
import { FindFirstPanel } from "./FindFirstPanel";
import { ProductAliasesPanel } from "./ProductAliasesPanel";
import { ProductExpanderModal } from "./ProductExpanderModal";
import { MiniThumb, ProductPhotoStrip, usePhotoPeek } from "@/components/photos/PhotoName";

import { ProductForm } from "./ProductForm";
import { ProductImportModal } from "./ProductImportModal";

function formatMoney(value: string | number) {
  const n = Number(value);
  return Number.isFinite(n) ? money(n) : "—";
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
  | { kind: "model"; key: string; name: string }
  | null;

interface CategoryEditState {
  code: string;
  name: string;
  is_active: boolean;
  is_secondhand_default: boolean;
  needs_host_model: boolean;
}

interface CategoryNewState {
  code: string;
  name: string;
  sort_order: string;
  is_active: boolean;
  is_secondhand_default: boolean;
  needs_host_model: boolean;
}

const EMPTY_NEW_CAT: CategoryNewState = {
  code: "",
  name: "",
  sort_order: "",
  is_active: true,
  is_secondhand_default: false,
  needs_host_model: true,
};

type BatchTool = "expander" | "parts" | "paste" | "import" | "accessory" | "phone";

/** 「批次工具」選單(字數一致)。原本散在上面那一排的入口都在這裡,一個都沒拿掉 */
const BATCH_TOOLS: { key: BatchTool; label: string; title: string }[] = [
  { key: "phone", label: "手機型號", title: "一次建好這個機型的品況 × 容量 × 顏色" },
  { key: "accessory", label: "配件展開", title: "建配件商品(品牌 × 功能 × 顏色),完成後勾選相容機型" },
  { key: "expander", label: "型號展開", title: "一個型號展開成容量 × 顏色" },
  { key: "parts", label: "零件批次", title: "照零件範本一次建好維修零件" },
  { key: "paste", label: "批次貼上", title: "一次貼上多筆商品" },
  { key: "import", label: "匯入表格", title: "匯入 CSV / Excel 檔" },
];

export function ProductsPage() {
  const nav = useNavigate();
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
  /** 點清單上的小縮圖看照片與規格 */
  const peek = usePhotoPeek();
  // 左側欄頁籤:商品列表 / 機型 / 類別管理
  const [leftTab, setLeftTab] = useState<"products" | "models" | "categories">(
    "products",
  );
  // 右側商品詳情頁籤:基本 vs 別名
  const [detailTab, setDetailTab] = useState<"basic" | "aliases">("basic");

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
  /** 新增時先帶進表單的字(「先找有沒有建過」找的那一句) */
  const [drawerPrefill, setDrawerPrefill] = useState<{
    name: string;
    barcode: string;
  } | null>(null);
  // ─── 按「新增商品」先找一次:有就用那一款,確定沒有才建
  const [findOpen, setFindOpen] = useState(false);

  // ─── 批次新增 Modal
  const [bulkOpen, setBulkOpen] = useState(false);
  const [expanderOpen, setExpanderOpen] = useState(false);
  const [accessoryExpanderOpen, setAccessoryExpanderOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [bulkPartsOpen, setBulkPartsOpen] = useState(false);
  const [bulkEditOpen, setBulkEditOpen] = useState(false);
  const [selectedProductIds, setSelectedProductIds] = useState<Set<number>>(
    new Set(),
  );
  const [bulkResult, setBulkResult] = useState<string | null>(null);

  // ─── 類別編輯(右側面板 inline form)
  const saveCategory = useSaveCategory();
  const [catEdit, setCatEdit] = useState<CategoryEditState>({
    code: "",
    name: "",
    is_active: true,
    is_secondhand_default: false,
    needs_host_model: true,
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
      needs_host_model: selectedCategory.needs_host_model,
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
        needs_host_model: catEdit.needs_host_model,
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
        needs_host_model: catNew.needs_host_model,
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

  // 放開的當下畫面就換、背景存、全部存完才重抓一次(規則在 lib/reorder.ts、lib/reorderStore.ts)。
  // 沒存成的訊息放在清單上面:右邊的類別詳情沒選類別時不會出現
  const { move: handleCategoryReorder, error: catOrderError } = useReorder({
    queryKey: ["categories"],
    path: (id) => `/categories/${id}/`,
    alsoRefresh: [["products"]],
  });

  function openBatchTool(key: BatchTool) {
    if (key === "phone") nav("/products/new-phone-model");
    else if (key === "accessory") setAccessoryExpanderOpen(true);
    else if (key === "expander") setExpanderOpen(true);
    else if (key === "parts") setBulkPartsOpen(true);
    else if (key === "paste") setBulkOpen(true);
    else setImportOpen(true);
  }

  /** 把一個既有商品找出來並選起來(右邊看得到它,旁邊就有「進貨」) */
  function showProduct(p: { id: number; sku: string }) {
    setProductQuery(p.sku);
    setAppliedProductQuery(p.sku);
    setLeftTab("products");
    setDetailTab("basic");
    setSelection({ kind: "product", id: p.id });
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
              {selectedProductIds.size > 0 && (
                <>
                  <span
                    style={{
                      color: "var(--text-dim)",
                      fontSize: 14,
                      padding: "0 6px",
                    }}
                  >
                    已勾選 {selectedProductIds.size} 筆
                  </span>
                  <button
                    className="btn"
                    onClick={() => setSelectedProductIds(new Set())}
                  >
                    清除選取
                  </button>
                  <button
                    className="btn primary"
                    onClick={() => setBulkEditOpen(true)}
                  >
                    批次修改 {selectedProductIds.size} 筆
                  </button>
                </>
              )}
              {/* 一次建很多筆的工具收在這裡(字數一致);平常建一個商品只有右邊那一顆 */}
              <MoreMenu label="批次工具" buttonClass="btn">
                {(close) =>
                  BATCH_TOOLS.map((t) => (
                    <button
                      key={t.key}
                      type="button"
                      role="menuitem"
                      className="ws-more-item"
                      title={t.title}
                      onClick={() => {
                        close();
                        openBatchTool(t.key);
                      }}
                    >
                      {t.label}
                    </button>
                  ))
                }
              </MoreMenu>
              <button className="btn primary" onClick={() => setFindOpen(true)}>
                新增商品
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
              leftTab === "models"
                ? "tab-switcher-item active"
                : "tab-switcher-item"
            }
            onClick={() => {
              setLeftTab("models");
              setSelection(null);
            }}
          >
            機型
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
            color: "var(--success-text-soft)",
            fontSize: 14,
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
                        fontSize: 14,
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
                        <th style={{ width: 30 }}>
                          <input
                            type="checkbox"
                            title="全選本頁"
                            checked={
                              (productsResult.data ?? []).length > 0 &&
                              (productsResult.data ?? []).every((p) =>
                                selectedProductIds.has(p.id),
                              )
                            }
                            onChange={(e) => {
                              const all = productsResult.data ?? [];
                              setSelectedProductIds((prev) => {
                                const next = new Set(prev);
                                if (e.target.checked) {
                                  all.forEach((p) => next.add(p.id));
                                } else {
                                  all.forEach((p) => next.delete(p.id));
                                }
                                return next;
                              });
                            }}
                          />
                        </th>
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
                          <td onClick={(e) => e.stopPropagation()}>
                            <input
                              type="checkbox"
                              checked={selectedProductIds.has(p.id)}
                              onChange={(e) => {
                                setSelectedProductIds((prev) => {
                                  const next = new Set(prev);
                                  if (e.target.checked) next.add(p.id);
                                  else next.delete(p.id);
                                  return next;
                                });
                              }}
                            />
                          </td>
                          <td>
                            <MiniThumb
                              src={p.photo_thumb}
                              onClick={() => peek.open({ id: p.id, name: p.name, sku: p.sku })}
                            />
                            {p.name}
                          </td>
                          <td>{p.category_name}</td>
                          <td className="num">{p.stock_qty}</td>
                        </tr>
                      ))}
                      {(productsResult.data ?? []).length === 0 && (
                        <tr>
                          <td colSpan={4} className="md-empty">
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

          {/* ─── 機型區(一機型一列,右側展開看底下全新/中古 SKU) ─── */}
          {leftTab === "models" && (
            <ModelBrowser
              selectedKey={selection?.kind === "model" ? selection.key : null}
              onPick={(key, name) => setSelection({ kind: "model", key, name })}
            />
          )}

          {/* ─── 類別區 ─── */}
          {leftTab === "categories" && (
          <section className="pc-section pc-section-categories category-mgr">
            <div className="pc-section-header">
              <span>類別(拖拉重排)</span>
            </div>
            {catOrderError && <Banner kind="error" message={catOrderError} />}
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
                                fontSize: 14,
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
              {leftTab === "models"
                ? "從左側選擇機型,看底下全新 / 中古各有哪些"
                : "從左側選擇商品或類別以檢視 / 編輯"}
            </div>
          )}

          {selection?.kind === "model" && (
            <ModelSkuPanel modelKey={selection.key} modelName={selection.name} />
          )}

          {selectedProduct && (
            <div className="pc-detail-body">
              <h3 className="pc-detail-title">{selectedProduct.name}</h3>
              <div className="tab-switcher" style={{ marginBottom: 12 }}>
                <button
                  className={
                    detailTab === "basic"
                      ? "tab-switcher-item active"
                      : "tab-switcher-item"
                  }
                  onClick={() => setDetailTab("basic")}
                >
                  基本
                </button>
                <button
                  className={
                    detailTab === "aliases"
                      ? "tab-switcher-item active"
                      : "tab-switcher-item"
                  }
                  onClick={() => setDetailTab("aliases")}
                >
                  別名
                </button>
              </div>

              {detailTab === "basic" && (
                <>
                  <ProductPhotoStrip productId={selectedProduct.id} />
                  <dl>
                    <dt>品名</dt>
                    <dd>{selectedProduct.name}</dd>
                    <dt>規格</dt>
                    <dd>{selectedProduct.spec || "—"}</dd>
                    <dt>條碼</dt>
                    <dd>{selectedProduct.barcode || "—"}</dd>
                    <dt>容量 / 顏色 / 版本</dt>
                    <dd>
                      {[
                        selectedProduct.capacity,
                        selectedProduct.color,
                        selectedProduct.region_version,
                      ]
                        .filter(Boolean)
                        .join(" / ") || "—"}
                    </dd>
                    <dt>類別</dt>
                    <dd>
                      {selectedProduct.category_code}{" "}
                      {selectedProduct.category_name}
                    </dd>
                    <dt>建議零售價</dt>
                    <dd>{formatMoney(selectedProduct.list_price)}</dd>
                    <dt>加權平均成本</dt>
                    <dd>{formatMoney(selectedProduct.weighted_avg_cost)}</dd>
                    {staffCostApplies(selectedProduct) && (
                      <>
                        <dt>業務員成本</dt>
                        <dd>
                          {formatMoney(
                            selectedProduct.staff_cost ?? selectedProduct.weighted_avg_cost,
                          )}
                          {/* 怎麼算只有管理員的資料裡有 */}
                          {canSetStaffCost(selectedProduct) &&
                            `(${
                              ruleText(
                                selectedProduct.staff_cost_mode,
                                selectedProduct.staff_cost_value,
                              ) || "照全公司"
                            })`}
                        </dd>
                      </>
                    )}
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
                    {/* 建好品號的下一步多半是進貨:帶著這個商品去進貨開單頁(中古機去中古收購;虛擬、停用的沒有這顆) */}
                    {(() => {
                      const to = purchaseLinkFor([selectedProduct]);
                      return to ? (
                        <button className="btn" onClick={() => nav(to)}>
                          進貨
                        </button>
                      ) : null;
                    })()}
                  </div>
                </>
              )}

              {detailTab === "aliases" && (
                <ProductAliasesPanel productId={selectedProduct.id} />
              )}
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
                  代碼 <span style={{ color: "var(--danger-text)" }}>*</span>
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
                      fontSize: 14,
                      marginLeft: 8,
                    }}
                  >
                    2–4 個英數字,會作為品號前綴
                  </span>
                </dd>
                <dt>
                  名稱 <span style={{ color: "var(--danger-text)" }}>*</span>
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
                      fontSize: 14,
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
                    <span style={{ color: "var(--text-dim)", fontSize: 14 }}>
                      勾起時,本類別下所有商品自動標為中古機(逐隻記成色 / 電池 / 自定售價)
                    </span>
                  </label>
                </dd>
                <dt>需要掛相容機型</dt>
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
                      checked={catNew.needs_host_model}
                      onChange={(e) =>
                        setCatNew((s) => ({
                          ...s,
                          needs_host_model: e.target.checked,
                        }))
                      }
                    />
                    <span style={{ color: "var(--text-dim)", fontSize: 14 }}>
                      關掉代表這類商品跟機型無關(線材 / 吊飾 / 家電),不列入待補相容機型
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
                  <span style={{ color: "var(--text-dim)", fontSize: 14 }}>
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
                    <span style={{ color: "var(--text-dim)", fontSize: 14 }}>
                      勾起並儲存時,會把底下所有商品同步標為中古機
                      (反向取消不會還原既有商品)
                    </span>
                  </label>
                </dd>
                <dt>需要掛相容機型</dt>
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
                      checked={catEdit.needs_host_model}
                      onChange={(e) =>
                        setCatEdit((s) => ({
                          ...s,
                          needs_host_model: e.target.checked,
                        }))
                      }
                    />
                    <span style={{ color: "var(--text-dim)", fontSize: 14 }}>
                      關掉代表這類商品跟機型無關(線材 / 吊飾 / 家電),不列入待補相容機型
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

      <FindFirstPanel
        open={findOpen}
        onClose={() => setFindOpen(false)}
        peeking={peek.isOpen}
        onPeek={peek.open}
        onUse={(p) => {
          setFindOpen(false);
          showProduct(p);
        }}
        onCreate={(kind, prefill) => {
          setFindOpen(false);
          if (kind === "phone") {
            nav("/products/new-phone-model");
            return;
          }
          setDrawerInitial(null);
          setDrawerPrefill(prefill);
          setDrawerOpen(true);
        }}
      />
      <ProductForm
        open={drawerOpen}
        initial={drawerInitial}
        prefill={drawerPrefill}
        onPeek={peek.open}
        peeking={peek.isOpen}
        onClose={() => setDrawerOpen(false)}
        onSaved={(p) => {
          // 新建的:選到那一筆(右邊看得到「進貨」),並且跳一句可以直接按的
          if (drawerInitial?.id) return;
          // 正在搜尋別的東西時,新的那一筆不在結果裡、右邊就看不到:回到「近期新增」(它在最上面)
          setProductQuery("");
          setAppliedProductQuery("");
          setLeftTab("products");
          setDetailTab("basic");
          setSelection({ kind: "product", id: p.id });
          const to = purchaseLinkFor([p]);
          toast(
            `已建立 ${p.sku} ${p.name}`,
            "ok",
            to ? { ms: 9000, action: { label: "進貨", fn: () => nav(to) } } : undefined,
          );
        }}
        onUseExisting={(id, note) => {
          // 記住叫法的結果用訊息條講(沒記住是紅的;以前放在上面那條綠色的成功列,看起來像成功)
          if (note) toast(note.text, note.tone, { ms: 6000 });
          // 用品號把那筆找出來並選起來,讓人直接看到既有的那一筆
          api<Product>(`/products/${id}/`).then(showProduct);
        }}
      />
      {/* 看照片與規格的面板放在「先找有沒有建過」與商品表單後面:從那兩個地方點開時要疊在上面 */}
      {peek.panel}
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
      <ProductExpanderModal
        mode="accessory"
        open={accessoryExpanderOpen}
        onClose={() => setAccessoryExpanderOpen(false)}
        onSuccess={(count) => {
          setAccessoryExpanderOpen(false);
          setBulkResult(`新增配件:成功建立 ${count} 筆配件`);
          setTimeout(() => setBulkResult(null), 4000);
        }}
      />
      <BulkCreatePartsModal
        open={bulkPartsOpen}
        onClose={() => setBulkPartsOpen(false)}
      />
      <BulkEditProductsModal
        open={bulkEditOpen}
        productIds={Array.from(selectedProductIds)}
        onClose={() => setBulkEditOpen(false)}
        onSuccess={(count) => {
          setBulkEditOpen(false);
          setBulkResult(`批次修改成功:${count} 筆`);
          setSelectedProductIds(new Set());
          setTimeout(() => setBulkResult(null), 4000);
        }}
      />
    </div>
  );
}

// ─── 機型瀏覽:左側一機型一列(品牌分組),點選右側展開 ───
function ModelBrowser({
  selectedKey,
  onPick,
}: {
  selectedKey: string | null;
  onPick: (key: string, name: string) => void;
}) {
  const [q, setQ] = useState("");
  const [applied, setApplied] = useState("");
  const models = usePhoneModels(applied || undefined);
  const rows = models.data ?? [];

  // 依品牌分組(品牌名 → 機型清單)
  const byBrand = useMemo(() => {
    const m = new Map<string, typeof rows>();
    for (const r of rows) {
      const b = r.brand_name || "其他";
      if (!m.has(b)) m.set(b, []);
      m.get(b)!.push(r);
    }
    return Array.from(m.entries());
  }, [rows]);

  return (
    <section className="pc-section">
      <div className="pc-section-header">機型</div>
      <div className="pc-section-search">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") setApplied(q.trim());
          }}
          placeholder="搜尋機型 / 系列,按 Enter"
        />
        <button className="btn primary" onClick={() => setApplied(q.trim())}>
          搜尋
        </button>
        {applied && (
          <button
            className="btn"
            onClick={() => {
              setQ("");
              setApplied("");
            }}
          >
            清除
          </button>
        )}
      </div>
      <div className="pc-section-body">
        {models.isLoading && <div className="md-empty">載入中…</div>}
        {!models.isLoading && rows.length === 0 && (
          <div className="md-empty">尚無機型</div>
        )}
        {byBrand.map(([brand, list]) => (
          <div key={brand}>
            <div
              style={{
                padding: "6px 12px",
                fontSize: 14,
                fontWeight: 600,
                color: "var(--text-dim)",
                background: "var(--panel-2)",
                borderBottom: "1px solid var(--border)",
              }}
            >
              {brand}
            </div>
            <table className="pc-list-table">
              <tbody>
                {list.map((r) => (
                  <tr
                    key={r.model_key}
                    onClick={() => onPick(r.model_key, r.model_name)}
                    className={selectedKey === r.model_key ? "selected" : ""}
                  >
                    <td>{r.model_name}</td>
                    <td className="num" style={{ width: 60 }}>
                      {r.sku_count} 款
                    </td>
                    <td className="num" style={{ width: 50 }}>
                      {r.total_stock}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
      </div>
    </section>
  );
}

// ─── 機型展開:右側顯示底下 SKU,按「全新 / 已拆封 / 中古」分組並排 ───
function ModelSkuPanel({
  modelKey,
  modelName,
}: {
  modelKey: string;
  modelName: string;
}) {
  const groups = useProductsByPhoneModel(modelKey);
  const data = groups.data ?? [];
  return (
    <div className="pc-detail-body">
      <h3 className="pc-detail-title">{modelName}</h3>
      {groups.isLoading && <div className="md-empty">載入中…</div>}
      {!groups.isLoading && data.length === 0 && (
        <div className="md-empty">這個機型底下還沒有商品</div>
      )}
      {data.map((g) => (
        <div key={g.condition} style={{ marginBottom: 18 }}>
          <div
            style={{
              fontWeight: 600,
              marginBottom: 6,
              color: g.is_secondhand ? "var(--warn-text-orange)" : "var(--text)",
            }}
          >
            {g.condition}
            <span style={{ color: "var(--text-dim)", fontWeight: 400 }}>
              {" "}
              · {g.skus.length} 款
            </span>
          </div>
          <table className="pc-list-table">
            <thead>
              <tr>
                <th>容量 / 顏色</th>
                <th style={{ width: 80 }}>地區</th>
                <th className="num" style={{ width: 80 }}>
                  售價
                </th>
                <th className="num" style={{ width: 50 }}>
                  在庫
                </th>
              </tr>
            </thead>
            <tbody>
              {g.skus.map((s) => (
                <tr key={s.id}>
                  <td>
                    {s.capacity} {s.color}
                  </td>
                  <td style={{ color: "var(--text-dim)" }}>
                    {s.region_version || "—"}
                  </td>
                  <td className="num">
                    {money(s.list_price)}
                  </td>
                  <td className="num">{s.stock_qty}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  );
}
