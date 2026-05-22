import { useEffect, useMemo, useState } from "react";

import { ApiHttpError } from "@/api/client";
import { useSalesPersons, useSaveSalesPerson } from "@/api/hooks";
import type { SalesPerson } from "@/api/types";
import { Banner } from "@/components/Banner";
import { Toolbar } from "@/components/Toolbar";

type Selection = { kind: "person"; id: number } | { kind: "new" } | null;

interface FormState {
  code: string;
  name: string;
  phone: string;
  note: string;
  is_active: boolean;
}

const EMPTY_FORM: FormState = {
  code: "",
  name: "",
  phone: "",
  note: "",
  is_active: true,
};

function toForm(s: SalesPerson): FormState {
  return {
    code: s.code,
    name: s.name,
    phone: s.phone,
    note: s.note,
    is_active: s.is_active,
  };
}

export function SalesPersonsPage() {
  const result = useSalesPersons();
  const save = useSaveSalesPerson();

  const [query, setQuery] = useState("");
  const [selection, setSelection] = useState<Selection>(null);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [error, setError] = useState<string | null>(null);
  const [savedFlash, setSavedFlash] = useState(false);

  const people = useMemo(() => {
    const list = result.data ?? [];
    return [...list].sort((a, b) => a.code.localeCompare(b.code));
  }, [result.data]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return people;
    return people.filter(
      (s) =>
        s.code.toLowerCase().includes(q) ||
        s.name.toLowerCase().includes(q) ||
        s.phone.toLowerCase().includes(q),
    );
  }, [people, query]);

  const selected = useMemo(() => {
    if (selection?.kind !== "person") return null;
    return people.find((s) => s.id === selection.id) ?? null;
  }, [selection, people]);

  useEffect(() => {
    if (selection?.kind === "person" && selected) {
      setForm(toForm(selected));
      setError(null);
      setSavedFlash(false);
    } else if (selection?.kind === "new") {
      setForm(EMPTY_FORM);
      setError(null);
      setSavedFlash(false);
    }
  }, [selection, selected]);

  function patch<K extends keyof FormState>(k: K, v: FormState[K]) {
    setForm((f) => ({ ...f, [k]: v }));
  }

  async function handleSave() {
    const code = form.code.trim().toUpperCase();
    const name = form.name.trim();
    if (!code) {
      setError("業務員代號必填");
      return;
    }
    if (!name) {
      setError("姓名必填");
      return;
    }
    const payload: Partial<SalesPerson> & { id?: number } = {
      code,
      name,
      phone: form.phone.trim(),
      note: form.note.trim(),
      is_active: form.is_active,
    };
    if (selection?.kind === "person") payload.id = selection.id;
    try {
      const saved = await save.mutateAsync(payload);
      setError(null);
      setSavedFlash(true);
      setTimeout(() => setSavedFlash(false), 2000);
      setSelection({ kind: "person", id: saved.id });
    } catch (e) {
      if (e instanceof ApiHttpError) {
        const body = e.body;
        if (typeof body === "object" && body) {
          const firstKey = Object.keys(body)[0];
          const msg = Array.isArray((body as Record<string, unknown>)[firstKey])
            ? (body as Record<string, string[]>)[firstKey][0]
            : JSON.stringify(body);
          setError(firstKey === "code" ? `代號問題:${msg}` : `${firstKey}:${msg}`);
        } else {
          setError(`儲存失敗 (${e.status})`);
        }
      } else {
        setError(String(e));
      }
    }
  }

  const isEditing = selection?.kind === "person";
  const isNew = selection?.kind === "new";

  return (
    <div className="page">
      <Toolbar
        title="業務員"
        actions={
          <button className="btn primary" onClick={() => setSelection({ kind: "new" })}>
            + 新增業務員
          </button>
        }
      />

      <div className="pc-layout">
        <aside className="pc-master" style={{ gridTemplateRows: "1fr" }}>
          <section className="pc-section">
            <div className="pc-section-header">
              業務員
              <span style={{ fontWeight: "normal" }}>
                {!result.isLoading && `${filtered.length} 筆`}
              </span>
            </div>
            <div className="pc-section-search">
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="搜尋 代號 / 姓名 / 電話"
              />
              {query && (
                <button className="btn" onClick={() => setQuery("")}>
                  清除
                </button>
              )}
            </div>
            <div className="pc-section-body">
              {result.isLoading && <div className="md-empty">載入中…</div>}
              {result.isError && <div className="md-empty">載入失敗</div>}
              {!result.isLoading && !result.isError && (
                <table className="pc-list-table">
                  <thead>
                    <tr>
                      <th style={{ width: 90 }}>代號</th>
                      <th>姓名</th>
                      <th style={{ width: 110 }}>電話</th>
                      <th style={{ width: 44 }}>狀態</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.map((s) => (
                      <tr
                        key={s.id}
                        onClick={() => setSelection({ kind: "person", id: s.id })}
                        className={
                          selection?.kind === "person" && selection.id === s.id
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
                          {query ? "查無業務員" : "尚無業務員,按右上角新增"}
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
              從左側選擇業務員以檢視 / 編輯,或按右上角「新增業務員」
            </div>
          )}

          {(isEditing || isNew) && (
            <div className="pc-detail-body">
              <h3 className="pc-detail-title">
                {isNew ? "新增業務員" : `業務員 · ${selected?.code} ${selected?.name}`}
              </h3>
              {error && <Banner kind="error" message={error} />}
              {savedFlash && <Banner kind="success" message="已儲存" />}
              <dl>
                <dt>
                  代號 <span style={{ color: "#ff7070" }}>*</span>
                </dt>
                <dd>
                  <input
                    value={form.code}
                    onChange={(e) => patch("code", e.target.value.toUpperCase())}
                    maxLength={20}
                    placeholder="例:S01 / WU"
                    style={{ width: 200 }}
                  />
                </dd>
                <dt>
                  姓名 <span style={{ color: "#ff7070" }}>*</span>
                </dt>
                <dd>
                  <input
                    value={form.name}
                    onChange={(e) => patch("name", e.target.value)}
                    maxLength={120}
                    style={{ width: 280 }}
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
                    style={{ display: "inline-flex", gap: 6, alignItems: "center" }}
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
                  onClick={handleSave}
                  disabled={save.isPending}
                >
                  {save.isPending ? "儲存中…" : "儲存"}
                </button>
                <button
                  className="btn"
                  onClick={() => setSelection(null)}
                  disabled={save.isPending}
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
