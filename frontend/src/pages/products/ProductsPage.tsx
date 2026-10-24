import { useCan } from "@/auth/AuthContext";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";

import {
  useCategories,
  useProductList,
  useProductsByPhoneModel,
  useSaveCategory,
  useBrands,
  useCategoryBrands,
  useCategoryTree,
  useProduct,
} from "@/api/hooks";
import { api } from "@/api/client";
import type { Category, CategoryKind, Product, SharePart, TreeProduct } from "@/api/types";
import { Banner } from "@/components/Banner";
import { PaneBack } from "@/components/PaneBack";
import { Toolbar } from "@/components/Toolbar";
import { ChoiceGroup, SegmentedControl, Tabs } from "@/components/ui";
import { MoreMenu } from "@/components/workbench/MoreMenu";
import { useReorder } from "@/hooks/useReorder";
import { cutNote } from "@/lib/listAll";
import { isProductCode } from "@/lib/deviceCodes";
import { money } from "@/lib/money";
import { newProductUrl } from "@/lib/productFormUrl";
import { readListSnapshot, saveListSnapshot, type ProductListSnapshot } from "@/lib/productListReturn";
import { isProductSavedMessage, openInNewTab } from "@/lib/productTabs";
import { purchaseLinkFor } from "@/lib/purchasePrefill";
import { canSetStaffCost, ruleText, staffCostApplies } from "@/lib/staffCost";

import { KindPicker } from "./KindPicker";
import { BulkCreatePartsModal } from "./BulkCreatePartsModal";
import { BulkEditProductsModal } from "./BulkEditProductsModal";
import { FindFirstPanel } from "./FindFirstPanel";
import { ProductAliasesPanel } from "./ProductAliasesPanel";
import { ProductExpanderModal } from "./ProductExpanderModal";
import { MiniThumb, ProductPhotoStrip, usePhotoPeek } from "@/components/photos/PhotoName";
import { fitsLine } from "@/lib/fits";

import { ProductImportModal } from "./ProductImportModal";
import { errorText } from "@/lib/errorText";

function formatMoney(value: string | number) {
  const n = Number(value);
  return Number.isFinite(n) ? money(n) : "—";
}

function flagText(p: Product) {
  const flags: string[] = [];
  if (p.requires_serial) flags.push("需追蹤序號");
  if (p.allows_telecom_line) flags.push("可綁門號合約");
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
  name: string;
  is_active: boolean;
  is_secondhand_default: boolean;
  kind: CategoryKind | "";
  /** 配件共用:現在實際跟著哪一個(沒改就不送,類別名稱判斷的照舊) */
  shares: SharePart | "none";
}

const SHARE_OPTIONS: { key: SharePart | "none"; label: string }[] = [
  { key: "screen", label: "跟螢幕" },
  { key: "body", label: "跟機身" },
  { key: "none", label: "不共用" },
];

interface CategoryNewState {
  name: string;
  sort_order: string;
  is_active: boolean;
  is_secondhand_default: boolean;
  kind: CategoryKind | "";
}

const EMPTY_NEW_CAT: CategoryNewState = {
  name: "",
  sort_order: "",
  is_active: true,
  is_secondhand_default: false,
  kind: "",
};

type BatchTool = "parts" | "import" | "accessory" | "phone";

/**
 * 「批次工具」選單(字數一致)。2026-10-23 收成這幾個(全站檢視 D8,owner「照你建議」):
 * 手機照平台型號庫建;配件一次很多款用多款展開、貼表格用匯入表格(批次貼上併進去了)。
 * 「型號展開」拿掉:它能直接建一批手機、繞過平台型號庫
 */
const BATCH_TOOLS: { key: BatchTool; label: string; title: string }[] = [
  { key: "phone", label: "手機型號", title: "一次建好這個機型的品況 × 容量 × 顏色" },
  { key: "accessory", label: "多款展開", title: "同一款配件的功能 × 顏色" },
  { key: "import", label: "匯入表格", title: "貼上或選檔案,一次建很多個配件" },
  { key: "parts", label: "零件批次", title: "照零件範本一次建好維修零件" },
];

