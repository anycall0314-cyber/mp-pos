import type { CategoryKind } from "@/api/types";

const KIND_OPTIONS: { key: CategoryKind; label: string }[] = [
  { key: "device", label: "主機" },
  { key: "accessory", label: "配件" },
  { key: "general", label: "一般" },
];

/** 類別的三種走法。主機 = 品牌 → 型號;配件 = 依手機 / 依廠牌;一般 = 廠牌 → 商品 */
export function KindPicker({ value, onChange }: { value: CategoryKind | ""; onChange: (k: CategoryKind) => void }) {
  return (
    <div className="tab-switcher">
      {KIND_OPTIONS.map((o) => (
        <button
          key={o.key}
          type="button"
          className={value === o.key ? "tab-switcher-item active" : "tab-switcher-item"}
          onClick={() => onChange(o.key)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
