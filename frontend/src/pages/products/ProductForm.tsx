import { FormEvent, useEffect, useRef, useState } from "react";

import { ApiHttpError } from "@/api/client";
import {
  useBrands,
  usePhoneSeriesList,
  useSaveBrand,
  useSaveCategory,
  useSavePhoneSeries,
  useSaveProduct,
} from "@/api/hooks";
import { searchCategories } from "@/api/search";
import type {
  AccessoryType,
  Brand,
  Category,
  LifecycleStatus,
  PhoneSeries,
  Product,
  WarehouseType,
} from "@/api/types";
import { PhoneModelPicker } from "@/components/PhoneModelPicker";
import { Banner } from "@/components/Banner";
import { ComboBox, ComboOption } from "@/components/ComboBox";
import { Drawer } from "@/components/Drawer";
import { Checkbox, Field } from "@/components/Field";
import { useModalDraft } from "@/hooks/useModalDraft";

/** 比對兩個 form state 是否不同(用於 dirty 判斷) */
function isDirtyAgainst<T extends object>(state: T, baseline: T): boolean {
  const keys = Object.keys(baseline) as (keyof T)[];
  for (const k of keys) {
    const a = state[k];
    const b = baseline[k];
    if (Array.isArray(a) && Array.isArray(b)) {
      if (a.length !== b.length) return true;
      for (let i = 0; i < a.length; i++) {
        if (JSON.stringify(a[i]) !== JSON.stringify(b[i])) return true;
      }
      continue;
    }
    if (a !== b) return true;
  }
  return false;
}

interface ProductFormProps {
  open: boolean;
  initial?: Product | null;
  onClose: () => void;
  onSaved?: (p: Product) => void;
}

interface FormState {
  category: number | "";
  name: string;
  spec: string;
  barcode: string;
  list_price: string;
  requires_serial: boolean;
  allows_telecom_line: boolean;
  allows_commission: boolean;
  is_virtual: boolean;
  is_secondhand: boolean;
  counts_cash: boolean;
  counts_margin: boolean;
  safety_stock: string;
  lifecycle_status: LifecycleStatus;
  accessory_type: AccessoryType;
  attach_rate: string;
  replenish_days: string;
  brand: number | "";
  series: number | "";
  generation: string; // 字串方便輸入,送出時 parseInt
  model_suffix: string;
  is_variant: boolean;
  related_models: {
    model_key: string;
    model_name: string;
    lifecycle_status?: LifecycleStatus | "";
  }[];
  warehouse_type: WarehouseType;
  is_externally_sellable: boolean;
  external_sale_price: string;
  min_sale_price: string;
  is_active: boolean;
}

const EMPTY: FormState = {
  category: "",
  name: "",
  spec: "",
  barcode: "",
  list_price: "0",
  requires_serial: true,
  allows_telecom_line: false,
  allows_commission: false,
  is_virtual: false,
  is_secondhand: false,
  counts_cash: true,
  counts_margin: true,
  safety_stock: "0",
  lifecycle_status: "active",
  // 預設「機型配件」(spec 要求)
  accessory_type: "phone_specific",
  attach_rate: "0.30",
  replenish_days: "14",
  brand: "",
  series: "",
  generation: "",
  model_suffix: "",
  is_variant: false,
  related_models: [],
  warehouse_type: "product",
  is_externally_sellable: false,
  external_sale_price: "0",
  min_sale_price: "0",
  is_active: true,
};

