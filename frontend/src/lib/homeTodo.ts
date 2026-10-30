/**
 * 今日總覽(2026-10-23,UI 改善計劃 6.1;全站檢視 G7)。
 *
 * 紅隊三條:
 *  1. 快捷是櫃檯動作(開銷貨單、代收話費、查詢庫存、維修收件),帳號看不到那一頁的收起來;
 *  2. 「待辦」只放按下去就做得完的佇列(調撥待入庫、維修待取件、退回待確認、匯入待確認、盤點待核准);
 *     庫存不足、逾期、合約待聯絡是給管店的人看的「注意」,分開放;
 *  3. 每一區跟著同一個門市範圍(鎖門市 = 那一家;沒鎖 = 全公司或首頁選的那一家)。
 *
 *  4. 到貨(2026-10-30):今天進貨的新品、缺貨補進,讓門市跟進貨同步知道。
 *
 * 這一份只決定「有哪幾組、點了去哪、誰看得到」;數字由伺服器 `home-summary` 給。
 */
import { isManager, matchForUser, type NavRole } from "../nav.ts";
import { withStore } from "./storeParam.ts";

export interface HomeItem {
  key: string;
  to: string;
  title: string;
  sub?: string;
}

export interface HomeGroup {
  key: string;
  label: string;
  count: number;
  to: string;
  items: HomeItem[];
}

/** 伺服器回的那一份裡,這裡用到的部分 */
export interface TodoSource {
  returns_pending?: number;
  contracts_pending?: number;
  intake_open?: number;
  counts_pending?: number;
  transfers_pending?: {
    count: number;
    items: { id: number; no: string; from_name: string; to_name: string; days: number }[];
  };
  low_stock?: { count: number; items: { id: number; name: string; qty: number }[] };
  repair_alerts?: {
    overdue_repairs?: {
      count: number;
      items: { id: number; no: string; customer_name: string; host_model_name: string; overdue_days: number }[];
    };
    overdue_external?: {
      count: number;
      items: { id: number; no: string; customer_name: string; vendor_name: string; overdue_days: number }[];
    };
    pickup?: {
      count: number;
      items: { id: number; no: string; customer_name: string; host_model_name: string; ready_days: number }[];
    };
  };
  arrivals?: Record<"new" | "restock", ArrivalSource>;
}

export interface ArrivalSource {
  count: number;
  items: { id: number; sku: string; name: string; qty: number; at: string; warehouses: string[] }[];
}

/** 首頁的主要快捷:名字是動作、字數一樣 */
export const QUICK_ACTIONS = [
  { to: "/sales/new", label: "開銷貨單" },
  { to: "/telecom/billing?new=1", label: "代收話費" }, // 直接打開代收工作區(全站檢視 V04)
  { to: "/inventory", label: "查詢庫存" },
  { to: "/repairs/new", label: "維修收件" },
] as const;

/** 這個帳號看不看得到那一頁(跟側邊欄同一套:收起來的頁點了也只會被擋) */
export function reachable(to: string, who: NavRole): boolean {
  return matchForUser(to.split("?")[0], who) !== null;
}

export function quickActions(who: NavRole) {
  return QUICK_ACTIONS.filter((a) => reachable(a.to, who));
}

const MAX_ITEMS = 3;

function group(key: string, label: string, count: number | undefined, to: string, items: HomeItem[] = []): HomeGroup {
  return { key, label, count: count ?? 0, to, items: items.slice(0, MAX_ITEMS) };
}

/** 幾段字用「 · 」接起來,空的那一段不寫(沒填廠商不會留一個「R-1 · 」) */
function join(...parts: (string | undefined)[]): string {
  return parts.filter((p) => p && p.trim()).join(" · ");
}

function days(n: number): string {
  return n >= 1 ? ` ${n} 天` : "";
}

/**
 * 按下去就做得完的事;數字是 0、或這個帳號去不了那一頁的不列。名稱一律 5 個字(一排並列字數一樣)。
 * `store` = 首頁現在看的那一家(全公司 = null):整組的連結帶過去,目的頁照那一家查(全站檢視 R06)。
 * 「匯入待確認」不帶:那一頁沒有門市條件(也不是一張清單,是選批次),數字可能比打開看到的少 —— 記在 COMPLETED。
 */
