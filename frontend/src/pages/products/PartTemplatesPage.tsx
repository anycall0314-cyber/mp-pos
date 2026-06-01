import { useEffect, useState } from "react";

import {
  useDeletePartTemplate,
  usePartTemplates,
  useSavePartTemplate,
} from "@/api/hooks";
import type { PartTemplate } from "@/api/types";
import { Banner } from "@/components/Banner";
import { Toolbar } from "@/components/Toolbar";

/**
 * 「快速加入」常用零件 — 點一下加一列並自動帶入名稱與代碼。
 */
const QUICK_PARTS: Array<{ name: string; code: string }> = [
  { name: "螢幕總成", code: "SCR" },
  { name: "電池", code: "BAT" },
  { name: "充電尾插", code: "USB" },
  { name: "後相機", code: "RCAM" },
  { name: "聽筒", code: "RCV" },
  { name: "喇叭", code: "SPK" },
  { name: "外框", code: "FRM" },
  { name: "背蓋", code: "BCK" },
];

/**
 * 「套用常用範本」 — 點一下清空並帶入整組(容量 / 顏色 / 配件類別 / 零件)。
 * Phase 2 起每個 preset 多了 capacities / colors / accessory_categories
 * 三個維度,wizard 套用此範本時會用這 3 個維度產生 SKU。
 */
const PRESET_TEMPLATES: Record<
  string,
  {
    capacities: string[];
    colors: string[];
    accessory_categories: string[];
    accessory_brands: string[];
    parts: Array<{
      name: string;
      code: string;
      shared_across_models?: boolean;
    }>;
  }
> = {
  智慧型手機: {
    capacities: ["128GB", "256GB", "512GB", "1TB"],
    colors: ["黑", "白", "鈦原色"],
    accessory_categories: ["殼", "貼"],
    accessory_brands: ["imos", "HODA", "JTLEGEND"],
    parts: [
      { name: "螢幕總成", code: "SCR" },
      { name: "電池", code: "BAT", shared_across_models: true },
      { name: "充電尾插", code: "USB" },
      { name: "後相機", code: "RCAM" },
      { name: "聽筒", code: "RCV" },
      { name: "喇叭", code: "SPK" },
    ],
  },
  平板: {
    capacities: ["128GB", "256GB", "512GB", "1TB"],
    colors: ["太空灰", "銀", "金"],
    accessory_categories: ["保護套", "貼"],
    accessory_brands: ["imos", "ESR", "Switcheasy"],
    parts: [
      { name: "螢幕總成", code: "SCR" },
      { name: "電池", code: "BAT", shared_across_models: true },
      { name: "充電尾插", code: "USB" },
      { name: "後相機", code: "RCAM" },
      { name: "喇叭", code: "SPK" },
    ],
  },
  智慧手錶: {
    capacities: ["41mm", "45mm", "49mm"],
    colors: ["黑", "銀", "金"],
    accessory_categories: ["錶帶", "保護貼"],
    accessory_brands: ["Apple", "Spigen"],
    parts: [
      { name: "螢幕總成", code: "SCR" },
      { name: "電池", code: "BAT", shared_across_models: true },
      { name: "後蓋", code: "BCV" },
    ],
  },
  筆電: {
    capacities: ["256GB", "512GB", "1TB", "2TB"],
    colors: ["太空灰", "銀"],
    accessory_categories: ["保護套"],
    accessory_brands: ["Targus", "tomtoc"],
    parts: [
      { name: "螢幕總成", code: "SCR" },
      { name: "電池", code: "BAT" },
      { name: "鍵盤", code: "KB" },
      { name: "觸控板", code: "TP" },
      { name: "充電尾插", code: "USB" },
    ],
  },
};

/**
 * 內部編輯用 item — 把 default_cost / default_safety_stock 都當字串處理,
 * 讓「未填」與「填 0」可以分開:空字串顯示 placeholder「0」,實際填 0 顯示 0。
 */
interface EditingItem {
  id?: number;
  name: string;
  code: string;
  sort_order: number;
  default_cost: string;
  default_safety_stock: string;
  shared_across_models: boolean;
}

interface EditingTemplate {
  id: number;
  name: string;
  note: string;
  is_active: boolean;
  default_capacities: string[];
  default_colors: string[];
  default_accessory_categories: string[];
  default_accessory_brands: string[];
  items: EditingItem[];
}

