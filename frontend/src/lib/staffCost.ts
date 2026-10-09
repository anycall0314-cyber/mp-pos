// 業務員成本:算獎金看的毛利用的成本(實際成本加上公司定的加成)。業務員毛利 = 未稅金額 − 業務員成本。
// 怎麼算只有伺服器那一份(backend/apps/core/staff_cost.py)。畫面這一側只做三件事:
//   (1) 還沒存的單:用伺服器給的「一件的業務員成本」估;
//   (2) 已經存的單:用單上記的那個數字(沒有記的舊單 = 實際成本,伺服器已經換好);
//   (3) 設定畫面的選項、文字與要送出去的值。
// 實際成本照舊所有人看得到(owner 2026-10-09:不用藏);公司佣金只有管理員有。
import { money } from "./money.ts";

type Num = string | number | null | undefined;

/** 商品自己的設定。選項字數一樣(同一排等長)。 */
export const PRODUCT_MODES: [string, string][] = [
  ["", "照全公司"],
  ["fixed", "固定金額"],
  ["plus", "加固定額"],
  ["percent", "加百分比"],
];
/** 全公司的那一條(沒有「固定金額」:每個商品同一個成本沒有意義)。 */
export const COMPANY_MODES: [string, string][] = [
  ["", "尚未設定"],
  ["plus", "加固定額"],
  ["percent", "加百分比"],
];

function num(v: Num): number {
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
}

/**
 * 這個商品現在算不算業務員成本的加成。owner 2026-10-10:「帶序號的產品先不做,先針對一般商品」——
 * 帶序號的(手機、中古機)與虛擬商品不顯示這一列、表單也沒有設定那一段(伺服器同樣不算、不存)。
 */
export function staffCostApplies(product: { is_virtual?: boolean; requires_serial?: boolean }): boolean {
  // 資料裡沒有「帶不帶序號」那一欄時當成不適用(不確定就不顯示)
  return product.requires_serial === false && !product.is_virtual;
}

/** 資料裡有沒有「怎麼算」那一欄(有 = 伺服器認定現在看的人是管理員,可以設定)。 */
export function canSetStaffCost(row: object | null | undefined): boolean {
  return !!row && Object.hasOwn(row, "staff_cost_mode");
}

/** 百分比照打的樣子顯示:20.00 → 20、12.50 → 12.5 */
function plain(v: Num): string {
  return String(num(v));
}

/** 一句話講這條設定;沒有設定回空字串。 */
export function ruleText(mode: string | null | undefined, value: Num): string {
  if (mode === "fixed") return `固定 ${money(value)}`;
  if (mode === "plus") return `成本加 ${money(value)}`;
  if (mode === "percent") return `成本加 ${plain(value)}%`;
  return "";
}

/** 數值那一格後面的單位。 */
export function valueUnit(mode: string): string {
  return mode === "percent" ? "%" : mode ? "元" : "";
}

/** 輸入框裡的字:沒有設定是空的;有設定照存的數字(20.00 → 20)。 */
export function valueInput(mode: string | null | undefined, value: Num): string {
  return mode ? plain(value) : "";
}

/** 這樣能不能存;不能回一句話。 */
export function ruleProblem(mode: string, text: string): string | null {
  if (!mode) return null;
  const t = text.trim();
  if (t === "") return "請填數字";
  if (!/^\d+(\.\d{1,2})?$/.test(t)) return "請填 0 以上的數字(最多兩位小數)";
  return null;
}

/** 要送給伺服器的兩欄。沒有設定 = 數值不留。 */
export function rulePayload(mode: string, text: string): { staff_cost_mode: string; staff_cost_value: string } {
  return { staff_cost_mode: mode, staff_cost_value: mode ? text.trim() : "0" };
}

interface ProductLike {
  is_virtual?: boolean;
  is_secondhand?: boolean;
  staff_cost?: Num;
  weighted_avg_cost?: Num;
}

/**
 * 還沒存的那一行,預估的業務員成本(整行)。
 * 中古機挑好了哪幾台、而且每一台的數字都有 → 各台加總(每一台成本不同);
 * 其餘 = 一件的業務員成本 × 數量。伺服器沒給這一欄(舊的草稿)退回平均成本,跟以前的估法一樣。
 */
export function estimateStaffCost(product: ProductLike, qty: number, unitCosts: Num[] = []): number {
  if (product.is_virtual) return 0;
  const known = unitCosts.filter((c) => c !== null && c !== undefined && String(c).trim() !== "");
  if (product.is_secondhand && known.length > 0 && known.length === unitCosts.length && known.length === qty) {
    return known.reduce((sum: number, c) => sum + num(c), 0);
  }
  const one = product.staff_cost ?? product.weighted_avg_cost;
  return num(one) * qty;
}

interface LineLike {
  product_counts_margin?: boolean;
  untaxed_amount?: Num;
  cost_at_post?: Num;
  staff_cost?: Num;
  commission?: Num;
  company_commission?: Num;
  telecom_plan?: number | null;
}

/** 這一行算不算毛利(收購二手那一類不算)。 */
export function countsMargin(line: LineLike): boolean {
  return line.product_counts_margin !== false;
}

/** 單上記的業務員成本;資料裡沒有這一欄(還沒更新的畫面資料)退回實際成本。 */
export function staffCostOf(line: LineLike): number {
  return num(line.staff_cost ?? line.cost_at_post);
}

/** 這一行的業務員毛利 = 未稅金額 − 業務員成本(不含佣金;不計毛利的行是 0)。 */
export function staffMargin(line: LineLike): number {
  return countsMargin(line) ? num(line.untaxed_amount) - staffCostOf(line) : 0;
}

/** 這一行的毛利(實際的)= 未稅金額 − 實際成本。 */
export function actualMargin(line: LineLike): number {
  return countsMargin(line) ? num(line.untaxed_amount) - num(line.cost_at_post) : 0;
}

/** 整張單的業務員毛利(含業務員佣金):銷貨單清單上那個數字。 */
export function orderStaffMargin(lines: LineLike[]): number {
  return lines.reduce(
    (sum, l) => (countsMargin(l) ? sum + staffMargin(l) + num(l.commission) : sum),
    0,
  );
}

/**
 * 整張單的實際毛利(管理員看的)= 未稅金額 − 實際成本 + 公司佣金。
 * 有門號那一行的公司佣金還沒設定 → 算不出來,回 null(不拿 0 或業務員佣金去猜)。
 * 資料裡沒有公司佣金那一欄(看的人不是管理員)也回 null。
 */
export function orderActualMargin(lines: LineLike[]): number | null {
  let total = 0;
  for (const l of lines) {
    if (!Object.hasOwn(l, "company_commission")) return null;
    if (!countsMargin(l)) continue;
    if (l.telecom_plan && (l.company_commission === null || l.company_commission === undefined)) return null;
    total += actualMargin(l) + num(l.company_commission);
  }
  return total;
}
