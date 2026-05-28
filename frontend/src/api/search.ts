import { api } from "./client";
import type { ComboOption } from "@/components/ComboBox";
import type {
  Carrier,
  Category,
  Customer,
  Member,
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
  opts?: {
    activeOnly?: boolean;
    /** 只列中古機(廠商收購中古用) */
    secondhandOnly?: boolean;
    /** 排除中古機(一般進貨單用) */
    excludeSecondhand?: boolean;
    /** 只列有庫存的(調撥用,排除零庫存) */
    inStockOnly?: boolean;
    /** 庫存以此倉計(搭配 inStockOnly;調撥帶來源倉) */
    warehouseId?: number | "";
    /** 只列主機 (accessory_type=none),機型配件挑相容主機用 */
    hostOnly?: boolean;
  },
): Promise<ComboOption<Product>[]> {
  const warehouseParam =
    opts?.warehouseId !== undefined && opts.warehouseId !== ""
      ? (opts.warehouseId as number)
      : undefined;
  const data = await fetchPaginated<Product>(
    `/products/?${qs({
      search: query,
      page_size: LIMIT,
      is_active: opts?.activeOnly ? "true" : undefined,
      is_secondhand: opts?.secondhandOnly
        ? "true"
        : opts?.excludeSecondhand
          ? "false"
          : undefined,
      in_stock_only: opts?.inStockOnly ? "true" : undefined,
      warehouse: warehouseParam,
      host_only: opts?.hostOnly ? "true" : undefined,
    })}`,
  );
  return data.map((p) => ({
    id: p.id,
    label: p.name,
    // 主機搜尋時 secondary 顯示「狀態 · SKU」,使用者能一眼看出該機型狀態
    secondary: opts?.hostOnly
      ? [lifecycleLabel(p.lifecycle_status), p.sku]
          .filter(Boolean)
          .join(" · ")
      : [p.sku, p.category_name].filter(Boolean).join(" / "),
    payload: p,
  }));
}

function lifecycleLabel(s?: string): string {
  switch (s) {
    case "active":
      return "主力現貨";
    case "replacing":
      return "即將換代";
    case "discontinued":
      return "停產下架";
    case "clearance":
      return "清倉處理";
    default:
      return "";
  }
}

export interface PhoneModelSearchResult {
  model_key: string;
  model_name: string;
  sku_count: number;
  total_stock: number;
  any_lifecycle_status: string;
}

/** 機型清單搜尋(配件挑相容機型用)。
 * 不走 ComboOption 因為 id 需是 string(model_key);PhoneModelPicker 直接吃這個陣列。
 */
export async function searchPhoneModels(
  query: string,
): Promise<PhoneModelSearchResult[]> {
  const url = `/products/phone-models/?${qs({ search: query })}`;
  const list = await api<
    {
      model_key: string;
      model_name: string;
      sku_count: number;
      total_stock: number;
      any_lifecycle_status: string;
      any_lifecycle_status_label: string;
      sample_sku_id: number;
      sample_sku_name: string;
    }[]
  >(url);
  return list.map((m) => ({
    model_key: m.model_key,
    model_name: m.model_name,
    sku_count: m.sku_count,
    total_stock: m.total_stock,
    any_lifecycle_status: m.any_lifecycle_status,
  }));
}

/**
 * 銷貨頁專用商品搜尋:
 * - 一般輸入 → 走商品搜尋(品名 / 品號 / 條碼 / 規格 / 類別,後端已涵蓋 IMEI)
 * - 若輸入像 IMEI(>=6 個英數字)→ 平行查序號,把命中的序號掛到對應商品上
 *   選到此商品時前端可自動把這支序號塞進該行,不用使用者再挑
 */
export interface SalesProductHit extends Product {
  matched_serial?: {
    id: number;
    serial_no: string;
    custom_unit_price?: string | null;
  };
}

