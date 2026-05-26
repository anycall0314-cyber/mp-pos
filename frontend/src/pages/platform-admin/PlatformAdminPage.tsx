import { useState } from "react";

import { Toolbar } from "@/components/Toolbar";

import { PlatformTenantsTab } from "./PlatformTenantsTab";
import { PlatformUsersTab } from "./PlatformUsersTab";
import { PlatformWarehousesTab } from "./PlatformWarehousesTab";

type Tab = "tenants" | "users" | "warehouses";

export function PlatformAdminPage() {
  const [tab, setTab] = useState<Tab>("tenants");
  return (
    <div className="page">
      <Toolbar title="平台管理">
        <div style={{ display: "flex", gap: 4 }}>
          {(
            [
              { key: "tenants", label: "經銷商" },
              { key: "users", label: "用戶" },
              { key: "warehouses", label: "倉別" },
            ] as const
          ).map((t) => (
            <button
              key={t.key}
              type="button"
              className={tab === t.key ? "btn primary" : "btn"}
              onClick={() => setTab(t.key)}
            >
              {t.label}
            </button>
          ))}
        </div>
      </Toolbar>
      <div className="entry-body">
        {tab === "tenants" && <PlatformTenantsTab />}
        {tab === "users" && <PlatformUsersTab />}
        {tab === "warehouses" && <PlatformWarehousesTab />}
      </div>
    </div>
  );
}
