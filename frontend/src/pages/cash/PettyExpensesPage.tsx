import { useCan } from "@/auth/AuthContext";
import { useMemo, useState } from "react";

import {
  usePettyExpenses,
  useVoidPettyExpense,
} from "@/api/hooks";
import type { PettyExpense } from "@/api/types";
import { ArmButton } from "@/components/workbench/ArmButton";
import { toast } from "@/components/workbench/toast";
import { AppliedFilters } from "@/components/AppliedFilters";
import { Toolbar } from "@/components/Toolbar";
import {
  MasterDetail,
  MasterColumn,
  DetailTab,
} from "@/components/master-detail/MasterDetail";
import { appliedList, cond, rangeCond } from "@/lib/appliedFilters";
import { localDay, monthStart } from "@/lib/fixedReports";
import { money, roundInt } from "@/lib/money";

import { PettyExpenseForm } from "./PettyExpenseForm";
import { errorText } from "@/lib/errorText";

export function PettyExpensesPage() {
  // 清單與合計 = 這段期間(預設本月)。以前不分期間只拿最新 50 筆,合計只加了那 50 筆
  const [from, setFrom] = useState(monthStart);
  const [to, setTo] = useState(localDay);
  const { data, isLoading, isError, error } = usePettyExpenses({ from, to });
  const voidMutation = useVoidPettyExpense();
  // 員工帳號的權限(作廢其他單):關掉的人沒有這顆(伺服器也會擋)
  const canVoid = useCan("void_others");
  const canWrite = useCan("cash_ops");                // 新增要「雜支調整」(不能修改:記錯了作廢再重記,owner 2026-10-24)
  const [drawerOpen, setDrawerOpen] = useState(false);
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
    .reduce((s, e) => s + roundInt(e.amount), 0);

  const columns: MasterColumn<PettyExpense>[] = [
    { key: "doc_date", header: "日期", render: (r) => r.doc_date },
    { key: "no", header: "單號", render: (r) => r.no },
    { key: "warehouse", header: "門市", render: (r) => r.warehouse_name, side: true },
    { key: "category", header: "類別", render: (r) => r.category_label },
    {
      key: "amount",
      header: "金額",
      render: (r) => (
        <span className="num">
          {money(r.amount)}
        </span>
      ),
    },
    {
      key: "payment",
      side: true,
      header: "付款",
      render: (r) => r.payment_method_name,
    },
    { key: "payee", header: "收款對象", render: (r) => r.payee || "—", side: true },
    {
      key: "handled_by",
      side: true,
      header: "經手人",
      render: (r) =>
        r.handled_by_name
          ? r.handled_by_name
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

  // 作廢按兩下(全站檢視 G1:以前跳瀏覽器的確認框,失敗再跳一個)
  async function handleVoid(r: PettyExpense) {
    try {
      await voidMutation.mutateAsync(r.id);
      toast(`${r.no} 已作廢`, "ok");
    } catch (e) {
      toast(`作廢失敗:${errorText(e)}`, "err");
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
              {r.warehouse_name}
            </dd>
            <dt>類別</dt>
            <dd>{r.category_label}</dd>
            <dt>金額</dt>
            <dd>{money(r.amount)}</dd>
            <dt>付款方式</dt>
            <dd>{r.payment_method_name}</dd>
            <dt>收款對象</dt>
            <dd>{r.payee || "—"}</dd>
            <dt>經手人</dt>
            <dd>
              {r.handled_by_name
                ? r.handled_by_name
                : "—"}
            </dd>
            <dt>備註</dt>
            <dd>{r.note || "—"}</dd>
            <dt>狀態</dt>
            <dd>{r.is_void ? "已作廢" : "有效"}</dd>
          </dl>
          {!r.is_void && (
            <div style={{ marginTop: 12, display: "flex", gap: 8 }}>
              {canVoid && (
                <ArmButton
                  // 換一張單就重來:不能沿用上一張「已按一下」(複審 P1)
                  key={r.id}
                  label="作廢"
                  className="btn danger"
                  onConfirm={() => handleVoid(r)}
                  disabled={voidMutation.isPending}
                />
              )}
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
          canWrite ? (
            <button
              className="btn"
              onClick={() => setDrawerOpen(true)}
            >
              新增雜支
            </button>
          ) : null
        }
      >
        <span style={{ color: "var(--text-dim)", fontSize: 14 }}>
          {filtered.length} 筆,有效金額合計{" "}
          <b style={{ color: "var(--text)" }}>
            {money(totalAmount)}
          </b>
        </span>
      </Toolbar>
      <div className="list-filterbar">
        <label>
          起日
          <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
        </label>
        <label>
          迄日
          <input type="date" value={to} onChange={(e) => setTo(e.target.value)} />
        </label>
        <button
          className="btn"
          type="button"
          onClick={() => {
            setFrom(monthStart());
            setTo(localDay());
          }}
        >
          本月
        </button>
        <button
          className="btn"
          type="button"
          onClick={() => {
            setFrom(localDay());
            setTo(localDay());
          }}
        >
          今天
        </button>
      </div>
      <AppliedFilters
        items={appliedList([rangeCond("期間", from, to, { from: monthStart(), to: localDay() }), cond("搜尋", query)])}
        onClear={() => {
          setFrom(monthStart());
          setTo(localDay());
          setQuery("");
        }}
      />
      {isLoading && <div className="md-empty">載入中…</div>}
      {isError && <div className="md-empty">載入失敗:{errorText(error)}</div>}
      {!isLoading && !isError && (
        <MasterDetail
          rows={filtered}
          columns={columns}
          rowKey={(r) => r.id}
          tabs={tabs}
          searchPlaceholder="搜尋 單號 / 門市 / 類別 / 收款對象 / 備註"
          onSearch={setQuery}
          searchValue={query}
          emptyText={(data ?? []).length === 0 ? "這段期間沒有雜支" : `查無符合「${query}」的雜支`}
        />
      )}
      <PettyExpenseForm
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
      />
    </div>
  );
}
