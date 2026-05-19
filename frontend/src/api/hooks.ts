import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import {
  Carrier,
  Category,
  Customer,
  InvoiceTrack,
  InvoiceType,
  Paginated,
  PaymentMethod,
  Product,
  ProductSerial,
  PurchaseOrder,
  SalesOrder,
  SalesPerson,
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

export interface DateRangeFilter {
  from?: string;
  to?: string;
}

export interface SalesOrdersFilter extends DateRangeFilter {
  customer?: number;
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
    ],
    queryFn: () =>
      list<SalesOrder>(
        `/sales-orders/${buildQS({
          doc_date__gte: filter?.from,
          doc_date__lte: filter?.to,
          customer: filter?.customer,
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
}) => {
  const qs = new URLSearchParams();
  qs.set("page_size", "100");
  if (params?.doc_date_gte) qs.set("doc_date__gte", params.doc_date_gte);
  if (params?.doc_date_lte) qs.set("doc_date__lte", params.doc_date_lte);
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
