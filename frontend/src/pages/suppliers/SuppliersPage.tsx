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
  code: string;
  name: string;
  contact: string;
  phone: string;
  tax_id: string;
  address: string;
  note: string;
  is_active: boolean;
}

const EMPTY_FORM: FormState = {
  code: "",
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
    code: s.code,
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
  const [savedFlash, setSavedFlash] = useState(false);

  const suppliers = useMemo(() => {
    const list = suppliersResult.data ?? [];
    return [...list].sort((a, b) => a.code.localeCompare(b.code));
  }, [suppliersResult.data]);

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
      setSavedFlash(false);
    } else if (selection?.kind === "new") {
      setForm(EMPTY_FORM);
      setError(null);
      setSavedFlash(false);
    }
  }, [selection, selectedSupplier]);

  function patch<K extends keyof FormState>(k: K, v: FormState[K]) {
    setForm((f) => ({ ...f, [k]: v }));
  }

  function startNew() {
    setSelection({ kind: "new" });
  }

  async function save() {
    const code = form.code.trim().toUpperCase();
    const name = form.name.trim();
    if (!code) {
      setError("供應商代碼必填");
      return;
    }
    if (!name) {
      setError("供應商名稱必填");
      return;
    }
    const payload: Partial<Supplier> & { id?: number } = {
      code,
      name,
      contact: form.contact.trim(),
      phone: form.phone.trim(),
      tax_id: form.tax_id.trim(),
      address: form.address.trim(),
      note: form.note.trim(),
      is_active: form.is_active,
    };
    if (selection?.kind === "supplier") {
      payload.id = selection.id;
    }
    try {
      const saved = await saveSupplier.mutateAsync(payload);
      setError(null);
      setSavedFlash(true);
      setTimeout(() => setSavedFlash(false), 2000);
      // 新增完成後切到該筆編輯畫面
      setSelection({ kind: "supplier", id: saved.id });
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
                      <th style={{ width: 90 }}>代碼</th>
                      <th>名稱</th>
                      <th style={{ width: 100 }}>電話</th>
                      <th style={{ width: 44 }}>狀態</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.map((s) => (
                      <tr
                        key={s.id}
                        onClick={() =>
                          setSelection({ kind: "supplier", id: s.id })
                        }
                        className={
                          selection?.kind === "supplier" &&
                          selection.id === s.id
                            ? "selected"
                            : ""
                        }
                      >
                        <td>{s.code}</td>
                        <td>{s.name}</td>
                        <td>{s.phone || "—"}</td>
                        <td
                          style={{
                            color: s.is_active ? "#80d090" : "var(--text-dim)",
                          }}
                        >
                          {s.is_active ? "啟用" : "停用"}
                        </td>
                      </tr>
                    ))}
                    {filtered.length === 0 && (
                      <tr>
                        <td colSpan={4} className="md-empty">
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
              {savedFlash && <Banner kind="success" message="已儲存" />}
              <dl>
                <dt>
                  代碼 <span style={{ color: "#ff7070" }}>*</span>
                </dt>
                <dd>
                  <input
                    value={form.code}
                    onChange={(e) =>
                      patch("code", e.target.value.toUpperCase())
                    }
                    maxLength={20}
                    placeholder="例:APPLE / SAMSUNG"
                    style={{ width: 200 }}
                  />
                </dd>
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
