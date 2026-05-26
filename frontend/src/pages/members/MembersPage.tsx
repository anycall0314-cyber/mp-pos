import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { ApiHttpError } from "@/api/client";
import {
  useLegacyPurchases,
  useMembers,
  useSalesOrders,
  useSaveMember,
} from "@/api/hooks";
import type { Member } from "@/api/types";
import { Banner } from "@/components/Banner";
import { Toolbar } from "@/components/Toolbar";

type Selection = { kind: "member"; id: number } | { kind: "new" } | null;

interface FormState {
  name: string;
  phone: string;
  national_id: string;
  birthday: string;
  address: string;
  note: string;
  is_active: boolean;
}

const EMPTY_FORM: FormState = {
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
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const result = useMembers();
  const save = useSaveMember();

  const [query, setQuery] = useState("");
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

  const members = useMemo(() => {
    const list = result.data ?? [];
    return [...list].sort((a, b) => a.name.localeCompare(b.name, "zh-Hant"));
  }, [result.data]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return members;
    return members.filter(
      (m) =>
        m.phone.toLowerCase().includes(q) ||
        m.name.toLowerCase().includes(q) ||
        m.national_id.toLowerCase().includes(q) ||
        m.code.toLowerCase().includes(q),
    );
  }, [members, query]);

  const selected = useMemo(() => {
    if (selection?.kind !== "member") return null;
    return members.find((m) => m.id === selection.id) ?? null;
  }, [selection, members]);

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

  const memberId = selection?.kind === "member" ? selection.id : null;
  const orders = useSalesOrders(memberId ? { member: memberId } : undefined);
  const legacy = useLegacyPurchases(memberId);

  // 把現役銷貨單明細 + 舊系統紀錄整成單一時間軸,每列一個商品 row。
  type Row = {
    key: string;
    source: "current" | "legacy";
    doc_date: string;
    is_void: boolean;
    product_name: string;
    product_sku: string;
    qty: number;
    unit_price: string;
    amount: string;
    serial_or_msisdn: string;
    sales_person_label: string;
    customer_name: string;
    doc_no: string;
    so_id: number | null;
  };

  const rows = useMemo<Row[]>(() => {
    const fromCurrent: Row[] = (orders.data ?? []).flatMap((so) =>
      so.items.map((it) => ({
        key: `c-${so.id}-${it.id}`,
        source: "current" as const,
        doc_date: so.doc_date,
        is_void: so.is_void,
        product_name: it.product_name,
        product_sku: it.product_sku,
        qty: it.qty,
        unit_price: it.unit_price,
        amount: it.amount,
        serial_or_msisdn:
          it.msisdn ||
          (it.serials ?? []).map((s) => s.serial_no).join(", ") ||
          "—",
        sales_person_label: so.sales_person_name
          ? `${so.sales_person_code ?? ""} ${so.sales_person_name}`
          : "—",
        customer_name: so.customer_name || "—",
        doc_no: so.no,
        so_id: so.id,
      })),
    );
    const fromLegacy: Row[] = (legacy.data ?? []).map((lp) => ({
      key: `l-${lp.id}`,
      source: "legacy" as const,
      doc_date: lp.doc_date,
      is_void: false,
      product_name: lp.product_name,
      product_sku: lp.product_sku,
      qty: lp.qty,
      unit_price: lp.unit_price,
      amount: lp.amount,
      serial_or_msisdn: lp.serial_no || "—",
      sales_person_label: "—",
      customer_name: "—",
      doc_no: lp.source_no || "(舊系統)",
      so_id: null,
    }));
    return [...fromCurrent, ...fromLegacy].sort((a, b) =>
      a.doc_date < b.doc_date ? 1 : a.doc_date > b.doc_date ? -1 : 0,
    );
  }, [orders.data, legacy.data]);

  const orderStats = useMemo(() => {
    const list = orders.data ?? [];
    const active = list.filter((o) => !o.is_void);
    const total = active.reduce((s, o) => s + Number(o.total || 0), 0);
    const legacyList = legacy.data ?? [];
    const legacyTotal = legacyList.reduce(
      (s, lp) => s + Number(lp.amount || 0),
      0,
    );
    const lastDateAll = rows.reduce<string | null>((d, r) => {
      if (r.is_void) return d;
      if (!d) return r.doc_date;
      return r.doc_date > d ? r.doc_date : d;
    }, null);
    return {
      count: active.length,
      total,
      legacyCount: legacyList.length,
      legacyTotal,
      lastVisit: lastDateAll,
    };
  }, [orders.data, legacy.data, rows]);

  function patch<K extends keyof FormState>(k: K, v: FormState[K]) {
    setForm((f) => ({ ...f, [k]: v }));
  }

  async function handleSave() {
    const name = form.name.trim();
    if (!name) {
      setError("姓名必填");
      return;
    }
    const payload: Partial<Member> & { id?: number } = {
      name,
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
                {!result.isLoading && `${filtered.length} 筆`}
              </span>
            </div>
            <div className="pc-section-search">
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="搜尋 電話 / 姓名 / 身分證 / 會員號"
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
                    {filtered.map((m) => (
                      <tr
                        key={m.id}
                        onClick={() => setSelection({ kind: "member", id: m.id })}
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
                    {filtered.length === 0 && (
                      <tr>
                        <td colSpan={3} className="md-empty">
                          {query ? "查無會員" : "尚無會員"}
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
              從左側選擇會員以檢視 / 編輯,或按右上角「新增會員」
            </div>
          )}

          {(isEditing || isNew) && (
            <div className="pc-detail-body">
              <h3 className="pc-detail-title">
                {isNew ? "新增會員" : `會員 · ${selected?.name}`}
              </h3>
              {error && <Banner kind="error" message={error} />}
              {savedFlash && <Banner kind="success" message="已儲存" />}
              <dl>
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
                    style={{ width: 280 }}
                  />
                </dd>
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

              {isEditing && selected && (
                <div style={{ marginTop: 24 }}>
                  <h4 className="pc-detail-title">
                    購買明細
                    {orders.isLoading || legacy.isLoading
                      ? " 載入中…"
                      : ` (${orderStats.count} 筆銷貨 · 累計 $${orderStats.total.toLocaleString()}${
                          orderStats.legacyCount > 0
                            ? ` · 舊系統 ${orderStats.legacyCount} 筆 / $${orderStats.legacyTotal.toLocaleString()}`
                            : ""
                        }${
                          orderStats.lastVisit
                            ? ` · 最近 ${orderStats.lastVisit}`
                            : ""
                        })`}
                  </h4>
                  <div className="md-table" style={{ height: "auto" }}>
                    <table>
                      <thead>
                        <tr>
                          <th style={{ width: 100 }}>日期</th>
                          <th>商品</th>
                          <th style={{ width: 160 }}>序號 / 門號</th>
                          <th className="num" style={{ width: 50 }}>數量</th>
                          <th className="num" style={{ width: 90 }}>單價</th>
                          <th className="num" style={{ width: 100 }}>小計</th>
                          <th style={{ width: 100 }}>業務員</th>
                          <th style={{ width: 100 }}>客戶</th>
                          <th style={{ width: 120 }}>單號</th>
                        </tr>
                      </thead>
                      <tbody>
                        {rows.map((r) => (
                          <tr
                            key={r.key}
                            onClick={() =>
                              r.so_id != null && navigate(`/sales/${r.so_id}`)
                            }
                            className={r.is_void ? "row-void" : undefined}
                            title={
                              r.source === "legacy"
                                ? "舊系統匯入紀錄"
                                : "點擊檢視銷貨單"
                            }
                            style={{
                              cursor: r.so_id != null ? "pointer" : "default",
                              opacity: r.source === "legacy" ? 0.85 : 1,
                            }}
                          >
                            <td>{r.doc_date}</td>
                            <td>
                              <div>{r.product_name}</div>
                              <div style={{ fontSize: 11, color: "var(--text-dim)" }}>
                                {r.product_sku}
                              </div>
                            </td>
                            <td style={{ fontSize: 12 }}>{r.serial_or_msisdn}</td>
                            <td className="num">{r.qty}</td>
                            <td className="num">
                              {Number(r.unit_price).toLocaleString()}
                            </td>
                            <td className="num">
                              {Number(r.amount).toLocaleString()}
                            </td>
                            <td>{r.sales_person_label}</td>
                            <td>{r.customer_name}</td>
                            <td style={{ fontSize: 12, color: "var(--text-dim)" }}>
                              {r.doc_no}
                              {r.source === "legacy" && (
                                <span
                                  style={{
                                    marginLeft: 4,
                                    fontSize: 10,
                                    padding: "1px 4px",
                                    border: "1px solid var(--text-dim)",
                                    borderRadius: 3,
                                  }}
                                >
                                  舊
                                </span>
                              )}
                            </td>
                          </tr>
                        ))}
                        {!orders.isLoading && !legacy.isLoading && rows.length === 0 && (
                          <tr>
                            <td colSpan={9} className="md-empty">
                              此會員尚無銷售紀錄
                            </td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
