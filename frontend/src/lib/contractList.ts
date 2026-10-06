/**
 * 合約到期名單的幾條小規則(純函式,`contractList.test.mjs` 有測試)。
 *
 * 標完的那一列留在原地(不抽掉,不然下面的往上跳、下一下會標到別人),所以畫面上的一頁
 * 可能混著「已經不屬於這個分頁」的列。翻頁不用頁碼、不用第幾筆,用「接在畫面最後一列後面」:
 * 前面少了誰(自己標的、別的店員標的)都不會讓後面的人被跳過。
 */

export type ContractTabKey = "pending" | "contacted" | "declined" | "renewed";

const TAB_STATE: Record<ContractTabKey, string> = {
  pending: "open",
  contacted: "contacted",
  declined: "declined",
  renewed: "renewed",
};

/** 這一筆現在的狀況還屬不屬於這個分頁 */
export function inTab(state: string, tab: ContractTabKey): boolean {
  return TAB_STATE[tab] === state;
}

/** 這個分頁是不是「到期日近的在上面」(待聯絡、已聯絡);不續約、已續約是新的在上面 */
export function nearestFirst(tab: ContractTabKey): boolean {
  return tab === "pending" || tab === "contacted";
}

interface Placed {
  contract_end: string;
  id: number;
}

/** 翻頁的游標:這一列在名單上的位置(到期日 + 明細編號)。寫法跟後端 `contract_views._key` 一樣 */
export function cursorOf(r: Placed): string {
  return `${r.contract_end},${r.id}`;
}

/** a 在這個分頁的名單上是不是排在 b 後面(同一天到期就看編號) */
export function comesAfter(a: Placed, b: Placed, tab: ContractTabKey): boolean {
  const near = nearestFirst(tab);
  if (a.contract_end !== b.contract_end) {
    return near ? a.contract_end > b.contract_end : a.contract_end < b.contract_end;
  }
  return near ? a.id > b.id : a.id < b.id;
}

/**
 * 畫面上這一頁後面還有沒有人。
 * `shown` = 畫面上的列(標完留在原地的也在);`fetched` = 伺服器現在回的這一頁;`serverHasMore` = 伺服器說它那一頁後面還有。
 * 標掉幾筆之後,伺服器那一頁會把後面的人遞補進來 —— 他們排在畫面最後一列的後面、畫面上還沒出現過:
 * 這時就算伺服器說「後面沒有了」,下一頁也要能按,不然那幾位就看不到了。
 */
export function hasNextPage(
  shown: Placed[],
  fetched: Placed[],
  serverHasMore: boolean,
  tab: ContractTabKey,
): boolean {
  if (shown.length === 0) return false;
  if (serverHasMore) return true;
  const last = shown[shown.length - 1];
  return fetched.some((r) => comesAfter(r, last, tab));
}

/**
 * 畫面上這一頁前面還有沒有人(跟 `hasNextPage` 對稱)。
 * 這一頁的人標掉之後,伺服器用同一個游標重抓:可能把更前面的人補進這一頁(他們排在畫面第一列的前面),
 * 也可能整頁空了(伺服器會說「前面還有」)。兩種都要讓「上一頁」能按 —— 不然還沒處理的人在前面、卻沒有路回去。
 */
export function hasPrevPage(
  shown: Placed[],
  fetched: Placed[],
  serverHasPrev: boolean,
  tab: ContractTabKey,
): boolean {
  if (shown.length === 0) return false;
  if (serverHasPrev) return true;
  const first = shown[0];
  return fetched.some((r) => comesAfter(first, r, tab));
}

/** 標過之後留在原地的那一份名單,記著它是第幾次名單(`epoch`)的 */
export interface KeptRows<R> {
  epoch: number;
  rows: R[];
}

/**
 * 現在這一次名單有沒有「留在原地」的那一份可以用。
 * 只認同一次:條件換過再換回來是新的一次,舊的那一份不能再搬出來蓋住新抓的名單
 * (別人剛改回未聯絡的客人會被遮住,翻頁還會把他跳過)。
 */
export function keptRows<R>(kept: KeptRows<R> | null, now: number): R[] | null {
  return kept && kept.epoch === now ? kept.rows : null;
}

/**
 * 標記存好、伺服器回了那一筆現在的樣子:留在原地的那一份要變成什麼。
 * 送出去到回來之間名單已經換過(`now !== at`)→ 不動,回來的結果不能蓋到新名單上。
 * 其他列原地不動,只把那一筆換成回來的。
 */
export function keepSaved<R extends { id: number }>(
  kept: KeptRows<R> | null,
  now: number,
  at: number,
  shown: R[],
  saved: R,
): KeptRows<R> | null {
  if (now !== at) return kept;
  const base = kept && kept.epoch === at ? kept.rows : shown;
  return { epoch: at, rows: base.map((x) => (x.id === saved.id ? saved : x)) };
}

/**
 * 存好之後清掉那一列打到一半的備註 —— 只有草稿還是送出去的那一句才清。
 * 送出去之後又補打的字不是這一次存的,要留著(畫面會標「未存」),不能無聲無息地丟掉。
 */
export function settleDraft(
  drafts: Record<number, string>,
  id: number,
  sent: string,
): Record<number, string> {
  if (drafts[id] === undefined || drafts[id] !== sent) return drafts;
  const rest = { ...drafts };
  delete rest[id];
  return rest;
}
