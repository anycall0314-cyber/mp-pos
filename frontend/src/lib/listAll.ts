// 清單怎麼拿:整份都要,還是只要最前面那一頁。讀清單的地方(`api/hooks.ts`)都走這裡。
//
// 以前共用的那一支只拿第一頁(伺服器一頁 50 筆)、不看後面還有沒有:第 51 筆看不到也搜不到,
// 頁面上的合計只加了那 50 筆,而且畫面不會講。現在每一處都要明講是哪一種:
// - `listAll`:整份都要(下拉的選項、管理頁、有合計的清單)。一頁一頁拿到沒有下一頁;超過上限就報錯,**不給一部分**。
// - `firstPage` / `topPage`:本來就只列最前面的(最近的銷貨單、搜尋到的前幾筆);`topPage` 另外回總共幾筆,畫面才講得出「只列前 N 筆」。

/** 伺服器一頁最多給這麼多(`backend/apps/core/pagination.py`)。 */
export const PAGE = 500;
/** 一份清單最多拿這麼多;再多就不是「整份拿回來在畫面上篩」做得來的。 */
export const MAX_ROWS = 5000;

export interface Page<T> {
  count: number;
  next: string | null;
  results: T[];
}

/** 跟伺服器要一頁(測試時換成假的)。 */
export type FetchPage = <T>(path: string) => Promise<Page<T>>;

/** 這份清單太長,不給一部分。`toString` 只回那一句話(畫面是直接把錯誤印出來的)。 */
export class TooManyRows extends Error {
  count: number;

  constructor(count: number, hint = "") {
    super(`超過 ${MAX_ROWS.toLocaleString("en-US")} 筆,${hint || "無法一次列出"}`);
    this.name = "TooManyRows";
    this.count = count;
  }

  toString(): string {
    return this.message;
  }
}

/** 網址換成第幾頁、一頁幾筆(原本帶的其他條件留著)。 */
export function pagePath(path: string, page: number, size: number = PAGE): string {
  const at = path.indexOf("?");
  const base = at < 0 ? path : path.slice(0, at);
  const q = new URLSearchParams(at < 0 ? "" : path.slice(at + 1));
  q.set("page_size", String(size));
  if (page > 1) q.set("page", String(page));
  else q.delete("page");
  return `${base}?${q.toString()}`;
}

async function walk<T>(fetchPage: FetchPage, path: string, hint: string) {
  const rows: T[] = [];
  const seen = new Set<unknown>();
  for (let page = 1; ; page += 1) {
    const got = await fetchPage<T>(pagePath(path, page));
    if (got.count > MAX_ROWS || page > MAX_ROWS / PAGE) throw new TooManyRows(got.count, hint);
    for (const row of got.results) {
      // 拿到一半有人新增:後面的列往後擠,同一列會在下一頁再出現一次
      const id = (row as { id?: unknown } | null)?.id;
      if (id !== undefined && id !== null) {
        if (seen.has(id)) continue;
        seen.add(id);
      }
      rows.push(row);
    }
    if (!got.next || got.results.length === 0) return { rows, count: got.count };
  }
}

/**
 * 整份都要。超過 `MAX_ROWS` 筆報 `TooManyRows`(`hint` = 人可以怎麼辦,例:「請把期間縮小」)。
 * 拿到一半清單有變(筆數對不起來)就整份重拿一次。
 */
export async function listAll<T>(fetchPage: FetchPage, path: string, hint = ""): Promise<T[]> {
  const first = await walk<T>(fetchPage, path, hint);
  if (first.rows.length === first.count) return first.rows;
  return (await walk<T>(fetchPage, path, hint)).rows;
}

/** 只要最前面那一頁(一頁幾筆照網址上寫的;伺服器最少給 50 筆)。 */
export async function firstPage<T>(fetchPage: FetchPage, path: string): Promise<T[]> {
  return (await fetchPage<T>(path)).results;
}

export interface Top<T> {
  rows: T[];
  /** 符合條件的總共幾筆(不只這一頁) */
  count: number;
}

/** 最前面那一頁,加上總共幾筆。 */
export async function topPage<T>(fetchPage: FetchPage, path: string): Promise<Top<T>> {
  const got = await fetchPage<T>(path);
  return { rows: got.results, count: got.count };
}

/** 「只列前 100 位」「只列最近 100 張」:沒有少列就是空的。 */
export function cutNote(top: Top<unknown> | undefined, words: string, unit: string): string {
  if (!top || top.count <= top.rows.length) return "";
  return `${words} ${top.rows.length} ${unit}`;
}

/** 幾個日期裡最晚的那一天("YYYY-MM-DD";空的不算)。 */
export function latestDay(...days: (string | null | undefined)[]): string | null {
  let latest: string | null = null;
  for (const day of days) if (day && (!latest || day > latest)) latest = day;
  return latest;
}

/**
 * 幾個候選裡編號就是 `id` 的第一個;都不是就是空的。
 * 會員頁右邊顯示誰用它:寧可先不顯示,也不把別人的資料放進表單(按儲存會存到選的那一位身上)。
 */
export function byId<T extends { id: number }>(id: number | null, ...candidates: (T | null | undefined)[]): T | null {
  if (id == null) return null;
  for (const one of candidates) if (one && one.id === id) return one;
  return null;
}
