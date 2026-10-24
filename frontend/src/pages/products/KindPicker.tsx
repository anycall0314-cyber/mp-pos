import type { CategoryKind } from "@/api/types";
import { ChoiceGroup } from "@/components/ui";

const KIND_OPTIONS: { value: CategoryKind; label: string }[] = [
  { value: "device", label: "主機" },
  { value: "accessory", label: "配件" },
  { value: "general", label: "一般" },
];

/** 類別的三種走法。主機 = 品牌 → 型號;配件 = 依手機 / 依廠牌;一般 = 廠牌 → 商品。是表單裡的單選(全站控制項 MC-06),不是分頁 */
export function KindPicker({ value, onChange }: { value: CategoryKind | ""; onChange: (k: CategoryKind) => void }) {
  return <ChoiceGroup label="類別走法" value={value || null} onChange={onChange} options={KIND_OPTIONS} />;
}
