import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiHttpError, api } from "./client";
import {
  type ContractQuery,
  type FollowStatus,
  listContracts,
  setContractFollowUp,
} from "./contracts";
import { listProductPhotos, type PhotosPayload } from "./photos";
import { rangeQuery, rangeReady, type ReportRange } from "@/lib/fixedReports";
import type { CatalogRow } from "@/lib/vendorOrder";
import type { VendorCategoryOption } from "@/lib/vendorPick";
import type { ManualPlan, ManualSend, PastedItem } from "@/lib/vendorManual";
import { withSaved, type MappingData, type MappingRow } from "@/lib/vendorMapping";
import type { ReceivePlan, ReceiveSend } from "@/lib/vendorReceive";
import {
  Carrier,
  Category,
  ClearancePressureResponse,
  CompatibilityResponse,
  Customer,
  DuplicateCandidate,
  HomeSummary,
  InventoryAlertsResponse,
  InvoiceTrack,
  InvoiceType,
  PartsUsageReport,
  Brand,
  Condition,
  PhoneSeries,
  ProductType,
  PartBulkCreateResult,
  PartPreviewRow,
  PartTemplate,
  RepairHistoryItem,
  RepairItem,
  RepairOrder,
  RepairQuotePreview,
  LegacyPurchase,
  Member,
  Paginated,
  CashAdjustment,
  PaymentMethod,
  PettyExpense,
  PhoneBillCollection,
  PlatformTenant,
  PlatformUser,
  PlatformWarehouse,
  Product,
  ProductAlias,
  ProductUsage,
  ProductSerial,
  IntakeBatch,
  IntakeItem,
  PurchaseOrder,
  ReturnableSummary,
  SalesOrder,
  SalesPerson,
  SalesReturn,
  SimCard,
  StockBalance,
  Supplier,
  TelecomPlan,
  TransferOrder,
  Warehouse,
  LegacyCandidate,
  LegacyException,
  LegacyHistoryDocDetail,
  LegacyHistoryPage,
  LegacyMapKind,
  LegacyMapsPage,
  LegacyMemberRow,
  LegacyMembersPage,
  AnalyticsCatalog,
  AnalyticsOption,
  AnalyticsResult,
  AnalyticsSpec,
  CommissionLines,
  FixedReportResult,
  LedgerOverview,
  PlatformVendor,
  PlatformVendorCategory,
  PlatformVendorItem,
  VendorItemImport,
  VendorLinkRow,
  VendorOrder,
  VendorOutsideOrder,
  SavedReport,
  StaffAccount,
  StaffAccountsResponse,
} from "./types";

// 通用：把分頁 results 攤平回傳（MVP 一頁 50 筆夠用）
function list<T>(path: string) {
  return api<Paginated<T>>(path).then((d) => d.results);
}

// ---- queries ----

export const useProducts = (
  params?: string,
  opts?: { enabled?: boolean },
) =>
  useQuery({
    queryKey: ["products", params ?? ""],
    queryFn: () => list<Product>(`/products/${params ? "?" + params : ""}`),
    enabled: opts?.enabled ?? true,
  });

export const useProduct = (id: number | null) =>
  useQuery({
    queryKey: ["product", id],
    queryFn: () => api<Product>(`/products/${id}/`),
    enabled: id != null,
  });

/**
 * 這個商品用過沒有(編輯表單打開時問)。不留舊的:每次打開重新問 ——
 * 剛作廢完那張單回來改,不能還拿到「用過」。
 */
export const useProductUsage = (id: number | null) =>
  useQuery({
    queryKey: ["product", id, "usage"],
    queryFn: () => api<ProductUsage>(`/products/${id}/usage/`),
    enabled: id != null,
    staleTime: 0,
    gcTime: 0,
  });

export const useCategories = () =>
  useQuery({ queryKey: ["categories"], queryFn: () => list<Category>("/categories/") });

export const useWarehouses = () =>
  useQuery({ queryKey: ["warehouses"], queryFn: () => list<Warehouse>("/warehouses/") });

export const useSuppliers = () =>
  useQuery({ queryKey: ["suppliers"], queryFn: () => list<Supplier>("/suppliers/") });

export const useCustomers = () =>
  useQuery({ queryKey: ["customers"], queryFn: () => list<Customer>("/customers/") });

export const useMembers = () =>
  useQuery({ queryKey: ["members"], queryFn: () => list<Member>("/members/") });

export const useLegacyPurchases = (memberId: number | null) =>
  useQuery({
    queryKey: ["legacy-purchases", memberId],
    queryFn: () =>
      list<LegacyPurchase>(
        `/legacy-purchases/?member=${memberId}&page_size=200`,
      ),
    enabled: memberId != null,
  });

export const useSalesPersons = () =>
  useQuery({
    queryKey: ["sales-persons"],
    queryFn: () => list<SalesPerson>("/sales-persons/"),
  });

export const useInvoiceTypes = (opts?: { activeOnly?: boolean }) =>
  useQuery({
    queryKey: ["invoice-types", opts?.activeOnly ?? false],
    queryFn: () =>
      list<InvoiceType>(
        opts?.activeOnly
          ? "/invoice-types/?is_active=true&page_size=50"
          : "/invoice-types/?page_size=50",
      ),
  });

export const useInvoiceTracks = () =>
  useQuery({
    queryKey: ["invoice-tracks"],
    queryFn: () => list<InvoiceTrack>("/invoice-tracks/?page_size=100"),
  });

export function useSaveInvoiceTrack() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: Partial<InvoiceTrack> & { id?: number }) => {
      const { id, ...body } = payload;
      const method = id ? "PATCH" : "POST";
      const url = id ? `/invoice-tracks/${id}/` : "/invoice-tracks/";
      return api<InvoiceTrack>(url, { method, body: JSON.stringify(body) });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["invoice-tracks"] }),
  });
}

export function useDeleteInvoiceTrack() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      api<void>(`/invoice-tracks/${id}/`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["invoice-tracks"] }),
  });
}

export async function peekInvoiceNo(
  invoiceTypeCode: string,
): Promise<string | null> {
  if (!invoiceTypeCode || invoiceTypeCode === "none") return null;
  try {
    const res = await api<{ next_invoice_no: string | null }>(
      `/invoice-tracks/peek/?invoice_type_code=${encodeURIComponent(invoiceTypeCode)}`,
    );
    return res.next_invoice_no;
  } catch {
    return null;
  }
}

export function useSaveInvoiceType() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: Partial<InvoiceType> & { id: number }) => {
      const { id, ...body } = payload;
      return api<InvoiceType>(`/invoice-types/${id}/`, {
        method: "PATCH",
        body: JSON.stringify(body),
      });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["invoice-types"] }),
  });
}

export const usePaymentMethods = (opts?: { activeOnly?: boolean }) =>
  useQuery({
    queryKey: ["payment-methods", opts?.activeOnly ?? false],
    queryFn: () =>
      list<PaymentMethod>(
        opts?.activeOnly
          ? "/payment-methods/?is_active=true&page_size=50"
          : "/payment-methods/?page_size=50",
      ),
  });

export function useSavePaymentMethod() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: Partial<PaymentMethod> & { id?: number }) => {
      const { id, ...body } = payload;
      const method = id ? "PATCH" : "POST";
      const url = id ? `/payment-methods/${id}/` : "/payment-methods/";
      return api<PaymentMethod>(url, { method, body: JSON.stringify(body) });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["payment-methods"] }),
  });
}

export function useDeletePaymentMethod() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      api<void>(`/payment-methods/${id}/`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["payment-methods"] }),
  });
}

/** 門號合約到期的名單(分頁 / 篩選都在參數裡) */
export const useContracts = (q: ContractQuery) =>
  useQuery({
    queryKey: ["telecom-contracts", q],
    queryFn: () => listContracts(q),
    // 換分頁 / 打搜尋時先留著上一份,畫面不會整個閃掉。那一份不是現在要的名單(`isPlaceholderData`):
    // 畫面只能拿來顯示、不能讓人按 —— 按下去標到的是上一份名單裡的人
    placeholderData: (prev) => prev,
    // 不留舊名單:換回看過的條件 / 那一頁一定重新抓。留著的話會先拿出剛剛的那一份,上面的人別的店員可能已經標過了
    gcTime: 0,
    // 名單不自己在背後換:人正要按的時候列一跳,就按到別人。只有人自己換條件、翻頁、再點分頁,或自己標完才重抓
    refetchOnReconnect: false,
  });

/** 標「已聯絡 / 不續約」、寫備註、取消標記 */
export function useContractFollowUp() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { id: number; status: FollowStatus | ""; note: string }) =>
      setContractFollowUp(v.id, v.status, v.note),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["telecom-contracts"] });
      qc.invalidateQueries({ queryKey: ["home-summary"] });
    },
  });
}

export const useCarriers = () =>
  useQuery({
    queryKey: ["carriers"],
    queryFn: () => list<Carrier>("/carriers/"),
  });

export const useTelecomPlans = (opts?: { includeInactive?: boolean }) =>
  useQuery({
    queryKey: ["telecom-plans", opts?.includeInactive ?? false],
    queryFn: () =>
      list<TelecomPlan>(
        opts?.includeInactive
          ? "/telecom-plans/"
          : "/telecom-plans/?is_active=true",
      ),
  });

export function useSaveCarrier() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: Partial<Carrier> & { id?: number }) => {
      const { id, ...body } = payload;
      const method = id ? "PATCH" : "POST";
      const url = id ? `/carriers/${id}/` : "/carriers/";
      return api<Carrier>(url, { method, body: JSON.stringify(body) });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["carriers"] }),
  });
}

export const useSimCards = (opts?: { includeInactive?: boolean }) =>
  useQuery({
    queryKey: ["sim-cards", opts?.includeInactive ?? false],
    queryFn: () =>
      list<SimCard>(
        opts?.includeInactive ? "/sim-cards/" : "/sim-cards/?status=in_stock",
      ),
  });

export const useAllSimCards = () =>
  useQuery({
    queryKey: ["sim-cards", "all"],
    queryFn: () => list<SimCard>("/sim-cards/"),
  });

export const usePettyExpenses = () =>
  useQuery({
    queryKey: ["petty-expenses"],
    queryFn: () => list<PettyExpense>("/petty-expenses/?page_size=200"),
  });