export function ProductsPage() {
  const nav = useNavigate();
  const queryClient = useQueryClient();
  // 整頁編輯改完 / 按上一頁回來:清單照按編輯當下的樣子擺回去(全站檢視 R07;規則在 lib/productListReturn.ts)
  const location = useLocation();
  const [back] = useState(() => readListSnapshot(sessionStore(), location.key));
  // ─── 商品搜尋
  // 預設顯示「近期新增 10 筆」(按建立時間倒序);有搜尋字才用搜尋
  const [productQuery, setProductQuery] = useState(back?.productQuery ?? "");
  const [appliedProductQuery, setAppliedProductQuery] = useState(back?.appliedProductQuery ?? "");
  const isSearching = appliedProductQuery.length > 0;
  const productsTop = useProductList(
    isSearching
      ? `search=${encodeURIComponent(appliedProductQuery)}&page_size=100`
      : `ordering=-created_at&page_size=10`,
    // 新增 / 編輯在另一個分頁做(SPEC-005):切回這一頁時重新抓,剛建的那一筆看得到
    { refetchOnWindowFocus: true },
  );
  // 下面沿用陣列的寫法;超過一頁的另外講「只列前 N 筆」(全站檢視 D2:以前悄悄少掉)
  const productsResult = { ...productsTop, data: productsTop.data?.rows };
  const productsCut = isSearching ? cutNote(productsTop.data, "只列前", "筆") : "";
  // 刷條碼 / 打品號剛好對到一筆(完全相同):直接選它(全站檢視 D2)
  const autoPicked = useRef(back?.appliedProductQuery ?? "");

  // ─── 類別搜尋(類別本來就少,一次撈完前端過濾)
  const [categoryQuery, setCategoryQuery] = useState(back?.categoryQuery ?? "");
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
  const [selection, setSelection] = useState<Selection>((back?.selection as Selection | undefined) ?? null);
  /** 點清單上的小縮圖看照片與規格 */
  const peek = usePhotoPeek();
  // 左側欄頁籤:商品列表 / 機型 / 類別管理
  const [leftTab, setLeftTab] = useState<"products" | "models" | "categories">(
    back?.leftTab ?? "products",
  );
  // 右側商品詳情頁籤:基本 vs 別名
  const [detailTab, setDetailTab] = useState<"basic" | "aliases">(back?.detailTab ?? "basic");
  /** 分類瀏覽走到哪一層、商品清單捲到哪(按編輯時一起記下來) */
  const browseAt = useRef<TreeAt | undefined>((back?.browseAt as TreeAt | null | undefined) ?? undefined);
  const listBody = useRef<HTMLDivElement>(null);
  const scrolledBack = useRef(!back);
  function listSnapshot(): ProductListSnapshot {
    return {
      leftTab,
      productQuery,
      appliedProductQuery,
      categoryQuery,
      selection,
      detailTab,
      browseAt: browseAt.current,
      listScroll: listBody.current?.scrollTop ?? 0,
    };
  }

  const listedProduct = useMemo(() => {
    if (selection?.kind !== "product") return null;
    return (
      (productsResult.data ?? []).find((p) => p.id === selection.id) ?? null
    );
  }, [selection, productsResult.data]);
  // 分類瀏覽點到的商品不在商品列表那一頁裡:另外讀那一個
  const pickedProduct = useProduct(selection?.kind === "product" && !listedProduct ? selection.id : null);
  const selectedProduct = listedProduct ?? (selection?.kind === "product" ? pickedProduct.data ?? null : null);

  const selectedCategory = useMemo(() => {
    if (selection?.kind !== "category") return null;
    return (
      (categoriesResult.data ?? []).find((c) => c.id === selection.id) ?? null
    );
  }, [selection, categoriesResult.data]);

  // ─── 按「新增商品」先找一次:有就用那一款,確定沒有才建
  const [findOpen, setFindOpen] = useState(false);

  // ─── 批次新增 Modal
  const [accessoryExpanderOpen, setAccessoryExpanderOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [bulkPartsOpen, setBulkPartsOpen] = useState(false);
  const [bulkEditOpen, setBulkEditOpen] = useState(false);
  // 員工帳號的權限:沒有「商品建檔」的帳號只能看(伺服器也會擋)
  const canEdit = useCan("edit_products");
  const [selectedProductIds, setSelectedProductIds] = useState<Set<number>>(
    new Set(),
  );
  const [bulkResult, setBulkResult] = useState<string | null>(null);

  // ─── 類別編輯(右側面板 inline form)
  const saveCategory = useSaveCategory();
  const [catEdit, setCatEdit] = useState<CategoryEditState>({
    name: "",
    is_active: true,
    is_secondhand_default: false,
    kind: "",
    shares: "none",
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
      name: selectedCategory.name,
      is_active: selectedCategory.is_active,
      is_secondhand_default: selectedCategory.is_secondhand_default,
      kind: selectedCategory.kind,
      shares: selectedCategory.shares_part || "none",
    });
    setCatError(null);
    setCatSavedFlash(false);
  }, [selectedCategory?.id]);

  async function saveCategoryEdit() {
    if (!selectedCategory) return;
    try {
      await saveCategory.mutateAsync({
        id: selectedCategory.id,
        name: catEdit.name.trim(),
        is_active: catEdit.is_active,
        is_secondhand_default: catEdit.is_secondhand_default,
        ...(catEdit.kind ? { kind: catEdit.kind } : {}),
        ...(catEdit.shares !== (selectedCategory.shares_part || "none") ? { shares_by: catEdit.shares } : {}),
      });
      setCatError(null);
      setCatSavedFlash(true);
      setTimeout(() => setCatSavedFlash(false), 2000);
    } catch (e) {
      setCatError(errorText(e));
    }
  }

  function startCreatingCategory() {
    setCatNew(EMPTY_NEW_CAT);
    setCatNewError(null);
    setSelection({ kind: "new_category" });
  }

  async function saveNewCategory() {
    // 代碼(品號開頭)系統給(全站檢視 D6)
    const name = catNew.name.trim();
    if (!name) {
      setCatNewError("要填名稱");
      return;
    }
    if (!catNew.kind) {
      setCatNewError("要選主機、配件或一般");
      return;
    }
    const explicit = Number(catNew.sort_order);
    const sort_order =
      Number.isFinite(explicit) && explicit > 0
        ? explicit
        : sortedCategories.length > 0
        ? Math.max(...sortedCategories.map((c) => c.sort_order)) + 10
        : 10;
    try {
      await saveCategory.mutateAsync({
        name,
        sort_order,
        is_active: catNew.is_active,
        is_secondhand_default: catNew.is_secondhand_default,
        kind: catNew.kind,
      });
      // 留在新增畫面、清空輸入,方便連續新增
      setCatNew(EMPTY_NEW_CAT);
      setCatNewError(null);
    } catch (e) {
      setCatNewError(errorText(e));
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

  /** 新增手機型號:跟新增商品一樣另開分頁;瀏覽器擋住就在這一頁換頁(全站檢視 D4) */
  function openPhoneWizard() {
    if (!openInNewTab("/products/new-phone-model")) nav("/products/new-phone-model");
  }

  function openBatchTool(key: BatchTool) {
    if (key === "phone") openPhoneWizard();
    else if (key === "accessory") setAccessoryExpanderOpen(true);
    else if (key === "parts") setBulkPartsOpen(true);
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

  // 另開的分頁(新增商品、新增手機型號)存好了:清單重抓、選到那一筆(全站檢視 D4;只認同一個網站送來的)
  useEffect(() => {
    function onMessage(e: MessageEvent) {
      if (e.origin !== window.location.origin || !isProductSavedMessage(e.data)) return;
      void queryClient.invalidateQueries({ queryKey: ["products"] });
      if (e.data.id !== null) api<Product>(`/products/${e.data.id}/`).then(showProduct).catch(() => undefined);
      else if (e.data.find) findProducts(e.data.find);
    }
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /** 商品清單搜這幾個字(新增手機型號的「去看」) */
  function findProducts(text: string) {
    setProductQuery(text);
    setAppliedProductQuery(text);
    setLeftTab("products");
  }

  // 整頁新增 / 編輯存好回來帶著 `?selected=商品編號`(SPEC-005):選到那一筆,網址清掉(重新整理不會一直跳回去)
  const [searchParams, setSearchParams] = useSearchParams();
  const selectedParam = searchParams.get("selected");
  const findParam = searchParams.get("find");
  useEffect(() => {
    if (!findParam) return;
    setSearchParams({}, { replace: true });
    findProducts(findParam);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [findParam]);
  useEffect(() => {
    if (!selectedParam || !/^\d+$/.test(selectedParam)) return;
    setSearchParams({}, { replace: true });
    api<Product>(`/products/${selectedParam}/`).then(showProduct).catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedParam]);

  useEffect(() => {
    const rows = productsTop.data?.rows;
    if (!isSearching || !rows || autoPicked.current === appliedProductQuery) return;
    autoPicked.current = appliedProductQuery;
    const exact = rows.filter((p) => isProductCode(p, appliedProductQuery));
    if (exact.length === 1 && rows.length >= 1 && selection?.kind !== "product") {
      setDetailTab("basic");
      setSelection({ kind: "product", id: exact[0].id });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [productsTop.data, appliedProductQuery]);

  // 編輯完回來:清單畫出來之後捲回原來的位置(只做一次)
  useLayoutEffect(() => {
    if (scrolledBack.current || !back || !productsTop.data || !listBody.current) return;
    scrolledBack.current = true;
    listBody.current.scrollTop = back.listScroll;
  }, [productsTop.data, back]);

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
                  {canEdit && (
                    <button
                      className="btn primary"
                      onClick={() => setBulkEditOpen(true)}
                    >
                      批次修改 {selectedProductIds.size} 筆
                    </button>
                  )}
                </>
              )}
              {/* 一次建很多筆的工具收在這裡(字數一致);平常建一個商品只有右邊那一顆。沒有「商品建檔」的帳號兩顆都沒有 */}
              {canEdit && (
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
              )}
              {canEdit && (
                <button className="btn" onClick={() => setFindOpen(true)}>
                  新增商品
                </button>
              )}
            </>
          ) : (
            <button
              className="btn"
              onClick={startCreatingCategory}
            >
              新增類別
            </button>
          )
        }
      >
        <Tabs
          id="pc"
          label="商品"
          items={[
            { key: "products", label: "商品列表" },
            { key: "models", label: "分類瀏覽" },
            { key: "categories", label: "類別管理" },
          ]}
          value={leftTab}
          onChange={(k) => {
            setLeftTab(k);
            if (k === "models") setSelection(null);
          }}
        />
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

      <div className={selection ? "pc-layout" : "pc-layout list-only"}>
        <aside
          className="pc-master"
          style={{ gridTemplateRows: "1fr" }}
          role="tabpanel"
          id={`pc-panel-${leftTab}`}
          aria-labelledby={`pc-tab-${leftTab}`}
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
                placeholder="品名 / 條碼"
                autoFocus
              />
              <button className="btn" onClick={runProductSearch}>
                搜尋
              </button>
              {appliedProductQuery && (
                <button className="btn" onClick={clearProductSearch}>
                  清除
                </button>
              )}
            </div>
            <div className="pc-section-body" ref={listBody}>
              {productsResult.isLoading && (
                <div className="md-empty">
                  {isSearching ? "搜尋中…" : "載入中…"}
                </div>
              )}
              {productsResult.isError && (
                <div className="md-empty">
                  沒有讀到:{errorText(productsResult.error)}{" "}
                  <button type="button" className="btn" onClick={() => void productsTop.refetch()}>
                    重試
                  </button>
                </div>
              )}
              {productsCut && <div className="md-empty">{productsCut}</div>}
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
                            {fitsLine(p.related_hosts) && <div className="pl-fits">{fitsLine(p.related_hosts)}</div>}
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
            <CategoryBrowser
              initialAt={browseAt.current}
              onAt={(at) => {
                browseAt.current = at;
              }}
              selectedKey={selection?.kind === "model" ? selection.key : null}
              selectedProductId={selection?.kind === "product" ? selection.id : null}
              onPickModel={(key, name) => setSelection({ kind: "model", key, name })}
              onPickProduct={(id) => {
                setDetailTab("basic");
                setSelection({ kind: "product", id });
              }}
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
                placeholder="搜尋類別"
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
          <PaneBack open={!!selection} onClose={() => setSelection(null)} />
          {selection?.kind === "model" && (
            <ModelSkuPanel
              modelKey={selection.key}
              modelName={selection.name}
              onPickProduct={(id) => {
                setDetailTab("basic");
                setSelection({ kind: "product", id });
              }}
            />
          )}

          {selectedProduct && (
            <div className="pc-detail-body">
              <h3 className="pc-detail-title">{selectedProduct.name}</h3>
              <Tabs
                id="pcd"
                label={`${selectedProduct.name} 的資料`}
                className="pc-detail-tabs"
                items={[
                  { key: "basic", label: "基本" },
                  { key: "aliases", label: "別名" },
                ]}
                value={detailTab}
                onChange={setDetailTab}
              />
              <div role="tabpanel" id={`pcd-panel-${detailTab}`} aria-labelledby={`pcd-tab-${detailTab}`}>

              {detailTab === "basic" && (
                <>
                  <ProductPhotoStrip productId={selectedProduct.id} />
                  <dl>
                    <dt>品名</dt>
                    <dd>{selectedProduct.name}</dd>
                    {/* 全站檢視 D1:品號顯示(owner 2026-10-23「顯示」;05-18「自動產生的代碼不在畫面顯示」只有品號例外) */}
                    <dt>品號</dt>
                    <dd>{selectedProduct.sku}</dd>
                    <dt>規格</dt>
                    <dd>{selectedProduct.spec || "—"}</dd>
                    {(selectedProduct.related_hosts ?? []).length > 0 && (
                      <>
                        <dt>適用機型</dt>
                        <dd>{fitsLine(selectedProduct.related_hosts, 99).replace(/^適用 /, "")}</dd>
                      </>
                    )}
                    <dt>條碼</dt>
                    <dd>{selectedProduct.barcode || "—"}</dd>
                    <dt>容量 / 顏色</dt>
                    <dd>
                      {[
                        selectedProduct.capacity,
                        selectedProduct.color,
                      ]
                        .filter(Boolean)
                        .join(" / ") || "—"}
                    </dd>
                    <dt>類別</dt>
                    <dd>
                      {selectedProduct.category_name}
                    </dd>
                    <dt>售價</dt>
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
                    {canEdit && (
                      // 整頁編輯(SPEC-005):同一個分頁打開;要另開分頁的人按住 Cmd 點
                      <Link
                        className="btn primary"
                        to={`/products/${selectedProduct.id}/edit`}
                        state={{ listKey: location.key }}
                        onClick={() => saveListSnapshot(sessionStore(), location.key, listSnapshot())}
                      >
                        編輯
                      </Link>
                    )}
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
                  名稱 <span style={{ color: "var(--danger-text)" }}>*</span>
                </dt>
                <dd>
                  <input
                    value={catNew.name}
                    onChange={(e) =>
                      setCatNew((s) => ({ ...s, name: e.target.value }))
                    }
                    autoFocus
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
                <dt>
                  類型 <span style={{ color: "var(--danger-text)" }}>*</span>
                </dt>
                <dd>
                  <KindPicker value={catNew.kind} onChange={(kind) => setCatNew((s) => ({ ...s, kind }))} />
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
                類別 · {selectedCategory.name}
              </h3>
              {catError && <Banner kind="error" message={catError} />}
              {catSavedFlash && <Banner kind="success" message="已儲存" />}
              <dl>
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
                <dt>類型</dt>
                <dd>
                  <KindPicker value={catEdit.kind} onChange={(kind) => setCatEdit((s) => ({ ...s, kind }))} />
                </dd>
                {catEdit.kind === "accessory" && (
                  <>
                    <dt>配件共用</dt>
                    <dd>
                      <ChoiceGroup
                        label="配件共用"
                        value={catEdit.shares}
                        onChange={(shares) => setCatEdit((st) => ({ ...st, shares }))}
                        options={SHARE_OPTIONS.map((o) => ({ value: o.key, label: o.label }))}
                      />
                    </dd>
                  </>
                )}
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
              <CategoryBrandsEditor category={selectedCategory} />
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
            openPhoneWizard();
            return;
          }
          // 另開一個分頁建(SPEC-005):這一頁照樣能查庫存、看別的商品
          window.open(newProductUrl(prefill), "_blank");
        }}
      />
      {/* 看照片與規格的面板放在「先找有沒有建過」與商品表單後面:從那兩個地方點開時要疊在上面 */}
      {peek.panel}
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
        mode="accessory"
        open={accessoryExpanderOpen}
        onClose={() => setAccessoryExpanderOpen(false)}
        onSuccess={(count) => {
          setAccessoryExpanderOpen(false);
          setBulkResult(`多款展開:成功建立 ${count} 筆配件`);
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
/** 類別底下的品牌(中項):加(選現有的或打新名字)、拿掉、上下移。拿掉不動任何商品 */
function CategoryBrandsEditor({ category }: { category: Category }) {
  const brands = useBrands();
  const ops = useCategoryBrands();
  const [text, setText] = useState("");
  const [error, setError] = useState("");
  const list = category.brands ?? [];
  const busy = ops.add.isPending || ops.remove.isPending || ops.order.isPending;
  const title = category.kind === "device" ? "品牌" : "廠牌";

  async function run(job: () => Promise<unknown>) {
    setError("");
    try {
      await job();
    } catch (e) {
      setError(errorText(e));
    }
  }
  function add() {
    const name = text.trim();
    if (!name) return;
    const hit = (brands.data ?? []).find((b) => b.name.trim().toLowerCase() === name.toLowerCase());
    void run(async () => {
      await ops.add.mutateAsync(hit ? { category: category.id, brand: hit.id } : { category: category.id, name });
      setText("");
    });
  }
  function move(i: number, d: number) {
    const ids = list.map((b) => b.id);
    const j = i + d;
    if (j < 0 || j >= ids.length) return;
    [ids[i], ids[j]] = [ids[j], ids[i]];
    void run(() => ops.order.mutateAsync({ category: category.id, brands: ids }));
  }

  return (
    <div className="cb-editor">
      <h4>
        {title} {list.length}
      </h4>
      {error && <Banner kind="error" message={error} />}
      <div className="cb-add">
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") add();
          }}
          list={`cb-brands-${category.id}`}
          placeholder={`${title}名稱`}
          disabled={busy}
        />
        <datalist id={`cb-brands-${category.id}`}>
          {(brands.data ?? []).map((b) => (
            <option key={b.id} value={b.name} />
          ))}
        </datalist>
        <button type="button" className="btn" onClick={add} disabled={busy || !text.trim()}>
          加入
        </button>
      </div>
      {list.length === 0 ? (
        <div className="md-empty">還沒有{title}</div>
      ) : (
        <table className="pc-list-table">
          <tbody>
            {list.map((b, i) => (
              <tr key={b.id}>
                <td>{b.name}</td>
                <td className="cb-row-btns">
                  <button type="button" className="btn" disabled={busy || i === 0} onClick={() => move(i, -1)} aria-label="往上">
                    ↑
                  </button>
                  <button
                    type="button"
                    className="btn"
                    disabled={busy || i === list.length - 1}
                    onClick={() => move(i, 1)}
                    aria-label="往下"
                  >
                    ↓
                  </button>
                  <button
                    type="button"
                    className="btn"
                    disabled={busy}
                    onClick={() => void run(() => ops.remove.mutateAsync({ category: category.id, brand: b.id }))}
                  >
                    拿掉
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

interface TreeAt {
  category?: { id: number; name: string; kind: CategoryKind };
  mode: "phone" | "maker";
  brand?: { id: string; name: string };
  model?: { id: string; name: string };
}

/** 分類瀏覽:類別 → 品牌(中項)→ 型號 → 商品(owner 2026-10-16;規則在 backend/apps/catalog/tree.py)。
 *  主機的型號點下去右邊列容量顏色品況;配件可切「依手機」(手機品牌 → 機型 → 照配件廠牌分組)/「依廠牌」 */
function CategoryBrowser({
  initialAt,
  onAt,
  selectedKey,
  selectedProductId,
  onPickModel,
  onPickProduct,
}: {
  /** 編輯完回來:走回原來那一層(全站檢視 R07) */
  initialAt?: TreeAt;
  onAt?: (at: TreeAt) => void;
  selectedKey: string | null;
  selectedProductId: number | null;
  onPickModel: (key: string, name: string) => void;
  onPickProduct: (id: number) => void;
}) {
  const [at, setAtState] = useState<TreeAt>(initialAt ?? { mode: "phone" });
  function setAt(next: TreeAt) {
    setAtState(next);
    onAt?.(next);
  }
  const cat = at.category;
  const mode = cat?.kind === "accessory" ? at.mode : cat?.kind === "general" ? "maker" : undefined;
  const level = useCategoryTree({
    category: cat?.id,
    mode,
    brand: at.brand?.id,
    model: at.model?.id,
  });
  const data = level.data;
  const crumbs: { label: string; go: TreeAt }[] = [{ label: "全部類別", go: { mode: at.mode } }];
  if (cat) crumbs.push({ label: cat.name, go: { mode: at.mode, category: cat } });
  if (cat && at.brand) crumbs.push({ label: at.brand.name, go: { mode: at.mode, category: cat, brand: at.brand } });
  if (cat && at.brand && at.model) crumbs.push({ label: at.model.name, go: at });
  const unit = cat?.kind === "device" ? "型號" : "個";

  const productRow = (p: TreeProduct, showMaker: boolean) => (
    <tr key={p.id} onClick={() => onPickProduct(p.id)} className={selectedProductId === p.id ? "selected" : ""}>
      <td>
        <div>{p.name}</div>
        <div className="cb-dim">
          {[showMaker ? p.maker : "", p.fits.length ? `適用 ${p.fits.slice(0, 3).join("、")}${p.fits.length > 3 ? "…" : ""}` : ""]
            .filter(Boolean)
            .join(" · ")}
        </div>
      </td>
      <td className="num" style={{ width: 50 }}>
        {p.stock_qty}
      </td>
    </tr>
  );

  return (
    <section className="pc-section">
      <div className="pc-section-header">分類</div>
      <div className="cb-crumbs">
        {crumbs.map((c, i) => (
          <span key={i}>
            {i > 0 && " › "}
            {i < crumbs.length - 1 ? (
              <button type="button" className="cb-crumb" onClick={() => setAt(c.go)}>
                {c.label}
              </button>
            ) : (
              <b>{c.label}</b>
            )}
          </span>
        ))}
      </div>
      {cat?.kind === "accessory" && (
        <div className="mb-groups">
          <SegmentedControl
            label="配件怎麼找"
            value={at.mode}
            onChange={(m) => setAt({ mode: m, category: cat })}
            options={[
              { value: "phone", label: "依手機" },
              { value: "maker", label: "依廠牌" },
            ]}
          />
        </div>
      )}
      <div className="pc-section-body">
        {level.isLoading && <div className="md-empty">載入中…</div>}
        {level.isError && <Banner kind="error" message={level.error instanceof Error ? level.error.message : "讀不到"} />}
        {data?.level === "categories" && (
          <table className="pc-list-table">
            <tbody>
              {data.items.map((c) => (
                <tr key={c.id} onClick={() => setAt({ mode: "phone", category: { id: c.id, name: c.name, kind: c.kind } })}>
                  <td>{c.name}</td>
                  <td className="num" style={{ width: 80 }}>
                    {c.count} 個
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {data?.level === "brands" &&
          (data.items.length === 0 ? (
            <div className="md-empty">這個類別還沒有商品</div>
          ) : (
            <table className="pc-list-table">
              <tbody>
                {data.items.map((b) => (
                  <tr key={String(b.id)} onClick={() => setAt({ ...at, brand: { id: String(b.id), name: b.name }, model: undefined })}>
                    <td>{b.name}</td>
                    <td className="num" style={{ width: 80 }}>
                      {b.count} {data.mode === "phone" ? "個" : unit}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ))}
        {data?.level === "models" &&
          (data.items.length === 0 ? (
            <div className="md-empty">沒有型號</div>
          ) : (
            <table className="pc-list-table">
              <tbody>
                {data.items.map((m) =>
                  data.mode === "phone" ? (
                    <tr key={String(m.id)} onClick={() => setAt({ ...at, model: { id: String(m.id), name: m.name } })}>
                      <td>{m.name}</td>
                      <td className="num" style={{ width: 80 }}>
                        {m.count} 個
                      </td>
                    </tr>
                  ) : (
                    <tr
                      key={m.key || `p${m.product_id}`}
                      onClick={() => (m.key ? onPickModel(m.key, m.name) : m.product_id && onPickProduct(m.product_id))}
                      className={(m.key && selectedKey === m.key) || (m.product_id && selectedProductId === m.product_id) ? "selected" : ""}
                    >
                      <td>{m.name}</td>
                      <td className="num" style={{ width: 60 }}>
                        {m.sku_count} 款
                      </td>
                      <td className="num" style={{ width: 50 }}>
                        {m.stock_qty}
                      </td>
                    </tr>
                  ),
                )}
              </tbody>
            </table>
          ))}
        {data?.level === "products" && (
          <>
            {data.total > 500 && <div className="cb-dim cb-note">只列前 500 個,其他請用搜尋</div>}
            {data.total === 0 && <div className="md-empty">沒有商品</div>}
            {data.grouped
              ? data.items.map((g) => (
                  <div key={g.maker}>
                    <div className="mb-brand-label">{g.maker}</div>
                    <table className="pc-list-table">
                      <tbody>{g.products.map((p) => productRow(p, false))}</tbody>
                    </table>
                  </div>
                ))
              : (
                <table className="pc-list-table">
                  <tbody>{data.items.map((p) => productRow(p, false))}</tbody>
                </table>
              )}
          </>
        )}
      </div>
    </section>
  );
}

// ─── 機型展開:右側顯示底下 SKU,按「全新 / 已拆封 / 中古」分組並排 ───
function ModelSkuPanel({
  modelKey,
  modelName,
  onPickProduct,
}: {
  modelKey: string;
  modelName: string;
  onPickProduct: (id: number) => void;
}) {
  const groups = useProductsByPhoneModel(modelKey);
  const data = groups.data ?? [];
  return (
    <div className="pc-detail-body">
      <h3 className="pc-detail-title">{modelName}</h3>
      {groups.isLoading && <div className="md-empty">載入中…</div>}
      {/* 讀不到不能寫成「還沒有商品」(像真的沒建) */}
      {groups.isError && (
        <div className="md-empty">
          沒有讀到{" "}
          <button type="button" className="btn" onClick={() => groups.refetch()}>
            重試
          </button>
        </div>
      )}
      {groups.isSuccess && data.length === 0 && (
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
                <tr key={s.id} onClick={() => onPickProduct(s.id)}>
                  <td>
                    {s.capacity} {s.color}
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

/** 這個分頁的暫存(瀏覽器不給用就當沒有) */
function sessionStore(): Storage | null {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}
