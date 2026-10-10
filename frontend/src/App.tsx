import { useEffect, useState } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";

import { useAuth } from "@/auth/AuthContext";
import { LoginPage } from "@/pages/login/LoginPage";
import { PhonePhotoPage } from "@/pages/photos/PhonePhotoPage";
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
import { PurchaseListPage } from "@/pages/purchases/PurchaseListPage";
import { PurchaseWorkbenchPage } from "@/pages/purchases/PurchaseWorkbenchPage";
import { LabelPrintPage } from "@/pages/labels/LabelPrintPage";
import { BusinessDailyReportPage } from "@/pages/reports/BusinessDailyReport";
import { CommissionLinesPage } from "@/pages/reports/CommissionLinesPage";
import { ExploreReportPage } from "@/pages/reports/ExploreReportPage";
import { FixedReportPage } from "@/pages/reports/FixedReportPage";
import { PartsUsageReportPage } from "@/pages/reports/PartsUsageReportPage";
import { SalesDailyReportPage } from "@/pages/reports/SalesDailyReport";
import { SecondhandAcquisitionPage } from "@/pages/secondhand-acquisition/SecondhandAcquisitionPage";
import { TransferWorkbenchPage } from "@/pages/transfers/TransferWorkbenchPage";
import { ToastHost } from "@/components/workbench/toast";
import { SalesReturnsPage } from "@/pages/sales/SalesPage";
import { SalesListPage } from "@/pages/sales/SalesListPage";
import { SalesWorkbenchPage } from "@/pages/sales/SalesWorkbenchPage";
import { SalesPrintPage } from "@/pages/sales/SalesPrintPage";
import { SalesReturnEntryPage } from "@/pages/sales/SalesReturnEntryPage";
import { CustomersPage } from "@/pages/customers/CustomersPage";
import { MembersPage } from "@/pages/members/MembersPage";
import { SalesPersonsPage } from "@/pages/sales-persons/SalesPersonsPage";
import { BackupPage } from "@/pages/backup/BackupPage";
import { LegacyMappingPage } from "@/pages/legacy/LegacyMappingPage";
import { LedgerChecksPage } from "@/pages/ledger/LedgerChecksPage";
import { NeedsAbility } from "@/components/NeedsAbility";
import { VendorLinksPage } from "@/pages/settings/VendorLinksPage";
import { VendorOrdersPage } from "@/pages/vendor-orders/VendorOrdersPage";
import { FIXED_REPORTS } from "@/lib/fixedReports";
import { SettingsPage } from "@/pages/settings/SettingsPage";
import { StaffAccountsPage } from "@/pages/settings/StaffAccountsPage";
import { SimCardsPage } from "@/pages/sim-cards/SimCardsPage";
import { SuppliersPage } from "@/pages/suppliers/SuppliersPage";
import { ContractsPage } from "@/pages/telecom/ContractsPage";
import { TelecomPlansPage } from "@/pages/telecom-plans/TelecomPlansPage";
import { ModuleBar } from "@/components/shell/ModuleBar";
import { Sidebar } from "@/components/shell/Sidebar";
import { matchForUser, visibleModules } from "@/nav";

