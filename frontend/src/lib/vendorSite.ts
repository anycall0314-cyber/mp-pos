// 把叫貨單送進廠商的下單網站(owner 2026-10-13:kcimos 要全自動)。這裡只管叫貨紀錄那一頁怎麼顯示;
// 規則在伺服器(backend/apps/vendor_orders/handoff.py),真正送單的是在廠商網站那一頁裡跑的小幫手。
// 送出去就是真的訂單、不能自己取消:**待確認的單不能再送**,畫面上不給送的按鈕、只給「訂單成立 / 沒有成立」。

export interface SiteState {
  supported: boolean;
  label: string;
  pending: boolean;
  /** 這個時間之前不能按「沒有成立」 */
  can_deny_at?: string | null;
  external_order_no: string;
  memo: string;
}

export interface SiteOrder {
  manual: boolean;
  sent_at: string | null;
  cancelled_at: string | null;
  site?: SiteState | null;
}

const NO_SITE: SiteState = { supported: false, label: "", pending: false, external_order_no: "", memo: "" };

/** 這張單的送單狀態;資料裡沒有那一格(伺服器比畫面舊)當成不能送。 */
export function siteOf(o: SiteOrder): SiteState {
  return o.site ?? NO_SITE;
}

/** 待確認:要人先確認上一次有沒有成立(這時候不能送、也不能自己標已傳)。 */
export function needsResolving(o: SiteOrder): boolean {
  const site = siteOf(o);
  return o.manual && site.supported && site.pending;
}

/**
 * 「沒有成立」什麼時候才可以按(毫秒;0 = 現在就可以)。剛送出的那幾分鐘小幫手可能還在等廠商的網站回答,
 * 訂單查詢上還看不到不代表沒有成立 —— 太早按、再送一次就是兩張訂單。伺服器同一條、它說了算。
 */
export function denyAt(o: SiteOrder): number {
  const at = Date.parse(siteOf(o).can_deny_at ?? "");
  return Number.isFinite(at) ? at : 0;
}

export function canDeny(o: SiteOrder, now: number): boolean {
  return denyAt(o) <= now;
}

/** 待確認的單在「狀況」那一欄寫什麼:還在可能送的那幾分鐘是「送出中」,過了才是「待確認」(字數一樣)。 */
export function pendingMark(o: SiteOrder, now: number): "送出中" | "待確認" {
  return canDeny(o, now) ? "待確認" : "送出中";
}

/** 幾點幾分(給「沒有成立」還不能按的那一句用)。 */
export function clockText(ms: number): string {
  const d = new Date(ms);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

/** 清單上最近一個「送出中 → 待確認」的時間(畫面到時候自己換字);沒有回 0。 */
export function nextFlip(orders: SiteOrder[], now: number): number {
  const times = orders.filter(needsResolving).map(denyAt).filter((t) => t > now);
  return times.length ? Math.min(...times) : 0;
}

/** 這張單現在可以按「自動送單」嗎:廠商有下單網站、還沒傳、沒取消、沒有待確認的。 */
export function canHandOff(o: SiteOrder): boolean {
  return o.manual && siteOf(o).supported && !siteOf(o).pending && !o.sent_at && !o.cancelled_at;
}

/** 可以自己「標記已傳 / 收回標記」嗎:待確認的不行;已經在廠商那邊成立的不能收回(收回就能再送一次)。 */
export function canMarkSent(o: SiteOrder): boolean {
  if (needsResolving(o)) return false;
  return !(o.sent_at && siteOf(o).external_order_no);
}

/** 人填的廠商訂單編號:去頭尾空白;只能是英文、數字、減號,4 到 40 個字(伺服器同一條)。不對回空字串。 */
export function cleanOrderNo(text: string): string {
  const s = text.trim();
  return /^[A-Za-z0-9-]{4,40}$/.test(s) ? s : "";
}

/** 書籤列上那一顆叫什麼(安裝頁與提示用同一個名字)。 */
export function helperName(label: string): string {
  return `${label} 小幫手`;
}

/**
 * 送單要在廠商網站的分頁裡做。**分頁要在按下去的那一下開**(等伺服器回了才開會被瀏覽器擋),先開空白的、拿到網址再帶過去;
 * 沒拿到就關掉。開出來的分頁拿不到這一頁(`opener` 清掉:那邊是別人的網站)。
 * `open` = 開一個空白分頁(被擋回 null);`ask` = 跟伺服器要網址。回 null = 帶過去了;回字串 = 沒送成的原因。
 */
export async function openSiteTab(
  open: () => { opener: unknown; location: { replace(url: string): void }; close(): void } | null,
  ask: () => Promise<{ url: string }>,
  describe: (error: unknown) => string,
): Promise<string | null> {
  const tab = open();
  if (!tab) return "瀏覽器擋住了新分頁,請允許這個網站開新分頁再按一次";
  try {
    tab.opener = null;
  } catch {
    // 有的瀏覽器不給改:不影響送單
  }
  try {
    const got = await ask();
    tab.location.replace(got.url);
    return null;
  } catch (e) {
    tab.close();
    return describe(e);
  }
}

/** 小幫手那一支程式放在哪(跟這一套 POS 同一個網站;`base` = 靜態檔的路徑開頭)。 */
export function helperUrl(origin: string, base: string): string {
  return new URL(`${base}kcimos-helper.js`, origin).toString();
}

/**
 * 書籤裡的那一行:在現在這一頁(廠商的網站)載入小幫手。每次都重新載(後面帶時間),載不到在頁面最上面講一句。
 * 只載入、不做別的:要送什麼、能不能送都是小幫手問 POS。
 */
export function bookmarklet(scriptUrl: string): string {
  const js =
    "(function(){var d=document,s=d.createElement('script');" +
    `s.src=${JSON.stringify(scriptUrl)}+'?t='+Date.now();` +
    "s.onerror=function(){var m=d.createElement('div');m.textContent='載不到 MP POS 小幫手';" +
    "m.style.cssText='position:fixed;top:0;left:0;right:0;z-index:2147483647;padding:12px;background:#b42318;color:#fff;font-size:18px;text-align:center';" +
    "d.body.appendChild(m);setTimeout(function(){m.remove()},5000)};" +
    "d.body.appendChild(s)})();";
  return `javascript:${encodeURIComponent(js)}`;
}
