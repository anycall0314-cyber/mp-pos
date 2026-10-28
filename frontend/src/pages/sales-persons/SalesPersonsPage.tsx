import { useEffect, useMemo, useState } from "react";

import { useSalesPersons, useSaveSalesPerson } from "@/api/hooks";
import type { SalesPerson } from "@/api/types";
import { Banner } from "@/components/Banner";
import { PaneBack } from "@/components/PaneBack";
import { Toolbar } from "@/components/Toolbar";
import { errorText } from "@/lib/errorText";
import { useDraftForm } from "@/hooks/useDraftForm";
import { LEAVE_TEXT } from "@/lib/draftGuard";
import { useDlLabels } from "@/hooks/useDlLabels";

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
  // 編輯表單的欄名綁到輸入框(讀螢幕、點欄名進那一格;全站控制項 MC-05)
  const dlRef = useDlLabels();
  const result = useSalesPersons();
  const save = useSaveSalesPerson();

  const [query, setQuery] = useState("");
  const [selection, setSelection] = useState<Selection>(null);
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

  // 只在換了一筆時重填;改過沒存,點別筆 / 新增 / 取消 / × 要按兩次(全站檢視 V01;規則在 lib/draftGuard.ts)
  const formKey = selection?.kind === "person" ? `p${selection.id}` : selection?.kind === "new" ? "new" : null;
  const draft = useDraftForm<FormState>(
    EMPTY_FORM,
    formKey,
    () => (selection?.kind === "person" ? (selected ? toForm(selected) : null) : EMPTY_FORM),
    [selected],
  );
  const form = draft.form;
  const patch = draft.patch;
  useEffect(() => {
    if (formKey === null) return;
    setError(null);
    setSavedFlash(false);
  }, [formKey]);

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
      draft.saved(`p${saved.id}`, toForm(saved));
      setSelection({ kind: "person", id: saved.id });
    } catch (e) {
      // 欄位錯誤只留中文那幾句、不露欄位名(全站檢視 G2;規則在 lib/errorText.ts)
      setError(errorText(e));
    }
  }

  const isEditing = selection?.kind === "person";
  const isNew = selection?.kind === "new";

  return (
    <div className="page">
      <Toolbar
        title="業務員"
        actions={
          <button
            className={draft.armed("new") ? "btn armed" : "btn"}
            onClick={() => {
              if (selection?.kind !== "new") draft.leave("new", () => setSelection({ kind: "new" }));
            }}
          >
            {draft.armed("new") ? "再按一次新增" : "新增業務員"}
          </button>
        }
      />

      <div className={isEditing || isNew ? "pc-layout pane-page" : "pc-layout pane-page list-only"}>
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
                        onClick={() => {
                          if (selection?.kind === "person" && selection.id === s.id) return;
                          draft.leave(`row:${s.id}`, () => setSelection({ kind: "person", id: s.id }));
                        }}
                        className={
                          selection?.kind === "person" && selection.id === s.id
                            ? "selected"
                            : ""
                        }
                      >
                        <td className="id-code">{s.code}</td>
                        <td>{s.name}</td>
                        <td>{s.phone || "—"}</td>
                        <td
                          style={{
                            color: s.is_active ? "var(--success-text-soft)" : "var(--text-dim)",
                          }}
                        >
                          {s.is_active ? "啟用" : "停用"}
                        </td>
                      </tr>
                    ))}
                    {filtered.length === 0 && (
                      <tr>
                        <td colSpan={4} className="md-empty">
                          {query ? "查無業務員" : "還沒有業務員"}
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
          <PaneBack open={isEditing || isNew} onClose={() => draft.leave("close", () => setSelection(null))} disabled={save.isPending} />

          {(isEditing || isNew) && !draft.ready && <div className="md-empty" style={{ marginTop: 40 }}>載入中…</div>}
          {draft.ready && (
            <div className="pc-detail-body">
              {draft.warning && <div className="pc-detail-warn"><Banner kind="info" message={LEAVE_TEXT} /></div>}
              <h3 className="pc-detail-title">
                {isNew ? "新增業務員" : `業務員 · ${selected?.code} ${selected?.name}`}
              </h3>
              {error && <Banner kind="error" message={error} />}
              {savedFlash && <Banner kind="success" message="已儲存" />}
              <dl ref={dlRef}>
                <dt>
                  代號 <span style={{ color: "var(--danger-text)" }}>*</span>
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
                  姓名 <span style={{ color: "var(--danger-text)" }}>*</span>
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
                  className={draft.armed("close") ? "btn armed" : "btn"}
                  onClick={() => draft.leave("close", () => setSelection(null))}
                  disabled={save.isPending}
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
