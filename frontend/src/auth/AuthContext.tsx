import { type AbilityKey, can } from "@/lib/abilities";
import { attachIdleLogout } from "@/lib/idleLogout";
import { attachSignInCheck } from "@/lib/signInPlace";
import { useQueryClient } from "@tanstack/react-query";
import {
  createContext,
  ReactNode,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";

import { api, authEvents, deviceId, getToken, setToken } from "@/api/client";
import type { CurrentUser, LoginResponse } from "@/api/types";

interface AuthState {
  user: CurrentUser | null;
  loading: boolean;
  /** 被登出的原因(帳號在別處登入);登入頁顯示,登入成功就收掉 */
  notice: string | null;
  login: (username: string, password: string) => Promise<CurrentUser>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
}

const AuthCtx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    const token = getToken();
    if (!token) {
      setUser(null);
      setLoading(false);
      return;
    }
    try {
      const me = await api<CurrentUser>("/auth/me/");
      setUser(me);
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // client.ts 收到 401 會 emit 'unauthorized' → 這裡清空 user 觸發路由 guard 跳 login
  // 帳號在別處登入的那一句留著給登入頁(之後沒帶 token 的 401 不會把它蓋掉;登入成功才收)
  useEffect(() => {
    function onUnauth(e: Event) {
      setUser(null);
      const said = (e as CustomEvent<{ notice?: string | null }>).detail?.notice;
      if (said) setNotice(said);
    }
    authEvents.addEventListener("unauthorized", onUnauth);
    return () => authEvents.removeEventListener("unauthorized", onUnauth);
  }, []);

  // 連續 2 小時沒有操作自動登出(門檻與怎麼算在 lib/idleLogout.ts):登入後開始看,
  // 滑鼠 / 鍵盤 / 觸控 / 捲動 / 點擊都重新算;超過就把 token 清掉並跳回登入頁。
  useEffect(() => {
    if (!user) return; // 未登入不需要看
    return attachIdleLogout(window, () => {
      // 安靜地 logout(不呼叫後端;前端 state 一定要清)
      setToken(null);
      setUser(null);
      qc.clear();
    });
  }, [user, qc]);

  // 同一個帳號在別處登入,這一台的鑰匙就作廢了:畫面開著也要自己跳回登入頁,不等人按(lib/signInPlace.ts)。
  // 只是問一下,回來的資料不用;401 由 client.ts 照常處理。
  useEffect(() => {
    if (!user) return;
    return attachSignInCheck(window, document, () => {
      api("/auth/me/").catch(() => {});
    });
  }, [user]);

  const login = useCallback(
    async (username: string, password: string) => {
      // 換帳號前先把上一位的資料清乾淨,避免新帳號看到舊資料
      qc.clear();
      const res = await api<LoginResponse>("/auth/login/", {
        method: "POST",
        // 這個瀏覽器的記號:同一個瀏覽器再登入拿回同一把,換位置登入舊的作廢(backend/apps/tenants/sign_in.py)
        body: JSON.stringify({ username, password, device: deviceId() }),
      });
      setToken(res.token);
      setNotice(null);
      setUser(res.user);
      return res.user;
    },
    [qc],
  );

  const logout = useCallback(async () => {
    try {
      await api("/auth/logout/", { method: "POST" });
    } catch {
      // 即使後端 token 已壞,前端也要清乾淨
    }
    setToken(null);
    setUser(null);
    setNotice(null);
    qc.clear();
  }, [qc]);

  return (
    <AuthCtx.Provider value={{ user, loading, notice, login, logout, refresh }}>
      {children}
    </AuthCtx.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthCtx);
  if (!ctx) throw new Error("useAuth 必須包在 <AuthProvider> 內");
  return ctx;
}

export function useCurrentUser(): CurrentUser | null {
  return useAuth().user;
}

/** 這個帳號能不能做這一項(員工帳號的權限)。只決定按鈕要不要出現;真正擋的是伺服器。 */
export function useCan(key: AbilityKey): boolean {
  return can(useAuth().user, key);
}

/**
 * 取當前登入帳號的「預設門市」+ 是否被鎖死。
 * 鎖倉帳號(tenant_user 且 is_warehouse_locked=true):表單應該把 warehouse 鎖死、
 * 不可改;管理員角色則維持 ComboBox 自由選擇。
 */
export function useDefaultWarehouse(): {
  id: number | null;
  name: string;
  locked: boolean;
} {
  const user = useCurrentUser();
  if (!user?.profile?.default_warehouse_id) {
    return { id: null, name: "", locked: false };
  }
  return {
    id: user.profile.default_warehouse_id,
    name: user.profile.default_warehouse_name ?? "",
    locked: user.profile.is_warehouse_locked,
  };
}

/**
 * 取當前登入帳號綁定的業務員(SalesPerson)。
 * 用來把「經手人 / 業務員」欄位自動預設成當前登入者。
 */
export function useDefaultHandledBy(): {
  id: number | null;
  name: string;
  code: string;
} {
  const user = useCurrentUser();
  if (!user?.sales_person) return { id: null, name: "", code: "" };
  return {
    id: user.sales_person.id,
    name: user.sales_person.name,
    code: user.sales_person.code,
  };
}
