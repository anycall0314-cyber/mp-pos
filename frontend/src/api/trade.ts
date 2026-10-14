// 批發(賣家那一半)的資料存取。規則在伺服器 backend/apps/trade/。
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import type { PriceCell, PriceRule, ScanFound, TradeOrder, UnitRule } from "@/lib/trade";

export interface TradeSetting {
  is_open: boolean;
  unit_rule: UnitRule;
  unit_value: number;
  auto_list_units: boolean;
  units_to_all: boolean;
  auto_accept: boolean;
  show_qty: boolean;
  default_percent: number;
  default_terms: string;
  pay_note: string;
  contact: string;
  rules: { key: UnitRule; label: string }[];
  terms: string[];
}

export interface TradePartner {
  id: number;
  name: string;
  kind: "platform" | "external";
  status: "guest" | "approved" | "blocked";
  status_label: string;
  percent: number;
  terms: string;
  note: string;
  /** 對外的同行:怎麼聯絡、金鑰的前幾碼(原文只在發的那一次看得到)、最後一次用 */
  contact?: string;
  key_hint?: string;
  key_used_at?: string;
  owed: number;
  received: number;
  due: number;
  credit: number;
  /** 報價連結(給沒用這套 POS 的同行用手機看現在的價);沒有是 null。`path` 要接在這個站的網址後面 */
  quote: { path: string; on: boolean; count: number; opened_at: string } | null;
}

export interface TradeInvite {
  id: number;
  hint: string;
  percent: number;
  terms: string;
  expires_at: string;
  /** 只有剛發的那一次有 */
  code?: string;
}

export interface TradeUnitRow {
  serial: number;
  serial_no: string;
  imei: string;
  sn: string;
  product: number;
  name: string;
  sku: string;
  warehouse: number | null;
  warehouse_name: string;
  grade: string;
  battery: number | null;
  note: string;
  retail_price: number;
  auto_price: number | null;
  is_listed: boolean;
  price: number | null;
  /** 獨立定價(價目怎麼改都不動它) */
  own: boolean;
  /** 價目表上符合它的最細的那一格 */
  rule: number | null;
  held_by: { order: number; order_no: string; partner: string } | null;
}

export interface TradeProductRow {
  product: number;
  sku: string;
  name: string;
  category: string;
  brand: string;
  /** 商品本身的機型與它適用的機型 */
  models: string[];
  list_price: number;
  requires_serial: boolean;
  is_listed: boolean;
  /** 固定價 / 門市價的幾 %(每個同行一樣);都是 null = 照同行折數 */
  price: number | null;
  percent: number | null;
  available: number;
}

export interface GoodsFacet {
  id: number;
  name: string;
  count: number;
}

export interface GoodsQuery {
  state: "listed" | "unlisted" | "all";
  q: string;
  category: number[];
  brand: number[];
  model: number[];
  priced: "" | "fixed" | "percent" | "none";
  fresh: 0 | 7 | 30;
}

export interface TradeLedger {
  partner: TradePartner;
  orders: { id: number; no: string; placed_at: string; owed: number; paid: number; due: number; payment_status: string }[];
  payments: { id: number; amount: number; received_on: string; method: string; note: string; is_void: boolean; by: string }[];
}

interface Page<T> {
  total: number;
  results: T[];
}

const post = <T,>(path: string, body: object = {}) => api<T>(path, { method: "POST", body: JSON.stringify(body) });
const query = (params: Record<string, string | number | undefined>) => {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== "") q.set(k, String(v));
  return q.toString();
};

/** 庫存會跟著動的動作做完之後,別頁看到的數量要重抓 */
const STOCK_KEYS = ["products", "serials", "stock-balances", "serial-list", "stock-flow", "stock-moves", "sales-orders"];

export const useTradeSetting = (enabled = true) =>
  useQuery({ queryKey: ["trade-setting"], queryFn: () => api<TradeSetting>("/trade/settings/"), enabled, retry: false });

export function useSaveTradeSetting() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Partial<TradeSetting>) => post<TradeSetting>("/trade/settings/", body),
    onSuccess: (data) => {
      qc.setQueryData(["trade-setting"], data);
      qc.invalidateQueries({ queryKey: ["trade-units"] });
    },
  });
}

export const useTradeSummary = (enabled = true) =>
  useQuery({
    queryKey: ["trade-summary"],
    queryFn: () => api<{ pending: number; to_ship: number }>("/trade/summary/"),
    enabled,
    refetchInterval: 60_000,
    staleTime: 0,
  });

