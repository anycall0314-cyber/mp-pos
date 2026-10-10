// 廠商叫貨區「先選類別、再選廠商」在畫面這一側的規則。跑法:npm test。
// 名單(有哪些類別、哪些廠商、掛在哪些類別)是平台定的;這家門市開通了沒、店員能不能叫,是每家門市 × 每家廠商各自的設定。
// **類別只用來篩廠商**:同一家廠商掛幾個類別都是同一個入口、同一份購物車(換類別不會換車)。

/** 伺服器給的一列:這家門市 × 這家廠商。 */
export interface LinkLike {
  warehouse: number;
  provider: string;
  provider_label: string;
  categories: number[];
  vendor_active: boolean;
  /** 這家門市可以跟這家往來了(全自動 = 貼了金鑰;半自動 = 管理員按了開通) */
  ready: boolean;
  clerk_ordering: boolean;
}

export interface VendorCategoryOption {
  id: number;
  name: string;
}

/** 這個人現在為什麼不能跟這一家叫貨(寫在廠商旁邊;三個字,同一排等長)。空的 = 可以叫。 */
export type Blocked = "" | "未開通" | "已停用" | "限管理";

export interface VendorOption {
  provider: string;
  label: string;
  categories: number[];
  blocked: Blocked;
}

/** 先看最根本的原因:還沒開通(沒有金鑰 / 沒按開通)→ 廠商已經停用 → 這家門市只讓管理員叫。 */
export function blockedOf(row: LinkLike, manager: boolean): Blocked {
  if (!row.ready) return "未開通";
  if (!row.vendor_active) return "已停用";
  if (!row.clerk_ordering && !manager) return "限管理";
  return "";
}

/** 這家門市看得到的廠商(照伺服器給的順序 = 平台排的順序)。 */
export function vendorOptions(rows: LinkLike[], warehouse: number | null, manager: boolean): VendorOption[] {
  return rows
    .filter((r) => r.warehouse === warehouse)
    .map((r) => ({ provider: r.provider, label: r.provider_label, categories: r.categories, blocked: blockedOf(r, manager) }));
}

/** 上面那一排類別:只列底下有廠商的;不到兩個就不用這一排(空陣列)。 */
export function categoryTabs(categories: VendorCategoryOption[], options: VendorOption[]): VendorCategoryOption[] {
  const used = categories.filter((c) => options.some((o) => o.categories.includes(c.id)));
  return used.length >= 2 ? used : [];
}

/** 這個類別底下的廠商;null = 全部。 */
export function inCategory(options: VendorOption[], category: number | null): VendorOption[] {
  return category === null ? options : options.filter((o) => o.categories.includes(category));
}

/**
 * 現在停在哪一家。`wanted` = 上次選的 / 剛剛點的。
 * 它還在這一排裡就留著(換類別時同一家廠商不換、購物車也不換);不在了才換成這一排第一家可以叫的,都不能叫就第一家。
 */
export function pickVendor(shown: VendorOption[], wanted: string | null): string | null {
  if (wanted !== null && shown.some((o) => o.provider === wanted)) return wanted;
  return (shown.find((o) => o.blocked === "") ?? shown[0])?.provider ?? null;
}

/** 要不要顯示「選廠商」那一排:只有一家時不用選(畫面就是那一家)。 */
export function showPicker(options: VendorOption[]): boolean {
  return options.length > 1;
}

/** 草稿(購物車、鑰匙)存在瀏覽器裡的那一格:一個帳號 × 一家門市 × 一家廠商一份。 */
export function draftSlot(username: string, warehouse: number, provider: string): string {
  return `vendor-order-draft:${username}:${warehouse}:${provider}`;
}

/** 多廠商之前只有一家廠商,它的代碼。 */
export const FIRST_VENDOR = "moceo";

/**
 * 多廠商之前草稿存的那一格(一個帳號 × 一家門市一份,沒有分廠商)。只有第一家廠商有;其他廠商回 null。
 */
export function legacyDraftSlot(username: string, warehouse: number, provider: string): string | null {
  return provider === FIRST_VENDOR ? `vendor-order-draft:${username}:${warehouse}` : null;
}

/**
 * 讀草稿:先讀這家廠商自己的那一格;沒有,才讀升級前的那一格(只有第一家廠商有)。
 * 升級前有人送出叫貨、回應沒回來,畫面是鎖著等「再送一次」的(鑰匙與鎖都在舊的那一格)。升級後如果不接著讀,
 * 鎖與鑰匙就不見了,重填再送會用新鑰匙,廠商那邊成立第二張(複審 2026-10-10)。
 */
export function readDraftText(
  get: (slot: string) => string | null,
  username: string,
  warehouse: number,
  provider: string,
): string | null {
  const mine = get(draftSlot(username, warehouse, provider));
  if (mine !== null) return mine;
  const old = legacyDraftSlot(username, warehouse, provider);
  return old === null ? null : get(old);
}

/** 記住這家門市上次停在哪一家廠商的那一格(只是方便,讀不到就算了)。 */
export function lastVendorSlot(warehouse: number): string {
  return `vendor-order-vendor:${warehouse}`;
}

/** 「廠商叫貨」這一頁的三個分頁(同一排,字數一樣)。 */
export type PageTab = "order" | "history" | "mapping";

export const PAGE_TABS: { value: PageTab; label: string }[] = [
  { value: "order", label: "叫貨" },
  { value: "history", label: "紀錄" },
  // 品名連連看:廠商的品項 ↔ 店內商品(連好之後到貨直接入庫,不用每次挑)
  { value: "mapping", label: "對照" },
];

/**
 * 這個帳號在這一頁看得到哪幾個分頁。叫貨的人與收貨的人都進得來(收貨的人不一定是叫貨的人):
 * 沒有「廠商叫貨」的人沒有「叫貨」這個分頁(廠商的商品與進價伺服器本來就不給他看);紀錄(到貨入庫在裡面)與對照都有。
 */
export function pageTabs(canOrder: boolean): { value: PageTab; label: string }[] {
  return canOrder ? PAGE_TABS : PAGE_TABS.filter((t) => t.value !== "order");
}

/** 現在停在哪個分頁:人點過、而且看得到的那一個;不然第一個看得到的(能叫貨 = 叫貨,只收貨 = 紀錄)。 */
export function currentTab(wanted: PageTab | null, canOrder: boolean): PageTab {
  const tabs = pageTabs(canOrder);
  return tabs.some((t) => t.value === wanted) ? (wanted as PageTab) : tabs[0].value;
}
