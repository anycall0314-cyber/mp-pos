import { useMemo, useState } from "react";

import {
  usePettyExpenses,
  useVoidPettyExpense,
} from "@/api/hooks";
import type { PettyExpense } from "@/api/types";
import { Toolbar } from "@/components/Toolbar";
import {
  MasterDetail,
  MasterColumn,
  DetailTab,
} from "@/components/master-detail/MasterDetail";

import { PettyExpenseForm } from "./PettyExpenseForm";

export function PettyExpensesPage() {
  const { data, isLoading, isError, error } = usePettyExpenses();
  const voidMutation = useVoidPettyExpense();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerInitial, setDrawerInitial] = useState<PettyExpense | null>(
    null,
  );
  const [query, setQuery] = useState("");

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = data ?? [];
    if (!q) return list;
    return list.filter((e) => {
      const hay = [
        e.no,
        e.warehouse_name,
        e.category_label,
        e.payee,
        e.note,
        e.payment_method_name,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return hay.includes(q);
    });
  }, [data, query]);

  const totalAmount = filtered
    .filter((e) => !e.is_void)
    .reduce((s, e) => s + Math.round(Number(e.amount)), 0);

  const columns: MasterColumn<PettyExpense>[] = [
    { key: "doc_date", header: "日期", render: (r) => r.doc_date },
    { key: "no", header: "單號", render: (r) => r.no },
    { key: "warehouse", header: "門市", render: (r) => r.warehouse_name },
    { key: "category", header: "類別", render: (r) => r.category_label },
    {
      key: "amount",
      header: "金額",
      render: (r) => (
        <span className="num">
          {Math.round(Number(r.amount)).toLocaleString()}
        </span>
      ),
    },
    {
      key: "payment",
      header: "付款",
      render: (r) => r.payment_method_name,
    },
    { key: "payee", header: "收款對象", render: (r) => r.payee || "—" },
    {
      key: "handled_by",
      header: "經手人",
      render: (r) =>
        r.handled_by_name
          ? `${r.handled_by_code} ${r.handled_by_name}`
          : "—",
    },
    {
      key: "void",
      header: "狀態",
      render: (r) =>
        r.is_void ? (
          <span style={{ color: "var(--text-dim)" }}>作廢</span>
        ) : (
          "—"
        ),
    },
  ];

  async function handleVoid(r: PettyExpense) {
    if (!confirm(`確定作廢雜支單 ${r.no}?`)) return;
    try {
      await voidMutation.mutateAsync(r.id);
    } catch (e) {
      alert(`作廢失敗:${e instanceof Error ? e.message : e}`);
    }
  }

  const tabs: DetailTab<PettyExpense>[] = [
    {
      key: "basic",
      label: "基本",
      render: (r) => (
        <div>
          <dl>
            <dt>單號</dt>
            <dd>{r.no}</dd>
            <dt>日期</dt>
            <dd>{r.doc_date}</dd>
            <dt>門市</dt>
            <dd>
              {r.warehouse_code} {r.warehouse_name}
            </dd>
            <dt>類別</dt>
            <dd>{r.category_label}</dd>
            <dt>金額</dt>
            <dd>{Math.round(Number(r.amount)).toLocaleString()}</dd>
            <dt>付款方式</dt>
            <dd>{r.payment_method_name}</dd>
            <dt>收款對象</dt>
            <dd>{r.payee || "—"}</dd>
            <dt>經手人</dt>
            <dd>
              {r.handled_by_name
                ? `${r.handled_by_code} ${r.handled_by_name}`
                : "—"}
            </dd>
            <dt>備註</dt>
            <dd>{r.note || "—"}</dd>
            <dt>狀態</dt>
            <dd>{r.is_void ? "已作廢" : "有效"}</dd>
          </dl>
          {!r.is_void && (
            <div style={{ marginTop: 12, display: "flex", gap: 8 }}>
              <button
                className="btn primary"
                onClick={() => {
                  setDrawerInitial(r);
                  setDrawerOpen(true);
                }}
              >
                編輯
              </button>
              <button
                className="btn danger"
                onClick={() => handleVoid(r)}
                disabled={voidMutation.isPending}
              >
                作廢
              </button>
            </div>
          )}
        </div>
      ),
    },
  ];

  return (
    <div className="page">
      <Toolbar
        title="店頭雜支"
        actions={
          <button
            className="btn primary"
            onClick={() => {
              setDrawerInitial(null);
              setDrawerOpen(true);
            }}
          >
            + 新增雜支
          </button>
        }
      >
        <span style={{ color: "var(--text-dim)", fontSize: 13 }}>
          {filtered.length} 筆,有效金額合計{" "}
          <b style={{ color: "var(--text)" }}>
            {totalAmount.toLocaleString()}
          </b>
        </span>
      </Toolbar>
      {isLoading && <div className="md-empty">載入中…</div>}
      {isError && <div className="md-empty">載入失敗:{String(error)}</div>}
      {!isLoading && !isError && (
        <MasterDetail
          rows={filtered}
          columns={columns}
          rowKey={(r) => r.id}
          tabs={tabs}
          searchPlaceholder="搜尋 單號 / 門市 / 類別 / 收款對象 / 備註"
          onSearch={setQuery}
          emptyDetailHint={
            (data ?? []).length === 0
              ? "尚無雜支,點右上「+ 新增雜支」開始記錄"
              : filtered.length === 0
                ? `查無符合「${query}」的雜支`
                : "從左側選擇雜支單檢視詳細"
          }
        />
      )}
      <PettyExpenseForm
        open={drawerOpen}
        initial={drawerInitial}
        onClose={() => setDrawerOpen(false)}
      />
    </div>
  );
}
