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
    return list.map((m) =>
      m.id === retryOf.id ? { ...m, reason: entry.reason } : m,
    );
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
