import { useEffect, useMemo, useState } from "react";

import { useSuppliers, useSaveSupplier } from "@/api/hooks";
import { ApiHttpError } from "@/api/client";
import type { Supplier } from "@/api/types";
import { Banner } from "@/components/Banner";
import { Toolbar } from "@/components/Toolbar";

type Selection =
  | { kind: "supplier"; id: number }
  | { kind: "new" }
  | null;

interface FormState {
  name: string;
  contact: string;
  phone: string;
  tax_id: string;
  address: string;
  note: string;
  is_active: boolean;
}

const EMPTY_FORM: FormState = {
  name: "",
  contact: "",
  phone: "",
  tax_id: "",
  address: "",
  note: "",
  is_active: true,
};

function toForm(s: Supplier): FormState {
  return {
    name: s.name,
    contact: s.contact,
    phone: s.phone,
    tax_id: s.tax_id,
    address: s.address,
    note: s.note,
    is_active: s.is_active,
  };
}

export function SuppliersPage() {
  const suppliersResult = useSuppliers();
  const saveSupplier = useSaveSupplier();

  const [query, setQuery] = useState("");
  const [selection, setSelection] = useState<Selection>(null);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [error, setError] = useState<string | null>(null);
  const [flashMsg, setFlashMsg] = useState<string | null>(null);
  const [draggingId, setDraggingId] = useState<number | null>(null);
  const [dragOverId, setDragOverId] = useState<number | null>(null);

  const suppliers = useMemo(() => {
    const list = suppliersResult.data ?? [];
    return [...list].sort(
      (a, b) => a.sort_order - b.sort_order || a.code.localeCompare(b.code),
    );
  }, [suppliersResult.data]);

  async function handleReorder(srcId: number, targetId: number) {
    if (srcId === targetId) return;
    const arr = [...suppliers];
    const fromIdx = arr.findIndex((s) => s.id === srcId);
    const toIdx = arr.findIndex((s) => s.id === targetId);
    if (fromIdx < 0 || toIdx < 0) return;
    const [removed] = arr.splice(fromIdx, 1);
    arr.splice(toIdx, 0, removed);
    const renumbered = arr.map((s, i) => ({ ...s, sort_order: (i + 1) * 10 }));
    const changed = renumbered.filter((s, i) => {
      const before = suppliers[i];
      return !before || before.id !== s.id || before.sort_order !== s.sort_order;
    });
    try {
      await Promise.all(
        changed.map((s) =>
          saveSupplier.mutateAsync({ id: s.id, sort_order: s.sort_order }),
        ),
      );
    } catch (e) {
      setError("排序儲存失敗,請重新整理頁面");
    }
  }

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return suppliers;
    return suppliers.filter(
      (s) =>
        s.code.toLowerCase().includes(q) ||
        s.name.toLowerCase().includes(q) ||
        s.contact.toLowerCase().includes(q) ||
        s.phone.toLowerCase().includes(q) ||
        s.tax_id.toLowerCase().includes(q),
    );
  }, [suppliers, query]);

  const selectedSupplier = useMemo(() => {
    if (selection?.kind !== "supplier") return null;
    return suppliers.find((s) => s.id === selection.id) ?? null;
  }, [selection, suppliers]);

  // 選到一筆 → 載入表單;切到新增 → 清空
  useEffect(() => {
    if (selection?.kind === "supplier" && selectedSupplier) {
      setForm(toForm(selectedSupplier));
      setError(null);
      setFlashMsg(null);
    } else if (selection?.kind === "new") {
      setForm(EMPTY_FORM);
      setError(null);
      setFlashMsg(null);
    }
  }, [selection, selectedSupplier]);

  function patch<K extends keyof FormState>(k: K, v: FormState[K]) {
    setForm((f) => ({ ...f, [k]: v }));
  }

  function startNew() {
    setSelection({ kind: "new" });
  }

  async function save() {
    const name = form.name.trim();
    if (!name) {
      setError("供應商名稱必填");
      return;
    }
    const payload: Partial<Supplier> & { id?: number } = {
      name,
      contact: form.contact.trim(),
      phone: form.phone.trim(),
      tax_id: form.tax_id.trim(),
      address: form.address.trim(),
      note: form.note.trim(),
      is_active: form.is_active,
    };
    const isCreate = selection?.kind !== "supplier";
    if (selection?.kind === "supplier") {
      payload.id = selection.id;
    }
    try {
      const saved = await saveSupplier.mutateAsync(payload);
      setError(null);
      if (isCreate) {
        // 連續新增:清空表單、維持新增模式,讓使用者可直接輸入下一筆
        setForm(EMPTY_FORM);
        setFlashMsg(`已新增「${saved.name}」(${saved.code}),可繼續輸入下一筆`);
      } else {
        setFlashMsg("已儲存");
        setSelection({ kind: "supplier", id: saved.id });
      }
      setTimeout(() => setFlashMsg(null), 2500);
    } catch (e) {
      if (e instanceof ApiHttpError) {
        const body = e.body;
        if (typeof body === "object" && body) {
          // 後端欄位錯誤(例如 code 重複)會回 {code: ["..."]}
          const firstKey = Object.keys(body)[0];
          const msg = Array.isArray((body as Record<string, unknown>)[firstKey])
            ? (body as Record<string, string[]>)[firstKey][0]
            : JSON.stringify(body);
          setError(
            firstKey === "code"
              ? `代碼問題:${msg}`
              : firstKey === "detail"
                ? String(msg)
                : `${firstKey}:${msg}`,
          );
        } else {
          setError(`儲存失敗 (${e.status})`);
        }
      } else {
        setError(String(e));
      }
    }
  }

  const isEditing = selection?.kind === "supplier";
  const isNew = selection?.kind === "new";

  return (
    <div className="page">
      <Toolbar
        title="供應商"
        actions={
          <button className="btn primary" onClick={startNew}>
            + 新增供應商
          </button>
        }
      />

      <div className="pc-layout">
        <aside className="pc-master" style={{ gridTemplateRows: "1fr" }}>
          <section className="pc-section">
            <div className="pc-section-header">
              供應商
              <span style={{ fontWeight: "normal" }}>
                {!suppliersResult.isLoading && `${filtered.length} 筆`}
              </span>
            </div>
            <div className="pc-section-search">
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="搜尋 代碼 / 名稱 / 聯絡人 / 電話 / 統編"
              />
              {query && (
                <button className="btn" onClick={() => setQuery("")}>
                  清除
                </button>
              )}
            </div>
            {!query && filtered.length > 1 && (
              <div
                style={{
                  padding: "2px 10px 6px",
                  fontSize: 12,
                  color: "var(--text-dim)",
                }}
              >
                拖曳左側 ≡ 調整順序,常用供應商往前排,挑選時更快
              </div>
            )}
            <div className="pc-section-body">
              {suppliersResult.isLoading && (
                <div className="md-empty">載入中…</div>
              )}
              {suppliersResult.isError && (
                <div className="md-empty">載入失敗</div>
              )}
              {!suppliersResult.isLoading && !suppliersResult.isError && (
                <table className="pc-list-table">
                  <thead>
                    <tr>
                      <th style={{ width: 28 }}></th>
                      <th style={{ width: 90 }}>代碼</th>
                      <th>名稱</th>
                      <th style={{ width: 100 }}>電話</th>
                      <th style={{ width: 44 }}>狀態</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.map((s) => {
                      const canDrag = !query;
                      return (
                        <tr
                          key={s.id}
                          draggable={canDrag}
                          onDragStart={(e) => {
                            if (!canDrag) return;
                            setDraggingId(s.id);
                            e.dataTransfer.effectAllowed = "move";
                            e.dataTransfer.setData("text/plain", String(s.id));
                          }}
                          onDragOver={(e) => {
                            if (!canDrag) return;
                            e.preventDefault();
                            if (dragOverId !== s.id) setDragOverId(s.id);
                          }}
                          onDragLeave={() => setDragOverId(null)}
                          onDrop={(e) => {
                            if (!canDrag) return;
                            e.preventDefault();
                            const src = draggingId;
                            setDraggingId(null);
                            setDragOverId(null);
                            if (src != null) handleReorder(src, s.id);
                          }}
                          onDragEnd={() => {
                            setDraggingId(null);
                            setDragOverId(null);
                          }}
                          onClick={() =>
                            setSelection({ kind: "supplier", id: s.id })
                          }
                          className={[
                            selection?.kind === "supplier" &&
                            selection.id === s.id
                              ? "selected"
                              : "",
                            draggingId === s.id ? "row-dragging" : "",
                            dragOverId === s.id && draggingId !== s.id
                              ? "row-drag-over"
                              : "",
                          ]
                            .filter(Boolean)
                            .join(" ")}
                        >
                          <td
                            className="drag-handle"
                            style={{
                              cursor: canDrag ? "grab" : "default",
                              color: canDrag
                                ? "var(--text-dim)"
                                : "transparent",
                            }}
                            title={canDrag ? "拖曳調整排序" : "搜尋中無法排序"}
                          >
                            ≡
                          </td>
                          <td>{s.code}</td>
                          <td>{s.name}</td>
                          <td>{s.phone || "—"}</td>
                          <td
                            style={{
                              color: s.is_active
                                ? "#80d090"
                                : "var(--text-dim)",
                            }}
                          >
                            {s.is_active ? "啟用" : "停用"}
                          </td>
                        </tr>
                      );
                    })}
                    {filtered.length === 0 && (
                      <tr>
                        <td colSpan={5} className="md-empty">
                          {query ? "查無供應商" : "尚無供應商,按右上角新增"}
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              )}
            </div>
          </section>
        </aside>

        <div className="pc-detail">
          {!isEditing && !isNew && (
            <div className="md-empty" style={{ marginTop: 40 }}>
              從左側選擇供應商以檢視 / 編輯,或按右上角「新增供應商」
            </div>
          )}

          {(isEditing || isNew) && (
            <div className="pc-detail-body">
              <h3 className="pc-detail-title">
                {isNew
                  ? "新增供應商"
                  : `供應商 · ${selectedSupplier?.code} ${selectedSupplier?.name}`}
              </h3>
              {error && <Banner kind="error" message={error} />}
              {flashMsg && <Banner kind="success" message={flashMsg} />}
              <dl>
                {isEditing && (
                  <>
                    <dt>代碼</dt>
                    <dd>
                      <span style={{ color: "var(--text-dim)" }}>
                        {selectedSupplier?.code}
                      </span>
                      <span
                        style={{
                          marginLeft: 8,
                          fontSize: 12,
                          color: "var(--text-dim)",
                        }}
                      >
                        (系統自動產生)
                      </span>
                    </dd>
                  </>
                )}
                <dt>
                  名稱 <span style={{ color: "#ff7070" }}>*</span>
                </dt>
                <dd>
                  <input
                    value={form.name}
                    onChange={(e) => patch("name", e.target.value)}
                    maxLength={120}
                    placeholder="例:蘋果經銷"
                    style={{ width: 280 }}
                  />
                </dd>
                <dt>聯絡人</dt>
                <dd>
                  <input
                    value={form.contact}
                    onChange={(e) => patch("contact", e.target.value)}
                    maxLength={60}
                    style={{ width: 200 }}
                  />
                </dd>
                <dt>電話</dt>
                <dd>
                  <input
                    value={form.phone}
                    onChange={(e) => patch("phone", e.target.value)}
                    maxLength={40}
                    style={{ width: 200 }}
                  />
                </dd>
                <dt>統一編號</dt>
                <dd>
                  <input
                    value={form.tax_id}
                    onChange={(e) => patch("tax_id", e.target.value)}
                    maxLength={20}
                    style={{ width: 160 }}
                  />
                </dd>
                <dt>地址</dt>
                <dd>
                  <input
                    value={form.address}
                    onChange={(e) => patch("address", e.target.value)}
                    maxLength={200}
                    style={{ width: "100%", maxWidth: 460 }}
                  />
                </dd>
                <dt>備註</dt>
                <dd>
                  <input
                    value={form.note}
                    onChange={(e) => patch("note", e.target.value)}
                    maxLength={200}
                    style={{ width: "100%", maxWidth: 460 }}
                  />
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
                      checked={form.is_active}
                      onChange={(e) => patch("is_active", e.target.checked)}
                    />
                    {form.is_active ? "啟用" : "停用"}
                  </label>
                </dd>
              </dl>
              <div style={{ marginTop: 16, display: "flex", gap: 8 }}>
                <button
                  className="btn primary"
                  onClick={save}
                  disabled={saveSupplier.isPending}
                >
                  {saveSupplier.isPending ? "儲存中…" : "儲存"}
                </button>
                <button
                  className="btn"
                  onClick={() => setSelection(null)}
                  disabled={saveSupplier.isPending}
                >
                  取消
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
