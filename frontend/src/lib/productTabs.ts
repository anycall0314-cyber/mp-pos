/**
 * 從商品管理另開的分頁(新增商品、新增手機型號)做完,回到原本那一頁(全站檢視 D4:以前按「回商品頁」又在新分頁裡開一個商品管理,
 * 建三個商品就多三個分頁)。原本那一頁不在商品管理(例如盤點、進貨開的)、已經關掉、或直接打網址進來的 → 不關,照舊在這一頁換頁。
 */
export const PRODUCT_SAVED_MSG = "mp-product-saved";

export interface ProductSavedMessage {
  type: typeof PRODUCT_SAVED_MSG;
  /** 選到這一筆;null = 只把清單重抓(手機型號一次建好幾個) */
  id: number | null;
  /** 商品管理搜這幾個字(新增手機型號的「去看」:看那一支的品項) */
  find?: string;
}

function productsOpener(): Window | null {
  try {
    const o = window.opener as Window | null;
    if (!o || o.closed) return null;
    if (o.location.origin !== window.location.origin) return null;
    return o.location.pathname === "/products" ? o : null;
  } catch {
    return null;
  }
}

/** 告訴原本那一頁(商品管理)剛建好了什麼;沒有那一頁回 false */
export function tellOpener(id: number | null, find?: string): boolean {
  const o = productsOpener();
  if (!o) return false;
  const msg: ProductSavedMessage = { type: PRODUCT_SAVED_MSG, id, ...(find ? { find } : {}) };
  o.postMessage(msg, window.location.origin);
  return true;
}

/** 回到原本那一頁並關掉這一頁;沒有那一頁回 false(呼叫的人自己換頁) */
export function backToOpener(id: number | null, find?: string): boolean {
  if (!tellOpener(id, find)) return false;
  try {
    (window.opener as Window).focus();
  } catch {
    // 拿不到焦點也沒關係,關掉這一頁就會回到那一頁
  }
  window.close();
  return true;
}

export function isProductSavedMessage(data: unknown): data is ProductSavedMessage {
  return (
    typeof data === "object" &&
    data !== null &&
    (data as { type?: unknown }).type === PRODUCT_SAVED_MSG &&
    ((data as { id?: unknown }).id === null || typeof (data as { id?: unknown }).id === "number") &&
    ((data as { find?: unknown }).find === undefined || typeof (data as { find?: unknown }).find === "string")
  );
}

/** 另開分頁;瀏覽器擋住就回 false(呼叫的人改在這一頁換頁,不要讓人再按一次建兩套) */
export function openInNewTab(url: string): boolean {
  return window.open(url, "_blank") !== null;
}