export const useTradeOrders = (state: "open" | "closed" | "all", q: string, limit: number) =>
  useQuery({
    queryKey: ["trade-orders", state, q, limit],
    queryFn: () => api<Page<TradeOrder>>(`/trade/orders/?${query({ state, q, limit })}`),
    placeholderData: keepPreviousData,
    // 同行隨時會下單、取消:待出貨那一頁每半分鐘看一次,而且每次切回來都重抓(全站預設 30 秒內不重抓,新單會晚出現)
    refetchInterval: state === "open" ? 30_000 : false,
    staleTime: 0,
    refetchOnMount: "always",
  });

/** 批發單上的每一個動作(接單、拒絕、不出、出貨、取消出貨):伺服器回整張單現在的樣子 */
export function useTradeOrderDo() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ path, body }: { path: string; body?: object }) => post<TradeOrder>(`/trade/${path}`, body),
    onSuccess: (_data, vars) => {
      for (const key of ["trade-orders", "trade-summary", "trade-units", "trade-partners", "trade-ledger"])
        qc.invalidateQueries({ queryKey: [key] });
      if (vars.path.includes("ship")) for (const key of STOCK_KEYS) qc.invalidateQueries({ queryKey: [key] });
    },
  });
}

export const scanTradeUnit = (code: string, warehouse: number | "") => post<ScanFound>("/trade/scan/", { code, warehouse });

/**
 * `product` 有給 = 只看一個型號(那個型號的每一台一次拿回來,畫面自己篩)。
 * **不留上一份**(沒有 `keepPreviousData`):換門市 / 狀態的那一下如果還拿著上一份,「同價」會勾到上一間門市的那一群、把它們的價改掉(複審 P0)。
 */
export const useTradeUnits = (state: string, q: string, warehouse: number | "", limit: number, product?: number) =>
  useQuery({
    queryKey: ["trade-units", state, q, warehouse, limit, product ?? 0],
    // 只看一個型號的時候另外帶它的價目表
    queryFn: () => api<Page<TradeUnitRow> & { rules?: PriceRule[] }>(`/trade/units/?${query({ state, q, warehouse, limit, product })}`),
  });

export interface TradeUnitModelRow {
  product: number;
  name: string;
  sku: string;
  total: number;
  unlisted: number;
  listed: number;
  held: number;
  /** 上架中的那幾台賣多少到多少;其中獨立定價的幾台 */
  price_low: number | null;
  price_high: number | null;
  own: number;
  rules: PriceRule[];
}

export interface TradePriceChangeRow {
  id: number;
  at: string;
  by: string;
  product: number;
  name: string;
  what: "rule" | "price" | "list" | "unlist" | "drop";
  what_label: string;
  scope: string;
  count: number;
  old_low: number | null;
  old_high: number | null;
  new_low: number | null;
  new_high: number | null;
  /** 有打序號查的時候:那一台從多少變多少 */
  units: { serial_no: string; old_price: number | null; new_price: number | null }[];
}

/** 改價紀錄(一個型號;`q` = 序號裡的字) */
export const useTradePriceChanges = (product: number | undefined, q: string, enabled: boolean) =>
  useQuery({
    queryKey: ["trade-units", "changes", product ?? 0, q],
    queryFn: () => api<Page<TradePriceChangeRow>>(`/trade/units/changes/?${query({ product, q, limit: 100 })}`),
    enabled,
  });

/** 中古機照型號算:每個型號在庫幾台、沒上架 / 上架中 / 被訂走各幾台 */
export const useTradeUnitModels = (warehouse: number | "") =>
  useQuery({
    queryKey: ["trade-units", "models", warehouse],
    queryFn: () => api<{ results: TradeUnitModelRow[] }>(`/trade/units/models/?${query({ warehouse })}`),
    placeholderData: keepPreviousData,
  });

type UnitsDo =
  | { list: { serial: number; price?: number; own?: boolean }[]; cell?: PriceCell; cell_price?: number; seen?: { product?: number; warehouse?: number } }
  | { unlist: number[]; seen?: { product?: number; warehouse?: number } }
  | { cells: { id: number; price: number }[] }
  | { drop: number };

export function useTradeUnitsDo() {
  const qc = useQueryClient();
  return useMutation({
    // `seen` = 畫面現在看的是哪個型號 / 哪一間門市:伺服器照它核對每一台,對不上整批不動
    mutationFn: (vars: UnitsDo): Promise<{ listed?: number; unlisted?: number; changed?: number }> => {
      if ("list" in vars) return post("/trade/units/list/", { rows: vars.list, cell: vars.cell, cell_price: vars.cell_price, ...vars.seen });
      if ("unlist" in vars) return post("/trade/units/unlist/", { serials: vars.unlist, ...vars.seen });
      if ("cells" in vars) return post("/trade/units/rules/", { cells: vars.cells });
      return post(`/trade/units/rules/${vars.drop}/drop/`);
    },
    // 沒成功也重新拿:多半是清單上有一台剛被賣掉,重新拿它就不在清單上了
    onSettled: () => qc.invalidateQueries({ queryKey: ["trade-units"] }),
  });
}