export function useSavePettyExpense() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: Partial<PettyExpense> & { id?: number }) => {
      const { id, ...body } = payload;
      const method = id ? "PATCH" : "POST";
      const url = id ? `/petty-expenses/${id}/` : "/petty-expenses/";
      return api<PettyExpense>(url, {
        method,
        body: JSON.stringify(body),
      });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["petty-expenses"] }),
  });
}

export interface BusinessDailyRow {
  id: number;
  no: string;
  [k: string]: unknown;
}
export interface BusinessDailySection {
  rows: BusinessDailyRow[];
  total: number;
}
export interface BusinessDailyAdjustments {
  rows: BusinessDailyRow[];
  in_total: number;
  out_total: number;
}
export interface BusinessDailyReport {
  warehouse: number;
  date: string;
  opening_cash: number;
  sales: BusinessDailySection;
  /** 個人收購付出去的現金(現金付款是負的銷貨單);total 是正數 */
  buybacks?: BusinessDailySection;
  non_cash_sales: BusinessDailySection;
  sales_returns: BusinessDailySection;
  purchases: BusinessDailySection;
  expenses: BusinessDailySection;
  phone_bills: BusinessDailySection;
  adjustments: BusinessDailyAdjustments;
  net_change: number;
}

export const useBusinessDailyReport = (
  warehouse: number | null,
  date: string,
) =>
  useQuery({
    queryKey: ["business-daily", warehouse ?? "", date],
    queryFn: () =>
      api<BusinessDailyReport>(
        `/reports/business-daily/?warehouse=${warehouse}&date=${date}`,
      ),
    enabled: !!warehouse && !!date,
  });

// 首頁總覽:今日 / 昨日營業額、低庫存、今日最新銷貨
export const useHomeSummary = () =>
  useQuery({
    queryKey: ["home-summary"],
    queryFn: () => api<HomeSummary>("/home-summary/"),
    // 每 30 秒重抓一次,讓首頁數字接近即時
    refetchInterval: 30000,
    refetchOnWindowFocus: true,
  });

// 銷售趨勢(回溫 / 退燒):資料由 manage.py compute_dynamic_stock 排程算
export interface TrendingItem {
  id: number;
  sku: string;
  name: string;
  stock: number;
  velocity_ewma: string;
  velocity_recent_14d: string;
  velocity_baseline_90d: string;
  trend_ratio: string;
  dynamic_safety_stock: number;
  kind: "up" | "down";
}
export interface TrendingResponse {
  trending_up: TrendingItem[];
  trending_down: TrendingItem[];
}
export const useTrending = (limit = 6) =>
  useQuery({
    queryKey: ["trending", limit],
    queryFn: () =>
      api<TrendingResponse>(`/products/trending/?limit=${limit}`),
    refetchInterval: 5 * 60 * 1000, // 5 分鐘重抓(資料每晚才會變,refetch 主要是換頁觸發)
    refetchOnWindowFocus: false,
  });

// 庫存警示:依商品狀態 + 關聯主機 推論觸發原因
export const useInventoryAlerts = () =>
  useQuery({
    queryKey: ["inventory-alerts"],
    queryFn: () => api<InventoryAlertsResponse>("/inventory-alerts/"),
    refetchInterval: 60000,
  });

// 清倉壓力追蹤:出清商品依預估清倉天數排序,> 60 天建議降價
export const useClearancePressure = () =>
  useQuery({
    queryKey: ["clearance-pressure"],
    queryFn: () => api<ClearancePressureResponse>("/clearance-pressure/"),
    refetchInterval: 60000,
  });

// 商品相容性:主機 → 列配件;機型配件 → 列主機 + 需求熱度
export const useProductCompatibility = (productId: number | null) =>
  useQuery({
    queryKey: ["product-compatibility", productId],
    queryFn: () =>
      api<CompatibilityResponse>(`/products/${productId}/compatibility/`),
    enabled: !!productId,
  });

export function useVoidPettyExpense() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      api<PettyExpense>(`/petty-expenses/${id}/void/`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["petty-expenses"] }),
  });
}

export const useCashAdjustments = () =>
  useQuery({
    queryKey: ["cash-adjustments"],
    queryFn: () =>
      list<CashAdjustment>("/cash-adjustments/?page_size=200"),
  });

export function useSaveCashAdjustment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: Partial<CashAdjustment> & { id?: number }) => {
      const { id, ...body } = payload;
      const method = id ? "PATCH" : "POST";
      const url = id ? `/cash-adjustments/${id}/` : "/cash-adjustments/";
      return api<CashAdjustment>(url, {
        method,
        body: JSON.stringify(body),
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["cash-adjustments"] });
      qc.invalidateQueries({ queryKey: ["business-daily"] });
    },
  });
}

export function useVoidCashAdjustment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      api<CashAdjustment>(`/cash-adjustments/${id}/void/`, {
        method: "POST",
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["cash-adjustments"] });
      qc.invalidateQueries({ queryKey: ["business-daily"] });
    },
  });
}

export const usePhoneBills = () =>
  useQuery({
    queryKey: ["phone-bills"],
    queryFn: () =>
      list<PhoneBillCollection>("/phone-bills/?page_size=200"),
  });

export const usePhoneBill = (id: number | null) =>
  useQuery({
    queryKey: ["phone-bills", id ?? ""],
    queryFn: () => api<PhoneBillCollection>(`/phone-bills/${id}/`),
    enabled: !!id,
  });

export function useSavePhoneBill() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (
      payload: Partial<PhoneBillCollection> & { id?: number },
    ) => {
      const { id, ...body } = payload;
      const method = id ? "PATCH" : "POST";
      const url = id ? `/phone-bills/${id}/` : "/phone-bills/";
      return api<PhoneBillCollection>(url, {
        method,
        body: JSON.stringify(body),
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["phone-bills"] });
      qc.invalidateQueries({ queryKey: ["business-daily"] });
    },
  });
}

export function useVoidPhoneBill() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      api<PhoneBillCollection>(`/phone-bills/${id}/void/`, {
        method: "POST",
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["phone-bills"] });
      qc.invalidateQueries({ queryKey: ["business-daily"] });
    },
  });
}

export function useSaveSimCard() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: Partial<SimCard> & { id?: number }) => {
      const { id, ...body } = payload;
      const method = id ? "PATCH" : "POST";
      const url = id ? `/sim-cards/${id}/` : "/sim-cards/";
      return api<SimCard>(url, { method, body: JSON.stringify(body) });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sim-cards"] }),
  });
}

export interface BulkTelecomPlanRow {
  name: string;
  monthly_fee?: string;
  contract_months?: string;
  commission?: string;
  kind?: string;
  carrier_name?: string;
  note?: string;
}
export interface BulkTelecomPlanCommon {
  carrier?: number;
  kind?: string;
  is_active?: boolean;
}

export function useBulkCreateTelecomPlans() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: {
      common: BulkTelecomPlanCommon;
      items: BulkTelecomPlanRow[];
    }) =>
      api<{ created: TelecomPlan[]; count: number }>("/telecom-plans/bulk/", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["telecom-plans"] }),
  });
}

export function useSaveTelecomPlan() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: Partial<TelecomPlan> & { id?: number }) => {
      const { id, ...body } = payload;
      const method = id ? "PATCH" : "POST";
      const url = id ? `/telecom-plans/${id}/` : "/telecom-plans/";
      return api<TelecomPlan>(url, { method, body: JSON.stringify(body) });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["telecom-plans"] }),
  });
}

export const useInStockSerials = (productId?: number, warehouseId?: number) => {
  const qs = new URLSearchParams({ status: "in_stock" });
  if (productId) qs.set("product", String(productId));
  if (warehouseId) qs.set("warehouse", String(warehouseId));
  return useQuery({
    queryKey: ["serials", "in_stock", productId ?? null, warehouseId ?? null],
    queryFn: () => list<ProductSerial>(`/serials/?${qs.toString()}`),
  });
};

/** 這個碼是哪一台(完全相同;整家公司、不管門市與狀態)。庫存查詢用它講「刷到的那一台現在在哪」。 */
export const useDevicesByCode = (code: string) => {
  const q = code.trim();
  return useQuery({
    queryKey: ["serials", "by-code", q],
    queryFn: () =>
      list<ProductSerial>(
        `/serials/?${new URLSearchParams({ code: q, page_size: "10" }).toString()}`,
      ),
    enabled: q.replace(/[\s\-_.]+/g, "").length > 0,
  });
};

export interface PendingTransfer {
  transfer_no: string;
  doc_date: string;
  qty: number;
  direction: "out" | "in" | null;
  from_warehouse: { code: string; name: string };
  to_warehouse: { code: string; name: string };
}

// 配件用:某商品「已派發未確認」的調撥(可限定與某倉相關)
export const usePendingTransfers = (
  productId?: number,
  warehouseId?: number,
) => {
  return useQuery({
    queryKey: ["pending-transfers", productId ?? null, warehouseId ?? null],
    enabled: !!productId,
    queryFn: () => {
      const qs = new URLSearchParams();
      if (warehouseId) qs.set("warehouse", String(warehouseId));
      return api<PendingTransfer[]>(
        `/products/${productId}/pending-transfers/?${qs.toString()}`,
      );
    },
  });
};

export interface DateRangeFilter {
  from?: string;
  to?: string;
}

export interface SalesOrdersFilter extends DateRangeFilter {
  customer?: number;
  member?: number;
}

function buildQS(params: Record<string, string | number | undefined>): string {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== "" && v !== null) u.set(k, String(v));
  }
  const s = u.toString();
  return s ? "?" + s : "";
}

export const usePurchaseOrders = (range?: DateRangeFilter) =>
  useQuery({
    queryKey: ["purchase-orders", range?.from ?? "", range?.to ?? ""],
    queryFn: () =>
      list<PurchaseOrder>(
        `/purchase-orders/${buildQS({
          doc_date__gte: range?.from,
          doc_date__lte: range?.to,
        })}`,
      ),
  });

export const usePurchaseOrder = (id: number | null) =>
  useQuery({
    queryKey: ["purchase-order", id],
    queryFn: () => api<PurchaseOrder>(`/purchase-orders/${id}/`),
    enabled: id != null,
  });

export const useSalesOrders = (filter?: SalesOrdersFilter) =>
  useQuery({
    queryKey: [
      "sales-orders",
      filter?.from ?? "",
      filter?.to ?? "",
      filter?.customer ?? "",
      filter?.member ?? "",
    ],
    queryFn: () =>
      list<SalesOrder>(
        `/sales-orders/${buildQS({
          doc_date__gte: filter?.from,
          doc_date__lte: filter?.to,
          customer: filter?.customer,
          member: filter?.member,
          page_size: 100,
        })}`,
      ),
  });

