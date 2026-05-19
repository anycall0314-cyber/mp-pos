import { useState } from "react";

import { useTelecomPlans } from "@/api/hooks";
import type { TelecomPlan } from "@/api/types";
import { Toolbar } from "@/components/Toolbar";
import {
  MasterDetail,
  MasterColumn,
  DetailTab,
} from "@/components/master-detail/MasterDetail";

import { BulkAddTelecomPlansModal } from "./BulkAddTelecomPlansModal";
import { TelecomPlanForm } from "./TelecomPlanForm";

const columns: MasterColumn<TelecomPlan>[] = [
  { key: "name", header: "專案名稱", render: (r) => r.name || "—" },
  {
    key: "carrier",
    header: "電信商",
    render: (r) => `${r.carrier_code} ${r.carrier_name}`,
  },
  {
    key: "monthly_fee",
    header: "月租",
    render: (r) => <span className="num">{r.monthly_fee.toLocaleString()}</span>,
  },
  {
    key: "contract_months",
    header: "綁約",
    render: (r) => <span className="num">{r.contract_months} 月</span>,
  },
  { key: "kind", header: "類型", render: (r) => r.kind_label },
  {
    key: "commission",
    header: "佣金",
    render: (r) => (
      <span className="num">{Number(r.commission).toLocaleString()}</span>
    ),
  },
  { key: "is_active", header: "啟用", render: (r) => (r.is_active ? "✓" : "—") },
];

export function TelecomPlansPage() {
  const { data, isLoading, isError, error } = useTelecomPlans({
    includeInactive: true,
  });
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerInitial, setDrawerInitial] = useState<TelecomPlan | null>(null);
  const [bulkOpen, setBulkOpen] = useState(false);
  const [bulkResult, setBulkResult] = useState<string | null>(null);

  const tabs: DetailTab<TelecomPlan>[] = [
    {
      key: "basic",
      label: "基本",
      render: (r) => (
        <div>
          <dl>
            <dt>專案名稱</dt>
            <dd>{r.name || "—"}</dd>
            <dt>電信商</dt>
            <dd>
              {r.carrier_code} {r.carrier_name}
            </dd>
            <dt>月租</dt>
            <dd>{r.monthly_fee.toLocaleString()}</dd>
            <dt>綁約月數</dt>
            <dd>{r.contract_months}</dd>
            <dt>類型</dt>
            <dd>{r.kind_label}</dd>
            <dt>佣金</dt>
            <dd>{Number(r.commission).toLocaleString()}</dd>
            <dt>備註</dt>
            <dd>{r.note || "—"}</dd>
            <dt>狀態</dt>
            <dd>{r.is_active ? "啟用" : "停用"}</dd>
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
        title="電信方案"
        actions={
          <>
            <button className="btn" onClick={() => setBulkOpen(true)}>
              批次新增
            </button>
            <button
              className="btn primary"
              onClick={() => {
                setDrawerInitial(null);
                setDrawerOpen(true);
              }}
            >
              + 新增方案
            </button>
          </>
        }
      />
      {bulkResult && (
        <div
          style={{
            padding: "6px 16px",
            background: "rgba(128,208,144,0.15)",
            color: "#80d090",
            fontSize: 12,
          }}
        >
          {bulkResult}
        </div>
      )}
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
              ? "尚無方案,點右上「+ 新增方案」開始建立"
              : "從左側選擇方案檢視詳細"
          }
        />
      )}
      <TelecomPlanForm
        open={drawerOpen}
        initial={drawerInitial}
        onClose={() => setDrawerOpen(false)}
      />
      <BulkAddTelecomPlansModal
        open={bulkOpen}
        onClose={() => setBulkOpen(false)}
        onSuccess={(count) => {
          setBulkOpen(false);
          setBulkResult(`成功建立 ${count} 筆方案`);
          setTimeout(() => setBulkResult(null), 4000);
        }}
      />
    </div>
  );
}