function toEditing(t: PartTemplate): EditingTemplate {
  return {
    id: t.id,
    name: t.name,
    note: t.note,
    is_active: t.is_active,
    default_capacities: t.default_capacities ?? [],
    default_colors: t.default_colors ?? [],
    default_accessory_categories: t.default_accessory_categories ?? [],
    default_accessory_brands: t.default_accessory_brands ?? [],
    items: t.items.map((it, idx) => ({
      id: it.id,
      name: it.name,
      code: it.code,
      sort_order: idx,
      // 從後端拿到 "0" 也維持 "0";從未存過的空才會是空字串(由 quickAdd 等建立)
      default_cost: it.default_cost ?? "",
      default_safety_stock:
        it.default_safety_stock != null ? String(it.default_safety_stock) : "",
      shared_across_models: it.shared_across_models,
    })),
  };
}

/**
 * ChipInput — 小型 tag 輸入器。
 * 輸入文字按 Enter / 逗號 / 頓號 提交一個 chip,backspace 在空白時刪掉最後一個。
 * 每個 chip 有 X 可移除;onChange 回 array<string>。
 */
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
          // 逗號 / 頓號 自動 commit
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

function emptyEditing(): EditingTemplate {
  return {
    id: 0,
    name: "",
    note: "",
    is_active: true,
    default_capacities: [],
    default_colors: [],
    default_accessory_categories: [],
    default_accessory_brands: [],
    items: [],
  };
}

