import { useEffect, useMemo, useState } from "react";

import { useSuppliers, useSaveSupplier } from "@/api/hooks";
import type { Supplier } from "@/api/types";
import { Banner } from "@/components/Banner";
import { PaneBack } from "@/components/PaneBack";
import { Toolbar } from "@/components/Toolbar";
import { useReorder } from "@/hooks/useReorder";
import { errorText } from "@/lib/errorText";
import { useDraftForm } from "@/hooks/useDraftForm";
import { LEAVE_TEXT } from "@/lib/draftGuard";
import { useDlLabels } from "@/hooks/useDlLabels";

type Selection =
  | { kind: "supplier"; id: number }
  | { kind: "new" }
  | null;

interface FormState {
  name: string;
  short_name: string;
  contact: string;
  phone: string;
  tax_id: string;
  address: string;
  note: string;
  is_active: boolean;
}

const EMPTY_FORM: FormState = {
  name: "",
  short_name: "",
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
    short_name: s.short_name ?? "",
    contact: s.contact,
    phone: s.phone,
    tax_id: s.tax_id,
    address: s.address,
    note: s.note,
    is_active: s.is_active,
  };
}

export function SuppliersPage() {
  // 編輯表單的欄名綁到輸入框(讀螢幕、點欄名進那一格;全站控制項 MC-05)
  const dlRef = useDlLabels();
  const suppliersResult = useSuppliers();
  const saveSupplier = useSaveSupplier();

  const [query, setQuery] = useState("");
  const [selection, setSelection] = useState<Selection>(null);
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

  // 放開的當下畫面就換、背景存、全部存完才重抓一次(規則在 lib/reorder.ts、lib/reorderStore.ts)
  const { move: handleReorder, error: orderError } = useReorder({
    queryKey: ["suppliers"],
    path: (id) => `/suppliers/${id}/`,
  });

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

  // 選到一筆 → 載入表單;切到新增 → 清空。只在換了一筆時重填;改過沒存,點別筆 / 新增 / 取消 / × 要按兩次(全站檢視 V01)
  const formKey = selection?.kind === "supplier" ? `s${selection.id}` : selection?.kind === "new" ? "new" : null;
  const draft = useDraftForm<FormState>(
    EMPTY_FORM,
    formKey,
    () => (selection?.kind === "supplier" ? (selectedSupplier ? toForm(selectedSupplier) : null) : EMPTY_FORM),
    [selectedSupplier],
  );
  const form = draft.form;
  const patch = draft.patch;
  useEffect(() => {
    if (formKey === null) return;
    setError(null);
    setFlashMsg(null);
  }, [formKey]);

  function startNew() {
    if (selection?.kind !== "new") draft.leave("new", () => setSelection({ kind: "new" }));
  }

  async function save() {
    const name = form.name.trim();
    if (!name) {
      setError("廠商名稱必填");
      return;
    }
    const payload: Partial<Supplier> & { id?: number } = {
      name,
      short_name: form.short_name.trim(),
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
        draft.saved("new", EMPTY_FORM);
        setFlashMsg(`已新增「${saved.name}」(${saved.code}),可繼續輸入下一筆`);
      } else {
        setFlashMsg("已儲存");
        draft.saved(`s${saved.id}`, toForm(saved));
        setSelection({ kind: "supplier", id: saved.id });
      }
      setTimeout(() => setFlashMsg(null), 2500);
    } catch (e) {
      // 欄位錯誤只留中文那幾句、不露欄位名(全站檢視 G2;規則在 lib/errorText.ts)
      setError(errorText(e));
    }
  }

  const isEditing = selection?.kind === "supplier";
  const isNew = selection?.kind === "new";

  return (
    <div className="page">
      <Toolbar
        title="廠商"
        actions={
          <button className={draft.armed("new") ? "btn armed" : "btn"} onClick={startNew}>
            {draft.armed("new") ? "再按一次新增" : "新增廠商"}
          </button>
        }
      />

      <div className={isEditing || isNew ? "pc-layout pane-page" : "pc-layout pane-page list-only"}>
        <aside className="pc-master" style={{ gridTemplateRows: "1fr" }}>
          <section className="pc-section">
            <div className="pc-section-header">
              廠商
              <span style={{ fontWeight: "normal" }}>
                {!suppliersResult.isLoading && `${filtered.length} 筆`}
              </span>
            </div>
            {orderError && <Banner kind="error" message={orderError} />}
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
                  fontSize: 14,
                  color: "var(--text-dim)",
                }}
              >
                拖曳左側 ≡ 調整順序,常用廠商往前排,挑選時更快
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
                          onClick={() => {
                            if (selection?.kind === "supplier" && selection.id === s.id) return;
                            draft.leave(`row:${s.id}`, () => setSelection({ kind: "supplier", id: s.id }));
                          }}
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
                                ? "var(--success-text-soft)"
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
                          {query ? "查無廠商" : "還沒有廠商"}
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
          <PaneBack open={isEditing || isNew} onClose={() => draft.leave("close", () => setSelection(null))} disabled={saveSupplier.isPending} />

          {(isEditing || isNew) && !draft.ready && <div className="md-empty" style={{ marginTop: 40 }}>載入中…</div>}
          {draft.ready && (
            <div className="pc-detail-body">
              {draft.warning && <div className="pc-detail-warn"><Banner kind="info" message={LEAVE_TEXT} /></div>}
              <h3 className="pc-detail-title">
                {isNew
                  ? "新增廠商"
                  : `廠商 · ${selectedSupplier?.code} ${selectedSupplier?.name}`}
              </h3>
              {error && <Banner kind="error" message={error} />}
              {flashMsg && <Banner kind="success" message={flashMsg} />}
              <dl ref={dlRef}>
                {isEditing && (
                  <>
                    <dt>代碼</dt>
                    <dd>
                      <span style={{ color: "var(--text-dim)" }}>
                        {selectedSupplier?.code}
                      </span>
                    </dd>
                  </>
                )}
                <dt>
                  名稱 <span style={{ color: "var(--danger-text)" }}>*</span>
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
                <dt>簡稱</dt>
                <dd>
                  <input
                    value={form.short_name}
                    onChange={(e) => patch("short_name", e.target.value)}
                    maxLength={20}
                    style={{ width: 120 }}
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
                  className={draft.armed("close") ? "btn armed" : "btn"}
                  onClick={() => draft.leave("close", () => setSelection(null))}
                  disabled={saveSupplier.isPending}
                >
                  {draft.armed("close") ? "再按一次取消" : "取消"}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
