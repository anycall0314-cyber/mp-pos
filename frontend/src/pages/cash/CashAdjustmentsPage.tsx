import { useMemo, useState } from "react";

import {
  useCashAdjustments,
  useVoidCashAdjustment,
} from "@/api/hooks";
import type { CashAdjustment } from "@/api/types";
import { Toolbar } from "@/components/Toolbar";
import {
  MasterDetail,
  MasterColumn,
  DetailTab,
} from "@/components/master-detail/MasterDetail";

import { CashAdjustmentForm } from "./CashAdjustmentForm";

export function CashAdjustmentsPage() {
  const { data, isLoading, isError, error } = useCashAdjustments();
  const voidMutation = useVoidCashAdjustment();
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
      const amt = Math.round(Number(a.amount));
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
        <span style={{ color: r.direction === "in" ? "#80d090" : "#ff7070" }}>
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
          style={{ color: r.direction === "in" ? "#80d090" : "#ff7070" }}
        >
          {r.direction === "in" ? "+" : "−"}
          {Math.round(Number(r.amount)).toLocaleString()}
        </span>
      ),
    },
    { key: "note", header: "備註", render: (r) => r.note || "—" },
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

  async function handleVoid(r: CashAdjustment) {
    if (!confirm(`確定作廢現金調整 ${r.no}?`)) return;
    try {
      await voidMutation.mutateAsync(r.id);
    } catch (e) {
      alert(`作廢失敗:${e instanceof Error ? e.message : e}`);
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
            <dd>{Math.round(Number(r.amount)).toLocaleString()}</dd>
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
        title="現金調整"
        actions={
          <button
            className="btn primary"
            onClick={() => {
              setDrawerInitial(null);
              setDrawerOpen(true);
            }}
          >
            + 新增調整
          </button>
        }
      >
        <span style={{ color: "var(--text-dim)", fontSize: 13 }}>
          {filtered.length} 筆,淨額{" "}
          <b
            style={{
              color: netTotal >= 0 ? "#80d090" : "#ff7070",
            }}
          >
            {netTotal >= 0 ? "+" : ""}
            {netTotal.toLocaleString()}
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
          searchPlaceholder="搜尋 單號 / 門市 / 方向 / 事由 / 備註"
          onSearch={setQuery}
          emptyDetailHint={
            (data ?? []).length === 0
              ? "尚無現金調整,點右上「+ 新增調整」開始記錄"
              : filtered.length === 0
                ? `查無符合「${query}」的調整`
                : "從左側選擇調整單檢視詳細"
          }
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
