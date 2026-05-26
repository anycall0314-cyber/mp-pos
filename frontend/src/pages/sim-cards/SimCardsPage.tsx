import { useState } from "react";

import { useAllSimCards } from "@/api/hooks";
import type { SimCard } from "@/api/types";
import { Toolbar } from "@/components/Toolbar";
import {
  MasterDetail,
  MasterColumn,
  DetailTab,
} from "@/components/master-detail/MasterDetail";

import { SimCardForm } from "./SimCardForm";

const columns: MasterColumn<SimCard>[] = [
  { key: "card_no", header: "卡號", render: (r) => r.card_no },
  {
    key: "vendor",
    header: "廠商",
    render: (r) => `${r.vendor_code} ${r.vendor_name}`,
  },
  {
    key: "deposit",
    header: "押金",
    render: (r) => (
      <span className="num">{Number(r.deposit).toLocaleString()}</span>
    ),
  },
  {
    key: "status",
    header: "狀態",
    render: (r) => r.status_label,
  },
  {
    key: "deposit_refunded",
    header: "押金歸還",
    render: (r) => (r.deposit_refunded ? "是" : "—"),
  },
];

export function SimCardsPage() {
  const { data, isLoading, isError, error } = useAllSimCards();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerInitial, setDrawerInitial] = useState<SimCard | null>(null);

  const tabs: DetailTab<SimCard>[] = [
    {
      key: "basic",
      label: "基本",
      render: (r) => (
        <div>
          <dl>
            <dt>卡號</dt>
            <dd>{r.card_no}</dd>
            <dt>廠商</dt>
            <dd>
              {r.vendor_code} {r.vendor_name}
            </dd>
            <dt>押金</dt>
            <dd>{Number(r.deposit).toLocaleString()}</dd>
            <dt>狀態</dt>
            <dd>{r.status_label}</dd>
            <dt>押金歸還</dt>
            <dd>{r.deposit_refunded ? "已歸還" : "未歸還"}</dd>
            <dt>出卡時間</dt>
            <dd>
              {r.issued_at
                ? r.issued_at.slice(0, 16).replace("T", " ")
                : "—"}
            </dd>
            <dt>開通時間</dt>
            <dd>
              {r.activated_at
                ? r.activated_at.slice(0, 16).replace("T", " ")
                : "—"}
            </dd>
            <dt>退回時間</dt>
            <dd>
              {r.returned_at
                ? r.returned_at.slice(0, 16).replace("T", " ")
                : "—"}
            </dd>
            <dt>備註</dt>
            <dd>{r.note || "—"}</dd>
          </dl>
          <div style={{ marginTop: 12 }}>
            <button
              className="btn primary"
              onClick={() => {
                setDrawerInitial(r);
                setDrawerOpen(true);
              }}
            >
              編輯
            </button>
          </div>
        </div>
      ),
    },
  ];

  return (
    <div className="page">
      <Toolbar
        title="SIM 卡"
        actions={
          <button
            className="btn primary"
            onClick={() => {
              setDrawerInitial(null);
              setDrawerOpen(true);
            }}
          >
            + 新增卡片
          </button>
        }
      />
      {isLoading && <div className="md-empty">載入中…</div>}
      {isError && <div className="md-empty">載入失敗:{String(error)}</div>}
      {!isLoading && !isError && (
        <MasterDetail
          rows={data ?? []}
          columns={columns}
          rowKey={(r) => r.id}
          tabs={tabs}
          searchPlaceholder=""
          emptyDetailHint={
            (data ?? []).length === 0
              ? "尚無 SIM 卡,點右上「+ 新增卡片」開始建立"
              : "從左側選擇卡片檢視詳細"
          }
        />
      )}
      <SimCardForm
        open={drawerOpen}
        initial={drawerInitial}
        onClose={() => setDrawerOpen(false)}
      />
    </div>
  );
}
