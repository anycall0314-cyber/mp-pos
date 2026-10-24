import { useSalesDefaultSource } from "@/api/hooks";
import { searchCustomers } from "@/api/search";
import { pickableSource } from "@/lib/customerSources";
import type { Customer, Member } from "@/api/types";
import { ComboBox, type ComboOption } from "./ComboBox";

export const DIRECT_SOURCE: ComboOption<Customer> = { id: 0, label: "直客", secondary: "沒有通路／同業來源" };
export function sourceOption(source: Customer | null): ComboOption<Customer> {
  return source ? { id: source.id, label: source.name, secondary: source.kind_label, payload: source } : DIRECT_SOURCE;
}

export function SourcePicker({ source, onChange, disabled, inherit = false, mode = "direct", ariaLabel = "來源" }: {
  source: Customer | null;
  /** 欄名(讀螢幕念的;全站控制項 MC-04) */
  ariaLabel?: string;
  onChange: (source: Customer | null, mode: Member["default_source_mode"]) => void;
  disabled?: boolean;
  inherit?: boolean;
  mode?: Member["default_source_mode"];
}) {
  const defaults = useSalesDefaultSource();
  const inherited: ComboOption<Customer> = { id: -1, label: `沿用銷貨預設（${defaults.data?.customer?.name ?? "直客"}）` };
  const chosen = inherit && mode === "sales_default" ? inherited : sourceOption(source);
  async function search(q: string) {
    const special = inherit ? [inherited, DIRECT_SOURCE] : [DIRECT_SOURCE];
    const matches = await searchCustomers(q);
    return special.filter(o => !q || o.label.includes(q)).concat(matches.filter(o => pickableSource(o.payload)));
  }
  return <ComboBox<Customer>
    value={chosen.id}
    selectedOption={chosen}
    disabled={disabled}
    fetchOptions={search}
    placeholder="直客／通路／同業"
    ariaLabel={ariaLabel}
    onChange={(id, opt) => onChange(opt?.payload ?? null, id === -1 ? "sales_default" : opt?.payload ? "customer" : "direct")}
  />;
}
