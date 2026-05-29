import { useEffect, useState } from "react";

import {
  useDeleteProductType,
  useProductTypes,
  useSaveProductType,
} from "@/api/hooks";
import type { ProductType } from "@/api/types";
import { Banner } from "@/components/Banner";
import { Toolbar } from "@/components/Toolbar";

/**
 * 常用類型對照(膠囊鈕 + 一鍵建立全部用)
 * code 直接用 2~3 碼英文字母,不走 slugify。
 */
const PRESETS: Array<{ name: string; code: string }> = [
  { name: "手機", code: "PH" },
  { name: "平板", code: "PD" },
  { name: "耳機", code: "EP" },
  { name: "手錶", code: "WT" },
  { name: "穿戴裝置", code: "WB" },
  { name: "配件", code: "AC" },
  { name: "門號/SIM", code: "SIM" },
  { name: "智慧家電", code: "SH" },
];

function slugify(s: string): string {
  return (
    s
      .toLowerCase()
      .trim()
      .replace(/\s+/g, "-")
      .replace(/[^a-z0-9-]/g, "")
      .slice(0, 20) || `type-${Date.now()}`
  );
}

/**
 * 類型 icon — 依代碼或名稱回傳對應 SVG。
 */
function TypeIcon({
  code,
  name,
  size = 28,
}: {
  code: string;
  name: string;
  size?: number;
}) {
  const key = code.toUpperCase();
  const props = {
    width: size,
    height: size,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.7,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
  };
  if (key === "PH" || name === "手機")
    return (
      <svg {...props}>
        <rect x="6" y="2" width="12" height="20" rx="2.5" />
        <line x1="11" y1="18.5" x2="13" y2="18.5" />
      </svg>
    );
  if (key === "PD" || name === "平板")
    return (
      <svg {...props}>
        <rect x="3" y="4" width="18" height="16" rx="2" />
        <circle cx="12" cy="17" r="0.6" fill="currentColor" />
      </svg>
    );
  if (key === "EP" || name === "耳機")
    return (
      <svg {...props}>
        <path d="M4 14a8 8 0 0 1 16 0" />
        <path d="M4 14v4a2 2 0 0 0 2 2h1v-6" />
        <path d="M20 14v4a2 2 0 0 1-2 2h-1v-6" />
      </svg>
    );
  if (key === "WT" || name === "手錶")
    return (
      <svg {...props}>
        <circle cx="12" cy="12" r="5" />
        <path d="M9 7l-1-3h8l-1 3" />
        <path d="M9 17l-1 3h8l-1-3" />
      </svg>
    );
  if (key === "WB" || name === "穿戴裝置")
    return (
      <svg {...props}>
        <rect x="4" y="8" width="16" height="8" rx="3" />
        <circle cx="12" cy="12" r="1.5" />
      </svg>
    );
  if (key === "AC" || name === "配件")
    return (
      <svg {...props}>
        <path d="M9 2v4" />
        <path d="M15 2v4" />
        <rect x="7" y="6" width="10" height="6" rx="1.5" />
        <path d="M12 12v4a3 3 0 0 0 3 3h2" />
      </svg>
    );
  if (key === "SIM" || name === "門號/SIM")
    return (
      <svg {...props}>
        <path d="M14 2H8a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V6z" />
        <line x1="14" y1="2" x2="14" y2="6" />
        <line x1="18" y1="6" x2="14" y2="6" />
        <rect x="9" y="11" width="6" height="6" rx="1" />
        <line x1="12" y1="11" x2="12" y2="17" />
        <line x1="9" y1="14" x2="15" y2="14" />
      </svg>
    );
  if (key === "SH" || name === "智慧家電")
    return (
      <svg {...props}>
        <path d="M3 11l9-8 9 8" />
        <path d="M5 9.5V20a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V9.5" />
        <circle cx="12" cy="14" r="1.5" />
      </svg>
    );
  // 預設:tag 圖
  return (
    <svg {...props}>
      <path d="M20.5 12.5L12 4H4v8l8.5 8.5a2 2 0 0 0 2.8 0l5.2-5.2a2 2 0 0 0 0-2.8z" />
      <circle cx="8" cy="8" r="1.2" fill="currentColor" />
    </svg>
  );
}

