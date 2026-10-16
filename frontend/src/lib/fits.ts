/** 配件的適用機型寫成一行(商品列表的品名底下、商品詳情)。店內品名常看不懂(`IPAD/AIR4-8/11吋`),這一行寫型號庫的名稱。 */
export function fitsLine(hosts: { model_name: string }[] | undefined, max = 3): string {
  const names = [...new Set((hosts ?? []).map((h) => h.model_name).filter(Boolean))];
  if (names.length === 0) return "";
  const shown = names.slice(0, max).join("、");
  return names.length > max ? `適用 ${shown} 等 ${names.length} 款` : `適用 ${shown}`;
}