export const useSalesOrder = (id: number | null) =>
  useQuery({
    queryKey: ["sales-order", id],
    queryFn: () => api<SalesOrder>(`/sales-orders/${id}/`),
    enabled: id != null,
  });

// 庫存矩陣:多倉攤開檢視
export interface StockMatrixWarehouse {
  id: number;
  code: string;
  name: string;
}
export interface StockMatrixProduct {
  id: number;
  sku: string;
  name: string;
  spec: string;
  capacity: string;
  color: string;
  region_version: string;
  condition_id: number | null;
  condition_name: string;
  tracks_unit_condition: boolean;
  phone_model_key: string;
  phone_model_name: string;
  category_id: number;
  category_name: string;
  category_code: string;
  list_price: string;
  weighted_avg_cost: string;
  requires_serial: boolean;
  is_secondhand: boolean;
  stock_by_warehouse: Record<string, number>;
  stock_total: number;
  /** 主圖的縮圖網址(沒有照片是空字串) */
  photo_thumb?: string;
}
export interface StockMatrixResponse {
  warehouses: StockMatrixWarehouse[];
  products: StockMatrixProduct[];
  total: number;
  page: number;
  page_size: number;
  has_more: boolean;
}
export interface StockMatrixFilter {
  warehouseIds: number[];
  search?: string;
  categoryIds?: number[];
  inStockOnly?: boolean;
  page?: number;
  pageSize?: number;
}
export const useStockMatrix = (
  filter: StockMatrixFilter,
  opts?: { enabled?: boolean },
) =>
  useQuery({
    queryKey: [
      "stock-matrix",
      filter.warehouseIds.join(","),
      filter.search ?? "",
      (filter.categoryIds ?? []).join(","),
      filter.inStockOnly ?? true,
      filter.page ?? 1,
      filter.pageSize ?? 500,
    ],
    queryFn: () => {
      const params = new URLSearchParams();
      if (filter.warehouseIds.length > 0) {
        params.set("warehouse_ids", filter.warehouseIds.join(","));
      }
      if (filter.search) params.set("search", filter.search);
      if (filter.categoryIds && filter.categoryIds.length > 0) {
        params.set("category_ids", filter.categoryIds.join(","));
      }
      params.set(
        "in_stock_only",
        filter.inStockOnly === false ? "false" : "true",
      );
      params.set("page", String(filter.page ?? 1));
      params.set("page_size", String(filter.pageSize ?? 500));
      return api<StockMatrixResponse>(`/products/stock-matrix/?${params}`);
    },
    enabled: opts?.enabled ?? true,
  });

// 銷貨日報專用:撈期間內全部銷貨單(含作廢),前端再分組與作廢分區
export interface SalesDailyReportFilter extends DateRangeFilter {
  warehouse?: number;
  sales_person?: number;
  customer?: number;
}

export const useSalesDailyReport = (
  filter: SalesDailyReportFilter,
  opts?: { enabled?: boolean },
) =>
  useQuery({
    queryKey: [
      "sales-daily-report",
      filter.from ?? "",
      filter.to ?? "",
      filter.warehouse ?? "",
      filter.sales_person ?? "",
      filter.customer ?? "",
    ],
    queryFn: () =>
      list<SalesOrder>(
        `/sales-orders/${buildQS({
          doc_date__gte: filter.from,
          doc_date__lte: filter.to,
          warehouse: filter.warehouse,
          sales_person: filter.sales_person,
          customer: filter.customer,
          page_size: 500,
          ordering: "doc_date,no",
        })}`,
      ),
    enabled: opts?.enabled ?? true,
  });

// ---- mutations ----

export interface BulkProductRow {
  name: string;
  spec?: string;
  barcode?: string;
  list_price?: string;
  /** 每行可選的類別名稱,後端依名稱比對 Category;空白 → 使用 common.category */
  category_name?: string;
  /** 這一列被判定可能重複時,寫下哪裡不同才能建 */
  distinct_reason?: string;
}
export interface BulkProductCommon {
  category?: number;
  requires_serial?: boolean;
  allows_telecom_line?: boolean;
  allows_commission?: boolean;
  is_virtual?: boolean;
  counts_cash?: boolean;
  counts_margin?: boolean;
  is_active?: boolean;
  accessory_type?: "none" | "phone_specific" | "universal";
  warehouse_type?: "product" | "parts";
  // Phase 1: brand / series 改用 FK id;model_suffix 補上
  brand?: number | null;
  series?: number | null;
  generation?: number | null;
  model_suffix?: string;
  lifecycle_status?: "pending" | "active" | "replacing" | "discontinued" | "clearance";
  safety_stock?: number;
  related_host_keys?: string[];
}

export interface BulkEditResult {
  updated: number;
  ids: number[];
}

export function useBulkEditProducts() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: {
      ids: number[];
      patch: Record<string, unknown>;
    }) =>
      api<BulkEditResult>("/products/bulk-edit/", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["products"] });
      qc.invalidateQueries({ queryKey: ["product"] });
    },
  });
}

export function useBulkCreateProducts() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: {
      common: BulkProductCommon;
      items: BulkProductRow[];
    }) =>
      api<{ created: Product[]; count: number }>("/products/bulk/", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["products"] }),
  });
}

export function useSaveProduct() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (
      payload: Partial<Product> & {
        id?: number;
        /** 系統說可能重複時,寫下哪裡不同才能建 */
        distinct_reason?: string;
        /** 這次編輯定下來的照片清單(沒動過照片就不帶,商品的照片不動) */
        photos?: PhotosPayload;
      },
    ) => {
      const { id, ...body } = payload;
      const method = id ? "PATCH" : "POST";
      const url = id ? `/products/${id}/` : "/products/";
      return api<Product>(url, { method, body: JSON.stringify(body) });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["products"] });
      qc.invalidateQueries({ queryKey: ["product"] });
      qc.invalidateQueries({ queryKey: ["product-photos"] });
    },
  });
}

/** 一個商品的照片(主圖在前)。點品名看照片的面板用 */
export const useProductPhotos = (productId: number | null) =>
  useQuery({
    queryKey: ["product-photos", productId],
    queryFn: () => listProductPhotos(productId as number),
    enabled: productId != null,
  });

export function useSaveCategory() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: Partial<Category> & { id?: number }) => {
      const { id, ...body } = payload;
      const method = id ? "PATCH" : "POST";
      const url = id ? `/categories/${id}/` : "/categories/";
      return api<Category>(url, { method, body: JSON.stringify(body) });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["categories"] });
      // 類別 is_secondhand_default 可能 cascade 到 products,順便刷新
      qc.invalidateQueries({ queryKey: ["products"] });
    },
  });
}

export function useSaveWarehouse() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: Partial<Warehouse> & { id?: number }) => {
      const { id, ...body } = payload;
      const method = id ? "PATCH" : "POST";
      const url = id ? `/warehouses/${id}/` : "/warehouses/";
      return api<Warehouse>(url, { method, body: JSON.stringify(body) });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["warehouses"] }),
  });
}

export function useSaveSupplier() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: Partial<Supplier> & { id?: number }) => {
      const { id, ...body } = payload;
      const method = id ? "PATCH" : "POST";
      const url = id ? `/suppliers/${id}/` : "/suppliers/";
      return api<Supplier>(url, { method, body: JSON.stringify(body) });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["suppliers"] }),
  });
}

export function useSaveCustomer() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: Partial<Customer> & { id?: number }) => {
      const { id, ...body } = payload;
      const method = id ? "PATCH" : "POST";
      const url = id ? `/customers/${id}/` : "/customers/";
      return api<Customer>(url, { method, body: JSON.stringify(body) });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["customers"] }),
  });
}

export function useSaveSalesPerson() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: Partial<SalesPerson> & { id?: number }) => {
      const { id, ...body } = payload;
      const method = id ? "PATCH" : "POST";
      const url = id ? `/sales-persons/${id}/` : "/sales-persons/";
      return api<SalesPerson>(url, { method, body: JSON.stringify(body) });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sales-persons"] }),
  });
}

export async function lookupCustomer(phone: string): Promise<Customer | null> {
  try {
    return await api<Customer>(
      `/customers/lookup/?phone=${encodeURIComponent(phone)}`,
    );
  } catch (e) {
    // 404 = 查無
    return null;
  }
}

export function useSaveMember() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: Partial<Member> & { id?: number }) => {
      const { id, ...body } = payload;
      const method = id ? "PATCH" : "POST";
      const url = id ? `/members/${id}/` : "/members/";
      return api<Member>(url, { method, body: JSON.stringify(body) });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["members"] }),
  });
}

export async function lookupMember(phone: string): Promise<Member | null> {
  try {
    return await api<Member>(
      `/members/lookup/?phone=${encodeURIComponent(phone)}`,
    );
  } catch (e) {
    return null;
  }
}

export interface MemberLastPrice {
  unit_price: string;
  doc_date: string;
  sales_order_no: string;
  sales_order_id: number;
}

export async function lookupMemberLastPrice(
  memberId: number,
  productId: number,
): Promise<MemberLastPrice | null> {
  try {
    return await api<MemberLastPrice>(
      `/sales-orders/last-price/?member=${memberId}&product=${productId}`,
    );
  } catch (e) {
    return null;
  }
}

export function useCreatePurchaseOrder() {
  const qc = useQueryClient();
  return useMutation({
    // key = 這一張新單的鑰匙(Idempotency-Key):同一把重送不會開第二張
    mutationFn: (vars: { payload: Partial<PurchaseOrder>; key?: string }) =>
      api<PurchaseOrder>("/purchase-orders/", {
        method: "POST",
        headers: vars.key ? { "Idempotency-Key": vars.key } : undefined,
        body: JSON.stringify(vars.payload),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["purchase-orders"] });
      qc.invalidateQueries({ queryKey: ["products"] });
      qc.invalidateQueries({ queryKey: ["serials"] });
    },
  });
}

export function useVoidPurchaseOrder() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      api<PurchaseOrder>(`/purchase-orders/${id}/void/`, { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["purchase-orders"] });
      qc.invalidateQueries({ queryKey: ["purchase-order"] });
      qc.invalidateQueries({ queryKey: ["products"] });
      qc.invalidateQueries({ queryKey: ["serials"] });
    },
  });
}

