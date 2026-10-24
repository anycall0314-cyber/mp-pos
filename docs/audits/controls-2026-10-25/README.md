# 全站控制項源碼盤點附錄

- 日期：2026-10-25；基準：`ebf7e0e7bfa9a1a5d1b751ea279ff3c975f2d15d`。
- 149 份 TSX/JSX 全數掃描；140 份含控制項；頁面檔 111 份，共用元件檔 35 份。
- 1649 個靜態控制項位置，其中原生 button 701 處。迴圈渲染只算一處，元件呼叫與內部 button 分開列；不能當成畫面上按鈕總數。
- 另外涵蓋 input / select / textarea、連結、summary、共用選擇元件、非原生點擊容器；輸入框包含文字／日期／檔案，不只開關。
- 全站 CSS 1 檔，以控制項關鍵字列出 565 條候選規則；不是 565 種錯誤或已確認仍在使用的樣式。
- 源碼盤點不等於所有角色、設備與部署站的實機驗收。完整明細見 [controls.csv](./controls.csv)、[css-rules.csv](./css-rules.csv)、[inventory.json](./inventory.json)。
- `hasDisabled=false` 不代表缺陷，可能是單純導覽；`ariaLabel` 空白也可能有可見文字或外部 label。必須看上下文，不以數字直接判定違規。
- 所有前端 JSX 來源都列入，沒有控制項的檔案也保留。後端公開報價模板另見主計劃書，未混入 TSX 數量。
- 151 份來源雜湊見 [sources.sha256](./sources.sha256)。可重跑工具見 [inventory-controls.mjs](./inventory-controls.mjs)；在 repo 根目錄執行，預設輸出到 outputs/controls-audit-rerun，不覆蓋本基線。

## 模組覆蓋

| 範圍 | 檔案 | 原生 button | 輸入控制 | 其他控制位置 |
|---|---:|---:|---:|---:|
| 其他 | 3 | 3 | 0 | 2 |
| components/共用 | 19 | 13 | 7 | 10 |
| components/invoice | 1 | 3 | 2 | 2 |
| components/labels | 2 | 3 | 0 | 2 |
| components/master-detail | 1 | 3 | 1 | 1 |
| components/photos | 4 | 28 | 2 | 4 |
| components/shell | 3 | 1 | 2 | 4 |
| components/workbench | 5 | 7 | 2 | 0 |
| pages/account | 1 | 1 | 3 | 0 |
| pages/backup | 1 | 12 | 4 | 0 |
| pages/cash | 4 | 10 | 15 | 12 |
| pages/customers | 1 | 5 | 8 | 4 |
| pages/home | 1 | 2 | 1 | 8 |
| pages/intake | 1 | 11 | 16 | 9 |
| pages/inventory | 11 | 62 | 46 | 48 |
| pages/labels | 1 | 6 | 0 | 0 |
| pages/ledger | 1 | 1 | 0 | 0 |
| pages/legacy | 1 | 13 | 5 | 5 |
| pages/login | 1 | 1 | 2 | 0 |
| pages/members | 4 | 8 | 14 | 3 |
| pages/phone-bills | 3 | 15 | 7 | 7 |
| pages/photos | 1 | 7 | 2 | 0 |
| pages/platform-admin | 6 | 28 | 51 | 3 |
| pages/products | 19 | 149 | 111 | 62 |
| pages/purchases | 7 | 43 | 27 | 25 |
| pages/repairs | 6 | 27 | 25 | 25 |
| pages/reports | 9 | 34 | 37 | 27 |
| pages/sales-persons | 1 | 4 | 6 | 2 |
| pages/sales | 5 | 46 | 27 | 28 |
| pages/secondhand-acquisition | 2 | 8 | 14 | 5 |
| pages/settings | 4 | 26 | 46 | 11 |
| pages/sim-cards | 2 | 7 | 6 | 4 |
| pages/suppliers | 1 | 4 | 9 | 2 |
| pages/telecom-plans | 3 | 18 | 16 | 13 |
| pages/telecom | 1 | 6 | 5 | 4 |
| pages/trade | 8 | 39 | 41 | 9 |
| pages/transfers | 1 | 12 | 9 | 7 |
| pages/vendor-orders | 4 | 35 | 18 | 13 |

## 逐檔覆蓋

