import { useEffect, useRef, useState } from "react";

import { api } from "./client";
import { ASK_LIMIT, chunks, toAsk, withAnswer, type CheckCache, type TakenInfo } from "@/lib/serialCheck";

const WAIT_MS = 400; // 打字停下來才問(一個字問一次沒有意義)
const RETRY_MS = 5000; // 沒問到答案:過一會兒自己再問一次

/**
 * 畫面上現在有的這些序號,哪幾個已經在系統裡(輸入的當下提醒用;規則在 lib/serialCheck.ts)。
 * 只問還沒查過的;`scope` 換了(開了一張新的單)就全部重來 —— 上一張單存進去的碼,現在就是「已經在系統裡」。
 * 問不到答案(斷線)不當成有問題也不當成沒問題:`failed` 是 true,過幾秒自己再問;存檔時伺服器照樣會擋。
 */
export function useSerialCheck(codes: string[], scope: string | number = ""): { cache: CheckCache; failed: boolean } {
  const [cache, setCache] = useState<CheckCache>({});
  const [failed, setFailed] = useState(false);
  const [retry, setRetry] = useState(0);
  const cacheRef = useRef<CheckCache>({});
  const scopeRef = useRef(scope);
  if (scopeRef.current !== scope) {
    scopeRef.current = scope;
    cacheRef.current = {};
  }
  const ask = toAsk(codes, cacheRef.current);
  const askKey = ask.join("\n");

  useEffect(() => {
    if (ask.length === 0) {
      setCache(cacheRef.current);
      return;
    }
    let dead = false;
    let again: ReturnType<typeof setTimeout> | undefined;
    const timer = setTimeout(async () => {
      try {
        let next = cacheRef.current;
        for (const part of chunks(ask, ASK_LIMIT)) {
          const got = await api<{ taken: TakenInfo[] }>("/serials/check/", {
            method: "POST",
            body: JSON.stringify({ codes: part }),
          });
          next = withAnswer(next, part, got.taken);
        }
        if (dead) return;
        cacheRef.current = next;
        setCache(next);
        setFailed(false);
      } catch {
        if (dead) return;
        setFailed(true);
        again = setTimeout(() => setRetry((n) => n + 1), RETRY_MS);
      }
    }, WAIT_MS);
    return () => {
      dead = true;
      clearTimeout(timer);
      if (again) clearTimeout(again);
    };
    // 只看「要問哪些碼」有沒有換(ask 每次都是新的陣列)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [askKey, scope, retry]);

  return { cache, failed };
}
