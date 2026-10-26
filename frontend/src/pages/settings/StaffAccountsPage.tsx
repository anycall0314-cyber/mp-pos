import { useMemo, useState } from "react";

import { useStaffAccounts, useWarehouses } from "@/api/hooks";
import type { StaffAccount, StaffRole } from "@/api/types";
import { Banner } from "@/components/Banner";
import { MasterColumn, MasterDetail } from "@/components/master-detail/MasterDetail";
import { Toolbar } from "@/components/Toolbar";
import { TabPanel, Tabs } from "@/components/ui";
import { apiErrorText } from "@/components/workbench/errors";
import { filterAccounts, roleLabel } from "@/lib/staffAccess";

import { StaffAccountForm } from "./StaffAccountForm";
import { StaffRoleForm } from "./StaffRoleForm";

/**
 * 系統設定 → 員工帳號(owner 2026-10-27:身份別 + 單一帳號的例外,權限改成直的排)。
 * 「帳號」:一列一人,點一列整頁打開(名字、門市、身份別、例外、重設密碼、停用);管理員帳號 = 管理者,固定全開、這裡不能改。
 * 「身份別」:店長、門市、行政…自己增刪;改勾選,那個身份的人一起變。規則在 lib/staffAccess.ts,真正擋的是伺服器。
 */
type View = { kind: "account"; row: StaffAccount | null } | { kind: "role"; row: StaffRole | null };
type Tab = "accounts" | "roles";
type RoleRow = { id: number; name: string; accounts: number; role: StaffRole | null };

const accountColumns: MasterColumn<StaffAccount>[] = [
  { key: "name", header: "名字", render: (a) => a.name || a.username },
  { key: "username", header: "帳號", render: (a) => a.username },
  { key: "role", header: "身份別", render: roleLabel },
  { key: "warehouse", header: "門市", render: (a) => (a.warehouse ? `${a.warehouse}${a.warehouse_locked ? "(鎖)" : ""}` : "全部") },
  {
    key: "state",
    header: "狀態",
    render: (a) => [a.is_active ? "" : "已停用", a.exceptions.length ? `例外 ${a.exceptions.length}` : ""].filter(Boolean).join(" · ") || "—",
  },
];

const roleColumns: MasterColumn<RoleRow>[] = [
  { key: "name", header: "身份別", render: (r) => r.name },
  { key: "accounts", header: "人數", render: (r) => <span className="num">{r.accounts}</span> },
];

export function StaffAccountsPage() {
  const { data, isLoading, isError, error, refetch, isFetching } = useStaffAccounts();
  const warehouses = useWarehouses();
  const stores = (warehouses.data ?? []).filter((w) => w.is_active);
  const [tab, setTab] = useState<Tab>("accounts");
  const [view, setView] = useState<View | null>(null);
  const [flash, setFlash] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [roleQuery, setRoleQuery] = useState("");
  const accounts = useMemo(() => filterAccounts(data?.accounts ?? [], query), [data, query]);
  const roleRows: RoleRow[] = useMemo(() => {
    const managers = (data?.accounts ?? []).filter((a) => !a.editable).length;
    const q = roleQuery.trim();
    return [
      { id: 0, name: "管理者", accounts: managers, role: null },
      ...(data?.roles ?? []).map((r) => ({ id: r.id, name: r.name, accounts: r.accounts, role: r })),
    ].filter((r) => !q || r.name.includes(q));
  }, [data, roleQuery]);

  function open(next: View) {
    setFlash(null);
    setView(next);
  }

  return (
    <div className="page">
      <Toolbar
        title="員工帳號"
        actions={
          !view &&
          data && (
            <button type="button" className="btn" onClick={() => open(tab === "accounts" ? { kind: "account", row: null } : { kind: "role", row: null })}>
              {tab === "accounts" ? "新增帳號" : "新增身份別"}
            </button>
          )
        }
      />
      {view && data && view.kind === "account" && (
        <StaffAccountForm
          key={view.row?.id ?? "new"}
          data={data}
          initial={view.row}
          stores={stores}
          onClose={(saved) => {
            setView(null);
            setFlash(saved ?? null);
          }}
        />
      )}
      {view && data && view.kind === "role" && (
        <StaffRoleForm
          key={view.row?.id ?? "new"}
          data={data}
          initial={view.row}
          onClose={(saved) => {
            setView(null);
            setFlash(saved ?? null);
          }}
        />
      )}
      <div className="pane-list" hidden={!!view}>
        {flash && <Banner kind="success" message={flash} />}
        <Tabs
          id="staff"
          label="員工帳號"
          items={[
            { key: "accounts", label: "帳號" },
            { key: "roles", label: "身份別" },
          ]}
          value={tab}
          onChange={setTab}
        />
        {isLoading && <div className="md-empty">載入中…</div>}
        {isError && (
          <div className="md-empty">
            {apiErrorText(error)}{" "}
            <button type="button" className="btn" onClick={() => void refetch()} disabled={isFetching}>
              重試
            </button>
          </div>
        )}
        {data && (
          <>
            <TabPanel id="staff" k="accounts" active={tab === "accounts"}>
              <MasterDetail
                rows={accounts}
                columns={accountColumns}
                rowKey={(a) => a.id}
                tabs={[]}
                searchPlaceholder="搜尋名字、帳號"
                onSearch={setQuery}
                searchValue={query}
                emptyText={data.accounts.length === 0 ? "還沒有帳號" : "查無符合的帳號"}
                // 管理員帳號固定全開,這裡不能改
                onOpen={(a) => a.editable && open({ kind: "account", row: a })}
              />
            </TabPanel>
            <TabPanel id="staff" k="roles" active={tab === "roles"}>
              <MasterDetail
                rows={roleRows}
                columns={roleColumns}
                rowKey={(r) => r.id}
                tabs={[]}
                searchPlaceholder="搜尋身份別"
                onSearch={setRoleQuery}
                searchValue={roleQuery}
                emptyText="查無符合的身份別"
                // 「管理者」固定全開,不能改、不能刪
                onOpen={(r) => r.role && open({ kind: "role", row: r.role })}
              />
            </TabPanel>
          </>
        )}
      </div>
    </div>
  );
}
