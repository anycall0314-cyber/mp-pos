// 品名連連看(廠商的品項 ↔ 店內商品)在畫面這一側的規則。跑法:npm test。
// 伺服器決定:品名、規格、一包幾個(都是它剛跟廠商要的)、那個商品能不能連、誰能連。
// 這裡只管:清單怎麼篩、連了幾個、存完那一列怎麼放回清單、去找店內商品時先帶什麼字、哪種商品一看就知道連不了、存完怎麼講,
// 以及「一次只存一筆、存的是開始那一刻的那一列」(`oneAtATime` / `linkFetched`)。

export interface MappedProduct {
  id: number;
  sku: string;
  name: string;
  is_active: boolean;
}

export interface MappingRow {
  key: string;
  sku: string;
  spec_id: number | null;
  name: string;
  spec_label: string;
  kind: string;
  size: string;
  unit: string;
  pack_qty: number;
  /** 對到店裡哪個商品(null = 還沒連) */
  product: MappedProduct | null;
}

export interface MappingData {
  warehouse: number;
  vendor: string;
  supplier: { id: number; name: string } | null;
  rows: MappingRow[];
}

/** 廠商那一邊怎麼叫:品名 + 規格 + 尺寸。 */
export function itemTitle(row: Pick<MappingRow, "name" | "spec_label" | "size">): string {
  return [row.name, row.spec_label, row.size].filter(Boolean).join(" ");
}

export function counts(rows: MappingRow[]): { linked: number; total: number } {
  return { linked: rows.filter((r) => r.product !== null).length, total: rows.length };
}

export interface MappingFilter {
  text: string;
  unlinkedOnly: boolean;
}

/** 找的字兩邊都比:廠商的品名 / 規格 / 料號 / 尺寸,與已經連到的店內品名 / 品號。每個字都要有。 */
export function filterRows(rows: MappingRow[], filter: MappingFilter): MappingRow[] {
  const words = filter.text.toLowerCase().split(/\s+/).filter(Boolean);
  return rows.filter((r) => {
    if (filter.unlinkedOnly && r.product !== null) return false;
    const hay = `${r.name} ${r.spec_label} ${r.sku} ${r.size} ${r.product?.name ?? ""} ${r.product?.sku ?? ""}`.toLowerCase();
    return words.every((w) => hay.includes(w));
  });
}

/**
 * 存完:伺服器回的那一列放回清單原本的位置(不重抓整份:重抓要再跟廠商要一次清單,而且列會跳)。
 * 清單上已經沒有那一列(換了門市 / 廠商之後才回來的)→ 不動。
 */
export function withSaved(data: MappingData | undefined, row: MappingRow): MappingData | undefined {
  if (!data || !data.rows.some((r) => r.key === row.key)) return data;
  return { ...data, rows: data.rows.map((r) => (r.key === row.key ? row : r)) };
}

/** 去找店內商品時先帶的字:廠商的品名 + 規格(料號、尺寸是廠商自己的,店裡不會這樣叫)。 */
export function findText(row: Pick<MappingRow, "name" | "spec_label">): string {
  return [row.name, row.spec_label].filter(Boolean).join(" ").trim();
}

export type Linkable = { is_active?: boolean; requires_serial?: boolean; is_secondhand?: boolean; is_virtual?: boolean };

/**
 * 這個商品為什麼連不了(null = 可以)。叫貨來的東西只入到按數量管的一般商品 —— 伺服器同一條、它說了算;
 * 這裡先講是讓人不用送出去才知道。
 */
export function whyNot(p: Linkable): string | null {
  if (p.is_active === false) return "這個商品已經停用";
  if (p.is_secondhand) return "中古機要逐台記,不能連";
  if (p.requires_serial) return "要刷序號的商品不能連";
  if (p.is_virtual) return "虛擬商品沒有庫存,不能連";
  return null;
}

/**
 * 一次只做一件:做的時候記著是哪一列(那一列顯示「儲存」、每一列的按鈕都先不能按)。已經有一件在做 → 這一件不做(回 null)。
 * **不拿 React 的 state 來判斷**:晚回來的回應手上的 state 是舊的那一份,會以為沒有人在做。`onChange` 只是讓畫面跟著畫。
 */
export function oneAtATime(onChange: (busy: string | null) => void = () => {}) {
  let busy: string | null = null;
  return {
    busy: () => busy,
    async run<T>(key: string, work: () => Promise<T>): Promise<T | null> {
      if (busy !== null) return null;
      busy = key;
      onChange(busy);
      try {
        return await work();
      } finally {
        busy = null;
        onChange(null);
      }
    },
  };
}

/**
 * 新增表單存檔時被防重複擋下、選了「就是這個」:把既有的那個商品查回來,連到 `row`。
 * **`row` 由呼叫的人在按下去的那一刻交進來**(複審 2026-10-10):表單這時候已經關了、「正在處理哪一列」也清掉了 ——
 * 等商品查回來才去看「現在是哪一列」的話,不是沒有(漏連)、就是人接著點的另一列(連錯,之後每次到貨都入錯)。
 * 查不回來、那個商品連不了:講原因、不連。回有沒有連成。
 */
export async function linkFetched<P extends Linkable>(
  row: MappingRow,
  deps: {
    fetch: () => Promise<P>;
    link: (row: MappingRow, product: P) => Promise<boolean>;
    say: (text: string) => void;
    errorText: (e: unknown) => string;
  },
): Promise<boolean> {
  let product: P;
  try {
    product = await deps.fetch();
  } catch (e) {
    deps.say(deps.errorText(e));
    return false;
  }
  const why = whyNot(product);
  if (why) {
    deps.say(why);
    return false;
  }
  return deps.link(row, product);
}

/** 存完的那一句。`before` = 存之前連到誰。 */
export function savedText(row: MappingRow, before: MappedProduct | null): string {
  const item = itemTitle(row);
  if (row.product === null) return before ? `${item}:已解除` : `${item}:沒有連`;
  if (before && before.id !== row.product.id) return `${item}:改連到 ${row.product.name}`;
  return `${item}:已連到 ${row.product.name}`;
}

/** 這一列的按鈕。同一列的字數一樣(owner:並排的按鈕等長)。 */
export function actionsOf(row: MappingRow): ("link" | "change" | "unlink")[] {
  return row.product === null ? ["link"] : ["change", "unlink"];
}

export const ACTION_LABEL = { link: "連結", change: "改連", unlink: "解除" } as const;
