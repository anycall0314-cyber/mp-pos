import { useEffect, useState } from "react";

import {
  useDeletePartTemplate,
  usePartTemplates,
  useSavePartTemplate,
} from "@/api/hooks";
import type { PartTemplate, PartTemplateItem } from "@/api/types";
import { Banner } from "@/components/Banner";
import { Toolbar } from "@/components/Toolbar";

export function PartTemplatesPage() {
  const list = usePartTemplates();
  const save = useSavePartTemplate();
  const del = useDeletePartTemplate();

  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [editing, setEditing] = useState<PartTemplate | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!editing && (list.data?.length ?? 0) > 0 && selectedId === null) {
      const first = list.data![0];
      setSelectedId(first.id);
      setEditing(first);
    }
  }, [list.data]);

  function startNew() {
    setSelectedId(null);
    setEditing({
      id: 0,
      name: "",
      note: "",
      is_active: true,
      items: [
        { name: "螢幕總成", code: "SCR", sort_order: 0, default_cost: "0", default_safety_stock: 0, shared_across_models: false },
        { name: "電池", code: "BAT", sort_order: 1, default_cost: "0", default_safety_stock: 0, shared_across_models: false },
      ],
      created_at: "",
      updated_at: "",
    });
  }

  function pick(t: PartTemplate) {
    setSelectedId(t.id);
    setEditing(t);
    setError(null);
  }

  function patch<K extends keyof PartTemplate>(k: K, v: PartTemplate[K]) {
    if (!editing) return;
    setEditing({ ...editing, [k]: v });
  }

  function patchItem(idx: number, partial: Partial<PartTemplateItem>) {
    if (!editing) return;
    const items = [...editing.items];
    items[idx] = { ...items[idx], ...partial };
    setEditing({ ...editing, items });
  }

  function addItem() {
    if (!editing) return;
    setEditing({
      ...editing,
      items: [
        ...editing.items,
        {
          name: "",
          code: "",
          sort_order: editing.items.length,
          default_cost: "0",
          default_safety_stock: 0,
          shared_across_models: false,
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
      const body = {
        id: editing.id || undefined,
        name: editing.name,
        note: editing.note,
        is_active: editing.is_active,
        items_input: editing.items.map((it, idx) => ({
          id: it.id,
          name: it.name,
          code: it.code,
          sort_order: idx,
          default_cost: it.default_cost,
          default_safety_stock: it.default_safety_stock,
          shared_across_models: it.shared_across_models,
        })),
      };
      const saved = await save.mutateAsync(body);
      setSelectedId(saved.id);
      setEditing(saved);
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
        {/* 左:範本列表 */}
        <div
          style={{
            width: 260,
            flex: "0 0 260px",
            borderRight: "1px solid var(--border)",
            paddingRight: 12,
          }}
        >
          <div style={{ fontSize: 12, color: "var(--text-dim)", padding: "4px 0 8px" }}>
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
              className={"pt-list-item" + (t.id === selectedId ? " selected" : "")}
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

        {/* 右:詳情 */}
        <div style={{ flex: 1, minWidth: 0 }}>
          {!editing ? (
            <div style={{ padding: 40, textAlign: "center", color: "var(--text-dim)" }}>
              左側選一個範本,或按「新增範本」
            </div>
          ) : (
            <>
              {error && <Banner kind="error" message={error} />}
              <div style={{ display: "grid", gridTemplateColumns: "2fr 3fr auto", gap: 12, marginBottom: 16, alignItems: "end" }}>
                <label>
                  範本名稱
                  <input
                    value={editing.name}
                    onChange={(e) => patch("name", e.target.value)}
                    placeholder="智慧型手機(標準)"
                  />
                </label>
                <label>
                  備註
                  <input
                    value={editing.note}
                    onChange={(e) => patch("note", e.target.value)}
                  />
                </label>
                <label style={{ display: "inline-flex", gap: 6, alignItems: "center", paddingBottom: 6 }}>
                  <input
                    type="checkbox"
                    checked={editing.is_active}
                    onChange={(e) => patch("is_active", e.target.checked)}
                  />
                  啟用
                </label>
              </div>

              <div style={{ display: "flex", alignItems: "center", marginBottom: 8 }}>
                <h4 style={{ margin: 0, flex: 1 }}>零件種類</h4>
                <button className="btn" onClick={addItem}>
                  + 加一項
                </button>
              </div>

              <table className="md-table-inner pt-items-table">
                <thead>
                  <tr>
                    <th>零件種類名稱</th>
                    <th style={{ width: 100 }}>代碼</th>
                    <th style={{ width: 110 }}>預設成本</th>
                    <th style={{ width: 110 }}>預設安全庫存</th>
                    <th
                      style={{ width: 110 }}
                      title="勾選後此零件在批次建立時不會逐機型展開,而是每個品牌建一筆共用 SKU,相容多個選定機型"
                    >
                      跨機型共用
                    </th>
                    <th style={{ width: 60 }}></th>
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
                          placeholder="例:SCR"
                          maxLength={10}
                        />
                      </td>
                      <td>
                        <input
                          type="number"
                          min="0"
                          value={it.default_cost}
                          onChange={(e) =>
                            patchItem(idx, { default_cost: e.target.value })
                          }
                        />
                      </td>
                      <td>
                        <input
                          type="number"
                          min="0"
                          value={it.default_safety_stock}
                          onChange={(e) =>
                            patchItem(idx, {
                              default_safety_stock:
                                Number(e.target.value) || 0,
                            })
                          }
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
                          title={
                            it.shared_across_models
                              ? "共用 — 同品牌只建一筆 SKU,相容多機型"
                              : "勾選 = 跨機型共用(常用於電池等少數零件)"
                          }
                        />
                      </td>
                      <td>
                        <button
                          type="button"
                          className="btn danger"
                          onClick={() => removeItem(idx)}
                        >
                          刪
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>

              <div style={{ display: "flex", gap: 8, marginTop: 16, justifyContent: "flex-end" }}>
                {editing.id ? (
                  <button className="btn danger" onClick={handleDelete}>
                    刪除範本
                  </button>
                ) : null}
                <button
                  className="btn primary"
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
