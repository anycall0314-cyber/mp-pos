/**
 * 門號合約到期的名單與聯絡紀錄。規則在後端 `apps/sales/contracts.py`:
 * 一筆合約 = 一行有方案、有到期日的銷貨明細;同一個門號在另一張單上有更新的合約 = 已續約;作廢、被退掉的不算。
 */
import { api } from "./client";

/** open 還沒處理 / contacted 已聯絡 / declined 不續約 / renewed 已續約(同一個門號有更新的合約) */
export type ContractState = "open" | "contacted" | "declined" | "renewed";
/** 名單的四個分頁。pending = 還沒處理,而且快到期或已經過期 */
export type ContractTab = "pending" | "contacted" | "declined" | "renewed";
export type FollowStatus = "contacted" | "declined";

export interface ContractRow {
  /** 銷貨明細的編號 */
  id: number;
  msisdn: string;
  contract_end: string;
  /** 負的 = 已經過期幾天 */
  days_left: number;
  activation_date: string | null;
  contract_months: number | null;
  plan_name: string;
  plan_kind: string;
  plan_kind_label: string;
  carrier_name: string;
  so_id: number;
  so_no: string;
  doc_date: string;
  warehouse_name: string;
  sales_person_name: string;
  customer_name: string;
  customer_phone: string;
  member_name: string;
  member_phone: string;
  state: ContractState;
  /** 聯絡紀錄。status 空的 = 只記了備註(還沒聯絡上),這一筆仍然是還沒處理 */
  follow: { status: FollowStatus | ""; note: string; by: string; at: string } | null;
}

export interface ContractList {
  today: string;
  remind_months: number;
  /** 待聯絡預設看到哪一天為止(今天 + 設定的月數) */
  remind_until: string;
  until: string | null;
  counts: Record<ContractTab | "overdue", number>;
  total: number;
  /** 這一頁最後一列後面還有沒有人 / 第一列前面還有沒有人 */
  has_more: boolean;
  has_prev: boolean;
  page_size: number;
  results: ContractRow[];
}

export interface ContractQuery {
  state: ContractTab;
  /** 待聯絡看到多遠:今天起幾個月內("all" = 不限;沒給 = 照系統設定) */
  months?: number | "all";
  warehouse?: number | "";
  carrier?: number | "";
  search?: string;
  /**
   * 翻頁:接在哪一列後面 / 排在哪一列前面(`cursorOf(那一列)`)。都沒給 = 最前面那一頁。
   * 不用頁碼:名單上的人被標掉(自己、別的店員)就離開這個分頁、後面的往前遞補,用頁碼翻會跳過遞補上來的人
   */
  after?: string;
  before?: string;
}

export function listContracts(q: ContractQuery) {
  const params = new URLSearchParams({ state: q.state });
  if (q.months === "all") params.set("until", "all");
  else if (q.months) params.set("months", String(q.months));
  if (q.warehouse) params.set("warehouse", String(q.warehouse));
  if (q.carrier) params.set("carrier", String(q.carrier));
  if (q.search?.trim()) params.set("search", q.search.trim());
  if (q.after) params.set("after", q.after);
  else if (q.before) params.set("before", q.before);
  return api<ContractList>(`/telecom-contracts/?${params}`);
}

/** status 空字串 = 還沒聯絡上(回到或留在待聯絡),備註照送來的存;兩個都空的 = 整筆紀錄拿掉。回這一筆現在的樣子 */
export const setContractFollowUp = (id: number, status: FollowStatus | "", note: string) =>
  api<ContractRow>(`/telecom-contracts/${id}/follow-up/`, {
    method: "POST",
    body: JSON.stringify({ status, note }),
  });
