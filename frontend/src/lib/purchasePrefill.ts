/**
 * 「建好品號 → 按進貨」:從商品那一邊帶著幾個商品去進貨開單頁。
 * 進貨開單頁的網址收 `?add=商品編號,商品編號`;這裡只管「網址怎麼組、怎麼讀」(純函式,有測試)。
 * 真正加進明細的規則還是進貨開單頁原本那一套(中古機不能走一般進貨、停用的不會被悄悄加進去)。
 */
import { barcodeIn } from "./findFirst.ts";

/** 一次最多帶幾個商品(一支機型展開的容量 × 顏色 × 品況不會超過這個數字太多;擋掉亂給的網址) */
export const MAX_PREFILL = 60;

interface Buyable {
  id?: number | null;
  is_secondhand?: boolean;
  is_virtual?: boolean;
  is_active?: boolean;
}

/**
 * 這幾個商品按「進貨」要去哪裡。
 * - 有一般商品(不是中古、不是虛擬、沒停用):去進貨開單頁,帶著它們;
 * - 只有中古機:去中古收購(中古機不走一般進貨單;那一頁沒辦法預先帶商品);
 * - 都不能進貨(虛擬商品、停用、沒有編號):回 null(不顯示「進貨」)。
 */
export function purchaseLinkFor(items: Buyable[]): string | null {
  const usable = items.filter(
    (p) => typeof p.id === "number" && p.id > 0 && !p.is_virtual && p.is_active !== false,
  );
  const regular = usable.filter((p) => !p.is_secondhand).map((p) => p.id as number);
  const all = [...new Set(regular)];
  const ids = all.slice(0, MAX_PREFILL);
  if (ids.length > 0) {
    // 帶不完的不能當沒這回事:把「還有幾項」一起交給進貨開單頁,它會講出來
    const more = all.length - ids.length;
    return `/purchases/new?add=${ids.join(",")}${more > 0 ? `&more=${more}` : ""}`;
  }
  if (usable.some((p) => p.is_secondhand)) return "/secondhand-acquisition";
  return null;
}

/** 網址上寫的商品編號:只收正整數、不重複、照原本的順序(亂給的超長網址只看前面一段) */
function validIds(raw: string | null | undefined): number[] {
  if (!raw) return [];
  const seen = new Set<number>();
  for (const part of raw.split(",", 2000)) {
    const text = part.trim();
    if (!/^[0-9]{1,15}$/.test(text)) continue;
    const id = Number(text);
    if (id > 0) seen.add(id);
  }
  return [...seen];
}

/**
 * 進貨開單頁打開時讀網址(`location.search`):
 * - `ids`:要加進明細的商品(最多 `MAX_PREFILL` 個);
 * - `more`:沒帶過來的有幾項(那一邊講的 `more`,加上這個網址自己超過上限的);
 * - `rest`:把 `add` / `more` 拿掉之後剩下的查詢字串(別的參數原樣留著),給「讀完就從網址拿掉」用。
 */
export function readPrefill(search: string): { ids: number[]; more: number; rest: string } {
  const params = new URLSearchParams(search);
  // 同一個參數寫了好幾次(`add=1&add=2`)全部都算
  const all = validIds(params.getAll("add").join(","));
  const ids = all.slice(0, MAX_PREFILL);
  const declared = (params.get("more") ?? "").trim();
  const more = all.length - ids.length + (/^[0-9]{1,6}$/.test(declared) ? Number(declared) : 0);
  params.delete("add");
  params.delete("more");
  const rest = params.toString();
  return { ids, more, rest: rest ? `?${rest}` : "" };
}

/**
 * 把網址上的 `add` / `more` 換成這幾個(`readPrefill` 的反向);別的參數原樣留著。
 * 進貨開單頁用它把網址寫成「所有還沒做完的」:`ids` 是空的就是把 `add` / `more` 拿掉。
 */
export function withPrefill(search: string, ids: number[], more: number): string {
  const params = new URLSearchParams(search);
  params.delete("add");
  params.delete("more");
  const unique = [...new Set(ids.filter((id) => Number.isInteger(id) && id > 0))];
  if (unique.length > 0) {
    params.set("add", unique.join(","));
    if (Number.isInteger(more) && more > 0) params.set("more", String(more));
  }
  const text = params.toString();
  return text ? `?${text}` : "";
}

