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
