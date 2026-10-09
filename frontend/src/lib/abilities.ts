// 員工帳號的權限:每個店員帳號一項一項勾(owner 2026-10-10)。
// 清單與判斷只有伺服器那一份(backend/apps/tenants/abilities.py),**真正擋的是伺服器**;
// 這裡只決定按鈕要不要出現(不讓人白按),以及員工帳號頁怎麼排。
export type AbilityKey =
  "void_sales" | "sales_return" | "void_purchase" | "void_others";

export interface AbilityInfo {
  key: string;
  label: string;
  group: string;
  note: string;
}

/**
 * 這個帳號能不能做這一項。登入資料裡沒有這一格(還沒載入、伺服器比較舊)當成可以:
 * 按鈕照舊出現,真的不行伺服器會擋並講原因。只有明講「不可以」才收起來。
 */
export function can(
  user: { abilities?: Record<string, boolean> } | null | undefined,
  key: AbilityKey,
): boolean {
  return user?.abilities?.[key] !== false;
}

/** 員工帳號頁:照分類排,分類與項目都照伺服器給的順序。 */
export function groupAbilities(
  list: AbilityInfo[],
): { group: string; items: AbilityInfo[] }[] {
  const groups: { group: string; items: AbilityInfo[] }[] = [];
  for (const item of list) {
    const last = groups.find((g) => g.group === item.group);
    if (last) last.items.push(item);
    else groups.push({ group: item.group, items: [item] });
  }
  return groups;
}

/** 勾下去的當下畫面先換(存好之後以伺服器回的為準;沒存成要換回來)。 */
export function withAbility<
  T extends { id: number; abilities: Record<string, boolean> },
>(accounts: T[], id: number, key: string, allowed: boolean): T[] {
  return accounts.map((a) =>
    a.id === id ? { ...a, abilities: { ...a.abilities, [key]: allowed } } : a,
  );
}

/**
 * 員工帳號頁的存檔閘門:**同一個帳號的同一項,上一次還沒存完就不收下一次。**
 * 勾一下就送一個請求;同一格連點兩下會有兩個請求在路上,誰先到伺服器不一定 ——
 * 比較早按的那一次晚到的話,最後留下的就跟人最後按的相反(複審抓到的)。
 * 不同的格子互不影響,可以同時存。
 */
export function createSaveGate() {
  const busy = new Set<string>();
  const listeners = new Set<() => void>();
  let version = 0;
  const slot = (id: number, key: string) => `${id}:${key}`;
  const changed = () => {
    version += 1;
    for (const fn of [...listeners]) fn();
  };
  return {
    /** 這一格是不是還在存(畫面拿來把那一格停用) */
    busy: (id: number, key: string) => busy.has(slot(id, key)),
    /** 全部都存完了(這時候才重抓,不拿半路的結果蓋掉還在存的那幾格) */
    idle: () => busy.size === 0,
    /** 哪幾格在存變了就通知(畫面靠它重畫:存完的那一格要放開) */
    subscribe(fn: () => void) {
      listeners.add(fn);
      return () => {
        listeners.delete(fn);
      };
    },
    version: () => version,
    /** 送出;這一格還在存就不送、回 false。送出去的不管成功失敗,結束時放開這一格。 */
    async run(
      id: number,
      key: string,
      send: () => Promise<unknown>,
    ): Promise<boolean> {
      const k = slot(id, key);
      if (busy.has(k)) return false;
      busy.add(k);
      changed();
      try {
        await send();
      } finally {
        busy.delete(k);
        changed();
      }
      return true;
    },
  };
}

/**
 * 員工帳號頁用的那一個閘門:**放在這裡、不跟著畫面走。**
 * 存到一半切到別頁再回來,畫面是重新建的;閘門如果跟著畫面重建,舊的請求還在路上就又能再送一次
 * (複審第二輪抓到的)。放在模組裡,回來的時候那一格還是鎖著,等原本那個請求結束才放開。
 */
export const staffSaveGate = createSaveGate();
