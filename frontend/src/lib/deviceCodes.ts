/**
 * 一台設備的兩個碼:IMEI 與 SN(可以都有,也可以只有一個)。
 * 判斷規則要跟後端 apps/inventory/identifiers.py 一致。
 */
export type CodeField = "imei" | "sn";

export interface DeviceCodes {
  imei: string;
  sn: string;
}

/** 比對用:去掉空白 / 破折號 / 底線 / 點,轉大寫。 */
export function normalizeCode(text: string | null | undefined): string {
  return (text ?? "")
    .trim()
    .replace(/[\s\-_.]+/g, "")
    .toUpperCase();
}

/** 15 碼數字而且檢查碼正確。只用來猜該放哪一格、提醒打錯,不拿來擋人。 */
export function looksLikeImei(text: string | null | undefined): boolean {
  const nv = normalizeCode(text);
  if (!/^[0-9]{15}$/.test(nv)) return false;
  let total = 0;
  for (let i = 0; i < 15; i++) {
    let n = Number(nv[14 - i]);
    if (i % 2 === 1) {
      n *= 2;
      if (n > 9) n -= 9;
    }
    total += n;
  }
  return total % 10 === 0;
}

/** 沒講是哪一種的單一個碼:像 IMEI 放 IMEI 那一格,否則放 SN。 */
export function splitCode(code: string | null | undefined): DeviceCodes {
  const value = (code ?? "").trim();
  return looksLikeImei(value) ? { imei: value, sn: "" } : { imei: "", sn: value };
}

/** 主碼:有 IMEI 用 IMEI,沒有才用 SN。 */
export function mainCode(c: Partial<DeviceCodes>): string {
  return (c.imei ?? "").trim() || (c.sn ?? "").trim();
}

/** 顯示用:兩個碼都寫出來,只有一個就只寫那一個。 */
export function codesLabel(
  c: Partial<DeviceCodes> & { serial_no?: string },
): string {
  const parts = [
    c.imei ? `IMEI ${c.imei}` : "",
    c.sn ? `SN ${c.sn}` : "",
  ].filter(Boolean);
  return parts.length > 0 ? parts.join(" / ") : (c.serial_no ?? "");
}

/** 長得像 IMEI(14~16 碼數字)但檢查碼不一定對:多半是 IMEI 打錯,不是 SN。 */
function imeiShaped(text: string): boolean {
  return /^[0-9]{14,16}$/.test(normalizeCode(text));
}

/**
 * 把刷到 / 貼上的碼放進「每台兩格」的清單。
 *
 * 手機盒上通常有 IMEI、IMEI2、SN 好幾個條碼,而且 IMEI2 也是檢查碼正確的 15 碼 ——
 * 光看碼分不出「下一台的 IMEI」還是「同一台的 IMEI2」,所以要先知道店家每台刷幾個碼(pair):
 *
 * - pair = false(每台刷一個碼):每個碼就是一台,放到「從目前這一台往下、兩格都還空著的第一台」。
 * - pair = true(每台刷 IMEI 與 SN):先把目前這一台補齊。這一台那一格已經有了、另一格還空著時,
 *   再來一個同類的碼多半是同一台的另一個條碼(IMEI2),**不放**,回報 refused,讓人接著刷缺的那一格。
 *
 * typed = 這個碼是打在(刷在)哪一格、那一格在刷之前是什麼:
 * - 種類跟那一格一樣 → 就是改這一格(原本有值 = 重刷)。
 * - 種類不一樣 → 那一格還原成刷之前的樣子(不會因為刷錯格把原本的碼蓋掉),碼另外放到該放的位置。
 * - 在 IMEI 那一格打了 14~16 碼數字但檢查碼不對 → 當成 IMEI 打錯,留在 IMEI 格(畫面會提醒),不搬去 SN。
 *
 * 回傳 focus = 下一個該刷的位置(一定是空格;沒有就是 null);dropped = 放不下(超過數量)的碼有幾個;
 * refused = 因為「這一台還缺另一格」沒有放的那個碼。
 */
export function routeCodes<T extends DeviceCodes>(
  entries: T[],
  qty: number,
  startIdx: number,
  typed: { field: CodeField; before: string } | null,
  codes: string[],
  blank: () => T,
  pair: boolean,
): {
  entries: T[];
  focus: { idx: number; field: CodeField } | null;
  dropped: number;
  refused: { code: string; missing: CodeField } | null;
} {
  const size = Math.max(qty, entries.length);
  const next = Array.from({ length: size }, (_, i) => ({
    ...(entries[i] ?? blank()),
  }));
  if (typed && startIdx < size) next[startIdx][typed.field] = typed.before;
  const otherOf = (f: CodeField): CodeField => (f === "imei" ? "sn" : "imei");
  let row = startIdx;
  let last: { idx: number; field: CodeField } | null = null;
  let dropped = 0;
  let refused: { code: string; missing: CodeField } | null = null;
  for (const raw of codes) {
    const code = raw.trim();
    if (!code) continue;
    const field: CodeField =
      looksLikeImei(code) || (typed?.field === "imei" && imeiShaped(code))
        ? "imei"
        : "sn";
    let pos = row;
    if (typed && field === typed.field && last === null && !refused) {
      pos = startIdx;
    } else if (pair) {
      if (pos < qty && next[pos][field]) {
        if (!next[pos][otherOf(field)]) {
          refused = { code, missing: otherOf(field) };
          continue;
        }
        while (pos < qty && next[pos][field]) pos++;
      }
      if (pos >= qty) {
        dropped++;
        continue;
      }
    } else {
      while (pos < qty && (next[pos].imei || next[pos].sn)) pos++;
      if (pos >= qty) {
        dropped++;
        continue;
      }
    }
    next[pos][field] = code;
    row = pos;
    last = { idx: pos, field };
  }
  if (refused && row < qty) {
    // 有碼沒放:停在目前這一台還缺的那一格
    return {
      entries: next,
      focus: { idx: row, field: refused.missing },
      dropped,
      refused,
    };
  }
  if (!last) return { entries: next, focus: null, dropped, refused };
  if (pair) {
    for (let r = last.idx; r < qty; r++) {
      for (const field of ["imei", "sn"] as CodeField[]) {
        if (!next[r][field])
          return { entries: next, focus: { idx: r, field }, dropped, refused };
      }
    }
  } else {
    for (let r = last.idx + 1; r < qty; r++) {
      if (!next[r].imei && !next[r].sn)
        return {
          entries: next,
          focus: { idx: r, field: "imei" },
          dropped,
          refused,
        };
    }
  }
  return { entries: next, focus: null, dropped, refused };
}