/**
 * 帶過來的商品,新的一行數量先放多少。
 * - 配件(不追序號):**0** —— 帶過來不代表進了幾件,要刷或打數量才算,0 存不了。
 *   先放 1 的話,接著把每一件都刷一次就多算一件(刷跟帶誰先誰後都一樣會錯)。
 * - 序號商品:1 個空位(刷到序號才算一台,空位沒刷存不了)。
 */
export function carriedQty(product: { requires_serial?: boolean }): number {
  return product.requires_serial ? 1 : 0;
}

/**
 * 草稿裡這一行的進貨數量。最少 1;只有一種 0 要留著:帶過來、還沒填數量的配件。
 * 載回來變成 1 的話,就是替人說了「進 1 件」。序號商品沒有 0(至少一個空位)。
 */
export function draftQty(line: { qty?: unknown; product: { requires_serial?: boolean } }): number {
  if (line.qty === 0 && !line.product.requires_serial) return 0;
  return Math.max(1, Number(line.qty) || 1);
}

/** 查回來的商品,這裡只看這幾欄 */
interface Fetched {
  name: string;
  is_secondhand?: boolean;
  is_virtual?: boolean;
  is_active?: boolean;
}

/**
 * 查回來的商品分一分:哪些可以放進一般進貨單(`fresh`,照帶過來的順序)、哪些不行。
 * 以伺服器現在回的為準,不信網址那一邊的判斷(商品可能剛被停用、網址可能是人手打的):
 * 查不到的不加;**中古機不加**(不走一般進貨單);**虛擬商品不加**;**停用的不加**(不會因為被帶過來就悄悄恢復)。
 * 不加的只留品名,給頁面講。
 */
export function sortFetched<P extends Fetched>(
  results: PromiseSettledResult<P>[],
): { fresh: P[]; inactive: string[]; secondhand: string[]; virtual: string[]; missing: number } {
  const out = { fresh: [] as P[], inactive: [] as string[], secondhand: [] as string[], virtual: [] as string[], missing: 0 };
  for (const r of results) {
    if (r.status !== "fulfilled" || !r.value) out.missing += 1;
    else if (r.value.is_secondhand) out.secondhand.push(r.value.name);
    else if (r.value.is_virtual) out.virtual.push(r.value.name);
    else if (r.value.is_active === false) out.inactive.push(r.value.name);
    else out.fresh.push(r.value);
  }
  return out;
}

/**
 * 在進貨開單頁當場找到 / 建好的商品,能不能放進這張(一般)進貨單。
 * 回一句話 = 不能(原因);null = 可以。中古機走中古收購、虛擬商品不用進貨 —— 跟上面 `sortFetched` 同一套分法。
 * 停用的不在這裡講:那一種頁面有自己的說法(管理員可以當場恢復)。
 */
export function notForPurchase(p: { name: string; is_secondhand?: boolean; is_virtual?: boolean }): string | null {
  if (p.is_secondhand) return `「${p.name}」是中古機,請到中古收購進`;
  if (p.is_virtual) return `「${p.name}」是虛擬商品,不用進貨`;
  return null;
}

/**
 * 「當場建 / 當場找」的一趟:從掃碼框的哪一串字、「沒加入」的哪一筆開始的。
 * **一趟只能帶回一個商品一次**(`take`):連按兩下「使用這款」、存檔的回應回來兩次,都只加一次。
 */
export interface CreateTrip<E> {
  kw: string;
  entry: E | null;
  /**
   * 帶回來的商品已經不是「這一趟那串字」的了(人在表單載入了別的草稿):
   * 商品照樣加進這張單,但**不劃**「沒加入」那一筆、不清掃碼框的字 —— 那串字還沒有對到商品。
   */
  detached: boolean;
}
/**
 * 這一趟「自己的」那一筆「沒加入」:離開這一頁之前檢查還有沒有別的碼沒處理時,這一筆不算(它正在被處理)。
 * 但載入過別的草稿的那一趟(`detached`)**沒有自己的那一筆**:表單裡的已經不是那串字的商品,那一筆其實還沒有著落,要照算。
 */
export function tripOwnEntry<E>(trip: CreateTrip<E> | null): E | null {
  return trip && !trip.detached ? trip.entry : null;
}

