import { useEffect, useRef, useState } from "react";
import { NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";

import { InventoryQueryPage } from "@/pages/inventory/InventoryQueryPage";
import { MembersPage } from "@/pages/members/MembersPage";
import { ProductsPage } from "@/pages/products/ProductsPage";
import { PurchasesPage } from "@/pages/purchases/PurchasesPage";
import { PurchaseEntryPage } from "@/pages/purchases/PurchaseEntryPage";
import { PurchaseLabelsPrintPage } from "@/pages/purchases/PurchaseLabelsPrintPage";
import { SecondhandAcquisitionPage } from "@/pages/secondhand-acquisition/SecondhandAcquisitionPage";
import { SalesPage } from "@/pages/sales/SalesPage";
import { SalesEntryPage } from "@/pages/sales/SalesEntryPage";
import { SalesPrintPage } from "@/pages/sales/SalesPrintPage";
import { SettingsPage } from "@/pages/settings/SettingsPage";
import { SimCardsPage } from "@/pages/sim-cards/SimCardsPage";
import { TelecomPlansPage } from "@/pages/telecom-plans/TelecomPlansPage";

interface NavItem {
  to: string;
  label: string;
}

interface NavGroup {
  key: string;
  label: string;
  items: NavItem[];
}

/**
 * 頂部主分類 + dropdown 子項。
 * 要加新模組就在對應 group 的 items 加一筆;新類別就 push 一個 group。
 */
const NAV_GROUPS: NavGroup[] = [
  {
    key: "master",
    label: "主檔",
    items: [
      { to: "/products", label: "商品" },
      { to: "/telecom-plans", label: "電信方案" },
      { to: "/sim-cards", label: "SIM 卡" },
    ],
  },
  {
    key: "ops",
    label: "進銷",
    items: [
      { to: "/purchases", label: "進貨" },
      { to: "/secondhand-acquisition", label: "中古收購(個人)" },
      { to: "/sales", label: "銷貨" },
      { to: "/transfers", label: "調撥" },
    ],
  },
  {
    key: "members",
    label: "會員",
    items: [{ to: "/members", label: "會員查詢" }],
  },
  {
    key: "stock",
    label: "庫存",
    items: [
      { to: "/inventory", label: "庫存查詢" },
      { to: "/serials", label: "序號查詢" },
    ],
  },
  {
    key: "settings",
    label: "設定",
    items: [{ to: "/settings", label: "系統設定" }],
  },
];

function Placeholder({ title }: { title: string }) {
  return <div className="placeholder">{title}(尚未實作)</div>;
}

function NavGroupMenu({ group }: { group: NavGroup }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const location = useLocation();

  // 本群任一子項命中 → 主類別 active
  const isActive = group.items.some((it) =>
    location.pathname.startsWith(it.to),
  );

  // 路由換頁就關
  useEffect(() => setOpen(false), [location.pathname]);

  // 點外面 / Esc 關閉
  useEffect(() => {
    function onClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node))
        setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, []);

  // 單一子項時直接視為 link,不出 dropdown
  if (group.items.length === 1) {
    const only = group.items[0];
    return (
      <NavLink
        to={only.to}
        className={({ isActive }) =>
          isActive ? "topnav-link active" : "topnav-link"
        }
      >
        {group.label}
      </NavLink>
    );
  }

  return (
    <div
      ref={ref}
      className={`topnav-group${open ? " open" : ""}`}
    >
      <button
        type="button"
        className={`topnav-link${isActive ? " active" : ""}`}
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-haspopup="menu"
      >
        {group.label} <span className="topnav-caret">▾</span>
      </button>
      {open && (
        <div className="topnav-dropdown" role="menu">
          {group.items.map((it) => (
            <NavLink
              key={it.to}
              to={it.to}
              role="menuitem"
              className={({ isActive }) =>
                isActive
                  ? "topnav-dropdown-item active"
                  : "topnav-dropdown-item"
              }
            >
              {it.label}
            </NavLink>
          ))}
        </div>
      )}
    </div>
  );
}

export function App() {
  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">MP POS</div>
        <nav className="topnav">
          {NAV_GROUPS.map((g) => (
            <NavGroupMenu key={g.key} group={g} />
          ))}
        </nav>
      </header>
      <main className="main">
        <Routes>
          <Route path="/" element={<Navigate to="/products" replace />} />
          <Route path="/products" element={<ProductsPage />} />
          <Route path="/telecom-plans" element={<TelecomPlansPage />} />
          <Route path="/sim-cards" element={<SimCardsPage />} />
          <Route path="/purchases" element={<PurchasesPage />} />
          <Route path="/purchases/:id" element={<PurchaseEntryPage />} />
          <Route
            path="/purchases/:id/print/labels"
            element={<PurchaseLabelsPrintPage />}
          />
          <Route
            path="/secondhand-acquisition"
            element={<SecondhandAcquisitionPage />}
          />
          <Route path="/sales" element={<SalesPage />} />
          <Route path="/sales/:id" element={<SalesEntryPage />} />
          <Route path="/sales/:id/print/:type" element={<SalesPrintPage />} />
          <Route path="/members" element={<MembersPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/transfers" element={<Placeholder title="調撥單" />} />
          <Route path="/inventory" element={<InventoryQueryPage />} />
          <Route path="/serials" element={<Placeholder title="序號查詢" />} />
        </Routes>
      </main>
    </div>
  );
}
