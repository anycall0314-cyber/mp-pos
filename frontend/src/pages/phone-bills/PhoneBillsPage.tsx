import { useCan } from "@/auth/AuthContext";
import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { usePhoneBills, useVoidPhoneBill } from "@/api/hooks";
import type { PhoneBillCollection } from "@/api/types";
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

import { PhoneBillForm } from "./PhoneBillForm";
import { maskIdNo } from "./mask";
import { errorText } from "@/lib/errorText";

export function PhoneBillsPage() {
  // 清單與合計 = 這段期間(預設本月)。以前不分期間只拿最新 50 筆,合計只加了那 50 筆
  const [from, setFrom] = useState(monthStart);
  const [to, setTo] = useState(localDay);
  const { data, isLoading, isError, error } = usePhoneBills({ from, to });
  const voidMutation = useVoidPhoneBill();
  // 員工帳號的權限(作廢其他單):關掉的人沒有這顆(伺服器也會擋)
  const canVoid = useCan("void_others");
  // 新增代收是整頁的工作區(全站檢視 V04);首頁「代收話費」帶 ?new=1 直接打開
  const [searchParams] = useSearchParams();
  const [creating, setCreating] = useState(() => searchParams.get("new") === "1");
  const todayQ = usePhoneBills({ from: localDay(), to: localDay() });
  const todayStats = useMemo(() => {
    const rows = (todayQ.data ?? []).filter((r) => !r.is_void);
    return todayQ.data ? { count: rows.length, amount: rows.reduce((sum, r) => sum + roundInt(r.amount), 0) } : null;
  }, [todayQ.data]);
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
    .reduce((s, e) => s + roundInt(e.amount), 0);

  const columns: MasterColumn<PhoneBillCollection>[] = [
    { key: "doc_date", header: "日期", render: (r) => r.doc_date },
    { key: "no", header: "單號", render: (r) => <span className="id-code">{r.no}</span> },
    { key: "warehouse", header: "門市", render: (r) => r.warehouse_name, side: true },
    { key: "carrier", header: "電信", render: (r) => r.carrier_name, side: true },
    { key: "phone", header: "電話", render: (r) => r.phone_no },
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
      key: "member",
      side: true,
      header: "會員",
      render: (r) =>
        r.member_name ? `${r.member_code} ${r.member_name}` : "—",
    },
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
  async function handleVoid(r: PhoneBillCollection) {
    try {
      await voidMutation.mutateAsync(r.id);
      toast(`${r.no} 已作廢`, "ok");
    } catch (e) {
      toast(`作廢失敗:${errorText(e)}`, "err");
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
              {r.warehouse_name}
            </dd>
            <dt>電信業者</dt>
            <dd>{r.carrier_name}</dd>
            <dt>電話號碼</dt>
            <dd>{r.phone_no}</dd>
            <dt>金額</dt>
            <dd>{money(r.amount)}</dd>
            <dt>身分證(隱碼)</dt>
            <dd>{maskIdNo(r.id_no)}</dd>
            <dt>經手人</dt>
            <dd>
              {r.handled_by_name
                ? r.handled_by_name
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
            {!r.is_void && canVoid && (
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
        </div>
      ),
    },
  ];

  if (creating) {
    return (
      <div className="page">
        <Toolbar title="代收話費" />
        <PhoneBillForm open onClose={() => setCreating(false)} todayStats={todayStats} />
      </div>
    );
  }

  return (
    <div className="page">
      <Toolbar
        title="代收話費"
        actions={
          <button
            className="btn primary"
            onClick={() => setCreating(true)}
          >
            新增代收
          </button>
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
          searchPlaceholder="搜尋 單號 / 門市 / 電信 / 電話 / 會員 / 經手人"
          onSearch={setQuery}
          searchValue={query}
          emptyText={(data ?? []).length === 0 ? "這段期間沒有代收話費" : `查無符合「${query}」的紀錄`}
        />
      )}
    </div>
  );
}