export function useCreateSalesOrder() {
  const qc = useQueryClient();
  return useMutation({
    // key = 這一張新單的鑰匙(Idempotency-Key):同一把重送不會開第二張、不會收兩次錢
    mutationFn: (vars: { payload: Partial<SalesOrder>; key?: string }) =>
      api<SalesOrder>("/sales-orders/", {
        method: "POST",
        headers: vars.key ? { "Idempotency-Key": vars.key } : undefined,
        body: JSON.stringify(vars.payload),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["sales-orders"] });
      qc.invalidateQueries({ queryKey: ["products"] });
      qc.invalidateQueries({ queryKey: ["serials"] });
    },
  });
}

/** 單存了之後改某一行門號合約的日期(續約日往後延、當初打錯);合約到期日由伺服器重算 */
export function useUpdateContractDates() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: {
      soId: number;
      item: number;
      activation_date: string;
      prev_contract_end: string | null;
    }) =>
      api<SalesOrder>(`/sales-orders/${vars.soId}/contract-dates/`, {
        method: "POST",
        body: JSON.stringify({
          item: vars.item,
          activation_date: vars.activation_date,
          prev_contract_end: vars.prev_contract_end,
        }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["sales-orders"] });
      qc.invalidateQueries({ queryKey: ["sales-order"] });
    },
  });
}

export function useVoidSalesOrder() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      api<SalesOrder>(`/sales-orders/${id}/void/`, { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["sales-orders"] });
      qc.invalidateQueries({ queryKey: ["sales-order"] });
      qc.invalidateQueries({ queryKey: ["products"] });
      qc.invalidateQueries({ queryKey: ["serials"] });
      qc.invalidateQueries({ queryKey: ["sim-cards"] });
    },
  });
}

// 銷退單
export interface SalesReturnsFilter extends DateRangeFilter {
  original_so?: number;
}

export const useSalesReturns = (filter?: SalesReturnsFilter) =>
  useQuery({
    queryKey: [
      "sales-returns",
      filter?.from ?? "",
      filter?.to ?? "",
      filter?.original_so ?? "",
    ],
    queryFn: () =>
      list<SalesReturn>(
        `/sales-returns/${buildQS({
          doc_date__gte: filter?.from,
          doc_date__lte: filter?.to,
          original_so: filter?.original_so,
          page_size: 100,
        })}`,
      ),
  });

export const useSalesReturn = (id: number | null) =>
  useQuery({
    queryKey: ["sales-return", id],
    queryFn: () => api<SalesReturn>(`/sales-returns/${id}/`),
    enabled: id != null,
  });

/** 查指定 SO 的「可退明細」(扣除已退累計與已退序號)。 */
export const useReturnableForSO = (salesOrderId: number | null) =>
  useQuery({
    queryKey: ["returnable", salesOrderId],
    queryFn: () =>
      api<ReturnableSummary>(
        `/sales-returns/returnable/?sales_order=${salesOrderId}`,
      ),
    enabled: salesOrderId != null,
  });

export interface CreateSalesReturnPayload {
  original_so: number;
  payment_method: string;
  void_original_invoice: boolean;
  note?: string;
}

export function useCreateSalesReturn() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: CreateSalesReturnPayload) =>
      api<SalesReturn>("/sales-returns/", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["sales-returns"] });
      qc.invalidateQueries({ queryKey: ["sales-orders"] });
      qc.invalidateQueries({ queryKey: ["sales-order"] });
      qc.invalidateQueries({ queryKey: ["returnable"] });
      qc.invalidateQueries({ queryKey: ["serials"] });
      qc.invalidateQueries({ queryKey: ["products"] });
    },
  });
}

export function useVoidSalesReturn() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      api<SalesReturn>(`/sales-returns/${id}/void/`, { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["sales-returns"] });
      qc.invalidateQueries({ queryKey: ["sales-return"] });
      qc.invalidateQueries({ queryKey: ["returnable"] });
      qc.invalidateQueries({ queryKey: ["serials"] });
      qc.invalidateQueries({ queryKey: ["products"] });
    },
  });
}

export interface SecondhandAcquisitionPayload {
  member: number;
  warehouse: number;
  product: number;
  /** 這一台的碼:IMEI、SN 可以都給,也可以只給一個 */
  imei: string;
  sn: string;
  condition_grade: string;
  custom_unit_price?: string | null;
  battery_health?: number | null;
  condition_note?: string;
  acquisition_price: string;
  payment_method_code: string;
  doc_date?: string | null;
  note?: string;
}

export interface SecondhandAcquisitionResult {
  serial: ProductSerial;
  sales_order: SalesOrder;
}

export function useSecondhandAcquisition() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: SecondhandAcquisitionPayload) =>
      api<SecondhandAcquisitionResult>(
        "/sales-orders/secondhand-acquisition/",
        { method: "POST", body: JSON.stringify(payload) },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["sales-orders"] });
      qc.invalidateQueries({ queryKey: ["products"] });
      qc.invalidateQueries({ queryKey: ["serials"] });
    },
  });
}

/** 補登或修改一台設備的 IMEI / SN(店員只能補空的那一格,管理員才能改已登記的)。 */
export function useSetSerialCodes() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (args: { id: number; imei: string; sn: string }) =>
      api<ProductSerial>(`/serials/${args.id}/codes/`, {
        method: "POST",
        body: JSON.stringify({ imei: args.imei, sn: args.sn }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["serials"] });
      qc.invalidateQueries({ queryKey: ["serial-history"] });
    },
  });
}

export function useSerialHistory(serialId: number | null) {
  return useQuery({
    queryKey: ["serial-history", serialId],
    queryFn: () =>
      api<SerialHistory>(`/serials/${serialId}/history/`),
    enabled: serialId != null,
  });
}

export interface SerialHistoryAcquisition {
  kind: "purchase" | "trade_in";
  kind_label: string;
  doc_date: string;
  amount: string;
  // purchase
  purchase_order_id?: number;
  purchase_order_no?: string;
  supplier_id?: number | null;
  supplier_name?: string;
  // trade_in
  sales_order_id?: number;
  sales_order_no?: string;
  member_id?: number | null;
  member_phone?: string;
  member_name?: string;
}

export interface SerialHistoryMovement {
  id: number;
  movement_type: string;
  type_label: string;
  from_warehouse_code: string;
  to_warehouse_code: string;
  ref_doc_type: string;
  ref_doc_id: number | null;
  note: string;
  created_at: string;
}

export interface SerialHistorySale {
  id: number;
  sales_order_id: number;
  sales_order_no: string;
  doc_date: string;
  is_void: boolean;
  customer_phone: string;
  customer_name: string;
  unit_price: string;
  amount: string;
}

export interface SerialCodeChange {
  id: number;
  created_at: string;
  changed_by: string;
  before_imei: string;
  before_sn: string;
  after_imei: string;
  after_sn: string;
}

export interface SerialHistory {
  serial: ProductSerial;
  acquisition: SerialHistoryAcquisition | null;
  movements: SerialHistoryMovement[];
  sales: SerialHistorySale[];
  /** 這一台的 IMEI / SN 被補登或修改過的紀錄(新的在前) */
  code_changes: SerialCodeChange[];
}

// ---- StockBalance ----

export const useStockBalances = (params?: {
  product?: number;
  warehouse?: number;
}) => {
  const qs = new URLSearchParams();
  qs.set("page_size", "200");
  if (params?.product != null) qs.set("product", String(params.product));
  if (params?.warehouse != null) qs.set("warehouse", String(params.warehouse));
  const url = `/stock-balances/?${qs.toString()}`;
  return useQuery({
    queryKey: ["stock-balances", qs.toString()],
    queryFn: () => list<StockBalance>(url),
  });
};

// ---- TransferOrder ----

export const useTransferOrders = (params?: {
  doc_date_gte?: string;
  doc_date_lte?: string;
  status?: string;
}) => {
  const qs = new URLSearchParams();
  qs.set("page_size", "100");
  if (params?.doc_date_gte) qs.set("doc_date__gte", params.doc_date_gte);
  if (params?.doc_date_lte) qs.set("doc_date__lte", params.doc_date_lte);
  if (params?.status) qs.set("status", params.status);
  return useQuery({
    queryKey: ["transfer-orders", qs.toString()],
    queryFn: () => list<TransferOrder>(`/transfer-orders/?${qs.toString()}`),
  });
};

export const useTransferOrder = (id: number | null) =>
  useQuery({
    queryKey: ["transfer-order", id],
    queryFn: () => api<TransferOrder>(`/transfer-orders/${id}/`),
    enabled: id != null,
  });

export function useCreateTransferOrder() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: Partial<TransferOrder>) =>
      api<TransferOrder>("/transfer-orders/", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["transfer-orders"] });
      qc.invalidateQueries({ queryKey: ["products"] });
      qc.invalidateQueries({ queryKey: ["serials"] });
      qc.invalidateQueries({ queryKey: ["stock-balances"] });
    },
  });
}

export function useConfirmTransferOrder() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      api<TransferOrder>(`/transfer-orders/${id}/confirm/`, { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["transfer-orders"] });
      qc.invalidateQueries({ queryKey: ["transfer-order"] });
      qc.invalidateQueries({ queryKey: ["products"] });
      qc.invalidateQueries({ queryKey: ["serials"] });
      qc.invalidateQueries({ queryKey: ["stock-balances"] });
    },
  });
}

export function useVoidTransferOrder() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      api<TransferOrder>(`/transfer-orders/${id}/void/`, { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["transfer-orders"] });
      qc.invalidateQueries({ queryKey: ["transfer-order"] });
      qc.invalidateQueries({ queryKey: ["products"] });
      qc.invalidateQueries({ queryKey: ["serials"] });
      qc.invalidateQueries({ queryKey: ["stock-balances"] });
    },
  });
}


// ────────────────────────────────────────────────────────────
// 平台管理員 endpoints (/platform/*)
// ────────────────────────────────────────────────────────────

export const usePlatformTenants = () =>
  useQuery({
    queryKey: ["platform-tenants"],
    queryFn: () =>
      list<PlatformTenant>("/platform/tenants/?page_size=200"),
  });

export function useSavePlatformTenant() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: Partial<PlatformTenant> & { id?: number }) => {
      const { id, ...body } = payload;
      const method = id ? "PATCH" : "POST";
      const url = id ? `/platform/tenants/${id}/` : "/platform/tenants/";
      return api<PlatformTenant>(url, { method, body: JSON.stringify(body) });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["platform-tenants"] });
      qc.invalidateQueries({ queryKey: ["platform-users"] });
      qc.invalidateQueries({ queryKey: ["platform-warehouses"] });
    },
  });
}

