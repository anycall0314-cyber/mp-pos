import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { ApiHttpError } from "@/api/client";
import {
  useMember,
  useMemberList,
  useSaveMember,
} from "@/api/hooks";
import type { Customer, Member } from "@/api/types";
import { Banner } from "@/components/Banner";
import { SourcePicker } from "@/components/SourcePicker";
import { Toolbar } from "@/components/Toolbar";
import { byId, cutNote } from "@/lib/listAll";
import { showMemberHistory } from "@/lib/memberUrl";

import { LegacyLinkCandidates } from "./LegacyLinkCandidates";

type Selection = { kind: "member"; id: number } | { kind: "new" } | null;

interface FormState {
  kind: Member["kind"];
  tax_id: string;
  contact: string;
  default_source_mode: Member["default_source_mode"];
  default_customer_detail: Customer | null;
  name: string;
  phone: string;
  national_id: string;
  birthday: string;
  address: string;
  note: string;
  is_active: boolean;
}

const EMPTY_FORM: FormState = {
  kind: "individual", tax_id: "", contact: "", default_source_mode: "sales_default", default_customer_detail: null,
  name: "",
  phone: "",
  national_id: "",
  birthday: "",
  address: "",
  note: "",
  is_active: true,
};

function toForm(m: Member): FormState {
  return {
    kind: m.kind, tax_id: m.tax_id, contact: m.contact, default_source_mode: m.default_source_mode, default_customer_detail: m.default_customer_detail,
    name: m.name,
    phone: m.phone,
    national_id: m.national_id,
    birthday: m.birthday ?? "",
    address: m.address,
    note: m.note,
    is_active: m.is_active,
  };
}

