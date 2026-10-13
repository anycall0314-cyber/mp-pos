// 叫貨廠商「誰看得到」(平台管理):全部公司,或只給指定的公司。
// owner 2026-10-13:kcimos 的價目是手機玩家那個帳號的進價,「Kcimos只有手機玩家看得到沒錯」。
// 真正擋的是伺服器(backend/apps/vendor_orders/vendors.py 的 open_to);這裡只管平台那一頁怎麼顯示。

/** 清單上廠商名稱後面那一小段:只給哪幾家(代碼);名單空的要講清楚沒有人看得到。 */
export function audienceLabel(v: { is_private: boolean; only_for: string[] }): string {
  if (!v.is_private) return "";
  return v.only_for.length > 0 ? `只給 ${v.only_for.join("、")}` : "沒有公司看得到";
}

/** 表單上的提醒:選了「指定公司」卻一家都沒勾 = 沒有任何公司看得到(可以存,但要讓人知道)。 */
export function audienceProblem(isPrivate: boolean, companies: string[]): string {
  return isPrivate && companies.length === 0 ? "一家都沒勾:沒有公司看得到" : "";
}

/** 勾 / 取消一家公司(照勾的順序、不重複)。 */
export function toggleCompany(companies: string[], code: string, on: boolean): string[] {
  const rest = companies.filter((c) => c !== code);
  return on ? [...rest, code] : rest;
}