export const usePlatformUsers = () =>
  useQuery({
    queryKey: ["platform-users"],
    queryFn: () => list<PlatformUser>("/platform/users/?page_size=200"),
  });

export function useSavePlatformUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (
      payload: Partial<PlatformUser> & {
        id?: number;
        password?: string;
        tenant?: number | null;
        role?: string;
        default_warehouse?: number | null;
        is_warehouse_locked?: boolean;
        create_sales_person?: boolean;
        sales_person_code?: string;
      },
    ) => {
      const { id, ...body } = payload;
      const method = id ? "PATCH" : "POST";
      const url = id ? `/platform/users/${id}/` : "/platform/users/";
      return api<PlatformUser>(url, { method, body: JSON.stringify(body) });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["platform-users"] }),
  });
}

export function useResetPlatformUserPassword() {
  return useMutation({
    mutationFn: ({ id, password }: { id: number; password: string }) =>
      api(`/platform/users/${id}/reset-password/`, {
        method: "POST",
        body: JSON.stringify({ password }),
      }),
  });
}

export const usePlatformWarehouses = () =>
  useQuery({
    queryKey: ["platform-warehouses"],
    queryFn: () =>
      list<PlatformWarehouse>("/platform/warehouses/?page_size=200"),
  });

export function useSavePlatformWarehouse() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: Partial<PlatformWarehouse> & { id?: number }) => {
      const { id, ...body } = payload;
      const method = id ? "PATCH" : "POST";
      const url = id ? `/platform/warehouses/${id}/` : "/platform/warehouses/";
      return api<PlatformWarehouse>(url, {
        method,
        body: JSON.stringify(body),
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["platform-warehouses"] });
      qc.invalidateQueries({ queryKey: ["platform-tenants"] });
      qc.invalidateQueries({ queryKey: ["warehouses"] });
    },
  });
}

// ─── 維修模組 ───
export const useRepairItems = () =>
  useQuery({
    queryKey: ["repair-items"],
    queryFn: () => list<RepairItem>("/repair-items/?page_size=500"),
  });

export const useRepairItemsByModel = (modelKey: string) =>
  useQuery({
    queryKey: ["repair-items-by-model", modelKey],
    queryFn: () =>
      api<RepairItem[]>(
        `/repair-items/by-model/?model_key=${encodeURIComponent(modelKey)}`,
      ),
    enabled: !!modelKey,
  });

export function useSaveRepairItem() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: Partial<RepairItem> & {
      id?: number;
      model_keys?: string[];
      parts_input?: { part_product: number; default_qty: number }[];
    }) => {
      const { id, ...rest } = body;
      return api<RepairItem>(
        id ? `/repair-items/${id}/` : "/repair-items/",
        {
          method: id ? "PUT" : "POST",
          body: JSON.stringify(rest),
        },
      );
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["repair-items"] });
      qc.invalidateQueries({ queryKey: ["repair-items-by-model"] });
    },
  });
}

export function useDeleteRepairItem() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      api(`/repair-items/${id}/`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["repair-items"] }),
  });
}

export const useRepairOrders = (params?: {
  status?: string;
  mode?: string;
  date_from?: string;
  date_to?: string;
}) => {
  const q = new URLSearchParams();
  if (params?.status) q.set("status", params.status);
  if (params?.mode) q.set("mode", params.mode);
  if (params?.date_from) q.set("received_date__gte", params.date_from);
  if (params?.date_to) q.set("received_date__lte", params.date_to);
  q.set("page_size", "200");
  return useQuery({
    queryKey: ["repair-orders", params],
    queryFn: () => list<RepairOrder>(`/repair-orders/?${q.toString()}`),
  });
};

export const useRepairOrder = (id: number | null) =>
  useQuery({
    queryKey: ["repair-order", id],
    queryFn: () => api<RepairOrder>(`/repair-orders/${id}/`),
    enabled: !!id,
  });

export function useSaveRepairOrder() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (
      body: Partial<RepairOrder> & {
        id?: number;
        parts_input?: { part_product: number; qty: number }[];
      },
    ) => {
      const { id, ...rest } = body;
      return api<RepairOrder>(
        id ? `/repair-orders/${id}/` : "/repair-orders/",
        {
          method: id ? "PATCH" : "POST",
          body: JSON.stringify(rest),
        },
      );
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["repair-orders"] });
      qc.invalidateQueries({ queryKey: ["repair-order"] });
    },
  });
}

export function useSetRepairStatus() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { id: number; status: string }) =>
      api<RepairOrder>(`/repair-orders/${vars.id}/set-status/`, {
        method: "POST",
        body: JSON.stringify({ status: vars.status }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["repair-orders"] });
      qc.invalidateQueries({ queryKey: ["repair-order"] });
    },
  });
}

export function useCompleteRepair() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      api<RepairOrder>(`/repair-orders/${id}/complete/`, { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["repair-orders"] });
      qc.invalidateQueries({ queryKey: ["repair-order"] });
    },
  });
}

export function useReopenRepair() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      api<RepairOrder>(`/repair-orders/${id}/reopen/`, { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["repair-orders"] });
      qc.invalidateQueries({ queryKey: ["repair-order"] });
    },
  });
}

export const useRepairQuotePreview = (id: number | null) =>
  useQuery({
    queryKey: ["repair-quote-preview", id],
    queryFn: () =>
      api<RepairQuotePreview>(`/repair-orders/${id}/quote-preview/`),
    enabled: !!id,
  });

export const useRepairHistoryByPhone = (phone: string) =>
  useQuery({
    queryKey: ["repair-history-by-phone", phone],
    queryFn: () =>
      api<RepairHistoryItem[]>(
        `/repair-orders/history-by-phone/?phone=${encodeURIComponent(phone)}`,
      ),
    enabled: !!phone && phone.trim().length >= 4,
    staleTime: 60_000,
  });

// ── 員工帳號的權限(系統設定 → 員工帳號;只有管理員)
export const useStaffAccounts = () =>
  useQuery({
    queryKey: ["staff-accounts"],
    queryFn: () => api<StaffAccountsResponse>(`/staff-accounts/`),
  });

export function useSaveStaffAbilities() {
  return useMutation({
    mutationFn: ({ id, abilities }: { id: number; abilities: Record<string, boolean> }) =>
      api<StaffAccount>(`/staff-accounts/${id}/`, {
        method: "PATCH",
        body: JSON.stringify({ abilities }),
      }),
    // 重抓由頁面決定(全部存完才抓一次:不拿半路的結果蓋掉還在存的那幾格)
  });
}

export interface TenantSettings {
  id: number;
  name?: string;
  code?: string;
  repair_warranty_days: number;
  /** 門號合約到期前幾個月開始出現在待聯絡名單 */
  contract_remind_months: number;
  /** 業務員成本全公司的那一條:只有管理員的資料裡有。"" = 尚未設定 */
  staff_cost_mode?: string;
  staff_cost_value?: string;
}

export const useTenantSettings = () =>
  useQuery({
    queryKey: ["tenant-settings"],
    queryFn: () => api<TenantSettings>(`/tenant-settings/`),
    staleTime: 5 * 60_000,
  });

export function useSaveTenantSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Partial<TenantSettings>) =>
      api<TenantSettings>(`/tenant-settings/`, {
        method: "PATCH",
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tenant-settings"] });
      // 「到期前幾個月提醒」改了:合約到期的名單與今日總覽的筆數要跟著重抓
      qc.invalidateQueries({ queryKey: ["telecom-contracts"] });
      qc.invalidateQueries({ queryKey: ["home-summary"] });
      // 業務員成本全公司的那一條改了:商品上算出來的數字要跟著重抓
      qc.invalidateQueries({ queryKey: ["products"] });
    },
  });
}

export const usePartsUsageReport = (params: {
  from?: string;
  to?: string;
}) => {
  const q = new URLSearchParams();
  if (params.from) q.set("from", params.from);
  if (params.to) q.set("to", params.to);
  return useQuery({
    queryKey: ["parts-usage-report", params],
    queryFn: () =>
      api<PartsUsageReport>(`/parts-usage-report/?${q.toString()}`),
    enabled: !!(params.from && params.to),
  });
};

export const usePartTemplates = () =>
  useQuery({
    queryKey: ["part-templates"],
    queryFn: () => list<PartTemplate>(`/part-templates/?page_size=100`),
  });

export const usePartTemplate = (id: number | null) =>
  useQuery({
    queryKey: ["part-template", id],
    queryFn: () => api<PartTemplate>(`/part-templates/${id}/`),
    enabled: !!id,
  });

export function useSavePartTemplate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (
      body: Partial<PartTemplate> & {
        id?: number;
        items_input?: unknown[];
      },
    ) => {
      const { id, ...rest } = body;
      return api<PartTemplate>(
        id ? `/part-templates/${id}/` : "/part-templates/",
        {
          method: id ? "PATCH" : "POST",
          body: JSON.stringify(rest),
        },
      );
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["part-templates"] });
      qc.invalidateQueries({ queryKey: ["part-template"] });
    },
  });
}

export function useDeletePartTemplate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      api<void>(`/part-templates/${id}/`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["part-templates"] });
    },
  });
}

export function usePartTemplatePreview() {
  return useMutation({
    mutationFn: (vars: {
      template_id: number;
      model_keys: string[];
      defaults?: { cost?: string; safety_stock?: number };
    }) =>
      api<{ rows: PartPreviewRow[] }>(
        `/part-templates/${vars.template_id}/preview/`,
        {
          method: "POST",
          body: JSON.stringify({
            model_keys: vars.model_keys,
            defaults: vars.defaults ?? {},
          }),
        },
      ),
  });
}

export function usePartBulkCreate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: {
      template_id: number;
      category_id: number;
      rows: Partial<PartPreviewRow>[];
    }) =>
      api<PartBulkCreateResult>(
        `/part-templates/${vars.template_id}/bulk-create/`,
        {
          method: "POST",
          body: JSON.stringify({
            category_id: vars.category_id,
            rows: vars.rows,
          }),
        },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["products"] });
    },
  });
}

// ─── Brand / PhoneSeries master ───

export const useBrands = () =>
  useQuery({
    queryKey: ["brands"],
    queryFn: () => list<Brand>(`/brands/?page_size=100`),
  });

