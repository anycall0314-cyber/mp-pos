import { useState } from "react";

import {
  useDeleteProductType,
  useProductTypes,
  useSaveProductType,
} from "@/api/hooks";
import type { ProductType } from "@/api/types";
import { Banner } from "@/components/Banner";
import { Toolbar } from "@/components/Toolbar";

interface EditingType {
  id?: number;
  code: string;
  name: string;
  sort_order: number;
  is_active: boolean;
}

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

export function ProductTypesPage() {
  const types = useProductTypes();
  const save = useSaveProductType();
  const del = useDeleteProductType();
  const [editing, setEditing] = useState<EditingType | null>(null);
  const [error, setError] = useState<string | null>(null);

  function startNew() {
    setEditing({
      code: "",
      name: "",
      sort_order: (types.data?.length ?? 0) + 1,
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
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div className="page">
      <Toolbar
        title="產品類型管理"
        actions={
          <button className="btn primary" onClick={startNew}>
            + 新增類型
          </button>
        }
      />
      <div className="entry-body">
        <div
          style={{
            fontSize: 13,
            color: "var(--text-dim)",
            marginBottom: 12,
            lineHeight: 1.6,
          }}
        >
          產品類型用來標示「系列屬於哪一類產品」:手機、平板、耳機、手錶、智慧家電…
          <br />
          建立後可在「品牌 / 系列管理」新增系列時挑選,讓同品牌混放不同類型的系列。
        </div>

        {error && <Banner kind="error" message={error} />}

        {/* 編輯 inline */}
        {editing && (
          <div className="pf-inline-modal" style={{ marginBottom: 16 }}>
            <div className="pf-inline-modal-title">
              {editing.id ? "編輯類型" : "新增類型"}
            </div>
            <div
              className="pf-inline-modal-body"
              style={{ flexWrap: "wrap", gap: 8 }}
            >
              <input
                placeholder="名稱(例:手機 / 平板 / 耳機)"
                value={editing.name}
                onChange={(e) =>
                  setEditing({ ...editing, name: e.target.value })
                }
                style={{ flex: "1 1 200px" }}
              />
              <input
                placeholder="代碼(留空自動產)"
                value={editing.code}
                onChange={(e) =>
                  setEditing({ ...editing, code: e.target.value })
                }
                style={{ width: 160 }}
              />
              <input
                type="number"
                min={0}
                value={editing.sort_order}
                onChange={(e) =>
                  setEditing({
                    ...editing,
                    sort_order: Number(e.target.value) || 0,
                  })
                }
                style={{ width: 80 }}
                title="排序"
              />
              <label
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 4,
                  fontSize: 13,
                }}
              >
                <input
                  type="checkbox"
                  checked={editing.is_active}
                  onChange={(e) =>
                    setEditing({ ...editing, is_active: e.target.checked })
                  }
                />
                啟用
              </label>
              <button
                type="button"
                className="btn"
                onClick={() => setEditing(null)}
              >
                取消
              </button>
              <button
                type="button"
                className="btn primary"
                onClick={submit}
                disabled={save.isPending}
              >
                {save.isPending ? "儲存中…" : "儲存"}
              </button>
            </div>
          </div>
        )}

        {types.isLoading && <div>載入中…</div>}
        {!types.isLoading && (types.data?.length ?? 0) === 0 && (
          <div
            style={{
              padding: 40,
              textAlign: "center",
              color: "var(--text-dim)",
            }}
          >
            尚未建立任何產品類型。按右上「+ 新增類型」開始。
          </div>
        )}
        {(types.data?.length ?? 0) > 0 && (
          <table className="md-table-inner">
            <thead>
              <tr>
                <th style={{ width: 60 }}>排序</th>
                <th style={{ width: 140 }}>代碼</th>
                <th>名稱</th>
                <th style={{ width: 100 }}>系列數</th>
                <th style={{ width: 80 }}>啟用</th>
                <th style={{ width: 140 }}></th>
              </tr>
            </thead>
            <tbody>
              {(types.data ?? []).map((t) => (
                <tr key={t.id}>
                  <td>{t.sort_order}</td>
                  <td>
                    <code style={{ fontSize: 12 }}>{t.code}</code>
                  </td>
                  <td>
                    <b>{t.name}</b>
                  </td>
                  <td>{t.series_count ?? 0}</td>
                  <td>
                    {t.is_active ? (
                      <span style={{ color: "#4ade80" }}>啟用</span>
                    ) : (
                      <span style={{ color: "#fb923c" }}>停用</span>
                    )}
                  </td>
                  <td>
                    <button
                      type="button"
                      className="btn"
                      onClick={() => startEdit(t)}
                    >
                      編輯
                    </button>
                    <button
                      type="button"
                      className="btn danger"
                      onClick={() => handleDelete(t)}
                      style={{ marginLeft: 4 }}
                    >
                      刪除
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
