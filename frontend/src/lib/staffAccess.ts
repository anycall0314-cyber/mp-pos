/**
 * 系統設定 → 員工帳號:身份別與帳號的勾選(owner 2026-10-27:「我要做身份別…或是針對特定帳號做權限調整」)。
 * 帳號跟著身份別走;跟身份別不一樣的是例外。真正的判斷在伺服器(apps/tenants/abilities.py),這裡只管畫面。
 */
import type { AbilityItem, StaffAccount, StaffRole } from "../api/types";

export type Flags = Record<string, boolean>;

/** 身份別的勾選;沒有身份別 = 照預設(預設不開的項目關著,其他開著) */
export function roleFlags(items: AbilityItem[], role: StaffRole | null | undefined): Flags {
  const out: Flags = {};
  for (const it of items) out[it.key] = role ? role.abilities[it.key] !== false : !it.opt_in;
  return out;
}

/** 新帳號預設的身份別:最多人用的(一樣多 → 先建的);沒有身份別 → null */
export function defaultRole(roles: StaffRole[]): StaffRole | null {
  let best: StaffRole | null = null;
  for (const r of roles) if (!best || r.accounts > best.accounts) best = r;
  return best;
}

/** 只送改過的項目(沒動到的「連帶關掉」不會被伺服器擋) */
export function changedFlags(before: Flags, after: Flags): Flags {
  const out: Flags = {};
  for (const [key, value] of Object.entries(after)) if (before[key] !== value) out[key] = value;
  return out;
}

/** 跟身份別不一樣的項目(照清單的順序) */
export function exceptionKeys(items: AbilityItem[], values: Flags, role: Flags): string[] {
  return items.filter((it) => values[it.key] !== role[it.key]).map((it) => it.key);
}

/** 一類勾了幾項 */
export function groupCount(keys: string[], values: Flags): { picked: number; total: number } {
  return { picked: keys.filter((k) => values[k]).length, total: keys.length };
}

/** 整類一起:半選或全沒勾 → 全開;全開 → 全關 */
export function toggleGroup(values: Flags, keys: string[]): Flags {
  const all = keys.length > 0 && keys.every((k) => values[k]);
  const next = { ...values };
  for (const k of keys) next[k] = !all;
  return next;
}

/** 這一項開著、但它要的另外幾項關著:回那幾項的名稱(實際上用不了);都開著 → 空的 */
export function missingNeeds(item: AbilityItem, values: Flags, labels: Record<string, string>): string[] {
  if (!values[item.key]) return [];
  return item.needs.filter((k) => !values[k]).map((k) => labels[k] ?? k);
}

/** 清單搜尋:名字、帳號 */
export function filterAccounts(accounts: StaffAccount[], query: string): StaffAccount[] {
  const q = query.trim().toLowerCase();
  if (!q) return accounts;
  return accounts.filter((a) => a.name.toLowerCase().includes(q) || a.username.toLowerCase().includes(q));
}

/** 清單上的身份別欄:管理員 = 「管理者」 */
export function roleLabel(a: StaffAccount): string {
  if (!a.editable) return "管理者";
  return a.staff_role?.name ?? "—";
}
