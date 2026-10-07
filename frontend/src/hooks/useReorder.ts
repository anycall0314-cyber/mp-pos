import { useQueryClient } from "@tanstack/react-query";
import { useSyncExternalStore } from "react";

import { api, sessionId } from "@/api/client";
import { listReorder, type ReorderEnv, type ReorderOptions } from "@/lib/reorderStore";

const ENV: ReorderEnv = {
  save: (path, body) => api(path, { method: "PATCH", body: JSON.stringify(body) }),
  session: sessionId,
};

/**
 * 拖拉排序:放開的當下畫面就換、背景存、全部存完才重抓一次。
 * 規則在 `lib/reorder.ts`(排隊、哪幾列要存)與 `lib/reorderStore.ts`(接快取、切頁、換登入狀態)。
 *
 * - `move(srcId, targetId)`:在 `onDrop` 裡呼叫;有東西要動回 true。
 * - `error`:沒存成的訊息(沒有就是 null),放在清單上面;切到別頁再回來還在,下一次拖成功才收掉。
 *
 * 清單的每一列要有 `id` / `sort_order` / `code`(`lib/reorder.ts` 的 `Sortable`)。
 */
export function useReorder(options: ReorderOptions) {
  const qc = useQueryClient();
  const list = listReorder(ENV, qc, options);
  const error = useSyncExternalStore(list.subscribe, list.message);
  return { move: list.move, error };
}
