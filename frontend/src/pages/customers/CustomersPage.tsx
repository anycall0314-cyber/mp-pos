import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { ApiHttpError } from "@/api/client";
import { useCustomers, useSalesOrders, useSaveCustomer } from "@/api/hooks";
import type { Customer, CustomerKind } from "@/api/types";
import { Banner } from "@/components/Banner";
import { Toolbar } from "@/components/Toolbar";

const CUSTOMER_KINDS: { value: CustomerKind; label: string }[] = [
  { value: "individual", label: "個人" },
  { value: "peer", label: "同業 / 盤商" },
  { value: "corporate", label: "企業" },
  { value: "other", label: "其他" },
];

type TabKey = "all" | CustomerKind | "member";

const TABS: { key: TabKey; label: string }[] = [
  { key: "all", label: "全部" },
  { key: "individual", label: "個人 / 直客" },
  { key: "peer", label: "同業 / 盤商" },
  { key: "corporate", label: "企業" },
  { key: "other", label: "其他" },
  { key: "member", label: "會員" },
];

type Selection = { kind: "customer"; id: number } | { kind: "new" } | null;

interface FormState {
  phone: string;
  name: string;
  kind: CustomerKind;
  is_member: boolean;
  tax_id: string;
  address: string;
  note: string;
  is_active: boolean;
}

const EMPTY_FORM: FormState = {
  phone: "",
  name: "",
  kind: "individual",
  is_member: false,
  tax_id: "",
  address: "",
  note: "",
  is_active: true,
};

function toForm(c: Customer): FormState {
  return {
    phone: c.phone,
    name: c.name,
    kind: c.kind,
    is_member: c.is_member,
    tax_id: c.tax_id,
    address: c.address,
    note: c.note,
    is_active: c.is_active,
  };
}

function isTabKey(v: string | null): v is TabKey {
  return !!v && TABS.some((t) => t.key === v);
}