| 源碼位置 | 原生 button | 輸入控制 | 其他控制 |
|---|---:|---:|---:|
| [frontend/src/App.tsx](../../../frontend/src/App.tsx) | 3 | 0 | 2 |
| [frontend/src/auth/AuthContext.tsx](../../../frontend/src/auth/AuthContext.tsx) | 0 | 0 | 0 |
| [frontend/src/components/AppliedFilters.tsx](../../../frontend/src/components/AppliedFilters.tsx) | 1 | 0 | 0 |
| [frontend/src/components/Banner.tsx](../../../frontend/src/components/Banner.tsx) | 0 | 0 | 0 |
| [frontend/src/components/ComboBox.tsx](../../../frontend/src/components/ComboBox.tsx) | 1 | 1 | 1 |
| [frontend/src/components/CompatibilityModal.tsx](../../../frontend/src/components/CompatibilityModal.tsx) | 1 | 0 | 2 |
| [frontend/src/components/DraftBanner.tsx](../../../frontend/src/components/DraftBanner.tsx) | 2 | 0 | 0 |
| [frontend/src/components/Drawer.tsx](../../../frontend/src/components/Drawer.tsx) | 1 | 0 | 2 |
| [frontend/src/components/EyeToggle.tsx](../../../frontend/src/components/EyeToggle.tsx) | 1 | 0 | 0 |
| [frontend/src/components/Field.tsx](../../../frontend/src/components/Field.tsx) | 0 | 1 | 0 |
| [frontend/src/components/MoneyInput.tsx](../../../frontend/src/components/MoneyInput.tsx) | 0 | 1 | 0 |
| [frontend/src/components/NeedsAbility.tsx](../../../frontend/src/components/NeedsAbility.tsx) | 0 | 0 | 0 |
| [frontend/src/components/PaneBack.tsx](../../../frontend/src/components/PaneBack.tsx) | 1 | 0 | 0 |
| [frontend/src/components/PeriodQuick.tsx](../../../frontend/src/components/PeriodQuick.tsx) | 1 | 0 | 0 |
| [frontend/src/components/PhoneModelPicker.tsx](../../../frontend/src/components/PhoneModelPicker.tsx) | 0 | 1 | 2 |
| [frontend/src/components/SamePhonePick.tsx](../../../frontend/src/components/SamePhonePick.tsx) | 2 | 0 | 0 |
| [frontend/src/components/SavedStrip.tsx](../../../frontend/src/components/SavedStrip.tsx) | 0 | 0 | 0 |
| [frontend/src/components/SerialHistoryModal.tsx](../../../frontend/src/components/SerialHistoryModal.tsx) | 2 | 2 | 2 |
| [frontend/src/components/SourcePicker.tsx](../../../frontend/src/components/SourcePicker.tsx) | 0 | 0 | 1 |
| [frontend/src/components/StoreSelect.tsx](../../../frontend/src/components/StoreSelect.tsx) | 0 | 1 | 0 |
| [frontend/src/components/Toolbar.tsx](../../../frontend/src/components/Toolbar.tsx) | 0 | 0 | 0 |
| [frontend/src/components/invoice/InvoiceJumpDialog.tsx](../../../frontend/src/components/invoice/InvoiceJumpDialog.tsx) | 3 | 2 | 2 |
| [frontend/src/components/labels/AccessoryLabelButton.tsx](../../../frontend/src/components/labels/AccessoryLabelButton.tsx) | 3 | 0 | 2 |
| [frontend/src/components/labels/LabelTile.tsx](../../../frontend/src/components/labels/LabelTile.tsx) | 0 | 0 | 0 |
| [frontend/src/components/master-detail/MasterDetail.tsx](../../../frontend/src/components/master-detail/MasterDetail.tsx) | 3 | 1 | 1 |
| [frontend/src/components/photos/PhotoLightbox.tsx](../../../frontend/src/components/photos/PhotoLightbox.tsx) | 3 | 0 | 4 |
| [frontend/src/components/photos/PhotoName.tsx](../../../frontend/src/components/photos/PhotoName.tsx) | 5 | 0 | 0 |
| [frontend/src/components/photos/PhotoSection.tsx](../../../frontend/src/components/photos/PhotoSection.tsx) | 15 | 2 | 0 |
| [frontend/src/components/photos/ProductPhotoPanel.tsx](../../../frontend/src/components/photos/ProductPhotoPanel.tsx) | 5 | 0 | 0 |
| [frontend/src/components/shell/ModuleBar.tsx](../../../frontend/src/components/shell/ModuleBar.tsx) | 1 | 1 | 2 |
| [frontend/src/components/shell/NavSearch.tsx](../../../frontend/src/components/shell/NavSearch.tsx) | 0 | 1 | 1 |
| [frontend/src/components/shell/Sidebar.tsx](../../../frontend/src/components/shell/Sidebar.tsx) | 0 | 0 | 1 |
| [frontend/src/components/workbench/ArmButton.tsx](../../../frontend/src/components/workbench/ArmButton.tsx) | 1 | 0 | 0 |
| [frontend/src/components/workbench/MoreMenu.tsx](../../../frontend/src/components/workbench/MoreMenu.tsx) | 1 | 0 | 0 |
| [frontend/src/components/workbench/QtyInput.tsx](../../../frontend/src/components/workbench/QtyInput.tsx) | 0 | 1 | 0 |
| [frontend/src/components/workbench/ScanBox.tsx](../../../frontend/src/components/workbench/ScanBox.tsx) | 4 | 1 | 0 |
| [frontend/src/components/workbench/toast.tsx](../../../frontend/src/components/workbench/toast.tsx) | 1 | 0 | 0 |
| [frontend/src/main.tsx](../../../frontend/src/main.tsx) | 0 | 0 | 0 |
| [frontend/src/pages/account/PasswordPage.tsx](../../../frontend/src/pages/account/PasswordPage.tsx) | 1 | 3 | 0 |
| [frontend/src/pages/backup/BackupPage.tsx](../../../frontend/src/pages/backup/BackupPage.tsx) | 12 | 4 | 0 |
| [frontend/src/pages/cash/CashAdjustmentForm.tsx](../../../frontend/src/pages/cash/CashAdjustmentForm.tsx) | 2 | 5 | 3 |
| [frontend/src/pages/cash/CashAdjustmentsPage.tsx](../../../frontend/src/pages/cash/CashAdjustmentsPage.tsx) | 3 | 2 | 2 |
| [frontend/src/pages/cash/PettyExpenseForm.tsx](../../../frontend/src/pages/cash/PettyExpenseForm.tsx) | 2 | 6 | 5 |
| [frontend/src/pages/cash/PettyExpensesPage.tsx](../../../frontend/src/pages/cash/PettyExpensesPage.tsx) | 3 | 2 | 2 |
| [frontend/src/pages/customers/CustomersPage.tsx](../../../frontend/src/pages/customers/CustomersPage.tsx) | 5 | 8 | 4 |
| [frontend/src/pages/home/HomePage.tsx](../../../frontend/src/pages/home/HomePage.tsx) | 2 | 1 | 8 |
| [frontend/src/pages/intake/IntakePage.tsx](../../../frontend/src/pages/intake/IntakePage.tsx) | 11 | 16 | 9 |
| [frontend/src/pages/inventory/CategoriesPage.tsx](../../../frontend/src/pages/inventory/CategoriesPage.tsx) | 5 | 6 | 1 |
| [frontend/src/pages/inventory/InventoryAlertsPage.tsx](../../../frontend/src/pages/inventory/InventoryAlertsPage.tsx) | 6 | 0 | 4 |
| [frontend/src/pages/inventory/InventoryQueryPage.tsx](../../../frontend/src/pages/inventory/InventoryQueryPage.tsx) | 13 | 1 | 10 |
| [frontend/src/pages/inventory/PhoneCountPage.tsx](../../../frontend/src/pages/inventory/PhoneCountPage.tsx) | 9 | 2 | 0 |
| [frontend/src/pages/inventory/SerialListPage.tsx](../../../frontend/src/pages/inventory/SerialListPage.tsx) | 3 | 6 | 10 |
| [frontend/src/pages/inventory/StockCountPage.tsx](../../../frontend/src/pages/inventory/StockCountPage.tsx) | 13 | 13 | 11 |
| [frontend/src/pages/inventory/StockCountsPage.tsx](../../../frontend/src/pages/inventory/StockCountsPage.tsx) | 2 | 3 | 2 |
| [frontend/src/pages/inventory/StockFlowPage.tsx](../../../frontend/src/pages/inventory/StockFlowPage.tsx) | 2 | 4 | 3 |
| [frontend/src/pages/inventory/StockMovesPage.tsx](../../../frontend/src/pages/inventory/StockMovesPage.tsx) | 4 | 4 | 3 |
| [frontend/src/pages/inventory/VendorExchangesPage.tsx](../../../frontend/src/pages/inventory/VendorExchangesPage.tsx) | 3 | 6 | 2 |
| [frontend/src/pages/inventory/stockReportParts.tsx](../../../frontend/src/pages/inventory/stockReportParts.tsx) | 2 | 1 | 2 |
| [frontend/src/pages/labels/LabelPrintPage.tsx](../../../frontend/src/pages/labels/LabelPrintPage.tsx) | 6 | 0 | 0 |
| [frontend/src/pages/ledger/LedgerChecksPage.tsx](../../../frontend/src/pages/ledger/LedgerChecksPage.tsx) | 1 | 0 | 0 |
| [frontend/src/pages/legacy/LegacyMappingPage.tsx](../../../frontend/src/pages/legacy/LegacyMappingPage.tsx) | 13 | 5 | 5 |
| [frontend/src/pages/login/LoginPage.tsx](../../../frontend/src/pages/login/LoginPage.tsx) | 1 | 2 | 0 |
| [frontend/src/pages/members/LegacyHistorySection.tsx](../../../frontend/src/pages/members/LegacyHistorySection.tsx) | 2 | 3 | 0 |
| [frontend/src/pages/members/LegacyLinkCandidates.tsx](../../../frontend/src/pages/members/LegacyLinkCandidates.tsx) | 1 | 0 | 0 |
| [frontend/src/pages/members/MemberHistoryPage.tsx](../../../frontend/src/pages/members/MemberHistoryPage.tsx) | 0 | 0 | 0 |
| [frontend/src/pages/members/MembersPage.tsx](../../../frontend/src/pages/members/MembersPage.tsx) | 5 | 11 | 3 |
| [frontend/src/pages/phone-bills/PhoneBillForm.tsx](../../../frontend/src/pages/phone-bills/PhoneBillForm.tsx) | 9 | 5 | 5 |
| [frontend/src/pages/phone-bills/PhoneBillReceiptPage.tsx](../../../frontend/src/pages/phone-bills/PhoneBillReceiptPage.tsx) | 2 | 0 | 0 |
| [frontend/src/pages/phone-bills/PhoneBillsPage.tsx](../../../frontend/src/pages/phone-bills/PhoneBillsPage.tsx) | 4 | 2 | 2 |
| [frontend/src/pages/photos/PhonePhotoPage.tsx](../../../frontend/src/pages/photos/PhonePhotoPage.tsx) | 7 | 2 | 0 |
| [frontend/src/pages/platform-admin/PlatformAdminPage.tsx](../../../frontend/src/pages/platform-admin/PlatformAdminPage.tsx) | 1 | 0 | 0 |
| [frontend/src/pages/platform-admin/PlatformDevicesTab.tsx](../../../frontend/src/pages/platform-admin/PlatformDevicesTab.tsx) | 8 | 4 | 3 |
| [frontend/src/pages/platform-admin/PlatformTenantsTab.tsx](../../../frontend/src/pages/platform-admin/PlatformTenantsTab.tsx) | 3 | 5 | 0 |
| [frontend/src/pages/platform-admin/PlatformUsersTab.tsx](../../../frontend/src/pages/platform-admin/PlatformUsersTab.tsx) | 4 | 11 | 0 |
| [frontend/src/pages/platform-admin/PlatformVendorsTab.tsx](../../../frontend/src/pages/platform-admin/PlatformVendorsTab.tsx) | 9 | 21 | 0 |
| [frontend/src/pages/platform-admin/PlatformWarehousesTab.tsx](../../../frontend/src/pages/platform-admin/PlatformWarehousesTab.tsx) | 3 | 10 | 0 |
| [frontend/src/pages/products/BrandSeriesImportModal.tsx](../../../frontend/src/pages/products/BrandSeriesImportModal.tsx) | 5 | 1 | 1 |
| [frontend/src/pages/products/BrandSeriesPage.tsx](../../../frontend/src/pages/products/BrandSeriesPage.tsx) | 15 | 9 | 1 |
| [frontend/src/pages/products/BulkCreatePartsModal.tsx](../../../frontend/src/pages/products/BulkCreatePartsModal.tsx) | 7 | 7 | 3 |
| [frontend/src/pages/products/BulkDuplicateRows.tsx](../../../frontend/src/pages/products/BulkDuplicateRows.tsx) | 0 | 1 | 0 |
| [frontend/src/pages/products/BulkEditProductsModal.tsx](../../../frontend/src/pages/products/BulkEditProductsModal.tsx) | 5 | 15 | 3 |
| [frontend/src/pages/products/ConditionsPage.tsx](../../../frontend/src/pages/products/ConditionsPage.tsx) | 6 | 5 | 0 |
| [frontend/src/pages/products/DeviceLibraryStep.tsx](../../../frontend/src/pages/products/DeviceLibraryStep.tsx) | 5 | 1 | 0 |
| [frontend/src/pages/products/DuplicatePanel.tsx](../../../frontend/src/pages/products/DuplicatePanel.tsx) | 3 | 1 | 1 |
| [frontend/src/pages/products/FindFirstPanel.tsx](../../../frontend/src/pages/products/FindFirstPanel.tsx) | 5 | 2 | 1 |
| [frontend/src/pages/products/KindPicker.tsx](../../../frontend/src/pages/products/KindPicker.tsx) | 1 | 0 | 0 |
| [frontend/src/pages/products/NewPhoneModelWizardPage.tsx](../../../frontend/src/pages/products/NewPhoneModelWizardPage.tsx) | 13 | 11 | 1 |
| [frontend/src/pages/products/PartTemplatesPage.tsx](../../../frontend/src/pages/products/PartTemplatesPage.tsx) | 9 | 8 | 3 |
| [frontend/src/pages/products/ProductAliasesPanel.tsx](../../../frontend/src/pages/products/ProductAliasesPanel.tsx) | 2 | 2 | 1 |
| [frontend/src/pages/products/ProductExpanderModal.tsx](../../../frontend/src/pages/products/ProductExpanderModal.tsx) | 6 | 11 | 8 |
| [frontend/src/pages/products/ProductForm.tsx](../../../frontend/src/pages/products/ProductForm.tsx) | 24 | 19 | 19 |
| [frontend/src/pages/products/ProductFormPage.tsx](../../../frontend/src/pages/products/ProductFormPage.tsx) | 3 | 0 | 0 |
| [frontend/src/pages/products/ProductImportModal.tsx](../../../frontend/src/pages/products/ProductImportModal.tsx) | 7 | 2 | 3 |
| [frontend/src/pages/products/ProductTypesPage.tsx](../../../frontend/src/pages/products/ProductTypesPage.tsx) | 8 | 4 | 2 |
| [frontend/src/pages/products/ProductsPage.tsx](../../../frontend/src/pages/products/ProductsPage.tsx) | 25 | 12 | 15 |
| [frontend/src/pages/purchases/PurchaseBatchPasteModal.tsx](../../../frontend/src/pages/purchases/PurchaseBatchPasteModal.tsx) | 9 | 4 | 4 |
| [frontend/src/pages/purchases/PurchaseLinesPage.tsx](../../../frontend/src/pages/purchases/PurchaseLinesPage.tsx) | 3 | 3 | 4 |
| [frontend/src/pages/purchases/PurchaseListPage.tsx](../../../frontend/src/pages/purchases/PurchaseListPage.tsx) | 5 | 1 | 4 |
| [frontend/src/pages/purchases/PurchaseProductPickerModal.tsx](../../../frontend/src/pages/purchases/PurchaseProductPickerModal.tsx) | 5 | 3 | 2 |
| [frontend/src/pages/purchases/PurchaseWorkbenchPage.tsx](../../../frontend/src/pages/purchases/PurchaseWorkbenchPage.tsx) | 15 | 10 | 8 |
| [frontend/src/pages/purchases/SecondhandSheetImport.tsx](../../../frontend/src/pages/purchases/SecondhandSheetImport.tsx) | 4 | 2 | 1 |
| [frontend/src/pages/purchases/SerialSlots.tsx](../../../frontend/src/pages/purchases/SerialSlots.tsx) | 2 | 4 | 2 |
| [frontend/src/pages/repairs/RepairEntryPage.tsx](../../../frontend/src/pages/repairs/RepairEntryPage.tsx) | 13 | 18 | 14 |
| [frontend/src/pages/repairs/RepairHistoryModal.tsx](../../../frontend/src/pages/repairs/RepairHistoryModal.tsx) | 3 | 0 | 2 |
| [frontend/src/pages/repairs/RepairItemsPage.tsx](../../../frontend/src/pages/repairs/RepairItemsPage.tsx) | 7 | 2 | 4 |
| [frontend/src/pages/repairs/RepairReceiptPrintPage.tsx](../../../frontend/src/pages/repairs/RepairReceiptPrintPage.tsx) | 0 | 0 | 0 |
| [frontend/src/pages/repairs/RepairsPage.tsx](../../../frontend/src/pages/repairs/RepairsPage.tsx) | 1 | 5 | 5 |
| [frontend/src/pages/repairs/UnlockPatternInput.tsx](../../../frontend/src/pages/repairs/UnlockPatternInput.tsx) | 3 | 0 | 0 |
| [frontend/src/pages/reports/BusinessDailyReport.tsx](../../../frontend/src/pages/reports/BusinessDailyReport.tsx) | 5 | 2 | 9 |
| [frontend/src/pages/reports/CommissionLinesPage.tsx](../../../frontend/src/pages/reports/CommissionLinesPage.tsx) | 1 | 0 | 1 |
| [frontend/src/pages/reports/ExploreReportPage.tsx](../../../frontend/src/pages/reports/ExploreReportPage.tsx) | 15 | 14 | 4 |
| [frontend/src/pages/reports/FixedReportPage.tsx](../../../frontend/src/pages/reports/FixedReportPage.tsx) | 1 | 0 | 0 |
| [frontend/src/pages/reports/InvoiceListPage.tsx](../../../frontend/src/pages/reports/InvoiceListPage.tsx) | 4 | 6 | 3 |
| [frontend/src/pages/reports/PartsUsageReportPage.tsx](../../../frontend/src/pages/reports/PartsUsageReportPage.tsx) | 2 | 2 | 1 |
| [frontend/src/pages/reports/RepairMonthlyPage.tsx](../../../frontend/src/pages/reports/RepairMonthlyPage.tsx) | 2 | 3 | 2 |
| [frontend/src/pages/reports/ReportRangeBar.tsx](../../../frontend/src/pages/reports/ReportRangeBar.tsx) | 1 | 5 | 2 |
| [frontend/src/pages/reports/SalesDailyReport.tsx](../../../frontend/src/pages/reports/SalesDailyReport.tsx) | 3 | 5 | 5 |
| [frontend/src/pages/sales-persons/SalesPersonsPage.tsx](../../../frontend/src/pages/sales-persons/SalesPersonsPage.tsx) | 4 | 6 | 2 |
| [frontend/src/pages/sales/SalesListPage.tsx](../../../frontend/src/pages/sales/SalesListPage.tsx) | 9 | 3 | 5 |
| [frontend/src/pages/sales/SalesPage.tsx](../../../frontend/src/pages/sales/SalesPage.tsx) | 3 | 2 | 2 |
| [frontend/src/pages/sales/SalesPrintPage.tsx](../../../frontend/src/pages/sales/SalesPrintPage.tsx) | 2 | 0 | 0 |
| [frontend/src/pages/sales/SalesReturnEntryPage.tsx](../../../frontend/src/pages/sales/SalesReturnEntryPage.tsx) | 1 | 3 | 3 |
| [frontend/src/pages/sales/SalesWorkbenchPage.tsx](../../../frontend/src/pages/sales/SalesWorkbenchPage.tsx) | 31 | 19 | 18 |
| [frontend/src/pages/secondhand-acquisition/SecondhandAcquisitionPage.tsx](../../../frontend/src/pages/secondhand-acquisition/SecondhandAcquisitionPage.tsx) | 2 | 0 | 1 |
| [frontend/src/pages/secondhand-acquisition/SecondhandPersonalEntry.tsx](../../../frontend/src/pages/secondhand-acquisition/SecondhandPersonalEntry.tsx) | 6 | 14 | 4 |
| [frontend/src/pages/settings/InvoicePrinterPage.tsx](../../../frontend/src/pages/settings/InvoicePrinterPage.tsx) | 5 | 1 | 0 |
| [frontend/src/pages/settings/SettingsPage.tsx](../../../frontend/src/pages/settings/SettingsPage.tsx) | 15 | 28 | 7 |
| [frontend/src/pages/settings/StaffAccountsPage.tsx](../../../frontend/src/pages/settings/StaffAccountsPage.tsx) | 4 | 2 | 1 |
| [frontend/src/pages/settings/VendorLinksPage.tsx](../../../frontend/src/pages/settings/VendorLinksPage.tsx) | 2 | 15 | 3 |
| [frontend/src/pages/sim-cards/SimCardForm.tsx](../../../frontend/src/pages/sim-cards/SimCardForm.tsx) | 4 | 5 | 3 |
| [frontend/src/pages/sim-cards/SimCardsPage.tsx](../../../frontend/src/pages/sim-cards/SimCardsPage.tsx) | 3 | 1 | 1 |
| [frontend/src/pages/suppliers/SuppliersPage.tsx](../../../frontend/src/pages/suppliers/SuppliersPage.tsx) | 4 | 9 | 2 |
| [frontend/src/pages/telecom-plans/BulkAddTelecomPlansModal.tsx](../../../frontend/src/pages/telecom-plans/BulkAddTelecomPlansModal.tsx) | 8 | 7 | 6 |
| [frontend/src/pages/telecom-plans/TelecomPlanForm.tsx](../../../frontend/src/pages/telecom-plans/TelecomPlanForm.tsx) | 4 | 6 | 5 |
| [frontend/src/pages/telecom-plans/TelecomPlansPage.tsx](../../../frontend/src/pages/telecom-plans/TelecomPlansPage.tsx) | 6 | 3 | 2 |
| [frontend/src/pages/telecom/ContractsPage.tsx](../../../frontend/src/pages/telecom/ContractsPage.tsx) | 6 | 5 | 4 |
| [frontend/src/pages/trade/TradeBookTab.tsx](../../../frontend/src/pages/trade/TradeBookTab.tsx) | 13 | 9 | 3 |
| [frontend/src/pages/trade/TradeGoodsTab.tsx](../../../frontend/src/pages/trade/TradeGoodsTab.tsx) | 6 | 7 | 0 |
| [frontend/src/pages/trade/TradeOrdersTab.tsx](../../../frontend/src/pages/trade/TradeOrdersTab.tsx) | 4 | 7 | 6 |
| [frontend/src/pages/trade/TradePage.tsx](../../../frontend/src/pages/trade/TradePage.tsx) | 2 | 0 | 0 |
| [frontend/src/pages/trade/TradeSettingPanel.tsx](../../../frontend/src/pages/trade/TradeSettingPanel.tsx) | 1 | 7 | 0 |
| [frontend/src/pages/trade/TradeUnitChanges.tsx](../../../frontend/src/pages/trade/TradeUnitChanges.tsx) | 0 | 1 | 0 |
| [frontend/src/pages/trade/TradeUnitList.tsx](../../../frontend/src/pages/trade/TradeUnitList.tsx) | 10 | 7 | 0 |
| [frontend/src/pages/trade/TradeUnitsTab.tsx](../../../frontend/src/pages/trade/TradeUnitsTab.tsx) | 3 | 3 | 0 |
| [frontend/src/pages/transfers/TransferWorkbenchPage.tsx](../../../frontend/src/pages/transfers/TransferWorkbenchPage.tsx) | 12 | 9 | 7 |
| [frontend/src/pages/vendor-orders/ManualReceiveDrawer.tsx](../../../frontend/src/pages/vendor-orders/ManualReceiveDrawer.tsx) | 6 | 3 | 2 |
| [frontend/src/pages/vendor-orders/MappingTab.tsx](../../../frontend/src/pages/vendor-orders/MappingTab.tsx) | 2 | 2 | 1 |
| [frontend/src/pages/vendor-orders/ReceiveDrawer.tsx](../../../frontend/src/pages/vendor-orders/ReceiveDrawer.tsx) | 6 | 2 | 2 |
| [frontend/src/pages/vendor-orders/VendorOrdersPage.tsx](../../../frontend/src/pages/vendor-orders/VendorOrdersPage.tsx) | 21 | 11 | 8 |