export function PartTemplatesPage() {
  // ─── 後端串接 ─────────────────────────────────────────
  const list = usePartTemplates();          // GET /part-templates/
  const save = useSavePartTemplate();       // POST / PATCH /part-templates/
  const del = useDeletePartTemplate();      // DELETE /part-templates/:id/

  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [editing, setEditing] = useState<EditingTemplate | null>(null);
  const [error, setError] = useState<string | null>(null);

  // 預設選第一筆,讓右邊不會空著
  useEffect(() => {
    if (!editing && (list.data?.length ?? 0) > 0 && selectedId === null) {
      const first = list.data![0];
      setSelectedId(first.id);
      setEditing(toEditing(first));
    }
  }, [list.data]);

  function startNew() {
    setSelectedId(null);
    setEditing(emptyEditing());
    setError(null);
  }

  function pick(t: PartTemplate) {
    setSelectedId(t.id);
    setEditing(toEditing(t));
    setError(null);
  }

  function patch<K extends keyof EditingTemplate>(
    k: K,
    v: EditingTemplate[K],
  ) {
    if (!editing) return;
    setEditing({ ...editing, [k]: v });
  }

  function patchItem(idx: number, partial: Partial<EditingItem>) {
    if (!editing) return;
    const items = [...editing.items];
    items[idx] = { ...items[idx], ...partial };
    setEditing({ ...editing, items });
  }

  function addItem(seed?: Partial<EditingItem>) {
    if (!editing) return;
    setEditing({
      ...editing,
      items: [
        ...editing.items,
        {
          name: seed?.name ?? "",
          code: seed?.code ?? "",
          sort_order: editing.items.length,
          default_cost: seed?.default_cost ?? "",
          default_safety_stock: seed?.default_safety_stock ?? "",
          shared_across_models: seed?.shared_across_models ?? false,
        },
      ],
    });
  }

  function removeItem(idx: number) {
    if (!editing) return;
    setEditing({
      ...editing,
      items: editing.items.filter((_, i) => i !== idx),
    });
  }

  function applyPreset(name: keyof typeof PRESET_TEMPLATES) {
    if (!editing) return;
    const dirty =
      editing.items.length > 0 ||
      editing.default_capacities.length > 0 ||
      editing.default_colors.length > 0 ||
      editing.default_accessory_categories.length > 0 ||
      editing.default_accessory_brands.length > 0;
    if (
      dirty &&
      !confirm(
        `套用「${name}」範本會清空現有零件 / 容量 / 顏色 / 配件類別清單,確定?`,
      )
    ) {
      return;
    }
    const preset = PRESET_TEMPLATES[name];
    const items: EditingItem[] = preset.parts.map((p, idx) => ({
      name: p.name,
      code: p.code,
      sort_order: idx,
      default_cost: "",
      default_safety_stock: "",
      shared_across_models: p.shared_across_models ?? false,
    }));
    setEditing({
      ...editing,
      default_capacities: [...preset.capacities],
      default_colors: [...preset.colors],
      default_accessory_categories: [...preset.accessory_categories],
      default_accessory_brands: [...preset.accessory_brands],
      items,
    });
  }

  function cancel() {
    // 若編輯既有範本 → 還原成最後一次從後端載入的狀態
    // 若是新增 → 清空回到「未編輯」
    if (editing?.id) {
      const original = (list.data ?? []).find((t) => t.id === editing.id);
      setEditing(original ? toEditing(original) : null);
    } else {
      setEditing(null);
      setSelectedId(null);
    }
    setError(null);
  }

  async function submit() {
    if (!editing) return;
    if (!editing.name.trim()) {
      setError("請填範本名稱");
      return;
    }
    if (editing.items.length === 0) {
      setError("至少要有一項零件種類");
      return;
    }
    for (const it of editing.items) {
      if (!it.name.trim() || !it.code.trim()) {
        setError("每個零件種類都要填名稱與代碼");
        return;
      }
    }
    setError(null);
    try {
      // ─── 提交至後端 ────────────────────────────────────
      // 後端用 items_input 接收(write-only),空字串轉成 "0" / 0。
      const body = {
        id: editing.id || undefined,
        name: editing.name,
        note: editing.note,
        is_active: editing.is_active,
        default_capacities: editing.default_capacities,
        default_colors: editing.default_colors,
        default_accessory_categories: editing.default_accessory_categories,
        default_accessory_brands: editing.default_accessory_brands,
        items_input: editing.items.map((it, idx) => ({
          id: it.id,
          name: it.name,
          code: it.code,
          sort_order: idx,
          default_cost: it.default_cost.trim() === "" ? "0" : it.default_cost,
          default_safety_stock:
            it.default_safety_stock.trim() === ""
              ? 0
              : Number(it.default_safety_stock) || 0,
          shared_across_models: it.shared_across_models,
        })),
      };
      const saved = await save.mutateAsync(body);
      setSelectedId(saved.id);
      setEditing(toEditing(saved));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function handleDelete() {
    if (!editing?.id) return;
    if (!confirm(`刪除範本「${editing.name}」?既有零件 SKU 不受影響`)) return;
    try {
      await del.mutateAsync(editing.id);
      setEditing(null);
      setSelectedId(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div className="page">
      <Toolbar
        title="零件範本管理"
        actions={
          <button className="btn primary" onClick={startNew}>
            + 新增範本
          </button>
        }
      />
      <div className="entry-body" style={{ display: "flex", gap: 16 }}>
        {/* ─── 左:範本列表 ─── */}
        <div
          style={{
            width: 260,
            flex: "0 0 260px",
            borderRight: "1px solid var(--border)",
            paddingRight: 12,
          }}
        >
          <div
            style={{
              fontSize: 12,
              color: "var(--text-dim)",
              padding: "4px 0 8px",
            }}
          >
            建立後可在「庫存 → 商品 → 零件批次建立」一鍵展開
          </div>
          {list.isLoading && <div>載入中…</div>}
          {!list.isLoading && (list.data?.length ?? 0) === 0 && !editing && (
            <div style={{ color: "var(--text-dim)", padding: 16 }}>
              尚未建立範本
            </div>
          )}
          {(list.data ?? []).map((t) => (
            <button
              key={t.id}
              type="button"
              className={
                "pt-list-item" + (t.id === selectedId ? " selected" : "")
              }
              onClick={() => pick(t)}
            >
              <div className="pt-list-name">{t.name}</div>
              <div className="pt-list-meta">
                {t.items.length} 種
                {!t.is_active && (
                  <span style={{ marginLeft: 8, color: "#fb923c" }}>停用</span>
                )}
              </div>
            </button>
          ))}
        </div>

        {/* ─── 右:詳情 ─── */}
        <div style={{ flex: 1, minWidth: 0 }}>
          {!editing ? (
            <div
              style={{
                padding: 40,
                textAlign: "center",
                color: "var(--text-dim)",
              }}
            >
              左側選一個範本,或按「+ 新增範本」
            </div>
          ) : (
            <>
              {error && <Banner kind="error" message={error} />}

              {/* ─── 套用常用範本 ─── */}
              <div style={{ marginBottom: 16 }}>
                <div
                  style={{
                    fontSize: 13,
                    color: "var(--text-dim)",
                    marginBottom: 8,
                  }}
                >
                  套用常用範本
                  <span
                    className="info-tip"
                    data-tip="點選一鍵帶入該類型常見的整組零件;若清單已有資料會先清空"
                  >
                    ?
                  </span>
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                  {Object.keys(PRESET_TEMPLATES).map((k) => (
                    <button
                      key={k}
                      type="button"
                      className="pill pill-strong"
                      onClick={() =>
                        applyPreset(k as keyof typeof PRESET_TEMPLATES)
                      }
                    >
                      {k}
                    </button>
                  ))}
                </div>
              </div>

              {/* ─── 範本資訊區 ─── */}
              <div style={{ marginBottom: 20 }}>
                <label
                  style={{
                    display: "block",
                    fontSize: 13,
                    color: "var(--text-dim)",
                    marginBottom: 6,
                  }}
                >
                  範本名稱
                </label>
                <input
                  className="input-lg"
                  value={editing.name}
                  onChange={(e) => patch("name", e.target.value)}
                  placeholder="例:智慧型手機(標準)"
                />

                <div
                  style={{
                    display: "flex",
                    gap: 12,
                    alignItems: "flex-start",
                    marginTop: 14,
                  }}
                >
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <label
                      style={{
                        display: "block",
                        fontSize: 13,
                        color: "var(--text-dim)",
                        marginBottom: 6,
                      }}
                    >
                      備註
                    </label>
                    <textarea
                      rows={2}
                      value={editing.note}
                      onChange={(e) => patch("note", e.target.value)}
                      placeholder="範本用途、適用機型或注意事項…"
                      style={{
                        width: "100%",
                        resize: "vertical",
                        padding: "8px 12px",
                        fontSize: 14,
                        lineHeight: 1.5,
                      }}
                    />
                  </div>
                  <label
                    className="toggle-switch"
                    style={{ paddingTop: 28 }}
                    title="停用後,此範本不會出現在『零件批次建立』選單"
                  >
                    <input
                      type="checkbox"
                      checked={editing.is_active}
                      onChange={(e) => patch("is_active", e.target.checked)}
                    />
                    <span className="toggle-track" />
                    啟用
                  </label>
                </div>
              </div>

              {/* ─── 機型維度預設(wizard 第 2 步會用)─── */}
              <div
                className="section-head"
                style={{ marginTop: 8, marginBottom: 6 }}
              >
                機型維度預設
                <span className="section-head-meta">
                  新增手機型號 wizard 套用此範本後自動帶入,可再微調
                </span>
              </div>

              <div className="form-field">
                <label className="form-field-label">預設容量清單</label>
                <ChipInput
                  value={editing.default_capacities}
                  onChange={(v) => patch("default_capacities", v)}
                  placeholder="輸入後按 Enter / 逗號 / 頓號 加入,例:128GB"
                />
                <div className="form-field-hint">
                  例:128GB / 256GB / 512GB / 1TB。
                  排序就是顯示順序,wizard 第 2 步用這個當預設勾選項。
                </div>
              </div>

              <div className="form-field">
                <label className="form-field-label">預設顏色清單</label>
                <ChipInput
                  value={editing.default_colors}
                  onChange={(v) => patch("default_colors", v)}
                  placeholder="輸入後按 Enter,例:黑"
                />
                <div className="form-field-hint">
                  例:黑 / 白 / 鈦原色。中古機收購時的具體成色寫在序號備註,不放這裡。
                </div>
              </div>

              <div className="form-field">
                <label className="form-field-label">相容配件類別</label>
                <ChipInput
                  value={editing.default_accessory_categories}
                  onChange={(v) => patch("default_accessory_categories", v)}
                  placeholder="輸入後按 Enter,例:殼"
                />
                <div className="form-field-hint">
                  例:殼 / 貼。線、充電器走通用配件不綁機型,不放這裡。
                  「+ 新增手機型號」wizard 會把這些當成「相容類別槽位」記錄,
                  但不會直接建配件 SKU,實際配件商品走「+ 新增配件」獨立建立。
                </div>
              </div>

              <div className="form-field">
                <label className="form-field-label">常用配件品牌</label>
                <ChipInput
                  value={editing.default_accessory_brands}
                  onChange={(v) => patch("default_accessory_brands", v)}
                  placeholder="輸入後按 Enter,例:imos"
                />
                <div className="form-field-hint">
                  例:imos / HODA / JTLEGEND。
                  「+ 新增配件」wizard 套此範本時,會顯示這些品牌讓你一個個建商品線
                  (例:imos 抗藍光保護貼、HODA 軍規防摔殼)。純參考用,不直接建 SKU。
                </div>
              </div>

              {/* ─── 零件種類清單 ─── */}
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  marginBottom: 8,
                }}
              >
                <h4 style={{ margin: 0, flex: 1, fontSize: 16 }}>
                  零件種類
                </h4>
                <span
                  style={{
                    fontSize: 13,
                    color: "var(--text-dim)",
                  }}
                >
                  展開後將建立 <b style={{ color: "var(--text)" }}>{editing.items.length}</b> 種零件
                </span>
              </div>

              {/* 快速加入 */}
              <div style={{ marginBottom: 10 }}>
                <div
                  style={{
                    fontSize: 12,
                    color: "var(--text-dim)",
                    marginBottom: 6,
                  }}
                >
                  快速加入
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                  {QUICK_PARTS.map((p) => (
                    <button
                      key={p.code}
                      type="button"
                      className="pill"
                      onClick={() => addItem({ name: p.name, code: p.code })}
                    >
                      + {p.name}
                    </button>
                  ))}
                </div>
              </div>

              <table className="md-table-inner pt-items-table">
                <thead>
                  <tr>
                    <th>零件名稱</th>
                    <th style={{ width: 100, textAlign: "center" }}>代碼</th>
                    <th style={{ width: 120, textAlign: "right" }}>預設成本</th>
                    <th style={{ width: 130, textAlign: "right" }}>
                      預設安全庫存
                    </th>
                    <th style={{ width: 130, textAlign: "center" }}>
                      跨機型共用
                      <span
                        className="info-tip"
                        data-tip="勾選 = 此零件多機型通用、共用同一料號(例如電池常常一顆電池對應多個機型);不勾 = 各機型各自獨立料號"
                      >
                        ?
                      </span>
                    </th>
                    <th style={{ width: 50 }}></th>
                  </tr>
                </thead>
                <tbody>
                  {editing.items.map((it, idx) => (
                    <tr key={idx}>
                      <td>
                        <input
                          value={it.name}
                          onChange={(e) =>
                            patchItem(idx, { name: e.target.value })
                          }
                          placeholder="例:螢幕總成"
                        />
                      </td>
                      <td>
                        <input
                          value={it.code}
                          onChange={(e) =>
                            patchItem(idx, {
                              code: e.target.value.toUpperCase(),
                            })
                          }
                          placeholder="SCR"
                          maxLength={10}
                          style={{ textAlign: "center" }}
                        />
                      </td>
                      <td>
                        <input
                          type="number"
                          min="0"
                          step="any"
                          value={it.default_cost}
                          onChange={(e) =>
                            patchItem(idx, { default_cost: e.target.value })
                          }
                          placeholder="0"
                          style={{ textAlign: "right" }}
                        />
                      </td>
                      <td>
                        <input
                          type="number"
                          min="0"
                          value={it.default_safety_stock}
                          onChange={(e) =>
                            patchItem(idx, {
                              default_safety_stock: e.target.value,
                            })
                          }
                          placeholder="0"
                          style={{ textAlign: "right" }}
                        />
                      </td>
                      <td style={{ textAlign: "center" }}>
                        <input
                          type="checkbox"
                          checked={it.shared_across_models}
                          onChange={(e) =>
                            patchItem(idx, {
                              shared_across_models: e.target.checked,
                            })
                          }
                        />
                      </td>
                      <td style={{ textAlign: "center" }}>
                        <button
                          type="button"
                          className="icon-btn icon-btn-danger"
                          onClick={() => removeItem(idx)}
                          aria-label="刪除"
                          title="刪除此列"
                        >
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
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>

              <button
                type="button"
                className="btn-add-row"
                onClick={() => addItem()}
              >
                + 加一項
              </button>

              {/* ─── 底部按鈕 ─── */}
              <div
                style={{
                  display: "flex",
                  gap: 8,
                  marginTop: 20,
                  justifyContent: "flex-end",
                  alignItems: "center",
                }}
              >
                {editing.id ? (
                  <button
                    type="button"
                    className="btn danger"
                    onClick={handleDelete}
                    style={{ marginRight: "auto" }}
                  >
                    刪除範本
                  </button>
                ) : null}
                <button type="button" className="btn" onClick={cancel}>
                  取消
                </button>
                <button
                  type="button"
                  className="btn primary btn-save"
                  onClick={submit}
                  disabled={save.isPending}
                >
                  {save.isPending ? "儲存中…" : "儲存範本"}
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
