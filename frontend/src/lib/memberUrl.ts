// 會員的消費紀錄一頁(owner 2026-10-20「會員消費紀錄我想要點會員，自動跳分頁，目前瀏覽視窗太小了」):
// 會員名單點一位 → 新分頁打開這個網址,整頁寬、只有消費紀錄;
// 改會員資料在原本那一頁的右邊(同一天:「跳分頁只要顯示消費紀錄不要編輯會員資料，原來的頁面右邊只需顯示編輯欄位」)。

export function memberUrl(id: number): string {
  return `/members/${id}`;
}

/** 網址上的會員編號;不是正整數 = null(照名單那一頁開)。 */
export function memberIdFromRoute(raw: string | undefined): number | null {
  if (!raw || !/^\d+$/.test(raw)) return null;
  const n = Number(raw);
  return n > 0 ? n : null;
}

/** 分頁標題:同時開好幾位會員分得出來。 */
export function memberTabTitle(name: string | undefined | null): string {
  return name ? `會員 ${name}` : "會員";
}