export function todoGroups(s: TodoSource | undefined, who: NavRole, store: number | null = null): HomeGroup[] {
  if (!s) return [];
  const t = s.transfers_pending;
  const pickup = s.repair_alerts?.pickup;
  const rows = [
    group("transfers", "調撥待入庫", t?.count, withStore("/transfers?pending=1", store),
      (t?.items ?? []).map((x) => ({ key: `t${x.id}`, to: `/transfers/${x.id}`, title: join(x.no, `${x.from_name} → ${x.to_name}`), sub: days(x.days).trim() || undefined }))),
    group("pickup", "維修待取件", pickup?.count, withStore("/repairs?status=ready_pickup", store),
      (pickup?.items ?? []).map((x) => ({ key: `p${x.id}`, to: `/repairs/${x.id}`, title: join(x.customer_name || x.no, x.host_model_name), sub: days(x.ready_days).trim() || undefined }))),
    group("returns", "退回待確認", s.returns_pending, withStore("/serials?status=returned", store)),
    group("intake", "匯入待確認", s.intake_open, "/intake"),
    ...(isManager(who.role)
      ? [group("counts", "盤點待核准", s.counts_pending, withStore("/inventory/stocktake?status=submitted", store))]
      : []),
  ];
  return rows.filter((g) => g.count > 0 && reachable(g.to, who));
}

/** 給管店的人看的(不是這一班按一下就清得掉的);`store` 同上 */
export function noticeGroups(s: TodoSource | undefined, who: NavRole, store: number | null = null): HomeGroup[] {
  if (!s) return [];
  const r = s.repair_alerts;
  const rows = [
    group("overdue", "維修單逾期", r?.overdue_repairs?.count, withStore("/repairs?overdue=1", store),
      (r?.overdue_repairs?.items ?? []).map((x) => ({ key: `o${x.id}`, to: `/repairs/${x.id}`, title: join(x.no, x.customer_name), sub: `逾期${days(x.overdue_days)}` }))),
    group("external", "委外單逾期", r?.overdue_external?.count, withStore("/repairs?overdue=external", store),
      (r?.overdue_external?.items ?? []).map((x) => ({ key: `e${x.id}`, to: `/repairs/${x.id}`, title: join(x.no, x.vendor_name), sub: `逾期${days(x.overdue_days)}` }))),
    group("contracts", "合約待聯絡", s.contracts_pending, withStore("/telecom/expiries", store)),
    group("low", "庫存量不足", s.low_stock?.count, withStore("/inventory/alerts", store),
      (s.low_stock?.items ?? []).map((x) => ({ key: `l${x.id}`, to: withStore("/inventory/alerts", store), title: x.name, sub: `剩 ${x.qty}` }))),
  ];
  return rows.filter((g) => g.count > 0 && reachable(g.to, who));
}

function clock(iso: string): string {
  const d = new Date(iso);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

/**
 * 到貨(owner 2026-10-30:「看到今天入庫的新品,讓進貨資訊與門市人員沒有時差」「還有原本零庫存進貨的也要」):
 * 哪些算新品、哪些算缺貨補進由伺服器定(`inventory/arrivals.py`),這裡只排成兩組。名稱一律 5 個字、0 的不列,
 * 每一項點了到庫存查詢查那個品號;整組沒有要去的頁(`to` 空的,不是連結)。`store` = null(全公司)才寫進了哪幾家。
 */
export function arrivalGroups(s: TodoSource | undefined, store: number | null = null): HomeGroup[] {
  if (!s?.arrivals) return [];
  const rows = (key: string, label: string, g: ArrivalSource): HomeGroup => ({
    key, label, count: g.count, to: "",
    items: g.items.map((x) => ({
      key: `${key}${x.id}`,
      to: `/inventory?search=${encodeURIComponent(x.sku)}`,
      title: x.name,
      sub: join(`+${x.qty}`, store === null ? x.warehouses.join("、") : "", clock(x.at)),
    })),
  });
  return [rows("new", "新品已到貨", s.arrivals.new), rows("restock", "缺貨已補進", s.arrivals.restock)]
    .filter((g) => g.count > 0);
}

/** 首頁選的門市(沒鎖的帳號;記在這台電腦)。看不懂的、已經沒有的門市當成全公司 */
export const HOME_STORE_KEY = "mp_pos_home_store";

export function pickStore(raw: string | null, ids: number[]): number | null {
  const n = Number(raw);
  return Number.isInteger(n) && n > 0 && ids.includes(n) ? n : null;
}

/**
 * 首頁每一區讀資料的狀態(全站檢視 R08):第一次就沒讀到(`failed`,給重試)、讀到過之後重抓失敗(`stale`,
 * 照樣顯示上一次讀到的、標「更新失敗」與那一份是幾點的)、讀到了(`ok`;真的是空的才寫「沒有…」)。
 * 讀不到不能寫成「沒有回溫的商品」「今天還沒有交易」(像真的沒有)。
 */
export type LoadState = "loading" | "failed" | "stale" | "ok";

export function loadState(q: { isLoading: boolean; isError: boolean; hasData: boolean }): LoadState {
  if (q.hasData) return q.isError ? "stale" : "ok";
  if (q.isError) return "failed";
  return "loading";
}
