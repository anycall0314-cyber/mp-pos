/**
 * 下拉的 Enter「完全相同才自動選」用的比法(全站檢視 A2;給 `ComboBox` 的 `exactOnEnter`)。
 * 去掉空白與連字號、不分大小寫。
 */
const plain = (s: string | null | undefined) => (s ?? "").replace(/[\s-]/g, "").toUpperCase();

/** SIM 卡:卡號一字不差(條碼槍刷整張卡號) */
export function sameCardNo(opt: { label: string }, query: string): boolean {
  const q = plain(query);
  return q !== "" && plain(opt.label) === q;
}

/** 會員:電話、統編、身分證、會員號、名稱其中一個一字不差 */
export function sameMember(
  opt: { label: string; payload?: { phone?: string; tax_id?: string; national_id?: string | null; code?: string; name?: string } },
  query: string,
): boolean {
  const q = plain(query);
  if (q === "") return false;
  const m = opt.payload;
  return [m?.phone, m?.tax_id, m?.national_id, m?.code, m?.name ?? opt.label].some((v) => plain(v) === q);
}
