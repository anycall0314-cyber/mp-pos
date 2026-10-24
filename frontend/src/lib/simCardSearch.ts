// SIM 卡清單的搜尋與狀態篩選(全站檢視 R04:以前搜尋框打字沒有作用)。跑法:npm test。
import type { SimCard, SimCardStatus } from "@/api/types";

/** 狀態的中文(新增 / 編輯的下拉與清單上面的篩選共用這一份) */
export const SIM_STATUSES: { value: SimCardStatus; label: string }[] = [
  { value: "in_stock", label: "在庫" },
  { value: "issued", label: "已出卡" },
  { value: "activated", label: "已開通" },
  { value: "returned", label: "退回廠商" },
  { value: "void", label: "作廢" },
];

/** 搜尋框寫的支援欄位 */
export const SIM_SEARCH_PLACEHOLDER = "搜尋 卡號 / 廠商";

const plain = (s: string) => s.replace(/\s+/g, "").toLowerCase();

/** 卡號(完整或一段,不管空白)、廠商名稱或代碼;狀態空的 = 全部。兩個條件同時成立才列。 */
export function filterSimCards(rows: SimCard[], query: string, status: SimCardStatus | ""): SimCard[] {
  const q = plain(query);
  return rows.filter((r) => {
    if (status && r.status !== status) return false;
    if (!q) return true;
    return plain(r.card_no).includes(q) || plain(r.vendor_name).includes(q) || plain(r.vendor_code).includes(q);
  });
}
