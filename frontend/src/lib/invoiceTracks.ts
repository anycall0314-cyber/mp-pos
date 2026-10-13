// 發票字軌在畫面上的規則(owner 2026-10-13):期別怎麼選、跳號視窗先講會發生什麼事、這條字軌現在是什麼狀態。
// 真正擋的是伺服器(backend/apps/tenants/services.py、serializers.py);這裡只算要顯示的字,讓人按確定之前看得懂。

/** 兩個月一期:每一期第一個月(奇數月)。 */
export const PERIOD_MONTHS = [1, 3, 5, 7, 9, 11] as const;

/** 一期的第一天(伺服器記的就是這個日期,例 `2026-11-01`)。年是民國年;年或月不對回空字串。 */
export function periodStart(rocYear: number, firstMonth: number): string {
  if (!Number.isInteger(rocYear) || rocYear < 1 || rocYear > 999) return "";
  if (!PERIOD_MONTHS.includes(firstMonth as (typeof PERIOD_MONTHS)[number])) return "";
  return `${rocYear + 1911}-${String(firstMonth).padStart(2, "0")}-01`;
}

/** `2026-11-01` → 民國年與那一期的第一個月;讀不出來(沒登記期別的舊字軌)回 null。 */
export function periodParts(start: string | null | undefined): { rocYear: number; firstMonth: number } | null {
  const m = /^(\d{4})-(\d{2})-01$/.exec(start ?? "");
  if (!m) return null;
  const year = Number(m[1]);
  const month = Number(m[2]);
  if (year <= 1911 || !PERIOD_MONTHS.includes(month as (typeof PERIOD_MONTHS)[number])) return null;
  return { rocYear: year - 1911, firstMonth: month };
}

/** 月份選單上的字:`11-12月`。 */
export function monthsLabel(firstMonth: number): string {
  return `${firstMonth}-${firstMonth + 1}月`;
}

/** 今天是哪一期(新增字軌時預設選這一期)。 */
export function periodOf(today: Date): { rocYear: number; firstMonth: number } {
  const month = today.getMonth() + 1;
  return { rocYear: today.getFullYear() - 1911, firstMonth: month % 2 ? month : month - 1 };
}

/** 發票號碼:字軌 + 8 位數。 */
export function invoiceNo(prefix: string, n: number): string {
  return `${prefix}${String(n).padStart(8, "0")}`;
}

export interface TrackRange {
  prefix: string;
  range_start: number;
  range_end: number;
  next_number: number;
}

/**
 * 跳號視窗裡打的字 → 號碼。只打數字、或連字軌一起打(`AB12345690`)都收;空白不算。
 * 讀不出來、字軌不是這一條的 → null。
 */
export function parseJumpInput(track: Pick<TrackRange, "prefix">, text: string): number | null {
  let s = text.replace(/\s+/g, "").toUpperCase();
  const prefix = track.prefix.toUpperCase();
  if (prefix && s.startsWith(prefix)) s = s.slice(prefix.length);
  if (!/^\d{1,8}$/.test(s)) return null;
  return Number(s);
}

export interface JumpPreview {
  /** 可以送出 */
  ok: boolean;
  /** 往後跳、往回改,或還不能送 */
  kind: "forward" | "back" | "none";
  /** 給人看的一句 */
  text: string;
}

/**
 * 按確定之前先講會發生什麼事。打的是「紙上的下一張」:
 * - 往後:中間那幾號不開了,寫出是哪幾號、共幾張。
 * - 往回:系統的下一張會倒回去 —— 提醒要跟紙對(紙不會自己倒回去)。
 * 那一號之後開過沒有只有伺服器知道,那邊會擋。
 */
export function jumpPreview(track: TrackRange, text: string): JumpPreview {
  if (!text.trim()) return { ok: false, kind: "none", text: "" };
  const n = parseJumpInput(track, text);
  const no = (x: number) => invoiceNo(track.prefix, x);
  if (n === null) return { ok: false, kind: "none", text: "請輸入號碼" };
  if (n < track.range_start || n > track.range_end + 1) {
    return { ok: false, kind: "none", text: `要在 ${no(track.range_start)} ~ ${no(track.range_end)} 之間` };
  }
  if (n === track.next_number) return { ok: false, kind: "none", text: "跟系統一樣,不用跳" };
  if (n > track.next_number) {
    const count = n - track.next_number;
    const skipped = count === 1 ? no(track.next_number) : `${no(track.next_number)} ~ ${no(n - 1)}`;
    const rest = n > track.range_end ? ";這條字軌用完" : "";
    return { ok: true, kind: "forward", text: `跳過 ${count} 張:${skipped}${rest}` };
  }
  return { ok: true, kind: "back", text: `往回 ${track.next_number - n} 張,下一張開 ${no(n)};先確認紙上是這一號` };
}

/** 跳號紀錄的一列:往後跳了幾張、或往回改了幾張。 */
export function jumpSummary(jump: { from_number: number; to_number: number }): string {
  const count = jump.to_number - jump.from_number;
  return count > 0 ? `跳過 ${count} 張` : `往回 ${-count} 張`;
}

export interface TrackState {
  is_active: boolean;
  is_depleted: boolean;
  period_state: "" | "past" | "now" | "future";
}

/** 字軌清單「狀態」那一欄(一種寫一個詞,字數一樣)。先看停用、再看期別、再看用完。 */
export function trackStateLabel(t: TrackState): string {
  if (!t.is_active) return "已停用";
  if (t.period_state === "past") return "已過期";
  if (t.is_depleted) return "已用完";
  if (t.period_state === "future") return "未開始";
  return "使用中";
}

/** 這條字軌現在開不開得出號碼(清單上「下一張」要不要寫成綠色的號碼)。 */
export function trackUsable(t: TrackState): boolean {
  return trackStateLabel(t) === "使用中";
}
