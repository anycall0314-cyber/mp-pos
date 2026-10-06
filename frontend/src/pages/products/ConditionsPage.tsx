import { useState } from "react";

import {
  useConditions,
  useDeleteCondition,
  useSaveCondition,
} from "@/api/hooks";
import type { Condition } from "@/api/types";
import { Banner } from "@/components/Banner";
import { Toolbar } from "@/components/Toolbar";

interface Editing {
  id?: number;
  code: string;
  name: string;
  is_secondhand: boolean;
  tracks_unit_condition: boolean;
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
      .slice(0, 20) || `cond-${Date.now()}`
  );
}

export function ConditionsPage() {
  // ─── 後端串接 ──────────────────────────────────────
  const conditions = useConditions();         // GET /conditions/
  const save = useSaveCondition();            // POST / PATCH /conditions/
  const del = useDeleteCondition();           // DELETE /conditions/:id/

  const [editing, setEditing] = useState<Editing | null>(null);
  const [error, setError] = useState<string | null>(null);

  function startNew() {
    setEditing({
      code: "",
      name: "",
      is_secondhand: false,
      tracks_unit_condition: true,
      sort_order: (conditions.data?.length ?? 0) + 1,
      is_active: true,
    });
    setError(null);
  }

  function startEdit(c: Condition) {
    setEditing({
      id: c.id,
      code: c.code,
      name: c.name,
      is_secondhand: c.is_secondhand,
      tracks_unit_condition: c.tracks_unit_condition,
      sort_order: c.sort_order,
      is_active: c.is_active,
    });
    setError(null);
  }

  async function submit() {
    if (!editing) return;
    if (!editing.name.trim()) {
      setError("請填品況名稱");
      return;
    }
    const code = editing.code.trim() || slugify(editing.name);
    // 名稱含「中古」自動勾「視為中古機」(user 仍可手動取消)
    const auto_secondhand =
      editing.is_secondhand ||
      editing.name.includes("中古") ||
      editing.name.toLowerCase().includes("used");
    try {
      await save.mutateAsync({
        ...editing,
        code,
        is_secondhand: auto_secondhand,
        tracks_unit_condition:
          auto_secondhand || editing.tracks_unit_condition,
      });
      setEditing(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function handleDelete(c: Condition) {
    if (
      !confirm(
        `刪除品況「${c.name}」?\n` +
          `已經有 ${c.product_count ?? 0} 個商品是這個品況的話刪不掉:請先把那些商品改成別的品況,或改成停用。`,
      )
    )
      return;
    try {
      await del.mutateAsync(c.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div className="page">
      <Toolbar
        title="商品品況"
        actions={
          <button className="btn primary" onClick={startNew}>
            + 新增品況
          </button>
        }
      />

      <div className="entry-body">
        <div
          style={{
            fontSize: 16,
            color: "var(--text-dim)",
            marginBottom: 16,
            lineHeight: 1.6,
          }}
        >
          「新增手機型號」時選的品況。預設有全新 / 已拆封 / 中古機(保固內)/ 中古機,可以自己增刪改。
          <br />
          名稱有「中古」會自動勾「視為中古機」:這個品況的商品每一台各記成本。
        </div>

        {error && <Banner kind="error" message={error} />}

        {/* 編輯 inline */}
        {editing && (
          <div className="form-card">
            <div className="section-head">
              {editing.id ? "編輯品況" : "新增品況"}
            </div>

            <div className="form-field">
              <label className="form-field-label" htmlFor="cd-name">
                品況名稱<span className="required">*</span>
              </label>
              <input
                id="cd-name"
                className="input-lg"
                value={editing.name}
                onChange={(e) =>
                  setEditing({ ...editing, name: e.target.value })
                }
                placeholder="例:全新 / 已拆封 / 中古機(保固內)"
                autoFocus
              />
            </div>

            <div className="form-row-2col">
              <div className="form-field" style={{ marginBottom: 0 }}>
                <label className="form-field-label" htmlFor="cd-code">
                  品況代碼
                </label>
                <input
                  id="cd-code"
                  value={editing.code}
                  onChange={(e) =>
                    setEditing({ ...editing, code: e.target.value })
                  }
                  placeholder="留空自動產生"
                />
                <div className="form-field-hint">
                  留空時依名稱自動產,例:全新 → brand-new
                </div>
              </div>
              <div className="form-field" style={{ marginBottom: 0 }}>
                <label className="form-field-label" htmlFor="cd-sort">
                  顯示排序
                </label>
                <input
                  id="cd-sort"
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

            <div className="form-field" style={{ marginTop: 18 }}>
              <label className="toggle-switch">
                <input
                  type="checkbox"
                  checked={editing.is_secondhand}
                  onChange={(e) =>
                    setEditing({
                      ...editing,
                      is_secondhand: e.target.checked,
                      // 中古機一定要逐台記(成色與每台成本本來就必填)
                      tracks_unit_condition: e.target.checked
                        ? true
                        : editing.tracks_unit_condition,
                    })
                  }
                />
                <span className="toggle-track" />
                視為中古機
              </label>
              <div className="form-field-hint">
                每隻獨立成本。名稱含「中古」會自動勾起來
              </div>
            </div>

            <div className="form-field">
              <label className="toggle-switch">
                <input
                  type="checkbox"
                  checked={editing.tracks_unit_condition}
                  disabled={editing.is_secondhand}
                  onChange={(e) =>
                    setEditing({
                      ...editing,
                      tracks_unit_condition: e.target.checked,
                    })
                  }
                />
                <span className="toggle-track" />
                逐台記機況
              </label>
              <div className="form-field-hint">
                {editing.is_secondhand
                  ? "中古機必開,不可關閉"
                  : "進貨可逐台記成色 / 電池 / 售價 / 備註"}
              </div>
            </div>

            <div className="form-field">
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
                停用後新增手機型號時不能選。
              </div>
            </div>

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
                {save.isPending ? "儲存中…" : "儲存品況"}
              </button>
            </div>
          </div>
        )}

        <div className="section-head">
          已建立品況
          <span className="section-head-meta">
            共 {conditions.data?.length ?? 0} 種
          </span>
        </div>

        {conditions.isLoading && <div>載入中…</div>}
        {!conditions.isLoading && (conditions.data?.length ?? 0) === 0 && (
          <div className="empty-cta">
            <div className="empty-cta-title">尚未建立任何品況</div>
            <div className="empty-cta-desc">
              預設值由系統 seed 4 個。如果這裡是空的,
              <br />
              代表 migration 還沒跑,請聯絡系統管理員。
            </div>
            <button className="btn primary btn-save" onClick={startNew}>
              + 自己建一個
            </button>
          </div>
        )}

        {(conditions.data?.length ?? 0) > 0 && (
          <table className="md-table-inner">
            <thead>
              <tr>
                <th style={{ width: 60 }}>排序</th>
                <th style={{ width: 160 }}>代碼</th>
                <th>名稱</th>
                <th style={{ width: 110, textAlign: "center" }}>
                  視為中古機
                </th>
                <th style={{ width: 110, textAlign: "center" }}>
                  逐台記機況
                </th>
                <th style={{ width: 100, textAlign: "center" }}>商品數</th>
                <th style={{ width: 80 }}>啟用</th>
                <th style={{ width: 160 }}></th>
              </tr>
            </thead>
            <tbody>
              {(conditions.data ?? []).map((c) => (
                <tr key={c.id}>
                  <td>{c.sort_order}</td>
                  <td>
                    <code style={{ fontSize: 14 }}>{c.code}</code>
                  </td>
                  <td>
                    <b>{c.name}</b>
                  </td>
                  <td style={{ textAlign: "center" }}>
                    {c.is_secondhand ? (
                      <span
                        style={{
                          padding: "2px 8px",
                          borderRadius: 999,
                          background: "rgba(251, 146, 60, 0.15)",
                          color: "var(--warn-text-orange)",
                          fontSize: 14,
                          fontWeight: 500,
                        }}
                      >
                        中古機
                      </span>
                    ) : (
                      <span style={{ color: "var(--text-dim)" }}>—</span>
                    )}
                  </td>
                  <td style={{ textAlign: "center" }}>
                    {c.tracks_unit_condition ? (
                      <span style={{ color: "var(--success-text)" }}>是</span>
                    ) : (
                      <span style={{ color: "var(--text-dim)" }}>—</span>
                    )}
                  </td>
                  <td style={{ textAlign: "center" }}>{c.product_count ?? 0}</td>
                  <td>
                    {c.is_active ? (
                      <span style={{ color: "var(--success-text)" }}>啟用</span>
                    ) : (
                      <span style={{ color: "var(--warn-text-orange)" }}>停用</span>
                    )}
                  </td>
                  <td>
                    <button
                      type="button"
                      className="btn"
                      onClick={() => startEdit(c)}
                    >
                      編輯
                    </button>
                    <button
                      type="button"
                      className="btn danger"
                      onClick={() => handleDelete(c)}
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