export function MembersPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const save = useSaveMember();

  const [query, setQuery] = useState("");
  // 名單問伺服器(會員會有幾萬位):打字停一下才問;沒打字 = 照姓名排的前 100 位
  const [search, setSearch] = useState("");
  useEffect(() => {
    const timer = setTimeout(() => setSearch(query.trim()), 300);
    return () => clearTimeout(timer);
  }, [query]);
  const result = useMemberList(search);
  // 選到的那一位:點名單時記下來,名單之後換了(打字搜尋)也還是他
  const [picked, setPicked] = useState<Member | null>(null);
  const [selection, setSelection] = useState<Selection>(() => {
    const sel = searchParams.get("selected");
    const n = sel ? Number(sel) : NaN;
    return Number.isFinite(n) ? { kind: "member", id: n } : null;
  });

  useEffect(() => {
    const sel = searchParams.get("selected");
    if (!sel) return;
    const n = Number(sel);
    if (!Number.isFinite(n)) return;
    if (selection?.kind === "member" && selection.id === n) return;
    setSelection({ kind: "member", id: n });
  }, [searchParams]);

  useEffect(() => {
    if (selection?.kind === "member") {
      if (searchParams.get("selected") !== String(selection.id)) {
        const next = new URLSearchParams(searchParams);
        next.set("selected", String(selection.id));
        setSearchParams(next, { replace: true });
      }
    } else if (searchParams.has("selected")) {
      const next = new URLSearchParams(searchParams);
      next.delete("selected");
      setSearchParams(next, { replace: true });
    }
  }, [selection]);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [error, setError] = useState<string | null>(null);
  const [savedFlash, setSavedFlash] = useState(false);

  const members = result.data?.rows ?? [];
  const cut = cutNote(result.data, "只列前", "位");

  // 從別頁連過來的那一位不在手上(也可能不在名單這一頁裡):另外讀
  const selectedId = selection?.kind === "member" ? selection.id : null;
  const one = useMember(selectedId != null && picked?.id !== selectedId ? selectedId : null);
  const selected = useMemo(() => byId(selectedId, picked, one.data), [selectedId, picked, one.data]);

  useEffect(() => {
    if (selection?.kind === "member" && selected) {
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
    const name = form.name.trim();
    if (!name) {
      setError("姓名／公司名稱必填");
      return;
    }
    const payload: Partial<Member> & { id?: number } = {
      name,
      kind: form.kind, tax_id: form.tax_id.trim(), contact: form.contact.trim(),
      default_source_mode: form.default_source_mode, default_customer: form.default_customer_detail?.id ?? null,
      phone: form.phone.trim(),
      national_id: form.national_id.trim(),
      birthday: form.birthday ? form.birthday : null,
      address: form.address.trim(),
      note: form.note.trim(),
      is_active: form.is_active,
    };
    if (selection?.kind === "member") payload.id = selection.id;
    try {
      const saved = await save.mutateAsync(payload);
      setError(null);
      setSavedFlash(true);
      setTimeout(() => setSavedFlash(false), 2000);
      setPicked(saved);
      setSelection({ kind: "member", id: saved.id });
    } catch (e) {
      if (e instanceof ApiHttpError) {
        const body = e.body;
        if (typeof body === "object" && body) {
          const firstKey = Object.keys(body)[0];
          const msg = Array.isArray((body as Record<string, unknown>)[firstKey])
            ? (body as Record<string, string[]>)[firstKey][0]
            : JSON.stringify(body);
          setError(`${firstKey}:${msg}`);
        } else {
          setError(`儲存失敗 (${e.status})`);
        }
      } else {
        setError(String(e));
      }
    }
  }

  const isEditing = selection?.kind === "member";
  const isNew = selection?.kind === "new";

  return (
    <div className="page">
      <Toolbar
        title="會員管理"
        actions={
          <button
            className="btn primary"
            onClick={() => setSelection({ kind: "new" })}
          >
            + 新增會員
          </button>
        }
      />

      <div className="pc-layout">
        <aside className="pc-master" style={{ gridTemplateRows: "1fr" }}>
          <section className="pc-section">
            <div className="pc-section-header">
              會員
              <span style={{ fontWeight: "normal" }}>
                {result.data && `${result.data.count} 筆`}
              </span>
            </div>
            <div className="pc-section-search">
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="搜尋 電話 / 姓名 / 公司 / 統編 / 會員號"
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
                      <th>姓名</th>
                      <th style={{ width: 120 }}>電話</th>
                      <th style={{ width: 90 }}>會員號</th>
                    </tr>
                  </thead>
                  <tbody>
                    {members.map((m) => (
                      <tr
                        key={m.id}
                        onClick={() => {
                          // 右邊編輯這一位,消費紀錄在另一個分頁、留在這一頁(owner 2026-10-20)
                          setPicked(m);
                          setSelection({ kind: "member", id: m.id });
                          showMemberHistory(m.id);
                        }}
                        className={
                          selection?.kind === "member" && selection.id === m.id
                            ? "selected"
                            : ""
                        }
                      >
                        <td>{m.name}</td>
                        <td style={{ color: m.phone ? "inherit" : "var(--text-dim)" }}>
                          {m.phone || "—"}
                        </td>
                        <td style={{ color: "var(--text-dim)" }}>{m.code}</td>
                      </tr>
                    ))}
                    {members.length === 0 && (
                      <tr>
                        <td colSpan={3} className="md-empty">
                          {search ? "查無會員" : "尚無會員"}
                        </td>
                      </tr>
                    )}
                    {cut && (
                      <tr>
                        <td colSpan={3} className="md-empty">
                          {cut}
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
              從左側選擇會員,或按右上角「新增會員」
            </div>
          )}

          {/* 那一位還沒讀到之前不給表單:上一位的資料還在格子裡,按儲存會存到這一位身上 */}
          {isEditing && !selected && (
            <div className="md-empty" style={{ marginTop: 40 }}>
              {one.isError ? "找不到這位會員" : "載入中…"}
            </div>
          )}

          {(isNew || (isEditing && selected)) && (
            <div className="pc-detail-body">
              <h3 className="pc-detail-title">
                {isNew ? "新增會員" : `會員 · ${selected?.name}`}
              </h3>
              {error && <Banner kind="error" message={error} />}
              {savedFlash && <Banner kind="success" message="已儲存" />}
              <dl>
                <dt>會員類型</dt><dd><select value={form.kind} onChange={e => patch("kind", e.target.value as Member["kind"])}><option value="individual">個人</option><option value="company">公司</option></select></dd>
                <dt>預設來源</dt><dd style={{maxWidth: 360}}><SourcePicker inherit mode={form.default_source_mode} source={form.default_customer_detail} onChange={(source, mode) => setForm(f => ({...f, default_customer_detail: source, default_source_mode: mode}))} /></dd>
                <dt>
                  {form.kind === "company" ? "公司名稱" : "姓名"} <span style={{ color: "var(--danger-text)" }}>*</span>
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
                    style={{ width: 280 }}
                  />
                </dd>
                {form.kind === "company" ? <>
                  <dt>統一編號</dt><dd><input value={form.tax_id} onChange={e => patch("tax_id", e.target.value)} maxLength={20} /></dd>
                  <dt>聯絡人</dt><dd><input value={form.contact} onChange={e => patch("contact", e.target.value)} maxLength={120} /></dd>
                </> : <>
                <dt>身分證字號</dt>
                <dd>
                  <input
                    value={form.national_id}
                    onChange={(e) => patch("national_id", e.target.value)}
                    maxLength={20}
                    style={{ width: 200 }}
                  />
                </dd>
                <dt>生日</dt>
                <dd>
                  <input
                    type="date"
                    value={form.birthday}
                    onChange={(e) => patch("birthday", e.target.value)}
                    style={{ width: 180 }}
                  />
                </dd>
                </>}
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
              {isEditing && selected && <LegacyLinkCandidates memberId={selected.id} />}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
