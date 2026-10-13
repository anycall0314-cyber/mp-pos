// 批發(賣家那一半)的資料存取。規則在伺服器 backend/apps/trade/。
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import type { ScanFound, TradeOrder, UnitRule } from "@/lib/trade";

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
  owed: number;
  received: number;
  due: number;
  credit: number;
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
  held_by: { order: number; order_no: string; partner: string } | null;
}

export interface TradeProductRow {
  product: number;
  sku: string;
  name: string;
  category: string;
  list_price: number;
  requires_serial: boolean;
  is_listed: boolean;
  price: number | null;
  available: number;
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
  });

export const useTradeOrders = (state: "open" | "closed" | "all", q: string, limit: number) =>
  useQuery({
    queryKey: ["trade-orders", state, q, limit],
    queryFn: () => api<Page<TradeOrder>>(`/trade/orders/?${query({ state, q, limit })}`),
    placeholderData: keepPreviousData,
    // 同行隨時會下單、取消:待出貨那一頁每半分鐘看一次
    refetchInterval: state === "open" ? 30_000 : false,
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

export const useTradeUnits = (state: string, q: string, warehouse: number | "", limit: number) =>
  useQuery({
    queryKey: ["trade-units", state, q, warehouse, limit],
    queryFn: () => api<Page<TradeUnitRow>>(`/trade/units/?${query({ state, q, warehouse, limit })}`),
    placeholderData: keepPreviousData,
  });

export function useTradeUnitsDo() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { list: { serial: number; price?: number }[] } | { unlist: number[] }): Promise<{ listed?: number; unlisted?: number }> =>
      "list" in vars
        ? post("/trade/units/list/", { rows: vars.list })
        : post("/trade/units/unlist/", { serials: vars.unlist }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["trade-units"] }),
  });
}

export const useTradeProducts = (state: "listed" | "all", q: string, limit: number, enabled = true) =>
  useQuery({
    queryKey: ["trade-products", state, q, limit],
    queryFn: () => api<Page<TradeProductRow>>(`/trade/products/?${query({ state, q, limit })}`),
    placeholderData: keepPreviousData,
    enabled,
  });

export function useTradeProductsDo() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (rows: { product: number; is_listed?: boolean; price?: number | null }[]) =>
      post<{ changed: number }>("/trade/products/", { rows }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["trade-products"] }),
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
