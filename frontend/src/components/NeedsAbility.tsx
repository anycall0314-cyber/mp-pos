import type { ReactNode } from "react";

import { useCan } from "@/auth/AuthContext";
import type { AbilityKey } from "@/lib/abilities";

/**
 * 整頁都是「做」某件事的頁面(進貨開單、進貨匯入、營業日報):這個帳號沒有那一項權限就不顯示內容,講一句話。
 * 入口本來就會收起來(導覽、按鈕),這是給直接打網址、或從書籤進來的人看的。真正擋的是伺服器。
 */
export function NeedsAbility({
  ability,
  doing,
  children,
}: {
  ability: AbilityKey;
  /** 「這個帳號不能…」後面接的字,例:進貨入庫 */
  doing: string;
  children: ReactNode;
}) {
  if (useCan(ability)) return <>{children}</>;
  return (
    <div className="page">
      <div className="md-empty">這個帳號不能{doing}</div>
    </div>
  );
}
