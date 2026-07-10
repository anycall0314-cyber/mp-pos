import { useEffect, useState } from "react";
import { NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";

import { useAuth } from "@/auth/AuthContext";
import { LoginPage } from "@/pages/login/LoginPage";
import { PlatformAdminPage } from "@/pages/platform-admin/PlatformAdminPage";
import { HomePage } from "@/pages/home/HomePage";
import { CashAdjustmentsPage } from "@/pages/cash/CashAdjustmentsPage";
import { PettyExpensesPage } from "@/pages/cash/PettyExpensesPage";
import { PhoneBillsPage } from "@/pages/phone-bills/PhoneBillsPage";
import { PhoneBillReceiptPage } from "@/pages/phone-bills/PhoneBillReceiptPage";
import { CategoriesPage } from "@/pages/inventory/CategoriesPage";
import { InventoryAlertsPage } from "@/pages/inventory/InventoryAlertsPage";
import { InventoryQueryPage } from "@/pages/inventory/InventoryQueryPage";
import { IntakePage } from "@/pages/intake/IntakePage";
import { RepairEntryPage } from "@/pages/repairs/RepairEntryPage";
import { RepairReceiptPrintPage } from "@/pages/repairs/RepairReceiptPrintPage";
import { RepairItemsPage } from "@/pages/repairs/RepairItemsPage";
import { RepairsPage } from "@/pages/repairs/RepairsPage";
import { BrandSeriesPage } from "@/pages/products/BrandSeriesPage";
import { ConditionsPage } from "@/pages/products/ConditionsPage";
import { NewPhoneModelWizardPage } from "@/pages/products/NewPhoneModelWizardPage";
import { PartTemplatesPage } from "@/pages/products/PartTemplatesPage";
import { ProductTypesPage } from "@/pages/products/ProductTypesPage";
import { ProductsPage } from "@/pages/products/ProductsPage";
import { PurchasesPage } from "@/pages/purchases/PurchasesPage";
import { PurchaseEntryPage } from "@/pages/purchases/PurchaseEntryPage";
import { PurchaseLabelsPrintPage } from "@/pages/purchases/PurchaseLabelsPrintPage";
import { BusinessDailyReportPage } from "@/pages/reports/BusinessDailyReport";
import { PartsUsageReportPage } from "@/pages/reports/PartsUsageReportPage";
import { SalesDailyReportPage } from "@/pages/reports/SalesDailyReport";
import { SecondhandAcquisitionPage } from "@/pages/secondhand-acquisition/SecondhandAcquisitionPage";
import { TransfersPage } from "@/pages/transfers/TransfersPage";
import { TransferEntryPage } from "@/pages/transfers/TransferEntryPage";
import { SalesPage } from "@/pages/sales/SalesPage";
import { SalesEntryPage } from "@/pages/sales/SalesEntryPage";
import { SalesPrintPage } from "@/pages/sales/SalesPrintPage";
import { SalesReturnEntryPage } from "@/pages/sales/SalesReturnEntryPage";
import { CustomersPage } from "@/pages/customers/CustomersPage";
import { MembersPage } from "@/pages/members/MembersPage";
import { SalesPersonsPage } from "@/pages/sales-persons/SalesPersonsPage";
import { SettingsPage } from "@/pages/settings/SettingsPage";
import { SimCardsPage } from "@/pages/sim-cards/SimCardsPage";
import { SuppliersPage } from "@/pages/suppliers/SuppliersPage";
import { TelecomPlansPage } from "@/pages/telecom-plans/TelecomPlansPage";
import { NavSection, PLATFORM_NAV_GROUP, SIDEBAR_NAV } from "@/nav";

function Placeholder({ title }: { title: string }) {
  return <div className="placeholder">{title}(尚未實作)</div>;
}

const SIDEBAR_GROUPS_KEY = "sidebar_collapsed_groups";

function readCollapsedGroups(): Record<string, boolean> {
  try {
    return JSON.parse(localStorage.getItem(SIDEBAR_GROUPS_KEY) || "{}");
  } catch {
    return {};
  }
}

/**
 * 側邊欄導覽:每個分類標題可點折疊(記在 localStorage,下次記得)。
 * 預設全展開;點連結自動關閉(窄畫面的)側邊欄。
 */
function SidebarNav({
  role,
  onNavigate,
}: {
  role?: string;
  onNavigate: () => void;
}) {
  const sections: NavSection[] = [...SIDEBAR_NAV];
  if (role === "platform_admin") {
    sections.push({
      label: PLATFORM_NAV_GROUP.label,
      items: PLATFORM_NAV_GROUP.items,
    });
  }

  const [collapsed, setCollapsed] = useState<Record<string, boolean>>(
    readCollapsedGroups,
  );

  function toggle(label: string) {
    setCollapsed((prev) => {
      const next = { ...prev, [label]: !prev[label] };
      try {
        localStorage.setItem(SIDEBAR_GROUPS_KEY, JSON.stringify(next));
      } catch {}
      return next;
    });
  }

  return (
    <nav className="sidebar-nav">
      {sections.map((s) => {
        const open = !collapsed[s.label];
        return (
          <div key={s.label} className={`sidebar-group${open ? " open" : ""}`}>
            <button
              type="button"
              className="sidebar-group-label"
              onClick={() => toggle(s.label)}
              aria-expanded={open}
            >
              <span>{s.label}</span>
              <svg
                className="sidebar-caret"
                width="12"
                height="12"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M9 6l6 6-6 6" />
              </svg>
            </button>
            {open &&
              s.items.map((it) => (
                <NavLink
                  key={it.to}
                  to={it.to}
                  end={it.to === "/home"}
                  onClick={onNavigate}
                  className={({ isActive }) =>
                    isActive ? "sidebar-link active" : "sidebar-link"
                  }
                >
                  {it.label}
                </NavLink>
              ))}
          </div>
        );
      })}
    </nav>
  );
}

type Theme = "dark" | "light";

function readTheme(): Theme {
  try {
    return localStorage.getItem("theme") === "light" ? "light" : "dark";
  } catch {
    return "dark";
  }
}

export function App() {
  const [theme, setTheme] = useState<Theme>(readTheme);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const location = useLocation();
  const { user, loading: authLoading, logout } = useAuth();
  // 路由切換自動關閉漢堡選單
  useEffect(() => setMobileNavOpen(false), [location.pathname]);
  const focusMode = new URLSearchParams(location.search).get("focus") === "1";
  // 列印頁面(/print/、/receipt、/labels)不渲染 topbar 與 main 框,避免列印時帶到導覽
  const isPrintMode =
    /\/print\//.test(location.pathname) ||
    /\/receipt(\/|$)/.test(location.pathname) ||
    /\/labels(\/|$)/.test(location.pathname);
  const isLoginPage = location.pathname === "/login";
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    try {
      localStorage.setItem("theme", theme);
    } catch {}
  }, [theme]);

  // /login 頁直接渲染,跳過所有 shell + guard
  if (isLoginPage) {
    return (
      <Routes>
        <Route path="/login" element={<LoginPage />} />
      </Routes>
    );
  }

  // 登入狀態還在解析:擋一下避免閃 login
  if (authLoading) {
    return (
      <div style={{ padding: 40, textAlign: "center", color: "var(--text-dim)" }}>
        載入中…
      </div>
    );
  }

  // 未登入 + 不是列印頁(列印頁是 window.open,允許短時間沒 user)→ 強制跳 /login
  if (!user && !isPrintMode) {
    return (
      <Navigate
        to="/login"
        replace
        state={{ from: location.pathname + location.search }}
      />
    );
  }

  return (
    <div className={`app-shell${mobileNavOpen ? " mobile-nav-open" : ""}`}>
      {!focusMode && !isPrintMode && (
        <>
          <div className="mobile-topbar">
            <button
              type="button"
              className="hamburger"
              onClick={() => setMobileNavOpen((v) => !v)}
              aria-label={mobileNavOpen ? "關閉選單" : "打開選單"}
            >
              {mobileNavOpen ? "關閉" : "選單"}
            </button>
            <div className="brand">MP POS</div>
          </div>
          <aside className="sidebar">
            <div className="sidebar-brand">MP POS</div>
            <SidebarNav
              role={user?.profile?.role}
              onNavigate={() => setMobileNavOpen(false)}
            />
            <div className="sidebar-footer">
              {user && (
                <div className="user-pill">
                  <div className="user-pill-text">
                    <span className="user-pill-name">{user.username}</span>
                    <span className="user-pill-meta">
                      {user.profile?.role_label ?? "—"}
                      {user.profile?.tenant_name
                        ? ` · ${user.profile.tenant_name}`
                        : ""}
                      {user.profile?.default_warehouse_name
                        ? ` · ${user.profile.default_warehouse_name}`
                        : ""}
                    </span>
                  </div>
                  <button
                    type="button"
                    className="btn user-pill-logout"
                    onClick={() => logout()}
                    title="登出"
                  >
                    登出
                  </button>
                </div>
              )}
              <button
                type="button"
                className="theme-toggle"
                onClick={() =>
                  setTheme((t) => (t === "dark" ? "light" : "dark"))
                }
                title={theme === "dark" ? "切換到日間模式" : "切換到夜間模式"}
                aria-label="切換主題"
              >
                {theme === "dark" ? (
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <circle cx="12" cy="12" r="4" />
                    <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" />
                  </svg>
                ) : (
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
                  </svg>
                )}
              </button>
            </div>
          </aside>
          {mobileNavOpen && (
            <div
              className="sidebar-backdrop"
              onClick={() => setMobileNavOpen(false)}
            />
          )}
        </>
      )}
      <div className="app-body">
        {focusMode && !isPrintMode && (
          <div className="focus-banner">
            檢視模式 — 此分頁僅供資料查看,不提供任何操作
          </div>
        )}
        <main className="main">
        <Routes>
          <Route path="/" element={<Navigate to="/home" replace />} />
          <Route path="/home" element={<HomePage />} />
          <Route path="/products" element={<ProductsPage />} />
          <Route path="/intake" element={<IntakePage />} />
          <Route path="/part-templates" element={<PartTemplatesPage />} />
          <Route path="/brand-series" element={<BrandSeriesPage />} />
          <Route path="/product-types" element={<ProductTypesPage />} />
          <Route path="/conditions" element={<ConditionsPage />} />
          <Route
            path="/products/new-phone-model"
            element={<NewPhoneModelWizardPage />}
          />
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
          <Route
            path="/sales/returns/new"
            element={<SalesReturnEntryPage />}
          />
          <Route
            path="/sales/returns/:id"
            element={<SalesReturnEntryPage />}
          />
          <Route path="/sales/:id" element={<SalesEntryPage />} />
          <Route path="/sales/:id/print/:type" element={<SalesPrintPage />} />
          <Route path="/customers" element={<CustomersPage />} />
          <Route path="/expenses" element={<PettyExpensesPage />} />
          <Route
            path="/cash-adjustments"
            element={<CashAdjustmentsPage />}
          />
          <Route path="/members" element={<MembersPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route
            path="/platform/admin"
            element={
              user?.profile?.role === "platform_admin" ? (
                <PlatformAdminPage />
              ) : (
                <Navigate to="/home" replace />
              )
            }
          />
          <Route path="/suppliers" element={<SuppliersPage />} />
          <Route path="/sales-persons" element={<SalesPersonsPage />} />
          <Route path="/transfers" element={<TransfersPage />} />
          <Route path="/transfers/:id" element={<TransferEntryPage />} />
          <Route path="/inventory" element={<InventoryQueryPage />} />
          <Route path="/inventory/alerts" element={<InventoryAlertsPage />} />
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
          <Route path="/telecom/billing" element={<PhoneBillsPage />} />
          <Route
            path="/telecom/billing/:id/receipt"
            element={<PhoneBillReceiptPage />}
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
          <Route path="/repairs" element={<RepairsPage />} />
          <Route path="/repairs/items" element={<RepairItemsPage />} />
          <Route path="/repairs/:id" element={<RepairEntryPage />} />
          <Route
            path="/print/repair-receipt/:id"
            element={<RepairReceiptPrintPage />}
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
            element={<BusinessDailyReportPage />}
          />
          <Route
            path="/reports/parts-usage"
            element={<PartsUsageReportPage />}
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
    </div>
  );
}