export function useSaveBrand() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: Partial<Brand> & { id?: number }) => {
      const { id, ...body } = payload;
      const method = id ? "PATCH" : "POST";
      const url = id ? `/brands/${id}/` : "/brands/";
      return api<Brand>(url, { method, body: JSON.stringify(body) });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["brands"] }),
  });
}

export const usePhoneSeriesList = (brandId?: number | null) =>
  useQuery({
    queryKey: ["phone-series", brandId ?? "all"],
    queryFn: () =>
      list<PhoneSeries>(
        brandId
          ? `/phone-series/?brand=${brandId}&is_active=true&page_size=100`
          : `/phone-series/?is_active=true&page_size=100`,
      ),
    enabled: brandId != null && brandId > 0,
  });

export function useSavePhoneSeries() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: Partial<PhoneSeries> & { id?: number }) => {
      const { id, ...body } = payload;
      const method = id ? "PATCH" : "POST";
      const url = id ? `/phone-series/${id}/` : "/phone-series/";
      return api<PhoneSeries>(url, { method, body: JSON.stringify(body) });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["phone-series"] }),
  });
}

export function useDeleteBrand() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      api<void>(`/brands/${id}/`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["brands"] });
      qc.invalidateQueries({ queryKey: ["phone-series"] });
    },
  });
}

export function useDeletePhoneSeries() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      api<void>(`/phone-series/${id}/`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["phone-series"] });
      qc.invalidateQueries({ queryKey: ["brands"] });
    },
  });
}

// ─── ProductType master ───

export const useProductTypes = () =>
  useQuery({
    queryKey: ["product-types"],
    queryFn: () => list<ProductType>(`/product-types/?page_size=100`),
  });

export function useSaveProductType() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: Partial<ProductType> & { id?: number }) => {
      const { id, ...body } = payload;
      const method = id ? "PATCH" : "POST";
      const url = id ? `/product-types/${id}/` : "/product-types/";
      return api<ProductType>(url, { method, body: JSON.stringify(body) });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["product-types"] });
      qc.invalidateQueries({ queryKey: ["phone-series"] });
    },
  });
}

export function useDeleteProductType() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      api<void>(`/product-types/${id}/`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["product-types"] });
      qc.invalidateQueries({ queryKey: ["phone-series"] });
    },
  });
}

// ─── 新增手機型號 wizard:一鍵建主機 SKU + 配件 + 零件 ───

export interface PhoneModelBundlePayload {
  brand_id: number | null;
  series_id: number | null;
  generation: number | null;
  model_suffix: string;
  main_category_id: number | null;
  accessory_category_id: number | null;
  parts_category_id: number | null;
  template_id: number | null;
  /** 整批共用的建議售價;`list_prices` 沒給的容量才用它(畫面現在都給 `list_prices`,這一格送 "0") */
  list_price: string;
  /** 每個容量的建議售價 {容量: 整數元};只能指到 `capacities` 裡有的 */
  list_prices?: Record<string, string>;
  condition_ids: number[];
  capacities: string[];
  colors: string[];
  /** 地區版本(台版 / 港版 …);整批一個值,不是維度 */
  region_version: string;
  /** 預覽列出可能重複時,每一筆各自寫哪裡不同:{品名: 理由} */
  distinct_reasons?: Record<string, string>;
  accessory_categories: string[];
  parts_items: Array<{
    name: string;
    code: string;
    shared_across_models?: boolean;
    default_cost?: string;
    default_safety_stock?: number;
  }>;
  dry_run?: boolean;
}

export interface PhoneModelBundleResult {
  model_name: string;
  model_key: string;
  /** 可能跟既有商品重複的 SKU(預覽時列出) */
  possible_duplicates?: Array<{
    name: string;
    kind: string;
    candidates: DuplicateCandidate[];
  }>;
  main_count: number;
  parts_count: number;
  /** 相容配件類別槽位記錄,不會建 SKU(配件走獨立 wizard) */
  accessory_slots: string[];
  main: Array<{
    id?: number;
    sku?: string;
    name: string;
    spec?: string;
    is_secondhand: boolean;
    condition_id?: number;
    condition_name?: string;
    capacity?: string;
    color?: string;
    region_version?: string;
    /** 這一個品項的建議售價(整數元) */
    list_price?: string;
  }>;
  parts: Array<{
    id?: number;
    sku?: string;
    name: string;
    code?: string;
    shared_across_models?: boolean;
  }>;
}

export function useCreatePhoneModelBundle() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: PhoneModelBundlePayload) =>
      api<PhoneModelBundleResult>("/products/create-phone-model/", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: (_, vars) => {
      if (!vars.dry_run) {
        qc.invalidateQueries({ queryKey: ["products"] });
        qc.invalidateQueries({ queryKey: ["stock-matrix"] });
      }
    },
  });
}

// ─── 機型分組瀏覽(型錄不翻倍:一機型一列,展開看底下全新/中古 SKU)───

export interface PhoneModelRow {
  model_key: string;
  model_name: string;
  sku_count: number;
  total_stock: number;
  brand_code: string;
  brand_name: string;
  series: string;
}

export const usePhoneModels = (search?: string) =>
  useQuery({
    queryKey: ["phone-models", search ?? ""],
    queryFn: () => {
      const p = new URLSearchParams();
      if (search) p.set("search", search);
      return api<PhoneModelRow[]>(`/products/phone-models/?${p}`);
    },
  });

export interface PhoneModelSkuGroup {
  condition: string;
  sort: number;
  is_secondhand: boolean;
  skus: {
    id: number;
    sku: string;
    name: string;
    capacity: string;
    color: string;
    region_version: string;
    list_price: string;
    stock_qty: number;
  }[];
}

export const useProductsByPhoneModel = (
  modelKey: string | null,
  warehouseIds?: number[],
) =>
  useQuery({
    queryKey: ["by-phone-model", modelKey ?? "", (warehouseIds ?? []).join(",")],
    queryFn: () => {
      const p = new URLSearchParams();
      p.set("model_key", modelKey ?? "");
      if (warehouseIds && warehouseIds.length > 0) {
        p.set("warehouse_ids", warehouseIds.join(","));
      }
      return api<PhoneModelSkuGroup[]>(`/products/by-phone-model/?${p}`);
    },
    enabled: !!modelKey,
  });

// ─── Condition master(商品狀態:全新 / 已拆封 / 中古機 …)───

export const useConditions = () =>
  useQuery({
    queryKey: ["conditions"],
    queryFn: () => list<Condition>(`/conditions/?page_size=100`),
  });

export function useSaveCondition() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: Partial<Condition> & { id?: number }) => {
      const { id, ...body } = payload;
      const method = id ? "PATCH" : "POST";
      const url = id ? `/conditions/${id}/` : "/conditions/";
      return api<Condition>(url, { method, body: JSON.stringify(body) });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["conditions"] }),
  });
}

export function useDeleteCondition() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      api<void>(`/conditions/${id}/`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["conditions"] }),
  });
}

export interface BrandImportResult {
  summary: {
    brands_created: number;
    brands_updated: number;
    series_created: number;
    series_updated: number;
    types_created: number;
    types_updated: number;
    rows_skipped: number;
  };
  preview: Array<{
    line: number;
    brand_name: string;
    brand_code: string;
    brand_action: string;
    series_name: string;
    series_code: string;
    series_action: string;
    type_name: string;
    type_code: string;
    type_action: string;
  }>;
  errors: Array<{ line: number; msg: string }>;
}

export function useImportBrandsSeries() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (vars: { file: File; dryRun: boolean }) => {
      const fd = new FormData();
      fd.append("file", vars.file);
      fd.append("dry_run", vars.dryRun ? "true" : "false");
      return api<BrandImportResult>("/brands/import/", {
        method: "POST",
        body: fd,
      });
    },
    onSuccess: (_, vars) => {
      if (!vars.dryRun) {
        qc.invalidateQueries({ queryKey: ["brands"] });
        qc.invalidateQueries({ queryKey: ["phone-series"] });
        qc.invalidateQueries({ queryKey: ["product-types"] });
      }
    },
  });
}

// ---- identity:商品別名 ----

export const useProductAliases = (product: number | null) =>
  useQuery({
    queryKey: ["product-aliases", product],
    queryFn: () =>
      list<ProductAlias>(`/identity/aliases/?product=${product}&page_size=200`),
    enabled: product != null,
  });

/** 「記住這個叫法」:把一句話記到一個既有商品上 */
export function useRememberPhrase() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: {
      product: number;
      value: string;
      supplier?: number | null;
      /** 這句話已指到別的商品時明確要求改指(限管理員) */
      repoint?: boolean;
    }) =>
      api<{ action: string; alias: ProductAlias | null }>(
        "/identity/aliases/remember/",
        { method: "POST", body: JSON.stringify(v) },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["product-aliases"] }),
  });
}

export function useSaveProductAlias() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: Partial<ProductAlias> & { id?: number }) => {
      const { id, ...body } = payload;
      const method = id ? "PATCH" : "POST";
      const url = id ? `/identity/aliases/${id}/` : "/identity/aliases/";
      return api<ProductAlias>(url, { method, body: JSON.stringify(body) });
    },
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ["product-aliases"] }),
  });
}

// ---- identity:待確認入庫 ----

export const useIntakeBatches = (params?: string) =>
  useQuery({
    queryKey: ["intake-batches", params ?? ""],
    queryFn: () =>
      list<IntakeBatch>(`/identity/intakes/${params ? "?" + params : ""}`),
  });

export const useIntakeBatch = (id: number | null) =>
  useQuery({
    queryKey: ["intake-batch", id],
    queryFn: () => api<IntakeBatch>(`/identity/intakes/${id}/`),
    enabled: id != null,
  });

export function useCreateIntake() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      raw_text: string;
      supplier?: number | null;
      warehouse?: number | null;
      vendor_doc_no?: string;
      source?: string;
    }) =>
      api<IntakeBatch>("/identity/intakes/", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["intake-batches"] }),
  });
}

export function useCreateIntakeOcr() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: {
      image: File;
      supplier?: number | null;
      warehouse?: number | null;
    }) => {
      const fd = new FormData();
      fd.append("image", v.image);
      if (v.supplier != null) fd.append("supplier", String(v.supplier));
      if (v.warehouse != null) fd.append("warehouse", String(v.warehouse));
      return api<IntakeBatch>("/identity/intakes/ocr/", { method: "POST", body: fd });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["intake-batches"] }),
  });
}

