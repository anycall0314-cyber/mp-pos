import type { Customer, Member } from "../api/types";

export function memberSource(member: Member | null, salesDefault: Customer | null): Customer | null {
  if (!member || member.default_source_mode === "sales_default" || !member.default_source_mode) return salesDefault;
  return member.default_source_mode === "direct" ? null : member.default_customer_detail;
}

export function sourceAfterMemberChange(
  current: Customer | null, manual: boolean, member: Member | null, salesDefault: Customer | null,
): { source: Customer | null; keptManual: boolean } {
  const next = memberSource(member, salesDefault);
  return { source: manual ? current : next, keptManual: manual && (current?.id ?? null) !== (next?.id ?? null) };
}

export function taxAfterMemberChange(current: string, manual: boolean, member: Member | null): string {
  return manual ? current : member?.kind === "company" ? member.tax_id : "";
}

/**
 * 開單時會員格打了字、找不到,按「新增會員」:打的是電話(去掉空白 / 連字號後 8 碼以上的數字)就帶進電話,
 * 不是就帶進姓名(全站檢視 A3:以前要從頭重打)。
 */
export function memberPrefill(typed: string): { phone: string; name: string } {
  const t = typed.trim();
  // 另一格清空:上一次開了又關掉的那一位的資料不能留著混成同一位(複審 P2)
  return /^\d{8,}$/.test(t.replace(/[\s-]/g, "")) ? { phone: t, name: "" } : { phone: "", name: t };
}

/** 新增會員的姓名是一長串數字 / 英數碼 = 多半是刷到條碼了(紅隊:游標停在姓名,接著刷商品會刷進來) */
export function nameLooksScanned(name: string): boolean {
  const t = name.trim();
  return /^\d{8,}$/.test(t) || /^[A-Z0-9]{10,}$/.test(t);
}

/**
 * 新的單、會員的預設能不能選這個來源:停用的不行;「個人(舊類別)」不行(全站檢視 E1 紅隊:
 * 那是以前個人收購自動建的、跟會員同名,選進新單會讓同一支電話又多一套紀錄)。舊單上已經掛著的照樣顯示。
 */
export function pickableSource(source: Pick<Customer, "is_active" | "kind"> | undefined): boolean {
  return !!source && source.is_active && source.kind !== "individual";
}
