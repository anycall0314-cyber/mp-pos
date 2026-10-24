/**
 * 系統設定(業務設定)分成四頁(全站檢視 L02,紅隊改過的做法):
 * - 記住上次看的那一頁 **記在登入的那個人**(櫃台電腦大家輪流用:記在這台電腦的話,店員從開單被送進來會停在老闆昨天看的那一頁)。
 * - 網址帶 `?tab=` 的(開單的「新增字軌」、功能搜尋打「發票字軌 / 付款方式」)直接開那一頁,不理上次。
 * - 分頁只是藏起來:按「儲存」的那幾塊打到一半的留著,分頁上一直標「還沒儲存」,不跳窗、不只提醒一次。
 */
export const SETTINGS_TABS = [
  { key: "general", label: "一般設定" },
  { key: "stores", label: "門市資料" },
  { key: "invoice", label: "發票設定" },
  { key: "payment", label: "付款方式" },
] as const;

export type SettingsTab = (typeof SETTINGS_TABS)[number]["key"];

const KEYS = SETTINGS_TABS.map((t) => t.key) as string[];

export function isSettingsTab(v: string | null | undefined): v is SettingsTab {
  return !!v && KEYS.includes(v);
}

/** 打開時看哪一頁:網址指定的 → 這個人上次看的 → 一般設定 */
export function openingTab(fromUrl: string | null, remembered: string | null): SettingsTab {
  if (isSettingsTab(fromUrl)) return fromUrl;
  if (isSettingsTab(remembered)) return remembered;
  return "general";
}

/** 記在這個帳號底下(同一台電腦換人登入各記各的) */
export function rememberKey(userId: number | string | null | undefined): string | null {
  return userId === null || userId === undefined || userId === "" ? null : `mp_pos_settings_tab:${userId}`;
}

/** 自動存的那一格現在的樣子:存檔中 / 已存 / 沒存成(沒存成時格子裡留著剛改的值,再離開或再點一次就重送) */
export type CellState = "saving" | "saved" | "failed";

export function cellText(state: CellState): string {
  return state === "saved" ? "已存" : state === "failed" ? "沒存成" : "存檔中";
}

/**
 * 勾選 / 單選 / 下拉這種受控的格子:這一頁改過的就照改成的值顯示(存檔中 / 已存 / 沒存成都是),沒改過的照伺服器。
 * 已存也照改成的值:伺服器已經收了,之後重抓清單失敗、手上還是舊資料時不能退回舊的卻寫「已存」(複審 P0)。
 */
export function shownValue<V>(cell: { state: CellState; value: V } | undefined, server: V): V {
  return cell ? cell.value : server;
}

/**
 * 打字的格子離開時要不要送(複審 P0:存檔中改回原值,要跟「剛送出的值」比,不是跟手上的舊資料比):
 * 沒改過 → 跟伺服器比;存檔中 / 已存 → 跟剛送出的值比;沒存成 → 改回伺服器的值就把「沒存成」拿掉,其他照送。
 */
export function blurAction<V>(typed: V, server: V, cell: { state: CellState; value: V } | undefined): "send" | "clear" | "none" {
  if (!cell) return typed !== server ? "send" : "none";
  if (cell.state === "failed") return typed === server ? "clear" : "send";
  return typed !== cell.value ? "send" : "none";
}