export function useCommitIntake() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      api<IntakeBatch>(`/identity/intakes/${id}/commit/`, { method: "POST" }),
    onSuccess: (b) => {
      qc.invalidateQueries({ queryKey: ["intake-batches"] });
      qc.invalidateQueries({ queryKey: ["intake-batch", b.id] });
    },
  });
}

function intakeItemAction(path: string, body?: unknown) {
  return api<IntakeItem>(path, {
    method: "POST",
    body: body ? JSON.stringify(body) : undefined,
  });
}

function invalidateIntake(qc: ReturnType<typeof useQueryClient>) {
  qc.invalidateQueries({ queryKey: ["intake-batch"] });
  qc.invalidateQueries({ queryKey: ["intake-batches"] });
}

export function useMatchIntakeItem() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: {
      id: number;
      product: number;
      learn_alias?: boolean;
      /** 商品已停用時,明確要求恢復(限管理員) */
      restore?: boolean;
    }) =>
      intakeItemAction(`/identity/intake-items/${v.id}/match/`, {
        product: v.product,
        learn_alias: v.learn_alias ?? true,
        restore: v.restore ?? false,
      }),
    onSuccess: () => invalidateIntake(qc),
  });
}

export function useNewProductForIntakeItem() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: {
      id: number;
      name?: string;
      category: number;
      capacity?: string;
      color?: string;
      region_version?: string;
      requires_serial?: boolean;
      learn_alias?: boolean;
      distinct_reason?: string;
    }) => {
      const { id, ...body } = v;
      return intakeItemAction(
        `/identity/intake-items/${id}/new-product/`,
        body,
      );
    },
    onSuccess: () => {
      invalidateIntake(qc);
      qc.invalidateQueries({ queryKey: ["products"] });
    },
  });
}

export function useRejectIntakeItem() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      intakeItemAction(`/identity/intake-items/${id}/reject/`),
    onSuccess: () => invalidateIntake(qc),
  });
}

export function useCorrectIntakeItem() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: {
      id: number;
      name?: string;
      qty?: number;
      unit_price?: string;
      barcode?: string;
      vendor_sku?: string;
      serials?: string[];
    }) => {
      const { id, ...body } = v;
      return intakeItemAction(`/identity/intake-items/${id}/correct/`, body);
    },
    onSuccess: () => invalidateIntake(qc),
  });
}

export function useCaptureIntakeUnits() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: {
      id: number;
      units: {
        identifiers: { kind?: string; value: string; is_primary?: boolean }[];
      }[];
    }) =>
      intakeItemAction(`/identity/intake-items/${v.id}/units/`, {
        units: v.units,
      }),
    onSuccess: () => invalidateIntake(qc),
  });
}

export function useSetIntakeHeader() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: {
      id: number;
      supplier?: number | null;
      warehouse?: number | null;
      tax_method?: string;
      vendor_doc_no?: string;
      document_total?: string | number | null;
    }) => {
      const { id, ...body } = v;
      return api<IntakeBatch>(`/identity/intakes/${id}/set-header/`, {
        method: "POST",
        body: JSON.stringify(body),
      });
    },
    onSuccess: (b) => {
      qc.invalidateQueries({ queryKey: ["intake-batches"] });
      qc.invalidateQueries({ queryKey: ["intake-batch", b.id] });
    },
  });
}

// ---- 舊 POS(歐睿)十年會員消費 ----
export interface LegacyHistoryFilters {
  date_from?: string;
  date_to?: string;
  store?: string;
  doc_type?: string;
  doc_no?: string;
}

function legacyQuery(params: Record<string, string | number | undefined>) {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== "") q.set(k, String(v));
  }
  return q.toString();
}

/** 某位會員的舊 POS 單據(分頁);summary 是後端算的完整篩選範圍合計 */
export const useLegacyHistory = (
  memberId: number | null,
  filters: LegacyHistoryFilters,
  page: number,
) =>
  useQuery({
    queryKey: ["legacy-history", memberId, filters, page],
    queryFn: () =>
      api<LegacyHistoryPage>(
        `/legacy/history/?${legacyQuery({ member: memberId ?? "", page, page_size: 20, ...filters })}`,
      ),
    enabled: memberId != null,
  });

export const useLegacyDocument = (id: number | null, memberId: number) =>
  useQuery({
    queryKey: ["legacy-document", id, memberId],
    queryFn: () =>
      api<LegacyHistoryDocDetail>(`/legacy/history/${id}/?member=${memberId}`),
    enabled: id != null,
  });

/** 這位會員可能對應的舊 POS 會員(管理員) */
export const useLegacyCandidates = (memberId: number | null, enabled: boolean) =>
  useQuery({
    queryKey: ["legacy-candidates", memberId],
    queryFn: () =>
      api<{ results: LegacyMemberRow[] }>(`/legacy/candidates/?member=${memberId}`).then(
        (d) => d.results,
      ),
    enabled: enabled && memberId != null,
  });

export const useLegacyMembers = (params: Record<string, string | number | undefined>) =>
  useQuery({
    queryKey: ["legacy-members", params],
    queryFn: () => api<LegacyMembersPage>(`/legacy/members/?${legacyQuery(params)}`),
  });

export const useLegacyMaps = (
  kind: LegacyMapKind,
  params: Record<string, string | number | undefined>,
) =>
  useQuery({
    queryKey: ["legacy-maps", kind, params],
    queryFn: () => api<LegacyMapsPage>(`/legacy/maps/${kind}/?${legacyQuery(params)}`),
  });

export const useLegacyMapCandidates = (kind: LegacyMapKind, id: number | null) =>
  useQuery({
    queryKey: ["legacy-map-candidates", kind, id],
    queryFn: () =>
      api<{ results: LegacyCandidate[] }>(`/legacy/maps/${kind}/${id}/candidates/`).then(
        (d) => d.results,
      ),
    enabled: id != null,
  });

export const useLegacyExceptions = () =>
  useQuery({
    queryKey: ["legacy-exceptions"],
    queryFn: () =>
      api<{ results: LegacyException[] }>(`/legacy/exceptions/`).then((d) => d.results),
  });

export const useLedgerChecks = () =>
  useQuery({
    queryKey: ["ledger-checks"],
    queryFn: () => api<LedgerOverview>(`/ledger/checks/`),
  });

// ── 自由組合報表 ────────────────────────────────────────────────────────────
export const useAnalyticsCatalog = () =>
  useQuery({
    queryKey: ["analytics-catalog"],
    queryFn: () => api<AnalyticsCatalog>(`/analytics/catalog/`),
    staleTime: Infinity,
  });

export const useAnalyticsQuery = (spec: AnalyticsSpec | null) =>
  useQuery({
    queryKey: ["analytics-query", spec],
    queryFn: () =>
      api<AnalyticsResult>(`/analytics/query/`, {
        method: "POST",
        body: JSON.stringify(spec),
      }),
    enabled: !!spec,
    placeholderData: (prev) => prev,
    retry: false,
  });

// ── 廠商叫貨(多廠商;每一支都要講是哪一家 `vendor`)──────────────────────────────
export const useVendorLinks = () =>
  useQuery({
    queryKey: ["vendor-links"],
    queryFn: () => api<{ results: VendorLinkRow[]; categories: VendorCategoryOption[] }>(`/vendor-links/`),
  });

/** 存一家門市的串接設定;`key` 有給才換金鑰(伺服器會拿它去問廠商一次)。 */
export const useSaveVendorLink = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Partial<VendorLinkRow> & { warehouse: number; vendor: string; key?: string }) =>
      api<VendorLinkRow>(`/vendor-links/`, { method: "POST", body: JSON.stringify(body) }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["vendor-links"] });
      qc.invalidateQueries({ queryKey: ["vendor-catalog"] });
    },
  });
};

export const useRemoveVendorKey = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { warehouse: number; vendor: string }) =>
      api<VendorLinkRow>(`/vendor-links/${vars.warehouse}/remove-key/`, {
        method: "POST",
        body: JSON.stringify({ vendor: vars.vendor }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["vendor-links"] });
      qc.invalidateQueries({ queryKey: ["vendor-catalog"] });
    },
  });
};

/** 廠商現在的商品與這家門市的進價。每次進這一頁現抓(價錢是廠商的,不留舊的)。 */
export const useVendorCatalog = (warehouse: number | null, vendor: string | null) =>
  useQuery({
    queryKey: ["vendor-catalog", warehouse, vendor],
    queryFn: () =>
      api<{ warehouse: number; vendor: string; manual: boolean; rows: CatalogRow[] }>(
        `/vendor-orders/catalog/?warehouse=${warehouse}&vendor=${encodeURIComponent(vendor ?? "")}`,
      ),
    enabled: warehouse !== null && vendor !== null,
    retry: false,
    gcTime: 0,
    refetchOnWindowFocus: false,
  });

export const useVendorOrders = (warehouse: number | null, vendor: string | null) =>
  useQuery({
    queryKey: ["vendor-orders", warehouse, vendor],
    queryFn: () =>
      api<{ results: VendorOrder[] }>(
        `/vendor-orders/?warehouse=${warehouse}&vendor=${encodeURIComponent(vendor ?? "")}`,
      ),
    enabled: warehouse !== null && vendor !== null,
  });

/** 送出一張叫貨單。**不自動重試**:沒有答覆時要不要再送由畫面照同一把鑰匙決定。 */
export const usePlaceVendorOrder = () =>
  useMutation({
    retry: false,
    mutationFn: (body: {
      request_key: string;
      warehouse: number;
      vendor: string;
      lines: { key: string; packs: number }[];
      payment_method: string;
      delivery_method: string;
      note: string;
    }) => api<VendorOrder>(`/vendor-orders/`, { method: "POST", body: JSON.stringify(body) }),
  });

export const useResendVendorOrder = () =>
  useMutation({
    retry: false,
    mutationFn: (id: number) => api<VendorOrder>(`/vendor-orders/${id}/resend/`, { method: "POST" }),
  });

/** 跟廠商要最新進度;順便帶回「不是從 POS 叫的」訂單。 */
export const useSyncVendorOrders = () =>
  useMutation({
    retry: false,
    mutationFn: (vars: { warehouse: number; vendor: string }) =>
      api<{ results: VendorOrder[]; others: VendorOutsideOrder[] }>(`/vendor-orders/sync/`, {
        method: "POST",
        body: JSON.stringify(vars),
      }),
  });

