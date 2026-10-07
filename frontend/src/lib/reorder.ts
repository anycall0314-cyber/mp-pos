/**
 * 拖拉排序(類別、供應商)的規則。只有這一份,有測試(`reorder.test.mjs`)。
 *
 * 順序存在每一列的 `sort_order`(小的在前;一樣的照代碼)。拖一列放到另一列上 = 搬到那一列的位置,
 * 整份重新編號(10、20、30…),只把編號有變的那幾列各存一次。
 *
 * 為什麼要有 `createReorderQueue`:以前是「放開 → 每一列各存一次 → 每存一列就重抓一次清單 → 全部回來畫面才換」。
 * 隔著網路時 18 個類別要等 5 秒以上,這段時間畫面沒有任何變化,看起來就像沒拖成;人再拖一次,
 * 又是照畫面上那一份舊順序算的,越拖越亂(還會留下兩列同一個編號)。現在:
 * - **放開的當下畫面就換**(`show`);
 * - 存檔在背景做,**一次拖動存完才存下一次**(下一次拖動是照畫面上已經換過的順序算的,兩次的存檔不能交錯);
 * - **全部存完才重抓一次**(`settle`);
 * - 有一列沒存成:等同一次的其他列都有結果,後面排隊的不存了,重抓伺服器現在的順序、講出來(`settle(false)`)。
 */

export interface Sortable {
  id: number;
  sort_order: number;
  code: string;
}

export interface OrderChange {
  id: number;
  sort_order: number;
}

/** 畫面上的順序:編號小的在前,編號一樣照代碼。 */
export function bySortOrder(a: Sortable, b: Sortable): number {
  return a.sort_order - b.sort_order || a.code.localeCompare(b.code);
}

export function inOrder<T extends Sortable>(list: readonly T[]): T[] {
  return [...list].sort(bySortOrder);
}

/**
 * 把 `srcId` 那一列搬到 `targetId` 那一列的位置,回整份重新編號過的清單(照新順序)。
 * 沒有東西要動(同一列、找不到其中一列)回 null。
 */
export function moveRow<T extends Sortable>(
  list: readonly T[],
  srcId: number,
  targetId: number,
): T[] | null {
  if (srcId === targetId) return null;
  const rows = inOrder(list);
  const from = rows.findIndex((r) => r.id === srcId);
  const to = rows.findIndex((r) => r.id === targetId);
  if (from < 0 || to < 0) return null;
  const [moved] = rows.splice(from, 1);
  rows.splice(to, 0, moved);
  return rows.map((r, i) => ({ ...r, sort_order: (i + 1) * 10 }));
}

/** 要存的那幾列:編號跟「伺服器現在有的」(`saved`)不一樣的。 */
export function changedRows(
  saved: readonly Sortable[],
  wanted: readonly Sortable[],
): OrderChange[] {
  const known = new Map(saved.map((r) => [r.id, r.sort_order]));
  return wanted
    .filter((r) => known.get(r.id) !== r.sort_order)
    .map((r) => ({ id: r.id, sort_order: r.sort_order }));
}

export interface ReorderDeps<T extends Sortable> {
  /** 畫面現在那一份清單 */
  read: () => readonly T[];
  /** 把畫面換成這一份(還沒存) */
  show: (rows: T[]) => void;
  /** 存一列的編號 */
  save: (change: OrderChange) => Promise<unknown>;
  /** 排隊的都做完了:重抓一次伺服器的清單;`ok` = 是不是全部存成。重抓沒成就丟錯(畫面那一份就不當成伺服器有的) */
  settle: (ok: boolean) => void | Promise<void>;
}

export interface ReorderQueue {
  /** 拖 `srcId` 放到 `targetId` 上。有東西要動回 true(畫面已經換了、存檔排進去了)。 */
  move: (srcId: number, targetId: number) => boolean;
  /** 排隊的存檔都做完(含最後那一次重抓)時完成。測試用。 */
  idle: () => Promise<void>;
}

export function createReorderQueue<T extends Sortable>(
  deps: ReorderDeps<T>,
): ReorderQueue {
  let chain: Promise<void> = Promise.resolve();
  let waiting = 0; // 排著還沒做完的拖動有幾次
  // 伺服器現在有的那一份(只用來算「哪幾列要存」):每存完一次拖動就換成那一次的
  let saved: readonly Sortable[] = [];
  // 畫面上那一份是不是就是伺服器有的。有一次沒存成之後就不是了(畫面換了、伺服器沒換),
  // 要等重抓回來才又是;這段時間再拖,就當成伺服器什麼都沒有 → 每一列都存(存完一定是畫面上那個順序)
  let trusted = true;
  let failed = false; // 這一輪有沒有哪一次沒存成

  async function run(wanted: T[]) {
    if (!failed) {
      // 等這一次的每一列都有結果(存成或沒存成)才往下:有一列先失敗就去重抓的話,
      // 還在路上的那幾列會在重抓之後才寫進伺服器,重抓到的那一份就是舊的
      const results = await Promise.allSettled(
        changedRows(saved, wanted).map(async (change) => deps.save(change)),
      );
      if (results.some((r) => r.status === "rejected")) {
        failed = true;
        trusted = false;
      } else {
        saved = wanted;
      }
    }
    waiting -= 1;
    if (waiting > 0) return;
    const ok = !failed;
    failed = false;
    try {
      await deps.settle(ok);
      trusted = true; // 重抓回來了(下一次拖動的存檔排在這之後才開始)
    } catch {
      trusted = false; // 重抓沒成:畫面那一份不能當成伺服器有的
    }
  }

  return {
    move(srcId, targetId) {
      const shown = deps.read();
      const wanted = moveRow(shown, srcId, targetId);
      if (!wanted) return false;
      if (waiting === 0) saved = trusted ? shown : [];
      waiting += 1;
      deps.show(wanted);
      chain = chain.then(() => run(wanted));
      return true;
    },
    idle: () => chain,
  };
}
