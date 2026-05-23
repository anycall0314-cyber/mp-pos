import { useEffect, useRef, useState } from "react";
import { NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";

import { CategoriesPage } from "@/pages/inventory/CategoriesPage";
import { InventoryQueryPage } from "@/pages/inventory/InventoryQueryPage";
import { ProductsPage } from "@/pages/products/ProductsPage";
import { PurchasesPage } from "@/pages/purchases/PurchasesPage";
import { PurchaseEntryPage } from "@/pages/purchases/PurchaseEntryPage";
import { PurchaseLabelsPrintPage } from "@/pages/purchases/PurchaseLabelsPrintPage";
import { SalesDailyReportPage } from "@/pages/reports/SalesDailyReport";
import { SecondhandAcquisitionPage } from "@/pages/secondhand-acquisition/SecondhandAcquisitionPage";
import { TransfersPage } from "@/pages/transfers/TransfersPage";
import { TransferEntryPage } from "@/pages/transfers/TransferEntryPage";
import { SalesPage } from "@/pages/sales/SalesPage";
import { SalesEntryPage } from "@/pages/sales/SalesEntryPage";
import { SalesPrintPage } from "@/pages/sales/SalesPrintPage";
import { CustomersPage } from "@/pages/customers/CustomersPage";
import { SalesPersonsPage } from "@/pages/sales-persons/SalesPersonsPage";
import { SettingsPage } from "@/pages/settings/SettingsPage";
import { SimCardsPage } from "@/pages/sim-cards/SimCardsPage";
import { SuppliersPage } from "@/pages/suppliers/SuppliersPage";
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
    key: "reports",
    label: "報表",
    items: [
      { to: "/reports/sales-daily", label: "銷貨日報" },
      { to: "/reports/business-daily", label: "營業日報" },
      { to: "/reports/margin-summary", label: "毛利彙總" },
      { to: "/reports/invoice-detail", label: "發票明細" },
    ],
  },
  {
    key: "stock",
    label: "庫存",
    items: [
      { to: "/inventory", label: "庫存查詢" },
      { to: "/purchases", label: "進貨作業" },
      { to: "/secondhand-acquisition", label: "中古入庫" },
      { to: "/products", label: "建立商品" },
      { to: "/serials", label: "序號查詢" },
      { to: "/inventory/stocktake", label: "盤點作業" },
      { to: "/inventory/movements", label: "異動查詢" },
    ],
  },
  {
    key: "sales",
    label: "銷貨",
    items: [
      { to: "/sales", label: "銷貨作業" },
      { to: "/transfers", label: "調撥作業" },
      { to: "/sales/pre-orders", label: "訂購作業" },
      { to: "/customers", label: "客戶管理" },
    ],
  },
  {
    key: "telecom",
    label: "門號",
    items: [
      { to: "/telecom/billing", label: "代收話費" },
      { to: "/telecom/activations", label: "開通查詢" },
      { to: "/telecom-plans", label: "方案管理" },
      { to: "/sim-cards", label: "卡片管理" },
      { to: "/telecom/commissions", label: "佣金對帳" },
      { to: "/telecom/expiries", label: "到期查詢" },
    ],
  },
  {
    key: "repairs",
    label: "維修",
    items: [
      { to: "/repairs/new", label: "建立報修" },
      { to: "/repairs", label: "維修列表" },
      { to: "/repairs/quotes", label: "報價作業" },
      { to: "/repairs/library", label: "資料庫" },
    ],
  },
  {
    key: "settings",
    label: "設定",
    items: [
      { to: "/settings", label: "發票付款" },
      { to: "/suppliers", label: "供應商" },
      { to: "/sales-persons", label: "業務員" },
      { to: "/settings/users", label: "人員權限" },
    ],
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
          <Route path="/customers" element={<CustomersPage />} />
          <Route
            path="/members"
            element={<Navigate to="/customers?tab=member" replace />}
          />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/suppliers" element={<SuppliersPage />} />
          <Route path="/sales-persons" element={<SalesPersonsPage />} />
          <Route path="/transfers" element={<TransfersPage />} />
          <Route path="/transfers/:id" element={<TransferEntryPage />} />
          <Route path="/inventory" element={<InventoryQueryPage />} />
          <Route path="/inventory/categories" element={<CategoriesPage />} />
          <Route path="/serials" element={<Placeholder title="序號查詢" />} />
          <Route
            path="/inventory/stocktake"
            element={<Placeholder title="盤點作業" />}
          />
          <Route
            path="/inventory/movements"
            element={<Placeholder title="異動查詢" />}
          />
          <Route
            path="/sales/pre-orders"
            element={<Placeholder title="訂購作業" />}
          />
          <Route
            path="/telecom/billing"
            element={<Placeholder title="代收話費" />}
          />
          <Route
            path="/telecom/activations"
            element={<Placeholder title="開通查詢" />}
          />
          <Route
            path="/telecom/commissions"
            element={<Placeholder title="佣金對帳" />}
          />
          <Route
            path="/telecom/expiries"
            element={<Placeholder title="到期查詢" />}
          />
          <Route path="/repairs" element={<Placeholder title="維修列表" />} />
          <Route
            path="/repairs/new"
            element={<Placeholder title="建立報修" />}
          />
          <Route
            path="/repairs/quotes"
            element={<Placeholder title="報價作業" />}
          />
          <Route
            path="/repairs/library"
            element={<Placeholder title="維修資料庫" />}
          />
          <Route
            path="/settings/users"
            element={<Placeholder title="人員權限" />}
          />
          <Route
            path="/reports/sales-daily"
            element={<SalesDailyReportPage />}
          />
          <Route
            path="/reports/business-daily"
            element={<Placeholder title="營業日報" />}
          />
          <Route
            path="/reports/margin-summary"
            element={<Placeholder title="毛利彙總" />}
          />
          <Route
            path="/reports/invoice-detail"
            element={<Placeholder title="發票明細" />}
          />
        </Routes>
      </main>
    </div>
  );
}