/** 到貨入庫要看的:廠商這張單現在的每一行、已出 / 已入 / 建議入幾個、對到哪個品號。每次打開現抓。 */
export const useVendorReceiving = (orderId: number | null) =>
  useQuery({
    queryKey: ["vendor-receiving", orderId],
    queryFn: () => api<ReceivePlan>(`/vendor-orders/${orderId}/receiving/`),
    enabled: orderId !== null,
    retry: false,
    gcTime: 0,
    refetchOnWindowFocus: false,
  });

/** 半自動廠商的單要看的(同一支端點,內容不一樣):店家叫的每一行、已入幾個、還可以加的品項。每次打開現抓。 */
export const useManualReceiving = (orderId: number | null) =>
  useQuery({
    queryKey: ["vendor-receiving-manual", orderId],
    queryFn: () => api<ManualPlan>(`/vendor-orders/${orderId}/receiving/`),
    enabled: orderId !== null,
    retry: false,
    gcTime: 0,
    refetchOnWindowFocus: false,
  });

/** 到貨入庫(開一張進貨單)。**不自動重試**:同一把鑰匙再送不會入兩次,要不要再送由畫面決定。 */
export const useReceiveVendorOrder = () => {
  const qc = useQueryClient();
  return useMutation({
    retry: false,
    mutationFn: (vars: {
      order: number;
      request_key: string;
      lines: ReceiveSend[] | ManualSend[];
      issue_note: string;
      /** 半自動廠商的單才有:這一次的運費(整數元) */
      freight?: number;
    }) =>
      api<{ receipt: number; order: VendorOrder }>(`/vendor-orders/${vars.order}/receive/`, {
        method: "POST",
        body: JSON.stringify({ request_key: vars.request_key, lines: vars.lines, issue_note: vars.issue_note, freight: vars.freight }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["vendor-orders"] });
      qc.invalidateQueries({ queryKey: ["purchase-orders"] });
      qc.invalidateQueries({ queryKey: ["products"] });
    },
  });
};

/**
 * 品名連連看:這家廠商現在的每一個品項與對到的店內商品。每次進那一頁現抓(品項是廠商的,不留舊的);
 * 不在背後自己重抓(人正要按的時候列不能自己換)。
 */
export const useVendorMappings = (warehouse: number | null, vendor: string | null) =>
  useQuery({
    queryKey: ["vendor-mappings", warehouse, vendor],
    queryFn: () =>
      api<MappingData>(`/vendor-orders/mappings/?warehouse=${warehouse}&vendor=${encodeURIComponent(vendor ?? "")}`),
    enabled: warehouse !== null && vendor !== null,
    retry: false,
    gcTime: 0,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });

/** 連 / 改 / 解除一個品項(`product` 給 null = 解除)。存完把伺服器回的那一列放回清單,不重抓整份。 */
export const useSaveVendorMapping = () => {
  const qc = useQueryClient();
  return useMutation({
    retry: false,
    mutationFn: (vars: { warehouse: number; vendor: string; key: string; product: number | null }) =>
      api<MappingRow>(`/vendor-orders/mappings/`, { method: "POST", body: JSON.stringify(vars) }),
    onSuccess: (row, vars) => {
      qc.setQueryData<MappingData>(["vendor-mappings", vars.warehouse, vars.vendor], (old) => withSaved(old, row));
    },
  });
};

/** 把廠商那邊「不是從這裡叫的」一張單認進來(之後才能到貨入庫)。認兩次是同一筆。 */
export const useAdoptVendorOrder = () =>
  useMutation({
    retry: false,
    mutationFn: (body: { warehouse: number; vendor: string; order_no: string }) =>
      api<VendorOrder>(`/vendor-orders/adopt/`, { method: "POST", body: JSON.stringify(body) }),
  });

/** 到貨問題(送錯、少到…):只記一句,不入庫。 */
export const useSaveVendorIssue = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { order: number; note: string }) =>
      api<VendorOrder>(`/vendor-orders/${vars.order}/issue/`, { method: "POST", body: JSON.stringify({ note: vars.note }) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["vendor-orders"] }),
  });
};

/** 半自動廠商的叫貨單:已貼給廠商 / 記一句進度 / 取消與恢復。回這張單現在的樣子,直接放回清單(不重抓)。 */
export const useVendorOrderAction = () => {
  const qc = useQueryClient();
  return useMutation({
    retry: false,
    mutationFn: (vars: { order: number; action: "sent" | "progress" | "cancel"; body: Record<string, unknown> }) =>
      api<VendorOrder>(`/vendor-orders/${vars.order}/${vars.action}/`, { method: "POST", body: JSON.stringify(vars.body) }),
    onSuccess: (order) => {
      qc.setQueriesData<{ results: VendorOrder[] }>({ queryKey: ["vendor-orders"] }, (old) =>
        old ? { ...old, results: old.results.map((o) => (o.id === order.id ? order : o)) } : old,
      );
    },
  });
};

// 平台管理:半自動廠商的價目表
export const usePlatformVendorItems = (vendorId: number | null) =>
  useQuery({
    queryKey: ["platform-vendor-items", vendorId],
    queryFn: () => api<{ vendor: string; results: PlatformVendorItem[] }>(`/platform/vendors/${vendorId}/items/`),
    enabled: vendorId !== null,
  });

export const useSavePlatformVendorItem = (vendorId: number) => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: Partial<PlatformVendorItem> & { id?: number }) => {
      const { id, ...body } = payload;
      return api<PlatformVendorItem>(id ? `/platform/vendor-items/${id}/` : `/platform/vendors/${vendorId}/items/`, {
        method: id ? "PATCH" : "POST",
        body: JSON.stringify(body),
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["platform-vendor-items", vendorId] });
      qc.invalidateQueries({ queryKey: ["platform-vendors"] });
    },
  });
};

/** 整批貼上:`apply` 沒給 = 只預覽;有問題的那一批伺服器回 400 但內容一樣是預覽(畫面要顯示哪幾列有錯)。 */
export const useImportPlatformVendorItems = (vendorId: number) => {
  const qc = useQueryClient();
  return useMutation({
    retry: false,
    mutationFn: async (vars: { rows: PastedItem[]; apply: boolean }) => {
      try {
        return await api<VendorItemImport>(`/platform/vendors/${vendorId}/items/import/`, {
          method: "POST",
          body: JSON.stringify(vars),
        });
      } catch (e) {
        const body = e instanceof ApiHttpError ? (e.body as VendorItemImport | undefined) : undefined;
        if (body && Array.isArray(body.rows)) return body;
        throw e;
      }
    },
    onSuccess: (got) => {
      if (!got.applied) return;
      qc.invalidateQueries({ queryKey: ["platform-vendor-items", vendorId] });
      qc.invalidateQueries({ queryKey: ["platform-vendors"] });
    },
  });
};

// 平台管理:叫貨類別與廠商名單(只有平台管理員;只能停用、不能刪)
export const usePlatformVendorCategories = () =>
  useQuery({
    queryKey: ["platform-vendor-categories"],
    queryFn: () => api<{ results: PlatformVendorCategory[] }>(`/platform/vendor-categories/`),
  });

export const useSavePlatformVendorCategory = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: Partial<PlatformVendorCategory> & { id?: number }) => {
      const { id, ...body } = payload;
      return api<PlatformVendorCategory>(id ? `/platform/vendor-categories/${id}/` : `/platform/vendor-categories/`, {
        method: id ? "PATCH" : "POST",
        body: JSON.stringify(body),
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["platform-vendor-categories"] });
      qc.invalidateQueries({ queryKey: ["vendor-links"] });
    },
  });
};

export const usePlatformVendors = () =>
  useQuery({
    queryKey: ["platform-vendors"],
    queryFn: () =>
      api<{ results: PlatformVendor[]; protocols: { value: string; label: string }[] }>(`/platform/vendors/`),
  });

export const useSavePlatformVendor = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: Partial<PlatformVendor> & { id?: number }) => {
      const { id, ...body } = payload;
      return api<PlatformVendor>(id ? `/platform/vendors/${id}/` : `/platform/vendors/`, {
        method: id ? "PATCH" : "POST",
        body: JSON.stringify(body),
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["platform-vendors"] });
      qc.invalidateQueries({ queryKey: ["platform-vendor-categories"] });
      qc.invalidateQueries({ queryKey: ["vendor-links"] });
    },
  });
};

// 固定的報表:內容由伺服器定,畫面只送日期 / 門市 /(商品排行)照什麼分。
// 不留上一份當佔位:三張報表共用同一個元件,欄位不一樣,換一張時不能先畫上一張的。
export const useFixedReport = (key: string, range: ReportRange) =>
  useQuery({
    queryKey: ["fixed-report", key, range],
    queryFn: () =>
      api<FixedReportResult>(`/analytics/presets/${key}/?${rangeQuery(range)}`),
    enabled: rangeReady(range),
    retry: false,
  });

export const useCommissionLines = (range: ReportRange) =>
  useQuery({
    queryKey: ["commission-lines", range],
    queryFn: () =>
      api<CommissionLines>(`/telecom-commissions/?${rangeQuery(range)}`),
    enabled: rangeReady(range),
    retry: false,
  });

export const useAnalyticsOptions = (dimension: string | null, q: string) =>
  useQuery({
    queryKey: ["analytics-options", dimension, q],
    queryFn: () =>
      api<{ results: AnalyticsOption[] }>(
        `/analytics/options/?dimension=${encodeURIComponent(dimension ?? "")}&q=${encodeURIComponent(q)}`,
      ).then((r) => r.results),
    enabled: !!dimension,
    placeholderData: (prev) => prev,
  });

export const useSavedReports = () =>
  useQuery({
    queryKey: ["analytics-reports"],
    queryFn: () =>
      api<{ results: SavedReport[] }>(`/analytics/reports/`).then((r) => r.results),
  });

export function useSaveReport() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: {
      id?: number;
      name: string;
      spec: AnalyticsSpec;
      shared: boolean;
    }) => {
      const { id, ...body } = payload;
      return api<SavedReport>(id ? `/analytics/reports/${id}/` : `/analytics/reports/`, {
        method: id ? "PATCH" : "POST",
        body: JSON.stringify(body),
      });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["analytics-reports"] }),
  });
}

export function useDeleteReport() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      api<void>(`/analytics/reports/${id}/`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["analytics-reports"] }),
  });
}