function toState(p: Product | null | undefined): FormState {
  if (!p) return { ...EMPTY };
  return {
    category: p.category,
    name: p.name,
    spec: p.spec,
    barcode: p.barcode,
    list_price: p.list_price,
    requires_serial: p.requires_serial,
    allows_telecom_line: p.allows_telecom_line,
    allows_commission: p.allows_commission,
    is_virtual: p.is_virtual,
    is_secondhand: p.is_secondhand,
    counts_cash: p.counts_cash,
    counts_margin: p.counts_margin,
    safety_stock: String(p.safety_stock ?? 0),
    lifecycle_status: p.lifecycle_status ?? "active",
    accessory_type: p.accessory_type ?? "none",
    attach_rate: p.attach_rate ?? "0.30",
    replenish_days: String(p.replenish_days ?? 14),
    brand: p.brand ?? "",
    series: p.series ?? "",
    generation: p.generation != null ? String(p.generation) : "",
    model_suffix: p.model_suffix ?? "",
    is_variant: p.is_variant ?? false,
    related_models: (p.related_hosts ?? []).map((h) => ({
      model_key: h.model_key,
      model_name: h.model_name,
      lifecycle_status: h.lifecycle_status,
    })),
    warehouse_type: p.warehouse_type ?? "product",
    is_externally_sellable: p.is_externally_sellable ?? false,
    external_sale_price: p.external_sale_price ?? "0",
    min_sale_price: p.min_sale_price ?? "0",
    is_active: p.is_active,
  };
}

const DRAFT_KEY = "modal-draft:product-form-new";

/** 即時拼出機型名稱(讓店員一邊填一邊看效果) */
function previewPhoneModelName(
  s: FormState,
  _brands?: Brand[],
  series?: PhoneSeries[],
): string {
  if (!s.series) return "";
  const ser = (series ?? []).find((x) => x.id === s.series);
  if (!ser) return "";
  const parts: string[] = [ser.name];
  if (s.generation.trim()) parts.push(s.generation.trim());
  if (s.model_suffix.trim()) parts.push(s.model_suffix.trim());
  let out = parts[0];
  for (let i = 1; i < parts.length; i++) {
    const p = parts[i];
    if (!p) continue;
    if (p[0] === "+" || p[0] === "/") out += p;
    else out += " " + p;
  }
  return out;
}

