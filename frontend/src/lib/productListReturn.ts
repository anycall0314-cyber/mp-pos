// 商品管理按「編輯」整頁改完(存好或取消)、或按瀏覽器的上一頁回來:清單回到原來的樣子(全站檢視 R07)。跑法:npm test。
//
// 以前回來只帶「選哪一筆」,清單被換成那一個品號的搜尋結果,原本搜的字、捲到哪、分類瀏覽到哪都不見。
// 做法:按編輯的當下把清單的樣子記在這個分頁(sessionStorage),用那一頁在瀏覽紀錄裡的記號(location.key)當鑰匙;
// 編輯頁存好 / 取消就回上一頁(同一個瀏覽紀錄),商品頁看到同一把鑰匙就照原樣擺回去。直接打網址進編輯頁的沒有鑰匙,照舊。

export const LIST_RETURN_KEY = "mp_pos_products_list";
/** 只留最近幾次(一個分頁裡來回很多次也不會越積越多) */
const KEEP = 10;

export interface ProductListSnapshot {
  leftTab: "products" | "models" | "categories";
  productQuery: string;
  appliedProductQuery: string;
  categoryQuery: string;
  /** 右邊打開的是哪一筆(商品 / 機型 / 類別);照原樣存 */
  selection: unknown;
  detailTab: "basic" | "aliases";
  /** 分類瀏覽走到哪一層(類別 › 廠牌 › 型號) */
  browseAt: unknown;
  /** 清單那一塊捲到哪(電腦上清單自己捲) */
  listScroll: number;
}

interface Store {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

interface Saved {
  order: string[];
  entries: Record<string, ProductListSnapshot>;
}

function readAll(store: Store | null): Saved {
  try {
    const raw = store?.getItem(LIST_RETURN_KEY);
    const parsed = raw ? (JSON.parse(raw) as Saved) : null;
    if (parsed && Array.isArray(parsed.order) && parsed.entries && typeof parsed.entries === "object") return parsed;
  } catch {
    /* 讀不到當成沒有 */
  }
  return { order: [], entries: {} };
}

/** 按編輯的當下:記下這一頁(`key` = 這一頁在瀏覽紀錄裡的記號)清單的樣子 */
export function saveListSnapshot(store: Store | null, key: string, snap: ProductListSnapshot): void {
  if (!store || !key) return;
  const all = readAll(store);
  const order = [...all.order.filter((k) => k !== key), key].slice(-KEEP);
  const entries: Record<string, ProductListSnapshot> = {};
  for (const k of order) entries[k] = k === key ? snap : all.entries[k];
  try {
    store.setItem(LIST_RETURN_KEY, JSON.stringify({ order, entries }));
  } catch {
    /* 存不下也沒關係:回來時照舊 */
  }
}

/** 回到這一頁:之前記過就拿回來(不刪:再按一次上一頁 / 下一頁回來也還在) */
export function readListSnapshot(store: Store | null, key: string): ProductListSnapshot | null {
  if (!store || !key) return null;
  return readAll(store).entries[key] ?? null;
}

/**
 * 編輯頁存好 / 取消要回哪裡:從商品頁點進來的(帶著鑰匙、而且瀏覽紀錄裡有上一頁)回上一頁,
 * 清單照原樣;直接打網址進來的去商品頁、選到這一筆(舊的做法)。
 */
export function returnTarget(listKey: unknown, historyIdx: unknown, selected?: number): -1 | string {
  if (typeof listKey === "string" && listKey && typeof historyIdx === "number" && historyIdx > 0) return -1;
  return selected ? `/products?selected=${selected}` : "/products";
}
