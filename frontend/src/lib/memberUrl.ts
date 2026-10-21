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

/**
 * 這個網址是消費紀錄分頁(`/members/:id`)→ 只看:不套側邊欄、上面那排(客戶 / 會員),畫面上沒有任何操作
 * (owner 2026-10-21「不用有側邊欄，也不需要有客戶，單純只要消費紀錄，讓分頁無需有任何功能讓門市開了兩個功能pos頁面」)。
 */
export function isMemberHistoryPath(pathname: string): boolean {
  return /^\/members\/[^/]+\/?$/.test(pathname);
}

/** 分頁標題:同時開好幾位會員分得出來。 */
export function memberTabTitle(name: string | undefined | null): string {
  return name ? `會員 ${name}` : "會員";
}

/**
 * 名單點一位 → 消費紀錄分頁(owner 2026-10-20「搜尋號碼點擊，自動開啟分頁，但不要自動跳轉過去，一樣留在原始頁面」)。
 * 瀏覽器不讓網頁自己在背景開分頁(試過假裝 Ctrl / Cmd 點連結、開完叫回原頁、新頁叫回原頁,Chrome 一律切到新分頁),
 * 所以只開一個消費紀錄分頁:第一次開(瀏覽器一定會切過去);之後換成點的那一位,不切過去、留在原頁。
 * 那個分頁被關掉、或被瀏覽器擋下沒開成,下一次再開一個。重新整理原頁之後也是再開一個(記不得之前那一個)。
 */
type Tab = { closed: boolean; location: { href: string } };
let historyTab: Tab | null = null;

export function showMemberHistory(
  id: number,
  open: (url: string, target: string) => Tab | null = (url, target) => window.open(url, target),
): void {
  const url = memberUrl(id);
  if (historyTab && !historyTab.closed) {
    historyTab.location.href = url;
    return;
  }
  historyTab = open(url, "_blank");
}

/** 右邊對照了舊會員 → 開著的消費紀錄分頁換成這一位重新讀;沒開著就不開(開了瀏覽器會切過去)。 */
export function refreshMemberHistory(id: number): void {
  if (historyTab && !historyTab.closed) historyTab.location.href = memberUrl(id);
}
