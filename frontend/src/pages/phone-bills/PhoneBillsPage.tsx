import { useMemo, useState } from "react";

import { usePhoneBills, useVoidPhoneBill } from "@/api/hooks";
import type { PhoneBillCollection } from "@/api/types";
import { Toolbar } from "@/components/Toolbar";
import {
  MasterDetail,
  MasterColumn,
  DetailTab,
} from "@/components/master-detail/MasterDetail";

import { PhoneBillForm } from "./PhoneBillForm";
import { maskIdNo } from "./mask";

export function PhoneBillsPage() {
  const { data, isLoading, isError, error } = usePhoneBills();
  const voidMutation = useVoidPhoneBill();
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
        e.carrier_name,
        e.phone_no,
        e.handled_by_name,
        e.member_name,
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

  const columns: MasterColumn<PhoneBillCollection>[] = [
    { key: "doc_date", header: "日期", render: (r) => r.doc_date },
    { key: "no", header: "單號", render: (r) => r.no },
    { key: "warehouse", header: "門市", render: (r) => r.warehouse_name },
    { key: "carrier", header: "電信", render: (r) => r.carrier_name },
    { key: "phone", header: "電話", render: (r) => r.phone_no },
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
      key: "member",
      header: "會員",
      render: (r) =>
        r.member_name ? `${r.member_code} ${r.member_name}` : "—",
    },
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

  async function handleVoid(r: PhoneBillCollection) {
    if (!confirm(`確定作廢代收話費單 ${r.no}?`)) return;
    try {
      await voidMutation.mutateAsync(r.id);
    } catch (e) {
      alert(`作廢失敗:${e instanceof Error ? e.message : e}`);
    }
  }

  const tabs: DetailTab<PhoneBillCollection>[] = [
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
            <dt>電信業者</dt>
            <dd>{r.carrier_name}</dd>
            <dt>電話號碼</dt>
            <dd>{r.phone_no}</dd>
            <dt>金額</dt>
            <dd>{Math.round(Number(r.amount)).toLocaleString()}</dd>
            <dt>身分證(隱碼)</dt>
            <dd>{maskIdNo(r.id_no)}</dd>
            <dt>經手人</dt>
            <dd>
              {r.handled_by_name
                ? `${r.handled_by_code} ${r.handled_by_name}`
                : "—"}
            </dd>
            <dt>會員</dt>
            <dd>
              {r.member_name ? `${r.member_code} ${r.member_name}` : "—"}
            </dd>
            <dt>狀態</dt>
            <dd>{r.is_void ? "已作廢" : "有效"}</dd>
          </dl>
          <div style={{ marginTop: 12, display: "flex", gap: 8 }}>
            <button
              className="btn"
              type="button"
              onClick={() =>
                window.open(
                  `/telecom/billing/${r.id}/receipt`,
                  "_blank",
                  "width=380,height=720",
                )
              }
            >
              列印收據
            </button>
            {!r.is_void && (
              <button
                className="btn danger"
                onClick={() => handleVoid(r)}
                disabled={voidMutation.isPending}
              >
                作廢
              </button>
            )}
          </div>
        </div>
      ),
    },
  ];

  return (
    <div className="page">
      <Toolbar
        title="代收話費"
        actions={
          <button
            className="btn primary"
            onClick={() => setDrawerOpen(true)}
          >
            + 新增代收
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
          searchPlaceholder="搜尋 單號 / 門市 / 電信 / 電話 / 會員 / 經手人"
          onSearch={setQuery}
          emptyDetailHint={
            (data ?? []).length === 0
              ? "尚無代收話費紀錄,點右上「+ 新增代收」開始"
              : filtered.length === 0
                ? `查無符合「${query}」的紀錄`
                : "從左側選擇代收單檢視詳細"
          }
        />
      )}
      <PhoneBillForm
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
      />
    </div>
  );
}
