import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  PhoneModelBundlePayload,
  PhoneModelBundleResult,
  useBrands,
  useCategories,
  useConditions,
  useCreatePhoneModelBundle,
  usePartTemplate,
  usePartTemplates,
  usePhoneSeriesList,
} from "@/api/hooks";
import { Banner } from "@/components/Banner";
import { Toolbar } from "@/components/Toolbar";

/**
 * 「新增手機型號」3 步 wizard。
 *
 * Step 1 基本資料:品牌 + 系列 + 世代 + 後綴 + 範本 + 類別 + 售價
 * Step 2 微調:狀態 / 容量 / 顏色 / 配件類別 / 零件清單(預設從範本帶入)
 * Step 3 預覽 + 一鍵建立:dry_run 列出 SKU 清單,確認後 commit
 *
 * 後端 endpoint:POST /api/v1/products/create-phone-model/
 */

// ─── Helpers ────────────────────────────────────────────────────

function ChipInput({
  value,
  onChange,
  placeholder,
}: {
  value: string[];
  onChange: (next: string[]) => void;
  placeholder?: string;
}) {
  const [draft, setDraft] = useState("");
  function commit(raw: string) {
    const trimmed = raw.trim().replace(/[,、]+$/, "").trim();
    if (!trimmed) return;
    if (value.includes(trimmed)) {
      setDraft("");
      return;
    }
    onChange([...value, trimmed]);
    setDraft("");
  }
  return (
    <div
      style={{
        display: "flex",
        flexWrap: "wrap",
        alignItems: "center",
        gap: 6,
        padding: "6px 8px",
        background: "var(--bg)",
        border: "1px solid var(--border)",
        borderRadius: 6,
        minHeight: 40,
      }}
    >
      {value.map((v, i) => (
        <span
          key={`${v}-${i}`}
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 4,
            padding: "3px 8px",
            borderRadius: 999,
            background: "rgba(79, 140, 255, 0.12)",
            border: "1px solid rgba(79, 140, 255, 0.35)",
            color: "var(--accent)",
            fontSize: 13,
          }}
        >
          {v}
          <button
            type="button"
            onClick={() => onChange(value.filter((_, j) => j !== i))}
            aria-label={`移除 ${v}`}
            style={{
              background: "transparent",
              border: 0,
              color: "inherit",
              cursor: "pointer",
              fontSize: 14,
              lineHeight: 1,
              padding: 0,
              marginLeft: 2,
            }}
          >
            ×
          </button>
        </span>
      ))}
      <input
        value={draft}
        onChange={(e) => {
          const v = e.target.value;
          if (/[,、]/.test(v)) {
            commit(v);
            return;
          }
          setDraft(v);
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            commit(draft);
          } else if (e.key === "Backspace" && !draft && value.length > 0) {
            onChange(value.slice(0, -1));
          }
        }}
        onBlur={() => draft && commit(draft)}
        placeholder={value.length === 0 ? placeholder : ""}
        style={{
          flex: 1,
          minWidth: 100,
          background: "transparent",
          border: 0,
          outline: 0,
          color: "var(--text)",
          fontSize: 14,
          padding: "4px 2px",
        }}
      />
    </div>
  );
}

function Stepper({ step }: { step: 1 | 2 | 3 }) {
  const steps = [
    { n: 1, label: "基本資料" },
    { n: 2, label: "微調維度" },
    { n: 3, label: "預覽建立" },
  ];
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        marginBottom: 20,
      }}
    >
      {steps.map((s, i) => (
        <div
          key={s.n}
          style={{ display: "flex", alignItems: "center", gap: 8 }}
        >
          <div
            style={{
              width: 28,
              height: 28,
              borderRadius: "50%",
              background:
                s.n < step
                  ? "var(--accent)"
                  : s.n === step
                    ? "var(--accent)"
                    : "var(--panel-2)",
              color: s.n <= step ? "#fff" : "var(--text-dim)",
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: 13,
              fontWeight: 600,
            }}
          >
            {s.n}
          </div>
          <div
            style={{
              fontSize: 14,
              fontWeight: s.n === step ? 600 : 400,
              color: s.n === step ? "var(--text)" : "var(--text-dim)",
            }}
          >
            {s.label}
          </div>
          {i < steps.length - 1 && (
            <div
              style={{
                width: 32,
                height: 1,
                background: "var(--border)",
                margin: "0 4px",
              }}
            />
          )}
        </div>
      ))}
    </div>
  );
}

