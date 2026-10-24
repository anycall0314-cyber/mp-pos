import { useMemo, useState } from "react";

import { useAllSimCards } from "@/api/hooks";
import type { SimCard, SimCardStatus } from "@/api/types";
import { AppliedFilters } from "@/components/AppliedFilters";
import { Toolbar } from "@/components/Toolbar";
import { Banner } from "@/components/Banner";
import {
  MasterDetail,
  MasterColumn,
} from "@/components/master-detail/MasterDetail";
import { money } from "@/lib/money";
import { appliedList, cond } from "@/lib/appliedFilters";
import { filterSimCards, SIM_SEARCH_PLACEHOLDER, SIM_STATUSES } from "@/lib/simCardSearch";

import { SimCardForm } from "./SimCardForm";
import { errorText } from "@/lib/errorText";

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
      <span className="num">{money(r.deposit)}</span>
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
  const { data, isLoading, isError, error, refetch, isFetching } = useAllSimCards();
  // 卡號 / 廠商搜尋與狀態篩選(全站檢視 R04;規則在 lib/simCardSearch.ts)。放在這一頁:讀取失敗重試時條件還在
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<SimCardStatus | "">("");
  const rows = useMemo(() => filterSimCards(data ?? [], query, status), [data, query, status]);
  const statusLabel = SIM_STATUSES.find((s) => s.value === status)?.label ?? "";
  // 新增 / 編輯:整頁換成表單(owner 2026-10-25 不要 modal);清單留著不卸下,回來時搜尋、捲動位置都還在
  const [editing, setEditing] = useState<{ card: SimCard | null } | null>(null);
  const [flash, setFlash] = useState<string | null>(null);

  return (
    <div className="page">
      <Toolbar
        title="SIM 卡"
        actions={
          !editing && (
            <button
              className="btn"
              onClick={() => {
                setFlash(null);
                setEditing({ card: null });
              }}
            >
              新增卡片
            </button>
          )
        }
      />
      {editing && (
        <SimCardForm
          key={editing.card?.id ?? "new"}
          initial={editing.card}
          onClose={(saved) => {
            setEditing(null);
            setFlash(saved ?? null);
          }}
        />
      )}
      <div className="pane-list" hidden={!!editing}>
      {flash && <Banner kind="success" message={flash} />}
      <div className="list-filterbar">
        <label>
          狀態
          <select value={status} onChange={(e) => setStatus(e.target.value as SimCardStatus | "")}>
            <option value="">全部</option>
            {SIM_STATUSES.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
        </label>
      </div>
      <AppliedFilters
        items={appliedList([cond("狀態", statusLabel), cond("搜尋", query)])}
        onClear={() => {
          setStatus("");
          setQuery("");
        }}
      />
      {isLoading && <div className="md-empty">載入中…</div>}
      {isError && (
        <div className="md-empty">
          載入失敗:{errorText(error)}{" "}
          <button type="button" className="btn" onClick={() => void refetch()} disabled={isFetching}>
            重試
          </button>
        </div>
      )}
      {!isLoading && !isError && (
        <MasterDetail
          rows={rows}
          columns={columns}
          rowKey={(r) => r.id}
          tabs={[]}
          searchPlaceholder={SIM_SEARCH_PLACEHOLDER}
          onSearch={setQuery}
          searchValue={query}
          emptyText={(data ?? []).length === 0 ? "還沒有 SIM 卡" : "查無符合的卡片"}
          onOpen={(r) => {
            setFlash(null);
            setEditing({ card: r });
          }}
        />
      )}
      </div>
    </div>
  );
}
