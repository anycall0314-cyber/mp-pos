import { useEffect, useMemo, useState } from "react";

import { api } from "@/api/client";
import {
  useCategories,
  usePartBulkCreate,
  usePartTemplatePreview,
  usePartTemplates,
} from "@/api/hooks";
import type {
  PartBulkCreateResult,
  PartPreviewRow,
  PartTemplate,
} from "@/api/types";
import { Banner } from "@/components/Banner";
import { DraftBanner } from "@/components/DraftBanner";
import { useModalDraft } from "@/hooks/useModalDraft";

const DRAFT_KEY = "modal-draft:bulk-create-parts";

interface Props {
  open: boolean;
  onClose: () => void;
}

interface PhoneModelOption {
  model_key: string;
  model_name: string;
  brand: string;
  sku_count: number;
}

/** 四步驟批次建立零件: 選範本 → 選機型 → 預覽調整 → 確認 */
export function BulkCreatePartsModal({ open, onClose }: Props) {
  const [step, setStep] = useState<number>(1);
  const [templateId, setTemplateId] = useState<number | null>(null);
  const [models, setModels] = useState<PhoneModelOption[]>([]);
  const [selectedKeys, setSelectedKeys] = useState<Set<string>>(new Set());
  const [defaultCost, setDefaultCost] = useState("0");
  const [defaultSafety, setDefaultSafety] = useState("2");
  const [categoryId, setCategoryId] = useState<number | "">("");
  const [rows, setRows] = useState<PartPreviewRow[]>([]);
  const [result, setResult] = useState<PartBulkCreateResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const templates = usePartTemplates();
  const categories = useCategories();
  const preview = usePartTemplatePreview();
  const bulkCreate = usePartBulkCreate();

  useEffect(() => {
    if (!open) return;
    setStep(1);
    setTemplateId(null);
    setSelectedKeys(new Set());
    setDefaultCost("0");
    setDefaultSafety("2");
    setRows([]);
    setResult(null);
    setError(null);
  }, [open]);

  // 草稿(step 也存,下次重開可從中途繼續)
  const draftState = useMemo(
    () => ({
      step,
      templateId,
      selectedKeys: Array.from(selectedKeys),
      defaultCost,
      defaultSafety,
      categoryId,
      rows,
    }),
    [step, templateId, selectedKeys, defaultCost, defaultSafety, categoryId, rows],
  );
  const draftHelper = useModalDraft({
    key: DRAFT_KEY,
    open,
    state: draftState,
    isEditMode: false,
    isEmpty: (s) =>
      !s.templateId &&
      s.selectedKeys.length === 0 &&
      s.rows.length === 0,
  });
  function loadDraftToState() {
    const d = draftHelper.draft;
    if (!d) return;
    const s = d.state;
    setStep(s.step);
    setTemplateId(s.templateId);
    setSelectedKeys(new Set(s.selectedKeys));
    setDefaultCost(s.defaultCost);
    setDefaultSafety(s.defaultSafety);
    setCategoryId(s.categoryId);
    setRows(s.rows);
    draftHelper.consumeDraft();
  }

  // Step 2 載入機型
  useEffect(() => {
    if (step !== 2 || models.length > 0) return;
    api<
      {
        model_key: string;
        model_name: string;
        brand: string;
        sku_count: number;
      }[]
    >("/products/phone-models/")
      .then((list) => setModels(list))
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [step, models.length]);

  // Step 3 → 呼叫 preview
  async function goPreview() {
    if (!templateId) return;
    setError(null);
    try {
      const res = await preview.mutateAsync({
        template_id: templateId,
        model_keys: Array.from(selectedKeys),
        defaults: {
          cost: defaultCost || "0",
          safety_stock: Number(defaultSafety) || 0,
        },
      });
      setRows(res.rows);
      setStep(3);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function commitCreate() {
    if (!templateId || !categoryId) {
      setError("請選擇商品類別");
      return;
    }
    setError(null);
    try {
      const res = await bulkCreate.mutateAsync({
        template_id: templateId,
        category_id: Number(categoryId),
        rows: rows.map((r) => ({
          model_key: r.model_key,
          model_keys: r.model_keys,
          name: r.name,
          sku: r.sku,
          cost: r.cost,
          safety_stock: r.safety_stock,
        })),
      });
      draftHelper.markSavedAndClear();
      setResult(res);
      setStep(4);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  const selectedTemplate: PartTemplate | undefined = (
    templates.data ?? []
  ).find((t) => t.id === templateId);

  const modelsByBrand = useMemo(() => {
    const m = new Map<string, PhoneModelOption[]>();
    for (const o of models) {
      const k = o.brand || "其他";
      if (!m.has(k)) m.set(k, []);
      m.get(k)!.push(o);
    }
    return Array.from(m.entries()).sort(([a], [b]) => a.localeCompare(b));
  }, [models]);

  function toggleKey(k: string) {
    const next = new Set(selectedKeys);
    if (next.has(k)) next.delete(k);
    else next.add(k);
    setSelectedKeys(next);
  }

  function toggleBrand(brand: string, on: boolean) {
    const next = new Set(selectedKeys);
    for (const m of modelsByBrand.find(([b]) => b === brand)?.[1] ?? []) {
      if (on) next.add(m.model_key);
      else next.delete(m.model_key);
    }
    setSelectedKeys(next);
  }

  function applyDefaultsToAll() {
    setRows((rs) =>
      rs.map((r) => ({
        ...r,
        cost: defaultCost || "0",
        safety_stock: Number(defaultSafety) || 0,
      })),
    );
  }

  const summarySku =
    selectedKeys.size * (selectedTemplate?.items.length ?? 0);
  const itemsCount = selectedTemplate?.items.length ?? 0;

  if (!open) return null;

  return (
    <div className="modal-overlay">{/* 遮罩點擊不關閉,只能用「取消」按鈕關 */}
      <div
        className="modal-card bcp-modal"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-title">
          零件批次建立 · 第 {step}/4 步
        </div>
        <div className="modal-body bcp-body">
          {error && <Banner kind="error" message={error} />}
          {draftHelper.draft && (
            <DraftBanner
              savedAt={draftHelper.draft.savedAt}
              onLoad={loadDraftToState}
              onDiscard={() => draftHelper.discardDraft()}
              label="上次有未完成的零件批次建立"
            />
          )}

          {/* Step 1: 選範本 */}
          {step === 1 && (
            <>
              <div className="bcp-step-hint">
                選擇一個零件範本(定義有哪些零件種類),之後會套用到下一步勾選的所有機型。
              </div>
              {templates.isLoading && <div>載入中…</div>}
              {!templates.isLoading && (templates.data?.length ?? 0) === 0 && (
                <Banner
                  kind="info"
                  message="尚未建立任何範本。請先到「零件範本管理」建立(例如:智慧型手機標準 = 螢幕、電池、後蓋…)。"
                />
              )}
              <div className="bcp-tpl-grid">
                {(templates.data ?? []).map((t) => {
                  const sel = t.id === templateId;
                  return (
                    <button
                      key={t.id}
                      type="button"
                      className={"bcp-tpl-card" + (sel ? " selected" : "")}
                      onClick={() => setTemplateId(t.id)}
                    >
                      <div className="bcp-tpl-name">
                        {t.name}
                        <span className="bcp-tpl-count">
                          {t.items.length} 種
                        </span>
                      </div>
                      <ul className="bcp-tpl-items">
                        {t.items.slice(0, 6).map((it) => (
                          <li key={it.id ?? it.code}>· {it.name}</li>
                        ))}
                        {t.items.length > 6 && (
                          <li>+ {t.items.length - 6} 種更多</li>
                        )}
                      </ul>
                    </button>
                  );
                })}
              </div>
            </>
          )}

          {/* Step 2: 選機型 */}
          {step === 2 && (
            <>
              <div className="bcp-step-hint">
                可跨品牌多選,整個系列一次全勾。
              </div>
              {modelsByBrand.length === 0 && <div>載入機型清單…</div>}
              {modelsByBrand.map(([brand, list]) => {
                const allOn = list.every((m) =>
                  selectedKeys.has(m.model_key),
                );
                return (
                  <div key={brand} className="bcp-brand-block">
                    <label className="bcp-brand-row">
                      <input
                        type="checkbox"
                        checked={allOn}
                        onChange={(e) => toggleBrand(brand, e.target.checked)}
                      />
                      <b>{brand || "其他"}</b>
                      <span className="bcp-brand-count">
                        ({list.length} 款)
                      </span>
                    </label>
                    <div className="bcp-model-grid">
                      {list.map((m) => {
                        const on = selectedKeys.has(m.model_key);
                        return (
                          <label
                            key={m.model_key}
                            className={"bcp-model-chip" + (on ? " on" : "")}
                          >
                            <input
                              type="checkbox"
                              checked={on}
                              onChange={() => toggleKey(m.model_key)}
                            />
                            {m.model_name}
                          </label>
                        );
                      })}
                    </div>
                  </div>
                );
              })}
              <div className="bcp-summary">
                <span>
                  <b>{selectedKeys.size}</b> 款機型
                </span>
                <span>×</span>
                <span>
                  <b>{itemsCount}</b> 種零件
                </span>
                <span>=</span>
                <span>
                  <b>{summarySku}</b> 筆 SKU 待建立
                </span>
              </div>
            </>
          )}

          {/* Step 3: 預覽 */}
          {step === 3 && (
            <>
              <div className="bcp-step-hint">
                品名與品號自動生成。成本與安全庫存可統一設定或個別調整,確認無誤後送出。
              </div>
              <div className="bcp-defaults-bar">
                <label>
                  統一安全庫存
                  <input
                    type="number"
                    min="0"
                    value={defaultSafety}
                    onChange={(e) => setDefaultSafety(e.target.value)}
                    style={{ width: 80 }}
                  />
                </label>
                <label>
                  統一成本
                  <input
                    type="number"
                    min="0"
                    value={defaultCost}
                    onChange={(e) => setDefaultCost(e.target.value)}
                    style={{ width: 100 }}
                  />
                </label>
                <button
                  type="button"
                  className="btn"
                  onClick={applyDefaultsToAll}
                >
                  套用至全部
                </button>
                <span style={{ marginLeft: "auto" }}>
                  共 <b>{rows.length}</b> 筆
                </span>
              </div>
              <label className="bcp-cat-row">
                建立到類別 (必選)
                <select
                  value={categoryId}
                  onChange={(e) =>
                    setCategoryId(
                      e.target.value ? Number(e.target.value) : "",
                    )
                  }
                >
                  <option value="">請選擇</option>
                  {(categories.data ?? []).map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.code} {c.name}
                    </option>
                  ))}
                </select>
              </label>
              <div className="bcp-preview-wrap">
                <table className="bcp-preview-table">
                  <thead>
                    <tr>
                      <th>品名</th>
                      <th>品號</th>
                      <th>零件種類</th>
                      <th>相容機型</th>
                      <th style={{ width: 80 }}>安全庫存</th>
                      <th style={{ width: 100 }}>成本</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r, idx) => (
                      <tr key={`${r.model_key}-${r.item_id}`}>
                        <td>
                          <input
                            value={r.name}
                            onChange={(e) => {
                              const next = [...rows];
                              next[idx] = { ...r, name: e.target.value };
                              setRows(next);
                            }}
                          />
                        </td>
                        <td>
                          <input
                            value={r.sku}
                            className={r.exists ? "bcp-exists" : ""}
                            onChange={(e) => {
                              const next = [...rows];
                              next[idx] = { ...r, sku: e.target.value };
                              setRows(next);
                            }}
                          />
                        </td>
                        <td>
                          <span className="bcp-tag">{r.item_name}</span>
                          {r.shared && (
                            <span
                              className="bcp-tag"
                              style={{
                                background: "rgba(251, 191, 36, 0.15)",
                                color: "#fbbf24",
                                marginLeft: 4,
                              }}
                            >
                              共用
                            </span>
                          )}
                        </td>
                        <td title={r.model_name}>
                          {r.shared ? (
                            <span>
                              <b>{r.model_keys.length}</b> 款共用{" "}
                              <span
                                style={{
                                  color: "var(--text-dim)",
                                  fontSize: 11,
                                }}
                              >
                                ({r.model_name.split(" / ").slice(0, 2).join(" / ")}
                                {r.model_keys.length > 2 ? " …" : ""})
                              </span>
                            </span>
                          ) : (
                            r.model_name
                          )}
                        </td>
                        <td>
                          <input
                            type="number"
                            min="0"
                            value={r.safety_stock}
                            onChange={(e) => {
                              const next = [...rows];
                              next[idx] = {
                                ...r,
                                safety_stock: Number(e.target.value) || 0,
                              };
                              setRows(next);
                            }}
                          />
                        </td>
                        <td>
                          <input
                            type="number"
                            min="0"
                            value={r.cost}
                            onChange={(e) => {
                              const next = [...rows];
                              next[idx] = { ...r, cost: e.target.value };
                              setRows(next);
                            }}
                          />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="bcp-format-hint">
                品名格式:機型名稱 + 零件種類名稱 ｜ 品號格式:PRT-品牌縮寫-機型縮寫-零件種類代碼
                ｜ 品號已存在的會以紅底顯示,送出時自動跳過
              </div>
            </>
          )}

          {/* Step 4: 結果 */}
          {step === 4 && result && (
            <>
              <div className="bcp-result-card">
                <div className="bcp-result-hero">
                  成功建立 <b>{result.created}</b> 筆零件 SKU
                </div>
                {result.skipped.length > 0 && (
                  <div className="bcp-result-row">
                    跳過 {result.skipped.length} 筆(品號已存在):
                    <div className="bcp-result-sub">
                      {result.skipped.slice(0, 30).join(" / ")}
                      {result.skipped.length > 30 &&
                        ` … 共 ${result.skipped.length} 筆`}
                    </div>
                  </div>
                )}
                {result.errors.length > 0 && (
                  <div className="bcp-result-row" style={{ color: "#ff7070" }}>
                    錯誤 {result.errors.length} 筆:
                    <ul className="bcp-result-sub">
                      {result.errors.slice(0, 10).map((e, i) => (
                        <li key={i}>
                          {e.sku}: {e.error}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
              <Banner
                kind="info"
                message="建立的零件已自動設定:商品性質=機型專屬、倉別=零件倉、不追蹤序號、產品狀態=主力現貨,並綁定對應機型相容性。"
              />
            </>
          )}
        </div>

        <div className="modal-actions bcp-actions">
          <button type="button" className="btn" onClick={onClose}>
            {step === 4 ? "完成" : "取消"}
          </button>
          {step > 1 && step < 4 && (
            <button
              type="button"
              className="btn"
              onClick={() => setStep(step - 1)}
            >
              上一步
            </button>
          )}
          {step === 1 && (
            <button
              type="button"
              className="btn primary"
              onClick={() => setStep(2)}
              disabled={!templateId}
            >
              下一步:選機型
            </button>
          )}
          {step === 2 && (
            <button
              type="button"
              className="btn primary"
              onClick={goPreview}
              disabled={selectedKeys.size === 0 || preview.isPending}
            >
              {preview.isPending
                ? "產生預覽中…"
                : `下一步:預覽 ${summarySku} 筆`}
            </button>
          )}
          {step === 3 && (
            <button
              type="button"
              className="btn primary"
              onClick={commitCreate}
              disabled={
                bulkCreate.isPending || !categoryId || rows.length === 0
              }
            >
              {bulkCreate.isPending
                ? "建立中…"
                : `確認建立 ${rows.length} 筆零件`}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