export async function searchProductsForSales(
  query: string,
  opts?: { warehouseId?: number | "" },
): Promise<ComboOption<SalesProductHit>[]> {
  const q = query.trim();
  if (!q) return [];

  // 出貨倉:有指定的話,庫存以該倉計;否則跨倉合計
  const warehouseParam =
    opts?.warehouseId !== undefined && opts.warehouseId !== ""
      ? (opts.warehouseId as number)
      : undefined;

  // 後端 search_fields 已包含 serials__serial_no,商品搜尋自然命中 IMEI 對應的商品
  // sales_pickable=true 只列「有庫存 OR 虛擬商品」,排除 0 庫存的實體商品
  const productsP = fetchPaginated<Product>(
    `/products/?${qs({
      search: q,
      page_size: LIMIT,
      is_active: "true",
      sales_pickable: "true",
      warehouse: warehouseParam,
    })}`,
  );

  // IMEI 偵測:>=6 字、含數字 → 平行查 in_stock 的序號,知道是哪一支命中
  const isImeiLike = /^[\w-]{6,}$/.test(q) && /\d/.test(q);
  const serialsP: Promise<ProductSerial[]> = isImeiLike
    ? fetchPaginated<ProductSerial>(
        `/serials/?${qs({
          search: q,
          status: "in_stock",
          page_size: 10,
          warehouse: warehouseParam,
        })}`,
      )
    : Promise.resolve([]);

  const [products, serials] = await Promise.all([productsP, serialsP]);

  // 為每個商品挑出命中的序號(若有)
  const result: ComboOption<SalesProductHit>[] = products.map((p) => {
    const matched = serials.find((s) => s.product === p.id);
    const hit: SalesProductHit = matched
      ? {
          ...p,
          matched_serial: {
            id: matched.id,
            serial_no: matched.serial_no,
            custom_unit_price: matched.custom_unit_price,
          },
        }
      : (p as SalesProductHit);
    const stockLabel = p.is_virtual ? "" : `在庫 ${p.stock_qty}`;
    return {
      id: p.id,
      label: p.name,
      secondary: matched
        ? [
            `IMEI ${matched.serial_no}`,
            p.sku,
            stockLabel,
          ]
            .filter(Boolean)
            .join(" · ")
        : [p.sku, p.category_name, stockLabel]
            .filter(Boolean)
            .join(" / "),
      payload: hit,
    };
  });

  // 把帶 matched_serial 的選項排到最前面(IMEI 命中通常是使用者意圖)
  result.sort((a, b) => {
    const am = a.payload?.matched_serial ? 1 : 0;
    const bm = b.payload?.matched_serial ? 1 : 0;
    return bm - am;
  });

  return result;
}

export async function searchSecondhandProducts(
  query: string,
): Promise<ComboOption<Product>[]> {
  const data = await fetchPaginated<Product>(
    `/products/?${qs({
      search: query,
      page_size: LIMIT,
      is_active: "true",
      is_secondhand: "true",
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
    secondary: [c.phone, c.kind_label].filter(Boolean).join(" / "),
    payload: c,
  }));
}

// 銷貨單「會員」欄位用:從獨立 Member 主檔搜尋
export async function searchMembers(
  query: string,
): Promise<ComboOption<Member>[]> {
  const data = await fetchPaginated<Member>(
    `/members/?${qs({ search: query, page_size: LIMIT })}`,
  );
  return data.map((m) => ({
    id: m.id,
    label: m.name || m.phone || `#${m.id}`,
    secondary: [m.phone, m.code].filter(Boolean).join(" / "),
    payload: m,
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
  return data.map((s) => {
    const parts: string[] = [];
    if (s.product_is_secondhand) {
      if (s.condition_grade) parts.push(`${s.condition_grade} 級`);
      if (s.custom_unit_price)
        parts.push(`售價 ${Number(s.custom_unit_price).toLocaleString()}`);
      if (s.battery_health != null) parts.push(`電池 ${s.battery_health}%`);
    }
    return {
      id: s.id,
      label: s.serial_no,
      secondary: parts.length > 0 ? parts.join(" · ") : s.product_name,
      payload: s,
    };
  });
}
