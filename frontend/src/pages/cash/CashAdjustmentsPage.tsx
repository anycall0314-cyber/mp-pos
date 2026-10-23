import { useCan } from "@/auth/AuthContext";
import { useMemo, useState } from "react";

import {
  useCashAdjustments,
  useVoidCashAdjustment,
} from "@/api/hooks";
import type { CashAdjustment } from "@/api/types";
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

import { CashAdjustmentForm } from "./CashAdjustmentForm";
import { errorText } from "@/lib/errorText";

export function CashAdjustmentsPage() {
  // 清單與合計 = 這段期間(預設本月)。以前不分期間只拿最新 50 筆,合計只加了那 50 筆
  const [from, setFrom] = useState(monthStart);
  const [to, setTo] = useState(localDay);
  const { data, isLoading, isError, error } = useCashAdjustments({ from, to });
  const voidMutation = useVoidCashAdjustment();
  // 員工帳號的權限(作廢其他單):關掉的人沒有這顆(伺服器也會擋)
  const canVoid = useCan("void_others");
  const canWrite = useCan("cash_ops");                // 新增 / 修改要「雜支調整」
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerInitial, setDrawerInitial] = useState<CashAdjustment | null>(
    null,
  );
  const [query, setQuery] = useState("");

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = data ?? [];
    if (!q) return list;
    return list.filter((a) => {
      const hay = [
        a.no,
        a.warehouse_name,
        a.direction_label,
        a.reason_label,
        a.note,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return hay.includes(q);
    });
  }, [data, query]);

  // 有效淨額 = in - out
  const netTotal = filtered
    .filter((a) => !a.is_void)
    .reduce((s, a) => {
      const amt = roundInt(a.amount);
      return s + (a.direction === "in" ? amt : -amt);
    }, 0);

  const columns: MasterColumn<CashAdjustment>[] = [
    { key: "doc_date", header: "日期", render: (r) => r.doc_date },
    { key: "no", header: "單號", render: (r) => r.no },
    { key: "warehouse", header: "門市", render: (r) => r.warehouse_name },
    {
      key: "direction",
      header: "方向",
      render: (r) => (
        <span style={{ color: r.direction === "in" ? "var(--success-text-soft)" : "var(--danger-text)" }}>
          {r.direction_label}
        </span>
      ),
    },
    { key: "reason", header: "事由", render: (r) => r.reason_label },
    {
      key: "amount",
      header: "金額",
      render: (r) => (
        <span
          className="num"
          style={{ color: r.direction === "in" ? "var(--success-text-soft)" : "var(--danger-text)" }}
        >
          {r.direction === "in" ? "+" : "−"}
          {money(r.amount)}
        </span>
      ),
    },
    {
      key: "handled_by",
      header: "經手人",
      render: (r) =>
        r.handled_by_name
          ? `${r.handled_by_code} ${r.handled_by_name}`
          : "—",
    },
    { key: "note", header: "備註", render: (r) => r.note || "—" },
  ];

  // 作廢按兩下(全站檢視 G1:以前跳瀏覽器的確認框,失敗再跳一個)
  async function handleVoid(r: CashAdjustment) {
    try {
      await voidMutation.mutateAsync(r.id);
      toast(`${r.no} 已作廢`, "ok");
    } catch (e) {
      toast(`作廢失敗:${errorText(e)}`, "err");
    }
  }

  const tabs: DetailTab<CashAdjustment>[] = [
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
            <dt>方向</dt>
            <dd>{r.direction_label}</dd>
            <dt>事由</dt>
            <dd>{r.reason_label}</dd>
            <dt>金額</dt>
            <dd>{money(r.amount)}</dd>
            <dt>經手人</dt>
            <dd>
              {r.handled_by_name
                ? `${r.handled_by_code} ${r.handled_by_name}`
                : "—"}
            </dd>
            <dt>備註</dt>
            <dd>{r.note || "—"}</dd>
          </dl>
          {!r.is_void && (
            <div style={{ marginTop: 12, display: "flex", gap: 8 }}>
              {canWrite && (
                <button
                  className="btn primary"
                  onClick={() => {
                    setDrawerInitial(r);
                    setDrawerOpen(true);
                  }}
                >
                  編輯
                </button>
              )}
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
        title="現金調整"
        actions={
          canWrite ? (
            <button
              className="btn primary"
              onClick={() => {
                setDrawerInitial(null);
                setDrawerOpen(true);
              }}
            >
              新增調整
            </button>
          ) : null
        }
      >
        <span style={{ color: "var(--text-dim)", fontSize: 14 }}>
          {filtered.length} 筆,淨額{" "}
          <b
            style={{
              color: netTotal >= 0 ? "var(--success-text-soft)" : "var(--danger-text)",
            }}
          >
            {netTotal >= 0 ? "+" : ""}
            {money(netTotal)}
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
          searchPlaceholder="搜尋 單號 / 門市 / 方向 / 事由 / 備註"
          onSearch={setQuery}
          searchValue={query}
          emptyText={(data ?? []).length === 0 ? "這段期間沒有現金調整" : `查無符合「${query}」的調整`}
        />
      )}
      <CashAdjustmentForm
        open={drawerOpen}
        initial={drawerInitial}
        onClose={() => setDrawerOpen(false)}
      />
    </div>
  );
}
