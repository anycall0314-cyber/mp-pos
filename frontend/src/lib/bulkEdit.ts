/**
 * 批次修改的屬性:每一個各自「不改 / 是 / 否」,預設不改(全站檢視 D9)。
 * 以前勾「修改屬性」五個一起送,「需追蹤序號」沒勾的話,還沒進過貨的品號會悄悄變成不追序號。
 */

export type Tri = "keep" | "yes" | "no";

export const ATTRS = [
  ["requires_serial", "需追蹤序號"],
  ["allows_telecom_line", "可綁門號合約"],
  ["allows_commission", "可有業務員佣金"],
  ["counts_cash", "計入現金"],
  ["counts_margin", "計入毛利"],
] as const;

export type AttrKey = (typeof ATTRS)[number][0];

export const TRI_CHOICES: readonly [Tri, string][] = [
  ["keep", "不改"],
  ["yes", "是"],
  ["no", "否"],
];

export function keepAll(): Record<AttrKey, Tri> {
  return Object.fromEntries(ATTRS.map(([k]) => [k, "keep"])) as Record<AttrKey, Tri>;
}

/** 只送有選的那幾個 */
export function attrPatch(attrs: Record<AttrKey, Tri>): Partial<Record<AttrKey, boolean>> {
  const out: Partial<Record<AttrKey, boolean>> = {};
  for (const [k] of ATTRS) {
    if (attrs[k] === "yes") out[k] = true;
    else if (attrs[k] === "no") out[k] = false;
  }
  return out;
}

/**
 * 草稿載回來:只認這一版存的「不改 / 是 / 否」。
 * 以前的草稿存的是勾不勾(true / false = 五個一起送的那種),一律當成不改 —— 不能把那個錯的預設帶回來。
 */
export function attrsFromDraft(saved: unknown): Record<AttrKey, Tri> {
  const out = keepAll();
  if (saved && typeof saved === "object") {
    for (const [k] of ATTRS) {
      const v = (saved as Record<string, unknown>)[k];
      if (v === "yes" || v === "no") out[k] = v;
    }
  }
  return out;
}

/** 確認視窗裡的那一句(用畫面上的名字,不寫欄位代碼) */
export function attrSummary(attrs: Record<AttrKey, Tri>): string[] {
  return ATTRS.filter(([k]) => attrs[k] !== "keep").map(([k, label]) => `${label}:${attrs[k] === "yes" ? "是" : "否"}`);
}