export function CustomersPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const tabParam = searchParams.get("tab");
  const tab: TabKey = isTabKey(tabParam) ? tabParam : "all";

  const result = useCustomers();
  const save = useSaveCustomer();

  const [query, setQuery] = useState("");
  const [selection, setSelection] = useState<Selection>(null);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [error, setError] = useState<string | null>(null);
  const [savedFlash, setSavedFlash] = useState(false);

  const customers = useMemo(() => {
    const list = result.data ?? [];
    return [...list].sort((a, b) => a.name.localeCompare(b.name, "zh-Hant"));
  }, [result.data]);

  const tabFiltered = useMemo(() => {
    if (tab === "all") return customers;
    if (tab === "member") return customers.filter((c) => c.is_member);
    return customers.filter((c) => c.kind === tab);
  }, [customers, tab]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return tabFiltered;
    return tabFiltered.filter(
      (c) =>
        c.phone.toLowerCase().includes(q) ||
        c.name.toLowerCase().includes(q) ||
        c.tax_id.toLowerCase().includes(q),
    );
  }, [tabFiltered, query]);

  const selected = useMemo(() => {
    if (selection?.kind !== "customer") return null;
    return customers.find((c) => c.id === selection.id) ?? null;
  }, [selection, customers]);

  useEffect(() => {
    if (selection?.kind === "customer" && selected) {
      setForm(toForm(selected));
      setError(null);
      setSavedFlash(false);
    } else if (selection?.kind === "new") {
      setForm({
        ...EMPTY_FORM,
        kind: tab === "all" || tab === "member" ? "individual" : tab,
        is_member: tab === "member",
      });
      setError(null);
      setSavedFlash(false);
    }
  }, [selection, selected, tab]);

  const customerId = selection?.kind === "customer" ? selection.id : null;
  const orders = useSalesOrders(
    customerId ? { customer: customerId } : undefined,
  );

  const orderStats = useMemo(() => {
    const list = orders.data ?? [];
    const active = list.filter((o) => !o.is_void);
    const total = active.reduce((s, o) => s + Number(o.total || 0), 0);
    const lastVisit = active.reduce<string | null>((d, o) => {
      if (!d) return o.doc_date;
      return o.doc_date > d ? o.doc_date : d;
    }, null);
    return { count: active.length, total, lastVisit };
  }, [orders.data]);

  function patch<K extends keyof FormState>(k: K, v: FormState[K]) {
    setForm((f) => ({ ...f, [k]: v }));
  }

  function selectTab(next: TabKey) {
    const params = new URLSearchParams(searchParams);
    if (next === "all") params.delete("tab");
    else params.set("tab", next);
    setSearchParams(params, { replace: true });
  }

  async function handleSave() {
    const phone = form.phone.trim();
    const name = form.name.trim();
    if (!name) {
      setError("姓名 / 名稱必填");
      return;
    }
    const payload: Partial<Customer> & { id?: number } = {
      phone,
      name,
      kind: form.kind,
      is_member: form.is_member,
      tax_id: form.tax_id.trim(),
      address: form.address.trim(),
      note: form.note.trim(),
      is_active: form.is_active,
    };
    if (selection?.kind === "customer") payload.id = selection.id;
    try {
      const saved = await save.mutateAsync(payload);
      setError(null);
      setSavedFlash(true);
      setTimeout(() => setSavedFlash(false), 2000);
      setSelection({ kind: "customer", id: saved.id });
    } catch (e) {
      if (e instanceof ApiHttpError) {
        const body = e.body;
        if (typeof body === "object" && body) {
          const firstKey = Object.keys(body)[0];
          const msg = Array.isArray((body as Record<string, unknown>)[firstKey])
            ? (body as Record<string, string[]>)[firstKey][0]
            : JSON.stringify(body);
          setError(firstKey === "phone" ? `電話問題:${msg}` : `${firstKey}:${msg}`);
        } else {
          setError(`儲存失敗 (${e.status})`);
        }
      } else {
        setError(String(e));
      }
    }
  }

  const isEditing = selection?.kind === "customer";
  const isNew = selection?.kind === "new";

  return (
    <div className="page">
      <Toolbar
        title="客戶管理"
        actions={
          <button
            className="btn primary"
            onClick={() => setSelection({ kind: "new" })}
          >
            + 新增客戶
          </button>
        }
      />

      <div style={{ padding: "8px 16px 0" }}>
        <div className="tab-switcher">
          {TABS.map((t) => {
            const count =
              t.key === "all"
                ? customers.length
                : t.key === "member"
                  ? customers.filter((c) => c.is_member).length
                  : customers.filter((c) => c.kind === t.key).length;
            return (
              <button
                key={t.key}
                type="button"
                className={
                  t.key === tab
                    ? "tab-switcher-item active"
                    : "tab-switcher-item"
                }
                onClick={() => selectTab(t.key)}
              >
                {t.label}
                <span
                  style={{
                    marginLeft: 6,
                    opacity: 0.7,
                    fontSize: 12,
                  }}
                >
                  {count}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      <div className="pc-layout">
        <aside className="pc-master" style={{ gridTemplateRows: "1fr" }}>
          <section className="pc-section">
            <div className="pc-section-header">
              客戶
              <span style={{ fontWeight: "normal" }}>
                {!result.isLoading && `${filtered.length} 筆`}
              </span>
            </div>
            <div className="pc-section-search">
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="搜尋 電話 / 姓名 / 統編"
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
                      <th>姓名 / 名稱</th>
                      <th style={{ width: 120 }}>電話</th>
                      <th style={{ width: 90 }}>類別</th>
                      <th style={{ width: 44 }}>會員</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.map((c) => (
                      <tr
                        key={c.id}
                        onClick={() => setSelection({ kind: "customer", id: c.id })}
                        className={
                          selection?.kind === "customer" && selection.id === c.id
                            ? "selected"
                            : ""
                        }
                      >
                        <td>{c.name}</td>
                        <td style={{ color: c.phone ? "inherit" : "var(--text-dim)" }}>
                          {c.phone || "—"}
                        </td>
                        <td>{c.kind_label}</td>
                        <td
                          style={{
                            color: c.is_member ? "#80d090" : "var(--text-dim)",
                          }}
                        >
                          {c.is_member ? "會員" : "—"}
                        </td>
                      </tr>
                    ))}
                    {filtered.length === 0 && (
                      <tr>
                        <td colSpan={4} className="md-empty">
                          {query ? "查無客戶" : "此分類尚無客戶"}
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
              從左側選擇客戶以檢視 / 編輯,或按右上角「新增客戶」
            </div>
          )}

          {(isEditing || isNew) && (
            <div className="pc-detail-body">
              <h3 className="pc-detail-title">
                {isNew ? "新增客戶" : `客戶 · ${selected?.name}`}
              </h3>
              {error && <Banner kind="error" message={error} />}
              {savedFlash && <Banner kind="success" message="已儲存" />}
              <dl>
                <dt>電話</dt>
                <dd>
                  <input
                    value={form.phone}
                    onChange={(e) => patch("phone", e.target.value)}
                    maxLength={40}
                    placeholder="選填(個人客戶建議填,同業/企業可省略)"
                    style={{ width: 280 }}
                  />
                </dd>
                <dt>
                  姓名 / 名稱 <span style={{ color: "#ff7070" }}>*</span>
                </dt>
                <dd>
                  <input
                    value={form.name}
                    onChange={(e) => patch("name", e.target.value)}
                    maxLength={120}
                    style={{ width: 280 }}
                  />
                </dd>
                <dt>客戶類別</dt>
                <dd>
                  <select
                    value={form.kind}
                    onChange={(e) => patch("kind", e.target.value as CustomerKind)}
                    style={{ width: 200 }}
                  >
                    {CUSTOMER_KINDS.map((k) => (
                      <option key={k.value} value={k.value}>
                        {k.label}
                      </option>
                    ))}
                  </select>
                </dd>
                <dt>會員</dt>
                <dd>
                  <label
                    style={{ display: "inline-flex", gap: 6, alignItems: "center" }}
                  >
                    <input
                      type="checkbox"
                      checked={form.is_member}
                      onChange={(e) => patch("is_member", e.target.checked)}
                    />
                    {form.is_member ? "會員" : "非會員"}
                  </label>
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
                    銷售紀錄
                    {orders.isLoading
                      ? " 載入中…"
                      : ` (${orderStats.count} 筆 · 累計 $${orderStats.total.toLocaleString()}${
                          orderStats.lastVisit
                            ? ` · 最近 ${orderStats.lastVisit}`
                            : ""
                        })`}
                  </h4>
                  <div className="md-table" style={{ height: "auto" }}>
                    <table>
                      <thead>
                        <tr>
                          <th>單號</th>
                          <th>日期</th>
                          <th>業務員</th>
                          <th>課稅別</th>
                          <th>發票號</th>
                          <th className="num">總額</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(orders.data ?? []).map((so) => (
                          <tr
                            key={so.id}
                            onClick={() => navigate(`/sales/${so.id}`)}
                            className={so.is_void ? "row-void" : undefined}
                          >
                            <td>{so.no}</td>
                            <td>{so.doc_date}</td>
                            <td>
                              {so.sales_person_name
                                ? `${so.sales_person_code ?? ""} ${so.sales_person_name}`
                                : "—"}
                            </td>
                            <td>{so.tax_method_label}</td>
                            <td>{so.invoice_no || "—"}</td>
                            <td className="num">
                              {Number(so.total).toLocaleString()}
                            </td>
                          </tr>
                        ))}
                        {!orders.isLoading && (orders.data ?? []).length === 0 && (
                          <tr>
                            <td colSpan={6} className="md-empty">
                              此客戶尚無銷售紀錄
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