const TrashIcon = () => (
  <svg
    width="16"
    height="16"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    <polyline points="3 6 5 6 21 6" />
    <path d="M19 6l-1.5 14a2 2 0 0 1-2 1.8H8.5a2 2 0 0 1-2-1.8L5 6" />
    <path d="M10 11v6M14 11v6" />
    <path d="M9 6V4a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2" />
  </svg>
);

const GripIcon = () => (
  <svg
    width="14"
    height="14"
    viewBox="0 0 24 24"
    fill="currentColor"
    aria-hidden="true"
  >
    <circle cx="9" cy="6" r="1.5" />
    <circle cx="15" cy="6" r="1.5" />
    <circle cx="9" cy="12" r="1.5" />
    <circle cx="15" cy="12" r="1.5" />
    <circle cx="9" cy="18" r="1.5" />
    <circle cx="15" cy="18" r="1.5" />
  </svg>
);

interface Editing {
  id?: number;
  code: string;
  name: string;
  sort_order: number;
  is_active: boolean;
}

export function ProductTypesPage() {
  // ─── 後端串接 ──────────────────────────────────────
  const types = useProductTypes();             // GET /product-types/
  const save = useSaveProductType();           // POST / PATCH /product-types/
  const del = useDeleteProductType();          // DELETE /product-types/:id/

  const [editing, setEditing] = useState<Editing | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [bulkBusy, setBulkBusy] = useState(false);

  // 取得目前清單長度 → 推算下一個 sort_order
  const totalCount = types.data?.length ?? 0;

  useEffect(() => {
    setError(null);
  }, [editing?.id]);

  function startNew(seed?: { name: string; code: string }) {
    setEditing({
      code: seed?.code ?? "",
      name: seed?.name ?? "",
      sort_order: totalCount + 1,
      is_active: true,
    });
    setError(null);
  }

  function startEdit(t: ProductType) {
    setEditing({
      id: t.id,
      code: t.code,
      name: t.name,
      sort_order: t.sort_order,
      is_active: t.is_active,
    });
    setError(null);
  }

  function applyChip(p: { name: string; code: string }) {
    if (!editing) return;
    setEditing({ ...editing, name: p.name, code: p.code });
  }

  async function submit() {
    if (!editing) return;
    if (!editing.name.trim()) {
      setError("請填類型名稱");
      return;
    }
    const code = editing.code.trim() || slugify(editing.name);
    try {
      await save.mutateAsync({ ...editing, code });
      setEditing(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function handleDelete(t: ProductType) {
    if (
      !confirm(
        `刪除類型「${t.name}」?\n旗下系列 (${t.series_count ?? 0} 個) 的「產品類型」會變空白(不會連動刪除系列)。`,
      )
    )
      return;
    try {
      await del.mutateAsync(t.id);
      if (editing?.id === t.id) setEditing(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  /**
   * 一鍵建立全部常用類型 — 已存在(以 code 比對)的會略過。
   */
  async function bulkCreateAll() {
    const existing = new Set(
      (types.data ?? []).map((t) => t.code.toUpperCase()),
    );
    const toCreate = PRESETS.filter((p) => !existing.has(p.code.toUpperCase()));
    if (toCreate.length === 0) {
      alert("常用類型已全部建立完成");
      return;
    }
    if (
      !confirm(
        `將建立 ${toCreate.length} 個常用類型(已存在的會自動略過),確定?`,
      )
    )
      return;
    setBulkBusy(true);
    let ok = 0;
    let fail = 0;
    let nextSort = totalCount + 1;
    for (const p of toCreate) {
      try {
        await save.mutateAsync({
          name: p.name,
          code: p.code,
          sort_order: nextSort++,
          is_active: true,
        });
        ok++;
      } catch {
        fail++;
      }
    }
    setBulkBusy(false);
    setError(null);
    alert(`建立完成:成功 ${ok} 筆${fail > 0 ? ` / 失敗 ${fail} 筆` : ""}`);
  }

  const currentPresetMatch = editing
    ? PRESETS.find((p) => p.name === editing.name)
    : null;

  return (
    <div className="page">
      <Toolbar
        title="產品類型管理"
        actions={
          <>
            <button
              type="button"
              className="btn"
              onClick={bulkCreateAll}
              disabled={bulkBusy}
              title="把常用的 8 種類型一次建好(已存在的會略過)"
            >
              {bulkBusy ? "建立中…" : "一鍵建立全部常用類型"}
            </button>
            <button className="btn primary" onClick={() => startNew()}>
              + 新增類型
            </button>
          </>
        }
      />

      <div className="entry-body">
        <div
          style={{
            fontSize: 14,
            color: "var(--text-dim)",
            marginBottom: 16,
            lineHeight: 1.6,
          }}
        >
          產品類型用來標示「系列屬於哪一類產品」:手機、平板、耳機、手錶、智慧家電…
          <br />
          建立後可在「品牌 / 系列管理」新增系列時挑選,讓同品牌混放不同類型的系列。
        </div>

        {error && <Banner kind="error" message={error} />}

        {/* ─── 編輯表單(卡片)─── */}
        {editing && (
          <div className="form-card">
            <div className="section-head">
              {editing.id ? "編輯類型" : "新增類型"}
              <span className="section-head-meta">
                {editing.id ? `ID #${editing.id}` : "未儲存"}
              </span>
            </div>

            {/* 常用類型膠囊 */}
            <div className="form-field">
              <div className="form-field-label">常用類型 — 點一下自動帶入</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {PRESETS.map((p) => (
                  <button
                    key={p.code}
                    type="button"
                    className={
                      "pill" +
                      (currentPresetMatch?.code === p.code ? " selected" : "")
                    }
                    onClick={() => applyChip(p)}
                  >
                    {p.name}
                  </button>
                ))}
              </div>
            </div>

            {/* 類型名稱 */}
            <div className="form-field">
              <label className="form-field-label" htmlFor="pt-name">
                類型名稱<span className="required">*</span>
              </label>
              <input
                id="pt-name"
                className="input-lg"
                value={editing.name}
                onChange={(e) =>
                  setEditing({ ...editing, name: e.target.value })
                }
                placeholder="例:手機 / 平板 / 耳機"
                autoFocus
              />
            </div>

            {/* 代碼 + 排序 */}
            <div className="form-row-2col">
              <div className="form-field" style={{ marginBottom: 0 }}>
                <label className="form-field-label" htmlFor="pt-code">
                  類型代碼
                </label>
                <input
                  id="pt-code"
                  value={editing.code}
                  onChange={(e) =>
                    setEditing({ ...editing, code: e.target.value })
                  }
                  placeholder="留空自動產生"
                />
                <div className="form-field-hint">
                  留空時依名稱自動生成,例:手機 → PH
                </div>
              </div>
              <div className="form-field" style={{ marginBottom: 0 }}>
                <label className="form-field-label" htmlFor="pt-sort">
                  顯示排序
                </label>
                <input
                  id="pt-sort"
                  type="number"
                  min={0}
                  value={editing.sort_order}
                  onChange={(e) =>
                    setEditing({
                      ...editing,
                      sort_order: Number(e.target.value) || 0,
                    })
                  }
                  placeholder="1"
                  style={{ textAlign: "center" }}
                />
                <div className="form-field-hint">數字小的排在前面</div>
              </div>
            </div>

            {/* 啟用 toggle */}
            <div className="form-field" style={{ marginTop: 18 }}>
              <label className="toggle-switch">
                <input
                  type="checkbox"
                  checked={editing.is_active}
                  onChange={(e) =>
                    setEditing({ ...editing, is_active: e.target.checked })
                  }
                />
                <span className="toggle-track" />
                啟用
              </label>
              <div className="form-field-hint">
                停用後新增系列時這個類型不會出現在下拉選單
              </div>
            </div>

            {/* 底部按鈕 */}
            <div
              style={{
                display: "flex",
                gap: 8,
                justifyContent: "flex-end",
                marginTop: 8,
                borderTop: "1px solid var(--border)",
                paddingTop: 16,
              }}
            >
              <button
                type="button"
                className="btn"
                onClick={() => setEditing(null)}
              >
                取消
              </button>
              <button
                type="button"
                className="btn primary btn-save"
                onClick={submit}
                disabled={save.isPending}
              >
                {save.isPending ? "儲存中…" : "儲存類型"}
              </button>
            </div>
          </div>
        )}

        {/* ─── 已建立類型清單 ─── */}
        <div className="section-head">
          已建立類型
          <span className="section-head-meta">共 {totalCount} 種</span>
          {totalCount > 1 && (
            <span
              className="section-head-meta"
              style={{ marginLeft: "auto", fontSize: 12 }}
            >
              依排序欄位顯示;之後可拖曳卡片調整順序
            </span>
          )}
        </div>

        {types.isLoading && <div>載入中…</div>}

        {!types.isLoading && totalCount === 0 && (
          <div className="empty-cta">
            <div className="empty-cta-title">尚未建立任何產品類型</div>
            <div className="empty-cta-desc">
              第一次設定可以按「一鍵建立全部常用類型」,
              <br />
              系統會幫你把手機、平板、耳機、手錶、穿戴裝置、配件、門號/SIM、智慧家電 8 種建好。
            </div>
            <div
              style={{
                display: "flex",
                gap: 8,
                justifyContent: "center",
                flexWrap: "wrap",
              }}
            >
              <button
                type="button"
                className="btn primary btn-save"
                onClick={bulkCreateAll}
                disabled={bulkBusy}
              >
                {bulkBusy ? "建立中…" : "一鍵建立全部常用類型"}
              </button>
              <button
                type="button"
                className="btn"
                onClick={() => startNew()}
              >
                + 我要自己建一個
              </button>
            </div>
          </div>
        )}

        {totalCount > 0 && (
          <div className="type-grid">
            {(types.data ?? []).map((t) => (
              <div
                key={t.id}
                className={
                  "type-card" + (editing?.id === t.id ? " selected" : "")
                }
                onClick={() => startEdit(t)}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    startEdit(t);
                  }
                }}
                title="點一下編輯此類型"
              >
                <span
                  className="type-card-drag"
                  aria-hidden="true"
                  title="拖曳調整順序(尚未啟用)"
                  onClick={(e) => e.stopPropagation()}
                >
                  <GripIcon />
                </span>
                <div className="type-card-icon">
                  <TypeIcon code={t.code} name={t.name} />
                </div>
                <div className="type-card-name">{t.name}</div>
                <div className="type-card-code">{t.code}</div>
                <div>
                  <span
                    className={
                      "type-card-status " + (t.is_active ? "on" : "off")
                    }
                  >
                    {t.is_active ? "啟用" : "停用"}
                  </span>
                  {(t.series_count ?? 0) > 0 && (
                    <span
                      style={{
                        marginLeft: 6,
                        fontSize: 11,
                        color: "var(--text-dim)",
                      }}
                    >
                      {t.series_count} 個系列
                    </span>
                  )}
                </div>
                <span className="type-card-sort">#{t.sort_order}</span>
                <button
                  type="button"
                  className="icon-btn icon-btn-danger"
                  style={{
                    position: "absolute",
                    bottom: 8,
                    left: 8,
                  }}
                  onClick={(e) => {
                    e.stopPropagation();
                    handleDelete(t);
                  }}
                  aria-label="刪除"
                  title="刪除此類型"
                >
                  <TrashIcon />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
