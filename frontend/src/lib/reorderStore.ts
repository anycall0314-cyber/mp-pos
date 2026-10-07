/**
 * 拖拉排序接到清單快取的那一段(不碰 React、不碰專案別的檔;測試用真的 QueryClient 跑,`reorderStore.test.mjs`)。
 * 排隊與「哪幾列要存」的規則在 `reorder.ts`;畫面那一側只有 `hooks/useReorder` 幾行。
 *
 * 這一段管三件 `reorder.ts` 管不到的事:
 * 1. **一份清單只有一條佇列,不跟著畫面走**(放在這個模組裡)。存到一半切到別頁再回來還是同一條;
 *    每個畫面各開一條的話,新的那一條會把畫面上「還沒存完的順序」當成伺服器已經有的。
 *    沒存成的訊息也留在這裡:切走再回來還看得到。
 * 2. **真的重抓到了才算重抓**。人已經切到別頁時,一般的「讓它過期」不會真的去抓(沒有畫面在用這一份);
 *    那樣快取裡還是沒存成的順序,卻被當成伺服器有的 —— 下一次拖動就會少存。所以不管有沒有畫面在用都去抓,
 *    而且要看到這一份真的被換過才算。
 * 3. **換了登入狀態,舊的佇列就作廢**:還沒送的不送(不然會用下一個人的身分送出去),
 *    收尾也不碰新登入狀態的快取與訊息;新的登入狀態用新的一條。
 */
import type { QueryClient, QueryKey } from "@tanstack/query-core";

import { createReorderQueue, type OrderChange, type Sortable } from "./reorder.ts";

export interface ReorderOptions {
  /** 清單在快取裡的鑰匙(例:`["categories"]`);快取裡放的是一個陣列 */
  queryKey: QueryKey;
  /** 存一列用的網址(例:`(id) => \`/categories/${id}/\``) */
  path: (id: number) => string;
  /** 全部存完之後要一起重抓的其他清單(例:類別順序會影響商品清單);不等它 */
  alsoRefresh?: QueryKey[];
}

export interface ReorderEnv {
  /** 存一列的編號(PATCH) */
  save: (path: string, body: { sort_order: number }) => Promise<unknown>;
  /** 現在是第幾次登入狀態(登入、登出、登入失效都會換) */
  session: () => number;
}

export interface ListReorder {
  /** 這一條佇列屬於第幾次登入狀態 */
  readonly session: number;
  /** 拖 `srcId` 放到 `targetId` 上;有東西要動回 true(畫面換了、存檔排進去了、上一次的訊息收掉) */
  move: (srcId: number, targetId: number) => boolean;
  /** 沒存成的訊息(沒有就是 null) */
  message: () => string | null;
  /** 訊息變了就通知(給 `useSyncExternalStore`) */
  subscribe: (notify: () => void) => () => void;
  /** 排隊的都做完(含收尾)時完成。測試用。 */
  idle: () => Promise<void>;
}

export const MESSAGES = {
  reloading: "排序沒存成,重新載入中",
  reloaded: "排序沒存成,已重新載入",
  stale: "排序沒存成,請重新整理頁面",
} as const;

interface Entry extends ListReorder {
  use: (qc: QueryClient, options: ReorderOptions) => void;
}

const lists = new Map<string, Entry>();

/** 這一份清單現在用的那一條佇列(沒有、或登入狀態換過了就開新的)。每次畫面 render 都呼叫,順便換上最新的設定。 */
export function listReorder(
  env: ReorderEnv,
  qc: QueryClient,
  options: ReorderOptions,
): ListReorder {
  const name = JSON.stringify(options.queryKey);
  let entry = lists.get(name);
  if (!entry || entry.session !== env.session()) {
    entry = create(env, qc, options);
    lists.set(name, entry);
  }
  entry.use(qc, options);
  return entry;
}

function create(env: ReorderEnv, firstQc: QueryClient, firstOptions: ReorderOptions): Entry {
  const session = env.session();
  let qc = firstQc;
  let options = firstOptions;
  let shown: unknown = null; // 最後換上畫面、收尾還沒開始的那一份
  let message: string | null = null;
  const listeners = new Set<() => void>();
  const alive = () => env.session() === session;

  function say(next: string | null) {
    if (message === next) return;
    message = next;
    listeners.forEach((notify) => notify());
  }

  /** 把清單從伺服器抓回來。真的抓到(快取被換成伺服器那一份)才回 true。 */
  async function reload(): Promise<boolean> {
    const before = qc.getQueryState(options.queryKey);
    // 快取裡沒有這一份:沒有東西是舊的,畫面回來時會從頭抓
    if (!before) return true;
    // refetchType "all":沒有畫面在用這一份(人切到別頁了)也去抓
    await qc.invalidateQueries({ queryKey: options.queryKey, refetchType: "all" });
    // 要看到這一份真的被換過才算:抓失敗、或設定成不重抓的清單,上面那一行不會換掉任何東西
    const after = qc.getQueryState(options.queryKey);
    return after !== undefined && after.dataUpdateCount > before.dataUpdateCount;
  }

  const queue = createReorderQueue<Sortable>({
    read: () => qc.getQueryData<Sortable[]>(options.queryKey) ?? [],
    show: (rows) => {
      const key = options.queryKey;
      // 先換畫面,再取消還在路上的重抓(不要回來把剛換好的順序蓋回去)。
      // 取消時快取會「回到重抓開始之前」:先寫進去,回到的就是這一份(測試「重抓還在路上又拖」在看這件事)
      qc.setQueryData(key, rows);
      shown = rows;
      void qc.cancelQueries({ queryKey: key });
    },
    save: (change: OrderChange) => {
      if (!alive()) throw new Error("登入狀態換過了,這一次不送");
      return env.save(options.path(change.id), { sort_order: change.sort_order });
    },
    settle: async (ok) => {
      // 登入狀態換過了:這一條已經作廢,不碰新登入狀態的快取與訊息
      if (!alive()) return;
      shown = null;
      // 這段時間人又拖了(畫面換成新的一份):上一輪的訊息就不講了 ——
      // 那一次沒存成的順序還在畫面上,會跟著新的這一次整份存進去
      const tell = (text: string) => {
        if (!ok && shown === null) say(text);
      };
      tell(MESSAGES.reloading);
      for (const queryKey of options.alsoRefresh ?? []) {
        void qc.invalidateQueries({ queryKey });
      }
      const reloaded = await reload();
      if (!reloaded) {
        // 沒有抓到:畫面上還是剛剛拖的順序,不能說「已重新載入」;丟錯 = 畫面那一份不能當成伺服器有的
        tell(MESSAGES.stale);
        throw new Error("清單沒有重抓到");
      }
      tell(MESSAGES.reloaded);
    },
  });

  return {
    session,
    move: (srcId, targetId) => {
      if (!alive()) return false;
      const moved = queue.move(srcId, targetId);
      if (moved) say(null); // 真的有動才收掉上一次的訊息(拖回同一列什麼都沒做,訊息留著)
      return moved;
    },
    message: () => message,
    subscribe: (notify) => {
      listeners.add(notify);
      return () => {
        listeners.delete(notify);
      };
    },
    idle: queue.idle,
    use: (nextQc, nextOptions) => {
      qc = nextQc;
      options = nextOptions;
    },
  };
}
