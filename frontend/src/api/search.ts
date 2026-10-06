import { api } from "./client";
import type { ComboOption } from "@/components/ComboBox";
import { codesLabel, normalizeCode } from "@/lib/deviceCodes";
import { money } from "@/lib/money";
import type {
  Carrier,
  Category,
  Customer,
  Member,
  Paginated,
  Product,
  ProductSerial,
  PurchaseOrderCategory,
  ResolveCandidate,
  ResolveResult,
  SalesOrder,
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

/**
 * 一句叫法 → 可能是它的既有商品。零庫存與已停用的都會列出來,
 * 每筆附符合原因與差異。
 */
export async function resolveProducts(
  query: string,
  opts?: {
    supplierId?: number | "";
    warehouseId?: number | "";
    /** true=只找中古機;false=排除中古機;不給=不限 */
    secondhand?: boolean;
    barcode?: string;
    vendorSku?: string;
    limit?: number;
  },
): Promise<ResolveResult> {
  return api<ResolveResult>(
    `/products/resolve/?${qs({
      q: query,
      supplier: opts?.supplierId === "" ? undefined : opts?.supplierId,
      warehouse: opts?.warehouseId === "" ? undefined : opts?.warehouseId,
      is_secondhand:
        opts?.secondhand === undefined ? undefined : String(opts.secondhand),
      barcode: opts?.barcode,
      vendor_sku: opts?.vendorSku,
      limit: opts?.limit,
    })}`,
  );
}

/** 候選的一行說明:已停用 / 庫存 / 符合原因 / 差異 */
export function candidateSummary(c: ResolveCandidate): string {
  return [
    c.is_active ? "" : "已停用",
    `庫存 ${c.product.stock_qty ?? 0}`,
    c.reasons.join("、"),
    c.differences.join(";"),
  ]
    .filter(Boolean)
    .join(" / ");
}

/**
 * 進貨選商品用:先列共用比對的候選(換個寫法、用別名、零庫存、已停用都找得到),
 * 再補上原本的搜尋結果(品號 / 條碼片段)。同一商品只出現一次。
 * 已停用的看得到;一般店員不能選,管理員選了由呼叫端先確認恢復。
 */
export async function searchProductsForPurchase(
  query: string,
  opts?: {
    secondhand?: boolean;
    supplierId?: number | "";
    warehouseId?: number | "";
  },
): Promise<ComboOption<Product>[]> {
  const plain = searchProducts(query, {
    activeOnly: true,
    secondhandOnly: opts?.secondhand === true,
    excludeSecondhand: opts?.secondhand === false,
    warehouseId: opts?.warehouseId,
  });
  if (!query.trim()) return plain;
  const [resolved, rest] = await Promise.all([
    resolveProducts(query, { ...opts, limit: LIMIT }),
    plain,
  ]);
  const options: ComboOption<Product>[] = resolved.candidates.map((c) => ({
    id: c.product.id,
    label: c.product.name,
    secondary: candidateSummary(c),
    payload: c.product,
    disabled: !c.selectable && !c.can_restore,
  }));
  const seen = new Set(options.map((o) => o.id));
  return options.concat(rest.filter((o) => !seen.has(o.id)));
}

/** 恢復已停用的商品(限管理員);回傳恢復後的商品 */
export function restoreProduct(id: number): Promise<Product> {
  return api<Product>(`/products/${id}/restore/`, { method: "POST" });
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
    imei: string;
    sn: string;
    custom_unit_price?: string | null;
    /** 輸入的字跟這一台登記的碼完全相同(刷條碼刷到的就是這一台) */
    exact: boolean;
  };
}

/**
 * 刷到的碼是哪一台:只認「完全相同」(去空白 / 破折號、不分大小寫;IMEI、SN 都算)。
 * 整家公司一起找,不管在哪個門市、什麼狀態 —— 要先知道這個碼是不是只有一台、那一台現在在哪。
 * 通常 0 或 1 台;2 台以上 = 舊資料的碼去掉符號後撞在一起,不知道是哪一台。
 */