/** 批發品:篩出來的全部一次拿回來(最多 2000)。**不留上一份**:換篩選那一下手上的不是現在這一群,不能拿來勾、拿來送 */
export const useTradeProducts = (f: GoodsQuery, enabled = true) =>
  useQuery({
    queryKey: ["trade-products", f],
    queryFn: () =>
      api<Page<TradeProductRow> & { facets: { categories: GoodsFacet[]; brands: GoodsFacet[]; models: GoodsFacet[] } }>(
        `/trade/products/?${query({ state: f.state, q: f.q, priced: f.priced, fresh: f.fresh || undefined, limit: 2000,
          category: f.category.join(","), brand: f.brand.join(","), model: f.model.join(",") })}`),
    enabled,
  });

export function useTradeProductsDo() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (rows: { product: number; is_listed?: boolean; price?: number | null; percent?: number | null }[]) =>
      post<{ changed: number }>("/trade/products/", { rows }),
    // 沒成功也重新拿(多半是清單上有一個剛被別人改了)
    onSettled: () => qc.invalidateQueries({ queryKey: ["trade-products"] }),
  });
}

export const useTradePartners = (enabled = true) =>
  useQuery({
    queryKey: ["trade-partners"],
    queryFn: () => api<{ partners: TradePartner[]; invites: TradeInvite[] }>("/trade/partners/"),
    enabled,
  });

export function useTradePartnerDo() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: number; body: Partial<Pick<TradePartner, "status" | "percent" | "terms" | "note">> }) =>
      post<TradePartner>(`/trade/partners/${id}/`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["trade-partners"] }),
  });
}

export function useTradeInvite() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { percent?: number; terms?: string }) => post<TradeInvite & { code: string }>("/trade/invites/", body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["trade-partners"] }),
  });
}

export const useTradeLedger = (partner: number | null) =>
  useQuery({
    queryKey: ["trade-ledger", partner],
    queryFn: () => api<TradeLedger>(`/trade/partners/${partner}/ledger/`),
    enabled: partner !== null,
  });

export function useTradePaymentDo() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (
      vars:
        | { partner: number; amount: number; request_key: string; received_on?: string; method?: string; note?: string }
        | { void: number },
    ) => ("void" in vars ? post<TradeLedger>(`/trade/payments/${vars.void}/void/`) : post<TradeLedger>("/trade/payments/", vars)),
    onSuccess: (data) => {
      qc.setQueryData(["trade-ledger", data.partner.id], data);
      for (const key of ["trade-partners", "trade-orders"]) qc.invalidateQueries({ queryKey: [key] });
    },
  });
}

/** 買家這一側:輸入同行給的往來代碼(管理員)。成功之後每一間門市自動開通,叫貨串接與叫貨頁要重抓。 */
export function useJoinDealer() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (code: string) => post<{ vendor: string; name: string }>("/vendor-orders/join/", { code }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["vendor-links"] }),
  });
}

/** 剛發的金鑰:原文只在這一次的回應裡(畫面收起來就沒有了)。`base` = 對外的網址 */
export interface IssuedKey {
  partner: TradePartner;
  key: string;
  base: string;
}

/** 建一個對外的同行並發金鑰 / 換一把(舊的立刻失效)。只有管理員。 */
export function useTradeKeyDo() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { name: string; contact: string } | { rotate: number }) =>
      "rotate" in vars ? post<IssuedKey>(`/trade/partners/${vars.rotate}/key/`) : post<IssuedKey>("/trade/partners/external/", vars),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["trade-partners"] }),
  });
}

/** 報價連結:開(第一次開會建一條)、關、換一條(舊的立刻不能看) */
export function useTradeQuoteDo() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { partner: number; do: "on" | "off" | "new" }) => post<{ partner: TradePartner }>(`/trade/partners/${vars.partner}/quote/`, { do: vars.do }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["trade-partners"] }),
  });
}

export interface VendorStatement {
  orders: { order_no: string; ordered_at: string; shipped_amount: number; paid_amount: number; due_amount: number; payment_method: string; payment_status: string }[];
  totals: { shipped: number; paid: number; due: number };
  credit: number;
}

/** 買家這一側:跟這家賣家的對帳單(賣家算的)。按了才問。 */
export const useVendorStatement = (warehouse: number | null, vendor: string | null, enabled: boolean) =>
  useQuery({
    queryKey: ["vendor-statement", warehouse, vendor],
    queryFn: () => api<VendorStatement>(`/vendor-orders/statement/?${query({ warehouse: warehouse ?? "", vendor: vendor ?? "" })}`),
    enabled: enabled && warehouse !== null && !!vendor,
    gcTime: 0,
    retry: false,
  });
