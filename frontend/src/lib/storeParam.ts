// 首頁選的門市帶到待辦 / 注意那幾張清單(全站檢視 R06)。跑法:npm test。
//
// 網址帶 `warehouse=門市編號`,目的頁照那一家查,上面「已套用的條件」寫門市名、可以清掉。
// 這只是「先選好哪一家」:鎖在門市的帳號伺服器照舊只給自己那一家(網址寫別家也沒用);
// 序號查詢本來就不照帳號鎖店,帶過去也只是先選好、照樣可以改成別家。

export const STORE_PARAM = "warehouse";

/** 網址上的門市編號:不是正整數就當沒有 */
export function storeIdFrom(raw: string | null): number | null {
  if (!raw || !/^\d+$/.test(raw)) return null;
  const n = Number(raw);
  return n > 0 ? n : null;
}

/**
 * 那一家還在不在:門市清單還沒回來先照網址查(`pending`);回來了沒有這一家、或已經停用 = 不認(當成全部,網址清掉)。
 */
export function storeCheck(
  id: number | null,
  stores: { id: number; name: string; is_active: boolean }[] | undefined,
  /** 鎖在門市的帳號、而且這一頁照帳號鎖店:網址寫別家當沒帶(伺服器反正只給自己那一家,寫別家只會變成 0 筆) */
  lockedTo: number | null = null,
): { id: number | null; name: string; state: "none" | "pending" | "ok" | "gone" } {
  if (id === null) return { id: null, name: "", state: "none" };
  if (lockedTo !== null && id !== lockedTo) return { id: null, name: "", state: "gone" };
  if (!stores) return { id, name: "", state: "pending" };
  const hit = stores.find((s) => s.id === id && s.is_active);
  return hit ? { id, name: hit.name, state: "ok" } : { id: null, name: "", state: "gone" };
}

/** 首頁的連結加上門市(全公司 = 不加);已經有其他條件的接在後面 */
export function withStore(to: string, store: number | null): string {
  if (store === null) return to;
  return `${to}${to.includes("?") ? "&" : "?"}${STORE_PARAM}=${store}`;
}
