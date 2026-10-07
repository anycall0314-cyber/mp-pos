/**
 * 掃碼框「沒加入」那一排的記帳規則(純函式,給 components/workbench/ScanBox 用;有測試)。
 *
 * 規則只有一條:**按了 Enter 卻沒進明細的碼一定要有紀錄,而且紀錄不靠輸入框**。
 * 下一個碼刷進來把輸入框蓋掉、人點了別筆重查,原本那一筆都還在;
 * 一筆只有兩種方式會消失:同一個碼後來加成功了,或人按「清掉」。
 * 有紀錄的時候單據不能送出(不然刷了 5 樣、有 1 樣沒加進去,單就少一樣)。
 */
export interface Missed {
  id: number;
  kw: string;
  reason: string;
  /**
   * 這一筆是因為「系統裡找不到它是哪個商品」才沒加進去的(找不到、相似的太多、不是完全相同):
   * 頁面有提供當場建商品的話,這一筆旁邊會有「建立」。
   * 其他原因(已停用、這張單已經送出、那一台在別的地方、連線錯誤)不是「沒建過」,沒有這一顆。
   */
  creatable?: boolean;
}

/** 沒加進去的原因是哪一種:找商品時沒有定案(可以當場建) / 其他 */
export type MissKind = "unresolved" | "other";

/** 記一筆「沒加入」要用的內容 */
export function missedEntry(id: number, kw: string, reason: string, kind: MissKind): Missed {
  return kind === "unresolved" ? { id, kw, reason, creatable: true } : { id, kw, reason };
}

/**
 * 這個碼沒加進去。
 * retryOf = 這次是人把清單裡的某一筆放回輸入框重查:結果算在那一筆上(換原因),不另外多一筆。
 * 其他情況一律多一筆 —— 同一個碼失敗幾次就記幾筆(刷了 5 個同樣的配件都沒加進去,要補 5 次)。
 */
export function addMissed(
  list: Missed[],
  entry: Missed,
  retryOf: Missed | null,
): Missed[] {
  if (retryOf && list.some((m) => m.id === retryOf.id)) {
    // 重查的結果整個換掉:原因換了,「能不能當場建」也跟著這一次的原因走
    return list.map((m) => {
      if (m.id !== retryOf.id) return m;
      const { creatable: _before, ...rest } = m;
      return entry.creatable ? { ...rest, reason: entry.reason, creatable: true } : { ...rest, reason: entry.reason };
    });
  }
  return [...list, entry];
}

/**
 * 這個碼加成功了:如果它記在「沒加入」,劃掉一筆。
 * 重查的就劃掉重查的那一筆;不然劃掉同一個碼最早的那一筆。別的碼的紀錄不動。
 */
export function resolveMissed(
  list: Missed[],
  kw: string,
  retryOf: Missed | null,
): Missed[] {
  const at =
    retryOf && list.some((m) => m.id === retryOf.id)
      ? list.findIndex((m) => m.id === retryOf.id)
      : list.findIndex((m) => m.kw === kw);
  if (at < 0) return list;
  const next = [...list];
  next.splice(at, 1);
  return next;
}

/**
 * 頁面當場找到 / 建好了商品、已經加進明細:「沒加入」要劃掉哪一筆。
 * - 有指定是哪一筆開始的(`entry`):**只劃那一筆**。那一筆已經不在了(人先按了清掉、或被別的方式劃掉)就什麼都不劃 ——
 *   不能退而求其次去劃「同一個碼的另一筆」:那一筆是另一次刷的、還沒進明細,劃掉單據就少一樣。
 * - 沒有指定(從下拉開始的):跟平常加成功一樣,劃同一個碼最早的那一筆(沒有就不動)。
 */
export function settleCreated(list: Missed[], kw: string, entry: Missed | null): Missed[] {
  if (!entry) return resolveMissed(list, kw, null);
  return list.some((m) => m.id === entry.id) ? list.filter((m) => m.id !== entry.id) : list;
}

/**
 * 同上那一刻,「放回輸入框重查的那一筆」(`retrying`)要不要一起放掉:
 * 只有它就是這一趟的那一筆;或這一趟沒有指定哪一筆、而輸入框現在還是這串字、重查的也正是這串字。
 * 其他情況(人已經點了別筆放回輸入框)不能動:不然他接著按 Enter,結果不會算在他點的那一筆上。
 */
export function retryAfterCreated(
  retrying: Missed | null,
  kw: string,
  entry: Missed | null,
  inputText: string,
): Missed | null {
  if (!retrying) return null;
  if (entry) return retrying.id === entry.id ? null : retrying;
  return retrying.kw === kw && inputText.trim() === kw.trim() ? null : retrying;
}

/**
 * 輸入框現在要送出的這串字,是不是「放回來重查的那一筆」。
 * 字不一樣(人改過、或被下一個碼蓋掉)就不是:那是新的一次,原本那一筆照樣留著。
 */
export function retryTarget(
  retrying: Missed | null,
  kw: string,
): Missed | null {
  return retrying && retrying.kw === kw ? retrying : null;
}

/** 現在能不能送出單據:回一句話 = 不能(原因);null = 可以。 */
export function scanBlocker(list: Missed[], inputText: string): string | null {
  if (list.length > 0) {
    return "「沒加入」那一排還有碼:處理好或按清掉,再確認";
  }
  const left = inputText.trim();
  if (left) return `掃碼框裡的「${left}」還沒加進去:加進去或清掉,再確認`;
  return null;
}
