// 序號防呆:輸入的當下就提醒「這一台已經在系統裡」/「這張單裡重複了」。跑法:npm test。
// 伺服器存檔時一定會擋(同一個碼只要沒作廢就不能再進);這裡只是提早講,讓人不用整張單打完才知道。
// **不默默拿掉任何一個碼**:有問題的留在格子裡標出來,由人處理(紅隊:貼三十支被剔三支,單上二十七、手上三十,帳實就對不起來)。
import { normalizeCode, type DeviceCodes } from "./deviceCodes.ts";

/** 伺服器說這個碼已經被哪一台用掉了。 */
export interface TakenInfo {
  code: string;
  product_name: string;
  product_sku: string;
  /** 在哪家門市;已售、調撥中的不掛在任何門市(空的) */
  warehouse_name: string;
  status: string;
  status_label: string;
  /** 還在店裡(在庫 / 調撥中 / 維修中);false = 已經不在了(已售 / 已退) */
  in_store: boolean;
}

/** 查過的結果。鍵 = 去掉符號的碼;null = 查過了,沒有人用;沒有這個鍵 = 還沒查。 */
export type CheckCache = Record<string, TakenInfo | null>;

/** 這幾台設備的每一個碼(IMEI、SN;空的不算)。 */
export function codesOf(units: Partial<DeviceCodes>[]): string[] {
  const out: string[] = [];
  for (const u of units) {
    for (const code of [u.imei, u.sn]) {
      const text = (code ?? "").trim();
      if (text) out.push(text);
    }
  }
  return out;
}

/** 還沒查過的碼(同一個碼的不同寫法只問一次)。 */
export function toAsk(codes: string[], cache: CheckCache): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const code of codes) {
    const key = normalizeCode(code);
    if (!key || key in cache || seen.has(key)) continue;
    seen.add(key);
    out.push(code.trim());
  }
  return out;
}

/** 把伺服器的答覆記下來:問了、沒在「已經有」那幾個裡的,記成沒有人用。 */
export function withAnswer(cache: CheckCache, asked: string[], taken: TakenInfo[]): CheckCache {
  const next = { ...cache };
  for (const code of asked) next[normalizeCode(code)] = null;
  for (const info of taken) next[normalizeCode(info.code)] = info;
  return next;
}

/** 這張單裡出現兩次以上的碼(IMEI、SN 一起比;去掉符號、不分大小寫)。 */
export function duplicateKeys(codes: string[]): Set<string> {
  const count = new Map<string, number>();
  for (const code of codes) {
    const key = normalizeCode(code);
    if (key) count.set(key, (count.get(key) ?? 0) + 1);
  }
  return new Set([...count].filter(([, n]) => n > 1).map(([key]) => key));
}

/** 那一台現在在哪:「甲民生店 · 在庫」;不掛在門市的只寫狀態(「已售」「調撥中」)。 */
export function whereText(info: Pick<TakenInfo, "warehouse_name" | "status_label">): string {
  return [info.warehouse_name, info.status_label].filter(Boolean).join(" · ");
}

/** 進貨:這個碼已經在系統裡。 */
export function takenText(info: TakenInfo): string {
  return `已經在系統裡:${info.product_name}(${whereText(info)})`;
}

/**
 * 個人收購:分兩種講(紅隊:只講「已經在系統裡」,店員會當成錄錯或贓貨把客人請走)。
 * 還在店裡的 = 同一個序號不可能有兩台,要核對實機;已經賣出去的 = 是我們賣的,收回來的功能還沒有,先不要收。
 */
export function buybackText(info: TakenInfo): string {
  return info.in_store
    ? `這一台還在店裡:${info.product_name}(${whereText(info)})。同一個序號不會有兩台,請核對實機`
    : `這一台是我們賣出去的:${info.product_name}。賣出去再收回來的功能還沒有,先不要收`;
}

export const DUPLICATE_TEXT = "這張單裡重複了";

/**
 * 這張單每一個有問題的碼 → 為什麼(鍵 = 去掉符號的碼)。已經在系統裡的優先講(那是改不掉的);其次才是單內重複。
 * 還沒查到答案的不算有問題(存檔時伺服器照樣會擋)。
 */
export function problemsOf(codes: string[], cache: CheckCache): Record<string, string> {
  const out: Record<string, string> = {};
  const dups = duplicateKeys(codes);
  for (const code of codes) {
    const key = normalizeCode(code);
    if (!key || key in out) continue;
    const info = cache[key];
    if (info) out[key] = takenText(info);
    else if (dups.has(key)) out[key] = DUPLICATE_TEXT;
  }
  return out;
}

/** 一個碼有沒有問題(格子底下那一句;沒有就是空字串)。 */
export function problemOf(code: string | null | undefined, problems: Record<string, string>): string {
  const key = normalizeCode(code);
  return key ? (problems[key] ?? "") : "";
}

/** 存檔前擋下來時講的那一句:列出前幾個,其餘寫還有幾個。 */
export function blockText(codes: string[], problems: Record<string, string>, show = 3): string | null {
  const seen = new Set<string>();
  const bad: string[] = [];
  for (const code of codes) {
    const key = normalizeCode(code);
    if (!key || seen.has(key) || !(key in problems)) continue;
    seen.add(key);
    bad.push(`${code.trim()} ${problems[key]}`);
  }
  if (bad.length === 0) return null;
  const more = bad.length > show ? `;還有 ${bad.length - show} 個` : "";
  return `序號有問題:${bad.slice(0, show).join(";")}${more}`;
}

/** 一次最多問幾個(跟伺服器的上限一樣);超過就分幾次問。 */
export const ASK_LIMIT = 500;

export function chunks<T>(list: T[], size = ASK_LIMIT): T[][] {
  const out: T[][] = [];
  for (let i = 0; i < list.length; i += size) out.push(list.slice(i, i + size));
  return out;
}
