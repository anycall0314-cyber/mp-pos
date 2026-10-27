// 員工帳號的權限:每個店員帳號一項一項勾(owner 2026-10-10)。
// 清單與判斷只有伺服器那一份(backend/apps/tenants/abilities.py),**真正擋的是伺服器**;
// 這裡只決定按鈕要不要出現(不讓人白按),以及員工帳號頁怎麼排。
export type AbilityKey =
  | "void_sales"
  | "sales_return"
  | "void_purchase"
  | "void_others"
  // 第二批
  | "edit_products"
  | "stock_count"
  | "release_returned"
  | "remember_barcode"
  | "purchase"
  | "secondhand_buy"
  | "cash_ops"
  | "view_business_daily"
  | "vendor_order"
  | "invoice_tracks"
  | "trade_sell"
  // 第三批:報表一張一個勾
  | "report_sales_daily"
  | "report_explore"
  | "report_parts"
  | "report_staff"
  | "report_products"
  | "report_commission"
  | "report_daily"
  | "report_activations"
  | "report_invoices"
  | "report_repairs";

export interface AbilityInfo {
  key: string;
  label: string;
  group: string;
  note: string;
}

/**
 * 這個帳號能不能做這一項。登入資料裡沒有這一格(還沒載入、伺服器比較舊)當成可以:
 * 按鈕照舊出現,真的不行伺服器會擋並講原因。只有明講「不可以」才收起來。
 */
export function can(
  user: { abilities?: Record<string, boolean> } | null | undefined,
  key: AbilityKey,
): boolean {
  return user?.abilities?.[key] !== false;
}

type Who = { abilities?: Record<string, boolean>; profile?: { role?: string } | null } | null | undefined;

/**
 * 看得到實際成本、實際毛利:只有管理員(公司管理員、平台管理員;跟 nav.ts 的 isManager 同一個意思)。
 * 其他人看業務員成本與業務員毛利(owner 2026-10-28)。真正擋的是伺服器(backend/apps/core/cost_access.py):
 * 店員的資料裡根本沒有實際成本,畫面只決定欄名與要不要留那一欄。
 */
export function seesActualCost(user: Who): boolean {
  const role = user?.profile?.role;
  return role === "tenant_admin" || role === "platform_admin";
}

/** 看得到進價(進貨單、進貨明細、叫貨單、上次進價):管理員,或有「進貨入庫」「廠商叫貨」其中一項(伺服器同一條)。 */
export function seesPurchasePrices(user: Who): boolean {
  return seesActualCost(user) || can(user, "purchase") || can(user, "vendor_order");
}

/** 員工帳號頁:照分類排,分類與項目都照伺服器給的順序。 */
export function groupAbilities<T extends AbilityInfo>(list: T[]): { group: string; items: T[] }[] {
  const groups: { group: string; items: T[] }[] = [];
  for (const item of list) {
    const last = groups.find((g) => g.group === item.group);
    if (last) last.items.push(item);
    else groups.push({ group: item.group, items: [item] });
  }
  return groups;
}
