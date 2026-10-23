/**
 * 今日總覽(2026-10-23,UI 改善計劃 6.1;全站檢視 G7)。
 *
 * 紅隊三條:
 *  1. 快捷是櫃檯動作(開銷貨單、代收話費、查詢庫存、維修收件),帳號看不到那一頁的收起來;
 *  2. 「待辦」只放按下去就做得完的佇列(調撥待入庫、維修待取件、退回待確認、匯入待確認、盤點待核准);
 *     庫存不足、逾期、合約待聯絡是給管店的人看的「注意」,分開放;
 *  3. 每一區跟著同一個門市範圍(鎖門市 = 那一家;沒鎖 = 全公司或首頁選的那一家)。
 *
 * 這一份只決定「有哪幾組、點了去哪、誰看得到」;數字由伺服器 `home-summary` 給。
 */
import { isManager, matchForUser, type NavRole } from "../nav.ts";

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
}

/** 首頁的主要快捷:名字是動作、字數一樣 */
export const QUICK_ACTIONS = [
  { to: "/sales/new", label: "開銷貨單" },
  { to: "/telecom/billing", label: "代收話費" },
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

/** 按下去就做得完的事;數字是 0、或這個帳號去不了那一頁的不列。名稱一律 5 個字(一排並列字數一樣) */
export function todoGroups(s: TodoSource | undefined, who: NavRole): HomeGroup[] {
  if (!s) return [];
  const t = s.transfers_pending;
  const pickup = s.repair_alerts?.pickup;
  const rows = [
    group("transfers", "調撥待入庫", t?.count, "/transfers?pending=1",
      (t?.items ?? []).map((x) => ({ key: `t${x.id}`, to: `/transfers/${x.id}`, title: join(x.no, `${x.from_name} → ${x.to_name}`), sub: days(x.days).trim() || undefined }))),
    group("pickup", "維修待取件", pickup?.count, "/repairs?status=ready_pickup",
      (pickup?.items ?? []).map((x) => ({ key: `p${x.id}`, to: `/repairs/${x.id}`, title: join(x.customer_name || x.no, x.host_model_name), sub: days(x.ready_days).trim() || undefined }))),
    group("returns", "退回待確認", s.returns_pending, "/serials?status=returned"),
    group("intake", "匯入待確認", s.intake_open, "/intake"),
    ...(isManager(who.role) ? [group("counts", "盤點待核准", s.counts_pending, "/inventory/stocktake?status=submitted")] : []),
  ];
  return rows.filter((g) => g.count > 0 && reachable(g.to, who));
}

/** 給管店的人看的(不是這一班按一下就清得掉的) */
export function noticeGroups(s: TodoSource | undefined, who: NavRole): HomeGroup[] {
  if (!s) return [];
  const r = s.repair_alerts;
  const rows = [
    group("overdue", "維修單逾期", r?.overdue_repairs?.count, "/repairs?overdue=1",
      (r?.overdue_repairs?.items ?? []).map((x) => ({ key: `o${x.id}`, to: `/repairs/${x.id}`, title: join(x.no, x.customer_name), sub: `逾期${days(x.overdue_days)}` }))),
    group("external", "委外單逾期", r?.overdue_external?.count, "/repairs?overdue=external",
      (r?.overdue_external?.items ?? []).map((x) => ({ key: `e${x.id}`, to: `/repairs/${x.id}`, title: join(x.no, x.vendor_name), sub: `逾期${days(x.overdue_days)}` }))),
    group("contracts", "合約待聯絡", s.contracts_pending, "/telecom/expiries"),
    group("low", "庫存量不足", s.low_stock?.count, "/inventory/alerts",
      (s.low_stock?.items ?? []).map((x) => ({ key: `l${x.id}`, to: "/inventory/alerts", title: x.name, sub: `剩 ${x.qty}` }))),
  ];
  return rows.filter((g) => g.count > 0 && reachable(g.to, who));
}

/** 首頁選的門市(沒鎖的帳號;記在這台電腦)。看不懂的、已經沒有的門市當成全公司 */
export const HOME_STORE_KEY = "mp_pos_home_store";

export function pickStore(raw: string | null, ids: number[]): number | null {
  const n = Number(raw);
  return Number.isInteger(n) && n > 0 && ids.includes(n) ? n : null;
}
