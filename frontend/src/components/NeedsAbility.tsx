import type { ReactNode } from "react";

import { useAuth } from "@/auth/AuthContext";
import { can, type AbilityKey } from "@/lib/abilities";

/**
 * 整頁都是「做」某件事的頁面(進貨開單、進貨匯入、營業日報):這個帳號沒有那一項權限就不顯示內容,講一句話。
 * 入口本來就會收起來(導覽、按鈕),這是給直接打網址、或從書籤進來的人看的。真正擋的是伺服器。
 * `ability` 給好幾項 = **有其中一項就可以進來**(跟導覽的 `needs` 同一個意思:全部關掉才收起來)。
 */
export function NeedsAbility({
  ability,
  doing,
  children,
}: {
  ability: AbilityKey | AbilityKey[];
  /** 「這個帳號不能…」後面接的字,例:進貨入庫 */
  doing: string;
  children: ReactNode;
}) {
  const user = useAuth().user;
  if ([ability].flat().some((key) => can(user, key))) return <>{children}</>;
  return (
    <div className="page">
      <div className="md-empty">這個帳號不能{doing}</div>
    </div>
  );
}