/**
 * 帶回來的商品要不要算在這一趟那串字上(劃掉「沒加入」那一筆、清掉掃碼框的字)。
 * 一般的一趟:算。載入過別的草稿的那一趟:不算 —— 除非**那串字是條碼**、而且存好的商品條碼正好就是它
 * (人載入草稿之後又把條碼改成這一次刷的:那它就是這一次刷的那個;不劃的話那一筆再重查一次會多加一件)。
 * 「是不是條碼」用帶進表單時的同一個認法(`barcodeIn`:去掉空白與連字號後整串數字、8 碼以上)。
 * **品名開始的那一趟載入草稿之後一律不算**:品名 `X-1` 去掉連字號剛好等於別的商品的條碼 `X1`,不代表它們是同一個東西。
 */
export function tripSettles<E>(
  trip: CreateTrip<E>,
  product: { barcode?: string | null },
): boolean {
  if (!trip.detached) return true;
  const scanned = barcodeIn(trip.kw);
  if (scanned === null) return false;
  return scanned === (product.barcode ?? "").replace(/[\s-]/g, "");
}

export function tripBox<E>() {
  let now: CreateTrip<E> | null = null;
  return {
    /** 開始新的一趟(上一趟沒做完的就不算了) */
    start(kw: string, entry: E | null) {
      now = { kw, entry, detached: false };
    },
    /** 看一下現在這一趟(不拿走) */
    peek(): CreateTrip<E> | null {
      return now;
    },
    /** 人在表單載入了別的草稿:這一趟之後帶回來的商品不算在那串字上(見 `detached`)。沒有進行中的一趟就不做事 */
    detach() {
      if (now) now = { ...now, detached: true };
    },
    /** 這一趟帶回商品了:拿走(之後再拿就是 null) */
    take(): CreateTrip<E> | null {
      const got = now;
      now = null;
      return got;
    },
    /** 人取消了(關掉沒選也沒建) */
    drop() {
      now = null;
    },
    active(): boolean {
      return now !== null;
    },
  };
}

/** 帶過來之後沒加進去的,分成幾種(進貨開單頁照這個講給人知道) */
export interface PrefillOutcome {
  /** 中古機的品名:不走一般進貨單 */
  secondhand: string[];
  /** 虛擬商品的品名:不用進貨 */
  virtual: string[];
  /** 停用商品的品名:要管理員恢復之後才能進貨 */
  inactive: string[];
  /** 查不到的有幾個(被刪了、不是這家公司的、連線沒回應或等太久) */
  missing: number;
  /** 其他沒加成的原因(這張單已經送出…),一句一行 */
  other: string[];
  /** 一次帶不完、根本沒帶過來的項數 */
  more: number;
}

/** 「甲」「乙」「丙」等 5 項:最多寫三個名字,總共幾項一定講 */
function nameList(names: string[]): string {
  const unique = [...new Set(names.map((n) => n.trim()).filter(Boolean))];
  const shown = unique.slice(0, 3).map((n) => `「${n}」`).join("");
  return unique.length > 3 ? `${shown}等 ${unique.length} 項` : shown;
}

/**
 * 沒加進去的要講給人知道,一種一行(放在明細上方那一條,按「知道了」才消失 —— 不是一閃就過的訊息:
 * 人以為都帶到了、其實少了幾項,存下去就是少進貨)。都加進去了就回空的。
 */
export function prefillReport(o: PrefillOutcome): string[] {
  const lines: string[] = [];
  if (o.secondhand.length > 0) {
    lines.push(`${nameList(o.secondhand)}是中古機,沒有加入:請到「中古收購」進`);
  }
  if (o.virtual.length > 0) {
    lines.push(`${nameList(o.virtual)}是虛擬商品,不用進貨,沒有加入`);
  }
  if (o.inactive.length > 0) {
    lines.push(`${nameList(o.inactive)}已停用,沒有加入:要管理員恢復之後才能進貨`);
  }
  if (o.missing > 0) lines.push(`有 ${o.missing} 個商品查不到(可能已經刪除,或網路沒回應),沒有加入`);
  for (const text of new Set(o.other.map((x) => x.trim()).filter(Boolean))) lines.push(text);
  if (o.more > 0) {
    lines.push(`一次最多帶 ${MAX_PREFILL} 項,另有 ${o.more} 項沒有帶過來:請用搜尋加入`);
  }
  return lines;
}