export function ProductForm({
  open,
  initial,
  onClose,
  onSaved,
}: ProductFormProps) {
  const [state, setState] = useState<FormState>(toState(initial));
  const [categoryOption, setCategoryOption] =
    useState<ComboOption<Category> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string[]>>({});
  const [showNewCategory, setShowNewCategory] = useState(false);
  const [newCategory, setNewCategory] = useState({
    code: "",
    name: "",
    sort_order: "",
  });
  const [closePromptOpen, setClosePromptOpen] = useState(false);
  const baselineRef = useRef<FormState>(toState(initial));

  // 草稿系統共用 hook
  const isEdit = !!initial?.id;
  const draftHelper = useModalDraft<FormState>({
    key: DRAFT_KEY,
    open,
    state,
    isEditMode: isEdit,
    isEmpty: (s) => !isDirtyAgainst(s, baselineRef.current),
  });

  const saveProduct = useSaveProduct();
  const saveCategory = useSaveCategory();
  // Phase 1: Brand / Series master
  const brands = useBrands();
  const phoneSeries = usePhoneSeriesList(
    typeof state.brand === "number" ? state.brand : null,
  );
  const saveBrand = useSaveBrand();
  const savePhoneSeries = useSavePhoneSeries();
  const [showNewBrand, setShowNewBrand] = useState(false);
  const [newBrandName, setNewBrandName] = useState("");
  const [showNewSeries, setShowNewSeries] = useState(false);
  const [newSeriesName, setNewSeriesName] = useState("");
  // 紀錄使用者是否手動改過世代序號;改過就不再從品名自動帶
  const genTouchedRef = useRef(false);

  useEffect(() => {
    if (open) {
      const base = toState(initial);
      setState(base);
      baselineRef.current = base;
      setCategoryOption(
        initial?.category
          ? {
              id: initial.category,
              label: initial.category_name,
              secondary: initial.category_code,
            }
          : null,
      );
      setError(null);
      setFieldErrors({});
      setShowNewCategory(false);
      setNewCategory({ code: "", name: "", sort_order: "" });
      setClosePromptOpen(false);
      genTouchedRef.current = !!initial?.generation;
    }
  }, [open, initial]);

  // 主機:品名變動時,若使用者未手動改 generation,自動從品名末碼擷取數字
  useEffect(() => {
    if (state.accessory_type !== "none") return;
    if (genTouchedRef.current) return;
    const m = state.name.match(/(\d+)\s*$/);
    if (m) {
      setState((s) => ({ ...s, generation: m[1] }));
    }
  }, [state.name, state.accessory_type]);

  // 草稿系統的 debounce / beforeunload / unmount 都由 useModalDraft 處理

  function patch<K extends keyof FormState>(k: K, v: FormState[K]) {
    setState((s) => ({ ...s, [k]: v }));
  }

  async function handleCreateCategory() {
    if (!newCategory.code || !newCategory.name) return;
    try {
      const payload: Partial<Category> = {
        code: newCategory.code,
        name: newCategory.name,
      };
      const sortOrderNum = Number(newCategory.sort_order);
      if (Number.isFinite(sortOrderNum) && sortOrderNum > 0) {
        payload.sort_order = sortOrderNum;
      }
      const c = await saveCategory.mutateAsync(payload);
      patch("category", c.id);
      setCategoryOption({ id: c.id, label: c.name, secondary: c.code });
      setShowNewCategory(false);
      setNewCategory({ code: "", name: "", sort_order: "" });
    } catch (e) {
      if (e instanceof ApiHttpError) {
        const body = e.body as Record<string, string[]>;
        setError("建立類別失敗:" + JSON.stringify(body));
      }
    }
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setFieldErrors({});
    if (!state.category) {
      setFieldErrors({ category: ["請選類別"] });
      return;
    }
    if (!state.name) {
      setFieldErrors({ name: ["請填品名"] });
      return;
    }
    try {
      const saved = await saveProduct.mutateAsync({
        id: initial?.id,
        category: state.category as number,
        name: state.name,
        spec: state.spec,
        barcode: state.barcode,
        list_price: state.list_price,
        requires_serial: state.requires_serial,
        allows_telecom_line: state.allows_telecom_line,
        allows_commission: state.allows_commission,
        is_virtual: state.is_virtual,
        is_secondhand: state.is_secondhand,
        counts_cash: state.counts_cash,
        counts_margin: state.counts_margin,
        safety_stock: Number(state.safety_stock) || 0,
        lifecycle_status: state.lifecycle_status,
        accessory_type: state.accessory_type,
        attach_rate: state.attach_rate || "0",
        replenish_days: Number(state.replenish_days) || 0,
        brand: state.brand || null,
        series: state.series || null,
        generation: state.generation ? Number(state.generation) : null,
        model_suffix: state.model_suffix,
        is_variant: state.is_variant,
        related_host_keys: state.related_models.map((m) => m.model_key),
        warehouse_type: state.warehouse_type,
        is_externally_sellable: state.is_externally_sellable,
        external_sale_price: state.external_sale_price || "0",
        min_sale_price: state.min_sale_price || "0",
        is_active: state.is_active,
      });
      // 儲存成功 → 清掉草稿 + 阻止 unmount flush 再寫回
      if (!isEdit) draftHelper.markSavedAndClear();
      onSaved?.(saved);
      onClose();
    } catch (e) {
      if (e instanceof ApiHttpError && e.body && typeof e.body === "object") {
        const body = e.body as Record<string, string[] | string>;
        const fe: Record<string, string[]> = {};
        let detail: string | null = null;
        for (const [k, v] of Object.entries(body)) {
          if (k === "detail") {
            detail = String(v);
          } else {
            fe[k] = Array.isArray(v) ? v : [String(v)];
          }
        }
        setFieldErrors(fe);
        if (detail) setError(detail);
      } else {
        setError(String(e));
      }
    }
  }

  function handleClose() {
    // 沒任何變更 → 直接關,不提示
    if (!isDirtyAgainst(state, baselineRef.current)) {
      onClose();
      return;
    }
    setClosePromptOpen(true);
  }

  function saveDraftAndClose() {
    // hook 已經有 debounce + unmount flush,這裡讓 unmount flush 自然發生即可
    setClosePromptOpen(false);
    onClose();
  }

  function discardAndClose() {
    setClosePromptOpen(false);
    draftHelper.markSavedAndClear();
    onClose();
  }

  function loadDraft() {
    if (!draftHelper.draft) return;
    setState(draftHelper.draft.state);
    draftHelper.consumeDraft();
  }

  function discardDraft() {
    draftHelper.discardDraft();
  }

  return (
    <Drawer
      open={open}
      title={isEdit ? `編輯商品 ${initial?.name}` : "新增商品"}
      onClose={handleClose}
      lockBackdrop
      footer={
        <>
          <button className="btn" onClick={handleClose} type="button">
            取消
          </button>
          <button
            className="btn primary"
            onClick={submit}
            type="button"
            disabled={saveProduct.isPending}
          >
            {saveProduct.isPending ? "儲存中…" : "儲存"}
          </button>
        </>
      }
    >
      {error && <Banner kind="error" message={error} />}
      {draftHelper.draft && !isEdit && (
        <div className="pf-draft-banner">
          <span>
            上次有未完成的草稿(
            {new Date(draftHelper.draft.savedAt).toLocaleString()})
          </span>
          <div className="pf-draft-actions">
            <button type="button" className="btn" onClick={discardDraft}>
              捨棄草稿
            </button>
            <button
              type="button"
              className="btn primary"
              onClick={loadDraft}
            >
              載入草稿
            </button>
          </div>
        </div>
      )}
      {closePromptOpen && (
        <div
          className="pf-close-prompt"
          onClick={(e) => e.stopPropagation()}
        >
          <div className="pf-close-prompt-title">關閉前處理未儲存資料</div>
          <div className="pf-close-prompt-msg">
            目前已輸入的內容尚未儲存,請選擇處理方式:
          </div>
          <div className="pf-close-prompt-actions">
            <button
              type="button"
              className="btn"
              onClick={() => setClosePromptOpen(false)}
            >
              繼續編輯
            </button>
            <button
              type="button"
              className="btn danger"
              onClick={discardAndClose}
            >
              捨棄,離開
            </button>
            {!isEdit && (
              <button
                type="button"
                className="btn primary"
                onClick={saveDraftAndClose}
              >
                儲存草稿,離開
              </button>
            )}
          </div>
        </div>
      )}
      <form onSubmit={submit} className="pf-compact">
        <Field
          label="倉別"
          required
          hint="商品倉=銷貨用,零件倉=維修用(隱藏建議售價;可選擇對外調貨同行)"
        >
          <div className="pf-tabs">
            <button
              type="button"
              className={`pf-tab${state.warehouse_type === "product" ? " active" : ""}`}
              onClick={() =>
                patch("warehouse_type", "product" as WarehouseType)
              }
            >
              商品倉
              <span className="pf-tab-sub">銷貨用</span>
            </button>
            <button
              type="button"
              className={`pf-tab${state.warehouse_type === "parts" ? " active" : ""}`}
              onClick={() => patch("warehouse_type", "parts" as WarehouseType)}
            >
              零件倉
              <span className="pf-tab-sub">維修用</span>
            </button>
          </div>
        </Field>

        <Field label="品名" required error={fieldErrors.name}>
          <input
            value={state.name}
            onChange={(e) => patch("name", e.target.value)}
          />
        </Field>

        {state.warehouse_type === "parts" && (
          <>
            <div className="fieldset">
              <legend>零件選項</legend>
              <Checkbox
                checked={state.is_externally_sellable}
                onChange={(v) => patch("is_externally_sellable", v)}
                label="可對外銷售(調貨給同行)"
                hint="開啟後此零件可被銷貨單搜尋到,異動標記為「零件調貨」"
              />
              {state.is_externally_sellable && (
                <div className="field-row">
                  <Field
                    label="對外售價"
                    hint="銷貨時自動帶入"
                  >
                    <input
                      type="number"
                      step="1"
                      min="0"
                      value={state.external_sale_price}
                      onChange={(e) =>
                        patch("external_sale_price", e.target.value)
                      }
                    />
                  </Field>
                  <Field
                    label="最低售價"
                    hint="防呆下限,銷貨手動調整不可低於此值"
                  >
                    <input
                      type="number"
                      step="1"
                      min="0"
                      value={state.min_sale_price}
                      onChange={(e) =>
                        patch("min_sale_price", e.target.value)
                      }
                    />
                  </Field>
                </div>
              )}
            </div>
          </>
        )}

        {state.warehouse_type === "product" && (
        <>
        <Field
          label="商品性質"
          required
          error={fieldErrors.accessory_type}
          hint="決定後續欄位顯示;選錯會影響庫存警示推論"
        >
          <div className="pf-tabs">
            <button
              type="button"
              className={`pf-tab${state.accessory_type === "none" ? " active" : ""}`}
              onClick={() => patch("accessory_type", "none" as AccessoryType)}
            >
              主機
              <span className="pf-tab-sub">手機 / 平板本體</span>
            </button>
            <button
              type="button"
              className={`pf-tab${state.accessory_type === "phone_specific" ? " active" : ""}`}
              onClick={() =>
                patch("accessory_type", "phone_specific" as AccessoryType)
              }
            >
              機型配件
              <span className="pf-tab-sub">手機殼 / 保護貼</span>
            </button>
            <button
              type="button"
              className={`pf-tab${state.accessory_type === "universal" ? " active" : ""}`}
              onClick={() =>
                patch("accessory_type", "universal" as AccessoryType)
              }
            >
              通用配件
              <span className="pf-tab-sub">充電線 / 耳機</span>
            </button>
          </div>
        </Field>

        {state.accessory_type === "none" && (
          <div className="fieldset">
            <legend>主機資訊</legend>
            <div className="field-row">
              <Field label="品牌" required error={fieldErrors.brand}>
                <div style={{ display: "flex", gap: 6 }}>
                  <select
                    style={{ flex: 1 }}
                    value={state.brand}
                    onChange={(e) => {
                      const v = e.target.value ? Number(e.target.value) : "";
                      patch("brand", v);
                      // 換品牌就清空系列
                      if (v !== state.brand) patch("series", "");
                    }}
                  >
                    <option value="">請選擇品牌</option>
                    {(brands.data ?? []).map((b: Brand) => (
                      <option key={b.id} value={b.id}>
                        {b.name}
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    className="btn"
                    onClick={() => {
                      setNewBrandName("");
                      setShowNewBrand(true);
                    }}
                    title="新增品牌主檔"
                  >
                    + 新增
                  </button>
                </div>
              </Field>
              <Field
                label="產品系列"
                required
                error={fieldErrors.series}
                hint={
                  state.brand
                    ? "從此品牌的系列主檔挑;找不到可按右側新增"
                    : "請先選品牌"
                }
              >
                <div style={{ display: "flex", gap: 6 }}>
                  <select
                    style={{ flex: 1 }}
                    value={state.series}
                    disabled={!state.brand}
                    onChange={(e) =>
                      patch(
                        "series",
                        e.target.value ? Number(e.target.value) : "",
                      )
                    }
                  >
                    <option value="">請選擇系列</option>
                    {(phoneSeries.data ?? []).map((s: PhoneSeries) => (
                      <option key={s.id} value={s.id}>
                        {s.name}
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    className="btn"
                    disabled={!state.brand}
                    onClick={() => {
                      setNewSeriesName("");
                      setShowNewSeries(true);
                    }}
                    title="新增此品牌的系列"
                  >
                    + 新增
                  </button>
                </div>
              </Field>
            </div>
            <div className="field-row">
              <Field
                label="世代序號"
                error={fieldErrors.generation}
                hint={
                  genTouchedRef.current
                    ? "已手動修正"
                    : "同系列第幾代;例:iPhone 15 → 15"
                }
              >
                <input
                  type="number"
                  step="1"
                  min="0"
                  value={state.generation}
                  onChange={(e) => {
                    genTouchedRef.current = true;
                    patch("generation", e.target.value);
                  }}
                />
              </Field>
              <Field
                label="型號後綴(選填)"
                hint="例:Pro / Pro Max / Plus / Ultra / +;留空 = 標準款"
              >
                <input
                  value={state.model_suffix}
                  onChange={(e) => patch("model_suffix", e.target.value)}
                  placeholder="Pro Max"
                />
              </Field>
              <Field label="拼出機型名稱">
                <input
                  value={previewPhoneModelName(state, brands.data, phoneSeries.data)}
                  readOnly
                  style={{ background: "var(--bg-2)", color: "var(--text-dim)" }}
                />
              </Field>
            </div>
            <Checkbox
              checked={state.is_variant}
              onChange={(v) => patch("is_variant", v)}
              label="規格變體"
              hint="勾選代表此為同代不同容量/顏色的變體,不觸發換代判斷邏輯"
            />

            {showNewBrand && (
              <div className="pf-inline-modal">
                <div className="pf-inline-modal-title">新增品牌</div>
                <div className="pf-inline-modal-body">
                  <input
                    autoFocus
                    placeholder="例:Asus / Nokia / Honor"
                    value={newBrandName}
                    onChange={(e) => setNewBrandName(e.target.value)}
                  />
                  <button
                    type="button"
                    className="btn"
                    onClick={() => setShowNewBrand(false)}
                  >
                    取消
                  </button>
                  <button
                    type="button"
                    className="btn primary"
                    disabled={!newBrandName.trim() || saveBrand.isPending}
                    onClick={async () => {
                      const name = newBrandName.trim();
                      const code = name
                        .toLowerCase()
                        .replace(/\s+/g, "-")
                        .replace(/[^a-z0-9\-]/g, "")
                        .slice(0, 20) || `brand-${Date.now()}`;
                      try {
                        const b = await saveBrand.mutateAsync({
                          code,
                          name,
                          sort_order: 99,
                          is_active: true,
                        });
                        patch("brand", b.id);
                        patch("series", "");
                        setShowNewBrand(false);
                      } catch (e) {
                        alert(
                          e instanceof Error ? e.message : String(e),
                        );
                      }
                    }}
                  >
                    {saveBrand.isPending ? "建立中…" : "建立"}
                  </button>
                </div>
              </div>
            )}
            {showNewSeries && state.brand && (
              <div className="pf-inline-modal">
                <div className="pf-inline-modal-title">
                  新增系列
                  <span style={{ color: "var(--text-dim)", fontSize: 12, marginLeft: 8 }}>
                    (
                    {(brands.data ?? []).find((b) => b.id === state.brand)?.name}
                    )
                  </span>
                </div>
                <div className="pf-inline-modal-body">
                  <input
                    autoFocus
                    placeholder="例:Galaxy S / iPhone / Redmi Note"
                    value={newSeriesName}
                    onChange={(e) => setNewSeriesName(e.target.value)}
                  />
                  <button
                    type="button"
                    className="btn"
                    onClick={() => setShowNewSeries(false)}
                  >
                    取消
                  </button>
                  <button
                    type="button"
                    className="btn primary"
                    disabled={
                      !newSeriesName.trim() || savePhoneSeries.isPending
                    }
                    onClick={async () => {
                      const name = newSeriesName.trim();
                      const code = name
                        .toLowerCase()
                        .replace(/\s+/g, "-")
                        .replace(/[^a-z0-9\-]/g, "")
                        .slice(0, 20) || `series-${Date.now()}`;
                      try {
                        const s = await savePhoneSeries.mutateAsync({
                          brand: state.brand as number,
                          code,
                          name,
                          sort_order: 99,
                          is_active: true,
                        });
                        patch("series", s.id);
                        setShowNewSeries(false);
                      } catch (e) {
                        alert(
                          e instanceof Error ? e.message : String(e),
                        );
                      }
                    }}
                  >
                    {savePhoneSeries.isPending ? "建立中…" : "建立"}
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
        </>
        )}

        <Field label="類別" required error={fieldErrors.category}>
          <div style={{ display: "flex", gap: 6 }}>
            <div style={{ flex: 1 }}>
              <ComboBox<Category>
                value={state.category}
                selectedOption={categoryOption}
                onChange={(id, opt) => {
                  patch("category", id);
                  setCategoryOption(opt ?? null);
                }}
                fetchOptions={searchCategories}
                placeholder="搜尋類別(代碼/名稱)"
              />
            </div>
            <button
              type="button"
              className="btn"
              onClick={() => setShowNewCategory((v) => !v)}
            >
              {showNewCategory ? "取消" : "+ 新類別"}
            </button>
          </div>
        </Field>

        {showNewCategory && (
          <div className="fieldset">
            <legend>新增類別</legend>
            <div className="field-row">
              <Field label="類別代碼">
                <input
                  value={newCategory.code}
                  onChange={(e) =>
                    setNewCategory((s) => ({
                      ...s,
                      code: e.target.value.toUpperCase(),
                    }))
                  }
                  maxLength={8}
                />
              </Field>
              <Field label="類別名稱">
                <input
                  value={newCategory.name}
                  onChange={(e) =>
                    setNewCategory((s) => ({ ...s, name: e.target.value }))
                  }
                />
              </Field>
              <Field label="排序(留空自動)">
                <input
                  type="number"
                  step="1"
                  value={newCategory.sort_order}
                  onChange={(e) =>
                    setNewCategory((s) => ({
                      ...s,
                      sort_order: e.target.value,
                    }))
                  }
                  placeholder="自動"
                />
              </Field>
            </div>
            <button
              type="button"
              className="btn primary"
              onClick={handleCreateCategory}
              disabled={saveCategory.isPending}
            >
              建立並選用
            </button>
          </div>
        )}

        {state.warehouse_type === "product" &&
          state.accessory_type === "phone_specific" && (
          <Field
            label="相容機型"
            hint="綁定後,查詢該機型庫存時此配件將自動列出,並納入安全庫存動態計算。同款不同容量/顏色/中古機等變體 SKU 全部涵蓋。"
          >
            <PhoneModelPicker
              placeholder={
                state.related_models.length === 0
                  ? "搜尋機型名稱…"
                  : "繼續加機型…"
              }
              onPick={(m) => {
                if (
                  state.related_models.some((x) => x.model_key === m.model_key)
                )
                  return;
                patch("related_models", [
                  ...state.related_models,
                  {
                    model_key: m.model_key,
                    model_name: m.model_name,
                    lifecycle_status:
                      m.any_lifecycle_status as LifecycleStatus,
                  },
                ]);
              }}
            />
            {state.related_models.length > 0 && (
              <div
                className="inv-chip-row"
                style={{
                  padding: "6px 0 0",
                  background: "transparent",
                  border: 0,
                }}
              >
                {state.related_models.map((m) => (
                  <button
                    key={m.model_key}
                    type="button"
                    className="inv-chip"
                    onClick={() =>
                      patch(
                        "related_models",
                        state.related_models.filter(
                          (x) => x.model_key !== m.model_key,
                        ),
                      )
                    }
                    title="點擊移除"
                  >
                    <span>
                      {m.model_name}
                      {m.lifecycle_status &&
                        m.lifecycle_status !== "active" && (
                          <span className="pf-chip-status">
                            {" "}
                            ·{" "}
                            {m.lifecycle_status === "replacing"
                              ? "即將換代"
                              : m.lifecycle_status === "discontinued"
                                ? "停產下架"
                                : "清倉處理"}
                          </span>
                        )}
                    </span>
                    <span className="inv-chip-x">×</span>
                  </button>
                ))}
              </div>
            )}
          </Field>
        )}

        <Field label="規格" error={fieldErrors.spec}>
          <input
            value={state.spec}
            onChange={(e) => patch("spec", e.target.value)}
          />
        </Field>

        <div className="field-row">
          <Field label="條碼" error={fieldErrors.barcode}>
            <input
              value={state.barcode}
              onChange={(e) => patch("barcode", e.target.value)}
            />
          </Field>
          {state.warehouse_type === "product" && (
            <Field label="建議零售價" error={fieldErrors.list_price}>
              <input
                type="number"
                step="1"
                value={state.list_price}
                onChange={(e) => patch("list_price", e.target.value)}
              />
            </Field>
          )}
          <Field
            label="安全庫存"
            error={fieldErrors.safety_stock}
            hint={
              state.lifecycle_status === "discontinued" ||
              state.lifecycle_status === "clearance"
                ? "停產 / 清倉商品不觸發補貨警示"
                : "跨倉總量低於此數,首頁會跳警示;0 = 不提醒"
            }
          >
            <input
              type="number"
              step="1"
              min="0"
              value={state.safety_stock}
              onChange={(e) => patch("safety_stock", e.target.value)}
              disabled={
                state.lifecycle_status === "discontinued" ||
                state.lifecycle_status === "clearance"
              }
            />
          </Field>
        </div>

        <Field
          label="商品狀態"
          error={fieldErrors.lifecycle_status}
          hint="決定庫存警示行為(停產 / 清倉不觸發補貨警示)"
        >
          <select
            value={state.lifecycle_status}
            onChange={(e) =>
              patch("lifecycle_status", e.target.value as LifecycleStatus)
            }
          >
            <option value="active">主力現貨</option>
            <option value="replacing">即將換代</option>
            <option value="discontinued">停產下架</option>
            <option value="clearance">清倉處理</option>
          </select>
        </Field>

        {state.accessory_type === "phone_specific" && (
          <div className="field-row">
            <Field
              label="配件購買率"
              error={fieldErrors.attach_rate}
              hint="買主機的人約幾成會買此配件(0.30 = 30%)"
            >
              <input
                type="number"
                step="0.05"
                min="0"
                max="1"
                value={state.attach_rate}
                onChange={(e) => patch("attach_rate", e.target.value)}
              />
            </Field>
            <Field
              label="補貨天數"
              error={fieldErrors.replenish_days}
              hint="動態安全庫存的天數因子,預設 14 天"
            >
              <input
                type="number"
                step="1"
                min="1"
                value={state.replenish_days}
                onChange={(e) => patch("replenish_days", e.target.value)}
              />
            </Field>
          </div>
        )}

        <details className="pf-details" open>
          <summary>屬性</summary>
          <div className="pf-details-body">
            <Checkbox
              checked={state.requires_serial}
              onChange={(v) =>
                patch("requires_serial", state.is_virtual ? false : v)
              }
              label="需追蹤序號"
            />
            <Checkbox
              checked={state.allows_telecom_line}
              onChange={(v) => patch("allows_telecom_line", v)}
              label="可綁門號合約"
            />
            <Checkbox
              checked={state.allows_commission}
              onChange={(v) => patch("allows_commission", v)}
              label="可有業務員佣金"
            />
            <Checkbox
              checked={state.is_active}
              onChange={(v) => patch("is_active", v)}
              label="啟用"
            />
          </div>
        </details>

        <details className="pf-details">
          <summary>會計處理</summary>
          <div className="pf-details-body fieldset-skip">
          <Checkbox
            checked={state.is_virtual}
            onChange={(v) => {
              patch("is_virtual", v);
              if (v) patch("requires_serial", false);
            }}
            label="虛擬商品"
          />
          <Checkbox
            checked={state.is_secondhand}
            onChange={(v) => {
              patch("is_secondhand", v);
              // 中古機一定追蹤序號;勾起時自動把追蹤序號打開、虛擬商品關掉
              if (v) {
                patch("requires_serial", true);
                patch("is_virtual", false);
              }
            }}
            label="中古機(逐隻記成色 / 電池 / 自定售價)"
          />
          <Checkbox
            checked={state.counts_cash}
            onChange={(v) => patch("counts_cash", v)}
            label="計入現金"
          />
          <Checkbox
            checked={state.counts_margin}
            onChange={(v) => patch("counts_margin", v)}
            label="計入毛利"
          />
          </div>
        </details>
      </form>
    </Drawer>
  );
}
