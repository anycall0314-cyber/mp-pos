// 批發品(按數量賣的:全新機、配件、之後的維修零件)的批次上架 / 改價在畫面這一側(owner 2026-10-14:
// 「一般商品也要可以用批次上架,可以依品牌,類別,關鍵字,型號等,用多重分類去選取與批次上架改價」)。
// 規則只有伺服器那一份(backend/apps/trade/listing.py:price_for / set_products);這裡是預覽改完的價、組要送的內容。
import { roundInt } from "./money.ts";
import { priceOf } from "./trade.ts";

export interface GoodsRow {
  product: number;
  name: string;
  list_price: number;
  is_listed: boolean;
  /** 固定價(每個同行一樣);null = 沒有 */
  price: number | null;
  /** 門市價的幾 %(每個同行一樣,門市價改了跟著變);null = 沒有 */
  percent: number | null;
}

/** 批發價怎麼算:固定價 / 門市價的幾 % / 照各同行的折數 */
export type GoodsMode = "fixed" | "percent" | "partner";

/** 一個商品現在的批發價(給「每個同行一樣」的那兩種算得出金額;照同行折數的算不出單一個價,回 null) */
export function goodsPrice(row: Pick<GoodsRow, "list_price" | "price" | "percent">): number | null {
  if (row.price !== null) return row.price;
  if (row.percent !== null) return roundInt((row.list_price * row.percent) / 100);
  return null;
}

/** 「門市價 %」那一格:1 到 200 的整數;空的回 undefined;不對回 null */
export function percentText(text: string): number | undefined | null {
  const t = text.trim();
  if (t === "") return undefined;
  if (!/^\d{1,3}$/.test(t)) return null;
  const n = Number(t);
  return n >= 1 && n <= 200 ? n : null;
}

/** 這個商品改完之後會是什麼(畫面上每一列「改成」那一格):自己那一列打了固定價優先 */
export function goodsAfter(row: GoodsRow, mode: GoodsMode | null, value: string, typed?: string): Pick<GoodsRow, "price" | "percent"> | null {
  if (typed !== undefined) {
    const price = priceOf(typed);
    return typeof price === "number" ? { price, percent: null } : price === undefined ? { price: null, percent: null } : null;
  }
  if (mode === null) return { price: row.price, percent: row.percent };
  if (mode === "partner") return { price: null, percent: null };
  if (mode === "fixed") {
    const price = priceOf(value);
    return typeof price === "number" ? { price, percent: null } : null;
  }
  const percent = percentText(value);
  return typeof percent === "number" ? { price: null, percent } : null;
}

export interface GoodsPlan {
  rows: { product: number; is_listed?: boolean; price?: number | null; percent?: number | null }[];
  /** 改完之後每個同行一樣的那些金額(預覽與確認用) */
  before: number[];
  after: number[];
  /** 改完是「照同行折數」的幾個 */
  toPartner: number;
  odd: boolean;
}

/**
 * 按下去要送什麼。`list` = 開放 / 收回 / 不動(null);`mode` + `value` = 這一次的改價方式(null = 不改價);`typed` = 每一列自己打的固定價。
 * 有一個不對回是哪一個。
 */
export function goodsPlan(chosen: GoodsRow[], list: boolean | null, mode: GoodsMode | null, value: string, typed: Record<number, string>): GoodsPlan | { error: string } {
  const plan: GoodsPlan = { rows: [], before: [], after: [], toPartner: 0, odd: false };
  if (mode === "fixed" && typeof priceOf(value) !== "number") return { error: "固定價要填正的整數" };
  if (mode === "percent" && typeof percentText(value) !== "number") return { error: "% 要填 1 到 200" };
  for (const r of chosen) {
    const after = goodsAfter(r, mode, value, typed[r.product]);
    if (after === null) return { error: `「${r.name}」的價要填正的整數` };
    const row: GoodsPlan["rows"][number] = { product: r.product };
    if (list !== null && list !== r.is_listed) row.is_listed = list;
    if (after.price !== r.price || after.percent !== r.percent) {
      if (after.price !== null) row.price = after.price;
      else if (after.percent !== null) row.percent = after.percent;
      else row.price = null;                                                 // 清掉 = 回到照同行的折數
      const was = goodsPrice(r);
      const now = goodsPrice({ list_price: r.list_price, ...after });
      if (was !== null) plan.before.push(was);
      if (now !== null) {
        plan.after.push(now);
        if (r.list_price > 0 && (now > r.list_price || now * 2 < r.list_price)) plan.odd = true;
      } else plan.toPartner += 1;
    }
    if (Object.keys(row).length > 1) plan.rows.push(row);
  }
  return plan;
}

/** 一次十個以上、或有改到價:先顯示再按一次 */
export const goodsNeedsConfirm = (plan: GoodsPlan) => plan.rows.length >= 10 || plan.after.length + plan.toPartner > 0;

const range = (ns: number[]) => {
  const low = Math.min(...ns);
  const high = Math.max(...ns);
  return low === high ? `${low}` : `${low}–${high}`;
};

/** 再按一次之前的那一行:只有數字(紅隊:員工把 70 打進固定價,要一眼看得出變成 70 元) */
export function goodsConfirmText(plan: GoodsPlan, list: boolean | null): string {
  const parts = [`${plan.rows.length} 個`];
  if (list === true) parts.push("開放");
  if (list === false) parts.push("收回");
  if (plan.after.length) parts.push(`${plan.before.length ? `${range(plan.before)} → ` : ""}${range(plan.after)}`, "每個同行一樣");
  if (plan.toPartner) parts.push(`照折數 ${plan.toPartner} 個`);
  if (plan.odd) parts.push("價差大");
  return parts.join(" · ");
}