export async function findDevicesByCode(code: string): Promise<ProductSerial[]> {
  if (!normalizeCode(code)) return [];
  return fetchPaginated<ProductSerial>(
    `/serials/?${qs({ code: code.trim(), page_size: 10 })}`,
  );
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

  // 刷到的碼是哪一台:只認「完全相同」。
  // 同商品另一台的碼剛好「包含」這串字時,用包含比對自動掛會賣錯實機。
  // 不能拿下面那種「包含」比對來自動掛序號(見 findDevicesByCode)。
  // 對到兩台以上就不知道是哪一台,不自動掛。
  const exactP = findDevicesByCode(q);
  // 只記得一部分(例如 IMEI 末幾碼)時用「包含」找:>=6 字、含數字才找;
  // 而且那個商品只有一台符合才自動掛,兩台以上就讓人自己挑。
  const isImeiLike = /^[\w-]{6,}$/.test(q) && /\d/.test(q);
  const partialP: Promise<ProductSerial[]> = isImeiLike
    ? fetchPaginated<ProductSerial>(
        `/serials/?${qs({
          search: q,
          status: "in_stock",
          page_size: 10,
          warehouse: warehouseParam,
        })}`,
      )
    : Promise.resolve([]);

  const [products, exact, partial] = await Promise.all([
    productsP,
    exactP,
    partialP,
  ]);

  // 剛好只對到一台,而且那一台在庫、在這個出貨倉,才算「刷到這一台」
  const conflict = exact.length > 1;
  const only = exact.length === 1 ? exact[0] : undefined;
  const sellable =
    only &&
    only.status === "in_stock" &&
    (warehouseParam === undefined || only.warehouse === warehouseParam)
      ? only
      : undefined;

  // 為每個商品挑出命中的序號(若有)
  const result: ComboOption<SalesProductHit>[] = products.map((p) => {
    const exactHit = sellable && sellable.product === p.id ? sellable : undefined;
    // 碼完全相同的那一台(不管能不能賣)不再用「包含」去掛別台;碼重複時也不掛
    const partialHits =
      conflict || only ? [] : partial.filter((s) => s.product === p.id);
    const matched =
      exactHit ?? (partialHits.length === 1 ? partialHits[0] : undefined);
    const hit: SalesProductHit = matched
      ? {
          ...p,
          matched_serial: {
            id: matched.id,
            serial_no: matched.serial_no,
            imei: matched.imei,
            sn: matched.sn,
            custom_unit_price: matched.custom_unit_price,
            exact: !!exactHit,
          },
        }
      : (p as SalesProductHit);
    const stockLabel = p.is_virtual ? "" : `在庫 ${p.stock_qty}`;
    return {
      id: p.id,
      label: p.name,
      secondary: matched
        ? [
            codesLabel(matched),
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

  // 刷到某一台的排最前面,其次是只對到一部分的(命中序號通常是使用者意圖)
  const rank = (o: ComboOption<SalesProductHit>) =>
    o.payload?.matched_serial ? (o.payload.matched_serial.exact ? 2 : 1) : 0;
  result.sort((a, b) => rank(b) - rank(a));

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
        parts.push(`售價 ${money(s.custom_unit_price)}`);
      if (s.battery_health != null) parts.push(`電池 ${s.battery_health}%`);
    }
    // 主碼是 IMEI 時把 SN 也寫出來:刷 SN 找到的那一台才認得出來
    if (s.imei && s.sn) parts.unshift(`SN ${s.sn}`);
    return {
      id: s.id,
      label: s.serial_no,
      secondary: parts.length > 0 ? parts.join(" · ") : s.product_name,
      payload: s,
    };
  });
}

/**
 * 某商品在某門市「在庫」的每一台(工作台的序號小標籤用:全部列出來給人點)。
 * 後端一頁 50 筆,這裡一頁一頁拿完;最多拿 400 台。
 */
export async function fetchInStockSerials(
  product: number,
  warehouse: number,
): Promise<ProductSerial[]> {
  const out: ProductSerial[] = [];
  for (let page = 1; page <= 8; page++) {
    const d = await api<Paginated<ProductSerial>>(
      `/serials/?${qs({ status: "in_stock", product, warehouse, page })}`,
    );
    out.push(...d.results);
    if (!d.next) break;
  }
  return out;
}

// 銷退單「原銷貨單」欄位用:用單號 / 客戶 / 電話 / 發票號碼找未作廢的銷貨單
// (不載整頁清單,舊單也找得到)
export async function searchSalesOrdersForReturn(
  query: string,
): Promise<ComboOption<SalesOrder>[]> {
  const data = await fetchPaginated<SalesOrder>(
    `/sales-orders/?${qs({ search: query, is_void: false, page_size: LIMIT })}`,
  );
  return data.map((so) => ({
    id: so.id,
    label: so.no,
    secondary: [so.doc_date, so.customer_name || "(散客)"].join(" / "),
    payload: so,
  }));
}
