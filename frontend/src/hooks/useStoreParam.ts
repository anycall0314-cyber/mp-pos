import { useEffect } from "react";
import { useSearchParams } from "react-router-dom";

import { useWarehouses } from "@/api/hooks";
import { useDefaultWarehouse } from "@/auth/AuthContext";
import { STORE_PARAM, storeCheck, storeIdFrom } from "@/lib/storeParam";

/**
 * 網址上的 `warehouse=門市編號`(首頁帶過來的;全站檢視 R06,規則在 lib/storeParam.ts)。
 * 回傳那一家的編號與名字;`clear()` 把網址上的拿掉(「清除條件」)。沒有這一家 / 停用的 / 鎖門市帳號寫別家的自己清掉。
 */
export function useStoreParam({ lockable = true }: { lockable?: boolean } = {}) {
  const [params, setParams] = useSearchParams();
  const warehouses = useWarehouses();
  // 照帳號鎖店的頁:鎖在門市的帳號網址寫別家當沒帶;序號查詢這種不鎖店的頁傳 lockable: false
  const own = useDefaultWarehouse();
  const lockedTo = lockable && own.locked ? own.id : null;
  const checked = storeCheck(storeIdFrom(params.get(STORE_PARAM)), warehouses.data, lockedTo);
  function clear() {
    if (!params.has(STORE_PARAM)) return;
    const next = new URLSearchParams(params);
    next.delete(STORE_PARAM);
    setParams(next, { replace: true });
  }
  useEffect(() => {
    if (checked.state === "gone") clear();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [checked.state]);
  return { id: checked.id, name: checked.name, clear };
}
