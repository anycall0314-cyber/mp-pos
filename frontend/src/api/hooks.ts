import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import {
  Carrier,
  Category,
  ClearancePressureResponse,
  CompatibilityResponse,
  Customer,
  HomeSummary,
  InventoryAlertsResponse,
  InvoiceTrack,
  InvoiceType,
  PartsUsageReport,
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
  ProductSerial,
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
  category_id: number;
  category_name: string;
  category_code: string;
  list_price: string;
  weighted_avg_cost: string;
  requires_serial: boolean;
  is_secondhand: boolean;
  stock_by_warehouse: Record<string, number>;
  stock_total: number;
}
export interface StockMatrixResponse {
  warehouses: StockMatrixWarehouse[];
  products: StockMatrixProduct[];
}
export interface StockMatrixFilter {
  warehouseIds: number[];
  search?: string;
  categoryIds?: number[];
  inStockOnly?: boolean;
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
    mutationFn: (payload: Partial<Product> & { id?: number }) => {
      const { id, ...body } = payload;
      const method = id ? "PATCH" : "POST";
      const url = id ? `/products/${id}/` : "/products/";
      return api<Product>(url, { method, body: JSON.stringify(body) });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["products"] });
    },
  });
}

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
    mutationFn: (payload: Partial<PurchaseOrder>) =>
      api<PurchaseOrder>("/purchase-orders/", {
        method: "POST",
        body: JSON.stringify(payload),
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
    mutationFn: (payload: Partial<SalesOrder>) =>
      api<SalesOrder>("/sales-orders/", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["sales-orders"] });
      qc.invalidateQueries({ queryKey: ["products"] });
      qc.invalidateQueries({ queryKey: ["serials"] });
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
  items: {
    original_item: number;
    qty: number;
    serial_ids?: number[];
  }[];
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
  serial_no: string;
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

export interface SerialHistory {
  serial: ProductSerial;
  acquisition: SerialHistoryAcquisition | null;
  movements: SerialHistoryMovement[];
  sales: SerialHistorySale[];
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

export interface TenantSettings {
  id: number;
  name?: string;
  code?: string;
  repair_warranty_days: number;
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