// ─── State ──────────────────────────────────────────────────────

interface PartItem {
  name: string;
  code: string;
  shared_across_models: boolean;
}

interface WizardState {
  brand_id: number | null;
  series_id: number | null;
  generation: string;
  model_suffix: string;
  main_category_id: number | null;
  accessory_category_id: number | null;
  parts_category_id: number | null;
  template_id: number | null;
  list_price: string;
  condition_ids: number[];
  capacities: string[];
  colors: string[];
  accessory_categories: string[];
  parts_items: PartItem[];
}

const INITIAL: WizardState = {
  brand_id: null,
  series_id: null,
  generation: "",
  model_suffix: "",
  main_category_id: null,
  accessory_category_id: null,
  parts_category_id: null,
  template_id: null,
  list_price: "",
  condition_ids: [],
  capacities: [],
  colors: [],
  accessory_categories: [],
  parts_items: [],
};

// ─── Component ──────────────────────────────────────────────────

export function NewPhoneModelWizardPage() {
  const nav = useNavigate();
  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [state, setState] = useState<WizardState>(INITIAL);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<PhoneModelBundleResult | null>(null);
  const [created, setCreated] = useState<PhoneModelBundleResult | null>(null);
  const [templateApplied, setTemplateApplied] = useState<number | null>(null);
  const [conditionsSeeded, setConditionsSeeded] = useState(false);

  const brands = useBrands();
  const series = usePhoneSeriesList(state.brand_id);
  const conditions = useConditions();
  const categories = useCategories();
  const templates = usePartTemplates();
  const template = usePartTemplate(state.template_id);
  const create = useCreatePhoneModelBundle();

  // 首次載入 conditions 後預設全勾(active 的)
  useEffect(() => {
    if (!conditionsSeeded && conditions.data) {
      setState((s) => ({
        ...s,
        condition_ids: (conditions.data ?? [])
          .filter((c) => c.is_active)
          .map((c) => c.id),
      }));
      setConditionsSeeded(true);
    }
  }, [conditions.data, conditionsSeeded]);

  // 切換範本後,把範本的 4 個維度帶入(只在 template 換時做一次,避免覆寫使用者已調的內容)
  useEffect(() => {
    if (
      template.data &&
      state.template_id != null &&
      state.template_id !== templateApplied
    ) {
      setState((s) => ({
        ...s,
        capacities: template.data.default_capacities ?? [],
        colors: template.data.default_colors ?? [],
        accessory_categories: template.data.default_accessory_categories ?? [],
        parts_items: (template.data.items ?? []).map((it) => ({
          name: it.name,
          code: it.code,
          shared_across_models: it.shared_across_models,
        })),
      }));
      setTemplateApplied(state.template_id);
    }
  }, [template.data, state.template_id, templateApplied]);

  function patch<K extends keyof WizardState>(k: K, v: WizardState[K]) {
    setState((s) => ({ ...s, [k]: v }));
  }

  function toggleCondition(id: number) {
    setState((s) => ({
      ...s,
      condition_ids: s.condition_ids.includes(id)
        ? s.condition_ids.filter((x) => x !== id)
        : [...s.condition_ids, id],
    }));
  }

  function validateStep1(): string | null {
    if (!state.brand_id) return "請選品牌";
    if (!state.main_category_id) return "請選主機類別";
    return null;
  }

  function validateStep2(): string | null {
    if (state.condition_ids.length === 0) return "至少選 1 個狀態";
    if (state.capacities.length === 0) return "至少 1 個容量";
    if (state.colors.length === 0) return "至少 1 個顏色";
    return null;
  }

  function buildPayload(dry_run: boolean): PhoneModelBundlePayload {
    return {
      brand_id: state.brand_id,
      series_id: state.series_id,
      generation: state.generation ? Number(state.generation) : null,
      model_suffix: state.model_suffix,
      main_category_id: state.main_category_id,
      accessory_category_id:
        state.accessory_category_id ?? state.main_category_id,
      parts_category_id: state.parts_category_id ?? state.main_category_id,
      template_id: state.template_id,
      list_price: state.list_price || "0",
      condition_ids: state.condition_ids,
      capacities: state.capacities,
      colors: state.colors,
      accessory_categories: state.accessory_categories,
      parts_items: state.parts_items,
      dry_run,
    };
  }

  async function gotoPreview() {
    const v = validateStep2();
    if (v) {
      setError(v);
      return;
    }
    setError(null);
    try {
      const res = await create.mutateAsync(buildPayload(true));
      setPreview(res);
      setStep(3);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function commitCreate() {
    setError(null);
    try {
      const res = await create.mutateAsync(buildPayload(false));
      setCreated(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  const expectedMain =
    state.condition_ids.length *
    state.capacities.length *
    state.colors.length;

  // 取目前範本名稱供 step 2 顯示
  const templateName = useMemo(() => {
    if (!state.template_id) return null;
    return (templates.data ?? []).find((t) => t.id === state.template_id)
      ?.name;
  }, [templates.data, state.template_id]);

  return (
    <div className="page">
      <Toolbar
        title="新增手機型號"
        actions={
          <button
            type="button"
            className="btn"
            onClick={() => nav("/products")}
          >
            返回商品列表
          </button>
        }
      />

      <div className="entry-body">
        <Stepper step={step} />

        {error && <Banner kind="error" message={error} />}

        {/* ─── Step 1:基本資料 ─────────────────────────────── */}
        {step === 1 && (
          <div className="form-card">
            <div className="section-head">
              基本資料
              <span className="section-head-meta">
                先告訴系統「這是什麼機型 / 套用哪個範本」
              </span>
            </div>

            <div className="form-row-2col">
              <div className="form-field" style={{ marginBottom: 0 }}>
                <label className="form-field-label">
                  品牌<span className="required">*</span>
                </label>
                <select
                  value={state.brand_id ?? ""}
                  onChange={(e) =>
                    patch(
                      "brand_id",
                      e.target.value ? Number(e.target.value) : null,
                    )
                  }
                >
                  <option value="">— 請選 —</option>
                  {(brands.data ?? [])
                    .filter((b) => b.is_active)
                    .map((b) => (
                      <option key={b.id} value={b.id}>
                        {b.name}
                      </option>
                    ))}
                </select>
              </div>
              <div className="form-field" style={{ marginBottom: 0 }}>
                <label className="form-field-label">系列</label>
                <select
                  value={state.series_id ?? ""}
                  onChange={(e) =>
                    patch(
                      "series_id",
                      e.target.value ? Number(e.target.value) : null,
                    )
                  }
                  disabled={!state.brand_id}
                >
                  <option value="">— 不指定 —</option>
                  {(series.data ?? []).map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <div className="form-row-2col" style={{ marginTop: 14 }}>
              <div className="form-field" style={{ marginBottom: 0 }}>
                <label className="form-field-label">世代(數字)</label>
                <input
                  type="number"
                  value={state.generation}
                  onChange={(e) => patch("generation", e.target.value)}
                  placeholder="例:17"
                  style={{ textAlign: "center" }}
                />
                <div className="form-field-hint">
                  例:iPhone 17 Pro 的 17;沒有就留空
                </div>
              </div>
              <div className="form-field" style={{ marginBottom: 0 }}>
                <label className="form-field-label">型號後綴</label>
                <input
                  value={state.model_suffix}
                  onChange={(e) => patch("model_suffix", e.target.value)}
                  placeholder="例:Pro / Pro Max / Ultra"
                />
                <div className="form-field-hint">
                  品牌 + 系列 + 世代 + 後綴 = 機型名稱
                </div>
              </div>
            </div>

            <div className="form-field" style={{ marginTop: 14 }}>
              <label className="form-field-label">套用範本</label>
              <select
                value={state.template_id ?? ""}
                onChange={(e) =>
                  patch(
                    "template_id",
                    e.target.value ? Number(e.target.value) : null,
                  )
                }
              >
                <option value="">— 不套範本 —</option>
                {(templates.data ?? [])
                  .filter((t) => t.is_active)
                  .map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.name}
                    </option>
                  ))}
              </select>
              <div className="form-field-hint">
                範本會自動帶入容量 / 顏色 / 配件類別 / 零件清單,下一步可再微調。
                範本管理在「庫存 → 零件範本管理」。
              </div>
            </div>

            <div className="form-row-2col" style={{ marginTop: 14 }}>
              <div className="form-field" style={{ marginBottom: 0 }}>
                <label className="form-field-label">
                  主機類別<span className="required">*</span>
                </label>
                <select
                  value={state.main_category_id ?? ""}
                  onChange={(e) => {
                    const v = e.target.value ? Number(e.target.value) : null;
                    patch("main_category_id", v);
                    if (state.accessory_category_id == null)
                      patch("accessory_category_id", v);
                    if (state.parts_category_id == null)
                      patch("parts_category_id", v);
                  }}
                >
                  <option value="">— 請選 —</option>
                  {(categories.data ?? [])
                    .filter((c) => c.is_active)
                    .map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name}
                      </option>
                    ))}
                </select>
              </div>
              <div className="form-field" style={{ marginBottom: 0 }}>
                <label className="form-field-label">建議售價(主機)</label>
                <input
                  type="number"
                  step="1"
                  value={state.list_price}
                  onChange={(e) => patch("list_price", e.target.value)}
                  placeholder="39900"
                  style={{ textAlign: "right" }}
                />
                <div className="form-field-hint">
                  套用到所有主機 SKU,之後可逐項調整
                </div>
              </div>
            </div>

            <div className="form-row-2col" style={{ marginTop: 14 }}>
              <div className="form-field" style={{ marginBottom: 0 }}>
                <label className="form-field-label">配件類別</label>
                <select
                  value={state.accessory_category_id ?? ""}
                  onChange={(e) =>
                    patch(
                      "accessory_category_id",
                      e.target.value ? Number(e.target.value) : null,
                    )
                  }
                >
                  <option value="">— 沿用主機類別 —</option>
                  {(categories.data ?? [])
                    .filter((c) => c.is_active)
                    .map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name}
                      </option>
                    ))}
                </select>
                <div className="form-field-hint">
                  配件 placeholder SKU 要掛到哪個類別
                </div>
              </div>
              <div className="form-field" style={{ marginBottom: 0 }}>
                <label className="form-field-label">零件類別</label>
                <select
                  value={state.parts_category_id ?? ""}
                  onChange={(e) =>
                    patch(
                      "parts_category_id",
                      e.target.value ? Number(e.target.value) : null,
                    )
                  }
                >
                  <option value="">— 沿用主機類別 —</option>
                  {(categories.data ?? [])
                    .filter((c) => c.is_active)
                    .map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name}
                      </option>
                    ))}
                </select>
                <div className="form-field-hint">
                  維修零件 SKU 要掛到哪個類別
                </div>
              </div>
            </div>

            <div
              style={{
                display: "flex",
                justifyContent: "flex-end",
                gap: 8,
                marginTop: 24,
                borderTop: "1px solid var(--border)",
                paddingTop: 16,
              }}
            >
              <button
                type="button"
                className="btn primary btn-save"
                onClick={() => {
                  const v = validateStep1();
                  if (v) {
                    setError(v);
                    return;
                  }
                  setError(null);
                  setStep(2);
                }}
              >
                下一步 →
              </button>
            </div>
          </div>
        )}

        {/* ─── Step 2:微調維度 ─────────────────────────────── */}
        {step === 2 && (
          <div className="form-card">
            <div className="section-head">
              微調維度
              <span className="section-head-meta">
                {templateName ? (
                  <>已套用「{templateName}」範本 — 取消不要的、自行補要的</>
                ) : (
                  <>沒套範本 — 全部要自己填</>
                )}
              </span>
            </div>

            {/* 狀態 */}
            <div className="form-field">
              <label className="form-field-label">
                狀態<span className="required">*</span>
              </label>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
                {(conditions.data ?? [])
                  .filter((c) => c.is_active)
                  .map((c) => (
                    <label
                      key={c.id}
                      style={{
                        display: "inline-flex",
                        alignItems: "center",
                        gap: 6,
                        padding: "6px 10px",
                        border: "1px solid var(--border)",
                        borderRadius: 6,
                        cursor: "pointer",
                        background: state.condition_ids.includes(c.id)
                          ? "rgba(79, 140, 255, 0.08)"
                          : "transparent",
                      }}
                    >
                      <input
                        type="checkbox"
                        checked={state.condition_ids.includes(c.id)}
                        onChange={() => toggleCondition(c.id)}
                      />
                      {c.name}
                      {c.is_secondhand && (
                        <span
                          style={{
                            padding: "1px 6px",
                            borderRadius: 999,
                            background: "rgba(251, 146, 60, 0.15)",
                            color: "#fb923c",
                            fontSize: 11,
                          }}
                        >
                          中古機
                        </span>
                      )}
                    </label>
                  ))}
              </div>
              <div className="form-field-hint">
                名稱含「中古」的狀態下建出的 SKU 會自動 is_secondhand=True,
                觸發中古機「每隻獨立成本」邏輯
              </div>
            </div>

            <div className="form-field">
              <label className="form-field-label">
                容量<span className="required">*</span>
              </label>
              <ChipInput
                value={state.capacities}
                onChange={(v) => patch("capacities", v)}
                placeholder="輸入後按 Enter,例:128GB"
              />
            </div>

            <div className="form-field">
              <label className="form-field-label">
                顏色<span className="required">*</span>
              </label>
              <ChipInput
                value={state.colors}
                onChange={(v) => patch("colors", v)}
                placeholder="輸入後按 Enter,例:黑"
              />
            </div>

            <div className="form-field">
              <label className="form-field-label">
                相容配件類別(僅供記錄)
              </label>
              <ChipInput
                value={state.accessory_categories}
                onChange={(v) => patch("accessory_categories", v)}
                placeholder="輸入後按 Enter,例:殼"
              />
              <div className="form-field-hint">
                這只是記錄「這支手機之後會配什麼類別的配件」, wizard 不會建任何配件 SKU。
                真正配件商品(imos / HODA 各品牌變體)要走「+ 新增配件」獨立 wizard,
                建好後在那邊勾選相容機型即可。
              </div>
            </div>

            {state.parts_items.length > 0 && (
              <div className="form-field">
                <label className="form-field-label">
                  維修零件清單(來自範本,共 {state.parts_items.length} 項)
                </label>
                <div
                  style={{
                    border: "1px solid var(--border)",
                    borderRadius: 6,
                    padding: 8,
                    background: "var(--bg)",
                  }}
                >
                  {state.parts_items.map((p, i) => (
                    <div
                      key={i}
                      style={{
                        display: "flex",
                        gap: 8,
                        padding: "4px 6px",
                        fontSize: 13,
                      }}
                    >
                      <code style={{ minWidth: 60 }}>{p.code}</code>
                      <span style={{ flex: 1 }}>{p.name}</span>
                      {p.shared_across_models && (
                        <span style={{ color: "var(--text-dim)", fontSize: 12 }}>
                          跨機型共用
                        </span>
                      )}
                    </div>
                  ))}
                </div>
                <div className="form-field-hint">
                  Wizard 會為每項建一個零件 SKU 並綁定到此機型。
                  要新增或修改零件清單請去「庫存 → 零件範本管理」改範本
                </div>
              </div>
            )}

            <div
              style={{
                background: "var(--panel-2)",
                border: "1px solid var(--border)",
                borderRadius: 6,
                padding: 12,
                marginTop: 8,
                fontSize: 14,
                color: "var(--text)",
              }}
            >
              預計建立:
              <b style={{ marginLeft: 6, color: "var(--accent)" }}>
                {expectedMain}
              </b>{" "}
              個主機 SKU
              {state.parts_items.length > 0 && (
                <>
                  {" "}
                  + <b>{state.parts_items.length}</b> 個維修零件 SKU
                </>
              )}
              {state.accessory_categories.length > 0 && (
                <span style={{ color: "var(--text-dim)" }}>
                  {" "}
                  (記錄 {state.accessory_categories.length} 個相容配件類別,不建 SKU)
                </span>
              )}
              <div
                style={{
                  fontSize: 12,
                  color: "var(--text-dim)",
                  marginTop: 4,
                }}
              >
                {state.condition_ids.length} 狀態 × {state.capacities.length} 容量 ×{" "}
                {state.colors.length} 顏色 = {expectedMain}
              </div>
            </div>

            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                gap: 8,
                marginTop: 20,
                borderTop: "1px solid var(--border)",
                paddingTop: 16,
              }}
            >
              <button
                type="button"
                className="btn"
                onClick={() => {
                  setError(null);
                  setStep(1);
                }}
              >
                ← 上一步
              </button>
              <button
                type="button"
                className="btn primary btn-save"
                onClick={gotoPreview}
                disabled={create.isPending}
              >
                {create.isPending ? "計算中…" : "預覽 →"}
              </button>
            </div>
          </div>
        )}

        {/* ─── Step 3:預覽 + 建立 ─────────────────────────── */}
        {step === 3 && preview && (
          <div className="form-card">
            {!created ? (
              <>
                <div className="section-head">
                  預覽
                  <span className="section-head-meta">
                    機型「{preview.model_name}」
                  </span>
                </div>

                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(2, 1fr)",
                    gap: 12,
                    marginBottom: 16,
                  }}
                >
                  <SummaryStat label="主機 SKU" value={preview.main_count} />
                  <SummaryStat
                    label="維修零件 SKU"
                    value={preview.parts_count}
                  />
                </div>

                {preview.accessory_slots.length > 0 && (
                  <div
                    style={{
                      fontSize: 13,
                      color: "var(--text-dim)",
                      marginBottom: 14,
                      padding: "8px 12px",
                      background: "var(--panel-2)",
                      borderRadius: 6,
                    }}
                  >
                    記錄「相容配件類別」:
                    {preview.accessory_slots.map((s, i) => (
                      <span
                        key={i}
                        style={{
                          display: "inline-block",
                          marginLeft: 6,
                          padding: "1px 8px",
                          borderRadius: 999,
                          background: "var(--bg)",
                          border: "1px solid var(--border)",
                          color: "var(--text)",
                        }}
                      >
                        {s}
                      </span>
                    ))}
                    <span style={{ marginLeft: 8 }}>
                      不會建 SKU,實際配件去「+ 新增配件」獨立建立
                    </span>
                  </div>
                )}

                <PreviewTable items={preview.main} kind="main" />
                {preview.parts.length > 0 && (
                  <PreviewTable items={preview.parts} kind="parts" />
                )}

                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    gap: 8,
                    marginTop: 20,
                    borderTop: "1px solid var(--border)",
                    paddingTop: 16,
                  }}
                >
                  <button
                    type="button"
                    className="btn"
                    onClick={() => {
                      setError(null);
                      setPreview(null);
                      setStep(2);
                    }}
                  >
                    ← 回去調整
                  </button>
                  <button
                    type="button"
                    className="btn primary btn-save"
                    onClick={commitCreate}
                    disabled={create.isPending}
                  >
                    {create.isPending
                      ? "建立中…"
                      : `確認建立 ${preview.main_count + preview.parts_count} 個 SKU`}
                  </button>
                </div>
              </>
            ) : (
              <>
                <div className="section-head">建立完成</div>
                <div
                  style={{
                    background: "rgba(74, 222, 128, 0.12)",
                    border: "1px solid rgba(74, 222, 128, 0.35)",
                    color: "#4ade80",
                    padding: 16,
                    borderRadius: 8,
                    marginBottom: 16,
                    fontSize: 14,
                    lineHeight: 1.6,
                  }}
                >
                  已成功建立機型「<b>{created.model_name}</b>」 ——
                  主機 <b>{created.main_count}</b> 個 SKU、
                  維修零件 <b>{created.parts_count}</b> 個。
                  {created.accessory_slots.length > 0 && (
                    <>
                      {" "}
                      已記錄 <b>{created.accessory_slots.length}</b> 個相容配件類別,
                      實際配件商品請走「+ 新增配件」獨立建立。
                    </>
                  )}{" "}
                  之後遇到全新 / 已拆封 / 中古機收購都不用再多一道「先建商品」手續,
                  直接掛序號即可。
                </div>

                <div
                  style={{
                    display: "flex",
                    gap: 8,
                    justifyContent: "flex-end",
                  }}
                >
                  <button
                    type="button"
                    className="btn"
                    onClick={() => {
                      // 重來:重置整個 wizard
                      setState(INITIAL);
                      setPreview(null);
                      setCreated(null);
                      setTemplateApplied(null);
                      setConditionsSeeded(false);
                      setStep(1);
                    }}
                  >
                    再建另一支機型
                  </button>
                  <button
                    type="button"
                    className="btn primary btn-save"
                    onClick={() => nav("/products")}
                  >
                    去看商品列表
                  </button>
                </div>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Sub components ─────────────────────────────────────────────

function SummaryStat({ label, value }: { label: string; value: number }) {
  return (
    <div
      style={{
        background: "var(--panel-2)",
        border: "1px solid var(--border)",
        borderRadius: 8,
        padding: "12px 16px",
        textAlign: "center",
      }}
    >
      <div style={{ fontSize: 12, color: "var(--text-dim)" }}>{label}</div>
      <div
        style={{ fontSize: 28, fontWeight: 600, color: "var(--text)" }}
      >
        {value}
      </div>
    </div>
  );
}

function PreviewTable({
  items,
  kind,
}: {
  items: Array<{ name: string; is_secondhand?: boolean }>;
  kind: "main" | "accessory" | "parts";
}) {
  const titles = {
    main: "主機 SKU",
    accessory: "配件 placeholder",
    parts: "維修零件 SKU",
  };
  return (
    <div style={{ marginBottom: 16 }}>
      <div
        style={{
          fontSize: 13,
          color: "var(--text-dim)",
          marginBottom: 6,
        }}
      >
        {titles[kind]}(共 {items.length} 個)
      </div>
      <div
        style={{
          border: "1px solid var(--border)",
          borderRadius: 6,
          maxHeight: 260,
          overflowY: "auto",
          background: "var(--bg)",
        }}
      >
        {items.map((it, i) => (
          <div
            key={i}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              padding: "6px 10px",
              borderBottom:
                i < items.length - 1 ? "1px solid var(--border)" : "none",
              fontSize: 13,
            }}
          >
            <span style={{ flex: 1 }}>{it.name}</span>
            {it.is_secondhand && (
              <span
                style={{
                  padding: "1px 6px",
                  borderRadius: 999,
                  background: "rgba(251, 146, 60, 0.15)",
                  color: "#fb923c",
                  fontSize: 11,
                }}
              >
                中古機
              </span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
