import { api } from "./client";
import type { ComboOption } from "@/components/ComboBox";
import type {
  Carrier,
  Category,
  Customer,
  Paginated,
  Product,
  ProductSerial,
  PurchaseOrderCategory,
  SalesPerson,
  SimCard,
  Supplier,
  TelecomPlan,
  Warehouse,
} from "./types";

const LIMIT = 20;

function qs(params: Record<string, string | number | boolean | undefined>) {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== "" && v !== null) u.set(k, String(v));
  }
  return u.toString();
}

async function fetchPaginated<T>(path: string): Promise<T[]> {
  const d = await api<Paginated<T>>(path);
  return d.results;
}

export async function searchProducts(
  query: string,
  opts?: { activeOnly?: boolean },
): Promise<ComboOption<Product>[]> {
  const data = await fetchPaginated<Product>(
    `/products/?${qs({
      search: query,
      page_size: LIMIT,
      is_active: opts?.activeOnly ? "true" : undefined,
    })}`,
  );
  return data.map((p) => ({
    id: p.id,
    label: p.name,
    secondary: [p.sku, p.category_name].filter(Boolean).join(" / "),
    payload: p,
  }));
}

export async function searchCustomers(
  query: string,
): Promise<ComboOption<Customer>[]> {
  const data = await fetchPaginated<Customer>(
    `/customers/?${qs({ search: query, page_size: LIMIT })}`,
  );
  return data.map((c) => ({
    id: c.id,
    label: c.name || c.phone || `#${c.id}`,
    secondary: [c.phone, c.is_member ? "會員" : null]
      .filter(Boolean)
      .join(" / "),
    payload: c,
  }));
}

export async function searchSuppliers(
  query: string,
): Promise<ComboOption<Supplier>[]> {
  const data = await fetchPaginated<Supplier>(
    `/suppliers/?${qs({ search: query, page_size: LIMIT })}`,
  );
  return data.map((s) => ({
    id: s.id,
    label: s.name,
    secondary: s.code,
    payload: s,
  }));
}

export async function searchWarehouses(
  query: string,
): Promise<ComboOption<Warehouse>[]> {
  const data = await fetchPaginated<Warehouse>(
    `/warehouses/?${qs({ search: query, page_size: LIMIT })}`,
  );
  return data.map((w) => ({
    id: w.id,
    label: w.name,
    secondary: w.code,
    payload: w,
  }));
}

export async function searchSalesPersons(
  query: string,
): Promise<ComboOption<SalesPerson>[]> {
  const data = await fetchPaginated<SalesPerson>(
    `/sales-persons/?${qs({ search: query, page_size: LIMIT })}`,
  );
  return data.map((sp) => ({
    id: sp.id,
    label: sp.name,
    secondary: sp.code,
    payload: sp,
  }));
}

export async function searchCarriers(
  query: string,
): Promise<ComboOption<Carrier>[]> {
  const data = await fetchPaginated<Carrier>(
    `/carriers/?${qs({ search: query, page_size: LIMIT })}`,
  );
  return data.map((c) => ({
    id: c.id,
    label: c.name,
    secondary: c.code,
    payload: c,
  }));
}

export async function searchPurchaseOrderCategories(
  query: string,
): Promise<ComboOption<PurchaseOrderCategory>[]> {
  const data = await fetchPaginated<PurchaseOrderCategory>(
    `/purchase-order-categories/?${qs({
      search: query,
      page_size: LIMIT,
      is_active: "true",
    })}`,
  );
  return data.map((c) => ({
    id: c.id,
    label: c.name,
    secondary: c.code,
    payload: c,
  }));
}

export async function searchCategories(
  query: string,
): Promise<ComboOption<Category>[]> {
  const data = await fetchPaginated<Category>(
    `/categories/?${qs({ search: query, page_size: LIMIT })}`,
  );
  return data.map((c) => ({
    id: c.id,
    label: c.name,
    secondary: c.code,
    payload: c,
  }));
}

export async function searchTelecomPlans(
  query: string,
  opts?: { activeOnly?: boolean },
): Promise<ComboOption<TelecomPlan>[]> {
  const data = await fetchPaginated<TelecomPlan>(
    `/telecom-plans/?${qs({
      search: query,
      page_size: LIMIT,
      is_active: opts?.activeOnly ? "true" : undefined,
    })}`,
  );
  return data.map((p) => ({
    id: p.id,
    label: p.name,
    secondary: `${p.carrier_code} ${p.monthly_fee}/${p.contract_months}月 ${p.kind_label}`,
    payload: p,
  }));
}

export async function searchSimCards(
  query: string,
  opts?: { vendor?: number; inStockOnly?: boolean },
): Promise<ComboOption<SimCard>[]> {
  const data = await fetchPaginated<SimCard>(
    `/sim-cards/?${qs({
      search: query,
      page_size: LIMIT,
      vendor: opts?.vendor,
      status: opts?.inStockOnly ? "in_stock" : undefined,
    })}`,
  );
  return data.map((c) => ({
    id: c.id,
    label: c.card_no,
    secondary: `${c.vendor_code} / ${c.status_label}`,
    payload: c,
  }));
}

export async function searchInStockSerials(
  query: string,
  opts: { product: number; warehouse: number },
): Promise<ComboOption<ProductSerial>[]> {
  const data = await fetchPaginated<ProductSerial>(
    `/serials/?${qs({
      search: query,
      page_size: LIMIT,
      status: "in_stock",
      product: opts.product,
      warehouse: opts.warehouse,
    })}`,
  );
  return data.map((s) => ({
    id: s.id,
    label: s.serial_no,
    secondary: s.product_name,
    payload: s,
  }));
}