function Placeholder({ title }: { title: string }) {
  return <div className="placeholder">{title}(尚未實作)</div>;
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

  // 手機掃 QR Code 開的拍照頁:不用登入(只認 QR Code 的憑證),不套外框
  if (location.pathname === "/m/photo") {
    return <PhonePhotoPage />;
  }

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

  const who = { role: user?.profile?.role, abilities: user?.abilities };
  const modules = visibleModules(who);
  const navMatch = matchForUser(location.pathname, who);

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
          <Sidebar
            modules={modules}
            match={navMatch}
            onNavigate={() => setMobileNavOpen(false)}
            onOpenRequest={() => setMobileNavOpen(true)}
            footer={
              <>
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
              </>
            }
          />
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
        {!focusMode && !isPrintMode && <ModuleBar match={navMatch} pathname={location.pathname} />}
        <div className="main-page">
        <Routes>
          <Route path="/" element={<Navigate to="/home" replace />} />
          <Route path="/home" element={<HomePage />} />
          <Route path="/products" element={<ProductsPage />} />
          <Route
            path="/intake"
            element={
              <NeedsAbility ability="purchase" doing="進貨入庫">
                <IntakePage />
              </NeedsAbility>
            }
          />
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
          <Route path="/purchases" element={<PurchaseListPage />} />
          <Route
            path="/purchases/new"
            element={
              <NeedsAbility ability="purchase" doing="進貨入庫">
                <PurchaseWorkbenchPage />
              </NeedsAbility>
            }
          />
          <Route path="/purchases/:id" element={<PurchaseListPage />} />
          <Route
            path="/purchases/:id/print/labels"
            element={<LabelPrintPage />}
          />
          <Route path="/labels/print" element={<LabelPrintPage />} />
          <Route
            path="/secondhand-acquisition"
            element={<SecondhandAcquisitionPage />}
          />
          <Route path="/sales" element={<SalesListPage />} />
          <Route path="/sales/new" element={<SalesWorkbenchPage />} />
          <Route path="/sales/returns" element={<SalesReturnsPage />} />
          <Route
            path="/sales/returns/new"
            element={<SalesReturnEntryPage />}
          />
          <Route
            path="/sales/returns/:id"
            element={<SalesReturnEntryPage />}
          />
          <Route path="/sales/:id" element={<SalesListPage />} />
          <Route path="/sales/:id/print/:type" element={<SalesPrintPage />} />
          <Route path="/customers" element={<CustomersPage />} />
          <Route path="/expenses" element={<PettyExpensesPage />} />
          <Route
            path="/cash-adjustments"
            element={<CashAdjustmentsPage />}
          />
          <Route path="/members" element={<MembersPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/settings/backup" element={<BackupPage />} />
          <Route path="/settings/legacy" element={<LegacyMappingPage />} />
          <Route path="/settings/ledger" element={<LedgerChecksPage />} />
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
          <Route path="/transfers" element={<TransferWorkbenchPage />} />
          <Route path="/transfers/:id" element={<TransferWorkbenchPage />} />
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
            element={<ContractsPage />}
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
            element={<StaffAccountsPage />}
          />
          <Route path="/settings/vendors" element={<VendorLinksPage />} />
          <Route
            path="/vendor-orders"
            element={
              <NeedsAbility ability="vendor_order" doing="叫貨">
                <VendorOrdersPage />
              </NeedsAbility>
            }
          />
          <Route
            path="/reports/sales-daily"
            element={
              <NeedsAbility ability="report_sales_daily" doing="看銷貨日報">
                <SalesDailyReportPage />
              </NeedsAbility>
            }
          />
          {FIXED_REPORTS.map((r) => (
            <Route
              key={r.key}
              path={r.path}
              element={
                <NeedsAbility ability={r.ability} doing={`看${r.title}`}>
                  {/* key:三張共用同一個元件,換一張要整個重來(日期、門市不沿用上一張的) */}
                  <FixedReportPage key={r.key} report={r} />
                </NeedsAbility>
              }
            />
          ))}
          <Route
            path="/reports/commissions"
            element={
              <NeedsAbility ability="report_commission" doing="看佣金明細">
                <CommissionLinesPage />
              </NeedsAbility>
            }
          />
          <Route
            path="/reports/business-daily"
            element={
              <NeedsAbility ability="view_business_daily" doing="看營業日報">
                <BusinessDailyReportPage />
              </NeedsAbility>
            }
          />
          <Route
            path="/reports/parts-usage"
            element={
              <NeedsAbility ability="report_parts" doing="看零件耗用">
                <PartsUsageReportPage />
              </NeedsAbility>
            }
          />
          <Route
            path="/reports/explore"
            element={
              <NeedsAbility ability="report_explore" doing="用自訂分析">
                <ExploreReportPage />
              </NeedsAbility>
            }
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
        </div>
        </main>
        {!isPrintMode && <ToastHost />}
      </div>
    </div>
  );
}
